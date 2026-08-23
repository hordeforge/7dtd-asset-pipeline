"""The operation registry: one machine-readable description of what this does.

Programmatic consumers of a build tool come in three shapes, and all three are
served from this one table rather than from three drifting implementations:

1. Python callers, through the `Pipeline` facade in `api.py`.
2. Other languages and CI, through `7dtd-assets call NAME --params '{...}'`,
   which is a subprocess away from anything.
3. Anything that needs many operations cheaply, through `7dtd-assets serve`,
   a line-delimited JSON request/response loop that pays process start once.

`7dtd-assets schema --json` publishes this table, so a consumer discovers the
operations, their JSON Schema parameters, what each returns, whether it writes,
what it costs, and which optional capability it needs — without parsing help
text or prose. A wrapper for any protocol can be generated from that manifest;
none is baked in here, because a local build tool should not carry a server.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .errors import PipelineError

# Cost classes, so a caller can decide what to run in a tight loop.
INSTANT = "instant"  # no I/O beyond the mod directory
FAST = "fast"  # parses a bundle or runs a local tool
SECONDS = "seconds"  # subprocess or network round trip
MINUTES = "minutes"  # starts a real Unity editor


@dataclass(frozen=True)
class Operation:
    name: str
    summary: str
    parameters: dict[str, Any]
    """JSON Schema for the params object."""
    returns: str
    cost: str
    writes: bool
    """True when the operation modifies files outside the build directory."""
    needs_config: bool
    needs_network: bool = False
    capabilities: tuple[str, ...] = ()
    handler: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    def describe(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("handler", None)
        data["capabilities"] = list(self.capabilities)
        return data


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


PATH_PARAM = {"type": "string", "description": "filesystem path"}

_DEFINITIONS: tuple[Operation, ...] = (
    Operation(
        name="status",
        summary="Whole-mod state: bundle, manifest, references, validity, capabilities. "
        "Never raises for a mod-state problem; problems are collected into the result.",
        parameters=_schema(),
        returns="Status: bundle_present, bundle_unity_version, version_matches_game, "
        "asset_count, references, valid, problems, capabilities",
        cost=INSTANT,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="capabilities",
        summary="Optional capabilities, what each unlocks, and the command that installs it.",
        parameters=_schema({"probe_versions": {"type": "boolean", "default": False}}),
        returns="list[Capability]: name, kind, available, version, unlocks, install",
        cost=INSTANT,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="doctor",
        summary="Host readiness: mod identity, project revision, engine modules, game "
        "revision, editor, Windows Build Support, and capabilities.",
        parameters=_schema(),
        returns="list[Check]: status (OK|WARN|INFO|FAIL), name, detail",
        cost=SECONDS,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="validate",
        summary="Validate the staged bundle and every bundle URI under Config/.",
        parameters=_schema({"bundle": PATH_PARAM}),
        returns="ValidationReport: messages, reference_count",
        cost=FAST,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="refs",
        summary="Every bundle URI discovered recursively in the mod's Config/ XML.",
        parameters=_schema(),
        returns="list of {source, uri, mod_name, bundle_path, asset_stem}",
        cost=INSTANT,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="inspect",
        summary="UnityFS metadata for one bundle: revision, archive format, class IDs, "
        "and whether the required class-142 AssetBundle object is present.",
        parameters=_schema({"bundle": PATH_PARAM}),
        returns="BundleInfo: path, unity_version, archive_format, class_ids, "
        "has_assetbundle_object",
        cost=FAST,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="inspect_deep",
        summary="Every serialized object in a bundle and, per prefab, the component "
        "census across its whole hierarchy. Answers whether a component survived a "
        "stripped engine module, which the class-142 gate cannot.",
        parameters=_schema({"bundle": PATH_PARAM}),
        returns="DeepReport: object_count, type_counts, entries[]",
        cost=FAST,
        writes=False,
        needs_config=True,
        capabilities=("UnityPy",),
    ),
    Operation(
        name="check_mesh",
        summary="Check an authored mesh before Unity import: extents, watertightness, "
        "geometry counts, and glTF conformance.",
        parameters=_schema(
            {
                "mesh": PATH_PARAM,
                "max_extent": {"type": "number", "default": 16.0},
                "strict": {"type": "boolean", "default": False},
            },
            required=["mesh"],
        ),
        returns="MeshReport: extents, vertex_count, face_count, watertight, "
        "gltf_errors, problems, skipped, ok",
        cost=FAST,
        writes=False,
        needs_config=False,
        capabilities=("trimesh",),
    ),
    Operation(
        name="check_sound",
        summary="Measure a WAV clip and reject the format mistakes a listener cannot fix: "
        "channels, sample rate, level, clipping, DC offset, and edge silence.",
        parameters=_schema(
            {
                "clip": PATH_PARAM,
                "max_seconds": {"type": "number", "default": 30.0},
                "require_mono": {"type": "boolean", "default": True},
            },
            required=["clip"],
        ),
        returns="SoundReport: channels, sample_rate, duration_seconds, peak, peak_dbfs, rms, "
        "dc_offset, clipped_samples, leading/trailing silence, problems, notes, ok",
        cost=FAST,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="check_icons",
        summary="Check this mod's UIAtlases PNGs as atlas cells and reconcile them with every "
        "CustomIcon key under Config/. Icons are not bundle members, so 'validate' cannot "
        "see them.",
        parameters=_schema(
            {
                "atlas_root": {"type": "string", "default": "UIAtlases"},
                "cell": {"type": "integer", "default": 160},
            }
        ),
        returns="IconReport: atlas_dir, icons[], resolved, external, problems, notes, ok",
        cost=INSTANT,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="render_icon",
        summary="Photograph a bundle prefab into an atlas icon with the editor, so the icon "
        "cannot drift from the mesh. Needs a graphics device; never uses -nographics.",
        parameters=_schema(
            {
                "prefab": {"type": "string", "description": "bundle stem or Assets/... path"},
                "output": PATH_PARAM,
                "size": {"type": "integer", "default": 160},
                "atlas": {"type": "string", "default": "ItemIconAtlas"},
                "yaw": {"type": "number", "default": 208.0},
                "pitch": {"type": "number", "default": 8.0},
                "padding": {"type": "number", "default": 1.22},
            },
            required=["prefab"],
        ),
        returns="RenderResult: prefab, output, size, rendered_pixels, alpha_coverage, log",
        cost=MINUTES,
        writes=True,
        needs_config=True,
        capabilities=("pillow",),
    ),
    Operation(
        name="check_log",
        summary="Reject a Unity build log that reports success while stripping engine "
        "modules.",
        parameters=_schema({"log": PATH_PARAM}, required=["log"]),
        returns="{ok: true} or an error naming every offending log line",
        cost=INSTANT,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="unity_release",
        summary="Resolve the official Unity editor download for a revision: changeset, "
        "archive URL, and the MD5 each download must match.",
        parameters=_schema(
            {"version": {"type": "string"}, "platform": {"type": "string", "default": "LINUX"}}
        ),
        returns="Release: version, changeset, editor_url, editor_md5, "
        "windows_mono_url, windows_mono_md5",
        cost=SECONDS,
        writes=False,
        needs_config=False,
        needs_network=True,
    ),
    Operation(
        name="build",
        summary="Build, gate, and stage the bundle. With probe=true, builds a throwaway "
        "cube bundle that proves the environment and stages nothing. This is the only "
        "operation that writes into the modlet, and only after every gate passes.",
        parameters=_schema({"probe": {"type": "boolean", "default": False}}),
        returns="{bundle: path}",
        cost=MINUTES,
        writes=True,
        needs_config=True,
    ),
    Operation(
        name="init",
        summary="Scaffold the pipeline into an existing modlet. Refuses to overwrite.",
        parameters=_schema(
            {
                "mod_root": PATH_PARAM,
                "unity_version": {"type": "string"},
                "game_dir": PATH_PARAM,
                "mod_name": {"type": "string"},
                "bundle_name": {"type": "string"},
                "changeset": {"type": "string"},
            },
            required=["mod_root"],
        ),
        returns="{created: [paths]}",
        cost=FAST,
        writes=True,
        needs_config=False,
    ),
)

OPERATIONS: dict[str, Operation] = {item.name: item for item in _DEFINITIONS}


def manifest() -> dict[str, Any]:
    """The full machine-readable contract, as published by `schema --json`."""
    from . import __version__

    return {
        "name": "7dtd-asset-pipeline",
        "version": __version__,
        "description": "Build and validate Unity asset bundles for 7 Days to Die mods.",
        "conventions": {
            "config": "Operations with needs_config resolve .7dtd-assets.toml upward "
            "from the working directory unless a config path is supplied.",
            "errors": "A failed operation reports a single user-actionable message. "
            "The CLI exits non-zero and prints 'ERROR: ...' to stderr; 'call' and "
            "'serve' return {ok: false, error: {message, type}}.",
            "capabilities": "An operation naming capabilities fails with an install "
            "command when one is missing. Query them with the 'capabilities' operation.",
            "paths": "Relative paths resolve against the mod root.",
        },
        "operations": [item.describe() for item in _DEFINITIONS],
        # Not operations: they are argv-passthrough commands rather than
        # JSON-in/JSON-out calls. Published here so a consumer can discover the
        # whole surface from one document instead of scraping help text.
        "generators": _generators(),
        "documentation": _documentation(),
    }


def _generators() -> list[dict[str, Any]]:
    """The packaged asset generators, callable as `7dtd-assets generate NAME`."""
    from .generators import describe

    return describe()


def _documentation() -> list[dict[str, str]]:
    """The packaged documentation, readable as `7dtd-assets docs TOPIC`."""
    from .docs import topics

    return topics()


def get(name: str) -> Operation:
    try:
        return OPERATIONS[name]
    except KeyError:
        known = ", ".join(sorted(OPERATIONS))
        raise PipelineError(f"unknown operation {name!r}; expected one of: {known}") from None
