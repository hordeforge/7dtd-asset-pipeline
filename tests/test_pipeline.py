from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.build import reject_disabled_modules
from sevendtd_asset_pipeline.config import CONFIG_NAME
from sevendtd_asset_pipeline.config import load_config
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scaffold import initialize
from sevendtd_asset_pipeline.validation import reject_ambiguous_stems, validate_mod

from fixtures import unityfs_bundle


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_scaffold_and_validate_mod(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config = load_config(self.root / ".7dtd-assets.toml")
        config.resources_dir.mkdir()
        config.bundle_output.write_bytes(unityfs_bundle([1, 142]))
        config.tracked_manifest.parent.mkdir(parents=True)
        config.tracked_manifest.write_text(
            "ManifestFileVersion: 0\nAssets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n",
            encoding="utf-8",
        )
        config.config_dir.mkdir()
        (config.config_dir / "items.xml").write_text(
            '<configs><append xpath="/items"><item name="x"><property name="Meshfile" '
            'value="#@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab" />'
            "</item></append></configs>",
            encoding="utf-8",
        )
        report = validate_mod(config)
        self.assertEqual(1, report.reference_count)

    def _stage_mod(self, uri: str) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config = load_config(self.root / CONFIG_NAME)
        config.resources_dir.mkdir()
        config.bundle_output.write_bytes(unityfs_bundle([1, 142]))
        config.tracked_manifest.parent.mkdir(parents=True)
        config.tracked_manifest.write_text(
            "ManifestFileVersion: 0\nAssets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n",
            encoding="utf-8",
        )
        config.config_dir.mkdir()
        (config.config_dir / "blocks.xml").write_text(
            f'<configs><block name="x"><property name="Model" value="{uri}" /></block></configs>',
            encoding="utf-8",
        )
        self.config = config

    def test_validate_accepts_bare_modfolder_uri(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        self.assertEqual(1, validate_mod(self.config).reference_count)

    def test_validate_rejects_foreign_mod_name(self) -> None:
        self._stage_mod("#@modfolder(OtherMod):Resources/example.unity3d?exampleThing.prefab")
        with self.assertRaisesRegex(PipelineError, "expected 'ExampleMod'"):
            validate_mod(self.config)

    def test_validate_rejects_non_modfolder_uri(self) -> None:
        self._stage_mod("#Resources/example.unity3d?exampleThing.prefab")
        with self.assertRaisesRegex(PipelineError, "targets game bundles"):
            validate_mod(self.config)

    def test_init_refuses_to_clobber_an_existing_makefile(self) -> None:
        makefile = self.root / "Makefile.assets"
        makefile.write_text("assets:\n\techo mine\n", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "Makefile.assets"):
            initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        self.assertIn("echo mine", makefile.read_text())

    def test_stem_collision_is_case_insensitive_and_extension_independent(self) -> None:
        with self.assertRaisesRegex(PipelineError, "ambiguous"):
            reject_ambiguous_stems(["Assets/Thing.prefab", "Assets/Props/thing.fbx"])

    def test_disabled_module_warning_fails(self) -> None:
        log = self.root / "unity.log"
        log.write_text("'AssetBundle' is not supported because the module AssetBundle is disabled in the build.\n")
        with self.assertRaisesRegex(PipelineError, "stripped"):
            reject_disabled_modules(log)

    def test_clean_build_log_passes(self) -> None:
        log = self.root / "unity.log"
        log.write_text("Build completed with a result of 'Succeeded'\n")
        reject_disabled_modules(log)

    def test_doctor_runs_every_branch_including_the_editor_one(self) -> None:
        # A NameError in the editor branch survived until a real doctor run,
        # because no test ever configured UNITY_EDITOR.
        import os

        from sevendtd_asset_pipeline.doctor import run_doctor

        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        editor = self.root / "fake-editor"
        editor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        editor.chmod(0o755)
        os.environ["UNITY_EDITOR"] = str(editor)
        try:
            config = load_config(self.root / CONFIG_NAME)
            checks = run_doctor(config)
        finally:
            os.environ.pop("UNITY_EDITOR", None)
        names = {check.name for check in checks}
        # A fake editor has no Windows Build Support, so the editor branch
        # returns that FAIL and stops before probing -version. What matters is
        # that the branch ran at all and reported rather than raised.
        self.assertIn("Windows support", names)
        self.assertTrue(any(check.status == "FAIL" for check in checks))

    def test_config_rejects_resources_outside_mod_root(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config_file = self.root / ".7dtd-assets.toml"
        config_file.write_text(
            config_file.read_text().replace('resources_dir = "Resources"', 'resources_dir = "../outside"')
        )
        with self.assertRaisesRegex(PipelineError, "must stay below"):
            load_config(config_file)


if __name__ == "__main__":
    unittest.main()
