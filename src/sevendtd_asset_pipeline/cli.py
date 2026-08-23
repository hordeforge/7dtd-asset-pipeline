"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import Pipeline, call_json
from .build import reject_disabled_modules, run_build
from .capabilities import capabilities
from .config import load_config
from .deep_inspect import deep_inspect
from .doctor import failed, run_doctor
from .docs import read as read_doc, topics as doc_topics
from .errors import PipelineError
from .generators import describe as describe_generators, run as run_generator
from .game import game_unity_version, project_unity_version
from .icon_check import check_icons
from .icon_render import render_icon
from .mesh_check import check_mesh
from .references import discover_references
from .operations import manifest
from .scaffold import initialize
from .serve import serve
from .sound_check import check_sound
from .status import collect_status
from .unity_release import fetch_release
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
        "--manifest-dir",
        help="where the tracked .manifest is committed, relative to the mod "
        "(default tools/shamway/manifests)",
    )

    doctor = commands.add_parser("doctor", help="check configuration and required tooling")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable checks")
    build = commands.add_parser("build", help="build, gate, and stage the configured bundle")
    build.add_argument("--probe", action="store_true", help="build a throwaway cube bundle only")
    validate = commands.add_parser("validate", help="validate the staged bundle and all XML references")
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
    release.add_argument("--platform", default="LINUX", help="editor host platform (default LINUX)")
    release.add_argument("--json", action="store_true")

    status = commands.add_parser(
        "status", help="report the mod's whole pipeline state without failing"
    )
    status.add_argument("--json", action="store_true")

    mesh = commands.add_parser(
        "check-mesh", help="check an authored mesh before Unity import (trimesh, glTF validator)"
    )
    mesh.add_argument("mesh", type=Path)
    mesh.add_argument("--max-extent", type=float, default=16.0, help="largest allowed size in metres")
    mesh.add_argument("--strict", action="store_true", help="treat glTF warnings as failures")
    mesh.add_argument("--json", action="store_true")

    sound = commands.add_parser(
        "check-sound", help="measure a WAV clip and reject unshippable formats"
    )
    sound.add_argument("clip", type=Path)
    sound.add_argument("--max-seconds", type=float, default=30.0)
    sound.add_argument(
        "--allow-stereo",
        dest="require_mono",
        action="store_false",
        help="permit a multi-channel clip (a deliberate 2D UI or music cue)",
    )
    sound.add_argument("--json", action="store_true")

    icons = commands.add_parser(
        "check-icons", help="check UIAtlases PNGs and every CustomIcon key under Config/"
    )
    icons.add_argument("--atlas-root", default="UIAtlases")
    icons.add_argument("--cell", type=int, default=160, help="expected atlas cell size in pixels")
    icons.add_argument("--json", action="store_true")

    render = commands.add_parser(
        "render-icon", help="render a bundle prefab into an atlas icon with the editor"
    )
    render.add_argument("prefab", help="bundle stem, or a project-relative Assets/... path")
    render.add_argument("--output", type=Path, help="default: UIAtlases/<atlas>/<stem>.png")
    render.add_argument("--size", type=int, default=160)
    render.add_argument("--atlas", default="ItemIconAtlas")
    render.add_argument("--yaw", type=float, default=208.0, help="camera yaw in degrees")
    render.add_argument("--pitch", type=float, default=8.0, help="camera pitch in degrees")
    render.add_argument("--padding", type=float, default=1.22, help="framing headroom factor")
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

    script_parser = commands.add_parser(
        "script", help="run a packaged host script: install-tools, install-unity-editor, compile-editor-scripts"
    )
    script_parser.add_argument("arguments", nargs=argparse.REMAINDER, help="`shamway script --list` names them")

    client_parser = commands.add_parser(
        "client",
        help="fresh-client acceptance: where, deploy, launch, log, mute, unmute, disable-discord",
        add_help=False,
    )
    client_parser.add_argument(
        "arguments", nargs=argparse.REMAINDER, help="passed through; `shamway client --help` lists them"
    )

    documentation = commands.add_parser(
        "docs", help="print this pipeline's documentation, from the installed package"
    )
    documentation.add_argument("topic", nargs="?", help="omit to list the topics")
    documentation.add_argument("--json", action="store_true", help="machine-readable topic list")

    schema = commands.add_parser(
        "schema", help="print the machine-readable operation contract"
    )
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


