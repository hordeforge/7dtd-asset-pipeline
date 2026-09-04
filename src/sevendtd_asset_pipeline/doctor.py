"""Actionable environment and project health checks."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .bundle_writer import collect_sources
from .capabilities import capabilities, extra_install, has_capability
from .config import BUNDLE_SOURCES, PipelineConfig
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .references import read_mod_name
from .unity_process import windows_standalone_support

REQUIRED_MODULES = ("com.unity.modules.assetbundle",)
RECOMMENDED_MODULES = (
    "com.unity.modules.audio",
    "com.unity.modules.imageconversion",
    "com.unity.modules.particlesystem",
    "com.unity.modules.physics",
)


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


def failed(checks: list[Check]) -> bool:
    return any(check.status == "FAIL" for check in checks)


_T = TypeVar("_T")


def _guard(checks: list[Check], name: str, action: Callable[[], _T]) -> _T | None:
    """Record a failing check instead of aborting the whole report.

    Agents and CI consume ``doctor --json``. A raised exception would collapse
    every remaining check into one stderr line, so each check reports its own
    verdict and the caller decides the exit code.
    """
    try:
        return action()
    except PipelineError as exc:
        checks.append(Check("FAIL", name, str(exc)))
        return None


def _modules(project: Path) -> dict[str, str]:
    manifest = project / "Packages" / "manifest.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read {manifest}: {exc}") from exc
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        raise PipelineError(f"{manifest} has no dependencies object")
    return dependencies


def run_doctor(config: PipelineConfig) -> list[Check]:
    checks: list[Check] = []

    actual_name = _guard(checks, "modlet", lambda: read_mod_name(config.mod_root / "ModInfo.xml"))
    if actual_name is not None:
        # A None here already appended its FAIL check via _guard.
        if actual_name != config.mod_name:
            checks.append(
                Check(
                    "FAIL",
                    "modlet",
                    f"ModInfo name {actual_name!r} does not match {config.mod_name!r}",
                )
            )
        else:
            checks.append(Check("OK", "modlet", f"{config.mod_root} ({actual_name})"))

    checks.append(
        Check(
            "OK", "bundle source", f"{config.bundle_source}: {BUNDLE_SOURCES[config.bundle_source]}"
        )
    )
    # Everything below this line is about Unity, and a mod that ships no bundle
    # has no use for any of it. Reporting a missing editor there would be a
    # standing warning about a tool that configuration says is not part of the
    # build, which is how a report stops being read.
    if not config.has_bundle:
        checks.append(
            Check("OK", "Unity", "not required: this mod ships no bundle (shamway docs no-unity)")
        )
        checks.extend(_game_checks(config, None))
        checks.extend(_capability_checks())
        return checks

    if config.bundle_source == "synthesized":
        checks.extend(_synthesized_checks(config))
        checks.extend(_game_checks(config, None))
        checks.extend(_capability_checks())
        return checks

    # An external build host may own the Unity project as well as the editor,
    # in which case there is nothing here to check and nothing wrong with that.
    project_version: str | None = None
    dependencies: dict[str, str] | None = None
    if not config.builds_locally and not config.unity_project.is_dir():
        checks.append(
            Check(
                "INFO",
                "Unity project",
                f"no project at {config.unity_project}; the build host owns it",
            )
        )
    else:
        project_version = _guard(
            checks, "Unity project", lambda: project_unity_version(config.unity_project)
        )
        if project_version is not None:
            checks.append(
                Check("OK", "Unity project", f"{config.unity_project} ({project_version})")
            )
        dependencies = _guard(checks, "engine modules", lambda: _modules(config.unity_project))
    if dependencies is not None:
        missing = [name for name in REQUIRED_MODULES if name not in dependencies]
        if missing:
            checks.append(
                Check(
                    "FAIL",
                    "engine modules",
                    "Unity package manifest is missing required modules: " + ", ".join(missing),
                )
            )
        else:
            checks.append(Check("OK", "engine modules", "required AssetBundle module is enabled"))
        omitted = [name for name in RECOMMENDED_MODULES if name not in dependencies]
        if omitted:
            checks.append(Check("WARN", "optional modules", "add when used: " + ", ".join(omitted)))
        else:
            checks.append(
                Check(
                    "OK", "optional modules", "common audio/image/particle/physics modules enabled"
                )
            )

    checks.extend(_game_checks(config, project_version))

    if config.unity_editor:
        checks.extend(_editor_checks(config))
    elif config.builds_locally:
        checks.append(
            Check("WARN", "Unity editor", "set UNITY_EDITOR to build; inspection still works")
        )
    else:
        # An external build host owns the editor. Its absence here is the
        # configured state, not a defect, so it is reported as information and
        # the command that replaces `build` is named.
        checks.append(
            Check(
                "INFO",
                "Unity editor",
                "not needed here: the bundle is built elsewhere and gated with "
                "'shamway stage BUNDLE --manifest M --log L'",
            )
        )

    checks.extend(_capability_checks())
    return checks


def _synthesized_checks(config: PipelineConfig) -> list[Check]:
    """Readiness for the editorless writer: a revision, a source folder, UnityPy.

    None of the Unity rows apply — there is no project to read a revision from
    and no editor to run — so this answers the three questions that decide
    whether `shamway build` can write a bundle here.
    """
    checks: list[Check] = []
    # With a game directory configured, the game row below reports the revision
    # it will use, so only its absence needs an answer here.
    if not config.game_dir and config.unity_version:
        checks.append(
            Check(
                "WARN",
                "Unity revision",
                f"using {config.unity_version} from {config.config_file.name}; set "
                "SEVEN_DAYS_TO_DIE_DIR so the installed game answers instead",
            )
        )
    elif not config.game_dir:
        checks.append(
            Check(
                "FAIL",
                "Unity revision",
                "no revision known: set SEVEN_DAYS_TO_DIE_DIR, or record [unity] version "
                f"in {config.config_file.name}. A bundle carries the revision it claims.",
            )
        )

    source = config.bundle_source_dir
    if not source.is_dir():
        checks.append(Check("FAIL", "bundle sources", f"no source directory at {source}"))
    else:
        found = _guard(checks, "bundle sources", lambda: collect_sources(source))
        if found is not None:
            kinds = ", ".join(sorted({path.suffix.lower() for path in found}))
            checks.append(
                Check("OK", "bundle sources", f"{len(found)} asset(s) in {source} ({kinds})")
            )

    if has_capability("UnityPy"):
        checks.append(
            Check(
                "OK", "writer", "UnityPy is installed; type trees for this revision are available"
            )
        )
    else:
        checks.append(
            Check(
                "FAIL",
                "writer",
                "the editorless writer needs UnityPy for the engine's own type trees: "
                + extra_install("writer"),
            )
        )
    return checks


def _game_checks(config: PipelineConfig, project_version: str | None) -> list[Check]:
    """The installed game: the authority on the revision, and the client's home.

    With `project_version` the game's revision is held against the project's.
    Without one — a mod that ships no bundle — the directory is still worth
    reporting, because `client deploy` and `client launch` are derived from it.
    """
    checks: list[Check] = []
    if not config.game_dir:
        if project_version is None:
            checks.append(
                Check("INFO", "game", "set SEVEN_DAYS_TO_DIE_DIR for client deployment and launch")
            )
        else:
            checks.append(
                Check("WARN", "game", "set SEVEN_DAYS_TO_DIE_DIR for authoritative version checks")
            )
        return checks
    game_dir = config.game_dir
    discovered = _guard(checks, "game", lambda: game_unity_version(game_dir))
    if discovered is None:
        return checks
    game_version, source = discovered
    if project_version is not None and game_version != project_version:
        checks.append(
            Check(
                "FAIL",
                "game",
                f"Unity project uses {project_version}; installed game bundle uses "
                f"{game_version} ({source})",
            )
        )
    else:
        checks.append(
            Check("OK", "game", f"{config.game_dir}; Unity {game_version} from {source.name}")
        )
    return checks


def _capability_checks() -> list[Check]:
    """Capability rows for humans; agents should call `capabilities()` instead."""
    checks: list[Check] = []
    for capability in capabilities():
        if capability.available:
            checks.append(Check("OK", capability.name, capability.path or "installed"))
        elif capability.unusable_reason:
            # Present but not usable. "Install it" would be the wrong advice —
            # it *is* installed — so this row says what was measured and what
            # the tool it gates does instead.
            checks.append(
                Check(
                    "WARN",
                    capability.name,
                    f"{capability.path} cannot be used: {capability.unusable_reason}",
                )
            )
        else:
            checks.append(
                Check(
                    "INFO",
                    capability.name,
                    f"optional: {capability.purpose} -> {capability.install}",
                )
            )
    return checks


def _editor_checks(config: PipelineConfig) -> list[Check]:
    """Verify the editor is runnable, licensed, and can target Windows.

    Each failure returns immediately: a missing Windows module makes the
    `-version` probe's result irrelevant, and running it anyway costs seconds.
    """
    editor = config.unity_editor
    if editor is None:
        return []
    if not editor.is_file() or not os.access(editor, os.X_OK):
        return [Check("FAIL", "Unity editor", f"Unity editor is not executable: {editor}")]
    windows = windows_standalone_support(editor)
    if config.target == "StandaloneWindows64" and not windows.is_file():
        return [
            Check("FAIL", "Windows support", f"Windows Build Support (Mono) is missing: {windows}")
        ]
    try:
        result = subprocess.run(
            [str(editor), "-version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return [Check("FAIL", "Unity editor", "Unity -version did not finish within 30 seconds")]
    reported = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
    if result.returncode != 0:
        return [
            Check("FAIL", "Unity editor", f"Unity -version exited {result.returncode}: {reported}")
        ]
    checks = [
        Check("OK", "Unity editor", f"{editor} ({reported})"),
        Check("OK", "Windows support", str(windows)),
    ]
    checks.append(editor_matches_project(reported, config))
    return checks


def editor_matches_project(reported: str, config: PipelineConfig) -> Check:
    """The editor binary's own version against the project's pinned revision.

    A host routinely has several editors installed, and a `UNITY_EDITOR` that
    points at the wrong one does not fail: batch mode opens the project,
    silently upgrades it to that editor's version, and builds a bundle the
    game rejects. The project-vs-game check cannot see this, because it reads
    `ProjectVersion.txt` *before* Unity rewrites it.
    """
    try:
        expected = project_unity_version(config.unity_project)
    except PipelineError as exc:
        return Check("WARN", "Editor revision", f"cannot read the project revision: {exc}")
    if expected in reported:
        return Check("OK", "Editor revision", f"editor reports {expected}, matching the project")
    return Check(
        "FAIL",
        "Editor revision",
        f"UNITY_EDITOR reports {reported!r} but the project is pinned to {expected}; a build "
        f"would silently upgrade the project. Point UNITY_EDITOR at the {expected} editor.",
    )
