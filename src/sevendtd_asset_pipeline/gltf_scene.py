"""Read a glTF/GLB scene graph, including skins, without going through trimesh.

trimesh's `force="mesh"` path is what the static-mesh lane uses, and it
collapses every node onto one mesh. Hierarchy, joint names, inverse-bind
matrices and per-vertex joints/weights live on the glTF document itself, so
this module reads that document. A source that asks for skinning and cannot
be encoded is refused here rather than flattened to MeshRenderer.
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
_WRAPPER_NAMES = frozenset({"", "Scene", "Root", "root"})
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
COMPONENT_STRUCT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass(frozen=True)
class GltfNode:
    index: int
    name: str
    children: tuple[int, ...]
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    mesh: int | None
    skin: int | None


@dataclass(frozen=True)
class GltfPrimitive:
    positions: tuple[tuple[float, float, float], ...]
    normals: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...] | None
    indices: tuple[tuple[int, int, int], ...]
    joints: tuple[tuple[int, int, int, int], ...] | None
    weights: tuple[tuple[float, float, float, float], ...] | None


@dataclass(frozen=True)
class GltfMesh:
    index: int
    name: str
    primitive: GltfPrimitive


@dataclass(frozen=True)
class GltfSkin:
    index: int
    name: str
    joints: tuple[int, ...]
    skeleton: int | None
    inverse_bind: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class GltfScene:
    source: Path
    nodes: tuple[GltfNode, ...]
    meshes: tuple[GltfMesh, ...]
    skins: tuple[GltfSkin, ...]
    roots: tuple[int, ...]

    def mesh_nodes(self) -> list[GltfNode]:
        return [node for node in self.nodes if node.mesh is not None]

    def has_skin(self) -> bool:
        return bool(self.skins) and any(node.skin is not None for node in self.nodes)

    def needs_hierarchy(self) -> bool:
        """Whether this scene must emit named child GameObjects.

        A single mesh hanging off a wrapper chain (Blender's Scene → Cube)
        stays on today's one-root prefab. A named sibling such as `armedLamp`,
        a second mesh node, or a skin is the opt-in.
        """
        if self.has_skin():
            return True
        mesh_nodes = self.mesh_nodes()
        if len(mesh_nodes) > 1:
            return True
        if not mesh_nodes:
            return any(node.name and node.name not in _WRAPPER_NAMES for node in self.nodes)
        mesh = mesh_nodes[0]
        chain = _ancestor_chain(self, mesh.index)
        for node in self.nodes:
            if node.index in chain:
                if node.index != mesh.index and node.name and node.name not in _WRAPPER_NAMES:
                    return True
                continue
            if node.name or node.mesh is not None or node.children:
                return True
        return False


def parse_gltf(source: Path) -> GltfScene:
    """Load a `.glb` / `.gltf` into a scene graph, refusing a malformed file."""
    try:
        document, blob = _load_document(source)
    except PipelineError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, struct.error, ValueError) as exc:
        raise PipelineError(f"cannot read glTF {source}: {exc}") from exc
    nodes_json = document.get("nodes") or []
    if not isinstance(nodes_json, list):
        raise PipelineError(f"{source.name} has a nodes table that is not a list")
    nodes = tuple(_parse_node(index, item, source) for index, item in enumerate(nodes_json))
    buffers = _load_buffers(document, blob, source)
    meshes = tuple(
        _parse_mesh(index, item, document, buffers, source)
        for index, item in enumerate(document.get("meshes") or [])
    )
    skins = tuple(
        _parse_skin(index, item, document, buffers, source)
        for index, item in enumerate(document.get("skins") or [])
    )
    scene_index = document.get("scene", 0)
    scenes = document.get("scenes") or []
    if not scenes:
        children = {child for node in nodes for child in node.children}
        roots = tuple(index for index in range(len(nodes)) if index not in children)
    else:
        if not isinstance(scene_index, int) or scene_index < 0 or scene_index >= len(scenes):
            raise PipelineError(f"{source.name} names scene {scene_index}, which is not in scenes")
        roots = tuple(int(index) for index in (scenes[scene_index].get("nodes") or []))
    _validate_graph(nodes, meshes, skins, roots, source)
    return GltfScene(source, nodes, meshes, skins, roots)


def _load_document(source: Path) -> tuple[dict[str, Any], bytes]:
    data = source.read_bytes()
    if data[:4] == GLB_MAGIC:
        return _parse_glb(data, source)
    document = json.loads(data.decode("utf-8"))
    if not isinstance(document, dict):
        raise PipelineError(f"{source.name} is not a JSON object")
    return document, b""


def _parse_glb(data: bytes, source: Path) -> tuple[dict[str, Any], bytes]:
    if len(data) < 12:
        raise PipelineError(f"{source.name} is too short to be a GLB")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_MAGIC or version != 2:
        raise PipelineError(f"{source.name} is not a glTF 2.0 GLB")
    if length > len(data):
        raise PipelineError(f"{source.name} declares {length} bytes and contains {len(data)}")
    offset = 12
    document: dict[str, Any] | None = None
    blob = b""
    while offset + 8 <= length:
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_len]
        offset += chunk_len
        if chunk_type == JSON_CHUNK:
            parsed = json.loads(chunk.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise PipelineError(f"{source.name} JSON chunk is not an object")
            document = parsed
        elif chunk_type == BIN_CHUNK:
            blob = chunk
    if document is None:
        raise PipelineError(f"{source.name} has no JSON chunk")
    return document, blob


def _load_buffers(document: dict[str, Any], blob: bytes, source: Path) -> list[bytes]:
    buffers: list[bytes] = []
    for index, item in enumerate(document.get("buffers") or []):
        uri = item.get("uri")
        if not uri:
            buffers.append(blob)
            continue
        if isinstance(uri, str) and uri.startswith("data:"):
            raise PipelineError(
                f"{source.name} buffer {index} uses a data URI; write a GLB or an external .bin"
            )
        path = (source.parent / str(uri)).resolve()
        try:
            buffers.append(path.read_bytes())
        except OSError as exc:
            raise PipelineError(f"{source.name} buffer {index} cannot read {path}: {exc}") from exc
    return buffers


def _parse_node(index: int, item: Any, source: Path) -> GltfNode:
    if not isinstance(item, dict):
        raise PipelineError(f"{source.name} node {index} is not an object")
    children = tuple(int(child) for child in (item.get("children") or []))
    if "matrix" in item:
        translation, rotation, scale = _decompose_matrix(item["matrix"], source, index)
    else:
        translation = _vec3(
            item.get("translation"), (0.0, 0.0, 0.0), source, f"node {index} translation"
        )
        rotation = _vec4(
            item.get("rotation"), (0.0, 0.0, 0.0, 1.0), source, f"node {index} rotation"
        )
        scale = _vec3(item.get("scale"), (1.0, 1.0, 1.0), source, f"node {index} scale")
    mesh = item.get("mesh")
    skin = item.get("skin")
    name = item.get("name")
    if name is None:
        name = ""
    if not isinstance(name, str):
        raise PipelineError(f"{source.name} node {index} name is not a string")
    return GltfNode(
        index=index,
        name=name,
        children=children,
        translation=translation,
        rotation=rotation,
        scale=scale,
        mesh=int(mesh) if mesh is not None else None,
        skin=int(skin) if skin is not None else None,
    )


def _parse_mesh(
    index: int,
    item: Any,
    document: dict[str, Any],
    buffers: list[bytes],
    source: Path,
) -> GltfMesh:
    if not isinstance(item, dict):
        raise PipelineError(f"{source.name} mesh {index} is not an object")
    primitives = item.get("primitives") or []
    if len(primitives) != 1:
        raise PipelineError(
            f"{source.name} mesh {index} has {len(primitives)} primitives; "
            "this writer encodes one primitive per mesh"
        )
    prim = primitives[0]
    attributes = prim.get("attributes") or {}
    if "POSITION" not in attributes:
        raise PipelineError(f"{source.name} mesh {index} has no POSITION attribute")
    positions = _read_vec3_list(document, buffers, attributes["POSITION"], source, "POSITION")
    if "NORMAL" in attributes:
        normals = _read_vec3_list(document, buffers, attributes["NORMAL"], source, "NORMAL")
    else:
        normals = tuple((0.0, 1.0, 0.0) for _ in positions)
    uvs = None
    if "TEXCOORD_0" in attributes:
        uvs = _read_vec2_list(document, buffers, attributes["TEXCOORD_0"], source, "TEXCOORD_0")
        if len(uvs) != len(positions):
            raise PipelineError(
                f"{source.name} mesh {index} TEXCOORD_0 length does not match POSITION"
            )
    if "indices" not in prim:
        raise PipelineError(f"{source.name} mesh {index} has no indices")
    flat = _read_scalars(document, buffers, prim["indices"], source, "indices")
    if len(flat) % 3:
        raise PipelineError(
            f"{source.name} mesh {index} index count {len(flat)} is not a multiple of 3"
        )
    indices = tuple((flat[i], flat[i + 1], flat[i + 2]) for i in range(0, len(flat), 3))
    joints = weights = None
    if "JOINTS_0" in attributes or "WEIGHTS_0" in attributes:
        if "JOINTS_0" not in attributes or "WEIGHTS_0" not in attributes:
            raise PipelineError(
                f"{source.name} mesh {index} has only one of JOINTS_0/WEIGHTS_0; both are required"
            )
        if "JOINTS_1" in attributes or "WEIGHTS_1" in attributes:
            raise PipelineError(
                f"{source.name} mesh {index} declares JOINTS_1/WEIGHTS_1; "
                "this writer encodes at most four influences per vertex"
            )
        joints = _read_vec4_int(document, buffers, attributes["JOINTS_0"], source, "JOINTS_0")
        weights = _read_vec4_float(document, buffers, attributes["WEIGHTS_0"], source, "WEIGHTS_0")
        if len(joints) != len(positions) or len(weights) != len(positions):
            raise PipelineError(
                f"{source.name} mesh {index} skin attribute length does not match POSITION"
            )
    name = item.get("name") or ""
    if not isinstance(name, str):
        name = ""
    return GltfMesh(
        index,
        name,
        GltfPrimitive(positions, normals, uvs, indices, joints, weights),
    )


def _parse_skin(
    index: int,
    item: Any,
    document: dict[str, Any],
    buffers: list[bytes],
    source: Path,
) -> GltfSkin:
    if not isinstance(item, dict):
        raise PipelineError(f"{source.name} skin {index} is not an object")
    joints = tuple(int(joint) for joint in (item.get("joints") or []))
    if not joints:
        raise PipelineError(f"{source.name} skin {index} has no joints")
    ibm_index = item.get("inverseBindMatrices")
    if ibm_index is None:
        raise PipelineError(f"{source.name} skin {index} has no inverseBindMatrices")
    matrices = _read_mat4_list(document, buffers, ibm_index, source, "inverseBindMatrices")
    if len(matrices) != len(joints):
        raise PipelineError(
            f"{source.name} skin {index} has {len(joints)} joints and {len(matrices)} inverse bind matrices"  # noqa: E501
        )
    skeleton = item.get("skeleton")
    name = item.get("name") or ""
    if not isinstance(name, str):
        name = ""
    return GltfSkin(
        index,
        name,
        joints,
        int(skeleton) if skeleton is not None else None,
        matrices,
    )


def _validate_graph(
    nodes: tuple[GltfNode, ...],
    meshes: tuple[GltfMesh, ...],
    skins: tuple[GltfSkin, ...],
    roots: tuple[int, ...],
    source: Path,
) -> None:
    n_nodes = len(nodes)
    for root in roots:
        if root < 0 or root >= n_nodes:
            raise PipelineError(f"{source.name} scene root {root} is not a node")
    parent: dict[int, int] = {}
    for node in nodes:
        for child in node.children:
            if child < 0 or child >= n_nodes:
                raise PipelineError(f"{source.name} node {node.index} child {child} is not a node")
            if child in parent:
                raise PipelineError(
                    f"{source.name} node {child} has two parents ({parent[child]} and {node.index})"
                )
            parent[child] = node.index
        if node.mesh is not None and (node.mesh < 0 or node.mesh >= len(meshes)):
            raise PipelineError(
                f"{source.name} node {node.index!r} ({node.name!r}) references mesh {node.mesh}, "
                "which does not exist"
            )
        if node.skin is not None and (node.skin < 0 or node.skin >= len(skins)):
            raise PipelineError(
                f"{source.name} node {node.index} references skin {node.skin}, which does not exist"
            )
        for value in (*node.translation, *node.rotation, *node.scale):
            if not math.isfinite(value):
                raise PipelineError(
                    f"{source.name} node {node.name or node.index} has a non-finite transform"
                )
    for node in nodes:
        seen: set[int] = set()
        cursor = node.index
        while cursor in parent:
            if cursor in seen:
                raise PipelineError(f"{source.name} has a cyclic node hierarchy at node {cursor}")
            seen.add(cursor)
            cursor = parent[cursor]
    for skin in skins:
        for joint in skin.joints:
            if joint < 0 or joint >= n_nodes:
                raise PipelineError(f"{source.name} skin {skin.index} joint {joint} is not a node")
        if skin.skeleton is not None and (skin.skeleton < 0 or skin.skeleton >= n_nodes):
            raise PipelineError(
                f"{source.name} skin {skin.index} skeleton {skin.skeleton} is not a node"
            )


def _ancestor_chain(scene: GltfScene, index: int) -> set[int]:
    parent = {child: node.index for node in scene.nodes for child in node.children}
    chain: set[int] = set()
    cursor: int | None = index
    while cursor is not None and cursor not in chain:
        chain.add(cursor)
        cursor = parent.get(cursor)
    return chain


def _read_accessor(
    document: dict[str, Any],
    buffers: list[bytes],
    accessor_index: int,
    source: Path,
    what: str,
) -> tuple[list[float] | list[int], str, int]:
    accessors = document.get("accessors") or []
    if accessor_index < 0 or accessor_index >= len(accessors):
        raise PipelineError(f"{source.name} {what} accessor {accessor_index} is missing")
    accessor = accessors[accessor_index]
    component = accessor.get("componentType")
    atype = accessor.get("type")
    count = accessor.get("count")
    if component not in COMPONENT_SIZES or atype not in TYPE_COUNTS or not isinstance(count, int):
        raise PipelineError(f"{source.name} {what} accessor has an unsupported type")
    n = TYPE_COUNTS[atype]
    view_index = accessor.get("bufferView")
    if view_index is None:
        raise PipelineError(f"{source.name} {what} accessor has no bufferView")
    views = document.get("bufferViews") or []
    if view_index < 0 or view_index >= len(views):
        raise PipelineError(f"{source.name} {what} bufferView {view_index} is missing")
    view = views[view_index]
    buffer_index = view.get("buffer", 0)
    if buffer_index < 0 or buffer_index >= len(buffers):
        raise PipelineError(f"{source.name} {what} buffer {buffer_index} is missing")
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    stride = int(view.get("byteStride", 0)) or (COMPONENT_SIZES[component] * n)
    fmt = "<" + COMPONENT_STRUCT[component] * n
    size = struct.calcsize(fmt)
    blob = buffers[buffer_index]
    values: list[Any] = []
    for i in range(count):
        start = offset + i * stride
        if start + size > len(blob):
            raise PipelineError(f"{source.name} {what} accessor reads past the end of its buffer")
        values.extend(struct.unpack_from(fmt, blob, start))
    return values, atype, count


def _read_vec3_list(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> tuple[tuple[float, float, float], ...]:
    values, atype, count = _read_accessor(document, buffers, index, source, what)
    if atype != "VEC3":
        raise PipelineError(f"{source.name} {what} is {atype}, not VEC3")
    return tuple(
        (float(values[i]), float(values[i + 1]), float(values[i + 2]))
        for i in range(0, count * 3, 3)
    )


def _read_vec2_list(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> tuple[tuple[float, float], ...]:
    values, atype, count = _read_accessor(document, buffers, index, source, what)
    if atype != "VEC2":
        raise PipelineError(f"{source.name} {what} is {atype}, not VEC2")
    return tuple((float(values[i]), float(values[i + 1])) for i in range(0, count * 2, 2))


def _read_vec4_int(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> tuple[tuple[int, int, int, int], ...]:
    values, atype, count = _read_accessor(document, buffers, index, source, what)
    if atype != "VEC4":
        raise PipelineError(f"{source.name} {what} is {atype}, not VEC4")
    return tuple(
        (int(values[i]), int(values[i + 1]), int(values[i + 2]), int(values[i + 3]))
        for i in range(0, count * 4, 4)
    )


def _read_vec4_float(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> tuple[tuple[float, float, float, float], ...]:
    values, atype, count = _read_accessor(document, buffers, index, source, what)
    if atype != "VEC4":
        raise PipelineError(f"{source.name} {what} is {atype}, not VEC4")
    return tuple(
        (float(values[i]), float(values[i + 1]), float(values[i + 2]), float(values[i + 3]))
        for i in range(0, count * 4, 4)
    )


def _read_scalars(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> list[int]:
    values, atype, _count = _read_accessor(document, buffers, index, source, what)
    if atype != "SCALAR":
        raise PipelineError(f"{source.name} {what} is {atype}, not SCALAR")
    return [int(value) for value in values]


def _read_mat4_list(
    document: dict[str, Any], buffers: list[bytes], index: int, source: Path, what: str
) -> tuple[tuple[float, ...], ...]:
    values, atype, count = _read_accessor(document, buffers, index, source, what)
    if atype != "MAT4":
        raise PipelineError(f"{source.name} {what} is {atype}, not MAT4")
    out = []
    for i in range(count):
        chunk = values[i * 16 : (i + 1) * 16]
        out.append(tuple(float(v) for v in chunk))
    return tuple(out)


def _vec3(
    value: Any, default: tuple[float, float, float], source: Path, what: str
) -> tuple[float, float, float]:
    if value is None:
        return default
    if not isinstance(value, list) or len(value) != 3:
        raise PipelineError(f"{source.name} {what} must be three numbers")
    return (float(value[0]), float(value[1]), float(value[2]))


def _vec4(
    value: Any, default: tuple[float, float, float, float], source: Path, what: str
) -> tuple[float, float, float, float]:
    if value is None:
        return default
    if not isinstance(value, list) or len(value) != 4:
        raise PipelineError(f"{source.name} {what} must be four numbers")
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


def _decompose_matrix(
    matrix: Any, source: Path, index: int
) -> tuple[
    tuple[float, float, float], tuple[float, float, float, float], tuple[float, float, float]
]:
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise PipelineError(f"{source.name} node {index} matrix is not 16 numbers")
    m = [float(v) for v in matrix]
    translation = (m[12], m[13], m[14])
    sx = math.sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2])
    sy = math.sqrt(m[4] * m[4] + m[5] * m[5] + m[6] * m[6])
    sz = math.sqrt(m[8] * m[8] + m[9] * m[9] + m[10] * m[10])
    if sx == 0 or sy == 0 or sz == 0:
        raise PipelineError(f"{source.name} node {index} has a singular TRS matrix")
    r00, r10, r20 = m[0] / sx, m[1] / sx, m[2] / sx
    r01, r11, r21 = m[4] / sy, m[5] / sy, m[6] / sy
    r02, r12, r22 = m[8] / sz, m[9] / sz, m[10] / sz
    trace = r00 + r11 + r22
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        qw = 0.25 * s
        qx = (r21 - r12) / s
        qy = (r02 - r20) / s
        qz = (r10 - r01) / s
    elif r00 > r11 and r00 > r22:
        s = 2.0 * math.sqrt(1.0 + r00 - r11 - r22)
        qw = (r21 - r12) / s
        qx = 0.25 * s
        qy = (r01 + r10) / s
        qz = (r02 + r20) / s
    elif r11 > r22:
        s = 2.0 * math.sqrt(1.0 + r11 - r00 - r22)
        qw = (r02 - r20) / s
        qx = (r01 + r10) / s
        qy = 0.25 * s
        qz = (r12 + r21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + r22 - r00 - r11)
        qw = (r10 - r01) / s
        qx = (r02 + r20) / s
        qy = (r12 + r21) / s
        qz = 0.25 * s
    return translation, (qx, qy, qz, qw), (sx, sy, sz)
