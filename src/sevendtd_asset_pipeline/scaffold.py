"""Scaffold a pipeline-owned Unity project into an existing modlet."""

from __future__ import annotations

import re
import shutil
from importlib.resources import files
from pathlib import Path

from .assets_src import create as create_assets_src
from .config import CONFIG_NAME, render_config
from .consumer_docs import render_agent_guide
from .errors import PipelineError
from .references import read_mod_name


# The mod-side entry points. `validate` and `check-icons` run together because
# icons are not bundle members: one command cannot see both.
MAKEFILE_TARGETS = """.PHONY: assets assets-probe assets-validate assets-doctor assets-status assets-icons

assets:
	7dtd-assets build

assets-probe:
	7dtd-assets build --probe

assets-validate:
	7dtd-assets validate
	7dtd-assets check-icons

assets-icons:
	7dtd-assets check-icons

assets-doctor:
	7dtd-assets doctor

assets-status:
	7dtd-assets status
"""


def default_bundle_name(mod_name: str) -> str:
    stem = re.sub(r"[^a-z0-9._-]+", "-", mod_name.lower()).strip("-._")
    return f"{stem or 'mod-assets'}.unity3d"


def initialize(
    mod_root: Path,
    mod_name: str | None,
    bundle_name: str | None,
    unity_version: str,
    changeset: str | None = None,
) -> list[Path]:
    mod_root = mod_root.resolve()
    if not mod_root.is_dir():
        raise PipelineError(f"mod root does not exist: {mod_root}")
    config_path = mod_root / CONFIG_NAME
    project = mod_root / "tools" / "7dtd-assets" / "UnityProject"
    makefile = mod_root / "Makefile.assets"
    existing = [path for path in (config_path, project, makefile) if path.exists()]
    if existing:
        raise PipelineError(
            "pipeline files already exist below "
            f"{mod_root}: {', '.join(path.name for path in existing)}; "
            "move them aside or update them explicitly"
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
    # Unity adds m_EditorVersionWithRevision itself on first open, but writing
    # it now pins the exact build in review and in git history, and tells
    # install-unity-editor.sh which changeset the project expects.
    version_file = project / "ProjectSettings" / "ProjectVersion.txt"
    lines = [f"m_EditorVersion: {unity_version}"]
    if changeset:
        lines.append(f"m_EditorVersionWithRevision: {unity_version} ({changeset})")
    version_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    makefile.write_text(MAKEFILE_TARGETS, encoding="utf-8")
    # The mod is where an agent actually works, so the rules travel with the
    # scaffold rather than living only in this repository.
    guide = mod_root / "tools" / "7dtd-assets" / "AGENTS.md"
    guide.write_text(render_agent_guide(mod_name, bundle_name), encoding="utf-8")
    # Editable sources and their provenance need a home outside the Unity
    # bundle folder, or they end up either unrecorded or accidentally shipped.
    # Created without clobbering: a mod may already have art here.
    assets_src = create_assets_src(mod_root, mod_name, bundle_name)
    return [config_path, project, makefile, guide, assets_src]
