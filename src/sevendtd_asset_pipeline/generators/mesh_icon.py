#!/usr/bin/env python3
"""Render a mesh file into an atlas icon through headless Blender.

This is the editorless half of the "the icon *is* the item" lane. `shamway
render-icon` photographs a **bundle prefab** in a Unity editor, which is the
right answer for a mod that has one; this photographs the **mesh file** with
Blender, which is the only answer for a mod on the synthesized path, where
there is no prefab and no editor.

    shamway generate mesh-icon assets-src/bundle/myModThing.glb \\
        UIAtlases/ItemIconAtlas/myModThing.png

The camera defaults match `IconRenderer.cs` (yaw 208, pitch 8, padding 1.22)
so the two lanes frame the same object the same way, and the supersample and
Lanczos downscale match `icon_render.py` — a real resampler is what keeps thin
geometry from breaking into dashes.

What it renders is **geometry, not appearance**. A mesh in an interchange file
has no Unity material, so this is a neutral-clay render: silhouette, framing
and proportion are what it proves. That is exactly the same wall that stops
the bundle writer at meshes (`shamway docs no-unity`), and it is why the
generated icon is a starting point for the art lane rather than the end of it.

Cycles on the CPU is deliberate. Blender's realtime engines want a GL context,
and a headless host without one produces a blank or garbage frame *and exits
zero* — the same failure `render-icon` designs out by refusing `-nographics`.
The coverage check below is the second guard: a render that drew almost
nothing fails instead of shipping a transparent cell.

Requires Blender on PATH (scripts/install-tools.sh --with-authoring) and
Pillow. Gate the result with `shamway check-icons`.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MINIMUM_COVERAGE = 0.02

BLENDER_SCRIPT = """
import math
import sys

import bpy
from mathutils import Euler, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
source, out = argv[0], argv[1]
pixels = int(argv[2])
yaw, pitch, padding = (float(value) for value in argv[3:6])
samples = int(argv[6])

bpy.ops.wm.read_factory_settings(use_empty=True)

suffix = source.lower().rsplit(".", 1)[-1]
if suffix in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=source)
elif suffix == "obj":
    bpy.ops.wm.obj_import(filepath=source)
elif suffix == "stl":
    bpy.ops.wm.stl_import(filepath=source)
elif suffix == "ply":
    bpy.ops.wm.ply_import(filepath=source)
else:
    raise SystemExit("unsupported mesh format: " + suffix)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("the file imported no mesh objects")

# One neutral material for every object, so the render reports silhouette and
# form rather than whatever the interchange file happened to carry.
clay = bpy.data.materials.new("shamwayClay")
clay.use_nodes = True
principled = clay.node_tree.nodes["Principled BSDF"]
principled.inputs["Base Color"].default_value = (0.62, 0.62, 0.60, 1.0)
principled.inputs["Roughness"].default_value = 0.55
for obj in meshes:
    obj.data.materials.clear()
    obj.data.materials.append(clay)

corners = [obj.matrix_world @ Vector(c) for obj in meshes for c in obj.bound_box]
low = Vector((min(c[i] for c in corners) for i in range(3)))
high = Vector((max(c[i] for c in corners) for i in range(3)))
centre = (low + high) / 2.0
radius = max((high - low).length / 2.0, 1e-4)

camera_data = bpy.data.cameras.new("shamwayIconCamera")
camera_data.type = "ORTHO"
camera = bpy.data.objects.new("shamwayIconCamera", camera_data)
bpy.context.scene.collection.objects.link(camera)
# Blender is Z-up and a camera looks down its own -Z, so the view direction is
# read off the rotation matrix rather than derived by hand: an inverted axis
# here is an icon of the object's back, which renders perfectly.
camera.rotation_euler = Euler((math.radians(90.0 - pitch), 0.0, math.radians(yaw)), "XYZ")
# matrix_world is evaluated lazily: read without this update it is still the
# identity, the camera points down -Z from the wrong place, and the render is
# a transparent square that no error reports.
bpy.context.view_layer.update()
view = camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
camera.location = centre - view * (radius * 4.0)
bpy.context.view_layer.update()

# Fit the orthographic frame to the projected bounds, not to the radius: a
# sphere's radius over-pads every shape that is not a sphere.
inverse = camera.matrix_world.inverted()
local = [inverse @ corner for corner in corners]
half_width = max(abs(point.x) for point in local)
half_height = max(abs(point.y) for point in local)
camera_data.ortho_scale = max(half_width, half_height) * 2.0 * padding
bpy.context.scene.camera = camera

