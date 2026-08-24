"""The host-script registry: what a mod reaches through `shamway script`.

`scripts.SCRIPTS` is a published surface like docs.TOPICS and
generators.GENERATORS: AGENTS.md says a new host script goes in it, and a
consumer calls it from an installed package with no checkout of this
repository. So every registered name must resolve to real packaged bytes, the
packaged copies must equal the repository's own (they have drifted before, as
docs/ had), and the listing must name what exists.
"""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

import sevendtd_asset_pipeline
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.scripts import SCRIPTS, main, path


class ScriptRegistryTests(unittest.TestCase):
    def test_every_registered_script_resolves_to_real_bytes(self) -> None:
        for name, (_filename, summary) in SCRIPTS.items():
            with self.subTest(name):
                self.assertTrue(summary, "a script must say what it is for")
                script = path(name)
                self.assertTrue(script.is_file(), str(script))
                self.assertTrue(script.read_bytes().startswith(b"#!"), str(script))

    def test_packaged_scripts_are_the_repo_scripts(self) -> None:
        """setup.py copies scripts/*.sh into the package on every build.

        A wheel built from a stale tree ships yesterday's installer; equality
        here is cheap to keep and expensive to lose.
        """
        source_root = Path(sevendtd_asset_pipeline.__file__).resolve().parents[2] / "scripts"
        if not source_root.is_dir():
            self.skipTest("running from a packaged install without the repo scripts/")
        packaged_root = Path(sevendtd_asset_pipeline.__file__).resolve().parent / "scripts"
        for filename in (filename for filename, _summary in SCRIPTS.values()):
            with self.subTest(filename):
                self.assertEqual(
                    (source_root / filename).read_bytes(),
                    (packaged_root / filename).read_bytes(),
                    f"{filename} differs between scripts/ and the packaged copy; "
                    "re-copy it (or rebuild the wheel) so both readers see one script",
                )
        # install-tools.sh resolves GitHub release URLs through this sibling,
        # so a staged installer without its current copy can resolve nothing.
        with self.subTest("github_asset_url.py"):
            self.assertEqual(
                (source_root / "github_asset_url.py").read_bytes(),
                (packaged_root / "github_asset_url.py").read_bytes(),
                "github_asset_url.py differs between scripts/ and the packaged copy; "
                "re-copy it (or rebuild the wheel) so both readers see one script",
            )

    def test_an_unknown_script_lists_the_known_ones(self) -> None:
        with self.assertRaisesRegex(PipelineError, "install-tools"):
            path("no-such-script")

    def test_the_listing_names_every_registered_script(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main(["--list"]))
        text = out.getvalue()
        for name, (_filename, summary) in SCRIPTS.items():
            self.assertIn(name, text)
            self.assertIn(summary, text)
        self.assertIn("--path", text)


if __name__ == "__main__":
    unittest.main()
