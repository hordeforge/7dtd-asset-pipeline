"""Actionable environment and project health checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .capabilities import capabilities
from .config import PipelineConfig
from .errors import PipelineError
from .game import game_unity_version, project_unity_version, validate_game_dir
from .references import read_mod_name

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


def _guard(checks: list[Check], name: str, action):
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
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read {manifest}: {exc}") from exc
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        raise PipelineError(f"{manifest} has no dependencies object")
    return dependencies


def run_doctor(config: PipelineConfig) -> list[Check]:
    checks: list[Check] = []

    actual_name = _guard(checks, "modlet", lambda: read_mod_name(config.mod_root / "ModInfo.xml"))
    if actual_name is None:
        pass
    elif actual_name != config.mod_name:
        checks.append(
            Check("FAIL", "modlet", f"ModInfo name {actual_name!r} does not match {config.mod_name!r}")
        )
    else:
        checks.append(Check("OK", "modlet", f"{config.mod_root} ({actual_name})"))

    project_version = _guard(
        checks, "Unity project", lambda: project_unity_version(config.unity_project)
    )
    if project_version is not None:
        checks.append(Check("OK", "Unity project", f"{config.unity_project} ({project_version})"))

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
                Check("OK", "optional modules", "common audio/image/particle/physics modules enabled")
            )

    if config.game_dir:
        discovered = _guard(checks, "game", lambda: game_unity_version(config.game_dir))
        if discovered is not None:
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
    else:
        checks.append(Check("WARN", "game", "set SEVEN_DAYS_TO_DIE_DIR for authoritative version checks"))

    if config.unity_editor:
        checks.extend(_editor_checks(config))
    else:
        checks.append(Check("WARN", "Unity editor", "set UNITY_EDITOR to build; inspection still works"))

    checks.extend(_capability_checks())
    return checks


def _capability_checks() -> list[Check]:
    """Capability rows for humans; agents should call `capabilities()` instead."""
    checks: list[Check] = []
    for capability in capabilities():
        detail = capability.path or "installed" if capability.available else (
            f"optional: {capability.purpose} -> {capability.install}"
        )
        checks.append(Check("OK" if capability.available else "INFO", capability.name, detail))
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
    windows = editor.parent / (
        "Data/PlaybackEngines/WindowsStandaloneSupport/UnityEditor.WindowsStandalone.Extensions.dll"
    )
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
        return [Check("FAIL", "Unity editor", f"Unity -version exited {result.returncode}: {reported}")]
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
        "would silently upgrade the project. Point UNITY_EDITOR at the {0} editor.".format(expected),
    )
