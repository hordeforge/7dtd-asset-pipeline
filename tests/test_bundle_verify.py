"""The verify-bundle classifier: what turns an editor run into pass/fail evidence.

`shamway verify-bundle` is the strongest offline evidence a synthesized bundle
can carry, and `_classify` is what decides its verdict. A bug there does not
lose a check, it invents a pass: a log whose marker lines stop matching must
never read as OK, and an exit-zero run that loaded nothing must be named. No
Unity editor exists in the unit suite, so the editor boundary is driven by a
stub executable — everything either side of it (the refusals, the throwaway
project, the classification of every log shape the verifier prints) is pinned.
"""

from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.bundle_verify import (
    EDITOR_FOLDER,
    VERIFIER_SCRIPT,
    _classify,
    _scratch_project,
    verify_with_editor,
)
from sevendtd_asset_pipeline.errors import PipelineError

REVISION = "2022.3.62f2"


class BundleCase(unittest.TestCase):
    """A temp home per test, so each owns its log and editor files."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_log(self, body: str) -> Path:
        log = self.root / "verify.log"
        log.write_text(body, encoding="utf-8")
        return log


class ClassifyTests(BundleCase):
    def test_a_log_of_loaded_assets_reads_ok(self) -> None:
        log = self.write_log(
            "Unity noise the batch editor always emits\n"
            "VERIFY-ASSET: mymodnote -> TextAsset named 'myModNote'\n"
            "VERIFY-TEXT: length 5\n"
            "[subsystem] more noise\n"
            "VERIFY-ASSET: mymodpanel -> Texture2D named 'myModPanel'\n"
            "VERIFY-TEX: 4x2 RGBA32\n"
        )
        report = _classify(Path("b.unity3d"), log, 0)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual([], report.problems)
        self.assertEqual(
            [("mymodnote", "TextAsset", "myModNote"), ("mymodpanel", "Texture2D", "myModPanel")],
            [(asset.key, asset.type, asset.name) for asset in report.assets],
        )
        self.assertEqual("length 5", report.assets[0].detail)
        self.assertEqual("4x2 RGBA32", report.assets[1].detail)

    def test_verify_fail_lines_are_problems_even_at_exit_zero(self) -> None:
        """The engine's own failure line decides, not the process exit code."""
        log = self.write_log(
            "VERIFY-ASSET: mymodnote -> TextAsset named 'myModNote'\n"
            "VERIFY-FAIL: Texture2D 'mymodpanel' did not load\n"
        )
        report = _classify(Path("b.unity3d"), log, 0)
        self.assertFalse(report.ok)
        self.assertIn("did not load", report.problems[0])

    def test_a_nonzero_exit_without_fail_lines_is_named_not_passed(self) -> None:
        """A crash before any verdict must not leave an empty, ok-looking report."""
        log = self.write_log("aborted early\n")
        report = _classify(Path("b.unity3d"), log, 3)
        self.assertFalse(report.ok)
        self.assertIn("exited 3", report.problems[0])
        self.assertIn("verify.log", report.problems[0])

    def test_an_exit_zero_run_that_loaded_nothing_is_named(self) -> None:
        """A bundle whose every member went unread would otherwise read as a pass."""
        report = _classify(Path("b.unity3d"), self.write_log("all quiet\n"), 0)
        self.assertFalse(report.ok)
        self.assertIn("no assets", report.problems[0])

    def test_a_detail_line_above_every_asset_is_ignored_not_fatal(self) -> None:
        log = self.write_log(
            "VERIFY-TEX: orphan detail\nVERIFY-ASSET: mymodnote -> TextAsset named 'myModNote'\n"
        )
        report = _classify(Path("b.unity3d"), log, 0)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual("", report.assets[0].detail)

    def test_an_unreadable_log_is_a_pipeline_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "cannot read the verifier log"):
            _classify(Path("b.unity3d"), self.root / "absent.log", 0)

    def test_the_report_round_trips_through_json(self) -> None:
        report = _classify(
            Path("b.unity3d"),
            self.write_log("VERIFY-ASSET: k -> TextAsset named 'k'\n"),
            0,
        )
        self.assertEqual(report.as_dict(), json.loads(json.dumps(report.as_dict())))


