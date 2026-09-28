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
from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from .assets_src import create as create_assets_src
from .config import (
    BUNDLE_SOURCES,
    CONFIG_NAME,
    SYNTHESIZED_SOURCE_ROOT,
    UNITY_SOURCE_ROOT,
    VALID_BUNDLE,
    render_config,
    resolve_bundle_source,
)
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


def initialize(
    mod_root: Path,
    mod_name: str | None,
    bundle_name: str | None,
    unity_version: str,
    changeset: str | None = None,
    adopt_project: Path | str | None = None,
    source_root: str | None = None,
    manifest_dir: str | None = None,
    bundle_source: str | None = None,
) -> list[Path]:
    """Create the pipeline inside a modlet, or adopt the Unity project it has.

    An unstated `bundle_source` means `"synthesized"`: no Unity project is
    created and no editor is ever started, because this tool writes the bundle
    itself. `"unity"` is the opt-in — it is the only value that copies a project
    template, and the only one that makes an editor a requirement of building
    this mod.

    The one exception is `adopt_project`, which *is* that opt-in: pointing at a
    Unity project the mod already has says the editor lane is wanted, so an
    unstated source there means `"unity"`. Stating any other source alongside it
    is refused, because there would be nothing for the project to be used by.

    With `adopt_project`, no project template is copied and no
    `ProjectVersion.txt` or package manifest is touched: those already exist and
    are the mod's. Only the pipeline-owned editor scripts are installed.

    With `bundle_source="none"` the mod ships no bundle: no Unity project is
    created, nothing is vendored into one, and the mod needs no editor to be
    built, validated or shipped.
    """
    bundle_source = resolve_bundle_source(bundle_source, adopt_project is not None)
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
        reason = "ships no bundle" if bundle_free else "writes its bundle without an editor"
        raise PipelineError(
            f'bundle_source "{bundle_source}" means the mod {reason}, so there is no '
            "Unity project to adopt"
        )

    if adopting and adopt_project is not None:
        project = Path(adopt_project)
        project = (project if project.is_absolute() else mod_root / project).resolve()
        _check_adoptable(project, mod_root, source_root)
    else:
        project = mod_root / "tools" / "shamway" / "UnityProject"

    projectless = bundle_free or synthesized
    if mod_name is None:
        mod_name = read_mod_name(mod_root / "ModInfo.xml")
    bundle_name = "" if bundle_free else (bundle_name or default_bundle_name(mod_name))
    # Same check before anything is written as the bundle_source one above: an
    # explicit --bundle-name that load_config would reject must fail now, not
    # after a whole Unity project tree has been copied. `default_bundle_name`
    # sanitizes, so only a caller-supplied name can get here.
    if bundle_name and not VALID_BUNDLE.fullmatch(bundle_name):
        raise PipelineError(
            f"bundle_name {bundle_name!r} is not a lowercase filesystem-safe name "
            "ending in .unity3d"
        )
    # Without a Unity project there is nothing for source_root to be relative
    # to, so it names a folder in the mod itself.
    if synthesized and not source_root:
        source_root = SYNTHESIZED_SOURCE_ROOT

    relative_project = "" if projectless else _relative(project, mod_root, "the Unity project")
    template = files("sevendtd_asset_pipeline").joinpath("templates/UnityProject")
    # The mod is where an agent actually works, so the rules travel with the
    # scaffold rather than living only in this repository.
    guide = mod_root / "tools" / "shamway" / "AGENTS.md"
    # Every body this run would write, rendered before the first write rather
    # than as each file is reached, because the conflict check below compares
    # against them and a run that discovers a conflict half way through has
    # already left the mod half scaffolded.
    bodies: dict[Path, str] = {
        config_path: render_config(
            mod_name,
            bundle_name,
            unity_version,
            unity_project=relative_project,
            source_root=source_root,
            manifest_dir=manifest_dir or "tools/shamway/manifests",
            bundle_source=bundle_source,
        ),
        makefile: BUNDLE_FREE_MAKEFILE_TARGETS if bundle_free else MAKEFILE_TARGETS,
        guide: render_agent_guide(mod_name, bundle_name, bundle_source),
    }
    # The two files the scaffold writes *into* the project, rendered for the
    # same reason and with the same consequence: they replace a template
    # placeholder, so the settled check below has to compare them against these
    # bodies rather than against the template they overwrite.
    project_bodies = {
        f"{UNITY_SOURCE_ROOT}/.gitkeep": (
            "# Put source assets and their Unity .meta files below this directory.\n"
        ),
        "ProjectSettings/ProjectVersion.txt": _project_version(unity_version, changeset),
    }
    _refuse_over_foreign_files(
        mod_root,
        bodies,
        project,
        template,
        owned=project_bodies,
        copying=not (adopting or projectless),
    )
    for target, body in bodies.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8", newline="\n")

    if projectless:
        created_scripts = []
    elif adopting:
        created_scripts = _install_editor_scripts(template, project)
    else:
        # Merging, not replacing: the conflict check above has established that
        # every template file already here holds the body this run would write,
        # so filling in a tree a previous run left incomplete changes nothing
        # else, and a file of the mod's own under the project is never a
        # template file and so never touched here.
        shutil.copytree(str(template), project, dirs_exist_ok=True)
        for name, body in project_bodies.items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8", newline="\n")
        created_scripts = []

    if synthesized:
        # The folder the writer reads. Created now, with a note in it, because
        # an empty configured path is the first thing a build would fail on.
        bundle_sources = mod_root / (source_root or SYNTHESIZED_SOURCE_ROOT)
        bundle_sources.mkdir(parents=True, exist_ok=True)
        keep = bundle_sources / ".gitkeep"
        if not keep.exists():
            keep.write_text(
                "# Every file here becomes a bundle asset: .png -> Texture2D,\n"
                "# .wav -> AudioClip, .txt/.json/.csv -> TextAsset, and a mesh\n"
                "# (.glb/.gltf/.obj/.stl/.ply) -> a prefab with its mesh, material and\n"
                "# shader. The file stem is the name the game loads it by; a texture\n"
                "# named <stem>_albedo is bound to that prefab's material.\n"
                "# See `shamway docs no-unity`.\n",
                encoding="utf-8",
                newline="\n",
            )
    # Editable sources and their provenance need a home outside the Unity
    # bundle folder, or they end up either unrecorded or accidentally shipped.
    # Created without clobbering: a mod may already have art here.
    # The README's "copy a selected output here" sentences have to name this
    # mod's real membership folder: `assets-src/bundle/` by default, a path
    # inside the Unity project only where one exists.
    membership = None if bundle_source == "unity" else (source_root or SYNTHESIZED_SOURCE_ROOT)
    assets_src = create_assets_src(mod_root, mod_name, bundle_name, membership=membership)
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


