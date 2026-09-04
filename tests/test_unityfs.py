"""The pipeline's BundleInfo contract over unityz metadata.

The tracked self-test bundle is the generated acceptance fixture. Its truncated
copy is the rejection fixture: both pass through the real pinned unityz parser,
while schema-focused tests isolate the small Python mapping layer.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unityfs import BundleInfo, inspect_bundle
from sevendtd_asset_pipeline.validation import validate_bundle

ROOT = Path(__file__).resolve().parents[1]
SELF_TEST_BUNDLE = ROOT / "examples" / "SelfTestMod" / "Resources" / "shamwayselftest.unity3d"


def metadata(*nodes: tuple[str, list[int]]) -> dict[str, object]:
    return {
        "type": "UnityFS",
        "version": 8,
        "nodes_list": [
            {
                "path": f"CAB-{index}",
                "serialized": {"unity": revision, "class_ids": class_ids},
            }
            for index, (revision, class_ids) in enumerate(nodes)
        ],
    }


class GeneratedFixtureTests(unittest.TestCase):
    def test_generated_bundle_reports_revision_format_and_classes(self) -> None:
        info = inspect_bundle(SELF_TEST_BUNDLE)
        self.assertEqual("2022.3.62f2", info.unity_version)
        self.assertEqual(8, info.archive_format)
        self.assertIn(142, info.class_ids)
        self.assertTrue(info.has_assetbundle_object)

    def test_truncated_generated_bundle_is_a_bounded_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "truncated.unity3d"
            path.write_bytes(SELF_TEST_BUNDLE.read_bytes()[:128])
            with self.assertRaisesRegex(PipelineError, "not a UnityFS.*readable by unityz"):
                inspect_bundle(path)


class MetadataContractTests(unittest.TestCase):
    def inspect(self, report: dict[str, object]) -> BundleInfo:
        with mock.patch("sevendtd_asset_pipeline.unityfs.run_json", return_value=report):
            return inspect_bundle(SELF_TEST_BUNDLE)

    def test_combines_class_ids_across_serialized_nodes_without_duplicates(self) -> None:
        info = self.inspect(metadata(("2022.3.62f2", [1, 142]), ("2022.3.62f2", [142, 28])))
        self.assertEqual((1, 142, 28), info.class_ids)

    def test_rejects_a_non_bundle_report(self) -> None:
        with self.assertRaisesRegex(PipelineError, "not a UnityFS"):
            self.inspect({"type": "SerializedFile", "version": 22})

    def test_rejects_a_bundle_without_serialized_nodes(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no SerializedFile nodes"):
            self.inspect({"type": "UnityFS", "version": 8, "nodes_list": []})

    def test_rejects_mixed_serialized_file_revisions(self) -> None:
        report = metadata(("2022.3.62f2", [142]), ("2021.3.1f1", [28]))
        with self.assertRaisesRegex(PipelineError, "mixes SerializedFile revisions"):
            self.inspect(report)

    def test_rejects_malformed_class_ids(self) -> None:
        report = metadata(("2022.3.62f2", [142]))
        nodes = report["nodes_list"]
        assert isinstance(nodes, list)
        node = nodes[0]
        assert isinstance(node, dict)
        serialized = node["serialized"]
        assert isinstance(serialized, dict)
        serialized["class_ids"] = [142, "28"]
        with self.assertRaisesRegex(PipelineError, "integer class ID"):
            self.inspect(report)

    def test_rejects_bundle_without_class_142(self) -> None:
        with (
            mock.patch(
                "sevendtd_asset_pipeline.unityfs.run_json",
                return_value=metadata(("2022.3.62f2", [1, 21, 28])),
            ),
            self.assertRaisesRegex(PipelineError, "class-142"),
        ):
            validate_bundle(SELF_TEST_BUNDLE)

    def test_rejects_wrong_unity_revision(self) -> None:
        with (
            mock.patch(
                "sevendtd_asset_pipeline.unityfs.run_json",
                return_value=metadata(("2021.3.1f1", [142])),
            ),
            self.assertRaisesRegex(PipelineError, "installed game uses"),
        ):
            validate_bundle(SELF_TEST_BUNDLE, "2022.3.62f2")

    def test_a_missing_file_remains_an_actionable_pipeline_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no such file"):
            inspect_bundle(Path("/nonexistent/dir/bundle.unity3d"))


if __name__ == "__main__":
    unittest.main()
