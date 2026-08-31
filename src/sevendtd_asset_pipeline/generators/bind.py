#!/usr/bin/env python3
"""Bind an authored mesh to a shipped shamway rig.

`generate entity` skins primitives. This skins a real mesh — a glTF, a
Wavefront OBJ, or several OBJs joined — onto the same bone names Idle1 and
Walk already play, so a modelled mesh still turns in
place on the staged look. The same flags, the same bytes: no GUI state.

    shamway generate bind spider.glb --rig arachnid --height 0.42 \\
        --solidify 0.012 --stretch-x 1.16 --warp 0.08 --double-sided out.glb
    shamway generate bind body.obj --extra head.obj --extra hands.obj \\
        --rig humanoid --head-lift --neck --stretch-x 1.12 out.glb --anim

`--solidify` is for open surfaces (paper-thin insect shells): Unity's Unlit
pass culls back-faces, so a mesh with thousands of boundary edges draws as a
wire cage. `--head-lift` places a `*head*` part so its lowest vertex sits on
the rest of the body's max Z (OBJ parts often arrive in head-local space;
lifting by the origin leaves a head-local mesh inside the torso hole). `--neck`
[metres] lifts that head by a further gap and fills it with a cylinder.
`--voxel` remeshes the joined mesh so overlapping extras fuse into one
surface.
`--anim` writes the sibling `{stem}.anim.json` `generate entity --anim idle,head,walk` would.
Heat-weighting that assigns no vertices (intersecting extras) falls
back to nearest-bone weights so the export still carries a skin.

After Blender exports, this generator lifts `Root` to the glTF scene root.
Blender wraps bones under the armature object (`arachnid/Root/...`); Idle1
names `Root/...`, and a wrapper makes every clip miss.

Requires Blender on PATH (`scripts/install-tools.sh --with-authoring`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from ..errors import PipelineError
from ..rigs import load_rig, rig_to_glb, scaled
from ..workdir import scratch_dir
from . import entity as entity_gen

BLENDER_TIMEOUT = 300
GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
MESH_SUFFIXES = {".glb", ".gltf", ".obj"}

BLENDER_SCRIPT = r"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1 :]
rig_glb, out_glb, name = argv[0], argv[1], argv[2]
height = float(argv[3])
stretch_x = float(argv[4])
stretch_y = float(argv[5])
stretch_z = float(argv[6])
displace = float(argv[7])
decimate = float(argv[8])
solidify = float(argv[9])
warp = float(argv[10])
head_lift = argv[11] == "1"
double_sided = argv[12] == "1"
neck = float(argv[13])
voxel = float(argv[14])
sources = argv[15:]


def bbox(obj):
    xs, ys, zs = [], [], []
    mw = obj.matrix_world
    for v in obj.data.vertices:
        w = mw @ v.co
        xs.append(w.x)
        ys.append(w.y)
        zs.append(w.z)
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs)), len(xs)


def apply_all(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def import_one(path):
    lower = path.lower()
    if lower.endswith(".glb") or lower.endswith(".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path, up_axis="Y", forward_axis="NEGATIVE_Z")
    else:
        raise SystemExit("unsupported mesh format: " + path)


bpy.ops.wm.read_factory_settings(use_empty=True)
imported = []
for path in sources:
    before = {o.name for o in bpy.context.scene.objects}
    import_one(path)
    new = [o for o in bpy.context.scene.objects if o.name not in before]
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    got = []
    # Keep world size before dropping a scale-300 parent armature.
    for o in new:
        if o.type != "MESH":
            continue
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
        apply_all(o)
        imported.append(o)
        got.append(o)
    if len(got) == 1:
        got[0].name = stem
    for o in new:
        if o.type == "ARMATURE":
            bpy.data.objects.remove(o, do_unlink=True)

meshes = [o for o in imported if "Icosphere" not in o.name]
if not meshes:
    raise SystemExit("ERROR: no mesh in " + ",".join(sources))
print("BIND_IMPORTED", [(o.name, bbox(o)[3]) for o in meshes])

def torso_and_heads(objects):
    heads = [o for o in objects if "head" in o.name.lower()]
    bodies = [o for o in objects if "head" not in o.name.lower()]
    if not heads or not bodies:
        return None, []
    named = [o for o in bodies if o.name.lower().startswith("body")]
    torso = named[0] if named else max(bodies, key=lambda o: bbox(o)[2][1])
    return torso, heads


# Place the head by its lowest vertex, not its origin. A head-local
# mesh has its origin in the neck; adding torso_max to every vertex
# parks that origin in the hole and the chin in the chest.
if head_lift or neck > 0:
    torso, heads = torso_and_heads(meshes)
    if torso is not None:
        _, _, (_, bzmax), _ = bbox(torso)
        # Some head extras carry a collar meant to sit in the torso
        # hole. gap=0 parks the lowest vertex on the rim and leaves the
        # collar floating as a plate. A small sink seats it.
        gap = neck if neck > 0 else -0.08
        for head in heads:
            _, _, (hzmin, _), _ = bbox(head)
            delta = (bzmax + gap) - hzmin
            for v in head.data.vertices:
                v.co.z += delta
            head.data.update()
            print("BIND_HEAD_LIFT", round(delta, 4), bbox(head))

if neck > 0:
    torso, heads = torso_and_heads(meshes)
    if torso is not None and heads:
        _, _, (tzmin, tzmax), _ = bbox(torso)
        hzmin = min(bbox(head)[2][0] for head in heads)
        z0 = tzmax - 0.08
        z1 = hzmin + 0.08
        depth = max(z1 - z0, 0.02)
        # Shoulder verts dominate a percentile of the top slice; a 7DTD
        # collar opening is ~0.12 m radius. A neck is ~0.06 m.
        hole = []
        for v in torso.data.vertices:
            if v.co.z < tzmax - 0.06:
                continue
            radius_xy = math.hypot(v.co.x, v.co.y)
            if radius_xy < 0.11:
                hole.append((v.co.x, v.co.y, radius_xy))
        if hole:
            cx = sum(item[0] for item in hole) / len(hole)
            cy = sum(item[1] for item in hole) / len(hole)
            inner = min(item[2] for item in hole)
            radius = max(0.045, min(inner * 0.55, 0.065))
        else:
            cx, cy, radius = 0.0, 0.0, 0.055
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=24,
            radius=radius,
            depth=depth,
            location=(cx, cy, z0 + depth / 2.0),
        )
        cylinder = bpy.context.view_layer.objects.active
        cylinder.name = "NeckFill"
        apply_all(cylinder)
        meshes.append(cylinder)
        print("BIND_NECK", round(neck, 4), round(radius, 4), round(depth, 4))

def name_bone_weights(mesh_obj):
    leaf = mesh_obj.name.lower()
    indices = list(range(len(mesh_obj.data.vertices)))
    mesh_obj.vertex_groups.clear()

    def assign(bone, verts):
        if not verts:
            return
        if bone not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=bone)
        mesh_obj.vertex_groups[bone].add(verts, 1.0, "REPLACE")

    if "head" in leaf:
        assign("Head", indices)
        return "Head"
    if "neck" in leaf:
        assign("Neck", indices)
        return "Neck"
    if "hand" in leaf:
        left = [
            i
            for i, vert in enumerate(mesh_obj.data.vertices)
            if (mesh_obj.matrix_world @ vert.co).x < 0
        ]
        right = [i for i in indices if i not in set(left)]
        assign("LeftHand", left)
        assign("RightHand", right)
        return "hands"
    if "foot" in leaf or "feet" in leaf:
        left = [
            i
            for i, vert in enumerate(mesh_obj.data.vertices)
            if (mesh_obj.matrix_world @ vert.co).x < 0
        ]
        right = [i for i in indices if i not in set(left)]
        assign("LeftFoot", left)
        assign("RightFoot", right)
        return "feet"
    assign("Neck", indices)
    return "Neck"


def import_rig():
    before = {o.name for o in bpy.context.scene.objects}
    bpy.ops.import_scene.gltf(filepath=rig_glb)
    for o in list(bpy.context.scene.objects):
        if o.name in before:
            continue
        if o.type == "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    found = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    print("BIND_ARMATURES", [o.name for o in found])
    return found[0]


def isolate_torso_from_legs(mesh_obj, armature):
    # Heat-weight puts glutes on Thigh (butt walks) and shin verts on Thigh
    # too (Idle1 swings the thigh bone, shin bone has nothing to move).
    # Pin the pelvis to Hips; paint anything on a thigh/shin/foot *shaft*
    # exclusively to that bone. Skip the hip socket on the thigh so glutes
    # are not captured. Leave chest/arms/head on AUTO; only strip stray
    # leg weights there. A height slab that ate the upper thigh made jello.
    hip = next((b for b in armature.data.bones if b.name == "Hips"), None)
    if hip is None:
        return
    mw_arm = armature.matrix_world
    hip_world = mw_arm @ hip.head_local
    spine = next((b for b in armature.data.bones if b.name == "Spine"), None)
    up = Vector((0.0, 0.0, 1.0))
    if spine is not None:
        delta = (mw_arm @ spine.head_local) - hip_world
        if delta.length > 1e-6:
            up = delta.normalized()

    def world_head(bone):
        return mw_arm @ bone.head_local

    def child_with(bone, token):
        for child in bone.children:
            if token in child.name:
                return child
        return None

    def down_end(bone):
        head = world_head(bone)
        tail = mw_arm @ bone.tail_local
        if (tail - head).dot(up) < -0.02:
            return tail
        return head - up * 0.12

    # glTF tails on this rig point at the parent, not the child (thigh
    # head 0.86 → tail 1.26, up into the belly). Walk the child heads
    # instead so a shin vert is not painted onto Foot.
    thighs, shins, feet = [], [], []
    for bone in armature.data.bones:
        start = world_head(bone)
        if "Thigh" in bone.name:
            child = child_with(bone, "Shin")
            thighs.append((bone.name, start, world_head(child) if child else down_end(bone)))
        elif "Shin" in bone.name:
            child = child_with(bone, "Foot")
            shins.append((bone.name, start, world_head(child) if child else down_end(bone)))
        elif "Foot" in bone.name:
            feet.append((bone.name, start, down_end(bone)))
    print(
        "BIND_SHAFTS",
        [(name, round(a.z, 3), round(b.z, 3)) for name, a, b in thighs + shins + feet],
    )
    mw = mesh_obj.matrix_world
    leg_groups = [
        g
        for g in mesh_obj.vertex_groups
        if any(token in g.name.lower() for token in ("thigh", "shin", "foot"))
    ]
    if not (leg_groups or thighs):
        return
    leg_index = {group.index for group in leg_groups}

    def ensure(name):
        if name not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=name)
        return mesh_obj.vertex_groups[name]

    def paint(index, weights):
        keep = set(weights)
        for other in list(mesh_obj.vertex_groups):
            if other.name not in keep:
                other.remove([index])
        for bone, weight in weights.items():
            ensure(bone).add([index], weight, "REPLACE")

    def exclusive(index, bone):
        paint(index, {bone: 1.0})

    def other_side(name):
        if name.startswith("Left"):
            return "Right" + name[4:]
        if name.startswith("Right"):
            return "Left" + name[5:]
        return ""

    def proj(point, start, end):
        span = end - start
        length_sq = span.length_squared
        if length_sq < 1e-12:
            return 0.0, (point - start).length
        t = (point - start).dot(span) / length_sq
        t_clamped = max(0.0, min(1.0, t))
        return t, (point - (start + span * t_clamped)).length

    pinned = 0
    webbed = 0
    painted = {"Thigh": 0, "Shin": 0, "Foot": 0}
    stripped = 0
    shaft_r = 0.15
    for index, vert in enumerate(mesh_obj.data.vertices):
        world = mw @ vert.co
        height = (world - hip_world).dot(up)
        has_leg = any(g.weight > 1e-4 for g in vert.groups if g.group in leg_index)
        if height >= 0.10:
            if has_leg:
                for group in leg_groups:
                    group.remove([index])
                stripped += 1
            continue
        hits = []
        for name, start, end in thighs:
            t, dist = proj(world, start, end)
            # t < 0.18 is the hip socket — glutes sit next to it.
            if t >= 0.18:
                hits.append((name, t, dist, "Thigh"))
        for name, start, end in shins:
            t, dist = proj(world, start, end)
            hits.append((name, t, dist, "Shin"))
        for name, start, end in feet:
            t, dist = proj(world, start, end)
            hits.append((name, t, dist, "Foot"))
        if not hits:
            exclusive(index, "Hips")
            pinned += 1
            continue
        name, t, dist, kind = min(hits, key=lambda item: item[2])
        contra = other_side(name)
        contra_d = min((item[2] for item in hits if item[0] == contra), default=1e9)
        # Voxel fuse leaves a sheet between the calves. Exclusive-paint
        # stretched that into the live-look streaks.
        if dist > shaft_r or contra_d <= dist * 1.5:
            exclusive(index, "Hips")
            if contra_d <= dist * 1.5 and dist <= shaft_r:
                webbed += 1
            else:
                pinned += 1
            continue
        blend = max(0.0, min(1.0, (t - 0.78) / 0.22))
        if kind == "Thigh" and t > 0.78:
            mix = {name: 1.0 - blend, name.replace("Thigh", "Shin"): blend}
        elif kind == "Shin" and t < 0.22:
            mix = {name: t / 0.22, name.replace("Shin", "Thigh"): 1.0 - t / 0.22}
        elif kind == "Shin" and t > 0.78:
            mix = {name: 1.0 - blend, name.replace("Shin", "Foot"): blend}
        elif kind == "Foot" and t < 0.40:
            mix = {name: t / 0.40, name.replace("Foot", "Shin"): 1.0 - t / 0.40}
        else:
            mix = {name: 1.0}
        mix = {bone: weight for bone, weight in mix.items() if weight > 1e-4}
        paint(index, mix or {name: 1.0})
        painted[kind] += 1
    print(
        "BIND_TORSO_ISOLATE",
        "pinned",
        pinned,
        "web",
        webbed,
        "thigh",
        painted["Thigh"],
        "shin",
        painted["Shin"],
        "foot",
        painted["Foot"],
        "stripped_torso",
        stripped,
        "hip_h",
        round(hip_world.z, 3),
    )


def isolate_chest_from_arms(mesh_obj, armature):
    # Heat-weight puts chest verts on Arm, so an Idle1 Z drop melts the
    # torso. Paint arm/forearm/hand shafts; strip Arm from the rest of
    # the chest. Skip the shoulder socket (Arm t < 0.20).
    chest = next((b for b in armature.data.bones if b.name == "Chest"), None)
    if chest is None:
        return
    mw_arm = armature.matrix_world
    mw = mesh_obj.matrix_world
    chest_world = mw_arm @ chest.head_local

    def world_head(bone):
        return mw_arm @ bone.head_local

    def child_with(bone, token):
        for child in bone.children:
            if token in child.name:
                return child
        return None

    arms, forearms, hands = [], [], []
    for bone in armature.data.bones:
        start = world_head(bone)
        if bone.name.endswith("Arm") and "Forearm" not in bone.name:
            child = child_with(bone, "Forearm")
            if child is not None:
                arms.append((bone.name, start, world_head(child)))
        elif "Forearm" in bone.name:
            child = child_with(bone, "Hand")
            if child is not None:
                forearms.append((bone.name, start, world_head(child)))
        elif bone.name.endswith("Hand"):
            parent = bone.parent
            along = start - world_head(parent) if parent is not None else Vector((0.12, 0, 0))
            if along.length < 1e-6:
                along = Vector((0.12, 0, 0))
            hands.append((bone.name, start, start + along.normalized() * 0.12))
    if not arms:
        return

    def ensure(name):
        if name not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=name)
        return mesh_obj.vertex_groups[name]

    def paint(index, bone):
        for other in list(mesh_obj.vertex_groups):
            if other.name != bone:
                other.remove([index])
        ensure(bone).add([index], 1.0, "REPLACE")

    def proj(point, start, end):
        span = end - start
        length_sq = span.length_squared
        if length_sq < 1e-12:
            return 0.0, (point - start).length
        t = (point - start).dot(span) / length_sq
        t_clamped = max(0.0, min(1.0, t))
        return t, (point - (start + span * t_clamped)).length

    arm_groups = [
        g
        for g in mesh_obj.vertex_groups
        if any(token in g.name for token in ("Arm", "Forearm", "Hand", "Shoulder"))
    ]
    painted = 0
    stripped = 0
    shaft_r = 0.12
    for index, vert in enumerate(mesh_obj.data.vertices):
        world = mw @ vert.co
        hits = []
        for name, start, end in arms:
            t, dist = proj(world, start, end)
            if t >= 0.20:
                hits.append((name, dist))
        for name, start, end in forearms + hands:
            _t, dist = proj(world, start, end)
            hits.append((name, dist))
        if hits:
            name, dist = min(hits, key=lambda item: item[1])
            if dist <= shaft_r:
                paint(index, name)
                painted += 1
                continue
        has_arm = any(
            g.weight > 1e-4
            for g in vert.groups
            if any(ag.index == g.group for ag in arm_groups)
        )
        if has_arm and (world - chest_world).length < 0.22:
            for group in arm_groups:
                group.remove([index])
            if "Chest" in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups["Chest"].add([index], 1.0, "ADD")
            stripped += 1
    print("BIND_ARM_ISOLATE", "painted", painted, "stripped", stripped)


# Heat-weight each part alone unless a voxel remesh will fuse them
# afterwards (that wipes vertex groups).
arm = None
if voxel <= 1e-9:
    arm = import_rig()
    for mesh in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        mesh.select_set(True)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        leaf = mesh.name.lower()
        named = any(token in leaf for token in ("head", "hand", "foot", "feet", "neck"))
        weighted = sum(1 for v in mesh.data.vertices if v.groups)
        if named or weighted == 0:
            tag = name_bone_weights(mesh)
            print("BIND_PART_WEIGHTS", mesh.name, "named", tag, len(mesh.data.vertices))
        else:
            print(
                "BIND_PART_WEIGHTS",
                mesh.name,
                "auto",
                weighted,
                "of",
                len(mesh.data.vertices),
            )

bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
body.name = name

(xmin, xmax), (ymin, ymax), (zmin, zmax), n = bbox(body)
span = max(zmax - zmin, 0.001)
if height > 0:
    s = height / span
    body.scale = (s, s, s)
    apply_all(body)
    (xmin, xmax), (ymin, ymax), (zmin, zmax), n = bbox(body)
body.location.x -= (xmin + xmax) / 2.0
body.location.y -= (ymin + ymax) / 2.0
body.location.z -= zmin
apply_all(body)
print("BIND_GROUNDED", n, bbox(body))

if abs(stretch_x - 1.0) > 1e-9 or abs(stretch_y - 1.0) > 1e-9 or abs(stretch_z - 1.0) > 1e-9:
    body.scale.x *= stretch_x
    body.scale.y *= stretch_y
    body.scale.z *= stretch_z
    apply_all(body)
if abs(warp) > 1e-6:
    (xmin, xmax), (ymin, ymax), (zmin, zmax), _n = bbox(body)
    span_y = max(ymax - ymin, 0.001)
    for v in body.data.vertices:
        t = (v.co.y - ymin) / span_y
        v.co.z += warp * math.sin(t * math.pi)
        v.co.x += warp * 0.35 * math.sin(t * math.pi * 2.0)
    body.data.update()
    print("BIND_WARP", warp)
if abs(displace) > 1e-6:
    disp = body.modifiers.new("Displace", "DISPLACE")
    disp.strength = displace
    disp.mid_level = 0.5
    bpy.ops.object.modifier_apply(modifier="Displace")
if decimate < 0.999:
    dec = body.modifiers.new("Decimate", "DECIMATE")
    dec.ratio = decimate
    bpy.ops.object.modifier_apply(modifier="Decimate")
if solidify > 0:
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    solid = body.modifiers.new("Solidify", "SOLIDIFY")
    solid.thickness = solidify
    solid.offset = 0.0
    solid.use_rim = True
    bpy.ops.object.modifier_apply(modifier="Solidify")
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    print("BIND_SOLIDIFY", solidify)
if double_sided:
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.duplicate()
    flipped = bpy.context.view_layer.objects.active
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.flip_normals()
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    flipped.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active
    print("BIND_DOUBLE_SIDED", len(body.data.vertices))

if voxel > 1e-9:
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    rem = body.modifiers.new("Voxel", "REMESH")
    rem.mode = "VOXEL"
    rem.voxel_size = voxel
    bpy.ops.object.modifier_apply(modifier="Voxel")
    print("BIND_VOXEL", voxel, len(body.data.vertices))
    arm = import_rig()
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    weighted = sum(1 for v in body.data.vertices if v.groups)
    print("BIND_PART_WEIGHTS", body.name, "auto", weighted, "of", len(body.data.vertices))

if arm is not None:
    isolate_torso_from_legs(body, arm)
    isolate_chest_from_arms(body, arm)

hide = bpy.data.materials.new("Hide")
body.data.materials.clear()
body.data.materials.append(hide)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.reset()
bpy.ops.object.mode_set(mode="OBJECT")
weighted = sum(1 for v in body.data.vertices if v.groups)
print(
    "BIND_SKIN",
    body.name,
    "vgroups",
    len(body.vertex_groups),
    "weighted",
    weighted,
    "of",
    len(body.data.vertices),
    "mods",
    [m.type for m in body.modifiers],
    "parent",
    None if body.parent is None else body.parent.name,
)

bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=out_glb,
    export_format="GLB",
    use_selection=True,
    export_animations=False,
    export_skins=True,
    export_all_influences=False,
    # Applying the Armature modifier here bakes the bind pose and
    # drops `skins`. Stretch/displace/decimate/solidify are already
    # applied as mesh modifiers before the rig is parented.
    export_apply=False,
    export_armature_object_remove=False,
)
print("BIND_WROTE", out_glb, "verts", len(body.data.vertices))
"""


