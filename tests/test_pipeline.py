from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fixtures import unityfs_bundle

from sevendtd_asset_pipeline.build import reject_disabled_modules
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.config import CONFIG_NAME, PipelineConfig, load_config
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scaffold import initialize
from sevendtd_asset_pipeline.validation import reject_ambiguous_stems, validate_mod


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

    def test_scaffold_rejects_an_unknown_bundle_source_before_writing(self) -> None:
        """The CLI's argparse choices catch this; the API and `call` arrive here.

        A bad value that reached render_config would scaffold every file and
        then write a configuration load_config rejects forever: a mod reported
        as created that no command can open.
        """
        with self.assertRaisesRegex(PipelineError, "bundle_source must be one of"):
            initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="bogus")
        self.assertFalse((self.root / CONFIG_NAME).exists(), "nothing may be written")
        self.assertFalse((self.root / "tools").exists())

    def test_scaffold_rejects_a_malformed_bundle_name_before_writing(self) -> None:
        """An explicit --bundle-name held to the same rule load_config applies."""
        with self.assertRaisesRegex(PipelineError, "bundle_name"):
            initialize(self.root, None, 'evil"\n[unity]\neditor = "/tmp/x"', "2022.3.62f2")
        self.assertFalse((self.root / CONFIG_NAME).exists(), "nothing may be written")
        self.assertFalse((self.root / "tools").exists())

    def test_a_config_with_an_invalid_byte_is_an_error_not_a_traceback(self) -> None:
        """One non-UTF-8 byte (an editor saving latin-1) fails as a gate, cleanly."""
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config_path = self.root / CONFIG_NAME
        config_path.write_bytes(config_path.read_bytes().replace(b"ExampleMod", b"Ex\xffmple"))
        with self.assertRaisesRegex(PipelineError, "cannot read"):
            load_config(config_path)

    def _load_with_machine_source_env(self, value: str) -> PipelineConfig:
        import os
        from unittest import mock

        clean = {key: value for key, value in os.environ.items() if key != "SHAMWAY_BUNDLE_SOURCE"}
        with mock.patch.dict(os.environ, {**clean, "SHAMWAY_BUNDLE_SOURCE": value}):
            return load_config(self.root / CONFIG_NAME)

    def test_the_machine_bundle_source_override_selects_this_host(self) -> None:
        """SHAMWAY_BUNDLE_SOURCE moves one committed configuration between hosts.

        The same checkout is a build host with an editor and an agent box
        without one; the file records the mod's decision, the environment
        this machine's.
        """
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        self.assertEqual("synthesized", load_config(self.root / CONFIG_NAME).bundle_source)
        self.assertEqual("unity", self._load_with_machine_source_env("unity").bundle_source)
        self.assertEqual("external", self._load_with_machine_source_env("external").bundle_source)

    def test_the_machine_bundle_source_may_not_invent_or_remove_a_bundle(self) -> None:
        initialize(self.root, None, None, "", bundle_source="none")
        for override in ("unity", "synthesized", "external"):
            with self.assertRaisesRegex(PipelineError, "cannot apply"):
                self._load_with_machine_source_env(override)

    def test_the_machine_bundle_source_rejects_values_that_are_not_sources(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        for override in ("none", "bogus"):
            with self.assertRaisesRegex(PipelineError, "may only be"):
                self._load_with_machine_source_env(override)

    def test_machine_bundle_sources_are_the_declared_sources_minus_none(self) -> None:
        """The override's allowed set is derived from BUNDLE_SOURCES, not a copy.

        A source added to BUNDLE_SOURCES becomes machine-selectable by
        construction; pinning the literal keeps adding one a deliberate,
        reviewed act rather than something an environment variable starts
        permitting silently.
        """
        from sevendtd_asset_pipeline.config import BUNDLE_SOURCES, MACHINE_BUNDLE_SOURCES

        self.assertEqual(("synthesized", "external", "unity"), MACHINE_BUNDLE_SOURCES)
        self.assertEqual(
            tuple(name for name in BUNDLE_SOURCES if name != "none"),
            MACHINE_BUNDLE_SOURCES,
        )

    def test_scaffold_survives_hostile_modinfo_characters(self) -> None:
        """A ModInfo Name with TOML metacharacters must still load back exactly.

        The name comes from an XML file that can be built on another machine,
        so quotes, backslashes, and character-referenced control characters in
        it are untrusted input at this boundary. Rendered raw into
        .shamway.toml they wrote a configuration nothing could parse.
        (Raw newlines in an XML attribute normalize to spaces; &#10;/&#9;
        character references survive parsing, which is why they are used here.)
        """
        hostile = 'Ex"ample\\Mod\nnext "line\ttab'
        escaped = hostile.replace("&", "&amp;")
        escaped = escaped.replace('"', "&quot;").replace("\n", "&#10;").replace("\t", "&#9;")
        (self.root / "ModInfo.xml").write_text(
            f'<xml><Name value="{escaped}" /></xml>', encoding="utf-8"
        )
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config = load_config(self.root / CONFIG_NAME)
        self.assertEqual(hostile, config.mod_name)

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
        body = (
            (self.root / CONFIG_NAME)
            .read_text(encoding="utf-8")
            .replace('directory = ""', 'directory = "game"', 1)
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
        body = path.read_text(encoding="utf-8").replace(
            "code_references = []", f"code_references = [{listed}]"
        )
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

    def test_init_writes_the_makefile_lf_only(self) -> None:
        """GNU make rejects CRLF recipes, which Windows text mode would write.

        The scaffold must therefore request LF explicitly rather than rely on
        the platform's default translation. The spy pins the `newline` argument
        because a Linux host cannot observe the difference by reading the file.
        """
        from unittest import mock

        captured: dict[str, object] = {}
        real_write_text = Path.write_text

        def spy(self: Path, data: str, *args: object, **kwargs: object) -> int:
            if self.name == "Makefile.assets":
                captured["newline"] = kwargs.get("newline")
            return real_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

        with mock.patch.object(Path, "write_text", spy):
            initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        self.assertEqual("\n", captured.get("newline"))

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
        log.write_text(
            "'AssetBundle' is not supported because the module AssetBundle"
            " is disabled in the build.\n"
        )
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

        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
        config = load_config(self.root / ".shamway.toml")
        self.assertEqual("OK", editor_matches_project("2022.3.62f2", config).status)
        self.assertEqual("OK", editor_matches_project("2022.3.62f2 (7670c08855a9)", config).status)
        self.assertEqual("FAIL", editor_matches_project("6000.5.9f1", config).status)

    def test_scaffold_pins_the_changeset_when_it_is_known(self) -> None:
        initialize(
            self.root,
            None,
            "example.unity3d",
            "2022.3.62f2",
            "7670c08855a9",
            bundle_source="unity",
        )
        version_file = (
            self.root
            / "tools"
            / "shamway"
            / "UnityProject"
            / "ProjectSettings"
            / "ProjectVersion.txt"
        )
        text = version_file.read_text()
        self.assertIn("m_EditorVersion: 2022.3.62f2", text)
        self.assertIn("m_EditorVersionWithRevision: 2022.3.62f2 (7670c08855a9)", text)

    def test_scaffold_omits_the_revision_line_when_the_changeset_is_unknown(self) -> None:
        # Unity writes that line itself on first open, so an unreachable
        # release service must not fail the scaffold.
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
        version_file = (
            self.root
            / "tools"
            / "shamway"
            / "UnityProject"
            / "ProjectSettings"
            / "ProjectVersion.txt"
        )
        text = version_file.read_text()
        self.assertIn("m_EditorVersion: 2022.3.62f2", text)
        self.assertNotIn("m_EditorVersionWithRevision", text)

    def test_doctor_runs_every_branch_including_the_editor_one(self) -> None:
        # A NameError in the editor branch survived until a real doctor run,
        # because no test ever configured UNITY_EDITOR.
        import os

        from sevendtd_asset_pipeline.doctor import run_doctor

        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
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

    def test_doctor_finds_windows_support_under_a_macos_app_bundle(self) -> None:
        """The macOS Hub layout keeps assemblies in Contents/, not MacOS/Data."""
        import os

        from sevendtd_asset_pipeline.doctor import run_doctor

        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
        contents = self.root / "Unity.app" / "Contents"
        macos = contents / "MacOS"
        macos.mkdir(parents=True)
        (contents / "Managed").mkdir()
        support = (
            contents
            / "PlaybackEngines"
            / "WindowsStandaloneSupport"
            / "UnityEditor.WindowsStandalone.Extensions.dll"
        )
        support.parent.mkdir(parents=True)
        support.write_bytes(b"")
        editor = macos / "Unity"
        editor.write_text("#!/bin/sh\necho 2022.3.62f2\n", encoding="utf-8")
        editor.chmod(0o755)
        os.environ["UNITY_EDITOR"] = str(editor)
        try:
            checks = run_doctor(load_config(self.root / CONFIG_NAME))
        finally:
            os.environ.pop("UNITY_EDITOR", None)
        windows = next(check for check in checks if check.name == "Windows support")
        self.assertEqual("OK", windows.status)
        # macOS exposes the temporary directory through /var while realpath
        # canonicalizes it to /private/var. The doctor is allowed to report
        # either spelling of the same file.
        self.assertEqual(support.resolve(), Path(windows.detail).resolve())

    def test_doctor_reports_the_synthesized_build_readiness(self) -> None:
        """The editorless writer answers three questions: revision, sources, UnityPy.

        This branch decided whether `shamway build` can write a bundle at all,
        and none of the Unity-project rows apply to it.
        """
        from sevendtd_asset_pipeline.capabilities import has_capability
        from sevendtd_asset_pipeline.doctor import run_doctor

        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="synthesized")
        config = load_config(self.root / CONFIG_NAME)

        from sevendtd_asset_pipeline.doctor import Check

        def by_name() -> dict[str, Check]:
            return {check.name: check for check in run_doctor(config)}

        # No game dir: the scaffolded [unity] version is WARN-grade evidence,
        # and the freshly scaffolded source folder holds only .gitkeep.
        checks = by_name()
        self.assertEqual("WARN", checks["Unity revision"].status)
        self.assertEqual("FAIL", checks["bundle sources"].status)
        self.assertIn("holds no assets", checks["bundle sources"].detail)
        writer = checks["writer"]
        self.assertEqual("FAIL" if not has_capability("UnityPy") else "OK", writer.status)

        (config.bundle_source_dir / "myModNote.txt").write_text("hello", encoding="utf-8")
        self.assertEqual("OK", by_name()["bundle sources"].status)

    def test_doctor_fails_a_synthesized_mod_with_no_revision_evidence(self) -> None:
        """A bundle carries the revision it claims; writing one with no answer is refused."""
        from sevendtd_asset_pipeline.doctor import failed, run_doctor

        initialize(self.root, None, "example.unity3d", "", bundle_source="synthesized")
        config = load_config(self.root / CONFIG_NAME)
        checks = run_doctor(config)
        self.assertTrue(failed(checks))
        revision = next(check for check in checks if check.name == "Unity revision")
        self.assertEqual("FAIL", revision.status)

    def test_config_rejects_resources_outside_mod_root(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config_file = self.root / ".shamway.toml"
        config_file.write_text(
            config_file.read_text().replace(
                'resources_dir = "Resources"', 'resources_dir = "../outside"'
            )
        )
        with self.assertRaisesRegex(PipelineError, "must stay below"):
            load_config(config_file)

    def test_config_rejects_a_foreign_schema_version(self) -> None:
        """A newer schema must fail loudly, not mis-parse into a silent corruption."""
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text().replace("schema_version = 1", "schema_version = 2")
        )
        with self.assertRaisesRegex(PipelineError, "schema_version"):
            load_config(config_file)

    def test_code_references_are_refused_on_a_bundle_free_mod(self) -> None:
        """A stem list implies assets inside a bundle; without one it can only lie."""
        initialize(self.root, None, None, "", bundle_source="none")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text().replace(
                'mod_root = "."', 'code_references = ["exampleThing"]\nmod_root = "."'
            )
        )
        with self.assertRaisesRegex(PipelineError, 'bundle_source = "none"'):
            load_config(config_file)

    def test_the_revision_gate_names_a_directory_that_is_not_an_install(self) -> None:
        game = self.root / "not-an-install"
        game.mkdir()
        with self.assertRaisesRegex(PipelineError, "is not a 7 Days to Die install"):
            from sevendtd_asset_pipeline.game import game_unity_version

            game_unity_version(game)

    def test_the_revision_gate_names_a_game_with_no_readable_bundle(self) -> None:
        """Unreadable candidates are skipped until the answer is 'none found'."""
        from sevendtd_asset_pipeline.game import game_unity_version

        game = self.root / "game"
        (game / "Data" / "Config").mkdir(parents=True)
        (game / "Data" / "Config" / "items.xml").write_text("<configs/>", encoding="utf-8")
        bundles = game / "Data" / "Bundles" / "Standalone"
        bundles.mkdir(parents=True)
        (bundles / "corrupt.unity3d").write_bytes(b"garbage")
        with self.assertRaisesRegex(PipelineError, "no readable UnityFS bundle"):
            game_unity_version(game)


