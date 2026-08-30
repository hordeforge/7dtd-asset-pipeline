"""Rig authoring: a declarative bone structure and its glTF armature.

A rig is the skeleton an entity model skins to: a set of named bones, each
with a parent and a rest-pose position. It is the missing authoring half of
the skinned-mesh lane — the bundle writer turns a glTF *skin* into a
`SkinnedMeshRenderer` with a named bone hierarchy, and a rig is what a modder
skins *against*, either in Blender or procedurally through `shamway generate
entity`.

The bone names in a rig are the mod's choice: they bind within the prefab,
and nothing in the engine requires a particular spelling on a self-contained
entity model. Two cases where names stop being free, recorded in
`docs/research/research-provenance.md`:

- **SDCS gear** rebinds a garment to the *wearer* by name, so a mod that
  wants its entity to wear armor must match the player rig's exact bone
  spellings, read off a live client (`Helpers.RigBoneNames` in 7dtd-playtest)
  — they are not readable offline.
- **TFP animation clips** are keyed to TFP's own rig and cannot be shipped
  anyway (the game's bundles embed their assets same-file), so matching them
  buys nothing until clips are authorable at all.

The spec format is JSON, one bone per entry, positions in metres relative to
the parent bone (local space):

    {
      "name": "myRig",
      "bones": [
        {"name": "Root", "parent": null, "pos": [0, 0, 0]},
        {"name": "Hips", "parent": "Root", "pos": [0, 0.98, 0]},
        {"name": "LeftThigh", "parent": "Hips", "pos": [-0.09, -0.12, 0]}
      ]
    }

`pos` accepts a list `[x, y, z]` or a map `{"x": ..., "y": ..., "z": ...}`.
`rot` (optional) is a quaternion `[x, y, z, w]`; `scale` (optional) a
uniform scalar. Y is up, matching the mesh lane's convention.

`rig_to_glb` emits a glTF 2.0 GLB whose node tree *is* the skeleton and whose
skin carries the inverse bind matrices — the armature a Blender author skins
a mesh onto, and the armature `shamway generate entity` skins primitives to
procedurally. The reader this repository's writer uses (`gltf_scene.py`)
parses that GLB directly.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PipelineError

GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
GLB_VERSION = 2
MAT4_FLOATS = 16

# Where the packaged rig templates live inside the wheel (`data/rigs/*.json`).
RIGS_DIR = Path(__file__).parent / "data" / "rigs"

# A named rig may only come from the packaged set. Everything else must be a
# path the caller owns; a typo'd name must not silently resolve to a template.
NAMED_RIGS = frozenset({"humanoid"})


@dataclass(frozen=True)
class RigBone:
    """One bone of a rig: a name, a parent, and a rest-pose transform.

    `pos` is local to the parent (metres), `rot` a unit quaternion `[x, y, z,
    w]` (identity when omitted), and `scale` a uniform local scale (1 when
    omitted). Y is up.
    """

    name: str
    parent: str | None
    pos: tuple[float, float, float]
    rot: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    scale: float = 1.0


@dataclass(frozen=True)
class Rig:
    """A validated bone structure, in declaration order."""

    name: str
    bones: tuple[RigBone, ...]

    def root(self) -> RigBone:
        """The single bone whose parent is None (every rig has exactly one)."""
        return next(bone for bone in self.bones if bone.parent is None)

    def index(self, name: str) -> int:
        for index, bone in enumerate(self.bones):
            if bone.name == name:
                return index
        raise KeyError(name)


def load_rig(spec: str | Path) -> Rig:
    """Load a rig from a path (``.json``) or a packaged template by name.

    ``humanoid`` resolves to the shipped template; any other string is taken
    as a filesystem path so a mod owns its rigs. The spec is validated the
    moment it loads — a rig with a dangling parent or a cycle is refused
    before any generator touches it.
    """
    path = resolve_rig_spec(spec)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PipelineError(f"rig spec {path} does not exist") from None
    except json.JSONDecodeError as exc:
        raise PipelineError(f"rig spec {path} is not valid JSON: {exc}") from None
    if not isinstance(document, dict):
        raise PipelineError(f"rig spec {path} must be a JSON object")
    name = document.get("name")
    if not isinstance(name, str) or not name:
        raise PipelineError(f'rig spec {path} needs a non-empty string "name"')
    raw_bones = document.get("bones")
    if not isinstance(raw_bones, list) or not raw_bones:
        raise PipelineError(f'rig spec {path} needs a non-empty "bones" array')
    bones: list[RigBone] = []
    for index, item in enumerate(raw_bones):
        if not isinstance(item, dict):
            raise PipelineError(f"rig spec {path} bone {index} is not an object")
        bone_name = item.get("name")
        if not isinstance(bone_name, str) or not bone_name:
            raise PipelineError(f'rig spec {path} bone {index} needs a non-empty string "name"')
        parent = item.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise PipelineError(
                f'rig spec {path} bone {bone_name!r} "parent" must be a string or null'
            )
        bones.append(
            RigBone(
                name=bone_name,
                parent=parent,
                pos=_read_vec3(item, "pos", path, bone_name, default=(0.0, 0.0, 0.0)),
                rot=_read_vec4(item, "rot", path, bone_name, default=(0.0, 0.0, 0.0, 1.0)),
                scale=_read_scale(item, path, bone_name),
            )
        )
    rig = Rig(name=name, bones=tuple(bones))
    validate_rig(rig, source=str(path))
    return rig


def resolve_rig_spec(spec: str | Path) -> Path:
    """The spec file a ``--rig`` argument means: a name or a filesystem path."""
    if isinstance(spec, Path):
        return spec
    if spec in NAMED_RIGS:
        return RIGS_DIR / f"{spec}.json"
    return Path(spec)


def validate_rig(rig: Rig, source: str = "rig") -> None:
    """Refuse a bone structure the generators cannot skin onto.

    Every check names the bone it rejects, so a large spec fails on the first
    actual mistake rather than on a count.
    """
    if not rig.bones:
        raise PipelineError(f"{source} has no bones")
    names = [bone.name for bone in rig.bones]
    if len(set(names)) != len(names):
        for name in names:
            if names.count(name) > 1:
                raise PipelineError(f"{source} has duplicate bone name {name!r}")
    roots = [bone for bone in rig.bones if bone.parent is None]
    if len(roots) != 1:
        raise PipelineError(
            f"{source} must have exactly one root bone (parent null); found {len(roots)}"
        )
    by_name = {bone.name: bone for bone in rig.bones}
    for bone in rig.bones:
        if bone.parent is not None and bone.parent not in by_name:
            raise PipelineError(f"{source} bone {bone.name!r} has unknown parent {bone.parent!r}")
        for value in bone.pos:
            if not math.isfinite(value):
                raise PipelineError(f"{source} bone {bone.name!r} has a non-finite pos")
        if not all(math.isfinite(value) for value in bone.rot):
            raise PipelineError(f"{source} bone {bone.name!r} has a non-finite rot")
        length = math.sqrt(sum(value * value for value in bone.rot))
        if abs(length - 1.0) > 1e-3:
            raise PipelineError(
                f"{source} bone {bone.name!r} rot is not a unit quaternion (length {length:.4f})"
            )
        if not math.isfinite(bone.scale) or bone.scale <= 0:
            raise PipelineError(f"{source} bone {bone.name!r} scale must be a positive number")
    # A parent chain that walks into itself: follow parents from each bone and
    # refuse on a revisit.
    for bone in rig.bones:
        seen: set[str] = set()
        cursor: str | None = bone.name
        while cursor is not None:
            if cursor in seen:
                raise PipelineError(f"{source} has a cyclic parent chain at bone {cursor!r}")
            seen.add(cursor)
            cursor = by_name[cursor].parent


def rig_to_glb(rig: Rig) -> bytes:
    """Serialize a rig as a glTF 2.0 GLB: the joint hierarchy plus a skin.

    Each bone becomes a node carrying its rest-pose TRS; the skin's
    `inverseBindMatrices` are the inverses of the world matrices, so a mesh
    skinned to this armature deforms around the rig exactly as authored. The
    output is the armature a Blender author skins against, or that
    `shamway generate entity` skins primitives to.
    """
    joint_indices = [rig.index(bone.name) for bone in rig.bones]
    world = world_matrices(rig)
    ibm = [mat_inverse(matrix) for matrix in world]
    blob = _mat4_buffer(ibm)
    nodes: list[dict[str, Any]] = []
    index_by_name = {bone.name: index for index, bone in enumerate(rig.bones)}
    for bone in rig.bones:
        node: dict[str, Any] = {"name": bone.name}
        if bone.pos != (0.0, 0.0, 0.0):
            node["translation"] = list(bone.pos)
        if bone.rot != (0.0, 0.0, 0.0, 1.0):
            node["rotation"] = list(bone.rot)
        if bone.scale != 1.0:
            node["scale"] = [bone.scale, bone.scale, bone.scale]
        children = [
            index_by_name[candidate.name]
            for candidate in rig.bones
            if candidate.parent == bone.name
        ]
        if children:
            node["children"] = children
        nodes.append(node)
    root_index = index_by_name[rig.root().name]
    document = {
        "asset": {"version": "2.0", "generator": "shamway"},
        "scene": 0,
        "scenes": [{"nodes": [root_index]}],
        "nodes": nodes,
        "skins": [
            {
                "name": rig.name,
                "joints": joint_indices,
                "skeleton": root_index,
                "inverseBindMatrices": 0,
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(joint_indices),
                "type": "MAT4",
            }
        ],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}],
        "buffers": [{"byteLength": len(blob)}],
    }
    return glb_bytes(document, blob)


def _read_vec3(
    item: dict[str, Any], key: str, path: Path, bone: str, default: tuple[float, float, float]
) -> tuple[float, float, float]:
    value = item.get(key, list(default))
    if isinstance(value, dict):
        value = [value.get(axis) for axis in ("x", "y", "z")]
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(
            isinstance(component, (int, float)) and not isinstance(component, bool)
            for component in value
        )
    ):
        raise PipelineError(
            f"rig spec {path} bone {bone!r} {key!r} must be [x, y, z] or {{x, y, z}}"
        )
    return (float(value[0]), float(value[1]), float(value[2]))


def _read_vec4(
    item: dict[str, Any],
    key: str,
    path: Path,
    bone: str,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    value = item.get(key, list(default))
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(
            isinstance(component, (int, float)) and not isinstance(component, bool)
            for component in value
        )
    ):
        raise PipelineError(
            f"rig spec {path} bone {bone!r} {key!r} must be a quaternion [x, y, z, w]"
        )
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def _read_scale(item: dict[str, Any], path: Path, bone: str) -> float:
    value = item.get("scale", 1.0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PipelineError(f'rig spec {path} bone {bone!r} "scale" must be a number')
    return float(value)


def world_matrices(rig: Rig) -> list[list[float]]:
    """World rest-pose matrices, column-major, parent-concatenated.

    Public because the entity generator skins parts to the rig: vertices are
    authored in a joint's local space and transformed by this matrix to the
    bind pose the skin expects.
    """
    local = {bone.name: _trs_matrix(bone.pos, bone.rot, bone.scale) for bone in rig.bones}
    parent = {bone.name: bone.parent for bone in rig.bones}
    world: dict[str, list[float]] = {}
    for bone in rig.bones:
        chain: list[str] = []
        cursor: str | None = bone.name
        while cursor is not None:
            chain.append(cursor)
            cursor = parent[cursor]
        matrix = _identity4()
        for name in reversed(chain):
            matrix = _mat_mul(matrix, local[name])
        world[bone.name] = matrix
    return [world[bone.name] for bone in rig.bones]


def _trs_matrix(
    translation: tuple[float, float, float],
    rotation: tuple[float, float, float, float],
    scale: float,
) -> list[float]:
    x, y, z, w = rotation
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        (1 - 2 * (yy + zz)) * scale,
        2 * (xy + wz) * scale,
        2 * (xz - wy) * scale,
        0.0,
        2 * (xy - wz) * scale,
        (1 - 2 * (xx + zz)) * scale,
        2 * (yz + wx) * scale,
        0.0,
        2 * (xz + wy) * scale,
        2 * (yz - wx) * scale,
        (1 - 2 * (xx + yy)) * scale,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    ]


def _identity4() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    """`a·b`, both column-major: element (row r, column c) is Σᵢ a[i·4+r]·b[c·4+i].

    Column-major indexing puts element (r, c) at index `c*4 + r`, so (a·b)[r][c]
    reads a[r][i] at `i*4+r` and b[i][c] at `c*4+i`. This is the composition
    order the world-matrix walk needs: `parent · local`.
    """
    out = [0.0] * MAT4_FLOATS
    for column in range(4):
        for row in range(4):
            out[column * 4 + row] = sum(a[i * 4 + row] * b[column * 4 + i] for i in range(4))
    return out


def mat_inverse(matrix: list[float]) -> list[float]:
    """4x4 inverse by Gauss-Jordan on the augmented matrix (column-major in/out).

    The input and output are column-major (element (r, c) at index `c*4 + r`),
    so `work` starts as the true rows, not slices of the flat input.
    """
    work = [[matrix[column * 4 + row] for column in range(4)] for row in range(4)]
    inverse = [[1.0 if row == col else 0.0 for col in range(4)] for row in range(4)]
    for column in range(4):
        pivot = next((row for row in range(column, 4) if abs(work[row][column]) > 1e-12), None)
        if pivot is None:
            raise PipelineError("rig armature has a singular rest-pose matrix")
        if pivot != column:
            work[column], work[pivot] = work[pivot], work[column]
            inverse[column], inverse[pivot] = inverse[pivot], inverse[column]
        factor = work[column][column]
        work[column] = [value / factor for value in work[column]]
        inverse[column] = [value / factor for value in inverse[column]]
        for row in range(4):
            if row == column:
                continue
            scale = work[row][column]
            work[row] = [
                value - scale * other for value, other in zip(work[row], work[column], strict=True)
            ]
            inverse[row] = [
                value - scale * other
                for value, other in zip(inverse[row], inverse[column], strict=True)
            ]
    return [inverse[row][column] for column in range(4) for row in range(4)]


def _mat4_buffer(matrices: list[list[float]]) -> bytes:
    payload = bytearray()
    for matrix in matrices:
        payload.extend(struct.pack("<16f", *matrix))
    return bytes(payload)


def glb_bytes(document: dict[str, Any], blob: bytes) -> bytes:
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_padding = (4 - len(json_bytes) % 4) % 4
    json_bytes += b" " * json_padding
    blob_padding = (4 - len(blob) % 4) % 4
    blob += b"\x00" * blob_padding
    total = 12 + 8 + len(json_bytes) + 8 + len(blob)
    return (
        struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, total)
        + struct.pack("<II", len(json_bytes), JSON_CHUNK)
        + json_bytes
        + struct.pack("<II", len(blob), BIN_CHUNK)
        + blob
    )
