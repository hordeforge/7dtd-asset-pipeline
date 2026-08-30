"""The generated client-side acceptance provider.

The provider is what turns "the offline gates passed" into "the game loaded
it", so the thing that must never silently drift is the mapping from bundle
membership to cases: a member with no case is a member nobody proved.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fixtures import static_triangle_glb

from sevendtd_asset_pipeline import acceptance
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.config import PipelineConfig
from sevendtd_asset_pipeline.errors import PipelineError


def _mod(
    root: Path,
    assets: list[str],
    mod_name: str = "ExampleMod",
    bundle_source: str = "synthesized",
) -> PipelineConfig:
    from sevendtd_asset_pipeline.config import load_config, render_config

    (root / "Config").mkdir(parents=True, exist_ok=True)
    (root / "Resources").mkdir(parents=True, exist_ok=True)
    (root / "tools/shamway/manifests").mkdir(parents=True, exist_ok=True)
    (root / "ModInfo.xml").write_text(
        f'<?xml version="1.0"?><xml><Name value="{mod_name}" /></xml>', encoding="utf-8"
    )
    (root / ".shamway.toml").write_text(
        render_config(
            mod_name=mod_name,
            bundle_name="examplemod.unity3d",
            unity_version="2022.3.62f2",
            bundle_source=bundle_source,
        ),
        encoding="utf-8",
    )
    manifest = root / "tools/shamway/manifests/examplemod.unity3d.manifest"
    body = "ManifestFileVersion: 0\nAssetBundleManifest: examplemod.unity3d\nAssets:\n"
    body += "".join(f"- bundle/{asset}\n" for asset in assets)
    manifest.write_text(body + "Dependencies: []\n", encoding="utf-8")
    # A synthesized provider is derived from the source folder, not from the
    # manifest, because only the writer knows that `prop.glb` becomes a prefab
    # named `prop` plus `prop_mesh` and `prop_mat`. Non-mesh files need only
    # exist and carry the right suffix. A `.glb` is parsed for hierarchy/skin,
    # so the dummy has to be a real static triangle, not empty bytes.
    source_dir = root / "assets-src" / "bundle"
    source_dir.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        dest = source_dir / asset
        if dest.suffix.lower() in {".glb", ".gltf"}:
            static_triangle_glb(dest)
        else:
            dest.write_bytes(b"")
    return load_config(root / ".shamway.toml")


class PlanTests(unittest.TestCase):
    def test_every_manifest_member_becomes_a_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png", "blast.wav", "data.json"])
            planned = acceptance.plan(config)
            # Membership, not order: a real manifest is written from a sorted
            # scan, and the synthesized route derives its names from the same
            # scan, so pinning the hand-written fixture's order asserted
            # something neither producer promises.
            self.assertEqual(
                {("panel", "Texture2D"), ("blast", "AudioClip"), ("data", "TextAsset")},
                set(planned.stems),
            )
            self.assertEqual("ExampleMod", planned.mod_name)
            self.assertEqual("Resources/examplemod.unity3d", planned.bundle_uri_path)

    def test_a_member_with_no_known_case_is_refused_not_skipped(self) -> None:
        """Silently dropping it would report a green run that proved less."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png", "mystery.shader"])
            with self.assertRaises(PipelineError) as raised:
                acceptance.plan(config)
            self.assertIn("mystery.shader", str(raised.exception))

    def test_a_missing_manifest_names_the_command_that_writes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png"])
            Path(config.tracked_manifest).unlink()
            with self.assertRaises(PipelineError) as raised:
                acceptance.plan(config)
            self.assertIn("shamway build", str(raised.exception))


class EditorBuiltManifestTests(unittest.TestCase):
    """The manifest route of `plan()`: the half an editor-built mod takes.

    A synthesized mod derives its cases from its source folder, but a mod whose
    bundle is built elsewhere (`external`, or a local editor) has no source
    folder here: `shamway stage`'s tracked manifest is the only membership list,
    and these cases are read from it.
    """

    def _external_mod(self, root: Path, assets: list[str]) -> PipelineConfig:
        return _mod(root, assets, bundle_source="external")

    def test_every_manifest_member_becomes_a_case_by_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = self._external_mod(Path(tmp), ["panel.png", "blast.wav", "prop.prefab"])
            planned = acceptance.plan(config)
        self.assertEqual(
            {("panel", "Texture2D"), ("blast", "AudioClip"), ("prop", "GameObject")},
            set(planned.stems),
        )

    def test_an_unknown_manifest_extension_is_refused_with_the_known_ones(self) -> None:
        """The same refusal rule the synthesized route enforces, from the manifest."""
        with tempfile.TemporaryDirectory() as tmp:
            config = self._external_mod(Path(tmp), ["panel.png", "mystery.shader"])
            with self.assertRaises(PipelineError) as raised:
                acceptance.plan(config)
        message = str(raised.exception)
        self.assertIn("mystery.shader", message)
        self.assertIn(".png", message, "the known extensions must be listed for the author")


