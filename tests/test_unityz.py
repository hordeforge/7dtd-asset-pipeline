from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import AbstractContextManager
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unityz import Unityz, run_json, run_json_lines


class UnityzProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "asset.unity3d"
        self.path.write_bytes(b"fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def patches(
        self, result: subprocess.CompletedProcess[str]
    ) -> tuple[
        AbstractContextManager[mock.MagicMock],
        AbstractContextManager[mock.MagicMock],
        AbstractContextManager[mock.MagicMock],
    ]:
        return (
            mock.patch("sevendtd_asset_pipeline.unityz.require_capability"),
            mock.patch("sevendtd_asset_pipeline.unityz.shutil.which", return_value="/bin/unityz"),
            mock.patch("sevendtd_asset_pipeline.unityz.subprocess.run", return_value=result),
        )

    def test_runs_a_bounded_argument_vector_and_decodes_one_object(self) -> None:
        result = subprocess.CompletedProcess([], 0, '{"type":"UnityFS"}\n', "")
        capability, executable, run = self.patches(result)
        with capability, executable, run as invoked:
            report = run_json("info", self.path, "--json")
        self.assertEqual("UnityFS", report["type"])
        invoked.assert_called_once_with(
            ["/bin/unityz", "info", str(self.path.resolve()), "--json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_nonzero_exit_keeps_the_tool_diagnostic(self) -> None:
        result = subprocess.CompletedProcess([], 1, "", "unityz: UnknownFormat\n")
        capability, executable, run = self.patches(result)
        with capability, executable, run, self.assertRaisesRegex(PipelineError, "UnknownFormat"):
            run_json("info", self.path, "--json")

    def test_multiline_failure_is_one_actionable_error_line(self) -> None:
        result = subprocess.CompletedProcess(
            [], 1, "bank: FSB5\n  sample 0: decode failed: Corrupt\n", ""
        )
        capability, executable, run = self.patches(result)
        output_dir = str(Path(self.temporary.name) / "audio")
        with capability, executable, run, self.assertRaises(PipelineError) as caught:
            Unityz(self.path).text("fsb", "--outdir", output_dir)
        message = str(caught.exception)
        self.assertNotIn("\n", message)
        self.assertIn("bank: FSB5 | sample 0: decode failed: Corrupt", message)

    def test_text_runs_a_writing_command_through_the_same_bounded_adapter(self) -> None:
        result = subprocess.CompletedProcess([], 0, "extracted 1 wav sample(s)\n", "")
        capability, executable, run = self.patches(result)
        output_dir = str(Path(self.temporary.name) / "audio")
        with capability, executable, run as invoked:
            output = Unityz(self.path).text("fsb", "--outdir", output_dir)
        self.assertEqual("extracted 1 wav sample(s)\n", output)
        invoked.assert_called_once_with(
            ["/bin/unityz", "fsb", str(self.path.resolve()), "--outdir", output_dir],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def test_invalid_json_is_a_pipeline_error(self) -> None:
        result = subprocess.CompletedProcess([], 0, "not json\n", "")
        capability, executable, run = self.patches(result)
        with capability, executable, run, self.assertRaisesRegex(PipelineError, "invalid JSON"):
            run_json("info", self.path, "--json")

    def test_json_report_decodes_a_machine_verdict_from_exit_one(self) -> None:
        result = subprocess.CompletedProcess([], 1, '{"checked":2,"failed":1}\n', "")
        capability, executable, run = self.patches(result)
        with capability, executable, run:
            report = Unityz(self.path).json_report("verify", "--json")
        self.assertEqual(1, report["failed"])

    def test_json_lines_preserve_each_serialized_file_document(self) -> None:
        result = subprocess.CompletedProcess([], 0, '{"node":"a"}\n{"node":"b"}\n', "")
        capability, executable, run = self.patches(result)
        with capability, executable, run:
            documents = run_json_lines("hierarchy", self.path, "--json")
        self.assertEqual(["a", "b"], [document["node"] for document in documents])

    def test_missing_file_fails_before_capability_or_process_probe(self) -> None:
        missing = Path(self.temporary.name) / "missing.unity3d"
        with (
            mock.patch("sevendtd_asset_pipeline.unityz.require_capability") as capability,
            mock.patch("sevendtd_asset_pipeline.unityz.subprocess.run") as run,
            self.assertRaisesRegex(PipelineError, "no such file"),
        ):
            run_json("info", missing, "--json")
        capability.assert_not_called()
        run.assert_not_called()

    def test_timeout_is_a_bounded_pipeline_error(self) -> None:
        capability, executable, run = self.patches(subprocess.CompletedProcess([], 0, "", ""))
        with (
            capability,
            executable,
            run as invoked,
            self.assertRaisesRegex(PipelineError, "timed out after 120s"),
        ):
            invoked.side_effect = subprocess.TimeoutExpired(["unityz"], 120)
            run_json("info", self.path, "--json")


if __name__ == "__main__":
    unittest.main()
