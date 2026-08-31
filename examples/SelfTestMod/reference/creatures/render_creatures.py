"""Render a .glb from several yaw angles, framing the full bounds (no clipping).

Usage (Blender headless):
    blender -b -P render_glb.py -- <glb> <outdir> <stem> [size]

Renders a solid-shaded reference of the whole model from front, both sides,
back, and two three-quarter views. The camera is orthographic and its scale is
derived from the union bounding box with a generous margin, so no angle can
clip the model. Output: <outdir>/<stem>_<label>.png and one contact sheet
<outdir>/<stem>_reference.png.
"""
import bpy, math, os, sys
from mathutils import Vector

def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    glb = args[0]; outdir = args[1]; stem = args[2]
    size = int(args[3]) if len(args) > 3 else 640
    os.makedirs(outdir, exist_ok=True)

    # Clean scene.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Import the glTF.
    bpy.ops.import_scene.gltf(filepath=glb)

    # World-space union bounding box of every mesh.
    deps = bpy.context.evaluated_depsgraph_get()
    mins = Vector((1e9, 1e9, 1e9)); maxs = Vector((-1e9, -1e9, -1e9))
    for ob in bpy.context.scene.objects:
        if ob.type != 'MESH':
            continue
        ev = ob.evaluated_get(deps)
        for corner in ev.bound_box:
            w = ev.matrix_world @ Vector(corner)
            mins = Vector(map(min, mins, w)); maxs = Vector(map(max, maxs, w))
    center = (mins + maxs) / 2.0
    extent = maxs - mins
    diag = max(extent.x, extent.y, extent.z, 0.001)

    # Uniform dark clay + light studio: a clear silhouette on a light bg, so
    # the shape reads whatever the imported material happens to be. This is a
    # geometry reference, not the in-game (textured) look; the albedo is a
    # separate PNG bound by the writer's `_albedo` convention.
    clay = bpy.data.materials.new("Clay"); clay.use_nodes = True
    bsdf = clay.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.75
    world = bpy.data.worlds.new("W"); bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.88, 0.88, 0.88, 1.0); bg.inputs[1].default_value = 1.0
    key = bpy.data.lights.new("Key", type='SUN'); key.energy = 3.5
    keyob = bpy.data.objects.new("Key", key); bpy.context.collection.objects.link(keyob)
    keyob.rotation_euler = (math.radians(55), 0, math.radians(35))
    fill = bpy.data.lights.new("Fill", type='SUN'); fill.energy = 1.2
    fillob = bpy.data.objects.new("Fill", fill); bpy.context.collection.objects.link(fillob)
    fillob.rotation_euler = (math.radians(70), 0, math.radians(220))
    # Assign the clay material to every mesh (uniform silhouette reference).
    for ob in bpy.context.scene.objects:
        if ob.type == 'MESH':
            ob.data.materials.clear()
            ob.data.materials.append(clay)

    scene = bpy.context.scene
    scene.render.resolution_x = size; scene.render.resolution_y = size
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    # Blender's default AgX view transform crushes greys into a washed
    # flat-looking frame; Standard keeps a flat, high-contrast reference.
    try:
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
    except Exception:
        pass

    cam_data = bpy.data.cameras.new("Cam"); cam_data.type = 'ORTHO'
    cam_data.ortho_scale = diag * 1.45  # generous margin: never clip
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

    # (label, yaw_deg, pitch_deg)
    views = [("front", 0, 12), ("threequarter", 45, 18), ("side", 90, 10),
             ("back", 180, 12), ("backquarter", 315, 18), ("otherside", 270, 10)]
    paths = []
    dist = diag * 3.0
    for label, yaw, pitch in views:
        a = math.radians(yaw); p = math.radians(pitch)
        # direction FROM the camera TO the model (camera looks -Z, so place on +dir)
        dirv = Vector((math.cos(p) * math.sin(a), -math.cos(p) * math.cos(a), math.sin(p)))
        cam.location = center + dirv * dist
        # point at the center
        look = center - cam.location
        cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
        out = os.path.join(outdir, f"{stem}_{label}.png")
        scene.render.filepath = out
        bpy.ops.render.render(write_still=True)
        paths.append((label, out))
    # Contact sheet.
    sheet = os.path.join(outdir, f"{stem}_reference.png")
    try:
        from PIL import Image
        imgs = [Image.open(p).convert("RGB") for _, p in paths]
        w, h = imgs[0].size; cols = 3; rows = 2
        canvas = Image.new("RGB", (w * cols, h * rows), (255, 255, 255))
        for i, im in enumerate(imgs):
            canvas.paste(im, ((i % cols) * w, (i // cols) * h))
        canvas.save(sheet)
        print(f"WROTE {sheet}")
    except Exception as e:
        print(f"NO_SHEET {e}")
    print(f"DONE {stem} diag={diag:.3f}")

main()
