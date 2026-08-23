"""The operation registry: one machine-readable description of what this does.

Programmatic consumers of a build tool come in three shapes, and all three are
served from this one table rather than from three drifting implementations:

1. Python callers, through the `Pipeline` facade in `api.py`.
2. Other languages and CI, through `shamway call NAME --params '{...}'`,
   which is a subprocess away from anything.
3. Anything that needs many operations cheaply, through `shamway serve`,
   a line-delimited JSON request/response loop that pays process start once.

`shamway schema --json` publishes this table, so a consumer discovers the
operations, their JSON Schema parameters, what each returns, whether it writes,
what it costs, and which optional capability it needs — without parsing help
text or prose. A wrapper for any protocol can be generated from that manifest;
none is baked in here, because a local build tool should not carry a server.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ._version import __version__
from .config import BUNDLE_SOURCES
from .docs import topics
from .errors import PipelineError
from .generators import GeneratorInfo, describe
from .prompts import KEYS, KINDS, kinds

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

    def describe(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = list(self.capabilities)
        return data


def _schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, object]:
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
        summary="Produce, gate and stage the bundle. With bundle_source \"unity\" a local "
        "editor builds it and probe=true proves the environment with a throwaway cube; with "
        "\"synthesized\" this tool writes it directly, no editor. Refused for \"external\" "
        "and \"none\"; use 'stage' there.",
        parameters=_schema({"probe": {"type": "boolean", "default": False}}),
        returns="{bundle: path}",
        cost=MINUTES,
        writes=True,
        needs_config=True,
    ),
    Operation(
        name="pack",
        summary="Synthesize a .unity3d from a directory of textures, clips and text files "
        "with no Unity at all, plus the membership manifest that records what went in. "
        "Writes the container, the type trees and every object directly.",
        parameters=_schema(
            {
                "source": {**PATH_PARAM, "description": "directory whose files become assets"},
                "output": {**PATH_PARAM, "description": "the .unity3d to write"},
                "unity_version": {"type": "string", "description": "revision to stamp"},
                "game_dir": {**PATH_PARAM, "description": "read the revision from a game install"},
                "manifest": {**PATH_PARAM, "description": "default: OUTPUT.manifest"},
            },
            required=["source", "output"],
        ),
        returns="{bundle, manifest, bytes, assets[], caveats[]}",
        cost=FAST,
        writes=True,
        needs_config=False,
        capabilities=("UnityPy",),
    ),
    Operation(
        name="verify_bundle",
        summary="Load a bundle in a real Unity runtime and report every asset it returns. "
        "The one offline check this pipeline does not also author: it is the engine's own "
        "loader. Needs an editor; proves construction, never acceptance.",
        parameters=_schema({"bundle": PATH_PARAM}),
        returns="VerifyReport: bundle, log, ok, assets[{key, type, name, detail}], problems[]",
        cost=MINUTES,
        writes=False,
        needs_config=True,
    ),
    Operation(
        name="acceptance_provider",
        summary="Generate the 7dtd-playtest scenario provider that loads every bundle member "
        "through the game's own DataLoader, inside a live client. One case per manifest "
        "entry, plus an absent stem that must stay null. Building it needs the .NET SDK and "
        "the harness assembly; running it belongs to hordeforge/7dtd-playtest.",
        parameters=_schema(
            {
                "harness_dll": {**PATH_PARAM, "description": "7dtd-playtest.dll; the provider "
                "is only rendered, not built, when this is omitted"},
                "install": {"type": "boolean", "description": "copy the built provider into "
                "the client's Mods folder"},
                "mods_dir": {**PATH_PARAM, "description": "override the client Mods folder"},
            }
        ),
        returns="{directory, assembly, suite, cases[{stem, kind}], written[], built, installed}",
        cost=FAST,
        writes=True,
        needs_config=True,
    ),
    Operation(
        name="stage",
        summary="Gate a bundle an editor elsewhere built and stage it into the modlet: the "
        "same revision, class-142, stem-collision and staging path as 'build', without a "
        "local Unity. Reports which gates could not run.",
        parameters=_schema(
            {
                "bundle": {**PATH_PARAM, "description": "the built .unity3d to gate and stage"},
                "manifest": {**PATH_PARAM, "description": "Unity's build manifest; "
                "defaults to BUNDLE.manifest beside the bundle"},
                "log": {**PATH_PARAM, "description": "the Unity log that built it; without "
                "one the disabled-module gate cannot run"},
            },
            required=["bundle"],
        ),
        returns="{bundle: path, skipped: [gates that did not run]}",
        cost=FAST,
        writes=True,
        needs_config=True,
    ),
    Operation(
        name="client_where",
        summary="Where the installed Proton client keeps its per-user Mods/ folder and its "
        "log, derived from the game directory. Nothing is read or written.",
        parameters=_schema({"game_dir": PATH_PARAM}),
        returns="{game_dir, compatdata, user_data, mods_dir, log_dir, launch[]}",
        cost=INSTANT,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="client_deploy",
        summary="Copy the deployable modlet (ModInfo.xml, Config/, Resources/, UIAtlases/, "
        "Prefabs/, UI/, root DLLs) into the client's per-user Mods/ folder for a fresh-client "
        "run, replacing a stale copy. Writes outside the modlet and outside the game install.",
        parameters=_schema(
            {
                "mods_dir": {**PATH_PARAM, "description": "defaults to the Proton per-user Mods/"},
                "mod_name": {"type": "string", "description": "folder name; defaults to ModInfo Name"},
                "replace": {"type": "boolean", "default": True},
            }
        ),
        returns="{destination, copied[]}",
        cost=FAST,
        writes=True,
        needs_config=True,
    ),
    Operation(
        name="client_launch",
        summary="Start a genuinely fresh client through Steam, optionally muted at the OS "
        "layer and stopped after run_seconds, then classify the log this launch wrote. "
        "Refuses while a client is running, because a reused client keeps the old bundle cached.",
        parameters=_schema(
            {
                "run_seconds": {"type": "integer", "description": "stop the client after this long"},
                "mute": {"type": "boolean", "default": False},
                "mod_name": {"type": "string", "description": "require 'Loaded Mod: NAME'"},
                "steam_bin": {"type": "string", "default": "steam"},
                "log_dir": PATH_PARAM,
            }
        ),
        returns="AcceptanceRun: log{found, missing_positive, problems, ok}, launched[], muted, ok",
        cost=MINUTES,
        writes=True,
        needs_config=False,
    ),
    Operation(
        name="client_log",
        summary="Find the newest client log (or read a given one) and classify it: the lines "
        "that prove the mod, its atlas and its localization loaded, and the lines that name "
        "each silent failure this pipeline knows.",
        parameters=_schema(
            {
                "path": PATH_PARAM,
                "log_dir": PATH_PARAM,
                "mod_name": {"type": "string"},
            }
        ),
        returns="LogReport: log, mod_name, found{}, missing_positive[], problems[], ok",
        cost=INSTANT,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="prompt",
        summary="Render a house-style image-generation prompt for one asset kind, "
        "with the key colour, the negative list, and the commands that consume "
        "the image the model returns.",
        parameters=_schema(
            {
                "kind": {
                    "type": "string",
                    # Derived from KINDS so the published schema cannot drift
                    # from what render() and `shamway prompt --list` accept.
                    "enum": sorted(KINDS),
                    "description": "item-icon, block-concept, material-albedo, "
                    "particle-card, or opacity-mask",
                },
                "subject": {
                    "type": "string",
                    "description": "the shapes, materials and components, in order of importance",
                },
                "role": {"type": "string", "description": "what it is for, in one clause"},
                "palette": {"type": "string", "description": "three to five named colours"},
                "key": {
                    "type": "string",
                    # "" keeps the kind's default; the same choices the CLI publishes.
                    "enum": ["", *sorted(KEYS)],
                    "description": "magenta, green, or black; defaults per kind",
                },
                "avoid": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "specific wrong answers the last candidate produced",
                },
                "stem": {"type": "string", "default": "myModThing"},
            },
            required=["kind", "subject"],
        ),
        returns="{kind, subject, key, key_hex, prompt, next: [commands], notes}",
        cost=INSTANT,
        writes=False,
        needs_config=False,
    ),
    Operation(
        name="init",
        summary="Scaffold the pipeline into an existing modlet, or adopt the Unity project "
        "the mod already has. Refuses to overwrite.",
        parameters=_schema(
            {
                "mod_root": PATH_PARAM,
                "unity_version": {"type": "string"},
                "game_dir": PATH_PARAM,
                "mod_name": {"type": "string"},
                "bundle_name": {"type": "string"},
                "changeset": {"type": "string"},
                "adopt_project": {
                    "type": "string",
                    "description": "existing Unity project to adopt instead of creating one; "
                    "must live below the mod root",
                },
                "source_root": {
                    "type": "string",
                    "description": "bundle-membership folder, relative to the Unity project",
                },
                "manifest_dir": {
                    "type": "string",
                    "description": "where the tracked .manifest is committed, relative to the mod",
                },
                "bundle_source": {
                    "type": "string",
                    # Derived from BUNDLE_SOURCES so the published schema cannot
                    # drift from what load_config and `init --bundle-source` accept.
                    "enum": sorted(BUNDLE_SOURCES),
                    "default": "unity",
                    "description": "where the bundle comes from: "
                    + ", ".join(f"{name} ({why})" for name, why in BUNDLE_SOURCES.items()),
                },
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
    return {
        "name": "7dtd-asset-pipeline",
        "version": __version__,
        "description": "Build and validate Unity asset bundles for 7 Days to Die mods.",
        "conventions": {
            "config": "Operations with needs_config resolve .shamway.toml upward "
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
        "prompt_kinds": _prompt_kinds(),
    }


def _generators() -> list[GeneratorInfo]:
    """The packaged asset generators, callable as `shamway generate NAME`."""
    return describe()


def _prompt_kinds() -> list[dict[str, str]]:
    """The house-style prompt shapes, rendered by the 'prompt' operation."""
    return kinds()


def _documentation() -> list[dict[str, str]]:
    """The packaged documentation, readable as `shamway docs TOPIC`."""
    return topics()


def get(name: str) -> Operation:
    try:
        return OPERATIONS[name]
    except KeyError:
        known = ", ".join(sorted(OPERATIONS))
        raise PipelineError(f"unknown operation {name!r}; expected one of: {known}") from None
