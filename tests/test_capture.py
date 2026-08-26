from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import unittest
from importlib.util import find_spec
from pathlib import Path
from typing import Any, cast
from unittest import mock

from sevendtd_asset_pipeline.capabilities import REGISTRY
from sevendtd_asset_pipeline.capture import (
    BACKENDS,
    MANIFEST_NAME,
    _require_backend,
    available_backends,
    capture,
    read_manifest,
    record_existing,
    session_type,
)
from sevendtd_asset_pipeline.errors import PipelineError


class SessionTests(unittest.TestCase):
    def test_the_session_type_decides_the_backends(self) -> None:
        """An X11 grabber under Wayland returns a black frame and exits zero, so
        the session selects candidates rather than merely ordering them."""
        self.assertEqual(session_type({"XDG_SESSION_TYPE": "wayland"}), "wayland")
        self.assertEqual(session_type({"XDG_SESSION_TYPE": "x11"}), "x11")
        self.assertEqual(session_type({"WAYLAND_DISPLAY": "wayland-0"}), "wayland")
        self.assertEqual(session_type({"DISPLAY": ":0"}), "x11")
        self.assertEqual(session_type({}), "none")

    def test_a_headless_host_offers_no_backend(self) -> None:
        self.assertEqual(available_backends({}), [])

    def test_a_wayland_session_never_offers_an_x11_only_backend(self) -> None:
        x11_only = {b.name for b in BACKENDS if b.sessions == ("x11",)}
        offered = {b.name for b in available_backends({"XDG_SESSION_TYPE": "wayland"})}
        self.assertEqual(offered & x11_only, set())

    def test_every_backend_invokes_the_tool_its_name_probes(self) -> None:
        """`available_backends` probes `shutil.which(backend.name)`, so the
        fixed argv must run that same binary, not a delegate under another name."""
        for backend in BACKENDS:
            with self.subTest(backend=backend.name):
                self.assertTrue(backend.argv)
                self.assertEqual(backend.argv[0], backend.name)

    def test_the_capability_probes_the_same_tools(self) -> None:
        spec = next(item for item in REGISTRY if item.name == "desktop-capture")
        self.assertEqual(set(spec.probe.split()), {b.name for b in BACKENDS})


