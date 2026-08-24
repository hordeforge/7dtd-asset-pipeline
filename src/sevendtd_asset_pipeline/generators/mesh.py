#!/usr/bin/env python3
"""Generate a parameterized mesh through headless Blender.

Blender is the authored-mesh lane: the right tool for organic, rigged, or
sculpted geometry, and for anything a composition of primitives cannot express.
This script is a working starting point for it, not a modelling tool — it
exists so a mod's first mesh is a checked-in script with recorded dimensions
rather than unrecorded GUI state, and so an agent has a template to extend.
Copy it into the mod's own `assets-src/` and build the real geometry there with
the full `bpy` API.

Validate whatever you export before it goes anywhere:

    shamway check-mesh out.glb

The GLB it writes is a bundle input as it stands. Dropped into a synthesized
mod's `assets-src/bundle/`, `shamway build` writes it into the `.unity3d` as a
Unity `Mesh` with no editor involved; a mod that builds with Unity imports the
same file instead. See `shamway docs no-unity` for which of the two a mod is
in, and for why a `Mesh` is not yet a prefab.

For hard-surface props that are really a few boxes and cylinders, the other
lane is cheaper: compose built-in primitives in the Unity project with
`GeneratedAsset.Primitive(...)`, which emits no mesh asset at all.

    shamway generate mesh out.glb --shape cylinder --size 0.19 0.19 0.42
    shamway generate mesh out.glb --shape box --size 1 0.5 2 --name myModCrate

`--size` is metres as **width, depth, height**. Blender is Z-up, so height is
authored as Z there; the glTF exporter converts to the Y-up convention Unity
and 7DTD use, and the height arrives as Y. Verified: `--size 0.19 0.19 0.42`
exports bounds of 0.19 x 0.42 x 0.19 in XYZ.

The pivot sits at the base, not the centre, so a placed block rests on the
ground instead of sinking half-way into it (exported bounds start at Y = 0).

Requires Blender on PATH (scripts/install-tools.sh --with-authoring).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BLENDER_SCRIPT = """
import sys, bpy
argv = sys.argv[sys.argv.index("--") + 1:]
shape, name, out = argv[0], argv[1], argv[2]
sx, sy, sz = (float(value) for value in argv[3:6])

bpy.ops.wm.read_factory_settings(use_empty=True)
if shape == "box":
    bpy.ops.mesh.primitive_cube_add(size=1.0)
elif shape == "cylinder":
    bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1.0, vertices=32)
elif shape == "sphere":
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=32, ring_count=16)
else:
    raise SystemExit("unknown shape " + shape)

obj = bpy.context.active_object
obj.name = name
obj.data.name = name
# Blender is Z-up; the exporter converts to Unity's Y-up, so height is Z here.
obj.scale = (sx, sy, sz)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
# Pivot at the base, so the origin is the contact point rather than the centre.
bpy.ops.object.mode_set(mode="OBJECT")
obj.data.transform(__import__("mathutils").Matrix.Translation((0, 0, sz / 2)))
obj.data.update()
bpy.ops.object.shade_smooth() if shape == "sphere" else None

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=False)
dims = obj.dimensions
print("BLENDER_EXTENTS %.6f %.6f %.6f" % (dims.x, dims.y, dims.z))
print("BLENDER_VERTS %d" % len(obj.data.vertices))
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="destination .glb")
    parser.add_argument("--shape", choices=("box", "cylinder", "sphere"), default="box")
    parser.add_argument(
        "--size",
        nargs=3,
        type=float,
        metavar=("WIDTH", "DEPTH", "HEIGHT"),
        default=[1.0, 1.0, 1.0],
        help="real-world metres; height arrives as Y after the Y-up conversion",
    )
    parser.add_argument("--name", default="generatedMesh", help="object and mesh name")
    args = parser.parse_args(argv)

    blender = shutil.which("blender")
    if not blender:
        print(
            "ERROR: blender is not on PATH. Run scripts/install-tools.sh --with-authoring.",
            file=sys.stderr,
        )
        return 1
    if any(value <= 0 for value in args.size):
        raise SystemExit("ERROR: every --size component must be positive")
    if args.output.suffix.lower() != ".glb":
        raise SystemExit("ERROR: export target must be .glb")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "generate.py"
        script.write_text(BLENDER_SCRIPT, encoding="utf-8")
        staged = Path(directory) / "out.glb"
        result = subprocess.run(
            [
                blender,
                "--background",
                "--factory-startup",
                "--python",
                str(script),
                "--",
                args.shape,
                args.name,
                str(staged),
                *(str(value) for value in args.size),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0 or not staged.is_file():
            print(result.stdout, file=sys.stderr)
            print(f"ERROR: Blender exited {result.returncode} without exporting", file=sys.stderr)
            return 1
        # Replace only on success, so a failed run never leaves a broken mesh.
        shutil.move(str(staged), args.output)

    for line in result.stdout.splitlines():
        if line.startswith("BLENDER_EXTENTS"):
            x, y, z = line.split()[1:]
            print(f"extents:  {float(x):.4f} x {float(y):.4f} x {float(z):.4f} m")
        elif line.startswith("BLENDER_VERTS"):
            print(f"vertices: {line.split()[1]}")
    print(f"path:     {args.output}")
    print(f"name:     {args.name}   (rename the Unity prefab to the bundle stem)")
    print("note:     height is the third value and arrives as Y after export")
    print("next:     shamway check-mesh " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
