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
        config = load_config(self.root / ".shamway.toml")
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

    def test_a_modinfo_name_disagreement_fails(self) -> None:
        """The configuration and the modlet must describe the same mod."""
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="OtherName" /></xml>', encoding="utf-8"
        )
        with self.assertRaisesRegex(PipelineError, "OtherName"):
            validate_mod(self.config)

    def test_a_reference_to_a_missing_bundle_is_named(self) -> None:
        self._stage_mod("#@modfolder:Resources/absent.unity3d?exampleThing.prefab")
        with self.assertRaisesRegex(PipelineError, "bundle does not exist"):
            validate_mod(self.config)

    def test_a_reference_to_a_foreign_bundle_fails(self) -> None:
        self._stage_mod("#@modfolder:Resources/other.unity3d?exampleThing.prefab")
        resources = self.root / "Resources"
        (resources / "other.unity3d").write_bytes(unityfs_bundle([142]))
        with self.assertRaisesRegex(PipelineError, "this pipeline owns"):
            validate_mod(self.config)

    def test_an_xml_reference_to_an_absent_asset_stem_fails(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?missingThing.prefab")
        with self.assertRaisesRegex(PipelineError, "absent from"):
            validate_mod(self.config)

    def test_an_xml_reference_with_mismatched_case_fails(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?examplething.prefab")
        with self.assertRaisesRegex(PipelineError, "asset case is 'examplething'"):
            validate_mod(self.config)

    def test_validate_holds_the_staged_bundle_to_the_installed_games_revision(self) -> None:
        """A game dir makes the revision gate authoritative, not just declared."""
        game = self.root / "game"
        (game / "Data" / "Config").mkdir(parents=True)
        (game / "Data" / "Config" / "items.xml").write_text("<configs/>", encoding="utf-8")
        entities = game / "Data" / "Bundles" / "Standalone" / "Entities"
        entities.mkdir(parents=True)
        # The install speaks 2022.3.62f2; the staged bundle claims something else.
        (entities / "Entities").write_bytes(unityfs_bundle([142], "2022.3.62f2"))
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        body = (self.root / CONFIG_NAME).read_text(encoding="utf-8").replace(
            'directory = ""', 'directory = "game"', 1
        )
        (self.root / CONFIG_NAME).write_text(body, encoding="utf-8")
        self.config = load_config(self.root / CONFIG_NAME)
        (self.config.resources_dir / "example.unity3d").write_bytes(
            unityfs_bundle([142], "2021.3.1f1")
        )
        with self.assertRaisesRegex(PipelineError, "installed game uses"):
            validate_mod(self.config)

    def test_validate_rejects_foreign_mod_name(self) -> None:
        self._stage_mod("#@modfolder(OtherMod):Resources/example.unity3d?exampleThing.prefab")
        with self.assertRaisesRegex(PipelineError, "expected 'ExampleMod'"):
            validate_mod(self.config)

    def test_validate_rejects_non_modfolder_uri(self) -> None:
        self._stage_mod("#Resources/example.unity3d?exampleThing.prefab")
        with self.assertRaisesRegex(PipelineError, "targets game bundles"):
            validate_mod(self.config)

    def _add_code_references(self, *stems: str) -> None:
        path = self.root / CONFIG_NAME
        listed = ", ".join(f'"{stem}"' for stem in stems)
        body = path.read_text(encoding="utf-8").replace("code_references = []", f"code_references = [{listed}]")
        path.write_text(body, encoding="utf-8")
        self.config = load_config(path)

    def test_code_references_are_validated_against_the_manifest(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        self._add_code_references("exampleThing")
        report = validate_mod(self.config)
        self.assertEqual(2, report.reference_count)
        self.assertTrue(any("code_references: exampleThing" in m for m in report.messages))

    def test_code_reference_absent_from_the_manifest_fails(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        self._add_code_references("exampleVfxLight")
        with self.assertRaisesRegex(PipelineError, "code_references.*absent"):
            validate_mod(self.config)

    def test_code_reference_case_must_match(self) -> None:
        self._stage_mod("#@modfolder:Resources/example.unity3d?exampleThing.prefab")
        self._add_code_references("examplething")
        with self.assertRaisesRegex(PipelineError, "asset case"):
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

    def test_particle_curve_mode_error_fails(self) -> None:
        log = self.root / "unity.log"
        log.write_text("Particle Velocity curves must all be in the same mode\nBuild completed\n")
        with self.assertRaisesRegex(PipelineError, "MinMaxCurve"):
            reject_disabled_modules(log)

    def test_doctor_rejects_an_editor_whose_version_differs_from_the_project(self) -> None:
        from sevendtd_asset_pipeline.doctor import editor_matches_project

        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config = load_config(self.root / ".shamway.toml")
        self.assertEqual("OK", editor_matches_project("2022.3.62f2", config).status)
        self.assertEqual("OK", editor_matches_project("2022.3.62f2 (7670c08855a9)", config).status)
        self.assertEqual("FAIL", editor_matches_project("6000.5.9f1", config).status)

    def test_scaffold_pins_the_changeset_when_it_is_known(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", "7670c08855a9")
        version_file = (
            self.root / "tools" / "shamway" / "UnityProject"
            / "ProjectSettings" / "ProjectVersion.txt"
        )
        text = version_file.read_text()
        self.assertIn("m_EditorVersion: 2022.3.62f2", text)
        self.assertIn("m_EditorVersionWithRevision: 2022.3.62f2 (7670c08855a9)", text)

    def test_scaffold_omits_the_revision_line_when_the_changeset_is_unknown(self) -> None:
        # Unity writes that line itself on first open, so an unreachable
        # release service must not fail the scaffold.
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        version_file = (
            self.root / "tools" / "shamway" / "UnityProject"
            / "ProjectSettings" / "ProjectVersion.txt"
        )
        text = version_file.read_text()
        self.assertIn("m_EditorVersion: 2022.3.62f2", text)
        self.assertNotIn("m_EditorVersionWithRevision", text)

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
        config_file = self.root / ".shamway.toml"
        config_file.write_text(
            config_file.read_text().replace('resources_dir = "Resources"', 'resources_dir = "../outside"')
        )
        with self.assertRaisesRegex(PipelineError, "must stay below"):
            load_config(config_file)


if __name__ == "__main__":
    unittest.main()
