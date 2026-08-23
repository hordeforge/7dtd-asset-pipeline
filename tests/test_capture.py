from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
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

    def test_every_backend_builds_an_argv_ending_in_its_output(self) -> None:
        for backend in BACKENDS:
            with self.subTest(backend=backend.name):
                argv = backend.command(Path("/tmp/shot.png"))
                self.assertEqual(argv[0], backend.name)
                self.assertEqual(argv[-1], "/tmp/shot.png")

    def test_the_capability_probes_the_same_tools(self) -> None:
        spec = next(item for item in REGISTRY if item.name == "desktop-capture")
        self.assertEqual(set(spec.probe.split()), {b.name for b in BACKENDS})


class SelectionTests(unittest.TestCase):
    """Backend selection without any tool installed or display attached."""

    def test_a_headless_host_is_refused_with_the_reason(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no desktop session"):
            _require_backend({})

    def test_a_session_without_tools_names_what_to_install(self) -> None:
        with mock.patch("sevendtd_asset_pipeline.capture.shutil.which", return_value=None):
            with self.assertRaisesRegex(PipelineError, "no screenshot tool for this x11 session"):
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
        self.assertTrue((self.evidence / "held-nuke.png").is_file())
        recorded = read_manifest(self.evidence)[0]
        self.assertEqual(entry.sha256, recorded["sha256"])

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


if __name__ == "__main__":
    unittest.main()