class SelectionTests(unittest.TestCase):
    """Backend selection without any tool installed or display attached."""

    def test_a_headless_host_is_refused_with_the_reason(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no desktop session"):
            _require_backend({})

    def test_a_session_without_tools_names_what_to_install(self) -> None:
        with (
            mock.patch("sevendtd_asset_pipeline.capture.shutil.which", return_value=None),
            self.assertRaisesRegex(PipelineError, "no screenshot tool for this x11 session"),
        ):
            _require_backend({"DISPLAY": ":0"})

    def test_selection_takes_the_first_installed_backend_for_the_session(self) -> None:
        installed = {"grim", "scrot"}

        def which(name: str) -> str | None:
            return "/usr/bin/" + name if name in installed else None

        with mock.patch("sevendtd_asset_pipeline.capture.shutil.which", side_effect=which):
            self.assertEqual("grim", _require_backend({"XDG_SESSION_TYPE": "wayland"}).name)
            self.assertEqual("scrot", _require_backend({"DISPLAY": ":0"}).name)


class CaptureTests(unittest.TestCase):
    """The run path, driven by stub executables instead of a real desktop."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.tools = root / "tools"
        self.tools.mkdir()
        self.evidence = root / "acceptance"
        self._patcher = mock.patch.dict(
            os.environ, {"PATH": f"{self.tools}:{os.environ.get('PATH', '')}"}
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def _tool(self, name: str, body: str) -> None:
        script = self.tools / name
        script.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        script.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    def test_a_successful_grab_is_recorded_with_its_digest(self) -> None:
        self._tool("grim", 'printf "fake png data" > "$1"')
        entry = capture(
            "held-nuke",
            observable="upright in the hand",
            root=self.evidence,
            env={"XDG_SESSION_TYPE": "wayland"},
        )
        self.assertEqual("grim", entry.backend)
        self.assertEqual("wayland", entry.session)
        self.assertIsNone(entry.verdict)
        self.assertEqual(len(b"fake png data"), entry.bytes)
        frame = self.evidence / "held-nuke.png"
        self.assertTrue(frame.is_file())
        recorded = read_manifest(self.evidence)[0]
        # The digest must describe the bytes on disk, not merely agree with
        # the in-memory entry: a grabber that staged corrupt bytes would
        # otherwise pass by round-tripping its own value back.
        self.assertEqual(hashlib.sha256(frame.read_bytes()).hexdigest(), recorded["sha256"])

    def test_a_tool_that_exits_zero_without_an_image_is_refused(self) -> None:
        self._tool("grim", "exit 0")
        with self.assertRaisesRegex(PipelineError, "wrote no image"):
            capture(
                "empty",
                root=self.evidence,
                env={"XDG_SESSION_TYPE": "wayland"},
            )

    def test_a_failing_tool_carries_its_last_error_line(self) -> None:
        self._tool("grim", 'echo "no compositor" >&2\necho "detail line" >&2\nexit 3')
        with self.assertRaisesRegex(PipelineError, r"grim failed \(3\).*detail line"):
            capture("broken", root=self.evidence, env={"XDG_SESSION_TYPE": "wayland"})

    def test_an_empty_label_is_rejected_before_anything_runs(self) -> None:
        with self.assertRaisesRegex(PipelineError, "needs a label"):
            capture("  ", root=self.evidence, env={})

    def test_a_traversal_label_cannot_escape_the_evidence_root(self) -> None:
        """A label is untrusted CLI/API input at a filesystem boundary.

        `../../secrets` must become a flattened name inside the evidence
        directory, never a path outside it; the same holds for an absolute
        label, which would otherwise write over whatever the stem names.
        """
        self._tool("grim", 'printf "fake png data" > "$1"')
        for hostile in ("../../secrets", "/etc/hosts", "a/b"):
            with self.subTest(label=hostile):
                entry = capture(hostile, root=self.evidence, env={"XDG_SESSION_TYPE": "wayland"})
                written = self.evidence / entry.file
                self.assertEqual(self.evidence.resolve(), written.parent.resolve())
                self.assertNotIn("/", written.name)
                self.assertTrue(written.is_file())

    def test_a_failed_grab_keeps_the_previous_frame_and_no_temporary(self) -> None:
        """The grabber aims at a staged name, so a failed shot cannot take the
        previously recorded frame down with it or leave a partial one behind."""
        source = self.evidence / "elsewhere.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        record_existing(source, "held-nuke", "before", self.evidence)
        before = (self.evidence / "held-nuke.png").read_bytes()
        self._tool("grim", "exit 3")
        with self.assertRaises(PipelineError):
            capture(
                "held-nuke",
                root=self.evidence,
                env={"XDG_SESSION_TYPE": "wayland"},
            )
        self.assertEqual(before, (self.evidence / "held-nuke.png").read_bytes())
        self.assertEqual(
            [],
            [path.name for path in self.evidence.iterdir() if ".tmp." in path.name],
        )


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / "frame.png"
        self.image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        self.evidence = self.root / "acceptance"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_recorded_frame_carries_its_observable_and_no_verdict(self) -> None:
        entry = record_existing(self.image, "held-nuke", "upright in the hand", self.evidence)
        self.assertEqual(entry.observable, "upright in the hand")
        self.assertIsNone(entry.verdict)
        self.assertEqual(entry.bytes, self.image.stat().st_size)
        self.assertTrue((self.evidence / "held-nuke.png").is_file())

    def test_a_frame_without_an_observable_says_so(self) -> None:
        entry = record_existing(self.image, "dropped-nuke", "", self.evidence)
        self.assertTrue(entry.notes)
        self.assertIn("proves nothing", entry.notes[0])

    def test_recording_the_same_label_twice_replaces_rather_than_duplicates(self) -> None:
        record_existing(self.image, "held-nuke", "first", self.evidence)
        record_existing(self.image, "held-nuke", "second", self.evidence)
        entries = read_manifest(self.evidence)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["observable"], "second")

    def test_the_manifest_accumulates_across_captures(self) -> None:
        record_existing(self.image, "held-nuke", "a", self.evidence)
        record_existing(self.image, "dropped-nuke", "b", self.evidence)
        labels = [entry["label"] for entry in read_manifest(self.evidence)]
        self.assertEqual(labels, ["held-nuke", "dropped-nuke"])

    def test_the_manifest_is_json_and_serializable(self) -> None:
        record_existing(self.image, "held-nuke", "a", self.evidence)
        text = (self.evidence / MANIFEST_NAME).read_text(encoding="utf-8")
        self.assertIsInstance(json.loads(text), list)

    def test_a_missing_manifest_is_empty_not_an_error(self) -> None:
        self.assertEqual(read_manifest(self.root / "nothing-here"), [])

    def test_a_corrupt_manifest_is_named_rather_than_silently_replaced(self) -> None:
        self.evidence.mkdir(parents=True)
        (self.evidence / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        with self.assertRaises(PipelineError):
            read_manifest(self.evidence)

    def test_a_manifest_that_is_not_a_list_is_refused(self) -> None:
        self.evidence.mkdir(parents=True)
        (self.evidence / MANIFEST_NAME).write_text('{"label": "x"}', encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "not a list"):
            read_manifest(self.evidence)

    def test_recording_a_missing_image_fails(self) -> None:
        with self.assertRaises(PipelineError):
            record_existing(self.root / "absent.png", "x", "", self.evidence)

    def test_a_failed_manifest_write_leaves_no_temporary_behind(self) -> None:
        """An interrupted publish must not strand its half-written body as state.

        The manifest's temporary file carries this process's pid plus a random
        suffix and is unlinked on every exit path, like every other atomic
        writer here; a stray fixed-name `.tmp` would survive the run forever.
        The staged frame is cleaned up with it: nothing recorded means nothing
        published.
        """
        self.evidence.mkdir(parents=True)

        def exploding(self: Path, target: object) -> Path:
            raise OSError(28, "No space left on device")

        with mock.patch.object(Path, "replace", exploding), self.assertRaises(OSError):
            record_existing(self.image, "held-nuke", "", self.evidence)
        self.assertEqual(
            [],
            [path.name for path in self.evidence.iterdir() if ".tmp." in path.name],
        )

    def test_concurrent_recordings_keep_every_entry(self) -> None:
        """Two capturers publishing together must not lose one sign-off.

        Recording is a read-modify-write of one shared manifest, and this host
        runs several agent sessions at once, so the sequence holds an exclusive
        flock: each of these concurrent recordings must survive in full.
        """
        if find_spec("fcntl") is None:
            self.skipTest("flock (fcntl) does not exist on this platform")
        labels = [f"held-{index}" for index in range(8)]
        failures: list[BaseException] = []

        def record(name: str) -> None:
            try:
                record_existing(self.image, name, "", self.evidence)
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                failures.append(exc)

        threads = [threading.Thread(target=record, args=(label,)) for label in labels]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual([], failures)
        self.assertEqual(
            sorted(labels),
            sorted(entry["label"] for entry in read_manifest(self.evidence)),
        )

    def test_a_recording_waits_for_a_holder_of_the_manifest_lock(self) -> None:
        """The flock excludes, rather than decorates: a holder delays a recorder."""
        if find_spec("fcntl") is None:
            self.skipTest("flock (fcntl) does not exist on this platform")
        import fcntl

        self.evidence.mkdir(parents=True)
        sidecar = open(self.evidence / f"{MANIFEST_NAME}.flock", "a+", encoding="utf-8")  # noqa: SIM115
        try:
            fcntl.flock(sidecar.fileno(), fcntl.LOCK_EX)
            done = threading.Event()

            def record() -> None:
                record_existing(self.image, "held-nuke", "", self.evidence)
                done.set()

            worker = threading.Thread(target=record)
            worker.start()
            self.assertFalse(done.wait(timeout=1.0), "recorded while another held the lock")
            self.assertFalse((self.evidence / MANIFEST_NAME).exists())
            fcntl.flock(sidecar.fileno(), fcntl.LOCK_UN)
            worker.join(timeout=30)
            self.assertTrue(done.is_set())
        finally:
            sidecar.close()
        self.assertEqual(["held-nuke"], [entry["label"] for entry in read_manifest(self.evidence)])

    def test_recording_still_works_where_flock_does_not_exist(self) -> None:
        """A native Windows client degrades to the unsynchronized write."""
        with (
            mock.patch("sevendtd_asset_pipeline.capture.find_spec", return_value=None),
        ):
            entry = record_existing(self.image, "held-nuke", "", self.evidence)
        self.assertEqual("held-nuke", entry.label)
        self.assertEqual(["held-nuke"], [e["label"] for e in read_manifest(self.evidence)])


class ClipAdoptionTests(unittest.TestCase):
    """`client capture --clip`: adopting an external clip directory one level up."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.capture_root = self.root / "acceptance"
        self.source = self.root / "capture" / "demo-20260825" / "thing"
        self.source.mkdir(parents=True, exist_ok=True)
        for index in range(4):
            (self.source / f"frame-{index:04d}.png").write_bytes(bytes([index] * 4))
        (self.source / "thing.mp4").write_bytes(b"muxed")
        (self.source / "client.log").write_text("clip complete demo/thing frames=4\n")

    def test_adoption_copies_hashes_and_records_every_file(self) -> None:
        from sevendtd_asset_pipeline.capture import record_existing_clip

        entry = record_existing_clip(
            self.source,
            "thing",
            "grip reads at the right thickness through a full turn",
            self.capture_root,
        )
        self.assertEqual("adopted-clip", entry.backend)
        self.assertEqual("thing", entry.directory)
        names = {item.name for item in entry.files}
        self.assertIn("frame-0000.png", names)
        self.assertIn("thing.mp4", names)
        self.assertIn("client.log", names)
        for item in entry.files:
            source = self.capture_root / "thing" / item.name
            self.assertEqual(
                hashlib.sha256(source.read_bytes()).hexdigest(),
                item.sha256,
                "adoption must hash the copied bytes, not the path",
            )
        manifest = read_manifest(self.capture_root)
        self.assertEqual(1, len(manifest))
        self.assertEqual("thing", manifest[0]["directory"])

    def test_re_adopting_a_label_replaces_the_earlier_entry(self) -> None:
        from sevendtd_asset_pipeline.capture import record_existing_clip

        record_existing_clip(self.source, "thing", "", self.capture_root)
        (self.source / "frame-0004.png").write_bytes(b"extra")
        record_existing_clip(self.source, "thing", "", self.capture_root)
        manifest = read_manifest(self.capture_root)
        self.assertEqual(1, len(manifest))
        self.assertIn(
            "frame-0004.png",
            {item["name"] for item in cast("list[dict[str, Any]]", manifest[0]["files"])},
        )

    def test_a_directory_without_frames_or_video_is_refused(self) -> None:
        from sevendtd_asset_pipeline.capture import record_existing_clip

        empty = self.root / "empty"
        empty.mkdir()
        (empty / "notes.txt").write_text("not a clip")
        with self.assertRaisesRegex(PipelineError, "does not look like a clip"):
            record_existing_clip(empty, "thing", "", self.capture_root)

    def test_adopting_in_place_records_without_copying(self) -> None:
        from sevendtd_asset_pipeline.capture import record_existing_clip

        adopted = self.capture_root / "thing"
        record_existing_clip(self.source, "thing", "", self.capture_root)
        before = {
            item["name"]
            for item in cast("list[dict[str, Any]]", read_manifest(self.capture_root)[0]["files"])
        }
        # Re-adopt the adopted directory itself: no copy, no wipe, just re-record.
        entry = record_existing_clip(adopted, "thing", "", self.capture_root)
        self.assertEqual(before, {item.name for item in entry.files})


if __name__ == "__main__":
    unittest.main()
