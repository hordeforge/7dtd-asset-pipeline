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
from .errors import PipelineError
from .game import game_unity_version, project_unity_version
from .mesh_check import check_mesh
from .references import discover_references
from .operations import manifest
from .scaffold import initialize
from .serve import serve
from .status import collect_status
from .unity_release import fetch_release
from .unityfs import inspect_bundle
from .validation import validate_bundle, validate_mod


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="7dtd-assets",
        description="Build and validate Unity asset bundles for 7 Days to Die mods.",
    )
    parser.add_argument("--config", type=Path, help="path to .7dtd-assets.toml")
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

    capability = commands.add_parser(
        "capabilities", help="list optional capabilities, what they unlock, and how to install them"
    )
    capability.add_argument("--json", action="store_true")
    capability.add_argument("--versions", action="store_true", help="also probe installed versions")
    capability.add_argument("--missing", action="store_true", help="list only unavailable ones")

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
            args.mod_root, args.mod_name, args.bundle_name, version, changeset
        )
        for path in created:
            print(f"created {path}")
        print("Next: set SEVEN_DAYS_TO_DIE_DIR and UNITY_EDITOR, then run 7dtd-assets doctor")
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
    if args.command == "check-log":
        reject_disabled_modules(args.log)
        print(f"OK: no disabled-module warnings in {args.log}")
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
            print(f"OK: bundle and {report.reference_count} XML reference(s) validated")
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
    if args.command == "refs":
        for reference in discover_references(config.config_dir):
            print(f"{reference.source.relative_to(config.mod_root)}: {reference.uri}")
        return 0
    raise PipelineError(f"unknown command {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return run(_parser().parse_args(argv))
    except (PipelineError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
