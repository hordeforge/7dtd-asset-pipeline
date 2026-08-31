"""Command-line interface."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

from . import atomic, audio_review
from . import video_review as video_review_mod
from .api import Pipeline, call_json
from .build import (
    expected_unity_version,
    reject_disabled_modules,
    run_build,
    stage_bundle,
    synthesized_caveats,
)
from .bundle_verify import verify_with_editor
from .bundle_writer import pack_directory
from .capabilities import capabilities
from .client import main as client_main
from .colour import DEFAULT_COLOUR_TOLERANCE, DEFAULT_TILE_RATIO, check_texture
from .config import BUNDLE_SOURCES, load_config, resolve_bundle_source
from .deep_inspect import deep_inspect
from .docs import read as read_doc
from .docs import topics as doc_topics
from .doctor import failed, run_doctor
from .errors import ConfigNotFoundError, PipelineError
from .game import game_unity_version, project_unity_version
from .generators import describe as describe_generators
from .generators import run as run_generator
from .icon_check import DEFAULT_ATLAS_ROOT, DEFAULT_CELL, check_icons
from .icon_render import (
    DEFAULT_ATLAS,
    DEFAULT_PADDING,
    DEFAULT_PITCH,
    DEFAULT_YAW,
    render_icon,
)
from .localization_check import check_localization
from .mesh_check import DEFAULT_MAX_EXTENT, check_mesh
from .operations import manifest
from .patch_check import check_patches
from .prompts import main as prompt_main
from .providers import resolve_provider
from .references import discover_references
from .scaffold import initialize
from .serve import serve
from .sound_check import DEFAULT_MAX_SECONDS, check_sound
from .status import collect_status
from .unity_release import DEFAULT_PLATFORM, fetch_release
from .unityfs import inspect_bundle
from .validation import validate_bundle, validate_mod


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shamway",
        description="Build and validate Unity asset bundles for 7 Days to Die mods.",
    )
    parser.add_argument("--config", type=Path, help="path to .shamway.toml")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="scaffold a pipeline into a modlet")
    init.add_argument("mod_root", type=Path)
    init.add_argument("--mod-name")
    init.add_argument("--bundle-name")
    init.add_argument("--unity-version", help="required when no game directory is supplied")
    init.add_argument(
        "--changeset",
        help="Unity changeset to pin in ProjectVersion.txt; resolved from Unity's "
        "release service when omitted and reachable",
    )
    init.add_argument("--game-dir", type=Path, help="discover Unity version from an installed game")
    init.add_argument(
        "--adopt",
        type=Path,
        metavar="UNITY_PROJECT",
        help="adopt a Unity project the mod already has instead of creating one; "
        "installs only the pipeline-owned editor scripts and moves nothing",
    )
    init.add_argument(
        "--source-root",
        help="bundle-membership folder relative to the Unity project "
        "(default Assets/ModAssets/Bundle)",
    )
    init.add_argument(
        "--bundle-source",
        choices=list(BUNDLE_SOURCES),
        default=None,
        help="where the bundle comes from (default synthesized, or unity with --adopt): "
        "synthesized (this tool writes it, no editor), none (the mod ships no bundle), "
        "external (built elsewhere, staged here with 'shamway stage'), or unity (opt in "
        "to a local editor building it)",
    )
    init.add_argument(
        "--manifest-dir",
        help="where the tracked .manifest is committed, relative to the mod "
        "(default tools/shamway/manifests)",
    )

    doctor = commands.add_parser("doctor", help="check configuration and required tooling")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable checks")
    build = commands.add_parser("build", help="build, gate, and stage the configured bundle")
    build.add_argument("--probe", action="store_true", help="build a throwaway cube bundle only")
    pack = commands.add_parser(
        "pack",
        help="write a .unity3d from textures, clips, text, meshes, glTF skins/hierarchies and .vfx,"
        " with no Unity",
    )
    pack.add_argument("source", type=Path, help="directory whose contents become the bundle")
    pack.add_argument("output", type=Path, help="the .unity3d to write")
    pack.add_argument(
        "--unity-version",
        help="the revision to stamp; defaults to the installed game's via --game-dir",
    )
    pack.add_argument("--game-dir", type=Path, help="read the revision from an installed game")
    pack.add_argument(
        "--manifest",
        type=Path,
        help="also write the membership manifest here (default: OUTPUT.manifest)",
    )
    pack.add_argument(
        "--compress-textures",
        action="store_true",
        help="block-compress textures to DXT1/DXT5 (8x/4x smaller, lossy); "
        "both sides must be a multiple of 4",
    )
    pack.add_argument(
        "--compress-audio",
        action="store_true",
        help="encode clips to Vorbis in an FSB5 bank (~40x smaller, lossy); "
        "needs FFmpeg and the 'fsb5' capability",
    )

    verify = commands.add_parser(
        "verify-bundle",
        help="load a bundle in a real Unity runtime and report every asset it returns",
    )
    verify.add_argument(
        "--draw",
        action="store_true",
        help="also photograph each prefab and report the fraction of the frame it "
        "filled: the only offline answer to whether it rasterizes. Needs a real "
        "graphics device — run under 'xvfb-run -a' on a headless host",
    )
    verify.add_argument("bundle", type=Path, nargs="?", help="default: the mod's staged bundle")
    verify.add_argument("--json", action="store_true")

    stage = commands.add_parser(
        "stage", help="gate and stage a bundle an editor elsewhere built (no local Unity)"
    )
    stage.add_argument("bundle", type=Path, help="the built .unity3d to gate and stage")
    stage.add_argument(
        "--manifest", type=Path, help="Unity's build manifest; default: BUNDLE.manifest beside it"
    )
    stage.add_argument(
        "--log",
        type=Path,
        help="the Unity log that built it; without one the disabled-module gate cannot run",
    )
    validate = commands.add_parser(
        "validate", help="validate the staged bundle and all XML references"
    )
    validate.add_argument("--bundle", type=Path, help="inspect one bundle instead of the mod")
    inspect = commands.add_parser("inspect", help="print UnityFS metadata for one bundle")
    inspect.add_argument("bundle", type=Path)
    inspect.add_argument("--json", action="store_true")
    inspect.add_argument(
        "--deep",
        action="store_true",
        help="list every serialized object and per-prefab components (needs UnityPy)",
    )
    release = commands.add_parser(
        "unity-release", help="resolve the official Unity editor download for a revision"
    )
    release.add_argument(
        "--version", help="Unity revision; defaults to the configured project's ProjectVersion.txt"
    )
    release.add_argument(
        "--platform", default=DEFAULT_PLATFORM, help="editor host platform (default LINUX)"
    )
    release.add_argument("--json", action="store_true")

    status = commands.add_parser(
        "status", help="report the mod's whole pipeline state without failing"
    )
    status.add_argument("--json", action="store_true")

    mesh = commands.add_parser(
        "check-mesh", help="check an authored mesh before Unity import (trimesh, glTF validator)"
    )
    mesh.add_argument("mesh", type=Path)
    mesh.add_argument(
        "--max-extent",
        type=float,
        default=DEFAULT_MAX_EXTENT,
        help="largest allowed size in metres",
    )
    mesh.add_argument("--strict", action="store_true", help="treat glTF warnings as failures")
    mesh.add_argument("--json", action="store_true")

    texture = commands.add_parser(
        "check-texture",
        help="check a generated texture's colour space and tiling",
    )
    texture.add_argument("texture", type=Path)
    texture.add_argument(
        "--matches",
        metavar="R,G,B",
        help="the material.color triple this texture replaces, as written in the asset "
        "builder (e.g. 0.46,0.39,0.15). Compared in sRGB, because that is the space a "
        "material colour is already in",
    )
    texture.add_argument(
        "--tolerance",
        type=float,
        default=DEFAULT_COLOUR_TOLERANCE,
        help="largest allowed per-channel drift from --matches",
    )
    texture.add_argument(
        "--tileable", action="store_true", help="assert the image still wraps at its edges"
    )
    texture.add_argument("--max-tile-ratio", type=float, default=DEFAULT_TILE_RATIO)
    texture.add_argument("--json", action="store_true")

    sound = commands.add_parser(
        "check-sound", help="measure a WAV clip and reject unshippable formats"
    )
    sound.add_argument("clip", type=Path)
    sound.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    sound.add_argument(
        "--allow-stereo",
        dest="require_mono",
        action="store_false",
        help="permit a multi-channel clip (a deliberate 2D UI or music cue)",
    )
    sound.add_argument("--json", action="store_true")

    review = commands.add_parser(
        "review-audio",
        help="advisory semantic review of a clip by a configured audio model "
        "(explicit network consent required)",
    )
    review.add_argument("clip", type=Path)
    review.add_argument(
        "--intent",
        type=Path,
        help="intent JSON file, committed beside the source; requires purpose and "
        "playback (see docs/authoring/audio.md)",
    )
    review.add_argument("--intent-text", help="inline intent JSON instead of --intent")
    review.add_argument(
        "--provider",
        default=audio_review.DEFAULT_PROVIDER,
        help=f"audio-review provider (default {audio_review.DEFAULT_PROVIDER})",
    )
    review.add_argument("--model", help="provider model identifier; default per provider")
    review.add_argument(
        "--output",
        type=Path,
        help="write the hash-addressed evidence document here; never overwrites without --force",
    )
    review.add_argument(
        "--allow-network",
        action="store_true",
        help="consent to uploading the audio to the provider; without it the command "
        "refuses before touching credentials",
    )
    review.add_argument(
        "--keep-raw-response",
        action="store_true",
        help="preserve the redacted raw provider response in the evidence document",
    )
    review.add_argument(
        "--force", action="store_true", help="overwrite an existing evidence document"
    )
    review.add_argument(
        "--timeout",
        type=float,
        default=audio_review.DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds to wait for the provider (default {audio_review.DEFAULT_TIMEOUT_SECONDS:g})",
    )
    review.add_argument("--json", action="store_true")

    video_review = commands.add_parser(
        "review-video",
        help="advisory semantic review of an adopted clip by a configured vision "
        "model via the deadeye gateway (explicit network consent required)",
    )
    video_review.add_argument("stem", help="the manifest stem of the asset the clip shows")
    video_review.add_argument(
        "--clip",
        type=Path,
        required=True,
        help="the adopted clip directory (see `shamway client capture --clip`)",
    )
    video_review.add_argument(
        "--intent",
        type=Path,
        help="intent JSON file, committed beside the source; requires purpose "
        "(see docs/authoring/video.md)",
    )
    video_review.add_argument("--intent-text", help="inline intent JSON instead of --intent")
    video_review.add_argument(
        "--provider",
        default=video_review_mod.DEFAULT_PROVIDER,
        help=f"vision-review provider (default {video_review_mod.DEFAULT_PROVIDER})",
    )
    video_review.add_argument("--model", help="provider model identifier; default per provider")
    video_review.add_argument(
        "--output",
        type=Path,
        help="write the hash-addressed evidence document here; never overwrites without --force",
    )
    video_review.add_argument(
        "--allow-network",
        action="store_true",
        help="consent to uploading the clip to the provider; without it the command "
        "refuses before touching anything",
    )
    video_review.add_argument(
        "--keep-raw-response",
        action="store_true",
        help="preserve the redacted raw provider response in the evidence document",
    )
    video_review.add_argument(
        "--force", action="store_true", help="overwrite an existing evidence document"
    )
    video_review.add_argument(
        "--timeout",
        type=float,
        default=video_review_mod.DEFAULT_TIMEOUT_SECONDS,
        help="seconds to wait for the gateway (default "
        f"{video_review_mod.DEFAULT_TIMEOUT_SECONDS:g})",
    )
    video_review.add_argument("--json", action="store_true")

    icons = commands.add_parser(
        "check-icons", help="check UIAtlases PNGs and every CustomIcon key under Config/"
    )
    icons.add_argument("--atlas-root", default=DEFAULT_ATLAS_ROOT)
    icons.add_argument(
        "--cell", type=int, default=DEFAULT_CELL, help="expected atlas cell size in pixels"
    )
    icons.add_argument("--json", action="store_true")

    loc = commands.add_parser(
        "check-localization",
        help="reconcile every Config/ localization key with the mod's Localization.csv "
        "(and the game's, so vanilla keys are allowed)",
    )
    loc.add_argument(
        "--allow-vanilla-keys",
        action="store_true",
        default=True,
        help="allow keys resolved by the game's own Localization.csv (default)",
    )
    loc.add_argument("--no-vanilla-keys", action="store_true", help="fail vanilla keys too")
    loc.add_argument("--json", action="store_true")

    patches = commands.add_parser(
        "check-patches",
        help="replay Config/ patch XPaths against the game's stock configs and fail "
        "the ones that select zero nodes (the engine silently no-ops those)",
    )
    patches.add_argument("--json", action="store_true")

    render = commands.add_parser(
        "render-icon", help="render a bundle prefab into an atlas icon with the editor"
    )
    render.add_argument("prefab", help="bundle stem, or a project-relative Assets/... path")
    render.add_argument("--output", type=Path, help="default: UIAtlases/<atlas>/<stem>.png")
    render.add_argument("--size", type=int, default=DEFAULT_CELL)
    render.add_argument("--atlas", default=DEFAULT_ATLAS)
    render.add_argument("--yaw", type=float, default=DEFAULT_YAW, help="camera yaw in degrees")
    render.add_argument(
        "--pitch", type=float, default=DEFAULT_PITCH, help="camera pitch in degrees"
    )
    render.add_argument(
        "--padding", type=float, default=DEFAULT_PADDING, help="framing headroom factor"
    )
    render.add_argument("--json", action="store_true")

    capability = commands.add_parser(
        "capabilities", help="list optional capabilities, what they unlock, and how to install them"
    )
    capability.add_argument("--json", action="store_true")
    capability.add_argument("--versions", action="store_true", help="also probe installed versions")
    capability.add_argument("--missing", action="store_true", help="list only unavailable ones")

    generate = commands.add_parser(
        "generate",
        help="run a packaged asset generator (no checkout of this repo needed)",
    )
    generate.add_argument(
        "generator", nargs="?", help="sound, audio, cutout, icon, texture-maps, or mesh"
    )
    generate.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="passed through unchanged; add --help to see a generator's own options",
    )
    generate.add_argument("--list", action="store_true", help="list the generators and exit")

    prompt_parser = commands.add_parser(
        "prompt",
        help="render a house-style image-generation prompt and the lane that follows it",
        add_help=False,
    )
    prompt_parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help='KIND --subject "..."; `shamway prompt --list` names the kinds',
    )

    script_parser = commands.add_parser(
        "script",
        help="run a packaged host script: install-tools, install-unity-editor, "
        "compile-editor-scripts, playtest-acceptance, playtest-synthesized, playtest-capture",
    )
    script_parser.add_argument(
        "arguments", nargs=argparse.REMAINDER, help="`shamway script --list` names them"
    )

    client_parser = commands.add_parser(
        "client",
        help="fresh-client acceptance: where, deploy, launch, log, capture, mute, unmute,"
        " disable-discord",
        add_help=False,
    )
    client_parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="passed through; `shamway client --help` lists them",
    )

    # Registered for `--help` only; `main` intercepts it before parsing, the
    # same way it does prompt, script and client. Without this row the command
    # exists, works, and is documented everywhere except where someone looks.
    acceptance_parser = commands.add_parser(
        "acceptance-provider",
        help="generate the 7dtd-playtest provider that loads every bundle member in a live client",
        add_help=False,
    )
    acceptance_parser.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="passed through; `shamway acceptance-provider --help` lists them",
    )

    documentation = commands.add_parser(
        "docs", help="print this pipeline's documentation, from the installed package"
    )
    documentation.add_argument("topic", nargs="?", help="omit to list the topics")
    documentation.add_argument("--json", action="store_true", help="machine-readable topic list")

    schema = commands.add_parser("schema", help="print the machine-readable operation contract")
    schema.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)

    call = commands.add_parser("call", help="run one operation by name with JSON parameters")
    call.add_argument("operation")
    call.add_argument("--params", default="{}", help="JSON object of parameters")

    server = commands.add_parser(
        "serve", help="line-delimited JSON requests on stdin, responses on stdout"
    )
    server.add_argument(
        "--allow-writes", action="store_true", help="permit operations that write files"
    )

    commands.add_parser("refs", help="list bundle references discovered recursively in Config/")
    check_log = commands.add_parser("check-log", help="fail on Unity disabled-module warnings")
    check_log.add_argument("log", type=Path)
    return parser


def _init_next_step(bundle_source: str) -> str:
    """What the person who just scaffolded should do next, per bundle source."""
    if bundle_source == "none":
        return "Next: run shamway doctor, then shamway validate. No Unity editor is needed."
    if bundle_source == "synthesized":
        return (
            "Next: put .png, .wav, .glb/.obj and .txt/.json/.csv files in assets-src/bundle/, "
            "then run "
            "shamway build. No editor is involved, so a fresh client is the acceptance: "
            "shamway client deploy . && shamway client launch"
        )
    if bundle_source == "external":
        return (
            "Next: set SEVEN_DAYS_TO_DIE_DIR, then run shamway doctor. Build the bundle where "
            "an editor lives and bring it back with: shamway stage BUNDLE --manifest M --log L"
        )
    return "Next: set SEVEN_DAYS_TO_DIE_DIR and UNITY_EDITOR, then run shamway doctor"


def _print_pairs(data: dict[str, object]) -> None:
    for key, value in data.items():
        print(f"{key}: {value}")


def _resolve_version(args: argparse.Namespace, demand: str) -> str:
    """The revision a bundle must carry: detected from the game, or named."""
    if args.game_dir:
        version, source = game_unity_version(args.game_dir.resolve())
        print(f"Detected Unity {version} from {source}")
        return version
    if args.unity_version:
        named: str = args.unity_version
        return named
    raise PipelineError(demand)


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        # Resolved here as well as in `initialize`, because everything this
        # branch prints and demands (a revision, the next step) depends on it.
        bundle_source = resolve_bundle_source(args.bundle_source, args.adopt is not None)
        if bundle_source == "none":
            # No bundle means no editor, so no revision has to be resolved and
            # neither a game install nor a network is needed to scaffold.
            version = ""
        else:
            version = _resolve_version(
                args,
                "init needs --game-dir or --unity-version, or --bundle-source none for a mod "
                "that ships no bundle",
            )
        changeset = args.changeset
        if not changeset and version:
            # Best effort: pinning the revision is valuable, but not worth
            # failing a scaffold over an unreachable network.
            try:
                changeset = fetch_release(version).changeset
                print(f"Resolved Unity {version} changeset {changeset}")
            except PipelineError:
                print("Could not resolve the changeset; Unity will add it on first open")
        created = initialize(
            args.mod_root,
            args.mod_name,
            args.bundle_name,
            version,
            changeset,
            args.adopt,
            args.source_root,
            args.manifest_dir,
            bundle_source,
        )
        for path in created:
            print(f"created {path}")
        if args.adopt:
            print(
                "Adopted an existing Unity project. Mark the mod's own asset generators "
                "with [ShamwayPreBuild] so 'shamway build' runs them before collecting."
            )
        print(_init_next_step(bundle_source))
        return 0

    if args.command == "inspect":
        if args.deep:
            deep = deep_inspect(args.bundle)
            if args.json:
                print(json.dumps(deep.as_dict(), indent=2, sort_keys=True))
            else:
                print(f"path: {deep.path}")
                print(f"objects: {deep.object_count}")
                print("types: " + ", ".join(f"{k}={v}" for k, v in deep.type_counts.items()))
                for entry in deep.entries:
                    components = ", ".join(f"{k}={v}" for k, v in entry.components.items())
                    detail = f" [{entry.object_count} objects: {components}]" if components else ""
                    print(f"  {entry.asset_stem} ({entry.type}) name={entry.object_name!r}{detail}")
            return 0
        info = inspect_bundle(args.bundle)
        data = {
            "path": str(info.path),
            "unity_version": info.unity_version,
            "archive_format": info.archive_format,
            "class_ids": list(info.class_ids),
            "has_assetbundle_object": info.has_assetbundle_object,
        }
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            _print_pairs(data)
        return 0
    if args.command == "check-mesh":
        mesh = check_mesh(args.mesh, args.max_extent, args.strict)
        if args.json:
            print(json.dumps(mesh.as_dict(), indent=2, sort_keys=True))
        else:
            data = mesh.as_dict()
            for key in (
                "path",
                "extents",
                "geometry_count",
                "vertex_count",
                "face_count",
                "watertight",
                "gltf_errors",
                "gltf_warnings",
            ):
                if data[key] is not None:
                    print(f"{key}: {data[key]}")
            for note in mesh.skipped:
                print(f"skipped: {note}")
            for problem in mesh.problems:
                print(f"problem: {problem}")
            print("OK" if mesh.ok else "FAILED")
        return 0 if mesh.ok else 1
    if args.command == "check-texture":
        wanted: tuple[float, float, float] | None = None
        if args.matches:
            parts = [p for p in args.matches.replace(" ", "").split(",") if p]
            if len(parts) != 3:
                raise PipelineError(
                    f"--matches needs three comma-separated channels, got {args.matches!r}"
                )
            try:
                red, green, blue = (float(p) for p in parts)
            except ValueError as exc:
                raise PipelineError(f"--matches is not numeric: {args.matches!r}") from exc
            wanted = (red, green, blue)
        texture_report = check_texture(
            args.texture, wanted, args.tolerance, args.tileable, args.max_tile_ratio
        )
        if args.json:
            print(json.dumps(texture_report.as_dict(), indent=2, sort_keys=True))
        else:
            data = texture_report.as_dict()
            for key in (
                "path",
                "size",
                "mean_bytes",
                "mean_srgb",
                "mean_linear",
                "expected_srgb",
                "colour_drift",
                "tile_ratio",
            ):
                if data[key] is not None:
                    print(f"{key}: {data[key]}")
            for note in texture_report.notes:
                print(f"note: {note}")
            for problem in texture_report.problems:
                print(f"problem: {problem}")
            print("OK" if texture_report.ok else "FAILED")
        return 0 if texture_report.ok else 1
    if args.command == "check-sound":
        sound = check_sound(args.clip, args.max_seconds, args.require_mono)
        if args.json:
            print(json.dumps(sound.as_dict(), indent=2, sort_keys=True))
        else:
            data = sound.as_dict()
            for key in (
                "path",
                "channels",
                "sample_rate",
                "duration_seconds",
                "peak",
                "peak_dbfs",
                "rms",
                "dc_offset",
                "clipped_samples",
                "leading_silence_seconds",
                "trailing_silence_seconds",
            ):
                print(f"{key}: {data[key]}")
            for note in sound.notes:
                print(f"note: {note}")
            for problem in sound.problems:
                print(f"problem: {problem}")
            print("OK" if sound.ok else "FAILED")
        return 0 if sound.ok else 1
    if args.command == "review-audio":
        report = audio_review.run_review(
            args.clip,
            provider=resolve_provider(args.provider),
            intent_path=args.intent,
            intent_text=args.intent_text,
            model=args.model,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout,
            keep_raw_response=args.keep_raw_response,
            output=args.output,
            force=args.force,
            notify=print,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            verdict = report["review"]
            print(f"summary: {verdict['summary']}")
            for strength in verdict["strengths"]:
                print(f"strength: {strength}")
            for issue in verdict["issues"]:
                moment = issue.get("at_seconds")
                at = f" [{moment[0]:g}-{moment[1]:g} s]" if moment else ""
                print(f"issue: {issue['description']}{at}")
            for change in verdict["recommended_changes"]:
                print(f"change: {change}")
            for key, value in sorted(verdict["rubric_scores"].items()):
                score = "unjudgeable" if value is None else f"{value:g}"
                print(f"score: {key} = {score}")
            print(f"confidence: {verdict['confidence']:g}")
            for limitation in verdict["limitations"]:
                print(f"limitation: {limitation}")
            usage = report["usage"]
            if not usage.get("reported_by_provider", False):
                print("usage: unavailable (the provider reported none; nothing estimated)")
            if report["evidence"]["path"]:
                print(f"evidence: {report['evidence']['path']}")
            print(f"note: {report['note']}")
        return 0
    if args.command == "pack":
        version = _resolve_version(
            args,
            "pack needs --game-dir or --unity-version: a bundle carries the revision "
            "it claims to be for, and the installed game is what has to load it",
        )
        bundle, manifest_text = pack_directory(
            args.source,
            args.output.name,
            version,
            compress_textures=args.compress_textures,
            compress_audio=args.compress_audio,
        )
        # Atomic writes: a pack interrupted midway must not leave a truncated
        # .unity3d at the path a later deploy would ship.
        atomic.write(args.output, bundle)
        # Not `manifest`: that name belongs to the operation registry's manifest()
        # at module level, and a local of the same name shadows it for the whole
        # of run() — which broke `shamway schema` in a way no unit test saw.
        manifest_path = args.manifest or Path(f"{args.output}.manifest")
        atomic.write(manifest_path, manifest_text)
        print(f"OK: synthesized {args.output} ({len(bundle)} bytes) and {manifest_path}")
        for caveat in synthesized_caveats():
            print(f"note: {caveat}")
        return 0
    if args.command == "check-log":
        reject_disabled_modules(args.log)
        print(f"OK: no disabled-module warnings in {args.log}")
        return 0
    if args.command == "generate":
        if args.list or not args.generator:
            for generator_entry in describe_generators():
                needs = (
                    ", ".join(generator_entry["capabilities"])
                    or "nothing beyond the standard library"
                )
                print(f"{generator_entry['name']:14} {generator_entry['summary']}")
                print(f"{'':14} needs: {needs}")
            print()
            print("Run one with: shamway generate NAME [ARGS...]  (--help works per generator)")
            return 0
        return run_generator(args.generator, args.arguments)
    if args.command == "prompt":
        return prompt_main(args.arguments or ["--list"])
    if args.command == "client":
        return client_main(args.arguments or ["--help"])
    if args.command == "docs":
        if not args.topic:
            entries = doc_topics()
            if args.json:
                print(json.dumps(entries, indent=2, sort_keys=True))
            else:
                for doc_entry in entries:
                    mark = " " if doc_entry["available"] == "true" else "!"
                    print(f"{mark} {doc_entry['topic']:20} {doc_entry['summary']}")
                print()
                print("Read one with: shamway docs TOPIC")
            return 0
        print(read_doc(args.topic), end="")
        return 0
    if args.command == "schema":
        print(json.dumps(manifest(), indent=2, sort_keys=True))
        return 0

    if args.command in ("call", "serve"):

        def resolve() -> Pipeline | None:
            # Only a *missing* configuration degrades to None, so the stateless
            # operations keep working with no modlet anywhere. A configuration
            # that exists but cannot be read propagates its own error: catching
            # every PipelineError here replaced "cannot read .shamway.toml:
            # invalid TOML at line N" with "needs a mod configuration", which
            # is the opposite of what a caller with a broken file needs.
            try:
                return Pipeline(load_config(args.config))
            except ConfigNotFoundError:
                return None

        if args.command == "serve":
            return serve(resolve, args.allow_writes)
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"--params is not valid JSON: {exc}") from exc
        if not isinstance(params, dict):
            raise PipelineError("--params must be a JSON object")
        print(json.dumps(call_json(resolve(), args.operation, params), indent=2, sort_keys=True))
        return 0

    if args.command == "capabilities":
        found = capabilities(args.versions)
        if args.missing:
            found = [item for item in found if not item.available]
        if args.json:
            print(json.dumps([item.as_dict() for item in found], indent=2, sort_keys=True))
        else:
            for item in found:
                mark = "OK  " if item.available else "MISS"
                detail = item.version or item.path or ""
                print(f"{mark} {item.name:15} {item.purpose}")
                print(f"     unlocks: {', '.join(item.unlocks)}")
                if item.available and detail:
                    print(f"     found:   {detail}")
                if not item.available:
                    print(f"     install: {item.install}")
        return 0
    if args.command == "unity-release":
        # An explicit --version answers without a modlet; resolving from the
        # project needs load_config, so it happens here, before the shared
        # load below would demand one.
        version = args.version or project_unity_version(load_config(args.config).unity_project)
        data = fetch_release(version, args.platform).as_dict()
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            _print_pairs(data)
        return 0
    if args.command == "validate" and args.bundle and args.config is None:
        info = validate_bundle(args.bundle)
        print(f"OK: {info.path} Unity {info.unity_version}; class-142 present")
        return 0

    config = load_config(args.config)
    if args.command == "review-video":
        report = video_review_mod.run_review(
            args.stem,
            clip=args.clip,
            provider=args.provider,
            intent_path=args.intent,
            intent_text=args.intent_text,
            model=args.model,
            config=config,
            allow_network=args.allow_network,
            timeout_seconds=args.timeout,
            keep_raw_response=args.keep_raw_response,
            output=args.output,
            force=args.force,
            notify=print,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            verdict = report["review"]
            print(f"summary: {verdict['summary']}")
            for strength in verdict["strengths"]:
                print(f"strength: {strength}")
            for issue in verdict["issues"]:
                moment = issue.get("at_seconds")
                at = f" [{moment[0]:g}-{moment[1]:g} s]" if moment else ""
                print(f"issue: {issue['description']}{at}")
            for change in verdict["recommended_changes"]:
                print(f"change: {change}")
            for key, value in sorted(verdict["rubric_scores"].items()):
                score = "unjudgeable" if value is None else f"{value:g}"
                print(f"score: {key} = {score}")
            print(f"confidence: {verdict['confidence']:g}")
            for limitation in verdict["limitations"]:
                print(f"limitation: {limitation}")
            if report["evidence"]["path"]:
                print(f"evidence: {report['evidence']['path']}")
            print(f"note: {report['note']}")
        return 0
    if args.command == "doctor":
        checks = run_doctor(config)
        if args.json:
            print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))
        else:
            for check in checks:
                print(f"{check.status:4} {check.name}: {check.detail}")
        # Every check reports its own verdict so the JSON stays complete; the
        # exit code is what makes a failure fatal to a script or CI job.
        return 1 if failed(checks) else 0
    if args.command == "build":
        output = run_build(config, args.probe)
        synthesized = config.bundle_source == "synthesized"
        verb = "synthesized" if synthesized else "built"
        print(f"OK: {verb} {output}")
        if synthesized:
            # Never "built": the word carries a claim about who serialized it.
            for caveat in synthesized_caveats():
                print(f"note: {caveat}")
        if not args.probe:
            print("Offline gates passed. A fresh-client load is still required for acceptance.")
        return 0
    if args.command == "verify-bundle":
        verified = verify_with_editor(
            args.bundle or config.bundle_output,
            config.unity_editor,
            expected_unity_version(config),
            config.build_dir / "verify",
            draw=args.draw,
        )
        if args.json:
            print(json.dumps(verified.as_dict(), indent=2, sort_keys=True))
        else:
            for asset in verified.assets:
                detail = f"  [{asset.detail}]" if asset.detail else ""
                print(f"{asset.key}: {asset.type} named {asset.name!r}{detail}")
            for problem in verified.problems:
                print(f"problem: {problem}")
            print("OK" if verified.ok else "FAILED")
            if verified.ok:
                print(
                    "A runtime of this revision loaded every asset. That is construction, "
                    "not acceptance: a fresh client and a human look still decide."
                )
        return 0 if verified.ok else 1
    if args.command == "stage":
        output, skipped = stage_bundle(config, args.bundle, args.manifest, args.log)
        print(f"OK: {output}")
        for gate in skipped:
            print(f"not run: {gate}")
        print("Offline gates passed. A fresh-client load is still required for acceptance.")
        return 0
    if args.command == "validate":
        expected = game_unity_version(config.game_dir)[0] if config.game_dir else None
        if args.bundle:
            info = validate_bundle(args.bundle, expected)
            print(f"OK: {info.path} Unity {info.unity_version}; class-142 present")
        else:
            validation = validate_mod(config)
            print(*validation.messages, sep="\n")
            print(
                f"OK: bundle and {validation.reference_count} reference(s) validated"
                " (XML and code_references)"
            )
        return 0
    if args.command == "status":
        status_report = collect_status(config)
        if args.json:
            print(json.dumps(status_report.as_dict(), indent=2, sort_keys=True))
        else:
            data = status_report.as_dict()
            for key in (
                "mod_name",
                "bundle_source",
                "bundle_path",
                "bundle_present",
                "bundle_unity_version",
                "game_unity_version",
                "version_matches_game",
                "bundle_has_assetbundle_object",
                "asset_count",
                "reference_count",
                "valid",
            ):
                print(f"{key}: {data[key]}")
            for problem in status_report.problems:
                print(f"problem: {problem}")
        return 0 if status_report.valid else 1
    if args.command == "check-icons":
        icons = check_icons(config.mod_root, config.config_dir, args.atlas_root, args.cell)
        if args.json:
            print(json.dumps(icons.as_dict(), indent=2, sort_keys=True))
        else:
            for icon in icons.icons:
                coverage = (
                    "" if icon.alpha_coverage is None else f" {icon.alpha_coverage:.0%} opaque"
                )
                print(
                    f"{icon.atlas}/{icon.stem}: {icon.width}x{icon.height}"
                    f" {icon.colour_type}{coverage}"
                )
            print(f"resolved: {len(icons.resolved)}  external: {len(icons.external)}")
            for note in icons.notes:
                print(f"note: {note}")
            for problem in icons.problems:
                print(f"problem: {problem}")
            print("OK" if icons.ok else "FAILED")
        return 0 if icons.ok else 1
    if args.command == "check-localization":
        loc_report = check_localization(
            config.mod_root,
            config.config_dir,
            config.game_dir,
            not args.no_vanilla_keys,
        )
        if args.json:
            print(json.dumps(loc_report.as_dict(), indent=2, sort_keys=True))
        else:
            print(
                f"referenced: {len(loc_report.referenced)}  resolved: {len(loc_report.resolved)}"
                f"  vanilla: {len(loc_report.vanilla)}  missing: {len(loc_report.missing)}"
            )
            for note in loc_report.notes:
                print(f"note: {note}")
            for problem in loc_report.problems:
                print(f"problem: {problem}")
            print("OK" if loc_report.ok else "FAILED")
        return 0 if loc_report.ok else 1
    if args.command == "check-patches":
        patch_report = check_patches(config.mod_root, config.config_dir, config.game_dir)
        if args.json:
            print(json.dumps(patch_report.as_dict(), indent=2, sort_keys=True))
        else:
            print(f"checked: {len(patch_report.checked)}  resolved: {len(patch_report.resolved)}")
            for note in patch_report.notes:
                print(f"note: {note}")
            for problem in patch_report.problems:
                print(f"problem: {problem}")
            print("OK" if patch_report.ok else "FAILED")
        return 0 if patch_report.ok else 1
    if args.command == "render-icon":
        result = render_icon(
            config,
            args.prefab,
            args.output,
            args.size,
            args.atlas,
            args.yaw,
            args.pitch,
            args.padding,
        )
        if args.json:
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        else:
            print(
                f"OK: {result.output} ({result.size}px from {result.rendered_pixels}px, "
                f"{result.alpha_coverage:.0%} opaque)"
            )
            print("An icon is accepted in the inventory, not in a file browser.")
        return 0
    if args.command == "refs":
        for reference in discover_references(config.config_dir):
            print(f"{reference.source.relative_to(config.mod_root)}: {reference.uri}")
        return 0
    raise PipelineError(f"unknown command {args.command}")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # These are passthroughs with their own argument handling, so their
    # `--help` must reach them rather than be claimed (and rejected) by this
    # parser. Each entry: command -> (module, argv used when none is given).
    passthrough = {
        "script": ("scripts", []),
        "prompt": ("prompts", ["--list"]),
        "client": ("client", ["--help"]),
        "acceptance-provider": ("acceptance", []),
    }
    head = arguments[:1]
    if head and head[0] in passthrough:
        module = importlib.import_module(f".{passthrough[head[0]][0]}", __package__)
        # importlib's attribute access is Any; pin the passthroughs' contract.
        entrypoint: Callable[[list[str]], int] = module.main
        try:
            return entrypoint(arguments[1:] or passthrough[head[0]][1])
        except PipelineError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    try:
        return run(_parser().parse_args(arguments))
    except (PipelineError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
