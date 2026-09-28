"""The release contract: one version, one set of published metadata, a changelog
the release reads, and a public surface that only moves deliberately.

Releases are tag-driven (docs/runbooks/release-checklist.md and
CONTRIBUTING.md): a `vX.Y.Z` tag must carry an artifact whose version equals
the tag, and since the release workflow publishes the tag's own CHANGELOG.md
section as its notes, a version without a section cannot ship. These tests pin
the wiring that makes that honest: the version is declared once, pyproject.toml
reads it instead of holding a second copy that can drift, the license is an
SPDX expression whose file exists and whose classifiers match the interpreters
ci.yml tests, the changelog keeps the sections the release workflow greps, and a
name leaving the supported `__all__` surface is declared in the changelog
rather than discovered by a consumer's ImportError.
"""

from __future__ import annotations

import re
import tomllib
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


class PackagingMetadataTests(ReleaseContractCase):
    """The published wheel's own metadata, checked against what ships with it.

    Nothing in the suite saw a deprecation from the build log before this:
    `project.license` as a TOML table and the `License ::` classifier beside it
    were both deprecated by setuptools with a 2027-02-18 removal, so a build
    that still works today would stop working with a setuptools upgrade and the
    only signal would be a warning scrollback nobody reads. These assertions
    are the warning.
    """

    def setUp(self) -> None:
        super().setUp()
        self.project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]

    def test_license_is_an_spdx_expression_not_a_table(self) -> None:
        self.assertEqual(
            self.project["license"],
            "MIT",
            "setuptools deprecated the `license = { text = ... }` table form and "
            "removes it on 2027-02-18; an SPDX string is the supported form",
        )

    def test_the_license_file_is_named_and_present(self) -> None:
        """An unnamed license ships no license text inside the wheel."""
        declared = self.project["license-files"]
        self.assertTrue(declared, "license-files must name the file to install")
        for name in declared:
            with self.subTest(name):
                self.assertTrue(
                    (REPO_ROOT / name).is_file(),
                    f"pyproject.toml declares license file {name!r}, which is not in the tree",
                )

    def test_no_license_classifier_survives_the_spdx_expression(self) -> None:
        """Setuptools refuses an SPDX expression and a license classifier together."""
        stale = [c for c in self.project["classifiers"] if c.startswith("License ::")]
        self.assertEqual(
            stale, [], "the SPDX expression above replaced these; both at once is an error"
        )

    def test_the_homepage_names_the_repository(self) -> None:
        """The wheel's front page has a Homepage field, not only a Repository URL."""
        repository = self.project["urls"]["Repository"]
        self.assertEqual(self.project["urls"]["Homepage"], repository)

    def test_python_classifiers_match_the_untested_interpreters(self) -> None:
        """The wheel claims exactly the minors ci.yml runs the suite against.

        A claimed minor nobody tested is an untested support promise; a tested
        minor with no classifier is support the metadata hides.
        """
        matrix = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        found = re.search(r"python-version:\s*\[([^\]]+)\]", matrix)
        if found is None:
            self.fail("ci.yml no longer declares a python-version matrix")
        tested = set(re.findall(r'"(\d+\.\d+)"', found.group(1)))
        self.assertTrue(tested, "parsed an empty python-version matrix out of ci.yml")
        claimed = {
            c.rsplit(" ", 1)[1]
            for c in self.project["classifiers"]
            if c.startswith("Programming Language :: Python :: ")
            and re.fullmatch(r"\d+\.\d+", c.rsplit(" ", 1)[1])
        }
        self.assertEqual(claimed, tested, "classifiers and ci.yml's matrix disagree")


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
            "AcceptanceRun",
            "AssetReference",
            "BundleInfo",
            "Capability",
            "Check",
            "ConfigNotFoundError",
            "DeepReport",
            "IconReport",
            "LocalizationReport",
            "LogReport",
            "MeshReport",
            "Operation",
            "PatchReport",
            "Pipeline",
            "PipelineConfig",
            "PipelineError",
            "PromptResult",
            "Release",
            "RenderResult",
            "SoundReport",
            "Status",
            "TextureReport",
            "ValidationReport",
            "VerifyReport",
            "__version__",
            "call_json",
            "capabilities",
            "check_icons",
            "check_localization",
            "check_mesh",
            "check_patches",
            "check_sound",
            "check_texture",
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
