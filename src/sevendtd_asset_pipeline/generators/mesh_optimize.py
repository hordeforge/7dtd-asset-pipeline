#!/usr/bin/env python3
"""Simplify and reorder a mesh with gltfpack, and prove the shape survived.

    shamway generate mesh-optimize thing.glb thing-lod1.glb --simplify 0.5

[gltfpack](https://github.com/zeux/meshoptimizer) does three things: it
simplifies (fewer triangles), reorders indices for vertex-cache locality, and
quantizes vertex attributes. Only the first two are worth anything *here*, and
that is worth stating because it is not obvious:

**Quantization does not shrink a shamway bundle.** gltfpack makes the glTF
smaller by storing positions as 16-bit, but `bundle_writer.mesh` re-encodes
every vertex into Unity's own stream as float32 regardless. A quantized input
produces a byte-identical-sized `Mesh`. Measured: a 7888-byte GLB packs to
4048 bytes and yields the same Unity mesh either way. Reach for gltfpack to
cut *triangles*, not bytes on disk.

Simplification does transfer, because fewer triangles is fewer vertices in the
stream — and it is how a mod builds LOD variants of one authored mesh without
re-authoring them.

The gate here is the reason this is a command rather than a line in a README:
simplification is lossy in *shape*, and a collapsed mesh still loads, still
passes `check-mesh`, and is simply the wrong object. This compares extents
before and after and refuses a mesh that moved further than `--max-drift`.

Requires gltfpack on PATH: `npm install -g gltfpack`, or a build from
meshoptimizer. Validate the result with `shamway check-mesh` as usual.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

GLTFPACK_TIMEOUT = 300


def measure(path: Path) -> tuple[int, int, list[float]]:
    """Triangles, vertices and extents, read through trimesh."""
    logging.getLogger("trimesh").addHandler(logging.NullHandler())
    import trimesh

    loaded = trimesh.load(str(path), force="mesh")
    extents = [round(float(value), 6) for value in loaded.extents]
    return len(loaded.faces), len(loaded.vertices), extents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the .glb/.gltf to optimize")
    parser.add_argument("output", type=Path, help="destination .glb")
    parser.add_argument(
        "--simplify",
        type=float,
        default=0.0,
        help="target fraction of the original triangles (0.5 halves them); "
        "0 disables simplification and only reorders",
    )
    parser.add_argument(
        "--max-drift",
        type=float,
        default=0.02,
        help="largest allowed change in any extent, as a fraction (default 2%%)",
    )
    parser.add_argument(
        "--keep-quantization",
        action="store_true",
        help="leave gltfpack's vertex quantization on; it does not shrink a "
        "shamway bundle, and it costs precision the writer would have kept",
    )
    args = parser.parse_args(argv)

    gltfpack = shutil.which("gltfpack")
    if not gltfpack:
        print(
            "ERROR: gltfpack is not on PATH. Install it with 'npm install -g gltfpack', "
            "or build it from https://github.com/zeux/meshoptimizer.",
            file=sys.stderr,
        )
        return 1
    if not args.source.is_file():
        print(f"ERROR: no mesh at {args.source}", file=sys.stderr)
        return 1
    if not 0.0 <= args.simplify <= 1.0:
        print("ERROR: --simplify is a fraction between 0 and 1", file=sys.stderr)
        return 1

    command = [gltfpack, "-i", str(args.source), "-o", str(args.output)]
    if args.simplify:
        command += ["-si", str(args.simplify)]
    if not args.keep_quantization:
        # -noq keeps float32 attributes. The writer re-encodes to float32
        # anyway, so quantizing here only loses precision for no gain.
        command.append("-noq")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        command,
        check=False,
        timeout=GLTFPACK_TIMEOUT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0 or not args.output.is_file():
        print(result.stdout.decode("utf-8", errors="replace").strip(), file=sys.stderr)
        print(f"ERROR: gltfpack exited {result.returncode}", file=sys.stderr)
        return 1

    before_faces, before_verts, before_extents = measure(args.source)
    after_faces, after_verts, after_extents = measure(args.output)

    drift = [
        abs(after - before) / before if before else 0.0
        for before, after in zip(before_extents, after_extents, strict=True)
    ]
    worst = max(drift, default=0.0)

    print(f"source:    {args.source}")
    print(f"output:    {args.output}")
    print(f"triangles: {before_faces} -> {after_faces}")
    print(f"vertices:  {before_verts} -> {after_verts}")
    print(f"extents:   {before_extents} -> {after_extents}")
    print(f"drift:     {worst:.4%} (limit {args.max_drift:.2%})")
    print(f"file:      {args.source.stat().st_size} -> {args.output.stat().st_size} bytes")

    if worst > args.max_drift:
        args.output.unlink(missing_ok=True)
        print(
            f"ERROR: simplification moved an extent by {worst:.2%}, over --max-drift. "
            "A collapsed mesh still loads and still passes check-mesh; it is just "
            "the wrong shape. Raise --simplify toward 1.0, or the limit if the "
            "change is intended.",
            file=sys.stderr,
        )
        return 1

    print("note:      a bundle does not shrink from quantization; the writer re-encodes")
    print(f"next:      shamway check-mesh {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
