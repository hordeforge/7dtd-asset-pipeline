"""What a second `shamway stage` does, and a second `build`.

Staging is the one write an agent, a CI job, and a person all perform against
the same modlet, and a retry after a lost terminal is the normal way it runs
twice. The property is convergence: the second run must end in the state the
first produced, and it must not accumulate anything beside the two artifacts
it owns.

The editorless synthesis is the same claim one layer down. Its writer is
deterministic by construction (fixed revision, fixed target, seeded pack), and
that is an assumption the staged bytes are what check; a writer that leaked a
timestamp or a directory listing would publish a different bundle on every run
and every diff of the modlet would read as a real change.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fixtures import unityfs_bundle

from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.config import CONFIG_NAME, PipelineConfig, load_config
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scaffold import initialize

MANIFEST = "ManifestFileVersion: 0\nAssets:\n- Assets/ModAssets/Bundle/exampleThing.prefab\n"


class StagingRerunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _external_mod(self) -> tuple[PipelineConfig, Path]:
        """A scaffolded `bundle_source = "external"` modlet and a bundle to stage."""
        initialize(self.root, None, "example.unity3d", "2022.3.62f2", bundle_source="external")
        config = load_config(self.root / CONFIG_NAME)
        built = self.root / "elsewhere"
        built.mkdir()
        bundle = built / "example.unity3d"
        bundle.write_bytes(unityfs_bundle([1, 142]))
        (built / "example.unity3d.manifest").write_text(MANIFEST, encoding="utf-8")
        return config, bundle

    def _modlet(self, config: PipelineConfig) -> dict[str, bytes]:
        return {
            path.relative_to(config.mod_root).as_posix(): path.read_bytes()
            for path in sorted(config.mod_root.rglob("*"))
            if path.is_file()
        }

    def test_a_second_stage_of_the_same_bundle_changes_nothing(self) -> None:
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle = self._external_mod()
        stage_bundle(config, bundle)
        first = self._modlet(config)
        # Two equal trees also describe a stage that published nothing, so
        # name the artifacts the comparison is supposed to be about.
        self.assertIn("Resources/example.unity3d", first)
        self.assertIn("tools/shamway/manifests/example.unity3d.manifest", first)
        stage_bundle(config, bundle)
        self.assertEqual(first, self._modlet(config))
        # A temporary name that outlived its run would be a third artifact the
        # modlet carries, and the next stage would carry one more.
        self.assertFalse([name for name in first if ".tmp." in name or ".old." in name])

    def test_a_rerun_reports_the_same_unrun_gates(self) -> None:
        """The second run is a fresh run: it re-derives what it could not check.

        A rerun that inherited the first run's gate list would report a build
        log as unrun when one was supplied this time, and the next reader
        would read a green line as one the second attempt established.
        """
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle = self._external_mod()
        log = self.root / "elsewhere" / "unity-build.log"
        log.write_text("Build succeeded\n", encoding="utf-8")
        _, without_log = stage_bundle(config, bundle)
        _, with_log = stage_bundle(config, bundle, log=log)
        self.assertTrue(any("build-log gate" in note for note in without_log))
        self.assertFalse(any("build-log gate" in note for note in with_log))

    def test_the_staged_artifact_is_itself_refused_as_input(self) -> None:
        """The guard that makes a rerun safe: staging what is already staged.

        Re-staging the modlet's own bundle would compare the file against
        itself and report success for work nothing did, and a caller reading
        that as a fresh build would carry the previous bytes forward believing
        they were new.
        """
        from sevendtd_asset_pipeline.build import stage_bundle

        config, bundle = self._external_mod()
        stage_bundle(config, bundle)
        with self.assertRaisesRegex(PipelineError, "already the staged bundle"):
            stage_bundle(config, config.bundle_output)


@unittest.skipUnless(
    has_capability("unityz"),
    "the synthesized backend needs unityz for the engine's type trees",
)
class SynthesisRerunTests(unittest.TestCase):
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

    def test_a_second_synthesis_publishes_the_same_bytes(self) -> None:
        from sevendtd_asset_pipeline.build import synthesize_bundle

        first_bundle = synthesize_bundle(self.config).read_bytes()
        first_manifest = self.config.tracked_manifest.read_bytes()
        second = synthesize_bundle(self.config)
        self.assertEqual(first_bundle, second.read_bytes())
        self.assertEqual(first_manifest, self.config.tracked_manifest.read_bytes())