# Key, fill and rim, in the relative directions IconRenderer.cs uses.
for name, euler, energy, colour in (
    ("key", (math.radians(52.0), 0.0, math.radians(yaw - 34.0)), 3.4, (1.0, 0.97, 0.90)),
    ("fill", (math.radians(74.0), 0.0, math.radians(yaw + 120.0)), 1.5, (0.66, 0.74, 0.88)),
    ("rim", (math.radians(112.0), 0.0, math.radians(yaw + 186.0)), 1.1, (0.95, 0.88, 0.76)),
):
    light_data = bpy.data.lights.new(name, type="SUN")
    light_data.energy = energy
    light_data.color = colour
    light_data.angle = 0.24
    light = bpy.data.objects.new(name, light_data)
    light.rotation_euler = Euler(euler, "XYZ")
    bpy.context.scene.collection.objects.link(light)

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = samples
scene.cycles.use_denoising = False
scene.render.film_transparent = True
scene.render.resolution_x = pixels
scene.render.resolution_y = pixels
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = out
bpy.ops.render.render(write_still=True)

print("BLENDER_EXTENTS %.6f %.6f %.6f" % tuple(high - low))
print("BLENDER_OBJECTS %d" % len(meshes))
"""


def _downscale(rendered: Path, target: Path, size: int) -> float:
    """Lanczos the supersampled frame down and report its alpha coverage."""
    from PIL import Image

    with Image.open(rendered) as handle:
        image = handle.convert("RGBA").resize((size, size), Image.LANCZOS)
        alpha = image.getchannel("A")
        # One byte per pixel in mode "L", so the raw buffer is the alpha list.
        coverage = sum(1 for value in alpha.tobytes() if value > 8) / float(size * size)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_suffix(target.suffix + ".tmp")
        image.save(staged, format="PNG")
    staged.replace(target)
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mesh", type=Path, help="the .glb/.gltf/.obj/.stl/.ply to photograph")
    parser.add_argument("output", type=Path, help="destination atlas cell .png")
    parser.add_argument("--size", type=int, default=160, help="atlas cell pixels (default 160)")
    parser.add_argument(
        "--supersample", type=int, default=4, help="render at N x --size, then Lanczos down"
    )
    parser.add_argument("--yaw", type=float, default=208.0, help="camera azimuth in degrees")
    parser.add_argument("--pitch", type=float, default=8.0, help="camera elevation in degrees")
    parser.add_argument("--padding", type=float, default=1.22, help="frame margin multiplier")
    parser.add_argument("--samples", type=int, default=32, help="Cycles samples per pixel")
    args = parser.parse_args(argv)

    blender = shutil.which("blender")
    if not blender:
        print(
            "ERROR: blender is not on PATH. Run scripts/install-tools.sh --with-authoring.",
            file=sys.stderr,
        )
        return 1
    if not args.mesh.is_file():
        print(f"ERROR: no mesh at {args.mesh}", file=sys.stderr)
        return 1
    if args.size < 8 or args.supersample < 1:
        print("ERROR: --size must be at least 8 and --supersample at least 1", file=sys.stderr)
        return 1
    if args.output.suffix.lower() != ".png":
        print("ERROR: an atlas cell is a .png", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "render.py"
        script.write_text(BLENDER_SCRIPT, encoding="utf-8")
        rendered = Path(directory) / "icon.png"
        result = subprocess.run(
            [
                blender,
                "--background",
                "--factory-startup",
                "--python",
                str(script),
                "--",
                str(args.mesh),
                str(rendered),
                str(args.size * args.supersample),
                str(args.yaw),
                str(args.pitch),
                str(args.padding),
                str(args.samples),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0 or not rendered.is_file():
            print(result.stdout, file=sys.stderr)
            print(f"ERROR: Blender exited {result.returncode} without rendering", file=sys.stderr)
            return 1
        coverage = _downscale(rendered, args.output, args.size)

    if coverage < MINIMUM_COVERAGE:
        # A blank cell looks like a framing bug and passes every other check.
        args.output.unlink(missing_ok=True)
        print(
            f"ERROR: only {coverage:.1%} of the cell was drawn, under {MINIMUM_COVERAGE:.0%}. "
            "The camera framed nothing: check the mesh has geometry "
            f"('shamway check-mesh {args.mesh}') and is not at the scene origin's far side.",
            file=sys.stderr,
        )
        return 1

    print(f"wrote {args.output} ({args.size}x{args.size}, {coverage:.1%} covered)")
    print("It is a clay render: silhouette and framing, not the in-game look.")
    print("Gate it: shamway check-icons  —  then look at it next to the game's own icons.")
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
