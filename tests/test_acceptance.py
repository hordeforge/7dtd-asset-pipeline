"""The generated client-side acceptance provider.

The provider is what turns "the offline gates passed" into "the game loaded
it", so the thing that must never silently drift is the mapping from bundle
membership to cases: a member with no case is a member nobody proved.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import acceptance
from sevendtd_asset_pipeline.config import PipelineConfig
from sevendtd_asset_pipeline.errors import PipelineError


def _mod(root: Path, assets: list[str], mod_name: str = "ExampleMod") -> PipelineConfig:
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
            bundle_source="synthesized",
        ),
        encoding="utf-8",
    )
    manifest = root / "tools/shamway/manifests/examplemod.unity3d.manifest"
    body = "ManifestFileVersion: 0\nAssetBundleManifest: examplemod.unity3d\nAssets:\n"
    body += "".join(f"- bundle/{asset}\n" for asset in assets)
    manifest.write_text(body + "Dependencies: []\n", encoding="utf-8")
    return load_config(root / ".shamway.toml")


class PlanTests(unittest.TestCase):
    def test_every_manifest_member_becomes_a_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png", "blast.wav", "data.json"])
            planned = acceptance.plan(config)
            self.assertEqual(
                [("panel", "Texture2D"), ("blast", "AudioClip"), ("data", "TextAsset")],
                list(planned.stems),
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
            self.assertEqual(first, second)
            self.assertTrue(all(acceptance.PROVIDER_DIRECTORY in str(p) for p in first))


class InjectionTests(unittest.TestCase):
    """Manifest stems and mod names are untrusted: they can arrive from an
    editor on another machine (`shamway stage`) or from a vendored ModInfo.xml,
    and they land in C# source the live client executes."""

    def _plan_with_stem(self, tmp: Path, stem: str):
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
            source = acceptance.render(self._plan_with_stem(tmp, stem))[
                "ExampleModAcceptance.cs"
            ]
        self.assertIn(acceptance._cs_body(stem), source)

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
        self.assertIn('"#@modfolder(Evil\\"Mod):Resources/examplemod.unity3d"', source.replace("\n        ", ""))
        ET.fromstring(files["ModInfo.xml"])  # must still parse
        self.assertIn('value="Evil&quot;Mod bundle acceptance"', files["ModInfo.xml"])

    def test_a_mod_name_with_markup_cannot_escape_the_project_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = _mod(Path(tmp), ["panel.png"], mod_name="Evil&lt;/Name&gt;--&gt;&lt;Target&gt;")
            planned = acceptance.plan(config)
            project = acceptance.render(planned)[f"{planned.assembly}.csproj"]
        # Exactly the template's own two comment terminators; the name may
        # not add a third, so injected markup can only ever sit inside a
        # comment.
        self.assertEqual(project.count("-->"), 2)


class RegistryTests(unittest.TestCase):
    def test_every_writer_kind_has_a_detail_line(self) -> None:
        kinds = {kind for kind, _ in acceptance.ASSET_CASES.values()}
        self.assertEqual(kinds, set(acceptance.ASSET_DETAILS))

    def test_the_synthesizable_extensions_all_have_cases(self) -> None:
        """A bundle this tool can write must be a bundle it can prove."""
        from sevendtd_asset_pipeline.bundle_writer import ASSET_KINDS

        for suffix, kind in ASSET_KINDS.items():
            with self.subTest(suffix):
                self.assertIn(suffix, acceptance.ASSET_CASES)
                self.assertEqual(kind, acceptance.ASSET_CASES[suffix][0])


if __name__ == "__main__":
    unittest.main()
