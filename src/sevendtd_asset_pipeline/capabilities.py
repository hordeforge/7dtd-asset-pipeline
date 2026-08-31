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
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from . import shader_blob
from .errors import PipelineError
from .providers import configuration_state


@dataclass(frozen=True)
class Capability:
    """One optional tool or library, and the feature it unlocks."""

    name: str
    kind: str
    """"command" (an executable on PATH), "module" (an importable),
    "any-command" (satisfied by any one of several interchangeable tools), or
    "provider-config" (a credential present in the environment)."""
    unlocks: tuple[str, ...]
    """The `shamway` commands or generator scripts this makes usable."""
    purpose: str
    install: str
    """The exact command that installs it."""
    available: bool
    path: str | None = None
    version: str | None = None
    unusable_reason: str | None = None
    """Why a tool that *is* on PATH still cannot do the job.

    Presence is not capability. A distribution can package a version of a tool
    that predates the feature this pipeline needs, and probing only with
    `which` reports it available, lets a build start, and fails in the middle
    with the tool's own error — the exact silent-until-late failure this
    project exists to move earlier. When this is set, `available` is `False`
    and this says what was measured.
    """

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
    usable: Callable[[str], str | None] | None = None
    """An extra check for a command that is present but may be too old.

    Takes the resolved path, returns `None` when the tool can do the job or a
    one-line reason when it cannot. Only run when the executable was found, so
    it costs at most one subprocess on a host that has the tool at all.
    """


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


# vkd3d-shader grew HLSL source support in 1.3 (WineHQ, March 2022). Debian and
# Ubuntu both still package 1.2 — measured: Ubuntu noble ships
# vkd3d-compiler 1.2-15build1, and a GitHub runner with it installed answered
# `vkd3d-compiler failed for profile vs_4_0: Invalid source type 'hlsl'`
# half-way through a build. Asking the binary which source types it supports
# beats comparing a version string: it is the same question the writer asks.
VKD3D_HLSL_HINT = (
    "it is older than vkd3d 1.3 and cannot read HLSL source, which is what this "
    "writer compiles (Debian and Ubuntu package 1.2). Build a usable one with: "
    "shamway script install-tools --with-vkd3d-source"
)


