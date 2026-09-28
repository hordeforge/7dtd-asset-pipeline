"""The analysis contract: the linters, the type checker, and CI that runs them.

Every other gate in this repository fails on something an asset got wrong. This
one fails when the analysis itself stops: a defect category dropped from
`select`, a strictness flag switched off, an analyzer unpinned, a workflow that
reports failure nobody reads, an inline ignore that silences more than its rule.
None of those is a visible change in a diff, and each one leaves the tree
looking exactly as defended as it was before.

The assertions are floors, not snapshots. Adding a category, a rule, or a
strictness flag is always allowed; removing one is what fails here, and the
message says which. The one exception is the blanket-ignore test, which reads
the shipped tree: an ignore that names no rule, or that names one and says
nothing about why, is a suppression whose cost outlives the finding.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import sevendtd_asset_pipeline

REPO_ROOT = Path(sevendtd_asset_pipeline.__file__).resolve().parents[2]

# Categories whose absence lets a real defect merge unseen: pyflakes and pycodestyle
# for the mechanical ones, bugbear and simplify for the control-flow ones, bandit
# for the process, path, and XML ones, pygrep-hooks and ruff for ignore hygiene,
# and the flake8-return and tryceratops rules for the exception paths.
REQUIRED_CATEGORIES = (
    "E",
    "W",
    "F",
    "B",
    "BLE",
    "S",
    "PGH",
    "RUF",
    "SIM",
    "RET",
    "C4",
    "PIE",
    "A",
    "I",
)

# Selected one code at a time, so a category is not enough: these are the
# exception-handling rules the tree is verified clean for.
REQUIRED_CODES = ("TRY201", "TRY203", "TRY300", "TRY400", "TRY401")

# mypy's own ceilings, plus the three --strict leaves and the error codes this
# tree holds itself to. Each was verified against the whole tree before it was
# written into pyproject.toml; the comment beside each says which.
REQUIRED_MYPY_FLAGS = (
    "strict",
    "strict_bytes",
    "strict_concatenate",
    "disallow_untyped_globals",
    "extra_checks",
)

REQUIRED_ERROR_CODES = (
    "ignore-without-code",
    "unused-ignore",
    "truthy-bool",
    "truthy-iterable",
    "redundant-expr",
    "possibly-undefined",
)

# The analyzers whose verdict changes between releases, so a checkout, a CI job
# and a local run must resolve one version.
PINNED_ANALYZERS = ("ruff", "mypy")

NOQA = re.compile(r"#\s*noqa(?::\s*(?P<codes>[A-Z]+[0-9]+(?:[,\s]+[A-Z]+[0-9]+)*))?", re.IGNORECASE)
TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?P<code>\[[^\]]+\])?")
SHELLCHECK_DISABLE = re.compile(
    r"#\s*shellcheck\s+disable=(?P<codes>[A-Z]+[0-9]+(?:[,\s]+[A-Z]+[0-9]+)*)(?P<rest>.*)$"
)


def python_sources(root: Path) -> list[Path]:
    """Every tracked Python file, minus the trees the analyzers skip on purpose."""
    skipped = {"build", "dist", ".venv", ".hypothesis", "reference", "tools", "__pycache__"}
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if not skipped & set(path.relative_to(root).parts)
    ]


def shell_sources(root: Path) -> list[Path]:
    """Every shell file, `bash -n` and shellcheck's, which is scripts/ here."""
    skipped = {"build", "dist", ".venv", ".hypothesis", "__pycache__"}
    return [
        path
        for path in sorted(root.rglob("*.sh"))
        if not skipped & set(path.relative_to(root).parts)
    ] + [root / "scripts" / "bootstrap"]


class AnalysisPostureCase(unittest.TestCase):
    """Guard like test_release_contract.py does: these files exist only in a checkout."""

    def setUp(self) -> None:
        if not (REPO_ROOT / "pyproject.toml").is_file():
            self.skipTest("running from a packaged install without the repository")
        self.pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


