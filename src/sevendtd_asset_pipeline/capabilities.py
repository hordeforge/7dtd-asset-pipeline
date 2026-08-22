"""The optional-capability registry: what is available, and what it unlocks.

The pipeline core is dependency-free on purpose, so several features are
optional. An agent must be able to ask *programmatically* which of them are
usable right now, what each one enables, and the exact command to install a
missing one — not scrape prose out of a diagnostic report.

This registry is the single source of truth. `7dtd-assets capabilities --json`,
the `capabilities` block in `status --json`, the `doctor` capability rows, and
the errors raised by the commands that need a capability all read from it, so
they cannot disagree.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache

from .errors import PipelineError


@dataclass(frozen=True)
class Capability:
    """One optional tool or library, and the feature it unlocks."""

    name: str
    kind: str
    """Either "command" (an executable on PATH) or "module" (an importable)."""
    unlocks: tuple[str, ...]
    """The `7dtd-assets` commands or generator scripts this makes usable."""
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


REGISTRY: tuple[_Spec, ...] = (
    _Spec(
        name="UnityPy",
        kind="module",
        probe="UnityPy",
        unlocks=("7dtd-assets inspect --deep",),
        purpose="list every serialized object and per-prefab component in a built bundle",
        install="pip install 'sevendtd-asset-pipeline[inspect]'",
    ),
    _Spec(
        name="trimesh",
        kind="module",
        probe="trimesh",
        unlocks=("7dtd-assets check-mesh",),
        purpose="mesh extents, watertightness, and geometry counts",
        install="pip install 'sevendtd-asset-pipeline[mesh]'",
    ),
    _Spec(
        name="gltf_validator",
        kind="command",
        probe="gltf_validator",
        unlocks=("7dtd-assets check-mesh",),
        purpose="Khronos glTF/GLB conformance for authored meshes",
        install="scripts/install-tools.sh --with-authoring",
    ),
    _Spec(
        name="blender",
        kind="command",
        probe="blender",
        unlocks=("scripts/generators/make-mesh.py",),
        purpose="authored mesh lane: organic, rigged, and sculpted geometry",
        install="scripts/install-tools.sh --with-authoring",
    ),
    _Spec(
        name="openscad",
        kind="command",
        probe="openscad",
        unlocks=("assets-src generators",),
        purpose="parametric hard-surface geometry",
        install="scripts/install-tools.sh --with-authoring",
    ),
    _Spec(
        name="pillow",
        kind="module",
        probe="PIL",
        unlocks=(
            "scripts/generators/make-icon.py",
            "scripts/generators/make-texture-maps.py",
        ),
        purpose="icon and texture generation",
        install="pip install 'sevendtd-asset-pipeline[authoring]'",
    ),
    _Spec(
        name="numpy",
        kind="module",
        probe="numpy",
        unlocks=("scripts/generators/make-texture-maps.py",),
        purpose="seeded numeric texture synthesis",
        install="pip install 'sevendtd-asset-pipeline[authoring]'",
    ),
    _Spec(
        name="magick",
        kind="command",
        probe="magick",
        unlocks=("assets-src generators",),
        purpose="deterministic raster transforms and contact sheets",
        install="scripts/install-tools.sh --with-authoring",
    ),
    _Spec(
        name="ffmpeg",
        kind="command",
        probe="ffmpeg",
        unlocks=("assets-src generators",),
        purpose="audio conversion, normalization, and filtering",
        install="scripts/install-tools.sh --with-authoring",
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
