"""Actionable environment and project health checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
    actual_name = read_mod_name(config.mod_root / "ModInfo.xml")
    if actual_name != config.mod_name:
        raise PipelineError(f"ModInfo name {actual_name!r} does not match {config.mod_name!r}")
    checks.append(Check("OK", "modlet", f"{config.mod_root} ({actual_name})"))

    project_version = project_unity_version(config.unity_project)
    checks.append(Check("OK", "Unity project", f"{config.unity_project} ({project_version})"))
    dependencies = _modules(config.unity_project)
    missing = [name for name in REQUIRED_MODULES if name not in dependencies]
    if missing:
        raise PipelineError("Unity package manifest is missing required modules: " + ", ".join(missing))
    checks.append(Check("OK", "engine modules", "required AssetBundle module is enabled"))
    omitted = [name for name in RECOMMENDED_MODULES if name not in dependencies]
    if omitted:
        checks.append(Check("WARN", "optional modules", "add when used: " + ", ".join(omitted)))
    else:
        checks.append(Check("OK", "optional modules", "common audio/image/particle/physics modules enabled"))

    if config.game_dir:
        validate_game_dir(config.game_dir)
        game_version, source = game_unity_version(config.game_dir)
        if game_version != project_version:
            raise PipelineError(
                f"Unity project uses {project_version}; installed game bundle uses {game_version} ({source})"
            )
        checks.append(Check("OK", "game", f"{config.game_dir}; Unity {game_version} from {source.name}"))
    else:
        checks.append(Check("WARN", "game", "set SEVEN_DAYS_TO_DIE_DIR for authoritative version checks"))

    if config.unity_editor:
        if not config.unity_editor.is_file() or not os.access(config.unity_editor, os.X_OK):
            raise PipelineError(f"Unity editor is not executable: {config.unity_editor}")
        windows = config.unity_editor.parent / "Data/PlaybackEngines/WindowsStandaloneSupport/UnityEditor.WindowsStandalone.Extensions.dll"
        if config.target == "StandaloneWindows64" and not windows.is_file():
            raise PipelineError(f"Windows Build Support (Mono) is missing: {windows}")
        try:
            result = subprocess.run(
                [str(config.unity_editor), "-version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise PipelineError("Unity -version did not finish within 30 seconds") from exc
        reported = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
        if result.returncode != 0:
            raise PipelineError(f"Unity -version exited {result.returncode}: {reported}")
        checks.append(Check("OK", "Unity editor", f"{config.unity_editor} ({reported})"))
        checks.append(Check("OK", "Windows support", str(windows)))
    else:
        checks.append(Check("WARN", "Unity editor", "set UNITY_EDITOR to build; inspection still works"))

    optional = {
        "blender": "headless mesh generation and conversion",
        "openscad": "parametric hard-surface meshes",
        "magick": "icons, masks, texture conversion",
        "ffmpeg": "audio conversion and synthesis filters",
        "gltf_validator": "glTF/GLB conformance",
    }
    for command, purpose in optional.items():
        found = shutil.which(command)
        checks.append(Check("OK" if found else "INFO", command, found or f"optional: {purpose}"))
    return checks
