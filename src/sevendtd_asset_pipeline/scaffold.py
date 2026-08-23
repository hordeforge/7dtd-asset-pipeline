"""Scaffold a pipeline-owned Unity project into a modlet, or adopt an existing one.

Two entry paths, because a mod that already ships assets is the harder and
more common case. A fresh scaffold copies the whole Unity project template.
*Adoption* copies only the pipeline-owned editor scripts into a project the
mod already has, and points the configuration at it — because moving a Unity
project means moving every `.meta` with it, and any mistake there re-imports
every asset under a new GUID and silently breaks every prefab reference.
"""

from __future__ import annotations

import re
import shutil
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from .assets_src import create as create_assets_src
from .config import BUNDLE_SOURCES, CONFIG_NAME, render_config
from .consumer_docs import render_agent_guide
from .errors import PipelineError
from .references import read_mod_name

# The mod-side entry points. `validate` and `check-icons` run together because
# icons are not bundle members: one command cannot see both.
MAKEFILE_TARGETS = """.PHONY: assets assets-probe assets-validate assets-doctor assets-status assets-icons

assets:
	shamway build

assets-probe:
	shamway build --probe

assets-validate:
	shamway validate
	shamway check-icons

assets-icons:
	shamway check-icons

assets-doctor:
	shamway doctor

assets-status:
	shamway status
"""

# A mod with no bundle has nothing to build, so the build targets are left out
# rather than left in to fail: a Makefile target that always errors teaches
# whoever runs it to stop trusting the file.
BUNDLE_FREE_MAKEFILE_TARGETS = """.PHONY: assets-validate assets-icons assets-doctor assets-status

assets-validate:
	shamway validate
	shamway check-icons

assets-icons:
	shamway check-icons

assets-doctor:
	shamway doctor

assets-status:
	shamway status
"""

# The Unity-owning modes. "none" means the mod ships no bundle at all, so no
# project is scaffolded, no editor script is vendored, and no revision is
# pinned; "external" still scaffolds the project, because the build host needs
# it in the repository even though this machine will never open it.


def default_bundle_name(mod_name: str) -> str:
    stem = re.sub(r"[^a-z0-9._-]+", "-", mod_name.lower()).strip("-._")
    return f"{stem or 'mod-assets'}.unity3d"


# The editor scripts this pipeline owns. On adoption these are copied into a
# project that already exists; treat them as vendored, because an upgrade
# replaces them. A mod's own editor scripts belong in a folder of their own.
PIPELINE_EDITOR_SCRIPTS = (
    "BundleBuilder.cs",
    "BundleVerifier.cs",
    "GeneratedAsset.cs",
    "IconRenderer.cs",
    "ShamwayPreBuild.cs",
)
EDITOR_FOLDER = "Assets/SevenDaysToDieAssetPipeline/Editor"

# Where a mod that has no Unity project keeps the files its bundle is made of.
# It sits beside the other editable sources rather than in the deployable part
# of the modlet, because the sources themselves never ship.
SYNTHESIZED_SOURCE_ROOT = "assets-src/bundle"


