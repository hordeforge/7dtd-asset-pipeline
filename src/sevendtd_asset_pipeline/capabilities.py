"""The optional-capability registry: what is available, and what it unlocks.

The pipeline core is dependency-free on purpose, so several features are
optional. An agent must be able to ask *programmatically* which of them are
usable right now, what each one enables, and the exact command to install a
missing one — not scrape prose out of a diagnostic report.

This registry is the single source of truth. `shamway capabilities --json`,
the `capabilities` block in `status --json`, the `doctor` capability rows, and
the errors raised by the commands that need a capability all read from it, so
they cannot disagree.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError


@dataclass(frozen=True)
class Capability:
    """One optional tool or library, and the feature it unlocks."""

    name: str
    kind: str
    """"command" (an executable on PATH), "module" (an importable), or
    "any-command" (satisfied by any one of several interchangeable tools)."""
    unlocks: tuple[str, ...]
    """The `shamway` commands or generator scripts this makes usable."""
    purpose: str
    install: str
    """The exact command that installs it."""
    available: bool
    path: str | None = None
    version: str | None = None

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["unlocks"] = list(self.unlocks)
        return data


@dataclass(frozen=True)
class _Spec:
    name: str
    kind: str
    probe: str
    unlocks: tuple[str, ...]
    purpose: str
    install: str


SOURCE_URL = "git+https://github.com/hordeforge/7dtd-asset-pipeline"


def installed_as_uv_tool() -> bool:
    """Whether this interpreter is a `uv tool install` environment.

    The distinction decides the install hint: `uv pip install` targets a venv
    the user activated, which a tool-installed `shamway` does not have. Its
    extras are added by reinstalling the tool with them.
    """
    prefix = Path(sys.prefix).as_posix()
    return "/uv/tools/" in prefix or prefix.endswith("/uv/tools")


def extra_install(extra: str) -> str:
    """The command that adds one optional-dependency extra to this install.

    Every hint pins the canonical git source, never the bare name: this
    project is not registered on PyPI, so an index-resolving hint fails
    outright today and resolves to whoever registers the name first tomorrow
    — dependency confusion on the exact line a user pastes into a shell.
    """
    if installed_as_uv_tool():
        return f"uv tool install --force '7dtd-asset-pipeline[{extra}] @ {SOURCE_URL}'"
    return f"uv pip install '7dtd-asset-pipeline[{extra}] @ {SOURCE_URL}'"


REGISTRY: tuple[_Spec, ...] = (
    _Spec(
        name="UnityPy",
        kind="module",
        probe="UnityPy",
        unlocks=(
            "shamway inspect --deep",
            "shamway pack",
            'shamway build with bundle_source = "synthesized"',
        ),
        purpose="read every serialized object in a bundle, and supply the engine's own "
        "per-revision type trees to the editorless bundle writer",
        install=extra_install("inspect"),
    ),
    _Spec(
        name="trimesh",
        kind="module",
        probe="trimesh",
        unlocks=(
            "shamway check-mesh",
            "shamway pack (meshes)",
            'shamway build with bundle_source = "synthesized" (meshes)',
        ),
        purpose="mesh extents, watertightness, geometry counts, and reading "
        "glTF/OBJ/STL/PLY into an editorless bundle",
        install=extra_install("mesh"),
    ),
    _Spec(
        name="fsb5",
        kind="module",
        probe="fsb5",
        unlocks=(
            "shamway generate audio from-bank",
            "the writer's own FSB5 round-trip check",
        ),
        purpose="decode an FSB5 bank back to PCM — the independent reader for the "
        "banks this project hand-writes, and for hearing a vanilla clip",
        install=extra_install("audio"),
    ),
    _Spec(
        name="gltf_validator",
        kind="command",
        probe="gltf_validator",
        unlocks=("shamway check-mesh",),
        purpose="Khronos glTF/GLB conformance for authored meshes",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="blender",
        kind="command",
        probe="blender",
        unlocks=("shamway generate mesh", "shamway generate mesh-icon"),
        purpose="authored mesh lane: organic, rigged, and sculpted geometry, exported "
        "as glTF straight into an editorless bundle, and the editorless icon render",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="gltfpack",
        kind="command",
        probe="gltfpack",
        unlocks=("shamway generate mesh-optimize",),
        purpose="simplify a mesh and reorder it for vertex-cache locality; it cuts "
        "triangles, which reaches the bundle, not bytes on disk, which does not",
        install="npm install -g gltfpack",
    ),
    _Spec(
        name="openscad",
        kind="command",
        probe="openscad",
        unlocks=(
            "shamway pack (.stl meshes it exports)",
            "a mod's own OpenSCAD generators",
        ),
        purpose="parametric hard-surface geometry; its STL output is a bundle input, "
        "so OpenSCAD reaches a .unity3d with no editor",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="pillow",
        kind="module",
        probe="PIL",
        unlocks=(
            "shamway render-icon",
            "shamway pack (textures)",
            "shamway generate icon",
            "shamway generate cutout",
            "shamway generate texture-maps",
            "alpha coverage in shamway check-icons",
        ),
        purpose="icon generation, background cutout, texture maps, and icon rendering",
        install=extra_install("authoring"),
    ),
    _Spec(
        name="numpy",
        kind="module",
        probe="numpy",
        unlocks=(
            "shamway generate texture-maps",
            "compress_textures (DXT1/DXT5 block compression)",
        ),
        purpose="seeded numeric texture synthesis, and the block compressor that "
        "shrinks a synthesized texture 4-8x",
        install=extra_install("authoring"),
    ),
    _Spec(
        name="magick",
        kind="command",
        probe="magick",
        unlocks=(
            "shamway pack (.svg/.psd/.exr/.webp/.avif textures)",
            "a mod's own image generators",
        ),
        purpose="rasterize the source formats Pillow cannot read — vector art above "
        "all — plus deterministic raster transforms for a mod's own scripts",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="xvfb",
        kind="command",
        probe="xvfb-run",
        unlocks=("shamway render-icon on a headless host",),
        purpose="a virtual display; the icon renderer needs a real graphics device and "
        "silently produces a blank image without one",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="desktop-capture",
        kind="any-command",
        probe="grim spectacle gnome-screenshot maim scrot import",
        unlocks=("shamway client capture",),
        purpose="a screenshot tool for the current desktop session, so a human "
        "visual sign-off leaves a citable frame instead of only a claim",
        install="shamway script install-tools --with-desktop-capture",
    ),
    _Spec(
        name="ffmpeg",
        kind="command",
        probe="ffmpeg",
        unlocks=(
            "shamway pack (.ogg/.mp3/.flac/.aiff/.m4a/.opus/.wma clips)",
            "a mod's own audio scripts",
        ),
        purpose="decode the compressed containers the standard library cannot open, "
        "plus conversion, normalization and filtering for a mod's own scripts",
        install="shamway script install-tools --with-authoring",
    ),
)


def _command_version(executable: str) -> str | None:
    """Best-effort version string. A tool that cannot report one is still usable."""
    for flag in ("--version", "-version"):
        try:
            result = subprocess.run(
                [executable, flag],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0][:120]
    return None


def _module_version(module: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    for candidate in (module, module.lower(), module.replace("PIL", "pillow")):
        try:
            return version(candidate)
        except PackageNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - metadata problems must not break the report
            return None
    return None


def _resolve(spec: _Spec, probe_versions: bool) -> Capability:
    if spec.kind == "module":
        available = importlib.util.find_spec(spec.probe) is not None
        return Capability(
            name=spec.name,
            kind=spec.kind,
            unlocks=spec.unlocks,
            purpose=spec.purpose,
            install=spec.install,
            available=available,
            path=None,
            version=_module_version(spec.probe) if (available and probe_versions) else None,
        )
    # A command kind: "command" probes one executable, while "any-command"
    # accepts the first present of several interchangeable tools — and which
    # one it is matters to the report, so `path` names it.
    candidates = [spec.probe] if spec.kind == "command" else spec.probe.split()
    path = next((found for name in candidates if (found := shutil.which(name))), None)
    return Capability(
        name=spec.name,
        kind=spec.kind,
        unlocks=spec.unlocks,
        purpose=spec.purpose,
        install=spec.install,
        available=path is not None,
        path=path,
        version=_command_version(path) if (path and probe_versions) else None,
    )


def capabilities(probe_versions: bool = False) -> list[Capability]:
    """Every optional capability and whether it is usable right now.

    `probe_versions` runs each present executable to read its version, which
    costs a subprocess per tool; leave it off for a fast availability check.
    """
    return [_resolve(spec, probe_versions) for spec in REGISTRY]


def _availability() -> dict[str, bool]:
    # Deliberately recomputed on every ask rather than cached: a `shamway serve`
    # session outlives the installs its own error messages call for, and a
    # frozen answer would have `capabilities` report a capability as present
    # while every gated operation keeps refusing it. The probes are
    # `find_spec` and `which` — cheap next to any operation they gate.
    return {capability.name: capability.available for capability in capabilities()}


def has_capability(name: str) -> bool:
    return _availability().get(name, False)


def require_capability(name: str) -> None:
    """Raise a message that names the capability and how to install it."""
    if has_capability(name):
        return
    spec = next((item for item in REGISTRY if item.name == name), None)
    if spec is None:
        raise PipelineError(f"unknown capability {name!r}")
    raise PipelineError(
        f"{', '.join(spec.unlocks)} needs the optional capability {spec.name!r} "
        f"({spec.purpose}). Install it with: {spec.install}"
    )
