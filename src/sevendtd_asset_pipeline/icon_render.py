"""Render a bundle prefab into an atlas icon, through the editor.

This is the second of the two icon lanes (the first is generated or drawn art;
see docs/authoring/art-direction.md). It exists because an icon that *is* the item cannot
drift from the item: regenerating the mesh regenerates the icon.

Three mistakes are designed out here rather than documented:

* **`-nographics` produces a blank image, not an error.** Unity runs the editor
  method, `Camera.Render()` draws nothing, and the PNG is a uniform transparent
  square. The build path uses `-nographics` deliberately; this path must not,
  so the flag is simply never passed and a headless host is told to put an X
  server (`xvfb-run`) in front of the command.
* **A stale prefab renders perfectly.** The mod's `[ShamwayPreBuild]`
  generators run before the camera does, so an icon cannot be a photograph of
  the geometry from before the last edit.
* **A blank render looks like a framing bug.** The coverage check below fails
  the command when almost nothing was drawn, which turns a silent bad icon into
  an actionable message.

Supersampling and the Lanczos downscale happen here rather than in the editor
because a real resampler is what keeps thin geometry from breaking into dashes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from . import atomic
from .capabilities import require_capability
from .config import PipelineConfig
from .errors import PipelineError
from .icon_check import DEFAULT_CELL, inspect_icon
from .unity_process import run_unity

SUPERSAMPLE = 4
MINIMUM_COVERAGE = 0.02
# The camera and framing a rendered icon is accepted at, shared with the
# published schema (operations.py) and the CLI (--size/--atlas/--yaw/--pitch/
# --padding). `DEFAULT_ATLAS` is the inventory atlas those angles were tuned on.
DEFAULT_ATLAS = "ItemIconAtlas"
DEFAULT_YAW = 208.0
DEFAULT_PITCH = 8.0
DEFAULT_PADDING = 1.22


def _graphics_device_args() -> list[str]:
    """Ask the editor for a real device without pinning a Linux-only API.

    `-force-glcore` is load-bearing under Xvfb: Vulkan has nothing to present
    to there. macOS and Windows editors use Metal and D3D11; forcing GLCore
    on those hosts either fails the launch or is ignored. This process is the
    editor's host, so `sys.platform` is the right probe.
    """
    if sys.platform.startswith("linux"):
        return ["-force-glcore"]
    return []


@dataclass(frozen=True)
class RenderResult:
    prefab: str
    output: str
    size: int
    rendered_pixels: int
    alpha_coverage: float | None
    log: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _resolve_prefab(config: PipelineConfig, prefab: str) -> str:
    """Accept a bundle stem or a project-relative path, and return the latter."""
    if prefab.startswith("Assets/"):
        candidate = config.unity_project / prefab
        if not candidate.is_file():
            raise PipelineError(f"no prefab at {candidate}")
        return prefab
    root = config.unity_project / config.source_root
    matches = sorted(root.rglob(f"{prefab}.prefab")) if root.is_dir() else []
    if not matches:
        raise PipelineError(
            f"no prefab named {prefab!r} below {root}; pass a project-relative "
            "'Assets/...' path, or build the prefab first"
        )
    if len(matches) > 1:
        listed = ", ".join(str(match.relative_to(config.unity_project)) for match in matches)
        raise PipelineError(
            f"{prefab!r} matches several prefabs ({listed}); bundle stems must be unique, "
            "so fix the duplicate before rendering it"
        )
    return str(matches[0].relative_to(config.unity_project))


def _downscale(source: Path, destination: Path, size: int) -> float:
    require_capability("pillow")
    from PIL import Image

    with Image.open(source) as image:
        resized = image.convert("RGBA").resize((size, size), Image.LANCZOS)
        # The format is named explicitly because PIL infers nothing from a
        # temporary name.
        with atomic.staged_write(destination) as staged:
            resized.save(staged, "PNG")
        counts = resized.getchannel("A").histogram()
    opaque: int = sum(counts[9:])
    return opaque / float(size * size)


def render_icon(
    config: PipelineConfig,
    prefab: str,
    output: Path | str | None = None,
    size: int = DEFAULT_CELL,
    atlas: str = DEFAULT_ATLAS,
    yaw: float = DEFAULT_YAW,
    pitch: float = DEFAULT_PITCH,
    padding: float = DEFAULT_PADDING,
    *,
    timeout: int = 900,
) -> RenderResult:
    """Render `prefab` (a bundle stem or project path) into an atlas PNG."""
    # It photographs a prefab out of the bundle's source folder, so a mod with
    # no bundle should hear that, not a complaint about an unset UNITY_EDITOR.
    config.require_bundle()
    if config.unity_editor is None:
        raise PipelineError("UNITY_EDITOR is not configured; run 'shamway doctor'")
    if not config.unity_editor.is_file() or not os.access(config.unity_editor, os.X_OK):
        raise PipelineError(f"Unity editor is not executable: {config.unity_editor}")
    require_capability("pillow")

    project_path = _resolve_prefab(config, prefab)
    stem = Path(project_path).stem
    destination = Path(output) if output else config.mod_root / "UIAtlases" / atlas / f"{stem}.png"
    if not destination.is_absolute():
        destination = (config.mod_root / destination).resolve()

    work = config.build_dir / "icons"
    work.mkdir(parents=True, exist_ok=True)
    large = work / f"{stem}@{SUPERSAMPLE}x.png"
    log = work / "unity-icon.log"
    pixels = size * SUPERSAMPLE

    command = [
        str(config.unity_editor),
        "-batchmode",
        "-quit",
        # No -nographics: see this module's docstring. A Linux editor under
        # Xvfb needs -force-glcore; other hosts pick Metal or D3D11 themselves.
        *_graphics_device_args(),
        "-projectPath",
        str(config.unity_project),
        "-executeMethod",
        "SevenDaysToDie.AssetPipeline.IconRenderer.RenderFromCommandLine",
        "-logFile",
        str(log),
        # The mod's [ShamwayPreBuild] generators run before the render, so a
        # regenerated mesh is what gets photographed; they need the same folder
        # a build would give them.
        "-sapSourceRoot",
        config.source_root,
        "-sapIconPrefab",
        project_path,
        "-sapIconOutput",
        str(large),
        "-sapIconPixels",
        str(pixels),
        "-sapIconYaw",
        f"{yaw:g}",
        "-sapIconPitch",
        f"{pitch:g}",
        "-sapIconPadding",
        f"{padding:g}",
    ]
    # The same bound a verify-bundle editor gets: an editor that hangs (the
    # Proton async-load starvation is one documented way) must fail the run
    # with its log named, not hold the command forever.
    try:
        result = run_unity(command, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"Unity did not finish rendering {project_path} within {timeout}s and was "
            f"killed; its partial log is {log}. On a machine with no display, run this "
            "command under 'xvfb-run -a'."
        ) from exc
    if result.returncode != 0:
        raise PipelineError(
            f"Unity exited {result.returncode} while rendering {project_path}; inspect {log}. "
            "On a machine with no display, run this command under 'xvfb-run -a'."
        )
    if not large.is_file():
        raise PipelineError(f"Unity reported success but wrote no image: {large}; inspect {log}")

    coverage = _downscale(large, destination, size)
    if coverage < MINIMUM_COVERAGE:
        raise PipelineError(
            f"the render is {coverage * 100:.1f}% covered, which means the camera framed "
            "almost nothing. Check that the prefab has renderers, and that this ran with a "
            f"graphics device (never -nographics). Kept the full-size render at {large}."
        )
    icon = inspect_icon(destination, atlas, size)
    if icon.problems:
        raise PipelineError(
            f"{destination} is not a usable atlas cell: " + "; ".join(icon.problems)
        )
    return RenderResult(
        prefab=project_path,
        output=str(destination),
        size=size,
        rendered_pixels=pixels,
        alpha_coverage=round(coverage, 4),
        log=str(log),
    )