class RuffConfigurationTests(AnalysisPostureCase):
    def test_every_defect_category_is_selected(self) -> None:
        selected = set(self.pyproject["tool"]["ruff"]["lint"]["select"])
        ignored = set(self.pyproject["tool"]["ruff"]["lint"]["ignore"])
        for category in REQUIRED_CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, selected)
                self.assertNotIn(
                    category, ignored, f"{category} is selected and then ignored wholesale"
                )

    def test_the_individual_correctness_rules_are_selected(self) -> None:
        selected = set(self.pyproject["tool"]["ruff"]["lint"]["select"])
        for code in REQUIRED_CODES:
            with self.subTest(code=code):
                self.assertIn(code, selected)

    def test_the_line_length_is_capped(self) -> None:
        width = self.pyproject["tool"]["ruff"]["line-length"]
        self.assertIsInstance(width, int)
        self.assertGreater(width, 0)
        self.assertLessEqual(width, 100, "a cap the tree already passes is 100 at most")


class MypyConfigurationTests(AnalysisPostureCase):
    def test_the_checker_runs_at_its_ceiling(self) -> None:
        config = self.pyproject["tool"]["mypy"]
        for flag in REQUIRED_MYPY_FLAGS:
            with self.subTest(flag=flag):
                self.assertIs(config.get(flag), True)
        for code in REQUIRED_ERROR_CODES:
            with self.subTest(code=code):
                self.assertIn(code, config.get("enable_error_code", []))

    def test_the_checked_floor_matches_the_declared_ones(self) -> None:
        self.assertEqual(self.pyproject["tool"]["mypy"]["python_version"], "3.11")
        self.assertIn(">=3.11", self.pyproject["project"]["requires-python"])
        self.assertEqual(self.pyproject["tool"]["ruff"]["target-version"], "py311")


class AnalyzerVersionTests(AnalysisPostureCase):
    def test_every_analyzer_is_pinned_to_one_version(self) -> None:
        declared = self.pyproject["dependency-groups"]["dev"]
        for analyzer in PINNED_ANALYZERS:
            with self.subTest(analyzer=analyzer):
                pins = [entry for entry in declared if entry.startswith(f"{analyzer}==")]
                self.assertEqual(
                    len(pins),
                    1,
                    f"{analyzer} must be pinned with == in the dev group, so CI and a "
                    f"checkout grade the same way",
                )


class EnforcementTests(AnalysisPostureCase):
    def test_check_runs_every_analyzer(self) -> None:
        for invocation in (
            "ruff check .",
            "ruff format --check .",
            "mypy .",
            "shellcheck -S style",
        ):
            with self.subTest(invocation=invocation):
                self.assertIn(invocation, self.makefile)

    def test_a_missing_analyzer_fails_in_ci_instead_of_skipping(self) -> None:
        # Each of the three analyzers a contributor may not have installed is
        # gated on PATH, and each says so in the same block. Dropping the
        # `[ -n "$${CI:-}" ]` arm turns a hard fail into a green skip.
        guards = self.makefile.count('-n "$${CI:-}"')
        self.assertGreaterEqual(
            guards, 3, "ruff, mypy and shellcheck each need a CI arm that exits non-zero"
        )

    def test_ci_runs_the_gate_without_tolerating_failure(self) -> None:
        self.assertIn("make check test", self.ci)
        self.assertNotIn("continue-on-error", self.ci)
        self.assertNotIn("|| true", self.ci.split("make check test")[0])


class SuppressionHygieneTests(AnalysisPostureCase):
    def test_every_python_ignore_names_its_rule(self) -> None:
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{number}"
            for path in python_sources(REPO_ROOT)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if (match := NOQA.search(line)) and not match.group("codes")
        ]
        self.assertEqual(offenders, [], f"a bare noqa silences every rule on its line: {offenders}")

    def test_every_type_ignore_names_its_error_code(self) -> None:
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{number}"
            for path in python_sources(REPO_ROOT)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if (match := TYPE_IGNORE.search(line)) and not match.group("code")
        ]
        self.assertEqual(
            offenders, [], f"mypy rejects a bare type: ignore, and so should the tree: {offenders}"
        )

    def test_every_shellcheck_disable_names_its_rule_and_says_why(self) -> None:
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{number}"
            for path in shell_sources(REPO_ROOT)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if (match := SHELLCHECK_DISABLE.search(line)) is not None
            and (not match.group("codes") or not match.group("rest").strip())
        ]
        self.assertEqual(
            offenders,
            [],
            f"a shellcheck disable must name its rule and say why: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
