"""The release contract: one version, a changelog the release reads, and a
public surface that only moves deliberately.

Releases are tag-driven (docs/runbooks/release-checklist.md and
CONTRIBUTING.md): a `vX.Y.Z` tag must carry an artifact whose version equals
the tag, and since the release workflow publishes the tag's own CHANGELOG.md
section as its notes, a version without a section cannot ship. These tests pin
the wiring that makes that honest: the version is declared once, pyproject.toml
reads it instead of holding a second copy that can drift, the changelog keeps
the sections the release workflow greps, and a name leaving the supported
`__all__` surface is declared in the changelog rather than discovered by a
consumer's ImportError.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import sevendtd_asset_pipeline

REPO_ROOT = Path(sevendtd_asset_pipeline.__file__).resolve().parents[2]


def unreleased_section(changelog: str) -> str:
    """The `[Unreleased]` body: what a consumer reads for the release in flight."""
    start = changelog.index("## [Unreleased]")
    rest = changelog[start + 1 :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


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

    def unreleased_section(self) -> str:
        """The text a consumer reads for the release being prepared."""
        return unreleased_section(self.text)


class PublicApiTests(ReleaseContractCase):
    """`__all__` is the supported surface, so a name leaving it is a break.

    CONTRIBUTING.md draws the line there: everything in
    `sevendtd_asset_pipeline.__all__` is the supported API and everything else
    may change without notice. Nothing enforced that, so an export could be
    renamed or dropped in a refactor and the only evidence a consumer had was
    an ImportError after upgrading. PUBLIC_API below is the snapshot: a name
    that leaves `__all__` fails here until the snapshot is updated and
    CHANGELOG.md's `[Unreleased]` section declares the removal by name.

    Additions need no snapshot update; the gate is on what breaks a consumer.
    """

    PUBLIC_API = frozenset(
        {
            "OPERATIONS",
            "AssetReference",
            "BundleInfo",
            "Capability",
            "Check",
            "ConfigNotFoundError",
            "DeepReport",
            "IconReport",
            "MeshReport",
            "Operation",
            "Pipeline",
            "PipelineConfig",
            "PipelineError",
            "Release",
            "RenderResult",
            "SoundReport",
            "Status",
            "ValidationReport",
            "__version__",
            "call_json",
            "capabilities",
            "check_icons",
            "check_mesh",
            "check_sound",
            "collect_status",
            "deep_inspect",
            "discover_references",
            "failed",
            "fetch_release",
            "game_unity_version",
            "has_capability",
            "initialize",
            "inspect_bundle",
            "load_config",
            "manifest",
            "manifest_assets",
            "project_unity_version",
            "reject_disabled_modules",
            "render_icon",
            "require_capability",
            "run_build",
            "run_doctor",
            "validate_bundle",
            "validate_mod",
        }
    )

    def setUp(self) -> None:
        super().setUp()
        self.exported = frozenset(sevendtd_asset_pipeline.__all__)

    def test_every_exported_name_exists(self) -> None:
        """`__all__` naming a missing attribute breaks `from … import *`."""
        for name in sorted(self.exported):
            with self.subTest(name):
                self.assertTrue(
                    hasattr(sevendtd_asset_pipeline, name),
                    f"__all__ exports {name}, which the package does not define",
                )

    def test_removals_are_declared_in_the_changelog(self) -> None:
        """A name leaving the surface needs a changelog entry naming it."""
        removed = self.PUBLIC_API - self.exported
        if not removed:
            return
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = unreleased_section(text)
        for name in sorted(removed):
            with self.subTest(name):
                self.assertIn(
                    f"`{name}`",
                    unreleased,
                    f"{name} left sevendtd_asset_pipeline.__all__; declare the removal "
                    "in CHANGELOG.md's [Unreleased] section, then drop it from "
                    "PublicApiTests.PUBLIC_API",
                )

    def test_the_snapshot_matches_the_surface(self) -> None:
        """An addition is a deliberate act: the snapshot is what says so.

        Without this, a name added to `__all__` in passing would never enter
        the snapshot, and the next removal would read as an addition nobody
        reviewed.
        """
        self.assertEqual(
            sorted(self.exported - self.PUBLIC_API),
            [],
            "new names in __all__ are the supported API; add each to "
            "PublicApiTests.PUBLIC_API and to the changelog's [Unreleased] "
            "### Added section",
        )


if __name__ == "__main__":
    unittest.main()
