"""The stable DeepReport mapping over unityz object and hierarchy JSON."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.deep_inspect import DeepReport, deep_inspect
from sevendtd_asset_pipeline.errors import PipelineError

ROOT = Path(__file__).resolve().parents[1]
SELF_TEST_BUNDLE = ROOT / "examples" / "SelfTestMod" / "Resources" / "shamwayselftest.unity3d"


@unittest.skipUnless(has_capability("unityz"), "deep_inspect needs unityz")
class DeepInspectFixtureTests(unittest.TestCase):
    def test_generated_bundle_keeps_the_public_object_and_prefab_census(self) -> None:
        report = deep_inspect(SELF_TEST_BUNDLE)
        self.assertEqual(604, report.object_count)
        self.assertEqual(50, len(report.entries))
        self.assertEqual(0, report.skipped_children)
        self.assertEqual(186, report.type_counts["GameObject"])
        self.assertEqual(3, report.type_counts["ParticleSystem"])

        entries = {entry.container_path: entry for entry in report.entries}
        self.assertEqual("flashCard", entries["flashcard"].object_name)
        self.assertEqual("alpha", entries["shamway/particles/alpha"].asset_stem)
        self.assertEqual(4, entries["burst"].object_count)
        self.assertEqual(
            {"ParticleSystem": 3, "ParticleSystemRenderer": 3, "Transform": 4},
            entries["burst"].components,
        )
        self.assertEqual(34, entries["shamwayselftestarachnid"].object_count)
        self.assertEqual(
            {
                "Animation": 1,
                "BoxCollider": 30,
                "CapsuleCollider": 1,
                "SkinnedMeshRenderer": 1,
                "Transform": 34,
            },
            entries["shamwayselftestarachnid"].components,
        )
        self.assertFalse(any(entry.partial for entry in report.entries))

    def test_a_missing_bundle_is_an_actionable_pipeline_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no such file"):
            deep_inspect(ROOT / "absent.unity3d")


class _Reader:
    def __init__(self, *, skipped: int = 0, verify_failures: list[object] | None = None) -> None:
        self.info: dict[str, object] = {
            "nodes_list": [{"path": "CAB", "serialized": {"type_tree": True}}],
            "object_list": [
                {"node": "CAB", "path_id": 1, "class": 142, "name": "bundle"},
                {"node": "CAB", "path_id": 2, "class": 1, "name": "brokenPrefab"},
                {"node": "CAB", "path_id": 3, "class": 1, "name": "goodPrefab"},
                {"node": "CAB", "path_id": 4, "class": 21, "name": "material"},
            ],
        }
        self.stats: dict[str, object] = {
            "objects": 4,
            "classes": {
                "142": {"name": "AssetBundle", "count": 1},
                "1": {"name": "GameObject", "count": 2},
                "4": {"name": "Transform", "count": 2},
                "21": {"name": "Material", "count": 1},
            },
        }
        self.hierarchy: list[dict[str, object]] = [
            {
                "node": "CAB",
                "skipped_children": skipped,
                "hierarchy": [
                    {
                        "name": "brokenPrefab",
                        "gameObject": 2,
                        "components": [4],
                        "children": [],
                        "skipped_children": skipped,
                    },
                    {
                        "name": "goodPrefab",
                        "gameObject": 3,
                        "components": [4],
                        "children": [],
                        "skipped_children": 0,
                    },
                ],
            }
        ]
        self.verify: dict[str, object] = {
            "checked": 4,
            "failed": len(verify_failures or []),
            "skipped": 0,
            "failures": verify_failures or [],
        }

    calls: list[tuple[str, ...]]

    def json(self, command: str, *arguments: str) -> dict[str, object]:
        self.__dict__.setdefault("calls", []).append((command, *arguments))
        if command == "info":
            return self.info
        if command == "stats":
            return self.stats
        if command == "show":
            return {
                "m_Container": [
                    ["broken", {"asset": {"m_FileID": 0, "m_PathID": 2}}],
                    ["good", {"asset": {"m_FileID": 0, "m_PathID": 3}}],
                    ["mat", {"asset": {"m_FileID": 0, "m_PathID": 4}}],
                    ["external", {"asset": {"m_FileID": 1, "m_PathID": 99}}],
                ]
            }
        raise AssertionError((command, arguments))

    def json_lines(self, command: str, *arguments: str) -> list[dict[str, object]]:
        self.__dict__.setdefault("calls", []).append((command, *arguments))
        if command != "hierarchy":
            raise AssertionError((command, arguments))
        return self.hierarchy

    def json_report(self, command: str, *arguments: str) -> dict[str, object]:
        self.__dict__.setdefault("calls", []).append((command, *arguments))
        if command != "verify":
            raise AssertionError((command, arguments))
        return self.verify


class DeepReportMappingTests(unittest.TestCase):
    def inspect(self, reader: _Reader) -> DeepReport:
        with mock.patch("sevendtd_asset_pipeline.deep_inspect.Unityz", return_value=reader):
            return deep_inspect(SELF_TEST_BUNDLE)

    def test_only_the_prefab_with_an_omitted_subtree_is_partial(self) -> None:
        report = self.inspect(_Reader(skipped=1))
        entries = {entry.container_path: entry for entry in report.entries}
        self.assertTrue(entries["broken"].partial)
        self.assertFalse(entries["good"].partial)
        self.assertEqual(1, report.skipped_children)

    def test_a_verified_object_failure_marks_its_container_entry(self) -> None:
        report = self.inspect(
            _Reader(verify_failures=[{"node": "CAB", "path_id": 4, "error": "read failed"}])
        )
        entries = {entry.container_path: entry for entry in report.entries}
        self.assertTrue(entries["mat"].partial)
        self.assertFalse(entries["good"].partial)

    def test_an_external_pointer_is_reported_but_marked_partial(self) -> None:
        report = self.inspect(_Reader())
        external = next(entry for entry in report.entries if entry.container_path == "external")
        self.assertEqual("Unknown", external.type)
        self.assertEqual("", external.object_name)
        self.assertTrue(external.partial)

    def test_a_typeless_bundle_decodes_through_the_built_in_trees(self) -> None:
        """A stripped 2022.3.62f2 file is read with `--builtin`, not refused."""
        reader = _Reader()
        reader.info["nodes_list"] = [
            {"path": "CAB", "serialized": {"type_tree": False, "unity": "2022.3.62f2"}}
        ]
        with mock.patch("sevendtd_asset_pipeline.deep_inspect.Unityz", return_value=reader):
            report = deep_inspect(SELF_TEST_BUNDLE)
        self.assertEqual(4, report.object_count)
        decoding = [call for call in reader.calls if call[0] != "info"]
        self.assertTrue(decoding)
        for call in decoding:
            self.assertIn("--builtin", call, call)
        self.assertNotIn("--builtin", next(call for call in reader.calls if call[0] == "info"))

    def test_an_embedded_tree_bundle_never_asks_for_built_in_trees(self) -> None:
        reader = _Reader()
        with mock.patch("sevendtd_asset_pipeline.deep_inspect.Unityz", return_value=reader):
            deep_inspect(SELF_TEST_BUNDLE)
        for call in reader.calls:
            self.assertNotIn("--builtin", call, call)

    def test_a_typeless_bundle_of_an_unshipped_release_is_refused_by_name(self) -> None:
        """unityz packs trees per exact release; an unshipped one leaves objects skipped."""
        reader = _Reader()
        reader.info["nodes_list"] = [
            {"path": "CAB", "serialized": {"type_tree": False, "unity": "2021.3.45f2"}}
        ]
        reader.verify["skipped"] = 4
        with (
            mock.patch("sevendtd_asset_pipeline.deep_inspect.Unityz", return_value=reader),
            self.assertRaisesRegex(PipelineError, "no built-in trees for 2021.3.45f2"),
        ):
            deep_inspect(SELF_TEST_BUNDLE)


if __name__ == "__main__":
    unittest.main()
