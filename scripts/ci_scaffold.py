#!/usr/bin/env python3
"""The scaffold job's fixture authoring and its assertions.

The `scaffold` job in .github/workflows/ci.yml proves the consumer path on a
runner that has never had a Unity editor. Its fixtures and checks live here
rather than in heredocs inside the workflow, for the reason
github_asset_url.py gives: one language per file. The practical win is that
`make check` compiles, lints and type-checks this file, which a heredoc in a
YAML string is never checked by anything until the job runs it.

Subcommands, in the order the job calls them:

    ci_scaffold.py author-sources DIR
    ci_scaffold.py check-vkd3d CAPS_JSON --expect usable|unusable
    ci_scaffold.py check-classes DEEP_JSON --require A B --forbid X Y

Every check prints a one-line OK on success and a single `ERROR: ...` on
failure, matching what the rest of this repository's commands do, and exits
non-zero so the job stops rather than continuing on a broken artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The bundle member names the workflow's Config/blocks.xml references. A block
# whose Model points at a prefab the bundle does not carry is exactly the
# silent failure the scaffold job exists to catch, so the names are fixed here
# rather than passed in.
MESH_NAME = "myModThing.glb"
ALBEDO_NAME = "myModThing_albedo.png"

# A 40cm cube: large enough that a wrong-units export is visible, small enough
# to be a plausible block prop.
MESH_EXTENTS = (0.4, 0.4, 0.4)
ALBEDO_SIZE = (64, 64)
ALBEDO_RGBA = (120, 60, 40, 255)


def author_sources(directory: Path) -> int:
    """Write the mesh and texture the bundle writer reads.

    trimesh and Pillow write both files directly. `shamway generate mesh`
    would be the authoring command, but it shells out to Blender, which this
    runner has no reason to install: what is under test is the writer reading
    an interchange file, not how the file was made.

    The mesh carries UV0. The writer refuses a mesh that has an albedo beside
    it and nothing to sample it with, because that combination draws one flat
    colour while every offline gate still passes. trimesh's primitives carry
    no UVs, so this supplies them the way a real export does.
    """
    import numpy
    import trimesh

    directory.mkdir(parents=True, exist_ok=True)
    box = trimesh.creation.box(extents=MESH_EXTENTS)
    flat = box.vertices[:, :2]
    span = box.vertices.max(axis=0) - box.vertices.min(axis=0)
    uv = (flat - flat.min(axis=0)) / span[:2]
    box.visual = trimesh.visual.TextureVisuals(uv=numpy.asarray(uv, dtype=float))
    box.export(directory / MESH_NAME)

    from PIL import Image

    Image.new("RGBA", ALBEDO_SIZE, ALBEDO_RGBA).save(directory / ALBEDO_NAME)
    print(f"OK: wrote {MESH_NAME} (with UV0) and {ALBEDO_NAME} into {directory}")
    return 0


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def check_vkd3d(report: Path, expect_usable: bool) -> int:
    """Assert the shader lane's capability row says what this job set up.

    Ubuntu packages vkd3d-compiler 1.2, which predates the HLSL support the
    writer needs (added in 1.3). The job installs that packaged binary first
    to exercise the degraded path, then a source build for the whole one, so
    both states are gated rather than only the happy one.
    """
    payload = _load(report)
    if not isinstance(payload, list):
        print(f"ERROR: {report} is not a capability array", file=sys.stderr)
        return 1
    rows = [row for row in payload if isinstance(row, dict) and row.get("name") == "vkd3d-compiler"]
    if not rows:
        print(f"ERROR: {report} lists no vkd3d-compiler row", file=sys.stderr)
        return 1
    lane = rows[0]
    if not lane.get("path"):
        print("ERROR: vkd3d-compiler is not on PATH; this step installed it", file=sys.stderr)
        return 1
    available = bool(lane.get("available"))
    if available != expect_usable:
        state = "usable" if available else "unusable"
        wanted = "usable" if expect_usable else "unusable"
        print(f"ERROR: expected a {wanted} vkd3d lane, got {state}", file=sys.stderr)
        return 1
    if expect_usable:
        print(f"OK: usable shader lane at {lane['path']}")
        return 0
    if not lane.get("unusable_reason"):
        print("ERROR: an unusable tool must say why, and this row does not", file=sys.stderr)
        return 1
    print(f"OK: present but unusable, reported as: {lane['unusable_reason']}")
    return 0


def check_classes(report: Path, require: list[str], forbid: list[str]) -> int:
    """Assert which serialized classes the written bundle does and does not carry.

    Both directions matter. The whole lane must produce every class the game
    resolves; the degraded lane must produce a bare mesh and *not* the prefab
    group, because packing a prefab with no usable shader would ship something
    that loads and draws nothing.
    """
    payload = _load(report)
    if not isinstance(payload, dict) or not isinstance(payload.get("type_counts"), dict):
        print(f"ERROR: {report} carries no type_counts object", file=sys.stderr)
        return 1
    present = set(payload["type_counts"])
    missing = sorted(set(require) - present)
    if missing:
        print(f"ERROR: bundle is missing {missing}; got {sorted(present)}", file=sys.stderr)
        return 1
    unwanted = sorted(set(forbid) & present)
    if unwanted:
        print(f"ERROR: bundle carries {unwanted}, which this lane must not pack", file=sys.stderr)
        return 1
    print(f"OK: {sorted(present)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="scaffold-job fixtures and assertions")
    sub = parser.add_subparsers(dest="command", required=True)

    author = sub.add_parser("author-sources", help="write the mesh and texture fixtures")
    author.add_argument("directory", type=Path, help="the assets-src/bundle directory")

    vkd3d = sub.add_parser("check-vkd3d", help="assert the shader lane's capability row")
    vkd3d.add_argument("report", type=Path, help="`shamway capabilities --json` output")
    vkd3d.add_argument(
        "--expect", choices=("usable", "unusable"), required=True, help="the expected lane state"
    )

    classes = sub.add_parser("check-classes", help="assert the bundle's serialized classes")
    classes.add_argument("report", type=Path, help="`shamway inspect --deep --json` output")
    classes.add_argument("--require", nargs="*", default=[], help="classes that must be present")
    classes.add_argument("--forbid", nargs="*", default=[], help="classes that must be absent")

    arguments = parser.parse_args()
    if arguments.command == "author-sources":
        return author_sources(arguments.directory)
    if arguments.command == "check-vkd3d":
        return check_vkd3d(arguments.report, arguments.expect == "usable")
    return check_classes(arguments.report, arguments.require, arguments.forbid)


if __name__ == "__main__":
    raise SystemExit(main())
