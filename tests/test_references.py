from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.references import (
    discover_references,
    manifest_assets,
    parse_reference,
    read_mod_name,
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

    def test_parses_bare_modfolder_self_reference(self) -> None:
        # 7DTD accepts '@modfolder:' as well as '@modfolder(Name):'
        # (maci0/7dtd-research docs/mod-loading.md; Assembly-CSharp string table).
        ref = parse_reference(
            Path("blocks.xml"), "#@modfolder:Resources/my.unity3d?Thing.prefab"
        )
        self.assertTrue(ref.is_modfolder)
        self.assertIsNone(ref.mod_name)
        self.assertEqual("Resources/my.unity3d", ref.bundle_path)
        self.assertEqual("Thing", ref.asset_stem)

    def test_flags_non_modfolder_uri(self) -> None:
        ref = parse_reference(Path("blocks.xml"), "#Other/Bundles/thing.unity3d?Thing.prefab")
        self.assertFalse(ref.is_modfolder)
        self.assertIsNone(ref.mod_name)

    def test_a_uri_without_an_asset_part_is_malformed(self) -> None:
        with self.assertRaisesRegex(PipelineError, "malformed bundle URI"):
            parse_reference(Path("blocks.xml"), "#@modfolder:Resources/my.unity3d")
        with self.assertRaisesRegex(PipelineError, "malformed bundle URI"):
            parse_reference(Path("blocks.xml"), "#@modfolder:Resources/my.unity3d?")
        with self.assertRaisesRegex(PipelineError, "malformed bundle URI"):
            parse_reference(Path("blocks.xml"), "#")

    def test_stems_are_taken_from_either_separator(self) -> None:
        back = parse_reference(Path("b.xml"), "#@modfolder:Resources\\my.unity3d?Props\\Thing.prefab")
        self.assertEqual("Thing", back.asset_stem)

    def test_modinfo_without_a_name_element_is_rejected(self) -> None:
        mod_info = self.root / "ModInfo.xml"
        mod_info.write_text("<xml><Version value='1.0' /></xml>", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "Name"):
            read_mod_name(mod_info)

    def test_unparseable_modinfo_names_the_file(self) -> None:
        mod_info = self.root / "ModInfo.xml"
        mod_info.write_text("<xml><Name value=", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "cannot parse.*ModInfo.xml"):
            read_mod_name(mod_info)

    def test_manifest_assets_accepts_indentation(self) -> None:
        manifest = self.root / "bundle.manifest"
        manifest.write_text("ManifestFileVersion: 0\nAssets:\n- Assets/A.prefab\n- Assets/B.wav\nDependencies: {}\n")
        self.assertEqual(["Assets/A.prefab", "Assets/B.wav"], manifest_assets(manifest))

    def test_a_manifest_listing_no_assets_is_rejected(self) -> None:
        manifest = self.root / "bundle.manifest"
        manifest.write_text("ManifestFileVersion: 0\nAssets:\nDependencies: {}\n")
        with self.assertRaisesRegex(PipelineError, "lists no Assets"):
            manifest_assets(manifest)

    def test_a_missing_manifest_is_an_error_not_a_traceback(self) -> None:
        with self.assertRaisesRegex(PipelineError, "cannot read manifest"):
            manifest_assets(self.root / "absent.manifest")

    def test_case_insensitive_resolution(self) -> None:
        resource = self.root / "Resources"
        resource.mkdir()
        bundle = resource / "MyBundle.Unity3D"
        bundle.write_bytes(b"x")
        self.assertEqual(bundle, resolve_case_insensitive(self.root, "resources/mybundle.unity3d"))

    def test_resolution_rejects_parent_traversal(self) -> None:
        with self.assertRaisesRegex(PipelineError, "escapes"):
            resolve_case_insensitive(self.root, "../secret")

    def test_a_directory_with_two_casings_of_one_name_is_rejected(self) -> None:
        """7DTD's stem-only lookup cannot pick between two casings; neither do we."""
        resource = self.root / "Resources"
        resource.mkdir()
        (resource / "MyBundle.unity3d").write_bytes(b"x")
        (resource / "mybundle.unity3d").write_bytes(b"y")
        with self.assertRaisesRegex(PipelineError, "collision"):
            resolve_case_insensitive(self.root, "Resources/mybundle.unity3d")

    def test_a_missing_intermediate_directory_resolves_to_none(self) -> None:
        self.assertIsNone(resolve_case_insensitive(self.root, "NoDir/thing.unity3d"))

    def test_a_directory_named_like_the_bundle_is_not_the_bundle(self) -> None:
        directory = self.root / "Resources" / "thing.unity3d"
        directory.mkdir(parents=True)
        self.assertIsNone(resolve_case_insensitive(self.root, "resources/thing.unity3d"))


if __name__ == "__main__":
    unittest.main()
