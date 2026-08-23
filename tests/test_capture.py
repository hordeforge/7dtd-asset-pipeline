from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.capabilities import REGISTRY
from sevendtd_asset_pipeline.capture import (
    BACKENDS,
    MANIFEST_NAME,
    available_backends,
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

    def test_recording_a_missing_image_fails(self) -> None:
        with self.assertRaises(PipelineError):
            record_existing(self.root / "absent.png", "x", "", self.evidence)


if __name__ == "__main__":
    unittest.main()