class SynthesizedNamingTests(unittest.TestCase):
    """The provider must ask for the names the writer actually emits.

    Found by running the suite in a live client: the provider mapped `.glb` to
    `LoadAsset<Mesh>` at the bare stem, but since the shader lane landed the
    prefab owns that stem and the mesh moved to `<stem>_mesh`. The client
    correctly answered null, and a perfectly good bundle read as a failure:

        shamwayPropProof: LoadAsset<Mesh> returned null
        FAIL shamwaypropproof_bundle/load_shamwayPropProof
    """

    def _cases(self, assets: list[str]) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as name:
            return dict(acceptance.plan(_mod(Path(name), assets)).stems)

    @unittest.skipUnless(
        has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
    )
    def test_a_mesh_source_is_asked_for_as_the_prefab_the_game_resolves(self) -> None:
        cases = self._cases(["prop.glb", "prop_albedo.png"])
        self.assertEqual("GameObject", cases["prop"], "Meshfile resolves a prefab, not a Mesh")
        self.assertEqual("Mesh", cases["prop_mesh"])
        self.assertEqual("Material", cases["prop_mat"])
        self.assertEqual("Texture2D", cases["prop_albedo"])

    @unittest.skipUnless(
        has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
    )
    def test_the_shader_gets_no_case(self) -> None:
        """It has no stem a mod asks for, and LoadAsset<Shader> is not how it is reached."""
        self.assertNotIn("Shader", set(self._cases(["prop.glb"]).values()))

    def test_a_non_mesh_source_still_takes_its_own_stem(self) -> None:
        cases = self._cases(["beep.wav", "notes.txt", "panel.png"])
        self.assertEqual({"beep": "AudioClip", "notes": "TextAsset", "panel": "Texture2D"}, cases)


class MixedVisualSuiteTests(unittest.TestCase):
    """Prefab-look and block-place are different pictures. Never one list."""

    def test_look_plus_block_is_mixed(self) -> None:
        self.assertTrue(acceptance.mixed_visual_suites("mod_look,mod_block_model"))
        self.assertTrue(acceptance.mixed_visual_suites("mod_block_place; mod_look"))
        self.assertTrue(acceptance.mixed_visual_suites("a_look a_block_model"))

    def test_load_plus_block_is_not_mixed(self) -> None:
        self.assertFalse(acceptance.mixed_visual_suites("mod_bundle,mod_block_model"))
        self.assertFalse(acceptance.mixed_visual_suites("mod_look"))
        self.assertFalse(acceptance.mixed_visual_suites("mod_block_model"))
        self.assertFalse(acceptance.mixed_visual_suites(""))

    def test_a_mixed_list_is_refused_by_name(self) -> None:
        with self.assertRaisesRegex(PipelineError, "different pictures"):
            acceptance.reject_mixed_visual_suites("self_look,self_block_model")


