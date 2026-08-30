#!/usr/bin/env python3
"""Generate a skinned entity: primitive parts bound to a rig, plus the XML.

This is the "fully generated" end of the entity lane. A mod that wants a
custom in-game creature without modelling one hands this generator a rig
(`--rig humanoid` is the shipped template) and a part set; it skins
procedural primitives to the rig and writes a GLB the bundle writer turns
into a `SkinnedMeshRenderer` with a named bone hierarchy — the same lane a
Blender-skinning author reaches through `shamway generate rig`.

    shamway generate entity myCreature.glb --rig humanoid
    shamway generate entity myCreature.glb --rig humanoid \
        --mod MyMod --bundle myMod --xml myCreature-entityclasses.xml

With `--xml`, the generator also writes the `entityclasses.xml` patch that
makes the engine spawn the entity. The wiring is the engine's own, verified
from the installed build's IL (recorded in `docs/research/research-provenance.md`):

- every entity class needs a **`Prefab`** property — missing or empty it is
  a hard error ("Mandatory property 'prefab' missing in entity_class …");
- the model the player sees is the **`Mesh`** property;
- both load through `LoadManager.LoadAsset<GameObject>` with the same
  `#@modfolder(Mod):Resources/bundle.unity3d?stem` bundle-URI resolution a
  `Meshfile` uses, so a prefab in a mod's own bundle serves both.

The generated patch names both properties after the same bundle prefab:

    <append xpath="/entity_classes">
      <entity_class name="myCreature">
        <property name="Prefab" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
        <property name="Mesh" value="#@modfolder(MyMod):Resources/myMod.unity3d?myCreature"/>
      </entity_class>
    </append>

What the fragment deliberately leaves out — `PhysicsBody`, `MaxHealth`,
`sounds`, `MoveSpeed`, AI, loot — is mod-specific and belongs in the mod's
own XML. A class with only the two model properties loads, spawns from the
debug menu, and stands in its authored pose: it has no animation (clips are
the editor-owned lane) and no physics body until the mod adds one. And a
custom entity class on a *dedicated* server gets a negative id and renders
nothing on clients in this build — record the caveat and test on a
client-hosted game; `docs/authoring/entities.md` has the details.

Parts are rigid: every vertex of a part binds 1.0 to its bone. At the bind
pose that is exactly the authored pose, and a skeleton posing later would
shear the seams between parts — smooth blends are a per-part choice, and the
generated GLB is a normal skinned mesh a mod can re-skin or replace.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

from ..atomic import write
from ..errors import PipelineError
from ..rigs import Rig, glb_bytes, load_rig, mat_inverse, scaled, world_matrices


def _arachnid_leg_parts() -> dict[str, dict[str, Any]]:
    """The 24 leg segments of the arachnid rig, as one part per joint.

    A spider is legs; the two body spheres alone would read as a floating
    sac. Each leg is three tapering cylinders, thin enough to read as
    limbs against the prosoma and abdomen.
    """
    parts: dict[str, dict[str, Any]] = {}
    for side in ("Left", "Right"):
        for index in range(1, 5):
            parts[f"{side}Leg{index}Upper"] = {"shape": "cylinder", "radius": 0.016, "height": 0.16}
            parts[f"{side}Leg{index}Middle"] = {
                "shape": "cylinder",
                "radius": 0.013,
                "height": 0.14,
            }
            parts[f"{side}Leg{index}Lower"] = {"shape": "cylinder", "radius": 0.01, "height": 0.12}
    return parts


# Default part sets, keyed by the rig they were authored for: one primitive
# per joint, in that joint's local space. The joint sits at the primitive's
# centre; cylinders run along the local Y. A rig without its own entry gets
# no default parts (pass `--parts`), and a size variant (a rig whose `scale`
# is not 1) takes its base rig's set scaled with it.
PARTS_BY_RIG: dict[str, dict[str, Any]] = {
    "humanoid": {
        "Hips": {"shape": "cylinder", "radius": 0.17, "height": 0.2},
        "Spine": {"shape": "cylinder", "radius": 0.15, "height": 0.17},
        "Chest": {"shape": "cylinder", "radius": 0.16, "height": 0.2},
        "Neck": {"shape": "cylinder", "radius": 0.05, "height": 0.07},
        "Head": {"shape": "sphere", "radius": 0.11},
        "LeftShoulder": {"shape": "sphere", "radius": 0.06},
        "RightShoulder": {"shape": "sphere", "radius": 0.06},
        "LeftArm": {"shape": "cylinder", "radius": 0.055, "height": 0.21},
        "RightArm": {"shape": "cylinder", "radius": 0.055, "height": 0.21},
        "LeftForearm": {"shape": "cylinder", "radius": 0.05, "height": 0.21},
        "RightForearm": {"shape": "cylinder", "radius": 0.05, "height": 0.21},
        "LeftHand": {"shape": "box", "width": 0.09, "depth": 0.05, "height": 0.12},
        "RightHand": {"shape": "box", "width": 0.09, "depth": 0.05, "height": 0.12},
        "LeftThigh": {"shape": "cylinder", "radius": 0.08, "height": 0.25},
        "RightThigh": {"shape": "cylinder", "radius": 0.08, "height": 0.25},
        "LeftShin": {"shape": "cylinder", "radius": 0.06, "height": 0.41},
        "RightShin": {"shape": "cylinder", "radius": 0.06, "height": 0.41},
        "LeftFoot": {"shape": "box", "width": 0.09, "depth": 0.24, "height": 0.07},
        "RightFoot": {"shape": "box", "width": 0.09, "depth": 0.24, "height": 0.07},
    },
    "quadruped": {
        "Pelvis": {"shape": "cylinder", "radius": 0.14, "height": 0.24},
        "Spine": {"shape": "cylinder", "radius": 0.13, "height": 0.13},
        "Chest": {"shape": "cylinder", "radius": 0.14, "height": 0.15},
        "Neck": {"shape": "cylinder", "radius": 0.05, "height": 0.24},
        "Head": {"shape": "sphere", "radius": 0.075},
        "Tail": {"shape": "cylinder", "radius": 0.025, "height": 0.16},
        "LeftFrontUpper": {"shape": "cylinder", "radius": 0.045, "height": 0.36},
        "LeftFrontLower": {"shape": "cylinder", "radius": 0.04, "height": 0.34},
        "LeftFrontPaw": {"shape": "box", "width": 0.07, "depth": 0.1, "height": 0.045},
        "RightFrontUpper": {"shape": "cylinder", "radius": 0.045, "height": 0.36},
        "RightFrontLower": {"shape": "cylinder", "radius": 0.04, "height": 0.34},
        "RightFrontPaw": {"shape": "box", "width": 0.07, "depth": 0.1, "height": 0.045},
        "LeftRearUpper": {"shape": "cylinder", "radius": 0.055, "height": 0.28},
        "LeftRearLower": {"shape": "cylinder", "radius": 0.045, "height": 0.27},
        "LeftRearPaw": {"shape": "box", "width": 0.08, "depth": 0.12, "height": 0.05},
        "RightRearUpper": {"shape": "cylinder", "radius": 0.055, "height": 0.28},
        "RightRearLower": {"shape": "cylinder", "radius": 0.045, "height": 0.27},
        "RightRearPaw": {"shape": "box", "width": 0.08, "depth": 0.12, "height": 0.05},
    },
    "bird": {
        "Pelvis": {"shape": "cylinder", "radius": 0.09, "height": 0.12},
        "Spine": {"shape": "cylinder", "radius": 0.08, "height": 0.08},
        "Chest": {"shape": "cylinder", "radius": 0.09, "height": 0.1},
        "Neck": {"shape": "cylinder", "radius": 0.03, "height": 0.22},
        "Head": {"shape": "sphere", "radius": 0.05},
        "Tail": {"shape": "cylinder", "radius": 0.02, "height": 0.18},
        "LeftWingUpper": {"shape": "box", "width": 0.16, "depth": 0.04, "height": 0.03},
        "LeftWingLower": {"shape": "box", "width": 0.16, "depth": 0.04, "height": 0.025},
        "LeftWingTip": {"shape": "box", "width": 0.14, "depth": 0.03, "height": 0.02},
        "RightWingUpper": {"shape": "box", "width": 0.16, "depth": 0.04, "height": 0.03},
        "RightWingLower": {"shape": "box", "width": 0.16, "depth": 0.04, "height": 0.025},
        "RightWingTip": {"shape": "box", "width": 0.14, "depth": 0.03, "height": 0.02},
        "LeftLegUpper": {"shape": "cylinder", "radius": 0.02, "height": 0.16},
        "LeftLegLower": {"shape": "cylinder", "radius": 0.018, "height": 0.12},
        "LeftFoot": {"shape": "box", "width": 0.06, "depth": 0.07, "height": 0.02},
        "RightLegUpper": {"shape": "cylinder", "radius": 0.02, "height": 0.16},
        "RightLegLower": {"shape": "cylinder", "radius": 0.018, "height": 0.12},
        "RightFoot": {"shape": "box", "width": 0.06, "depth": 0.07, "height": 0.02},
    },
    "dinosaur": {
        "Pelvis": {"shape": "cylinder", "radius": 0.3, "height": 0.45},
        "Spine": {"shape": "cylinder", "radius": 0.25, "height": 0.4},
        "Chest": {"shape": "cylinder", "radius": 0.22, "height": 0.35},
        "Neck": {"shape": "cylinder", "radius": 0.12, "height": 0.5},
        "Head": {"shape": "sphere", "radius": 0.13},
        "Tail1": {"shape": "cylinder", "radius": 0.15, "height": 0.6},
        "Tail2": {"shape": "cylinder", "radius": 0.09, "height": 0.55},
        "Tail3": {"shape": "cylinder", "radius": 0.05, "height": 0.5},
        "LeftThigh": {"shape": "cylinder", "radius": 0.14, "height": 0.55},
        "LeftShin": {"shape": "cylinder", "radius": 0.1, "height": 0.75},
        "LeftFoot": {"shape": "box", "width": 0.22, "depth": 0.45, "height": 0.1},
        "RightThigh": {"shape": "cylinder", "radius": 0.14, "height": 0.55},
        "RightShin": {"shape": "cylinder", "radius": 0.1, "height": 0.75},
        "RightFoot": {"shape": "box", "width": 0.22, "depth": 0.45, "height": 0.1},
        "LeftArm": {"shape": "cylinder", "radius": 0.05, "height": 0.32},
        "LeftForearm": {"shape": "cylinder", "radius": 0.04, "height": 0.25},
        "RightArm": {"shape": "cylinder", "radius": 0.05, "height": 0.32},
        "RightForearm": {"shape": "cylinder", "radius": 0.04, "height": 0.25},
    },
    "arachnid": {
        "Prosoma": {"shape": "sphere", "radius": 0.16},
        "Abdomen": {"shape": "sphere", "radius": 0.2},
        "LeftPedipalp": {"shape": "cylinder", "radius": 0.015, "height": 0.12},
        "RightPedipalp": {"shape": "cylinder", "radius": 0.015, "height": 0.12},
        **_arachnid_leg_parts(),
    },
    "crocodile": {
        "Pelvis": {"shape": "cylinder", "radius": 0.16, "height": 0.25},
        "Spine1": {"shape": "cylinder", "radius": 0.15, "height": 0.3},
        "Spine2": {"shape": "cylinder", "radius": 0.14, "height": 0.32},
        "Chest": {"shape": "cylinder", "radius": 0.13, "height": 0.34},
        "Neck": {"shape": "cylinder", "radius": 0.07, "height": 0.32},
        "Head": {"shape": "cylinder", "radius": 0.06, "height": 0.4},
        "Tail1": {"shape": "cylinder", "radius": 0.09, "height": 0.4},
        "Tail2": {"shape": "cylinder", "radius": 0.06, "height": 0.42},
        "Tail3": {"shape": "cylinder", "radius": 0.035, "height": 0.4},
        "LeftFrontUpper": {"shape": "cylinder", "radius": 0.035, "height": 0.24},
        "LeftFrontLower": {"shape": "cylinder", "radius": 0.028, "height": 0.2},
        "LeftFrontFoot": {"shape": "box", "width": 0.06, "depth": 0.1, "height": 0.03},
        "RightFrontUpper": {"shape": "cylinder", "radius": 0.035, "height": 0.24},
        "RightFrontLower": {"shape": "cylinder", "radius": 0.028, "height": 0.2},
        "RightFrontFoot": {"shape": "box", "width": 0.06, "depth": 0.1, "height": 0.03},
        "LeftRearUpper": {"shape": "cylinder", "radius": 0.04, "height": 0.2},
        "LeftRearLower": {"shape": "cylinder", "radius": 0.03, "height": 0.18},
        "LeftRearFoot": {"shape": "box", "width": 0.06, "depth": 0.1, "height": 0.03},
        "RightRearUpper": {"shape": "cylinder", "radius": 0.04, "height": 0.2},
        "RightRearLower": {"shape": "cylinder", "radius": 0.03, "height": 0.18},
        "RightRearFoot": {"shape": "box", "width": 0.06, "depth": 0.1, "height": 0.03},
    },
}

_SEGMENTS = 20


def default_parts_for(rig: Rig) -> dict[str, dict[str, Any]]:
    """The default part set for `rig`, scaled with the rig.

    Size variants (``quadruped-small`` and friends) are the base rig's bones
    at another scale, so they take the base rig's part set; a rig with no
    authored set gets none, and a mod passes `--parts` instead.
    """
    source = PARTS_BY_RIG.get(rig.name) or PARTS_BY_RIG.get(rig.name.rsplit("-", 1)[0])
    if source is None:
        return {}
    return scale_parts(source, rig.scale)


def scale_parts(parts: dict[str, dict[str, Any]], factor: float) -> dict[str, dict[str, Any]]:
    """A copy of `parts` with every dimension multiplied by `factor`.

    `shape` is left alone; every numeric key (radius, height, width, depth)
    scales, so a part set authored for the base rig stays proportioned to a
    size variant's bones.
    """
    if factor == 1.0:
        return {name: dict(part) for name, part in parts.items()}
    return {
        name: {
            key: value * factor if key != "shape" and isinstance(value, (int, float)) else value
            for key, value in part.items()
        }
        for name, part in parts.items()
    }


def load_parts(spec: str | None, rig: Rig) -> dict[str, dict[str, Any]]:
    """The part set a `--parts` argument means: the rig's default, or a JSON file.

    A parts file maps bone names to primitives:

        {"parts": {
            "Head": {"shape": "sphere", "radius": 0.12},
            "LeftArm": {"shape": "cylinder", "radius": 0.06, "height": 0.22}
        }}

    Every named bone must exist in the rig; bones without a part simply get
    none (they are still joints, and the engine's bone chain does not need
    geometry on every link). A custom spec is scaled with the rig exactly
    like the defaults.
    """
    if spec is None:
        defaults = default_parts_for(rig)
        if not defaults:
            raise PipelineError(
                f"rig {rig.name!r} has no default part set; pass --parts with a JSON file"
            )
        return defaults
    path = Path(spec)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PipelineError(f"parts spec {path} does not exist") from None
    except json.JSONDecodeError as exc:
        raise PipelineError(f"parts spec {path} is not valid JSON: {exc}") from None
    raw = document.get("parts") if isinstance(document, dict) else None
    if not isinstance(raw, dict) or not raw:
        raise PipelineError(f'parts spec {path} needs a non-empty "parts" object')
    parts: dict[str, dict[str, Any]] = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise PipelineError(f"parts spec {path} part {name!r} is not an object")
        shape = item.get("shape")
        if shape not in ("cylinder", "sphere", "box"):
            raise PipelineError(
                f"parts spec {path} part {name!r} shape must be cylinder, sphere or box"
            )
        for key, value in item.items():
            if key != "shape" and (not isinstance(value, (int, float)) or value <= 0):
                raise PipelineError(f"parts spec {path} part {name!r} {key!r} must be positive")
        parts[name] = dict(item)
    return scale_parts(parts, rig.scale)


def build_entity_glb(rig: Rig, parts: dict[str, dict[str, Any]], name: str) -> bytes:
    """The skinned entity GLB: rig joints plus one skinned mesh node.

    Part geometry is authored in each joint's local space and transformed by
    that joint's world matrix, so the mesh sits in the bind pose exactly as
    the rig describes. Every vertex binds 1.0 to its part's joint.
    """
    unknown = sorted(set(parts) - {bone.name for bone in rig.bones})
    if unknown:
        raise PipelineError(f"parts name bones that are not in the rig: {', '.join(unknown)}")
    world = world_matrices(rig)
    index_by_name = {bone.name: index for index, bone in enumerate(rig.bones)}

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    joints: list[tuple[int, int, int, int]] = []
    weights: list[tuple[float, float, float, float]] = []
    indices: list[tuple[int, int, int]] = []

    for bone in rig.bones:
        part = parts.get(bone.name)
        if part is None:
            continue
        base = len(positions)
        local_pos, local_norm, local_uv, part_indices = _primitive(part["shape"], part)
        matrix = world[index_by_name[bone.name]]
        for local, normal, uv in zip(local_pos, local_norm, local_uv, strict=True):
            positions.append(_apply_matrix(matrix, local))
            normals.append(_apply_rotation(matrix, normal))
            uvs.append(uv)
            joints.append((index_by_name[bone.name], 0, 0, 0))
            weights.append((1.0, 0.0, 0.0, 0.0))
        for triangle in part_indices:
            indices.append((base + triangle[0], base + triangle[1], base + triangle[2]))

    blob = bytearray()
    views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    mesh = {
        "name": name,
        "primitives": [
            {
                "attributes": {
                    "POSITION": _append_view(
                        blob, views, accessors, positions, "<3f", 5126, "VEC3"
                    ),
                    "NORMAL": _append_view(blob, views, accessors, normals, "<3f", 5126, "VEC3"),
                    "TEXCOORD_0": _append_view(blob, views, accessors, uvs, "<2f", 5126, "VEC2"),
                    "JOINTS_0": _append_view(blob, views, accessors, joints, "<4B", 5121, "VEC4"),
                    "WEIGHTS_0": _append_view(blob, views, accessors, weights, "<4f", 5126, "VEC4"),
                },
                "indices": _append_view(blob, views, accessors, indices, "<3H", 5123, "SCALAR"),
            }
        ],
    }

    # Joint nodes, in rig order, then the skinned mesh node as a sibling root.
    nodes: list[dict[str, Any]] = []
    for bone in rig.bones:
        node: dict[str, Any] = {"name": bone.name}
        if bone.pos != (0.0, 0.0, 0.0):
            node["translation"] = list(bone.pos)
        if bone.rot != (0.0, 0.0, 0.0, 1.0):
            node["rotation"] = list(bone.rot)
        children = [
            index_by_name[candidate.name]
            for candidate in rig.bones
            if candidate.parent == bone.name
        ]
        if children:
            node["children"] = children
        nodes.append(node)
    # The skinned mesh node hangs off the root joint, named `body` — the same
    # convention the writer's own skinned fixtures use. It must not take the
    # file stem: that is the prefab root's name, and the writer refuses a node
    # that collides with it.
    mesh_node_index = len(nodes)
    nodes[0].setdefault("children", []).append(mesh_node_index)
    nodes.append({"name": "body", "mesh": 0, "skin": 0})

    ibm = [mat_inverse(matrix) for matrix in world]
    ibm_accessor = _append_view(blob, views, accessors, ibm, "<16f", 5126, "MAT4")
    root_index = index_by_name[rig.root().name]
    document = {
        "asset": {"version": "2.0", "generator": "shamway"},
        "scene": 0,
        "scenes": [{"nodes": [root_index]}],
        "nodes": nodes,
        "meshes": [mesh],
        "skins": [
            {
                "name": rig.name,
                "joints": list(range(len(rig.bones))),
                "skeleton": root_index,
                "inverseBindMatrices": ibm_accessor,
            }
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    return glb_bytes(document, bytes(blob))


def entity_xml(entity_name: str, mod: str, bundle: str, stem: str) -> str:
    """The `entityclasses.xml` patch fragment for the generated entity.

    `UserSpawnType` is included because it decides whether the class is
    spawnable at all: the console `spawnentity` command lists only classes
    whose `userSpawnType` is not None (verified from
    `ConsoleCmdSpawnEntity.il.txt` — the enum is `None`/`Console`/`Menu`).
    Without it a generated creature loads but cannot be spawned from the
    console or the debug menu.
    """
    uri = f"#@modfolder({mod}):Resources/{bundle}.unity3d?{stem}"
    return f"""<configs>