def _config(args: argparse.Namespace):
    return load_config(args.config)


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        if args.game_dir:
            version, source = game_unity_version(args.game_dir.resolve())
            print(f"Detected Unity {version} from {source}")
        elif args.unity_version:
            version = args.unity_version
        else:
            raise PipelineError("init needs --game-dir or --unity-version")
        changeset = args.changeset
        if not changeset:
            # Best effort: pinning the revision is valuable, but not worth
            # failing a scaffold over an unreachable network.
            try:
                changeset = fetch_release(version).changeset
                print(f"Resolved Unity {version} changeset {changeset}")
            except PipelineError:
                print("Could not resolve the changeset; Unity will add it on first open")
        created = initialize(
            args.mod_root, args.mod_name, args.bundle_name, version, changeset,
            args.adopt, args.source_root, args.manifest_dir,
        )
        for path in created:
            print(f"created {path}")
        if args.adopt:
            print(
                "Adopted an existing Unity project. Mark the mod's own asset generators "
                "with [ShamwayPreBuild] so 'shamway build' runs them before collecting."
            )
        print("Next: set SEVEN_DAYS_TO_DIE_DIR and UNITY_EDITOR, then run shamway doctor")
        return 0

    if args.command == "inspect":
        if args.deep:
            report = deep_inspect(args.bundle)
            if args.json:
                print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
            else:
                print(f"path: {report.path}")
                print(f"objects: {report.object_count}")
                print("types: " + ", ".join(f"{k}={v}" for k, v in report.type_counts.items()))
                for entry in report.entries:
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
            for key, value in data.items():
                print(f"{key}: {value}")
        return 0
    if args.command == "check-mesh":
        report = check_mesh(args.mesh, args.max_extent, args.strict)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        else:
            data = report.as_dict()
            for key in ("path", "extents", "geometry_count", "vertex_count", "face_count",
                        "watertight", "gltf_errors", "gltf_warnings"):
                if data[key] is not None:
                    print(f"{key}: {data[key]}")
            for note in report.skipped:
                print(f"skipped: {note}")
            for problem in report.problems:
                print(f"problem: {problem}")
            print("OK" if report.ok else "FAILED")
        return 0 if report.ok else 1
    if args.command == "check-sound":
        report = check_sound(args.clip, args.max_seconds, args.require_mono)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        else:
            data = report.as_dict()
            for key in ("path", "channels", "sample_rate", "duration_seconds", "peak",
                        "peak_dbfs", "rms", "dc_offset", "clipped_samples",
                        "leading_silence_seconds", "trailing_silence_seconds"):
                print(f"{key}: {data[key]}")
            for note in report.notes:
                print(f"note: {note}")
            for problem in report.problems:
                print(f"problem: {problem}")
            print("OK" if report.ok else "FAILED")
        return 0 if report.ok else 1
    if args.command == "check-log":
        reject_disabled_modules(args.log)
        print(f"OK: no disabled-module warnings in {args.log}")
        return 0
    if args.command == "generate":
        if args.list or not args.generator:
            for entry in describe_generators():
                needs = ", ".join(entry["capabilities"]) or "nothing beyond the standard library"
                print(f"{entry['name']:14} {entry['summary']}")
                print(f"{'':14} needs: {needs}")
            print()
            print("Run one with: shamway generate NAME [ARGS...]  (--help works per generator)")
            return 0
        return run_generator(args.generator, args.arguments)
    if args.command == "client":
        from .client import main as client_main

        return client_main(args.arguments or ["--help"])
    if args.command == "docs":
        if not args.topic:
            entries = doc_topics()
            if args.json:
                print(json.dumps(entries, indent=2, sort_keys=True))
            else:
                for entry in entries:
                    mark = " " if entry["available"] == "true" else "!"
                    print(f"{mark} {entry['topic']:20} {entry['summary']}")
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
            try:
                return Pipeline(load_config(args.config))
            except PipelineError:
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
    if args.command == "unity-release" and args.version:
        data = fetch_release(args.version, args.platform).as_dict()
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            for key, value in data.items():
                print(f"{key}: {value}")
        return 0
    if args.command == "validate" and args.bundle and args.config is None:
        info = validate_bundle(args.bundle)
        print(f"OK: {info.path} Unity {info.unity_version}; class-142 present")
        return 0

    config = _config(args)
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
        print(f"OK: {output}")
        if not args.probe:
            print("Offline gates passed. A fresh-client load is still required for acceptance.")
        return 0
    if args.command == "validate":
        expected = game_unity_version(config.game_dir)[0] if config.game_dir else None
        if args.bundle:
            info = validate_bundle(args.bundle, expected)
            print(f"OK: {info.path} Unity {info.unity_version}; class-142 present")
        else:
            report = validate_mod(config)
            print(*report.messages, sep="\n")
            print(f"OK: bundle and {report.reference_count} reference(s) validated (XML and code_references)")
        return 0
    if args.command == "unity-release":
        data = fetch_release(project_unity_version(config.unity_project), args.platform).as_dict()
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            for key, value in data.items():
                print(f"{key}: {value}")
        return 0
    if args.command == "status":
        report = collect_status(config)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        else:
            data = report.as_dict()
            for key in (
                "mod_name", "bundle_path", "bundle_present", "bundle_unity_version",
                "game_unity_version", "version_matches_game",
                "bundle_has_assetbundle_object", "asset_count", "reference_count", "valid",
            ):
                print(f"{key}: {data[key]}")
            for problem in report.problems:
                print(f"problem: {problem}")
        return 0 if report.valid else 1
    if args.command == "check-icons":
        report = check_icons(config.mod_root, config.config_dir, args.atlas_root, args.cell)
        if args.json:
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        else:
            for icon in report.icons:
                coverage = "" if icon.alpha_coverage is None else f" {icon.alpha_coverage:.0%} opaque"
                print(f"{icon.atlas}/{icon.stem}: {icon.width}x{icon.height} {icon.colour_type}{coverage}")
            print(f"resolved: {len(report.resolved)}  external: {len(report.external)}")
            for note in report.notes:
                print(f"note: {note}")
            for problem in report.problems:
                print(f"problem: {problem}")
            print("OK" if report.ok else "FAILED")
        return 0 if report.ok else 1
    if args.command == "render-icon":
        result = render_icon(
            config, args.prefab, args.output, args.size, args.atlas,
            args.yaw, args.pitch, args.padding,
        )
        if args.json:
            print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        else:
            print(f"OK: {result.output} ({result.size}px from {result.rendered_pixels}px, "
                  f"{result.alpha_coverage:.0%} opaque)")
            print("An icon is accepted in the inventory, not in a file browser.")
        return 0
    if args.command == "refs":
        for reference in discover_references(config.config_dir):
            print(f"{reference.source.relative_to(config.mod_root)}: {reference.uri}")
        return 0
    raise PipelineError(f"unknown command {args.command}")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # `client` is a passthrough with its own argparse, so its `--help` must
    # reach it rather than be claimed (and rejected) by this parser.
    if arguments[:1] == ["script"]:
        from .scripts import main as script_main  # noqa: PLC0415

        try:
            return script_main(arguments[1:])
        except PipelineError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if arguments[:1] == ["client"]:
        from .client import main as client_main  # noqa: PLC0415

        try:
            return client_main(arguments[1:] or ["--help"])
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
