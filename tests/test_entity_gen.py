"""The generated-entity lane: rig + parts -> skinned GLB -> bundle -> read-back.

The bundle leg drives the writer's own skinned path (`mesh_source_objects` /
`build_bundle`) and reads the result back with UnityPy, which parses Unity's
format with none of this repository's code — so an acceptance here is the
same evidence the writer's own suite demands: a `SkinnedMeshRenderer` with
the rig's bones bound by name hash, and no MeshRenderer fallback.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.bundle_writer import (
    GAME_OBJECT,
    MESH,
    MESH_FILTER,
    MESH_RENDERER,
    SKINNED_MESH_RENDERER,
    TRANSFORM,
    bone_name_hash,
    bone_transform_path,
    build_bundle,
    mesh_source_objects,
    shader,
)
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.generators import run
from sevendtd_asset_pipeline.generators.entity import entity_xml
from sevendtd_asset_pipeline.gltf_scene import parse_gltf
from sevendtd_asset_pipeline.rigs import load_rig, scaled

REVISION = "2022.3.62f2"
needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"), "the writer needs UnityPy for the engine's type trees"
)
needs_vkd3d = unittest.skipUnless(
    has_capability("vkd3d-compiler"), "the prefab lane needs a usable shader compiler"
)
needs_trimesh = unittest.skipUnless(
    has_capability("trimesh"), "the mesh lane reads interchange files through trimesh"
)


def read_objects(bundle: Path) -> dict[int, list[dict[str, Any]]]:
    import UnityPy

    found: dict[int, list[dict[str, Any]]] = {}
    for obj in UnityPy.load(str(bundle)).objects:
        found.setdefault(int(obj.type.value), []).append(obj.read_typetree())
    return found


class EntityGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def generate(self, *extra: str) -> Path:
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out), *extra]), 0)
        return out

    def test_generated_glb_is_a_single_skinned_mesh(self) -> None:
        out = self.generate()
        scene = parse_gltf(out)
        self.assertEqual(len(scene.nodes), 21)  # 20 joints + the mesh node
        self.assertEqual(len(scene.meshes), 1)
        self.assertEqual(len(scene.skins), 1)
        skinned = [node for node in scene.nodes if node.skin is not None]
        self.assertEqual(len(skinned), 1)
        self.assertEqual(skinned[0].name, "body")
        skin = scene.skins[0]
        self.assertEqual(len(skin.joints), 20)
        self.assertEqual(len(skin.inverse_bind), 20)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        weights = primitive.weights
        assert joints is not None and weights is not None
        self.assertEqual(len(primitive.positions), len(joints))
        self.assertEqual(len(primitive.positions), len(weights))
        for joint_row, weight_row in zip(joints, weights, strict=True):
            self.assertEqual(len(joint_row), 4)
            self.assertEqual(len(weight_row), 4)
            self.assertGreaterEqual(max(weight_row), 1.0)

    def test_every_vertex_binds_one_bone(self) -> None:
        out = self.generate()
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        weights = primitive.weights
        assert joints is not None and weights is not None
        joint_names = {scene.nodes[j].name for j in scene.skins[0].joints}
        for joint_row, weight_row in zip(joints, weights, strict=True):
            self.assertEqual(sum(weight_row), 1.0)
            self.assertIn(joint_row[0], range(len(scene.skins[0].joints)))
        self.assertIn("Hips", joint_names)
        self.assertIn("LeftHand", joint_names)

    def test_custom_parts_file_is_honoured(self) -> None:
        parts = self.root / "parts.json"
        parts.write_text(
            json.dumps(
                {
                    "parts": {
                        "Head": {"shape": "sphere", "radius": 0.2},
                        "Root": {"shape": "box", "width": 0.3, "depth": 0.3, "height": 0.3},
                    }
                }
            ),
            encoding="utf-8",
        )
        out = self.generate("--parts", str(parts))
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        self.assertGreater(len(primitive.positions), 0)
        joints = primitive.joints
        assert joints is not None
        rig = load_rig("humanoid")
        head_index = rig.index("Head")
        self.assertTrue(
            any(joint_row[0] == head_index for joint_row in joints),
            "a part must bind to the Head joint",
        )

    def test_parts_for_unknown_bones_are_refused(self) -> None:
        parts = self.root / "parts.json"
        parts.write_text(
            json.dumps({"parts": {"GhostBone": {"shape": "sphere", "radius": 0.1}}}),
            encoding="utf-8",
        )
        out = self.root / "x.glb"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run("entity", [str(out), "--parts", str(parts)])
        self.assertEqual(code, 1)
        self.assertIn("not in the rig", stderr.getvalue())

    def test_bad_parts_shape_is_refused(self) -> None:
        parts = self.root / "parts.json"
        parts.write_text(
            json.dumps({"parts": {"Head": {"shape": "icosahedron"}}}), encoding="utf-8"
        )
        out = self.root / "x.glb"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run("entity", [str(out), "--parts", str(parts)])
        self.assertEqual(code, 1)
        self.assertIn("cylinder, sphere or box", stderr.getvalue())

    def test_xml_needs_mod_and_bundle(self) -> None:
        out = self.root / "x.glb"
        with self.assertRaises(SystemExit) as raised:
            run("entity", [str(out), "--xml", str(self.root / "e.xml")])
        self.assertIn("--xml needs --mod and --bundle", str(raised.exception))

    def test_xml_fragment_names_both_model_properties(self) -> None:
        fragment = entity_xml("myCreature", "MyMod", "myMod", "creature")
        self.assertIn('<append xpath="/entity_classes">', fragment)
        self.assertIn('name="myCreature"', fragment)
        self.assertIn(
            'name="Prefab" value="#@modfolder(MyMod):Resources/myMod.unity3d?creature"',
            fragment,
        )
        self.assertIn(
            'name="Mesh" value="#@modfolder(MyMod):Resources/myMod.unity3d?creature"',
            fragment,
        )
        self.assertIn("</configs>", fragment)

    def test_xml_is_written_by_the_cli(self) -> None:
        xml = self.root / "creature-entityclasses.xml"
        out = self.root / "creature.glb"
        self.assertEqual(
            run("entity", [str(out), "--mod", "MyMod", "--bundle", "myMod", "--xml", str(xml)]),
            0,
        )
        text = xml.read_text(encoding="utf-8")
        self.assertIn('name="creature"', text)
        self.assertIn("#@modfolder(MyMod):Resources/myMod.unity3d?creature", text)

    def test_unknown_rig_is_refused(self) -> None:
        out = self.root / "x.glb"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run("entity", [str(out), "--rig", str(self.root / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", stderr.getvalue())

    def test_every_named_rig_generates_with_its_own_parts(self) -> None:
        from sevendtd_asset_pipeline.generators.entity import default_parts_for

        for name in (
            "humanoid",
            "quadruped",
            "quadruped-small",
            "quadruped-large",
            "bird",
            "dinosaur",
            "arachnid",
            "crocodile",
        ):
            with self.subTest(name):
                out = self.root / f"{name}.glb"
                self.assertEqual(run("entity", [str(out), "--rig", name]), 0)
                scene = parse_gltf(out)
                self.assertEqual(len(scene.skins), 1)
                rig = load_rig(name)
                parts = default_parts_for(rig)
                # Root gets no part; every other bone of the rig has one.
                self.assertEqual(len(parts), len(rig.bones) - 1, name)

    def test_size_variant_scales_the_parts_with_the_bones(self) -> None:
        from sevendtd_asset_pipeline.generators.entity import default_parts_for

        medium = default_parts_for(load_rig("quadruped"))
        small = default_parts_for(load_rig("quadruped-small"))
        self.assertAlmostEqual(small["Head"]["radius"], medium["Head"]["radius"] * 0.45)
        self.assertAlmostEqual(
            small["LeftFrontUpper"]["height"], medium["LeftFrontUpper"]["height"] * 0.45
        )

    def test_scale_flag_halves_bones_and_parts(self) -> None:
        from sevendtd_asset_pipeline.generators.entity import default_parts_for

        out = self.generate("--rig", "quadruped", "--scale", "0.5")
        scene = parse_gltf(out)
        pelvis = next(node for node in scene.nodes if node.name == "Pelvis")
        self.assertAlmostEqual(pelvis.translation[1], 0.3, places=4)
        rig = scaled(load_rig("quadruped"), 0.5)
        parts = default_parts_for(rig)
        self.assertAlmostEqual(parts["Head"]["radius"], 0.075 * 0.5)

    def test_a_rig_without_default_parts_asks_for_a_parts_file(self) -> None:
        spec = self.root / "tree.json"
        spec.write_text(
            json.dumps(
                {
                    "name": "tree",
                    "bones": [
                        {"name": "Trunk", "parent": None, "pos": [0, 0, 0]},
                        {"name": "Branch", "parent": "Trunk", "pos": [0, 0.4, 0]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        out = self.root / "tree.glb"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run("entity", [str(out), "--rig", str(spec)])
        self.assertEqual(code, 1)
        self.assertIn("no default part set", stderr.getvalue())


@needs_unitypy
@needs_vkd3d
@needs_trimesh
class EntityBundleTests(unittest.TestCase):
    """The generated entity through the writer's own skinned lane, read back
    with UnityPy — construction evidence the pipeline's own gates demand."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def pack(self, source: Path) -> tuple[bytes, dict[int, list[dict[str, Any]]]]:
        objects = mesh_source_objects(source, set())
        objects.append(shader("Shamway/Unlit"))
        payload = build_bundle(objects, REVISION, "entity.unity3d")
        written = self.root / "entity.unity3d"
        written.write_bytes(payload)
        return payload, read_objects(written)

    def test_generated_entity_is_a_skinned_prefab(self) -> None:
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out)]), 0)
        _payload, trees = self.pack(out)
        self.assertIn(SKINNED_MESH_RENDERER, trees)
        self.assertNotIn(MESH_RENDERER, trees)
        self.assertNotIn(MESH_FILTER, trees)
        smr = trees[SKINNED_MESH_RENDERER][0]
        self.assertEqual(len(smr["m_Bones"]), 20)
        self.assertNotEqual(smr["m_RootBone"]["m_PathID"], 0)
        mesh_tree = trees[MESH][0]
        self.assertEqual(len(mesh_tree["m_BindPose"]), 20)
        self.assertEqual(len(mesh_tree["m_BoneNameHashes"]), 20)

    def test_bones_bind_by_the_hash_of_their_transform_paths(self) -> None:
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out)]), 0)
        _payload, trees = self.pack(out)
        mesh_tree = trees[MESH][0]
        scene = parse_gltf(out)
        expected = [
            bone_name_hash(bone_transform_path(scene, joint)) for joint in scene.skins[0].joints
        ]
        self.assertEqual(list(mesh_tree["m_BoneNameHashes"]), expected)
        # Leaf names are not what Unity stores: Hips is Root/Hips on this rig
        # (there is no Origin node; the path is the authored ancestor chain).
        self.assertEqual(bone_name_hash("Root"), mesh_tree["m_BoneNameHashes"][0])
        self.assertEqual(bone_name_hash("Root/Hips"), mesh_tree["m_BoneNameHashes"][1])
        self.assertNotEqual(bone_name_hash("Hips"), mesh_tree["m_BoneNameHashes"][1])

    def test_joint_game_objects_keep_their_names_and_tree(self) -> None:
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out)]), 0)
        _payload, trees = self.pack(out)
        gos = {item["m_Name"]: item for item in trees[GAME_OBJECT]}
        self.assertIn("Root", gos)
        self.assertIn("Hips", gos)
        self.assertIn("LeftForearm", gos)
        self.assertIn("RightFoot", gos)
        self.assertIn("body", gos)  # the skinned mesh node
        self.assertIn("creature", gos)  # the prefab root the engine resolves by stem
        transforms = trees[TRANSFORM]
        # 20 joints + the skinned mesh node + the prefab root.
        self.assertEqual(len(transforms), 22)

    def test_vertex_data_carries_joints_and_weights_channels(self) -> None:
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out)]), 0)
        _payload, trees = self.pack(out)
        mesh_tree = trees[MESH][0]
        channels = mesh_tree["m_VertexData"]["m_Channels"]
        self.assertEqual(4, channels[12]["dimension"])  # JOINTS
        self.assertEqual(0, channels[12]["format"])
        self.assertEqual(4, channels[13]["dimension"])  # WEIGHTS
        self.assertEqual(10, channels[13]["format"])


if __name__ == "__main__":
    unittest.main()