\t<append xpath="/entity_classes">
\t\t<entity_class name="{entity_name}">
\t\t\t<property name="Prefab" value="{uri}"/>
\t\t\t<property name="Mesh" value="{uri}"/>
\t\t\t<property name="UserSpawnType" value="Menu"/>
\t\t</entity_class>
\t</append>
</configs>
"""


def _primitive(
    shape: str, spec: dict[str, Any]
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float]],
    list[tuple[int, int, int]],
]:
    """One primitive in local space, centred on the joint, along local +Y."""
    if shape == "cylinder":
        return _cylinder(spec["radius"], spec["height"])
    if shape == "sphere":
        return _sphere(spec["radius"])
    return _box(spec["width"], spec["depth"], spec["height"])


def _cylinder(
    radius: float, height: float
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float]],
    list[tuple[int, int, int]],
]:
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    top = height / 2.0
    bottom = -top
    side_top = []
    side_bottom = []
    for i in range(_SEGMENTS):
        angle = 2.0 * math.pi * i / _SEGMENTS
        x, z = radius * math.cos(angle), radius * math.sin(angle)
        side_top.append(len(positions))
        positions.append((x, top, z))
        normals.append((math.cos(angle), 0.0, math.sin(angle)))
        uvs.append((i / _SEGMENTS, 1.0))
        side_bottom.append(len(positions))
        positions.append((x, bottom, z))
        normals.append((math.cos(angle), 0.0, math.sin(angle)))
        uvs.append((i / _SEGMENTS, 0.0))
    indices: list[tuple[int, int, int]] = []
    for i in range(_SEGMENTS):
        nxt = (i + 1) % _SEGMENTS
        indices.append((side_top[i], side_bottom[i], side_top[nxt]))
        indices.append((side_top[nxt], side_bottom[i], side_bottom[nxt]))
    for center_y, normal_y in ((top, 1.0), (bottom, -1.0)):
        center = len(positions)
        positions.append((0.0, center_y, 0.0))
        normals.append((0.0, normal_y, 0.0))
        uvs.append((0.5, 0.5))
        ring = [center]
        for i in range(_SEGMENTS):
            angle = 2.0 * math.pi * i / _SEGMENTS
            ring.append(len(positions))
            positions.append((radius * math.cos(angle), center_y, radius * math.sin(angle)))
            normals.append((0.0, normal_y, 0.0))
            uvs.append((0.5 + 0.5 * math.cos(angle), 0.5 + 0.5 * math.sin(angle)))
        for i in range(_SEGMENTS):
            nxt = i + 1
            if normal_y > 0:
                indices.append((center, ring[nxt], ring[i]))
            else:
                indices.append((center, ring[i], ring[nxt]))
    return positions, normals, uvs, indices


def _sphere(
    radius: float,
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float]],
    list[tuple[int, int, int]],
]:
    rings = 10
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    grid: list[list[int]] = []
    for ring in range(rings + 1):
        theta = math.pi * ring / rings
        row: list[int] = []
        for segment in range(_SEGMENTS):
            phi = 2.0 * math.pi * segment / _SEGMENTS
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.cos(theta)
            z = radius * math.sin(theta) * math.sin(phi)
            row.append(len(positions))
            positions.append((x, y, z))
            normals.append((x / radius, y / radius, z / radius))
            uvs.append((segment / _SEGMENTS, ring / rings))
        grid.append(row)
    indices: list[tuple[int, int, int]] = []
    for ring in range(rings):
        for segment in range(_SEGMENTS):
            nxt = (segment + 1) % _SEGMENTS
            a, b, c, d = (
                grid[ring][segment],
                grid[ring][nxt],
                grid[ring + 1][nxt],
                grid[ring + 1][segment],
            )
            indices.append((a, b, d))
            indices.append((b, c, d))
    return positions, normals, uvs, indices


def _box(
    width: float, depth: float, height: float
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[tuple[float, float]],
    list[tuple[int, int, int]],
]:
    half = (width / 2.0, height / 2.0, depth / 2.0)
    faces: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = [
        # (normal, corners)
        (
            (0, 1, 0),
            (-half[0], half[1], half[2]),
            (half[0], half[1], half[2]),
            (half[0], half[1], -half[2]),
            (-half[0], half[1], -half[2]),
        ),
        (
            (0, -1, 0),
            (-half[0], -half[1], -half[2]),
            (half[0], -half[1], -half[2]),
            (half[0], -half[1], half[2]),
            (-half[0], -half[1], half[2]),
        ),
        (
            (1, 0, 0),
            (half[0], -half[1], half[2]),
            (half[0], -half[1], -half[2]),
            (half[0], half[1], -half[2]),
            (half[0], half[1], half[2]),
        ),
        (
            (-1, 0, 0),
            (-half[0], -half[1], -half[2]),
            (-half[0], -half[1], half[2]),
            (-half[0], half[1], half[2]),
            (-half[0], half[1], -half[2]),
        ),
        (
            (0, 0, 1),
            (-half[0], -half[1], half[2]),
            (half[0], -half[1], half[2]),
            (half[0], half[1], half[2]),
            (-half[0], half[1], half[2]),
        ),
        (
            (0, 0, -1),
            (half[0], -half[1], -half[2]),
            (-half[0], -half[1], -half[2]),
            (-half[0], half[1], -half[2]),
            (half[0], half[1], -half[2]),
        ),
    ]
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    indices: list[tuple[int, int, int]] = []
    for normal, *corners in faces:
        base = len(positions)
        for corner in corners:
            positions.append(corner)
            normals.append(normal)
        # Whole-face UV, every face the same orientation.
        uvs.extend(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
        a, b, c, d = range(base, base + 4)
        # Wind the quad so its outward normal is the face normal (CCW outside).
        e1 = _sub(positions[b], positions[a])
        e2 = _sub(positions[c], positions[a])
        if _dot(_cross(e1, e2), normal) < 0:
            b, c = c, b
        indices.append((a, b, c))
        indices.append((a, c, d))
    return positions, normals, uvs, indices


def _sub(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _apply_matrix(
    matrix: list[float], value: tuple[float, float, float]
) -> tuple[float, float, float]:
    x, y, z = value
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def _apply_rotation(
    matrix: list[float], value: tuple[float, float, float]
) -> tuple[float, float, float]:
    x, y, z = value
    out = (
        matrix[0] * x + matrix[4] * y + matrix[8] * z,
        matrix[1] * x + matrix[5] * y + matrix[9] * z,
        matrix[2] * x + matrix[6] * y + matrix[10] * z,
    )
    length = math.sqrt(out[0] * out[0] + out[1] * out[1] + out[2] * out[2])
    if length == 0:
        return value
    return (out[0] / length, out[1] / length, out[2] / length)


def _append_view(
    blob: bytearray,
    views: list[dict[str, Any]],
    accessors: list[dict[str, Any]],
    values: list[Any],
    fmt: str,
    component_type: int,
    atype: str,
) -> int:
    """Pack `values` into the blob and register its bufferView and accessor.

    The accessor `count` is the number of elements, but a SCALAR accessor
    counts *scalars*: an index list of N triangles is 3N values, exactly as
    the reader groups them back into triangles.
    """
    offset = len(blob)
    payload = bytearray()
    for value in values:
        payload.extend(struct.pack(fmt, *value))
    blob.extend(payload)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})
    count = len(values) * (3 if atype == "SCALAR" else 1)
    accessors.append(
        {
            "bufferView": len(views) - 1,
            "byteOffset": 0,
            "componentType": component_type,
            "count": count,
            "type": atype,
        }
    )
    return len(accessors) - 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="destination skinned entity .glb")
    parser.add_argument(
        "--rig", default="humanoid", help="rig template name (humanoid) or a .json rig spec"
    )
    parser.add_argument(
        "--parts", default=None, help="path to a parts JSON (default: the rig's own set)"
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=None,
        help="uniform size factor on top of the rig's own scale (e.g. 0.5 halves it)",
    )
    parser.add_argument(
        "--name", default=None, help="entity and prefab name (default: output stem)"
    )
    parser.add_argument("--mod", default=None, help="mod folder name, for the XML URI")
    parser.add_argument("--bundle", default=None, help="bundle file stem, for the XML URI")
    parser.add_argument(
        "--xml", default=None, help="write the entityclasses.xml patch to this path"
    )
    parser.add_argument("--entity-name", default=None, help="entity_class name (default: stem)")
    args = parser.parse_args(argv)

    if args.output.suffix.lower() != ".glb":
        raise SystemExit("ERROR: the entity must be written as .glb")
    if args.xml is not None and (not args.mod or not args.bundle):
        raise SystemExit("ERROR: --xml needs --mod and --bundle to build the bundle URI")
    try:
        rig = load_rig(args.rig)
        if args.scale is not None:
            rig = scaled(rig, args.scale)
        parts = load_parts(args.parts, rig)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    stem = args.output.stem
    name = args.name or stem
    try:
        payload = build_entity_glb(rig, parts, name)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    write(args.output, payload)

    n_parts = sum(1 for bone in rig.bones if bone.name in parts)
    print(f"wrote {args.output}: {len(rig.bones)} bones, {n_parts} parts")
    if args.xml is not None:
        entity_name = args.entity_name or stem
        fragment = entity_xml(entity_name, args.mod, args.bundle, stem)
        write(Path(args.xml), fragment)
        print(
            f"wrote {args.xml}: entity_class {entity_name!r} -> "
            f"#@modfolder({args.mod}):Resources/{args.bundle}.unity3d?{stem}"
        )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