def _project_version(unity_version: str, changeset: str | None) -> str:
    """The `ProjectVersion.txt` the scaffold pins, template placeholder replaced.

    Unity adds m_EditorVersionWithRevision itself on first open, but writing
    it now pins the exact build in review and in git history, and tells
    install-unity-editor.sh which changeset the project expects.
    """
    lines = [f"m_EditorVersion: {unity_version}"]
    if changeset:
        lines.append(f"m_EditorVersionWithRevision: {unity_version} ({changeset})")
    return "\n".join(lines) + "\n"


def _refuse_over_foreign_files(
    mod_root: Path,
    bodies: dict[Path, str],
    project: Path,
    template: Traversable,
    *,
    owned: dict[str, str],
    copying: bool,
) -> None:
    """Refuse a scaffold that would overwrite a file this run did not write.

    A rerun is a normal thing to do: `init` failed halfway, or a mod wants the
    same pipeline at a new editor revision. Refusing on mere existence made
    both unrecoverable, because the leftovers a half-finished run leaves are
    exactly the files whose presence the check was reading. So the test is
    content, not presence: a file already holding the body this run would write
    is this scaffold, re-run or resumed, and rewriting it is a verified no-op.
    Anything else is somebody's file and is still refused.

    The same applies to the project tree, compared file by file against the
    template and `owned`: absent is fine (an interrupted copy resumes),
    byte-identical is fine, and one edited byte means the mod owns that file.
    """
    conflicting = [path for path, body in bodies.items() if _differs(path, body)]
    if copying and project.exists() and not _template_settled(template, project, owned):
        conflicting.append(project)
    if conflicting:
        raise PipelineError(
            "pipeline files already exist below "
            f"{mod_root}: {', '.join(path.name for path in conflicting)}; "
            "move them aside or update them explicitly"
        )


def _differs(path: Path, body: str) -> bool:
    """Whether `path` exists and holds something other than `body`.

    A file that exists and cannot be read counts as different: this check
    exists to keep the scaffold off a file it did not write, and unreadable is
    not evidence of ownership either way.
    """
    try:
        return path.read_bytes() != body.encode("utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        return path.exists()


def _template_settled(template: Traversable, project: Path, owned: dict[str, str]) -> bool:
    """Whether every template file already under `project` holds the body this run writes.

    The template's own files, and the two the scaffold replaces a placeholder
    in, which are compared against `owned` rather than against the template.
    A file the mod added is in neither set, so it is invisible here and the
    merge that follows leaves it alone.
    """
    for source, names in _walk_template(template):
        relative = "/".join(names)
        expected = owned.get(relative)
        expected_bytes = source.read_bytes() if expected is None else expected.encode("utf-8")
        target = project.joinpath(*names)
        if not target.is_file():
            continue
        if target.read_bytes() != expected_bytes:
            return False
    return True


def _walk_template(template: Traversable) -> Iterator[tuple[Traversable, tuple[str, ...]]]:
    """Every file in `template`, with its path components below it."""
    stack: list[tuple[Traversable, tuple[str, ...]]] = [(template, ())]
    while stack:
        entry, names = stack.pop()
        for child in entry.iterdir():
            # `child.name` is the last component on every Traversable that has
            # one; the components are carried by `names` rather than parsed back
            # out of a path, because a zip-backed package resource has no
            # `relative_to` before 3.12.
            child_names = (*names, child.name)
            if child.is_dir():
                stack.append((child, child_names))
            else:
                yield child, child_names


def _check_adoptable(project: Path, mod_root: Path, source_root: str | None) -> None:
    """Refuse an adoption that would produce a configuration nothing can build."""
    if not project.is_dir():
        raise PipelineError(f"no Unity project at {project}")
    if not (project / "Assets").is_dir():
        raise PipelineError(f"{project} has no Assets/ directory, so it is not a Unity project")
    _relative(project, mod_root, "the Unity project")
    if source_root:
        bundle_source_dir = project / source_root
        if not bundle_source_dir.is_dir():
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
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        written.append(target)
    return written
