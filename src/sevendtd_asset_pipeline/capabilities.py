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
from pathlib import Path
from dataclasses import asdict, dataclass
from functools import lru_cache

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


SOURCE_URL = "git+https://github.com/ywy50/7dtd-asset-pipeline"


def installed_as_uv_tool() -> bool:
    """Whether this interpreter is a `uv tool install` environment.

    The distinction decides the install hint: `uv pip install` targets a venv
    the user activated, which a tool-installed `shamway` does not have. Its
    extras are added by reinstalling the tool with them.
    """
    prefix = Path(sys.prefix).as_posix()
    return "/uv/tools/" in prefix or prefix.endswith("/uv/tools")


def extra_install(extra: str) -> str:
    """The command that adds one optional-dependency extra to this install."""
    if installed_as_uv_tool():
        return f"uv tool install --force '7dtd-asset-pipeline[{extra}] @ {SOURCE_URL}'"
    return f"uv pip install '7dtd-asset-pipeline[{extra}]'"


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
        unlocks=("shamway check-mesh",),
        purpose="mesh extents, watertightness, and geometry counts",
        install=extra_install("mesh"),
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
        unlocks=("shamway generate mesh",),
        purpose="authored mesh lane: organic, rigged, and sculpted geometry",
        install="shamway script install-tools --with-authoring",
    ),
    _Spec(
        name="openscad",
        kind="command",
        probe="openscad",
        unlocks=("a mod's own OpenSCAD generators",),
        purpose="parametric hard-surface geometry",
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
        unlocks=("shamway generate texture-maps",),
        purpose="seeded numeric texture synthesis",
        install=extra_install("authoring"),
    ),
    _Spec(
        name="magick",
        kind="command",
        probe="magick",
        unlocks=("a mod's own image generators",),
        purpose="deterministic raster transforms and contact sheets",
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
        unlocks=("a mod's own audio scripts",),
        purpose="audio conversion, normalization, and filtering",
        install="shamway script install-tools --with-authoring",
    ),
)


def _command_version(executable: str) -> str | None:
    """Best-effort version string. A tool that cannot report one is still usable."""
    for flag in ("--version", "-version"):
        try:
            result = subprocess.run(
                [executable, flag], check=False, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0][:120]
    return None


def _module_version(module: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    for candidate in (module, module.lower(), module.replace("PIL", "pillow")):
        try:
            return version(candidate)
        except PackageNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - metadata problems must not break the report
            return None
    return None


def _resolve(spec: _Spec, probe_versions: bool) -> Capability:
    if spec.kind == "any-command":
        # Interchangeable tools: the first one present satisfies the capability,
        # and which one it is matters to the report, so `path` names it.
        path = next(
            (found for name in spec.probe.split() if (found := shutil.which(name))), None
        )
        return Capability(
            name=spec.name, kind=spec.kind, unlocks=spec.unlocks, purpose=spec.purpose,
            install=spec.install, available=path is not None, path=path,
            version=_command_version(path) if (path and probe_versions) else None,
        )
    if spec.kind == "command":
        path = shutil.which(spec.probe)
        return Capability(
            name=spec.name, kind=spec.kind, unlocks=spec.unlocks, purpose=spec.purpose,
            install=spec.install, available=path is not None, path=path,
            version=_command_version(path) if (path and probe_versions) else None,
        )
    available = importlib.util.find_spec(spec.probe) is not None
    return Capability(
        name=spec.name, kind=spec.kind, unlocks=spec.unlocks, purpose=spec.purpose,
        install=spec.install, available=available, path=None,
        version=_module_version(spec.probe) if (available and probe_versions) else None,
    )


def capabilities(probe_versions: bool = False) -> list[Capability]:
    """Every optional capability and whether it is usable right now.

    `probe_versions` runs each present executable to read its version, which
    costs a subprocess per tool; leave it off for a fast availability check.
    """
    return [_resolve(spec, probe_versions) for spec in REGISTRY]


@lru_cache(maxsize=None)
def _availability() -> dict[str, bool]:
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