def _vkd3d_reads_hlsl(path: str) -> str | None:
    """Whether this `vkd3d-compiler` can take HLSL in, not merely whether it exists."""
    try:
        listed = subprocess.run(
            [path, "--print-source-types"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "it could not be run to ask which source types it supports"
    # A build old enough not to know the flag fails it, which is the answer.
    if listed.returncode != 0 or "hlsl" not in listed.stdout:
        return VKD3D_HLSL_HINT
    return None


def _zmolv_present(_probe: str) -> str | None:
    """Whether the SMOL-V encoder can actually be loaded, not merely imported."""
    if shader_blob.smolv_library() is None:
        return (
            "the zmol-v shared library is not on this host, so a synthesized shader "
            "carries no Vulkan sub-program"
        )
    return None


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
        name="vkd3d-compiler",
        kind="command",
        probe="vkd3d-compiler",
        usable=_vkd3d_reads_hlsl,
        unlocks=(
            "shamway pack (prefabs and materials)",
            'shamway build with bundle_source = "synthesized" (prefabs and materials)',
        ),
        purpose="compile the unlit shader's HLSL to the DXBC shader model 4 bytecode a "
        "d3d11 sub-program carries, so a synthesized bundle can ship a material and a "
        "visible prefab with no editor",
        # In the base set, not --with-authoring: it belongs to the default
        # build path rather than to an optional art lane.
        install="shamway script install-tools",
    ),
    _Spec(
        name="libzmolv",
        kind="module",
        probe="sevendtd_asset_pipeline.shader_blob",
        usable=_zmolv_present,
        unlocks=("a Vulkan sub-program in a synthesized shader (ShaderCompilerPlatform 18)",),
        purpose="compress the SPIR-V a Vulkan sub-program carries into the SMOL-V Unity "
        "stores. A client running Vulkan has no sub-program to create without it; every "
        "other graphics API is unaffected",
        install="scripts/install-tools.sh (builds the pinned zmol-v into this "
        "checkout's .local/lib); ZMOLV_LIBRARY overrides the search",
    ),
    _Spec(
        name="glslangValidator",
        kind="command",
        probe="glslangValidator",
        unlocks=("the SPIR-V a Vulkan sub-program carries, alongside the SMOL-V encoder",),
        purpose="compile this writer's HLSL to SPIR-V for shader platform 18 the way "
        "Unity itself does. A host with the SMOL-V encoder but without it refuses to "
        "synthesize a shader rather than silently dropping that platform",
        install="shamway script install-tools",
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
        name="lxml",
        kind="module",
        probe="lxml",
        unlocks=("shamway check-patches (full XPath 1.0)",),
        purpose="evaluate Config/ patch XPaths with the full XPath 1.0 the engine's "
        "XPathEvaluate uses. Without it check-patches falls back to the standard-library "
        "subset and reports selectors it cannot run as not checked",
        install=extra_install("patch"),
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
        install="bun install -g gltfpack",
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
    _Spec(
        name="model-audio-review",
        kind="provider-config",
        probe="sevendtd_asset_pipeline.providers",
        unlocks=("shamway review-audio",),
        purpose="submit an authored clip's actual bytes plus its recorded intended-use "
        "intent to a configured audio-capable model (Gemini) for an advisory critique. "
        "Availability reports a credential present in the environment — configured, "
        "not verified: nothing contacts the provider until a review is submitted, and "
        "the verdict never satisfies the human-listen gate",
        # The one capability installed by setting an environment variable
        # rather than installing a tool; the command below is still exact.
        install="export GEMINI_API_KEY=<key>  # create one at https://aistudio.google.com/apikey",
    ),
    _Spec(
        name="model-video-review",
        kind="command",
        probe="deadeye",
        unlocks=("shamway review-video",),
        purpose="submit an adopted clip's frames or muxed video plus its recorded "
        "intent to a configured vision-capable model (the deadeye gateway in "
        "hordeforge/7dtd-vision-review) for an advisory critique. Availability "
        "reports the gateway CLI on PATH — configured, not verified: nothing "
        "contacts a provider until a review is submitted, and the verdict never "
        "satisfies the human-look gate",
        install="uv tool install --from git+https://github.com/hordeforge/7dtd-vision-review",
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
    if spec.kind == "provider-config":
        # Credential presence only, from environment variables: discovery,
        # `doctor`, and `status` must never contact a provider or verify a
        # key. "Configured" is therefore not "verified" — the verification
        # happens at submission time and nowhere else.
        state = configuration_state()
        configured = sorted(name for name, found in state.items() if found == "configured")
        available = bool(configured)
        return Capability(
            name=spec.name,
            kind=spec.kind,
            unlocks=spec.unlocks,
            purpose=spec.purpose,
            install=spec.install,
            available=available,
            path=None,
            version=None,
            unusable_reason=None
            if available
            else f"no provider credential is configured (checked offline: "
            f"{', '.join(sorted(state))}); {spec.install}",
        )
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
    reason = spec.usable(path) if (path and spec.usable) else None
    return Capability(
        name=spec.name,
        kind=spec.kind,
        unlocks=spec.unlocks,
        purpose=spec.purpose,
        install=spec.install,
        # A present-but-incapable tool is *not* available: every caller gating
        # on this must take the same branch it takes for an absent one, or the
        # build starts and dies half-way through instead of degrading.
        available=path is not None and reason is None,
        path=path,
        version=_command_version(path) if (path and probe_versions) else None,
        unusable_reason=reason,
    )


def capabilities(probe_versions: bool = False) -> list[Capability]:
    """Every optional capability and whether it is usable right now.

    `probe_versions` runs each present executable to read its version, which
    costs a subprocess per tool; leave it off for a fast availability check.
    """
    return [_resolve(spec, probe_versions) for spec in REGISTRY]


_SPEC_BY_NAME: dict[str, _Spec] = {spec.name: spec for spec in REGISTRY}


def _availability() -> dict[str, bool]:
    # Deliberately recomputed on every ask rather than cached: a `shamway serve`
    # session outlives the installs its own error messages call for, and a
    # frozen answer would have `capabilities` report a capability as present
    # while every gated operation keeps refusing it. The probes are
    # `find_spec` and `which` — cheap next to any operation they gate.
    return {capability.name: capability.available for capability in capabilities()}


def has_capability(name: str) -> bool:
    """One capability's availability, probed fresh.

    Resolves only the named spec rather than sweeping the whole registry:
    these gates sit inside per-texture and per-class loops (`compress`,
    `check_texture`, the bundle writer's type trees), and a sweep runs every
    command probe (including the `usable` subprocess for a tool like
    `vkd3d-compiler`) to answer a question about one module. Freshness is
    unchanged: no answer is ever cached across asks.
    """
    spec = _SPEC_BY_NAME.get(name)
    return _resolve(spec, probe_versions=False).available if spec is not None else False


def require_capability(name: str) -> None:
    """Raise a message that names the capability and how to install it."""
    if has_capability(name):
        return
    spec = _SPEC_BY_NAME.get(name)
    if spec is None:
        raise PipelineError(f"unknown capability {name!r}")
    # A tool that is present but too old needs a different sentence from one
    # that is absent: "install it" is useless advice when it is installed.
    # (For provider-config capabilities the same distinction separates an
    # unconfigured credential from anything PATH-shaped.) Only the failed
    # capability is re-resolved, for its reason; the sweep a whole-registry
    # report would pay buys nothing here.
    found = _resolve(spec, probe_versions=False)
    if found.unusable_reason:
        raise PipelineError(
            f"{', '.join(spec.unlocks)} needs the optional capability {spec.name!r} "
            f"({spec.purpose}), and the one on this host cannot be used: "
            f"{found.unusable_reason}"
        )
    raise PipelineError(
        f"{', '.join(spec.unlocks)} needs the optional capability {spec.name!r} "
        f"({spec.purpose}). Install it with: {spec.install}"
    )