class EditorRefusalTests(BundleCase):
    def test_no_editor_is_a_pipeline_error_with_the_next_step(self) -> None:
        bundle = self.root / "b.unity3d"
        bundle.write_bytes(b"UnityFS")
        with self.assertRaisesRegex(PipelineError, "UNITY_EDITOR"):
            verify_with_editor(bundle, None, REVISION, self.root)

    def test_an_editor_path_that_is_not_a_file_is_refused_before_anything_runs(self) -> None:
        bundle = self.root / "b.unity3d"
        bundle.write_bytes(b"UnityFS")
        absent = self.root / "not-an-editor"
        with self.assertRaisesRegex(PipelineError, "not executable"):
            verify_with_editor(bundle, absent, REVISION, self.root)
        self.assertFalse((self.root / "verify-project").exists(), "no project may be built")


class StubEditorRunTests(BundleCase):
    """The full path with a shell stub standing in for the editor binary."""

    def _editor(self, body: str) -> Path:
        editor = self.root / "stub-editor"
        editor.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        editor.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        return editor

    def test_a_successful_stub_run_classifies_its_own_log(self) -> None:
        # The stub answers the same argv the real editor gets and writes the
        # log where -logFile points, so wiring mistakes cannot hide behind a
        # mocked subprocess.run.
        self._editor(
            'for pair in "$@"; do case "$prev" in -logFile) '
            'printf "%s\\n" "VERIFY-ASSET: mymodnote -> TextAsset named \'myModNote\'" > "$pair";; '
            "esac; prev=$pair; done; exit 0"
        )
        bundle = self.root / "b.unity3d"
        bundle.write_bytes(b"UnityFS")
        report = verify_with_editor(bundle, self.root / "stub-editor", REVISION, self.root / "work")
        self.assertTrue(report.ok, report.problems)
        self.assertEqual([("mymodnote", "TextAsset")], [(a.key, a.type) for a in report.assets])

    def test_a_timeout_is_a_pipeline_error_naming_the_partial_log(self) -> None:
        self._editor("# never reached")
        bundle = self.root / "b.unity3d"
        bundle.write_bytes(b"UnityFS")
        with (
            mock.patch(
                "sevendtd_asset_pipeline.bundle_verify.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="editor", timeout=900),
            ),
            self.assertRaisesRegex(PipelineError, "did not finish verifying within 900s"),
        ):
            verify_with_editor(
                bundle, self.root / "stub-editor", REVISION, self.root / "work", timeout=900
            )


class ScratchProjectTests(BundleCase):
    def test_the_project_pins_the_revision_the_modules_and_the_verifier_script(self) -> None:
        project = _scratch_project(self.root, REVISION)
        version = (project / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8")
        self.assertIn(f"m_EditorVersion: {REVISION}", version)
        manifest = json.loads((project / "Packages" / "manifest.json").read_text(encoding="utf-8"))
        # Without the AssetBundle module the runtime has no loader to call,
        # and the verifier would fail for a reason that proves nothing.
        self.assertIn("com.unity.modules.assetbundle", manifest["dependencies"])
        script = project / EDITOR_FOLDER / VERIFIER_SCRIPT
        self.assertTrue(script.is_file())
        self.assertTrue(script.read_text(encoding="utf-8").strip())

    def test_recreating_the_project_keeps_one_copy_of_the_script(self) -> None:
        first = _scratch_project(self.root, REVISION)
        second = _scratch_project(self.root, REVISION)
        self.assertEqual(first, second)
        scripts = list((second / EDITOR_FOLDER).iterdir())
        self.assertEqual([VERIFIER_SCRIPT], [path.name for path in scripts])


if __name__ == "__main__":
    unittest.main()
