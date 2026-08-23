from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import collect_status, load_config
from sevendtd_asset_pipeline.config import CONFIG_NAME
from sevendtd_asset_pipeline.scaffold import initialize

from fixtures import unityfs_bundle


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        self.config = load_config(self.root / CONFIG_NAME)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reports_a_missing_bundle_without_raising(self) -> None:
        status = collect_status(self.config)
        self.assertFalse(status.bundle_present)
        self.assertFalse(status.valid)
        self.assertTrue(status.problems)
        self.assertEqual("ExampleMod", status.mod_name)

    def test_reports_a_complete_mod_as_valid(self) -> None:
        self.config.resources_dir.mkdir()
        self.config.bundle_output.write_bytes(unityfs_bundle([1, 142]))
        self.config.tracked_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.config.tracked_manifest.write_text(
            "Assets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n", encoding="utf-8"
        )
        self.config.config_dir.mkdir()
        (self.config.config_dir / "blocks.xml").write_text(
            '<configs><block name="x"><property name="Model" '
            'value="#@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab" />'
            "</block></configs>",
            encoding="utf-8",
        )
        status = collect_status(self.config)
        self.assertTrue(status.valid, status.problems)
        self.assertEqual([], status.problems)
        self.assertEqual(1, status.asset_count)
        self.assertEqual(1, status.reference_count)
        self.assertEqual("exampleThing", status.references[0]["asset_stem"])
        self.assertTrue(status.bundle_has_assetbundle_object)
        # The whole structure must survive a JSON round trip for agents.
        import json

        self.assertEqual(status.as_dict(), json.loads(json.dumps(status.as_dict())))

    def test_scaffold_writes_a_consumer_agent_guide(self) -> None:
        guide = self.root / "tools" / "shamway" / "AGENTS.md"
        self.assertTrue(guide.is_file())
        text = guide.read_text()
        self.assertIn("ExampleMod", text)
        self.assertIn("example.unity3d", text)
        self.assertIn("shamway status --json", text)
        # The guide carries JSON examples; rendering must not mangle their
        # braces or choke on them.
        self.assertIn('{"id":1,"op":"status"}', text)
        self.assertNotIn("{mod_name}", text)
        self.assertNotIn("{bundle_name}", text)


if __name__ == "__main__":
    unittest.main()