class SynthesisPreflightTests(unittest.TestCase):
    """The editorless build path's refusals, which need no writer to reach."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _synthesized_config(self, unity_version: str = "2022.3.62f2") -> PipelineConfig:
        initialize(self.root, None, "example.unity3d", unity_version, bundle_source="synthesized")
        return load_config(self.root / CONFIG_NAME)

    def test_a_synthesis_without_any_revision_evidence_is_refused(self) -> None:
        """A bundle claims a revision; writing one that claims nothing is refused."""
        from sevendtd_asset_pipeline.build import expected_unity_version

        config = self._synthesized_config("")
        with self.assertRaisesRegex(PipelineError, "no Unity revision is known"):
            expected_unity_version(config)

    def test_an_unknown_build_target_is_named_with_the_known_ones(self) -> None:
        """The argument check fires before any writer work starts."""
        from sevendtd_asset_pipeline.build import synthesize_bundle

        config = self._synthesized_config()
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text(encoding="utf-8").replace(
                'target = "StandaloneWindows64"', 'target = "Dreamcast"'
            ),
            encoding="utf-8",
        )
        config = load_config(config_file)
        with self.assertRaisesRegex(PipelineError, "StandaloneWindows64"):
            synthesize_bundle(config)


class BuildPreflightTests(unittest.TestCase):
    """`run_build`'s editor checks fire before any editor is started."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        # Explicitly the editor lane: these are `run_build`'s Unity preflights,
        # which the default source never reaches.
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _config_without_host_environment(self, **overrides: str) -> PipelineConfig:
        """load_config resolves UNITY_EDITOR and SEVEN_DAYS_TO_DIE_DIR at load time."""
        import os
        from unittest import mock

        clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("UNITY_EDITOR", "SEVEN_DAYS_TO_DIE_DIR")
        }
        clean.update(overrides)
        with mock.patch.dict(os.environ, clean, clear=True):
            return load_config(self.root / CONFIG_NAME)

    def test_a_local_build_without_an_editor_is_refused_with_the_next_step(self) -> None:
        from sevendtd_asset_pipeline.build import run_build

        config = self._config_without_host_environment()
        with self.assertRaisesRegex(PipelineError, "UNITY_EDITOR is not configured"):
            run_build(config)

    def test_an_editor_that_cannot_be_executed_is_refused_before_use(self) -> None:
        import stat

        from sevendtd_asset_pipeline.build import run_build

        editor = self.root / "not-an-editor"
        editor.write_text("this is not executable", encoding="utf-8")
        editor.chmod(stat.S_IRUSR | stat.S_IWUSR)
        config = self._config_without_host_environment(UNITY_EDITOR=str(editor))
        with self.assertRaisesRegex(PipelineError, "not executable"):
            run_build(config)

    def test_a_project_at_the_wrong_revision_for_the_game_is_refused(self) -> None:
        from sevendtd_asset_pipeline.build import run_build

        game = self.root / "game"
        (game / "Data" / "Config").mkdir(parents=True)
        (game / "Data" / "Config" / "items.xml").write_text("<configs/>", encoding="utf-8")
        entities = game / "Data" / "Bundles" / "Standalone" / "Entities"
        entities.mkdir(parents=True)
        (entities / "Entities").write_bytes(unityfs_bundle([142], "2022.3.62f2"))
        editor = self.root / "fake-editor"
        editor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        editor.chmod(0o755)
        version_file = (
            self.root
            / "tools"
            / "shamway"
            / "UnityProject"
            / "ProjectSettings"
            / "ProjectVersion.txt"
        )
        version_file.write_text("m_EditorVersion: 2021.3.1f1\n", encoding="utf-8")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text(encoding="utf-8").replace(
                'directory = ""', f'directory = "{game.as_posix()}"', 1
            ),
            encoding="utf-8",
        )
        config = self._config_without_host_environment(UNITY_EDITOR=str(editor))
        with self.assertRaisesRegex(PipelineError, "installed game uses"):
            run_build(config)