def initialize(
    mod_root: Path,
    mod_name: str | None,
    bundle_name: str | None,
    unity_version: str,
    changeset: str | None = None,
    adopt_project: Path | str | None = None,
    source_root: str | None = None,
    manifest_dir: str | None = None,
    bundle_source: str = "unity",
) -> list[Path]:
    """Create the pipeline inside a modlet, or adopt the Unity project it has.

    With `adopt_project`, no project template is copied and no
    `ProjectVersion.txt` or package manifest is touched: those already exist and
    are the mod's. Only the pipeline-owned editor scripts are installed.

    With `bundle_source="none"` the mod ships no bundle: no Unity project is
    created, nothing is vendored into one, and the mod needs no editor to be
    built, validated or shipped.
    """
    # Checked before anything is written: an unknown source renders a
    # configuration `load_config` rejects, and the scaffold has already copied
    # a Unity project by the time that surfaces. The CLI's argparse choices
    # catch this for the command line; the API and `shamway call` arrive here.
    if bundle_source not in BUNDLE_SOURCES:
        options = ", ".join(f"{name!r} ({why})" for name, why in BUNDLE_SOURCES.items())
        raise PipelineError(f"bundle_source must be one of: {options}")
    mod_root = mod_root.resolve()
    if not mod_root.is_dir():
        raise PipelineError(f"mod root does not exist: {mod_root}")
    config_path = mod_root / CONFIG_NAME
    makefile = mod_root / "Makefile.assets"
    bundle_free = bundle_source == "none"
    synthesized = bundle_source == "synthesized"
    adopting = adopt_project is not None
    if adopting and (bundle_free or synthesized):
        reason = (
            "ships no bundle" if bundle_free else "writes its bundle without an editor"
        )
        raise PipelineError(
            f'bundle_source "{bundle_source}" means the mod {reason}, so there is no '
            "Unity project to adopt"
        )

    if adopting:
        project = Path(adopt_project)
        project = (project if project.is_absolute() else mod_root / project).resolve()
        _check_adoptable(project, mod_root, source_root)
    else:
        project = mod_root / "tools" / "shamway" / "UnityProject"

    projectless = bundle_free or synthesized
    guarded = [config_path, makefile] + ([] if adopting or projectless else [project])
    existing = [path for path in guarded if path.exists()]
    if existing:
        raise PipelineError(
            "pipeline files already exist below "
            f"{mod_root}: {', '.join(path.name for path in existing)}; "
            "move them aside or update them explicitly"
        )
    if mod_name is None:
        mod_name = read_mod_name(mod_root / "ModInfo.xml")
    bundle_name = "" if bundle_free else (bundle_name or default_bundle_name(mod_name))
    # Without a Unity project there is nothing for source_root to be relative
    # to, so it names a folder in the mod itself.
    if synthesized and not source_root:
        source_root = SYNTHESIZED_SOURCE_ROOT

    relative_project = "" if projectless else _relative(project, mod_root, "the Unity project")
    config_path.write_text(
        render_config(
            mod_name,
            bundle_name,
            unity_version,
            unity_project=relative_project,
            source_root=source_root or "Assets/ModAssets/Bundle",
            manifest_dir=manifest_dir or "tools/shamway/manifests",
            bundle_source=bundle_source,
        ),
        encoding="utf-8",
    )

    template = files("sevendtd_asset_pipeline").joinpath("templates/UnityProject")
    if projectless:
        created_scripts = []
    elif adopting:
        created_scripts = _install_editor_scripts(template, project)
    else:
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
        created_scripts = []

    makefile.write_text(
        BUNDLE_FREE_MAKEFILE_TARGETS if bundle_free else MAKEFILE_TARGETS, encoding="utf-8"
    )
    if synthesized:
        # The folder the writer reads. Created now, with a note in it, because
        # an empty configured path is the first thing a build would fail on.
        bundle_sources = mod_root / (source_root or SYNTHESIZED_SOURCE_ROOT)
        bundle_sources.mkdir(parents=True, exist_ok=True)
        keep = bundle_sources / ".gitkeep"
        if not keep.exists():
            keep.write_text(
                "# Every file here becomes a bundle asset: .png -> Texture2D,\n"
                "# .wav -> AudioClip, .txt/.json/.csv -> TextAsset. The file stem is\n"
                "# the name the game loads it by. See `shamway docs no-unity`.\n",
                encoding="utf-8",
            )
    # The mod is where an agent actually works, so the rules travel with the
    # scaffold rather than living only in this repository.
    guide = mod_root / "tools" / "shamway" / "AGENTS.md"
    guide.parent.mkdir(parents=True, exist_ok=True)
    guide.write_text(render_agent_guide(mod_name, bundle_name, bundle_source), encoding="utf-8")
    # Editable sources and their provenance need a home outside the Unity
    # bundle folder, or they end up either unrecorded or accidentally shipped.
    # Created without clobbering: a mod may already have art here.
    assets_src = create_assets_src(mod_root, mod_name, bundle_name)
    # Report the editor folder on adoption and the whole project on a fresh
    # scaffold: in both cases it is what the caller now owns and should commit.
    if projectless:
        touched_paths = [config_path, makefile, guide, assets_src]
        if synthesized:
            touched_paths.insert(1, mod_root / (source_root or SYNTHESIZED_SOURCE_ROOT))
        return touched_paths
    touched = created_scripts[0] if adopting else project
    return [config_path, touched, makefile, guide, assets_src]


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        raise PipelineError(
            f"{label} must live below the mod root, so the mod stays a standalone "
            f"repository: {path} is outside {root}"
        ) from None


def _check_adoptable(project: Path, mod_root: Path, source_root: str | None) -> None:
    """Refuse an adoption that would produce a configuration nothing can build."""
    if not project.is_dir():
        raise PipelineError(f"no Unity project at {project}")
    if not (project / "Assets").is_dir():
        raise PipelineError(
            f"{project} has no Assets/ directory, so it is not a Unity project"
        )
    _relative(project, mod_root, "the Unity project")
    if source_root:
        bundle_source = project / source_root
        if not bundle_source.is_dir():
            raise PipelineError(
                f"--source-root {source_root!r} does not exist in {project}. "
                "It is the folder whose contents become the bundle, relative to the "
                "Unity project root."
            )


def _install_editor_scripts(template: Traversable, project: Path) -> list[Path]:
    """Copy the pipeline-owned editor scripts into an adopted project."""
    destination = project / EDITOR_FOLDER
    destination.mkdir(parents=True, exist_ok=True)
    written = [destination]
    for name in PIPELINE_EDITOR_SCRIPTS:
        source = template.joinpath(EDITOR_FOLDER).joinpath(name)
        target = destination / name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(target)
    return written
