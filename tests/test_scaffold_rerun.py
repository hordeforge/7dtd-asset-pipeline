"""What a second `shamway init` does.

`init` is the one setup command a mod author re-runs by hand: after a failure,
after a pipeline upgrade, after changing their mind about an argument. A
scaffold that refuses on mere existence made every one of those a dead end,
because the leftovers a half-finished run leaves are exactly the files whose
presence the check was reading.

The property under test is convergence. Running `init` twice with the same
arguments must end in the state one run produces, and must never overwrite a
file the mod owns.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scaffold import default_bundle_name, initialize

BUNDLE_SOURCES = ("synthesized", "none", "unity")


class ScaffoldRerunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "ModInfo.xml").write_text(
            '<xml><Name value="ExampleMod" /></xml>', encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _init(self, source: str = "synthesized", **overrides: object) -> list[Path]:
        options: dict[str, object] = {
            "bundle_name": "example.unity3d",
            "unity_version": "2022.3.62f2",
            "bundle_source": source,
        }
        options.update(overrides)
        return initialize(self.root, "ExampleMod", **options)  # type: ignore[arg-type]

    def _tree(self) -> dict[str, bytes]:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def test_a_second_init_with_the_same_arguments_changes_nothing(self) -> None:
        """The whole claim: a rerun is a verified no-op, not an error.

        Asserted on the bytes of every file, so "nothing changed" means nothing
        changed rather than "the run happened to raise".
        """
        for source in BUNDLE_SOURCES:
            with self.subTest(bundle_source=source):
                self.setUp()
                published = self._init(source)
                after_first = self._tree()
                # An `initialize` that published nothing would make both trees
                # identical and the comparison below true for the wrong reason.
                self.assertIn(".shamway.toml", after_first)
                self.assertTrue(published, f"init({source}) reported no written files")
                self.assertGreater(len(after_first), 3, f"init({source}) scaffolded almost nothing")
                self._init(source)
                self.assertEqual(after_first, self._tree())

    def test_a_run_interrupted_halfway_is_resumed_by_the_next_one(self) -> None:
        """A failure part way through must not strand a mod no rerun can finish.

        The failure lands on the agent guide, after the config and the makefile
        are already published, which is the shape that used to leave a mod
        permanently un-scaffoldable.
        """
        real = Path.write_text

        def die_on_the_guide(self: Path, *args: object, **kwargs: object) -> int:
            if self.name == "AGENTS.md" and self.parent.name == "shamway":
                raise OSError("no space left on device")
            return real(self, *args, **kwargs)  # type: ignore[arg-type]

        with mock.patch.object(Path, "write_text", die_on_the_guide), self.assertRaises(OSError):
            self._init("synthesized")
        self.assertFalse((self.root / "tools" / "shamway" / "AGENTS.md").is_file())
        self._init("synthesized")
        guide = self.root / "tools" / "shamway" / "AGENTS.md"
        self.assertTrue(guide.is_file())
        self.assertIn("shamway", guide.read_text(encoding="utf-8"))

    def test_an_interrupted_project_copy_is_completed_by_the_next_run(self) -> None:
        source = "unity"
        self._init(source)
        project = self.root / "tools" / "shamway" / "UnityProject"
        missing = next(
            path
            for path in sorted(project.rglob("*"))
            if path.is_file() and path.name != "ProjectVersion.txt"
        )
        relative = missing.relative_to(project)
        missing.unlink()
        self._init(source)
        self.assertTrue((project / relative).is_file())

    def test_a_file_the_mod_edited_is_refused_not_overwritten(self) -> None:
        config = self.root / ".shamway.toml"
        self._init("synthesized")
        config.write_text(config.read_text(encoding="utf-8") + "\n# tuned by hand\n")
        edited = config.read_text(encoding="utf-8")
        with self.assertRaises(PipelineError) as raised:
            self._init("synthesized")
        self.assertIn(".shamway.toml", str(raised.exception))
        self.assertEqual(edited, config.read_text(encoding="utf-8"))

    def test_a_project_file_the_mod_edited_is_refused_not_overwritten(self) -> None:
        source = "unity"
        self._init(source)
        project = self.root / "tools" / "shamway" / "UnityProject"
        edited = next(
            path for path in sorted(project.rglob("*")) if path.is_file() and path.suffix == ".cs"
        )
        mine = edited.read_bytes() + b"\n// the mod's own\n"
        edited.write_bytes(mine)
        with self.assertRaises(PipelineError) as raised:
            self._init(source)
        self.assertIn("UnityProject", str(raised.exception))
        self.assertEqual(mine, edited.read_bytes())

    def test_a_rerun_with_different_arguments_still_refuses(self) -> None:
        """Convergence is re-running the same scaffold, not adopting over one.

        A different bundle name is a different scaffold, and silently rewriting
        the config under it would be the destructive half of this change.
        """
        self._init("synthesized")
        with self.assertRaises(PipelineError):
            self._init("synthesized", bundle_name="renamed.unity3d")

    def test_the_mods_own_files_under_the_project_survive_a_rerun(self) -> None:
        source = "unity"
        self._init(source)
        art = self.root / "tools/shamway/UnityProject/Assets/ModAssets/Bundle/thing.png"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_bytes(b"the design")
        self._init(source)
        self.assertEqual(b"the design", art.read_bytes())

    def test_a_missing_template_file_reads_as_resumable_not_as_a_conflict(self) -> None:
        """The settled check ignores absence; only a differing byte conflicts."""
        source = "unity"
        self._init(source)
        project = self.root / "tools" / "shamway" / "UnityProject"
        shutil_targets = [p for p in sorted(project.rglob("*")) if p.is_file()]
        self.assertTrue(shutil_targets)
        for path in shutil_targets:
            path.unlink()
        self._init(source)
        self.assertEqual(
            sorted(path.relative_to(project).as_posix() for path in shutil_targets),
            sorted(
                path.relative_to(project).as_posix()
                for path in project.rglob("*")
                if path.is_file()
            ),
        )


class BundleNameTests(unittest.TestCase):
    """The bundle stem 7DTD looks an asset up by.

    A file-stem collision is what makes one mod's assets unreachable, so two
    mod names must not derive one bundle name. A name written in a script with
    no ASCII in it used to fold to the single fallback every other such mod
    also took.
    """

    def test_ascii_and_accented_names_are_unchanged(self) -> None:
        self.assertEqual("mymod.unity3d", default_bundle_name("MyMod"))
        self.assertEqual("caf-mod.unity3d", default_bundle_name("Café Mod"))

    def test_two_non_latin_mod_names_do_not_share_a_stem(self) -> None:
        first = default_bundle_name("Кирка")
        second = default_bundle_name("Пикада")
        self.assertNotEqual(first, second)
        for name in (first, second):
            self.assertRegex(name, r"^mod-[0-9a-f]{8}\.unity3d$")

    def test_a_non_latin_name_still_names_its_latin_part(self) -> None:
        self.assertEqual("mod.unity3d", default_bundle_name("日本語Mod"))


if __name__ == "__main__":
    unittest.main()
