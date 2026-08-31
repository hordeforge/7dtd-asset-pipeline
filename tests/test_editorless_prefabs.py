"""Named hierarchies, skinned meshes and ParticleSystem graphs.

Every acceptance here drives `pack_directory` / `build_bundle` and is read back
with UnityPy, which parses Unity's format with none of this repository's code.
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.bundle_writer import (
    GAME_OBJECT,
    MESH,
    MESH_FILTER,
    MESH_RENDERER,
    PARTICLE_ADDITIVE_SHADER,
    PARTICLE_ALPHA_SHADER,
    PARTICLE_SYSTEM,
    PARTICLE_SYSTEM_RENDERER,
    SKINNED_MESH_RENDERER,
    TRANSFORM,
    bone_name_hash,
    bone_transform_path,
    build_bundle,
    mesh,
    mesh_prefab,
    mesh_source_objects,
    pack_directory,
    shader,
    synthesized_members,
    vfx_prefab_objects,
)
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.gltf_scene import parse_gltf
from sevendtd_asset_pipeline.vfx import parse_vfx

REVISION = "2022.3.62f2"
needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"), "the writer needs UnityPy for the engine's type trees"
)
needs_trimesh = unittest.skipUnless(
    has_capability("trimesh"), "the mesh lane reads interchange files through trimesh"
)
needs_vkd3d = unittest.skipUnless(
    has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
)
needs_lz4 = unittest.skipUnless(
    __import__("importlib").util.find_spec("lz4") is not None,
    "shader blob compression needs the lz4 extra",
)


JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def write_glb(path: Path, document: dict[str, Any], blob: bytes = b"") -> Path:
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    chunks = struct.pack("<II", len(encoded), JSON_CHUNK) + encoded
    if blob:
        blob = blob + b"\x00" * ((-len(blob)) % 4)
        chunks += struct.pack("<II", len(blob), BIN_CHUNK) + blob
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks)
    return path


def accessor(
    buffer_view: int, component: int, count: int, atype: str, offset: int = 0
) -> dict[str, Any]:
    return {
        "bufferView": buffer_view,
        "byteOffset": offset,
        "componentType": component,
        "count": count,
        "type": atype,
    }


_TRIANGLE_MESH = {
    "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}]
}


def triangle_blob() -> tuple[bytes, list[dict[str, Any]], list[dict[str, Any]]]:
    """One triangle: positions, normals, uvs, indices."""
    positions = struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1)
    normals = struct.pack("<9f", 0, 0, 1, 0, 0, 1, 0, 0, 1)
    uvs = struct.pack("<6f", 0, 0, 1, 0, 0, 1)
    indices = struct.pack("<3H", 0, 1, 2)
    blob = positions + normals + uvs + indices
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 36},
        {"buffer": 0, "byteOffset": 72, "byteLength": 24},
        {"buffer": 0, "byteOffset": 96, "byteLength": 6},
    ]
    accessors = [
        accessor(0, 5126, 3, "VEC3"),
        accessor(1, 5126, 3, "VEC3"),
        accessor(2, 5126, 3, "VEC2"),
        accessor(3, 5123, 3, "SCALAR"),
    ]
    return blob, views, accessors


def write_hierarchy_glb(path: Path) -> Path:
    blob, views, accessors = triangle_blob()
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "body", "mesh": 0, "children": [1]},
            {"name": "armedLamp", "children": [2], "translation": [0.1, 0.2, 0.3]},
            {"name": "nestedChild", "translation": [0.0, 0.5, 0.0]},
        ],
        "meshes": [
            {
                "name": "body",
                "primitives": [
                    {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}
                ],
            }
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    return write_glb(path, document, blob)


def write_skinned_glb(
    path: Path,
    *,
    weights: list[tuple[float, float, float, float]] | None = None,
    origin: bool = False,
) -> Path:
    # Four vertices, two bones (hips, spine).
    positions = struct.pack(
        "<12f",
        0.1,
        0.0,
        0.0,
        -0.1,
        0.0,
        0.0,
        0.1,
        1.0,
        0.0,
        -0.1,
        1.0,
        0.0,
    )
    normals = struct.pack("<12f", *([0.0, 0.0, 1.0] * 4))
    uvs = struct.pack("<8f", 0, 0, 1, 0, 0, 1, 1, 1)
    indices = struct.pack("<6H", 0, 1, 2, 2, 1, 3)
    joints = struct.pack("<16B", 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    if weights is None:
        weight_values: list[tuple[float, float, float, float]] = [
            (1.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
        ]
    else:
        weight_values = weights
    weight_bytes = b"".join(struct.pack("<4f", *row) for row in weight_values)
    ibm_hips = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    ibm_spine = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1)
    blob = positions + normals + uvs + indices + joints + weight_bytes + ibm_hips + ibm_spine
    offset = 0
    views = []
    lengths = [48, 48, 32, 12, 16, 64, 128]
    for length in lengths:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": length})
        offset += length
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": (
            [
                {"name": "Origin", "children": [1]},
                {"name": "Hips", "children": [2, 3], "translation": [0, 0, 0]},
                {"name": "Spine", "translation": [0, 1, 0]},
                {"name": "body", "mesh": 0, "skin": 0},
            ]
            if origin
            else [
                {"name": "hips", "children": [1, 2], "translation": [0, 0, 0]},
                {"name": "spine", "translation": [0, 1, 0]},
                {"name": "body", "mesh": 0, "skin": 0},
            ]
        ),
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                            "JOINTS_0": 4,
                            "WEIGHTS_0": 5,
                        },
                        "indices": 3,
                    }
                ]
            }
        ],
        "skins": [
            {
                "joints": [1, 2] if origin else [0, 1],
                "skeleton": 1 if origin else 0,
                "inverseBindMatrices": 6,
            }
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": [
            accessor(0, 5126, 4, "VEC3"),
            accessor(1, 5126, 4, "VEC3"),
            accessor(2, 5126, 4, "VEC2"),
            accessor(3, 5123, 6, "SCALAR"),
            accessor(4, 5121, 4, "VEC4"),
            accessor(5, 5126, 4, "VEC4"),
            accessor(6, 5126, 2, "MAT4"),
        ],
    }
    return write_glb(path, document, blob)


def write_png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGBA", (4, 4), (255, 128, 0, 128)).save(path)
    return path


def vfx_document(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "format": "shamway.vfx",
        "version": 1,
        "budget": 32,
        "materials": [
            {"name": "flashMat", "blend": "additive", "texture": "flashCard"},
            {"name": "smokeMat", "blend": "alpha", "texture": "smokeCard"},
        ],
        "systems": [
            {
                "name": "flash",
                "duration": 0.35,
                "looping": False,
                "start_delay": 0.0,
                "simulation_space": "world",
                "scaling_mode": "hierarchy",
                "max_particles": 8,
                "start_lifetime": 0.35,
                "start_speed": 0.0,
                "start_size": 2.0,
                "start_rotation": 0.0,
                "start_color": [1, 0.8, 0.2, 1],
                "emission": {"rate": 0, "bursts": [{"time": 0, "count": 8}]},
                "shape": {"type": "sphere", "radius": 0.5},
                "color_over_lifetime": {
                    "gradient": [
                        {"t": 0, "color": [1, 1, 1, 1]},
                        {"t": 1, "color": [1, 1, 1, 0]},
                    ]
                },
                "renderer": {"mode": "billboard", "material": "flashMat"},
            },
            {
                "name": "smoke",
                "duration": 2.0,
                "looping": False,
                "max_particles": 16,
                "start_lifetime": [0.8, 1.2],
                "start_speed": 1.0,
                "start_size": {"curve": [[0, 0.2], [1, 1.0]]},
                "start_color": [0.4, 0.4, 0.4, 1],
                "emission": {"rate": 8},
                "shape": {"type": "cone", "radius": 0.2, "angle": 20},
                "velocity_over_lifetime": {"x": 0, "y": 1, "z": 0, "space": "local"},
                "limit_velocity": {"dampen": 0.1, "magnitude": 4},
                "size_over_lifetime": {"curve": [[0, 1], [1, 0.2]]},
                "rotation_over_lifetime": 45,
                "renderer": {
                    "mode": "stretched_billboard",
                    "material": "smokeMat",
                    "length_scale": 2.5,
                },
            },
        ],
    }
    body.update(overrides)
    return body


def read_objects(bundle: Path) -> dict[int, list[dict[str, Any]]]:
    import UnityPy

    found: dict[int, list[dict[str, Any]]] = {}
    for obj in UnityPy.load(str(bundle)).objects:
        found.setdefault(int(obj.type.value), []).append(obj.read_typetree())
    return found


@needs_unitypy
class HierarchyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def pack(self, source: Path) -> tuple[bytes, dict[int, list[dict[str, Any]]]]:
        objects = mesh_source_objects(source, set())
        objects.append(shader("Shamway/Unlit"))
        payload = build_bundle(objects, REVISION, "hier.unity3d")
        written = self.root / "hier.unity3d"
        written.write_bytes(payload)
        return payload, read_objects(written)

    @needs_vkd3d
    def test_named_children_survive_with_authored_names_and_parenting(self) -> None:
        source = write_hierarchy_glb(self.root / "timedNuke.glb")
        _payload, objects = self.pack(source)
        gos = {item["m_Name"]: item for item in objects[GAME_OBJECT]}
        self.assertIn("timedNuke", gos)
        self.assertIn("body", gos)
        self.assertIn("armedLamp", gos)
        self.assertIn("nestedChild", gos)
        transforms = objects[TRANSFORM]
        by_go = {item["m_GameObject"]["m_PathID"]: item for item in transforms}
        path_ids = {}
        import UnityPy

        env = UnityPy.load(str(self.root / "hier.unity3d"))
        for obj in env.objects:
            if int(obj.type.value) == GAME_OBJECT:
                tree = obj.read_typetree()
                path_ids[tree["m_Name"]] = obj.path_id

        def transform_id(name: str) -> int:
            for obj in env.objects:
                if int(obj.type.value) != TRANSFORM:
                    continue
                tree = obj.read_typetree()
                if tree["m_GameObject"]["m_PathID"] == path_ids[name]:
                    return int(obj.path_id)
            raise AssertionError(f"no transform for {name}")

        lamp_tr = by_go[path_ids["armedLamp"]]
        nested_tr = by_go[path_ids["nestedChild"]]
        body_tr = by_go[path_ids["body"]]
        self.assertEqual(lamp_tr["m_Father"]["m_PathID"], transform_id("body"))
        self.assertAlmostEqual(lamp_tr["m_LocalPosition"]["x"], -0.1, places=5)
        self.assertAlmostEqual(lamp_tr["m_LocalPosition"]["y"], 0.2, places=5)
        self.assertEqual(nested_tr["m_Father"]["m_PathID"], transform_id("armedLamp"))
        self.assertEqual(body_tr["m_Father"]["m_PathID"], transform_id("timedNuke"))
        child_ids = [item["m_PathID"] for item in body_tr["m_Children"]]
        self.assertIn(transform_id("armedLamp"), child_ids)
        container = dict(objects[142][0]["m_Container"])
        self.assertIn("timednuke", container)
        self.assertNotIn("armedlamp", container)

    @needs_vkd3d
    def test_mesh_stays_on_the_authored_node_not_the_root_when_the_mesh_is_a_child(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {"name": "payload", "children": [1]},
                {"name": "armedLamp", "mesh": 0},
            ],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "lamp.glb", document, blob)
        _payload, objects = self.pack(source)
        self.assertEqual(1, len(objects[MESH_FILTER]))
        import UnityPy

        env = UnityPy.load(str(self.root / "hier.unity3d"))
        gos = {}
        for obj in env.objects:
            if int(obj.type.value) == GAME_OBJECT:
                gos[obj.read_typetree()["m_Name"]] = obj.path_id
        filt = objects[MESH_FILTER][0]
        self.assertEqual(filt["m_GameObject"]["m_PathID"], gos["armedLamp"])

    def test_duplicate_child_names_are_rejected(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {"name": "root", "mesh": 0, "children": [1, 2]},
                {"name": "armedLamp"},
                {"name": "armedLamp"},
            ],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "dup.glb", document, blob)
        with self.assertRaisesRegex(PipelineError, "armedLamp"):
            mesh_source_objects(source, set())

    def test_a_cycle_is_rejected(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {"name": "a", "mesh": 0, "children": [1]},
                {"name": "b", "children": [0]},
            ],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "cycle.glb", document, blob)
        with self.assertRaisesRegex(PipelineError, "cyclic"):
            parse_gltf(source)

    def test_a_dangling_mesh_index_is_rejected(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "root", "mesh": 9, "children": [1]}, {"name": "armedLamp"}],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "dangling.glb", document, blob)
        with self.assertRaisesRegex(PipelineError, "does not exist"):
            parse_gltf(source)

    def test_a_non_finite_transform_is_rejected(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {"name": "root", "mesh": 0, "children": [1]},
                {"name": "armedLamp", "translation": [0, float("nan"), 0]},
            ],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "nan.glb", document, blob)
        with self.assertRaisesRegex(PipelineError, "non-finite"):
            parse_gltf(source)

    def test_a_single_mesh_gltf_still_collapses_to_the_static_prefab_shape(self) -> None:
        blob, views, accessors = triangle_blob()
        document = {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [{"name": "Cube", "mesh": 0}],
            "meshes": [_TRIANGLE_MESH],
            "buffers": [{"byteLength": len(blob)}],
            "bufferViews": views,
            "accessors": accessors,
        }
        source = write_glb(self.root / "cube.glb", document, blob)
        objects = mesh_source_objects(source, set())
        class_ids = [obj.class_id for obj in objects]
        self.assertIn(MESH_FILTER, class_ids)
        self.assertIn(MESH_RENDERER, class_ids)
        self.assertNotIn(SKINNED_MESH_RENDERER, class_ids)
        gos = [obj for obj in objects if obj.class_id == GAME_OBJECT]
        self.assertEqual(1, len(gos))
        self.assertEqual("cube", gos[0].name)


@needs_unitypy
class SkinnedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @needs_vkd3d
    def test_a_skinned_mesh_writes_smr_bones_weights_and_bind_poses(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        objects = mesh_source_objects(source, set())
        objects.append(shader("Shamway/Unlit"))
        written = self.root / "skin.unity3d"
        written.write_bytes(build_bundle(objects, REVISION, "skin.unity3d"))
        trees = read_objects(written)
        self.assertIn(SKINNED_MESH_RENDERER, trees)
        self.assertNotIn(MESH_RENDERER, trees)
        self.assertNotIn(MESH_FILTER, trees)
        mesh_tree = trees[MESH][0]
        self.assertEqual(2, len(mesh_tree["m_BindPose"]))
        hashes = mesh_tree["m_BoneNameHashes"]
        self.assertEqual(2, len(hashes))
        self.assertEqual(bone_name_hash("hips"), hashes[0])
        self.assertEqual(bone_name_hash("hips/spine"), hashes[1])
        self.assertNotEqual(
            bone_name_hash("spine"),
            hashes[1],
            "the spine hash is the slash-separated path, not the leaf name",
        )
        self.assertEqual(bone_name_hash("hips"), mesh_tree["m_RootBoneNameHash"])
        channels = mesh_tree["m_VertexData"]["m_Channels"]
        self.assertEqual(4, channels[12]["dimension"])
        self.assertEqual(0, channels[12]["format"])
        self.assertEqual(4, channels[13]["dimension"])
        self.assertEqual(10, channels[13]["format"])
        smr = trees[SKINNED_MESH_RENDERER][0]
        self.assertEqual(2, len(smr["m_Bones"]))
        self.assertNotEqual(0, smr["m_RootBone"]["m_PathID"])
        self.assertNotEqual(0, smr["m_Mesh"]["m_PathID"])
        gos = {item["m_Name"] for item in trees[GAME_OBJECT]}
        self.assertIn("hips", gos)
        self.assertIn("spine", gos)

    def test_a_skin_is_never_flattened_to_mesh_renderer(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        objects = mesh_source_objects(source, set())
        self.assertTrue(any(obj.class_id == SKINNED_MESH_RENDERER for obj in objects))
        self.assertFalse(any(obj.class_id == MESH_RENDERER for obj in objects))

    def test_non_normalized_weights_are_normalized(self) -> None:
        source = write_skinned_glb(
            self.root / "gear.glb",
            weights=[(2, 2, 0, 0), (2, 2, 0, 0), (0, 2, 2, 0), (0, 2, 2, 0)],
        )
        objects = mesh_source_objects(source, set())
        geometry = next(obj for obj in objects if obj.class_id == MESH)
        data = bytes(geometry.fields["m_VertexData"]["m_DataSize"])
        # first vertex: pos12 + nrm12 + uv8 + weights16
        w0, w1, w2, _w3 = struct.unpack_from("<4f", data, 32)
        self.assertAlmostEqual(0.5, w0, places=5)
        self.assertAlmostEqual(0.5, w1, places=5)
        self.assertEqual(0.0, w2)

    def test_zero_weights_are_rejected(self) -> None:
        source = write_skinned_glb(
            self.root / "gear.glb",
            weights=[(0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 1, 0, 0)],
        )
        with self.assertRaisesRegex(PipelineError, "no bone weight"):
            mesh_source_objects(source, set())

    def test_negative_weights_are_rejected(self) -> None:
        source = write_skinned_glb(
            self.root / "gear.glb",
            weights=[(-1, 2, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 1, 0, 0)],
        )
        with self.assertRaisesRegex(PipelineError, "negative"):
            mesh_source_objects(source, set())

    def test_out_of_range_joint_indices_are_rejected(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        document, blob = _glb_parts(source)
        # JOINTS_0 is bufferView 4, first vertex's first index -> 9
        views = document["bufferViews"]
        start = views[4]["byteOffset"]
        blob = blob[:start] + bytes([9, 0, 0, 0]) + blob[start + 4 :]
        write_glb(source, document, blob)
        with self.assertRaisesRegex(PipelineError, "out of range"):
            mesh_source_objects(source, set())

    def test_missing_joints_are_rejected(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        document, blob = _glb_parts(source)
        document["skins"][0]["joints"] = [0, 99]
        write_glb(source, document, blob)
        with self.assertRaisesRegex(PipelineError, "joint"):
            parse_gltf(source)

    def test_a_singular_bind_matrix_is_rejected(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        document, blob = _glb_parts(source)
        zero = struct.pack("<16f", *([0.0] * 16))
        # ibm starts after pos48+nrm48+uv32+idx12+joints16+weights64 = 220
        blob = blob[:220] + zero + blob[220 + 64 :]
        write_glb(source, document, blob)
        with self.assertRaisesRegex(PipelineError, "singular"):
            mesh_source_objects(source, set())

    @needs_vkd3d
    @needs_lz4
    def test_pack_directory_writes_the_origin_hips_hash(self) -> None:
        write_skinned_glb(self.root / "gear.glb", origin=True)
        payload, _manifest = pack_directory(self.root, "skin.unity3d", REVISION)
        written = self.root / "skin.unity3d"
        written.write_bytes(payload)
        mesh_tree = read_objects(written)[MESH][0]
        self.assertEqual(1722913273, mesh_tree["m_RootBoneNameHash"])
        self.assertEqual(bone_name_hash("Origin/Hips"), mesh_tree["m_BoneNameHashes"][0])
        self.assertEqual(bone_name_hash("Origin/Hips/Spine"), mesh_tree["m_BoneNameHashes"][1])

    def test_nomad_bodycloth_root_hash_is_origin_hips(self) -> None:
        bundle = _nomad_gear_bundle()
        if bundle is None:
            self.skipTest("installed game nomad.bundle is not present")
        import UnityPy

        for obj in UnityPy.load(str(bundle)).objects:
            if int(obj.type.value) != MESH:
                continue
            tree = obj.read_typetree()
            if tree.get("m_Name") != "bodyCloth":
                continue
            self.assertEqual(1722913273, tree["m_RootBoneNameHash"])
            return
        self.fail("nomad.bundle has no Mesh named bodyCloth")


def _nomad_gear_bundle() -> Path | None:
    game = os.environ.get("SEVEN_DAYS_TO_DIE_DIR")
    if not game:
        return None
    path = (
        Path(game)
        / "Data/Addressables/Standalone/player_assets_entities/player/female/gear/nomad.bundle"
    )
    return path if path.is_file() else None


@needs_trimesh
class BoneHashTests(unittest.TestCase):
    """CRC of the Transform path, and pack-time refusal, independent of UnityPy.

    The pack-time refusals run `pack_directory`, which reads the interchange
    file through trimesh — gated, or a job without trimesh fails them with
    the capability error instead of the refusal they test.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_origin_hips_crc_is_the_harvested_nomad_value(self) -> None:
        self.assertEqual(1722913273, bone_name_hash("Origin/Hips"))
        self.assertNotEqual(1722913273, bone_name_hash("Hips"))
        self.assertNotEqual(1722913273, bone_name_hash("hips"))
        self.assertNotEqual(1722913273, bone_name_hash("gearFemaleNomadPrefab/Origin/Hips"))

    def test_origin_hips_path_is_the_hashed_string(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb", origin=True)
        scene = parse_gltf(source)
        hips, spine = scene.skins[0].joints
        self.assertEqual("Origin/Hips", bone_transform_path(scene, hips))
        self.assertEqual("Origin/Hips/Spine", bone_transform_path(scene, spine))
        self.assertEqual(1722913273, bone_name_hash(bone_transform_path(scene, hips)))

    def test_pack_directory_rejects_a_skin_with_out_of_range_joints(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        document, blob = _glb_parts(source)
        document["skins"][0]["joints"] = [0, 99]
        write_glb(source, document, blob)
        with self.assertRaisesRegex(PipelineError, "joint"):
            pack_directory(self.root, "bad.unity3d", REVISION)

    def test_synthesized_members_does_not_invent_a_static_prefab_for_a_broken_skin(self) -> None:
        source = write_skinned_glb(self.root / "gear.glb")
        document, blob = _glb_parts(source)
        document["skins"][0]["joints"] = [0, 99]
        write_glb(source, document, blob)
        with self.assertRaisesRegex(PipelineError, "joint"):
            synthesized_members(self.root)


def _glb_parts(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    offset = 12
    document = None
    blob = b""
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + length]
        offset += length
        if kind == JSON_CHUNK:
            document = json.loads(chunk.decode("utf-8"))
        elif kind == BIN_CHUNK:
            blob = chunk
    assert document is not None
    return document, blob


@needs_unitypy
@needs_vkd3d
@needs_lz4
class ParticleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_vfx_prefab_carries_systems_renderers_and_blend_state(self) -> None:
        write_png(self.root / "flashCard.png")
        write_png(self.root / "smokeCard.png")
        (self.root / "burst.vfx").write_text(json.dumps(vfx_document()), encoding="utf-8")
        sources = self.root
        payload, _manifest = pack_directory(sources, "vfx.unity3d", REVISION)
        written = self.root / "vfx.unity3d"
        written.write_bytes(payload)
        trees = read_objects(written)
        self.assertGreaterEqual(len(trees[PARTICLE_SYSTEM]), 2)
        self.assertEqual(len(trees[PARTICLE_SYSTEM]), len(trees[PARTICLE_SYSTEM_RENDERER]))
        gos = {item["m_Name"] for item in trees[GAME_OBJECT]}
        self.assertIn("burst", gos)
        self.assertIn("flash", gos)
        self.assertIn("smoke", gos)
        systems = trees[PARTICLE_SYSTEM]
        self.assertTrue(any(item["InitialModule"]["maxNumParticles"] == 8 for item in systems))
        self.assertTrue(any(item["InitialModule"]["maxNumParticles"] == 16 for item in systems))
        self.assertTrue(any(item["EmissionModule"]["m_BurstCount"] == 1 for item in systems))
        self.assertTrue(any(item["ShapeModule"]["type"] == 0 for item in systems))
        self.assertTrue(any(item["ShapeModule"]["type"] == 4 for item in systems))
        renderers = trees[PARTICLE_SYSTEM_RENDERER]
        modes = {item["m_RenderMode"] for item in renderers}
        self.assertIn(0, modes)
        self.assertIn(1, modes)
        materials = {item["m_Name"]: item for item in trees[21]}
        additive = materials["flashMat"]
        alpha = materials["smokeMat"]
        self.assertEqual(3000, additive["m_CustomRenderQueue"])
        self.assertEqual(3000, alpha["m_CustomRenderQueue"])
        add_floats = dict(additive["m_SavedProperties"]["m_Floats"])
        alpha_floats = dict(alpha["m_SavedProperties"]["m_Floats"])
        self.assertEqual(5.0, add_floats["_SrcBlend"])
        self.assertEqual(1.0, add_floats["_DstBlend"])
        self.assertEqual(0.0, add_floats["_ZWrite"])
        self.assertEqual(5.0, alpha_floats["_SrcBlend"])
        self.assertEqual(10.0, alpha_floats["_DstBlend"])
        shaders = trees[48]
        states = [
            item["m_ParsedForm"]["m_SubShaders"][0]["m_Passes"][0]["m_State"] for item in shaders
        ]
        dests = {state["rtBlend0"]["destBlend"]["val"] for state in states}
        self.assertTrue(
            dests & {1.0, 10.0},
            f"particle shaders must not be opaque One/Zero, got {dests}",
        )
        for state in states:
            if state["rtBlend0"]["destBlend"]["val"] in (1.0, 10.0):
                self.assertEqual(0.0, state["zWrite"]["val"])
                self.assertEqual(5.0, state["rtBlend0"]["srcBlend"]["val"])
        container = dict(trees[142][0]["m_Container"])
        self.assertIn("burst", container)
        self.assertIn("flashmat", container)
        self.assertNotIn("flash", container)
        self.assertTrue(any(item["VelocityModule"]["enabled"] for item in systems))
        self.assertTrue(any(item["ClampVelocityModule"]["enabled"] for item in systems))
        self.assertTrue(any(item["ColorModule"]["enabled"] for item in systems))

    def test_missing_card_textures_are_rejected_by_name(self) -> None:
        (self.root / "burst.vfx").write_text(json.dumps(vfx_document()), encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "flashCard"):
            pack_directory(self.root, "vfx.unity3d", REVISION)

    def test_mixed_velocity_curve_modes_are_rejected(self) -> None:
        doc = vfx_document()
        doc["systems"][1]["velocity_over_lifetime"] = {
            "x": 0,
            "y": {"curve": [[0, 1], [1, 0]]},
            "z": 0,
        }
        with self.assertRaisesRegex(PipelineError, "curve mode"):
            parse_vfx(_write_json(self.root / "bad.vfx", doc))

    def test_over_budget_systems_are_rejected(self) -> None:
        doc = vfx_document(budget=10)
        with self.assertRaisesRegex(PipelineError, "over its budget"):
            parse_vfx(_write_json(self.root / "big.vfx", doc))

    def test_remaining_shape_types_serialize(self) -> None:
        write_png(self.root / "flashCard.png")
        write_png(self.root / "smokeCard.png")
        doc = vfx_document(budget=48)
        extra = []
        for name, shape in (
            ("haze", "hemisphere"),
            ("sparks", "circle"),
            ("dust", "box"),
        ):
            extra.append(
                {
                    "name": name,
                    "max_particles": 4,
                    "start_lifetime": 1,
                    "emission": {"rate": 1},
                    "shape": {"type": shape, "radius": 1, "scale": [1, 1, 1]},
                    "renderer": {"mode": "billboard", "material": "smokeMat"},
                }
            )
        doc["systems"].extend(extra)
        (self.root / "burst.vfx").write_text(json.dumps(doc), encoding="utf-8")
        payload, _ = pack_directory(self.root, "shapes.unity3d", REVISION)
        written = self.root / "shapes.unity3d"
        written.write_bytes(payload)
        types = {item["ShapeModule"]["type"] for item in read_objects(written)[PARTICLE_SYSTEM]}
        self.assertTrue({0, 2, 4, 5, 10} <= types)

    def test_unsupported_modules_are_rejected(self) -> None:
        doc = vfx_document()
        doc["systems"][0]["trails"] = True
        with self.assertRaisesRegex(PipelineError, "unsupported modules"):
            parse_vfx(_write_json(self.root / "trail.vfx", doc))

    def test_two_vfx_builds_are_byte_identical(self) -> None:
        write_png(self.root / "flashCard.png")
        write_png(self.root / "smokeCard.png")
        (self.root / "burst.vfx").write_text(json.dumps(vfx_document()), encoding="utf-8")
        first, _ = pack_directory(self.root, "vfx.unity3d", REVISION)
        second, _ = pack_directory(self.root, "vfx.unity3d", REVISION)
        self.assertEqual(first, second)

    def test_a_horizontal_billboard_system_sets_render_mode_two(self) -> None:
        write_png(self.root / "flashCard.png")
        write_png(self.root / "smokeCard.png")
        doc = vfx_document()
        doc["systems"][0]["renderer"]["mode"] = "horizontal_billboard"
        (self.root / "burst.vfx").write_text(json.dumps(doc), encoding="utf-8")
        from sevendtd_asset_pipeline.bundle_writer import texture_2d

        objects, _shaders = vfx_prefab_objects(self.root / "burst.vfx", {"flashCard", "smokeCard"})
        objects.append(texture_2d("flashCard", self.root / "flashCard.png"))
        objects.append(texture_2d("smokeCard", self.root / "smokeCard.png"))
        objects.append(shader(PARTICLE_ALPHA_SHADER, blend="alpha", vertex_color=True))
        objects.append(shader(PARTICLE_ADDITIVE_SHADER, blend="additive", vertex_color=True))
        written = self.root / "horiz.unity3d"
        written.write_bytes(build_bundle(objects, REVISION, "horiz.unity3d"))
        modes = {item["m_RenderMode"] for item in read_objects(written)[PARTICLE_SYSTEM_RENDERER]}
        self.assertIn(2, modes)


def _write_json(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@needs_unitypy
@needs_trimesh
class BackwardCompatTests(unittest.TestCase):
    def test_an_obj_still_emits_mesh_filter_and_mesh_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "prop.obj"
            source.write_text(
                "v 1 0 0\nv 0 1 0\nv 0 0 1\nv 0 0 0\nf 1 2 3\nf 1 3 4\nf 1 4 2\nf 2 4 3\n",
                encoding="utf-8",
            )
            objects = [mesh("prop_mesh", source), *mesh_prefab("prop", "prop_mesh")]
            self.assertTrue(any(obj.class_id == MESH_FILTER for obj in objects))
            self.assertTrue(any(obj.class_id == MESH_RENDERER for obj in objects))
            self.assertFalse(any(obj.class_id == SKINNED_MESH_RENDERER for obj in objects))
            self.assertFalse(any(obj.class_id == PARTICLE_SYSTEM for obj in objects))


@needs_unitypy
@needs_vkd3d
@needs_lz4
class PackDirectoryNewTypesTests(unittest.TestCase):
    def test_static_and_vfx_and_hierarchy_pack_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "staticProp.obj").write_text(
                "v 1 0 0\nv 0 1 0\nv 0 0 1\nv 0 0 0\nf 1 2 3\nf 1 3 4\nf 1 4 2\nf 2 4 3\n",
                encoding="utf-8",
            )
            write_hierarchy_glb(root / "timedNuke.glb")
            write_png(root / "flashCard.png")
            write_png(root / "smokeCard.png")
            (root / "burst.vfx").write_text(json.dumps(vfx_document()), encoding="utf-8")
            payload, _manifest = pack_directory(root, "all.unity3d", REVISION)
            written = root / "all.unity3d"
            written.write_bytes(payload)
            trees = read_objects(written)
            self.assertIn(MESH_FILTER, trees)
            self.assertIn(MESH_RENDERER, trees)
            self.assertIn(PARTICLE_SYSTEM, trees)
            gos = {item["m_Name"] for item in trees[GAME_OBJECT]}
            self.assertIn("staticProp", gos)
            self.assertIn("timedNuke", gos)
            self.assertIn("armedLamp", gos)
            self.assertIn("burst", gos)

    def test_two_hierarchy_builds_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_hierarchy_glb(root / "timedNuke.glb")
            first, _ = pack_directory(root, "hier.unity3d", REVISION)
            second, _ = pack_directory(root, "hier.unity3d", REVISION)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
