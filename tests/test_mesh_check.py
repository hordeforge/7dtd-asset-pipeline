"""The glTF conformance lane must never pass on missing evidence.

A validator that exits zero with an unreadable report proves neither
conformance nor its absence. Recording nothing would leave `ok` true with no
conformance evidence at all — exactly the silence this pipeline exists to
remove — so the unusable report is a problem line, like any other failed gate.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sevendtd_asset_pipeline.mesh_check import check_mesh


class GlTFValidatorReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.mesh = Path(self.temporary.name) / "myModThing.glb"
        self.mesh.write_bytes(b"")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_validator(
        self, returncode: int, stdout: str, stderr: str = ""
    ) -> tuple[bool, list[str]]:
        validator = "/usr/bin/gltf-validator"
        run_result = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
        with (
            mock.patch("sevendtd_asset_pipeline.mesh_check.has_capability", return_value=False),
            mock.patch("sevendtd_asset_pipeline.mesh_check.shutil.which", return_value=validator),
            mock.patch(
                "sevendtd_asset_pipeline.mesh_check.subprocess.run", return_value=run_result
            ),
        ):
            report = check_mesh(self.mesh)
        return report.ok, report.problems

    def test_a_zero_exit_with_an_unreadable_report_fails_rather_than_passing(self) -> None:
        ok, problems = self._run_validator(returncode=0, stdout="<html>not json</html>")
        self.assertFalse(ok)
        self.assertTrue(any("no readable report" in problem for problem in problems))

    def test_a_nonzero_exit_with_an_unreadable_report_names_the_exit(self) -> None:
        ok, problems = self._run_validator(
            returncode=3, stdout="", stderr="segfault during resource scan"
        )
        self.assertFalse(ok)
        self.assertTrue(any("exited 3" in problem for problem in problems))

    def test_a_readable_report_with_no_issues_still_passes(self) -> None:
        ok, problems = self._run_validator(returncode=0, stdout='{"issues": {}}')
        self.assertTrue(ok)
        self.assertEqual([], [problem for problem in problems if "glTF" in problem])


if __name__ == "__main__":
    unittest.main()
