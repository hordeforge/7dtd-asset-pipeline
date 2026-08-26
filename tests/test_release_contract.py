"""The release contract: one version, and a changelog the release reads.

Releases are tag-driven (docs/runbooks and CONTRIBUTING.md): a `vX.Y.Z` tag
must carry an artifact whose version equals the tag, and since the release
workflow publishes the tag's own CHANGELOG.md section as its notes, a version
without a section cannot ship. These tests pin the wiring that makes that
honest: the version is declared once, pyproject.toml reads it instead of
holding a second copy that can drift, and the changelog keeps the sections the
release workflow greps.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import sevendtd_asset_pipeline

REPO_ROOT = Path(sevendtd_asset_pipeline.__file__).resolve().parents[2]


class ReleaseContractCase(unittest.TestCase):
    """Guard like test_scripts.py does: these files exist only in a checkout."""

    def setUp(self) -> None:
        if not (REPO_ROOT / "pyproject.toml").is_file():
            self.skipTest("running from a packaged install without the repository")


class VersionDeclarationTests(ReleaseContractCase):
    def test_pyproject_reads_the_version_instead_of_copying_it(self) -> None:
        """A second static copy in [project] is how artifacts report stale versions."""
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', text)
        project_table = text.split("[project]", 1)[1].split("[", 1)[0]
        self.assertIsNone(
            re.search(r'^version\s*=\s*"', project_table, re.MULTILINE),
            "pyproject.toml must not declare a second static version; "
            "the single source is sevendtd_asset_pipeline._version.__version__",
        )
        self.assertIn('version = { attr = "sevendtd_asset_pipeline._version.__version__" }', text)

    def test_declared_version_is_a_valid_release_version(self) -> None:
        self.assertRegex(
            sevendtd_asset_pipeline.__version__,
            r"^\d+\.\d+\.\d+$",
            "the release gate compares __version__ to vX.Y.Z tags verbatim",
        )


class ChangelogTests(ReleaseContractCase):
    def setUp(self) -> None:
        super().setUp()
        self.text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_has_an_unreleased_section(self) -> None:
        self.assertIn("## [Unreleased]", self.text)

    def test_every_dated_section_is_a_taggable_version(self) -> None:
        headings = re.findall(r"^## \[([^\]]+)\](?: - \d{4}-\d{2}-\d{2})?$", self.text, re.M)
        self.assertTrue(headings, "no release sections found")
        for version in headings:
            with self.subTest(version):
                if version == "Unreleased":
                    continue
                self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_the_current_version_has_a_section(self) -> None:
        """The release workflow fails a tag with no CHANGELOG.md section.

        Pinning it here means the drift surfaces in the suite on main, not only
        when someone next pushes a tag.
        """
        current = sevendtd_asset_pipeline.__version__
        self.assertRegex(self.text, rf"(?m)^## \[{re.escape(current)}\]")


if __name__ == "__main__":
    unittest.main()