class ConfigRejectionTests(unittest.TestCase):
    """The configuration parser's refusal lines, one per malformed shape.

    Everything in the pipeline reads this file, so a value of the wrong type
    must be named here rather than discovered as a TypeError three commands
    later. The happy paths are covered by every scaffold-based test above.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _load(self, body: str) -> None:
        config_file = self.root / CONFIG_NAME
        config_file.write_text(body, encoding="utf-8")
        load_config(config_file)

    def test_malformed_toml_is_a_named_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "cannot read"):
            self._load("schema_version = 1\nmod_name = \n")

    def test_an_empty_mod_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "mod_name"):
            self._load('schema_version = 1\nmod_name = ""\nbundle_source = "none"\n')

    def test_a_non_string_mod_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "mod_name"):
            self._load('schema_version = 1\nmod_name = 7\nbundle_source = "none"\n')

    def test_scalar_unity_and_game_sections_are_rejected(self) -> None:
        head = 'schema_version = 1\nmod_name = "M"\nbundle_source = "none"\n'
        with self.assertRaisesRegex(PipelineError, r"\[unity\] and \[game\] must be TOML tables"):
            self._load(head + "unity = 5\n")
        with self.assertRaisesRegex(PipelineError, r"\[unity\] and \[game\] must be TOML tables"):
            self._load(head + 'game = "nope"\n')

    def test_code_references_must_be_non_empty_stems(self) -> None:
        for body in (
            'schema_version = 1\nmod_name = "M"\n'
            'bundle_source = "synthesized"\nbundle_name = "m.unity3d"\n'
            'code_references = ["a", ""]\n',
            'schema_version = 1\nmod_name = "M"\n'
            'bundle_source = "synthesized"\nbundle_name = "m.unity3d"\n'
            'code_references = "exampleThing"\n',
        ):
            with (
                self.subTest(body=body),
                self.assertRaisesRegex(PipelineError, "code_references"),
            ):
                self._load(body)

    def test_an_empty_path_value_is_rejected(self) -> None:
        body = 'schema_version = 1\nmod_name = "M"\nbundle_source = "none"\nresources_dir = ""\n'
        with self.assertRaisesRegex(PipelineError, "resources_dir.*non-empty path string"):
            self._load(body)

    def test_a_config_that_does_not_exist_is_reported_with_the_search_root(self) -> None:
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        with self.assertRaisesRegex(PipelineError, f"could not find {CONFIG_NAME}.*{nested}"):
            load_config(nested / CONFIG_NAME)

    def test_bundle_source_dir_reads_against_the_right_base(self) -> None:
        """With a project the source sits inside it; without, against the mod."""
        for bundle_source, base in (("unity", "unity_project"), ("synthesized", "mod_root")):
            with (
                self.subTest(bundle_source=bundle_source),
                tempfile.TemporaryDirectory() as name,
            ):
                root = Path(name)
                (root / "ModInfo.xml").write_text(
                    '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
                )
                initialize(
                    root, None, "example.unity3d", "2022.3.62f2", bundle_source=bundle_source
                )
                config = load_config(root / CONFIG_NAME)
                expected_base = getattr(config, base)
                self.assertEqual(expected_base / config.source_root, config.bundle_source_dir)


needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"),
    "the synthesized backend needs UnityPy for the engine's type trees",
)


@needs_unitypy
class SynthesisStagingTests(unittest.TestCase):
    """`synthesize_bundle` is `run_build`'s editorless second half.

    The probe must stage exactly nothing — the same promise the Unity probe
    makes at minutes of cost — and the real run stages manifest-then-bundle
    through the same atomic copies and gates as `stage_bundle`.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="synthesized")
        self.config = load_config(self.root / CONFIG_NAME)
        source = self.config.bundle_source_dir
        source.mkdir(parents=True, exist_ok=True)
        (source / "myModNote.txt").write_text("hello", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_probe_writes_nothing_into_the_modlet(self) -> None:
        from sevendtd_asset_pipeline.build import synthesize_bundle

        built = synthesize_bundle(self.config, probe=True)
        self.assertEqual("probe", built.parent.name)
        self.assertTrue(built.is_file())
        self.assertFalse(self.config.bundle_output.exists())
        self.assertFalse(self.config.tracked_manifest.exists())

    def test_a_full_synthesis_gates_and_stages_both_artifacts(self) -> None:
        from sevendtd_asset_pipeline.build import synthesize_bundle
        from sevendtd_asset_pipeline.references import manifest_assets
        from sevendtd_asset_pipeline.unityfs import inspect_bundle

        staged = synthesize_bundle(self.config)
        self.assertEqual(self.config.bundle_output, staged)
        # The artifact staged is the artifact the gates just passed on.
        probe = synthesize_bundle(self.config, probe=True)
        self.assertEqual(probe.read_bytes(), staged.read_bytes())
        info = inspect_bundle(staged)
        self.assertTrue(info.has_assetbundle_object)
        self.assertEqual("2022.3.62f2", info.unity_version)
        self.assertEqual(["bundle/myModNote.txt"], manifest_assets(self.config.tracked_manifest))


MANIFEST = "ManifestFileVersion: 0\nAssets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n"


class UnityOptionalTests(unittest.TestCase):
    """The three ways a mod exists without a Unity editor on this machine.

    `bundle_source = "synthesized"` — the default — keeps the bundle and writes
    it here. `"external"` keeps the bundle and every gate that reads it, and
    moves only the editor elsewhere. `"none"` drops the bundle entirely, which
    is what an XML-and-icons modlet actually is.
    """

    def test_the_default_source_scaffolds_no_unity_project(self) -> None:
        """Unity is opt-in: an `init` that did not ask for it gets no editor.

        The default used to be `"unity"`, which put a Unity project and an
        editor requirement into every mod that never said it wanted one.
        """
        created = initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config = load_config(self.root / CONFIG_NAME)
        self.assertEqual("synthesized", config.bundle_source)
        self.assertFalse((self.root / "tools" / "shamway" / "UnityProject").exists())
        # Resolved on both sides: `initialize` resolves the mod root, and on
        # macOS the temporary directory is /var/... while its resolution is
        # /private/var/..., so comparing raw paths passes only on Linux.
        expected = (self.root / "assets-src" / "bundle").resolve()
        self.assertIn(expected, [path.resolve() for path in created])
        self.assertEqual(expected, config.bundle_source_dir.resolve())

    def test_adopting_a_project_is_itself_the_opt_in_to_unity(self) -> None:
        """`--adopt` must not need `--bundle-source unity` repeated after it.

        Pointing at a Unity project the mod already has says the editor lane is
        wanted. Defaulting to synthesized there would scaffold a mod beside a
        project nothing reads.
        """
        project = self.root / "Existing"
        (project / "Assets" / "ModAssets" / "Bundle").mkdir(parents=True)
        (project / "ProjectSettings").mkdir()
        (project / "Packages").mkdir()
        (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 2022.3.62f2\n", encoding="utf-8"
        )
        (project / "Packages" / "manifest.json").write_text(
            '{"dependencies": {"com.unity.modules.assetbundle": "1.0.0"}}', encoding="utf-8"
        )
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", adopt_project=project)
        self.assertEqual("unity", load_config(self.root / CONFIG_NAME).bundle_source)

    def test_render_config_defaults_source_root_per_bundle_source(self) -> None:
        """A shared literal default rendered a path that resolves nowhere.

        `source_root` is project-relative for "unity" and mod-relative for
        "synthesized", so one default could only be right for one of them —
        and `render_config` was defaulting to the Unity one for both. Only
        `initialize` substituted the right value, so every other caller wrote a
        configuration pointing at <mod>/Assets/ModAssets/Bundle.
        """
        from sevendtd_asset_pipeline.config import render_config

        synthesized = render_config("M", "m.unity3d", "2022.3.62f2", bundle_source="synthesized")
        self.assertIn('source_root = "assets-src/bundle"', synthesized)
        editor = render_config("M", "m.unity3d", "2022.3.62f2", bundle_source="unity")
        self.assertIn('source_root = "Assets/ModAssets/Bundle"', editor)
        explicit = render_config(
            "M", "m.unity3d", "2022.3.62f2", source_root="mine/here", bundle_source="synthesized"
        )
        self.assertIn('source_root = "mine/here"', explicit)

    def test_a_project_relative_source_root_without_a_project_is_refused(self) -> None:
        """Switching a mod off the editor lane must not silently misread source_root.

        `source_root` is project-relative for "unity" and mod-relative for
        everything else, so a configuration flipped without moving it resolves
        to <mod>/Assets/ModAssets/Bundle. The build error there said "create
        that folder", which is the wrong fix: the key has to change.
        """
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text().replace(
                'bundle_source = "unity"', 'bundle_source = "synthesized"'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PipelineError, "inside a Unity project"):
            load_config(config_file)

    def test_a_mod_root_assets_folder_that_exists_is_left_alone(self) -> None:
        """The check is about a path that resolves nowhere, not about its shape.

        A mod may legitimately keep its sources in `<mod>/Assets/...`; refusing
        that would break a layout nobody asked about.
        """
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="unity")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text().replace(
                'bundle_source = "unity"', 'bundle_source = "synthesized"'
            ),
            encoding="utf-8",
        )
        (self.root / "Assets" / "ModAssets" / "Bundle").mkdir(parents=True)
        self.assertEqual("synthesized", load_config(config_file).bundle_source)

    def test_a_stated_source_always_wins_over_both_defaults(self) -> None:
        initialize(self.root, None, None, "", bundle_source="none")
        self.assertEqual("none", load_config(self.root / CONFIG_NAME).bundle_source)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _external_mod(self) -> tuple[PipelineConfig, Path, Path]:
        """A scaffolded `bundle_source = "external"` modlet with a bundle to stage."""
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="external")
        config = load_config(self.root / CONFIG_NAME)
        built = self.root / "elsewhere"
        built.mkdir()
        bundle = built / "example.unity3d"
        bundle.write_bytes(unityfs_bundle([1, 142]))
        manifest = built / "example.unity3d.manifest"
        manifest.write_text(MANIFEST, encoding="utf-8")
        return config, bundle, manifest

    def test_stage_gates_and_stages_a_bundle_built_elsewhere(self) -> None:
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle, _ = self._external_mod()
        staged, skipped = stage_bundle(config, bundle)
        self.assertEqual(config.bundle_output, staged)
        self.assertEqual(bundle.read_bytes(), staged.read_bytes())
        self.assertEqual(MANIFEST, config.tracked_manifest.read_text())
        # An unrun gate must be reported, or it reads exactly like a passed one.
        self.assertTrue(any("build-log gate" in note for note in skipped))
        self.assertTrue(any("game-revision gate" in note for note in skipped))

    def test_stage_runs_the_build_log_gate_when_the_log_travels_with_the_bundle(self) -> None:
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle, _ = self._external_mod()
        log = self.root / "elsewhere" / "unity-build.log"
        log.write_text(
            "AssetBundle is not supported because the module Asset Bundle is disabled "
            "in the build\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PipelineError, "stripped engine-module classes"):
            stage_bundle(config, bundle, log=log)
        self.assertFalse(config.bundle_output.exists())

    def test_stage_rejects_a_bundle_without_the_class_142_object(self) -> None:
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle, _ = self._external_mod()
        bundle.write_bytes(unityfs_bundle([1]))
        with self.assertRaisesRegex(PipelineError, "class-142"):
            stage_bundle(config, bundle)
        self.assertFalse(config.bundle_output.exists())

    def test_stage_demands_the_manifest_that_describes_the_bundle(self) -> None:
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle, manifest = self._external_mod()
        manifest.unlink()
        with self.assertRaisesRegex(PipelineError, "no build manifest beside the bundle"):
            stage_bundle(config, bundle)

    def test_build_refuses_to_start_an_editor_for_an_external_bundle(self) -> None:
        from sevendtd_asset_pipeline.build import run_build

        config, _, _ = self._external_mod()
        with self.assertRaisesRegex(PipelineError, "shamway stage"):
            run_build(config)

    def test_a_bundle_free_mod_scaffolds_and_validates_without_unity(self) -> None:
        from sevendtd_asset_pipeline.doctor import failed, run_doctor

        created = initialize(self.root, None, None, "", bundle_source="none")
        self.assertNotIn("UnityProject", " ".join(str(path) for path in created))
        self.assertFalse((self.root / "tools" / "shamway" / "UnityProject").exists())
        config = load_config(self.root / CONFIG_NAME)
        self.assertFalse(config.has_bundle)
        (self.root / "Config").mkdir()
        report = validate_mod(config)
        self.assertIn("no bundle declared", report.messages[0])
        checks = run_doctor(config)
        self.assertFalse(failed(checks))
        # Nothing may nag about an editor this mod does not use.
        self.assertNotIn("Unity editor", {check.name for check in checks})

    def test_a_bundle_free_mod_rejects_xml_that_loads_from_a_bundle(self) -> None:
        initialize(self.root, None, None, "", bundle_source="none")
        config = load_config(self.root / CONFIG_NAME)
        config.config_dir.mkdir()
        (config.config_dir / "items.xml").write_text(
            '<configs><append xpath="/items"><item name="x"><property name="Meshfile" '
            'value="#@modfolder(ExampleMod):Resources/example.unity3d?exampleThing.prefab" />'
            "</item></append></configs>",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PipelineError, "load assets from a bundle"):
            validate_mod(config)

    def test_a_bundle_free_config_rejects_a_bundle_name(self) -> None:
        initialize(self.root, None, None, "", bundle_source="none")
        config_file = self.root / CONFIG_NAME
        # Inserted at the top: a key appended after the file's last [table]
        # would belong to that table, not to the document.
        config_file.write_text(
            config_file.read_text().replace(
                'mod_root = "."', 'mod_root = "."\nbundle_name = "example.unity3d"'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PipelineError, "must be empty"):
            load_config(config_file)

    def test_the_staged_bundle_paths_refuse_to_answer_without_a_bundle(self) -> None:
        # A caller that asks for the path anyway gets the configuration's own
        # answer, not a path into a directory that will never hold the file.
        initialize(self.root, None, None, "", bundle_source="none")
        config = load_config(self.root / CONFIG_NAME)
        with self.assertRaisesRegex(PipelineError, 'bundle_source = "none"'):
            _ = config.bundle_output
        with self.assertRaisesRegex(PipelineError, 'bundle_source = "none"'):
            _ = config.tracked_manifest

    def test_the_machine_may_override_where_the_bundle_is_built(self) -> None:
        # The same committed configuration is checked out on a build host with
        # an editor and on a machine without one.
        import os

        from sevendtd_asset_pipeline.config import BUNDLE_SOURCE_ENV

        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="external")
        os.environ[BUNDLE_SOURCE_ENV] = "unity"
        try:
            self.assertTrue(load_config(self.root / CONFIG_NAME).builds_locally)
            os.environ[BUNDLE_SOURCE_ENV] = "none"
            with self.assertRaisesRegex(PipelineError, "may only be"):
                load_config(self.root / CONFIG_NAME)
        finally:
            os.environ.pop(BUNDLE_SOURCE_ENV, None)

    def test_the_machine_may_not_give_a_bundle_free_mod_a_bundle(self) -> None:
        import os

        from sevendtd_asset_pipeline.config import BUNDLE_SOURCE_ENV

        initialize(self.root, None, None, "", bundle_source="none")
        os.environ[BUNDLE_SOURCE_ENV] = "unity"
        try:
            with self.assertRaisesRegex(PipelineError, "ships no bundle"):
                load_config(self.root / CONFIG_NAME)
        finally:
            os.environ.pop(BUNDLE_SOURCE_ENV, None)

    def test_an_unknown_bundle_source_is_rejected_with_the_alternatives(self) -> None:
        initialize(self.root, None, "example.unity3d", "2022.3.62f2")
        config_file = self.root / CONFIG_NAME
        config_file.write_text(
            config_file.read_text().replace(
                'bundle_source = "synthesized"', 'bundle_source = "somehow"'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PipelineError, "bundle_source must be one of"):
            load_config(config_file)


if __name__ == "__main__":
    unittest.main()