class RenderTests(unittest.TestCase):
    def test_the_rendered_source_carries_the_uri_the_engine_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png", "blast.wav"])
            files = acceptance.render(acceptance.plan(config))
            source = files["ExampleModAcceptance.cs"]
            self.assertIn(
                '"#@modfolder(ExampleMod):Resources/examplemod.unity3d"',
                source.replace("\n        ", ""),
            )
            self.assertIn('DataLoader.LoadAsset<Texture2D>(Bundle + "?panel")', source)
            self.assertIn('DataLoader.LoadAsset<AudioClip>(Bundle + "?blast")', source)
            self.assertIn("IScenarioProvider", source)
            self.assertIn('yield return "examplemod_bundle"', source)
            self.assertNotIn("examplemod_look", source)
            self.assertNotIn("Instantiate", source)

    def test_an_absent_stem_case_is_always_present(self) -> None:
        """Without it, a loader answering every request would read as a pass."""
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png"])
            source = acceptance.render(acceptance.plan(config))["ExampleModAcceptance.cs"]
            self.assertIn(acceptance.ABSENT_STEM, source)
            self.assertIn("absent_stem_is_null", source)

    def test_the_project_references_the_harness_and_the_game(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png"])
            project = acceptance.render(acceptance.plan(config))["ExampleModAcceptance.csproj"]
            self.assertIn("$(PlaytestHarnessPath)", project)
            self.assertIn("$(GameManagedDir)/Assembly-CSharp.dll", project)
            self.assertIn("Unity.Addressables", project)

    def test_writing_is_idempotent_and_lands_under_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png"])
            planned = acceptance.plan(config)
            first = acceptance.write(planned)
            second = acceptance.write(planned)
            self.assertTrue(first, "write produced no files; idempotence over nothing")
            self.assertEqual(first, second)
            self.assertTrue(all(acceptance.PROVIDER_DIRECTORY in str(p) for p in first))
            names = {p.name for p in first}
            self.assertIn(f"{planned.assembly}.cs", names)
            self.assertIn(f"{planned.assembly}.csproj", names)


class InjectionTests(unittest.TestCase):
    """Manifest stems and mod names are untrusted: they can arrive from an
    editor on another machine (`shamway stage`) or from a vendored ModInfo.xml,
    and they land in C# source the live client executes."""

    def _plan_with_stem(self, tmp: str | Path, stem: str) -> acceptance.ProviderPlan:
        config = _mod(Path(tmp), ["panel.png"])
        planned = acceptance.plan(config)
        return acceptance.ProviderPlan(
            directory=planned.directory,
            assembly=planned.assembly,
            suite_id=planned.suite_id,
            mod_name=planned.mod_name,
            bundle_uri_path=planned.bundle_uri_path,
            stems=((stem, "Texture2D"),),
        )

    def test_a_stem_cannot_break_out_of_the_generated_string_literals(self) -> None:
        hostile = 'x" ; System.Console.WriteLine("pwned"); var y = "'
        with tempfile.TemporaryDirectory() as tmp:
            source = acceptance.render(self._plan_with_stem(tmp, hostile))[
                "ExampleModAcceptance.cs"
            ]
        # The stem survives exactly, only escaped...
        self.assertIn(acceptance._cs_body(hostile), source)
        # ...and every double quote in the file still closes its literal, so
        # nothing outside a string can have terminated one early.
        self.assertEqual(source.count('"') % 2, 0)

    def test_control_characters_in_a_stem_are_escaped_not_embedded_raw(self) -> None:
        stem = "bad\tname\rx"
        with tempfile.TemporaryDirectory() as tmp:
            source = acceptance.render(self._plan_with_stem(tmp, stem))["ExampleModAcceptance.cs"]
        self.assertIn(acceptance._cs_body(stem), source)

    def test_control_characters_without_a_named_escape_become_unicode_escapes(self) -> None:
        """A control byte a C# literal cannot carry raw (a NUL from a mangled
        filename, an ESC) must not reach the generated source unescaped."""
        escaped = acceptance._cs_body("a\x00b\x1bc\x7fd")
        self.assertEqual("a\\u0000b\\u001bc\\u007fd", escaped)
        self.assertNotIn("\x00", escaped)

    def test_a_non_identifier_stem_yields_a_valid_local_variable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = acceptance.render(self._plan_with_stem(tmp, "blast-loop"))[
                "ExampleModAcceptance.cs"
            ]
        self.assertIn("blastloopLoaded", source)
        self.assertNotIn("-loopLoaded", source)

    def test_a_mod_name_with_quotes_cannot_break_the_bundle_literal_or_xml(self) -> None:
        import xml.etree.ElementTree as ET

        with tempfile.TemporaryDirectory() as tmp:
            # The fixture stores the entity form; read_mod_name decodes it back
            # to a raw quote, which render must then re-escape.
            config = _mod(Path(tmp), ["panel.png"], mod_name="Evil&quot;Mod")
            planned = acceptance.plan(config)
            files = acceptance.render(planned)
        source = files[f"{planned.assembly}.cs"]
        self.assertIn(
            '"#@modfolder(Evil\\"Mod):Resources/examplemod.unity3d"',
            source.replace("\n        ", ""),
        )
        # Self-generated bytes under test, not attacker input: stdlib ET is
        # exactly the parser the game-adjacent tooling uses.
        ET.fromstring(files["ModInfo.xml"])  # noqa: S314 - parses our own output
        self.assertIn('value="Evil&quot;Mod bundle acceptance"', files["ModInfo.xml"])

    def test_a_mod_name_with_markup_cannot_escape_the_project_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(
                Path(tmp), ["panel.png"], mod_name="Evil&lt;/Name&gt;--&gt;&lt;Target&gt;"
            )
            planned = acceptance.plan(config)
            project = acceptance.render(planned)[f"{planned.assembly}.csproj"]
        # Exactly the template's own two comment terminators; the name may
        # not add a third, so injected markup can only ever sit inside a
        # comment.
        self.assertEqual(project.count("-->"), 2)


class RegistryTests(unittest.TestCase):
    def test_every_writer_kind_has_a_detail_line(self) -> None:
        kinds = set(acceptance.ASSET_CASES.values())
        self.assertEqual(kinds, set(acceptance.ASSET_DETAILS))

    def test_the_synthesizable_extensions_all_have_cases(self) -> None:
        """A bundle this tool can write must be a bundle it can prove."""
        from sevendtd_asset_pipeline.bundle_writer import ASSET_KINDS

        for suffix, kind in ASSET_KINDS.items():
            with self.subTest(suffix):
                self.assertIn(suffix, acceptance.ASSET_CASES)
                self.assertEqual(kind, acceptance.ASSET_CASES[suffix])


def _mod_with_motions(root: Path, assets: list[str], motions: dict[str, str]) -> PipelineConfig:
    """`_mod` plus an `[acceptance] motion_kinds` declaration."""
    from sevendtd_asset_pipeline.config import load_config

    _mod(root, assets)
    config_path = root / ".shamway.toml"
    body = config_path.read_text(encoding="utf-8")
    declared = ", ".join(f'"{stem}" = "{kind}"' for stem, kind in motions.items())
    config_path.write_text(
        body + f"\n[acceptance]\nmotion_kinds = {{ {declared} }}\n", encoding="utf-8"
    )
    return load_config(config_path)


class MotionKindTests(unittest.TestCase):
    """The `[acceptance] motion_kinds` field and the cases it generates."""

    @unittest.skipUnless(
        has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
    )
    def test_a_turntable_kind_generates_a_staged_clip_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _mod_with_motions(root, ["prop.glb"], {"prop": "turntable"})
            plan_ = acceptance.plan(config)
            self.assertEqual((("prop", "turntable"),), plan_.motions)
            source = acceptance.render(plan_)[f"{plan_.assembly}.cs"]
            self.assertIn("CaseDef.StagedClip", source)
            self.assertIn('"motion_prop"', source)
            self.assertIn("staged.transform.Rotate(0f, 360f * Time.deltaTime / 12f, 0f)", source)
            # The load case survives: a clip is motion evidence, not the load gate.
            self.assertIn("load_prop", source)

    @unittest.skipUnless(
        has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
    )
    def test_a_fixed_kind_generates_the_unchanged_look_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _mod_with_motions(root, ["prop.glb"], {"prop": "fixed"})
            plan_ = acceptance.plan(config)
            source = acceptance.render(plan_)[f"{plan_.assembly}.cs"]
            self.assertNotIn("CaseDef.StagedClip", source)
            self.assertIn('CaseDef.Staged(label, "look_prop"', source)
            self.assertIn("ahead * 3.5f", source)
            self.assertNotIn("ahead * 1.2f", source)
            self.assertIn('yield return "examplemod_look"', source)
            self.assertIn('if (suite == "examplemod_look")', source)
            self.assertLess(
                source.index('if (suite == "examplemod_look")'),
                source.index("Instantiate"),
            )
            self.assertIn("RejectMixedVisualSuites", source)
            self.assertIn("different pictures", source)

    def test_absent_motion_kinds_leave_generation_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = _mod(root, ["prop.glb"])
            declared = _mod_with_motions(root, ["prop.glb"], {})
            self.assertEqual(
                acceptance.render(acceptance.plan(plain)),
                acceptance.render(acceptance.plan(declared)),
            )

    @unittest.skipUnless(
        has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
    )
    def test_a_walk_cycle_kind_equips_walks_and_records_the_player(self) -> None:
        """A walk cycle cannot be staged: the case equips the item on the
        player, drives a real walk, and records it with the on-demand clip
        recorder."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _mod_with_motions(root, ["prop.glb"], {"prop": "walk-cycle"})
            source = acceptance.render(acceptance.plan(config))[
                f"{acceptance.plan(config).assembly}.cs"
            ]
            self.assertIn("CaseDef.Live", source)
            self.assertIn('Helpers.TryEquipItem(player, "prop")', source)
            self.assertIn('Helpers.BeginClip("motion_prop", 2, 4)', source)
            self.assertIn("Helpers.StartWalk(1f)", source)
            self.assertIn("Helpers.StopWalk()", source)
            self.assertIn('Helpers.EndClip("motion_prop")', source)
            # A walk is the game's own animation; nothing here stages or spins.
            self.assertNotIn("CaseDef.StagedClip", source)
            self.assertNotIn("Rotate(0f, 360f", source)

    def test_a_kind_on_a_non_prefab_member_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _mod_with_motions(root, ["prop.glb", "tile.png"], {"tile": "turntable"})
            with self.assertRaisesRegex(PipelineError, "loads as Texture2D"):
                acceptance.plan(config)

    def test_a_kind_on_an_unknown_stem_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _mod_with_motions(root, ["prop.glb"], {"nope": "turntable"})
            with self.assertRaisesRegex(PipelineError, "not a bundle member"):
                acceptance.plan(config)


if __name__ == "__main__":
    unittest.main()