def promote_root(path: Path) -> None:
    """Lift `Root` to the glTF scene root and parent the mesh to it.

    Blender's exporter wraps bones under the armature object, so clip paths
    `Root/Prosoma/...` miss every bone until the wrapper is gone.
    """
    data = path.read_bytes()
    chunk_len = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20 : 20 + chunk_len])
    nodes = doc["nodes"]
    print("BIND_GLTF_SKINS", len(doc.get("skins") or []), "nodes", len(nodes))
    try:
        root_i = next(i for i, node in enumerate(nodes) if node.get("name") == "Root")
        mesh_i = next(i for i, node in enumerate(nodes) if "mesh" in node)
    except StopIteration as exc:
        raise SystemExit(f"ERROR: {path.name} has no Root bone or no mesh after bind") from exc
    joint_set: set[int] = set()
    for skin in doc.get("skins") or []:
        joint_set.update(skin["joints"])
    for node in nodes:
        children = [c for c in node.get("children") or [] if c not in (mesh_i, root_i)]
        if children:
            node["children"] = children
        else:
            node.pop("children", None)
    root_children = list(nodes[root_i].get("children") or [])
    if mesh_i not in root_children:
        root_children.append(mesh_i)
    nodes[root_i]["children"] = root_children
    keep = set(joint_set) | {root_i, mesh_i}
    old_to_new = {old: new for new, old in enumerate(sorted(keep))}
    new_nodes = []
    for old in sorted(keep):
        node = dict(nodes[old])
        if "children" in node:
            node["children"] = [old_to_new[c] for c in node["children"] if c in old_to_new]
            if not node["children"]:
                node.pop("children", None)
        new_nodes.append(node)
    new_root = old_to_new[root_i]
    parented: set[int] = set()
    for node in new_nodes:
        parented.update(node.get("children") or [])
    orphans = [i for i in range(len(new_nodes)) if i != new_root and i not in parented]
    if orphans:
        children = list(new_nodes[new_root].get("children") or [])
        children.extend(orphans)
        new_nodes[new_root]["children"] = children
    doc["nodes"] = new_nodes
    doc["scenes"][0]["nodes"] = [new_root]
    for skin in doc.get("skins") or []:
        skin["joints"] = [old_to_new[j] for j in skin["joints"]]
        skin["skeleton"] = new_root
    new_json = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    new_json += b" " * ((4 - len(new_json) % 4) % 4)
    rest = data[20 + chunk_len :]
    version = struct.unpack_from("<I", data, 4)[0]
    header_len = 12 + 8 + len(new_json) + len(rest)
    out = GLB_MAGIC + struct.pack("<II", version, header_len)
    out += struct.pack("<II", len(new_json), JSON_CHUNK) + new_json
    out += rest
    path.write_bytes(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "EXAMPLES\n"
            "  shamway generate bind spider.glb --rig arachnid --height 0.42"
            " --solidify 0.012 out.glb\n"
            "  shamway generate bind body.obj --extra head.obj --rig humanoid"
            " --head-lift --neck --anim out.glb\n"
        ),
    )
    parser.add_argument("source", type=Path, help="authored mesh (.glb, .gltf, .obj)")
    parser.add_argument("output", type=Path, help="destination skinned .glb")
    parser.add_argument(
        "--rig",
        default="humanoid",
        help="shipped rig name or a .json rig spec (default: humanoid)",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="MESH",
        help="additional mesh to join before binding; repeatable",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=0.0,
        help="uniform height in metres after import; 0 keeps the source size",
    )
    parser.add_argument(
        "--stretch-x",
        type=float,
        default=1.0,
        help="width stretch after grounding (1.0 = none)",
    )
    parser.add_argument(
        "--stretch-y",
        type=float,
        default=1.0,
        help="length stretch after grounding (Blender Y after import)",
    )
    parser.add_argument(
        "--stretch-z",
        type=float,
        default=1.0,
        help="height stretch after grounding (Blender Z after import)",
    )
    parser.add_argument(
        "--warp",
        type=float,
        default=0.0,
        help="deterministic sine warp along length (metres of back-arch / S-curve)",
    )
    parser.add_argument(
        "--double-sided",
        action="store_true",
        help="duplicate the mesh with flipped normals so Unlit back-face cull cannot punch holes",
    )
    parser.add_argument("--displace", type=float, default=0.0, help="displace strength")
    parser.add_argument(
        "--decimate",
        type=float,
        default=1.0,
        help="decimate ratio in (0, 1]; 1.0 keeps every vertex",
    )
    parser.add_argument(
        "--solidify",
        type=float,
        default=0.0,
        help="even shell thickness in metres for open surfaces; 0 skips",
    )
    parser.add_argument(
        "--head-lift",
        action="store_true",
        help="lift a *head* part so its lowest vertex sits on the body's max Z",
    )
    parser.add_argument(
        "--neck",
        nargs="?",
        const=0.04,
        default=0.0,
        type=float,
        metavar="M",
        help=(
            "fill a neck cylinder of this height in metres (0.04 when the flag "
            "is present with no value) and lift the head onto it"
        ),
    )
    parser.add_argument(
        "--voxel",
        type=float,
        default=0.0,
        help="voxel remesh size in metres after join (0 skips); fuses overlapping meshes",
    )
    parser.add_argument("--name", default="Bound", help="joined mesh name")
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="uniform size factor on the rig (same as generate rig --scale)",
    )
    parser.add_argument(
        "--anim",
        action="store_true",
        help="write sibling {stem}.anim.json (Idle1+Walk on this rig)",
    )
    args = parser.parse_args(argv)

    sources = [args.source, *(Path(item) for item in args.extra)]
    for source in sources:
        if not source.is_file():
            print(f"ERROR: no mesh at {source}", file=sys.stderr)
            return 1
        if source.suffix.lower() not in MESH_SUFFIXES:
            print(
                f"ERROR: {source.name} is not .glb/.gltf/.obj",
                file=sys.stderr,
            )
            return 1
    if args.output.suffix.lower() != ".glb":
        print("ERROR: the bound mesh must be written as .glb", file=sys.stderr)
        return 1
    if args.height < 0:
        print("ERROR: --height must be >= 0", file=sys.stderr)
        return 1
    if args.stretch_x <= 0 or args.stretch_y <= 0 or args.stretch_z <= 0:
        print("ERROR: every --stretch-* must be positive", file=sys.stderr)
        return 1
    if not 0.0 < args.decimate <= 1.0:
        print("ERROR: --decimate must be in (0, 1]", file=sys.stderr)
        return 1
    if args.solidify < 0:
        print("ERROR: --solidify must be >= 0", file=sys.stderr)
        return 1
    if args.neck < 0:
        print("ERROR: --neck must be >= 0", file=sys.stderr)
        return 1
    if args.voxel < 0:
        print("ERROR: --voxel must be >= 0", file=sys.stderr)
        return 1
    try:
        rig = load_rig(args.rig)
        if args.scale is not None:
            rig = scaled(rig, args.scale)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    blender = shutil.which("blender")
    if not blender:
        print(
            "ERROR: blender is not on PATH. Run scripts/install-tools.sh --with-authoring.",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with scratch_dir("bind-") as directory:
        script = directory / "bind.py"
        script.write_text(BLENDER_SCRIPT, encoding="utf-8")
        rig_glb = directory / "rig.glb"
        rig_glb.write_bytes(rig_to_glb(rig))
        staged = directory / "out.glb"
        try:
            result = subprocess.run(
                [
                    blender,
                    "--background",
                    "--factory-startup",
                    "--python",
                    str(script),
                    "--",
                    str(rig_glb),
                    str(staged),
                    args.name,
                    str(args.height),
                    str(args.stretch_x),
                    str(args.stretch_y),
                    str(args.stretch_z),
                    str(args.displace),
                    str(args.decimate),
                    str(args.solidify),
                    str(args.warp),
                    "1" if args.head_lift else "0",
                    "1" if args.double_sided else "0",
                    str(args.neck),
                    str(args.voxel),
                    *(str(source.resolve()) for source in sources),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=BLENDER_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            print(
                f"ERROR: Blender did not finish within {BLENDER_TIMEOUT}s and was killed; "
                "a wedged headless start is the usual cause.",
                file=sys.stderr,
            )
            return 1
        if result.returncode != 0 or not staged.is_file():
            print(result.stdout, file=sys.stderr)
            print(f"ERROR: Blender exited {result.returncode} without binding", file=sys.stderr)
            return 1
        promote_root(staged)
        shutil.move(str(staged), args.output)

    if args.anim:
        with scratch_dir("bind-anim-") as directory:
            dummy = directory / f"{args.output.stem}.glb"
            code = entity_gen.main([str(dummy), "--rig", args.rig, "--anim", "idle,head,walk"])
            if code:
                return int(code)
            anim = dummy.with_suffix(".anim.json")
            if not anim.is_file():
                print("ERROR: generate entity wrote no sibling .anim.json", file=sys.stderr)
                return 1
            shutil.copy2(anim, args.output.with_suffix(".anim.json"))

    for line in result.stdout.splitlines():
        if line.startswith("BIND_"):
            print(line)
    print(f"wrote {args.output} (rig {rig.name!r})")
    hide = args.output.with_name(args.output.stem + "_albedo.png")
    print(f"next:     shamway generate hide {hide}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
