"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import reject_disabled_modules, run_build
from .config import load_config
from .doctor import run_doctor
from .errors import PipelineError
from .game import game_unity_version
from .references import discover_references
from .scaffold import initialize
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
        created = initialize(args.mod_root, args.mod_name, args.bundle_name, version)
        for path in created:
            print(f"created {path}")
        print("Next: set SEVEN_DAYS_TO_DIE_DIR and UNITY_EDITOR, then run 7dtd-assets doctor")
        return 0

    if args.command == "inspect":
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
    if args.command == "check-log":
        reject_disabled_modules(args.log)
        print(f"OK: no disabled-module warnings in {args.log}")
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
        return 0
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
