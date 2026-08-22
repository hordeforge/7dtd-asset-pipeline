"""Scaffold a pipeline-owned Unity project into an existing modlet."""

from __future__ import annotations

import re
import shutil
from importlib.resources import files
from pathlib import Path

from .config import CONFIG_NAME, render_config
from .errors import PipelineError
from .references import read_mod_name


def default_bundle_name(mod_name: str) -> str:
    stem = re.sub(r"[^a-z0-9._-]+", "-", mod_name.lower()).strip("-._")
    return f"{stem or 'mod-assets'}.unity3d"


def initialize(
    mod_root: Path,
    mod_name: str | None,
    bundle_name: str | None,
    unity_version: str,
) -> list[Path]:
    mod_root = mod_root.resolve()
    if not mod_root.is_dir():
        raise PipelineError(f"mod root does not exist: {mod_root}")
    config_path = mod_root / CONFIG_NAME
    project = mod_root / "tools" / "7dtd-assets" / "UnityProject"
    if config_path.exists() or project.exists():
        raise PipelineError(
            f"pipeline files already exist below {mod_root}; move them aside or update them explicitly"
        )
    if mod_name is None:
        mod_name = read_mod_name(mod_root / "ModInfo.xml")
    bundle_name = bundle_name or default_bundle_name(mod_name)
    config_path.write_text(render_config(mod_name, bundle_name, unity_version), encoding="utf-8")
    template = files("sevendtd_asset_pipeline").joinpath("templates/UnityProject")
    shutil.copytree(str(template), project)
    bundle_source = project / "Assets" / "ModAssets" / "Bundle"
    bundle_source.mkdir(parents=True, exist_ok=True)
    (bundle_source / ".gitkeep").write_text(
        "# Put source assets and their Unity .meta files below this directory.\n",
        encoding="utf-8",
    )
    version_file = project / "ProjectSettings" / "ProjectVersion.txt"
    version_file.write_text(
        f"m_EditorVersion: {unity_version}\n",
        encoding="utf-8",
    )
    makefile = mod_root / "Makefile.assets"
    makefile.write_text(
        ".PHONY: assets assets-probe assets-validate assets-doctor\n\n"
        "assets:\n\t7dtd-assets build\n\n"
        "assets-probe:\n\t7dtd-assets build --probe\n\n"
        "assets-validate:\n\t7dtd-assets validate\n\n"
        "assets-doctor:\n\t7dtd-assets doctor\n",
        encoding="utf-8",
    )
    return [config_path, project, makefile]
