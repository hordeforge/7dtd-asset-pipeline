from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.references import (
    discover_references,
    manifest_assets,
    parse_reference,
    resolve_case_insensitive,
)


class ReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discovers_nested_config_and_both_quote_styles(self) -> None:
        nested = self.root / "Config" / "XUi"
        nested.mkdir(parents=True)
        (nested / "windows.xml").write_text(
            "<x value=\"#@modfolder(MyMod):Resources/my.unity3d?first.prefab\" "
            "other='#@modfolder(MyMod):Resources/my.unity3d?second.wav'/>",
            encoding="utf-8",
        )
        refs = discover_references(self.root / "Config")
        self.assertEqual(["first", "second"], [ref.asset_stem for ref in refs])

    def test_parses_mod_bundle_and_asset(self) -> None:
        ref = parse_reference(
            Path("items.xml"), "#@modfolder(MyMod):Resources/my.unity3d?Props/Thing.prefab"
        )
        self.assertEqual("MyMod", ref.mod_name)
        self.assertEqual("Resources/my.unity3d", ref.bundle_path)
        self.assertEqual("Thing", ref.asset_stem)

    def test_manifest_assets_accepts_indentation(self) -> None:
        manifest = self.root / "bundle.manifest"
        manifest.write_text("ManifestFileVersion: 0\nAssets:\n- Assets/A.prefab\n- Assets/B.wav\nDependencies: {}\n")
        self.assertEqual(["Assets/A.prefab", "Assets/B.wav"], manifest_assets(manifest))

    def test_case_insensitive_resolution(self) -> None:
        resource = self.root / "Resources"
        resource.mkdir()
        bundle = resource / "MyBundle.Unity3D"
        bundle.write_bytes(b"x")
        self.assertEqual(bundle, resolve_case_insensitive(self.root, "resources/mybundle.unity3d"))

    def test_resolution_rejects_parent_traversal(self) -> None:
        with self.assertRaisesRegex(PipelineError, "escapes"):
            resolve_case_insensitive(self.root, "../secret")


if __name__ == "__main__":
    unittest.main()
