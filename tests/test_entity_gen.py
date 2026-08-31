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
    CAPSULE_COLLIDER,
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
        self.assertIn('name="UserSpawnType" value="Menu"', fragment)
        self.assertIn("</configs>", fragment)

    def test_an_animated_creature_is_a_real_spawnable_animal(self) -> None:
        """`--anim` makes the class a concrete EntityAlive, not a bare stub:
        Class names the C# animal type, IsAnimalEntity/Faction let the game's
        spawner and AI treat it as one, and a slow MoveSpeed is emitted so a
        generated creature walks at a visible pace. The class is the mod's own
        (default EntityAnimalSnake — not a stock animal's own type, which would
        inherit a pre-authored model/physics body the rig does not have)."""
        fragment = entity_xml(
            "myCreature",
            "MyMod",
            "myMod",
            "creature",
            avatar_controller="GameObjectAnimalAnimation",
        )
        self.assertIn('name="Class" value="EntityAnimalSnake"', fragment)
        self.assertIn('name="IsAnimalEntity" value="true"', fragment)
        self.assertIn('name="Faction" value="animals"', fragment)
        self.assertIn('name="AvatarController" value="GameObjectAnimalAnimation"', fragment)
        self.assertIn('name="MoveSpeed" value="1.5"', fragment)
        # No borrowed stock physics body: grounding comes from the Physics-node
        # capsule the writer emits, not from a Stag layout of stag bone paths.
        self.assertNotIn("PhysicsBody", fragment)

    def test_entity_class_and_minimal_opt_out(self) -> None:
        """`--entity-class` overrides the C# type; `--minimal-entity` emits the
        bare stub (a class with no entity type is not spawnable, kept only for
        special cases)."""
        from sevendtd_asset_pipeline.generators.entity import entity_xml

        custom = entity_xml(
            "myCreature",
            "M",
            "b",
            "creature",
            avatar_controller="GameObjectAnimalAnimation",
            entity_class="EntityAnimalRabbit",
        )
        self.assertIn('name="Class" value="EntityAnimalRabbit"', custom)
        minimal = entity_xml(
            "myCreature",
            "M",
            "b",
            "creature",
            avatar_controller="GameObjectAnimalAnimation",
            minimal=True,
        )
        self.assertNotIn('name="Class"', minimal)
        self.assertNotIn("PhysicsBody", minimal)

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
                # Root gets no part. Other bones may be joints without a
                # mesh (arachnid Middle, crocodile Lower) so they do not
                # hang a second set of limbs.
                bone_names = {bone.name for bone in rig.bones}
                self.assertNotIn("Root", parts, name)
                self.assertTrue(parts, name)
                self.assertTrue(set(parts) <= bone_names, name)

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

    def test_atlas_remaps_each_part_into_its_own_cell(self) -> None:
        """`--atlas` confines each part's UVs to its own cell of a square grid,
        so a hide can paint each region its own colour. Every vertex must land
        inside exactly one cell, and the manifest must name the same cells."""
        out = self.root / "creature.glb"
        manifest = self.root / "creature.atlas.json"
        self.assertEqual(
            run("entity", [str(out), "--rig", "quadruped", "--atlas", str(manifest)]), 0
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        scene = parse_gltf(out)
        uvs = scene.meshes[0].primitive.uvs
        assert uvs is not None
        cells = document["parts"]
        roles = document["roles"]

        def inside(uv: tuple[float, float], cell: tuple[float, float, float, float]) -> bool:
            u0, v0, u1, v1 = cell
            # The mesh insets each cell by 2% so a UV never rides the shared
            # gutter; tolerate float32 rounding at the inset boundary.
            eps = 2e-3
            lo_u, hi_u = u0 + 0.02 * (u1 - u0) - eps, u1 - 0.02 * (u1 - u0) + eps
            lo_v, hi_v = v0 + 0.02 * (v1 - v0) - eps, v1 - 0.02 * (v1 - v0) + eps
            return lo_u <= uv[0] <= hi_u and lo_v <= uv[1] <= hi_v

        for uv in uvs:
            matches = [name for name, cell in cells.items() if inside(uv, cell)]
            self.assertEqual(len(matches), 1, f"UV {uv} landed in {len(matches)} cells")
        # The paw parts exist and are classified apart from the body — the
        # discrimination the atlas exists to enable.
        self.assertEqual(roles["LeftFrontPaw"], "paw")
        self.assertEqual(roles["Pelvis"], "body")
        self.assertNotEqual(roles["LeftFrontPaw"], roles["Pelvis"])


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
        self.assertIn("Physics", gos)  # the grounding-capsule node the engine reads
        transforms = trees[TRANSFORM]
        # 20 joints + the skinned mesh node + the prefab root + the Physics node.
        self.assertEqual(len(transforms), 23)

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

    def test_grounding_capsule_bottom_sits_at_the_feet(self) -> None:
        """The engine grounds an entity by its CharacterController capsule, and
        reads it off a `Physics` child of the model root: `Entity::PhysicsInit`
        does `RootTransform.Find("Physics")`, then `AddCharacterController`
        reads that node's CapsuleCollider and calls `SetSize`. So the generated
        prefab must carry a `Physics` child, direct under the prefab root, whose
        capsule's bottom (`center.y - height/2`) is at the mesh's lowest point —
        that is what stops the `the legs clip into the ground` settle-onto-the-
        torso read."""
        out = self.root / "creature.glb"
        self.assertEqual(run("entity", [str(out)]), 0)
        _payload, trees = self.pack(out)

        def hierarchy(bundle: Path) -> dict[str, dict[str, Any]]:
            """Map each GO name to its world transform, by UnityPy path_id.

            Inside one bundle, a Transform's `m_GameObject.m_PathID` equals its
            owning GameObject's own path_id, and a GameObject's
            `m_Component[*].component.m_PathID` equals that component's path_id
            — the two agree only via UnityPy's path_id, not the re-indexed
            typetree, so the correlation has to be done on the parsed objects.
            """
            import UnityPy

            names: dict[int, str] = {}
            transforms: dict[int, dict[str, Any]] = {}
            for obj in UnityPy.load(str(bundle)).objects:
                tree = obj.read_typetree()
                if int(obj.type.value) == GAME_OBJECT:
                    names[obj.path_id] = tree["m_Name"]
                elif int(obj.type.value) == TRANSFORM:
                    transforms[obj.path_id] = tree
            out: dict[str, dict[str, Any]] = {}
            for go_id, name in names.items():
                matched = next(
                    (
                        (tid, t)
                        for tid, t in transforms.items()
                        if t["m_GameObject"]["m_PathID"] == go_id
                    ),
                    (None, None),
                )
                out[name] = {"transform": matched[1], "transform_id": matched[0]}
            return out

        bundle = self.root / "entity.unity3d"
        hier = hierarchy(bundle)
        physics_transform = hier["Physics"]["transform"]
        root_transform = hier["creature"]["transform"]
        assert physics_transform is not None
        assert root_transform is not None
        # Physics is a direct child of the prefab root, as the real animals have
        # it, so the engine's `RootTransform.Find("Physics")` resolves it.
        # `m_Father.m_PathID` is the parent Transform's component id.
        self.assertEqual(
            physics_transform["m_Father"]["m_PathID"], hier["creature"]["transform_id"]
        )
        self.assertEqual(physics_transform["m_LocalPosition"]["y"], 0.0)
        # The prefab root directly lists the Physics node as a child, so the
        # engine's `RootTransform.Find("Physics")` resolves it.
        root_child_paths = {c["m_PathID"] for c in root_transform["m_Children"]}
        self.assertIn(hier["Physics"]["transform_id"], root_child_paths)

        # The capsule bottom is at the mesh's feet (min y of the authored mesh).
        capsules = trees[CAPSULE_COLLIDER]
        self.assertEqual(len(capsules), 1)
        cap = capsules[0]
        self.assertEqual(cap["m_Direction"], 1)
        bottom = cap["m_Center"]["y"] - cap["m_Height"] / 2.0
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        feet_y = min(point[1] for point in primitive.positions)
        self.assertAlmostEqual(bottom, feet_y, places=3)

        # An animated entity keeps the Physics node under the root, not swept
        # into the figure the animation wraps the model bones in.
        animated = self.root / "animated.glb"
        self.assertEqual(run("entity", [str(animated), "--anim", "idle,walk"]), 0)
        self.pack(animated)
        hier2 = hierarchy(bundle)
        # The animated prefab root is the GLB stem (`animated`), not `creature`.
        self.assertEqual(
            hier2["Physics"]["transform"]["m_Father"]["m_PathID"],
            hier2["animated"]["transform_id"],
        )
        # The animated root keeps both the figure (the animation carrier) and
        # the Physics node as direct children — the Physics node is not swept
        # under the figure, which it would be if the figure wrap re-parented it.
        root2 = hier2["animated"]["transform"]
        root2_child_paths = {c["m_PathID"] for c in root2["m_Children"]}
        self.assertIn(hier2["figure"]["transform_id"], root2_child_paths)
        self.assertIn(hier2["Physics"]["transform_id"], root2_child_paths)


class CylinderWindingTests(unittest.TestCase):
    """A generated entity's primitive cylinders must be wound facing OUTWARD.

    The `_cylinder` builder produces side faces plus two cap fans. With the
    material shader's default back-face culling, a side face wound CW from
    outside is culled, so the cylinder's curved body vanishes and only the two
    cap discs draw — a generated quadruped (legs, body, spine and tail are
    cylinders) renders as a couple of floating discs. This pins the side faces
    to outward (CCW from outside, radial normal agrees with the face normal).
    """

    @staticmethod
    def _outward_fraction() -> float:
        from sevendtd_asset_pipeline.generators.entity import _SEGMENTS, _cylinder

        positions, _normals, _uvs, indices = _cylinder(0.5, 1.0)
        faces = indices[: 2 * _SEGMENTS]  # the side faces, before the cap fans
        outward = 0
        for a, b, c in faces:
            ax, ay, az = positions[a]
            bx, by, bz = positions[b]
            cx, _cy, cz = positions[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, _cy - ay, cz - az
            nx, _ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            fx, _fy, fz = (ax + bx + cx) / 3.0, (ay + by + _cy) / 3.0, (az + bz + cz) / 3.0
            # Outward at this face is the radial direction (x, 0, z).
            dot = nx * fx + nz * fz
            if dot > 0:
                outward += 1
        return outward / len(faces)

    def test_cylinder_side_faces_face_outward(self) -> None:
        # Before the fix the side faces were wound inward (0% outward); now
        # every side face must agree with its outward radial direction.
        frac = self._outward_fraction()
        self.assertGreaterEqual(frac, 0.99, f"cylinder side faces outward fraction {frac:.3f}")


class RemainingRigConstructionTests(unittest.TestCase):
    """Each remaining shipped rig meets the quadruped construction bar.

    Skinned GLB, per-part UV atlas with a role map a hide can paint, spawnable
    XML (`Prefab` + `Mesh` + `UserSpawnType`), and `--anim` writing Idle1 + Walk
    beside the mesh. Size morph is `--scale` on the same generator.
    """

    REMAINING = ("bird", "arachnid", "dinosaur", "crocodile", "humanoid")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_each_remaining_rig_is_skinned_atlased_animated_and_spawnable(self) -> None:
        for name in self.REMAINING:
            with self.subTest(name):
                out = self.root / f"{name}.glb"
                manifest = self.root / f"{name}.atlas.json"
                xml = self.root / f"{name}-entityclasses.xml"
                self.assertEqual(
                    run(
                        "entity",
                        [
                            str(out),
                            "--rig",
                            name,
                            "--atlas",
                            str(manifest),
                            "--anim",
                            "idle,head,walk",
                            "--mod",
                            "MyMod",
                            "--bundle",
                            "myMod",
                            "--xml",
                            str(xml),
                        ],
                    ),
                    0,
                )
                scene = parse_gltf(out)
                self.assertEqual(len(scene.skins), 1, name)
                self.assertTrue(scene.skins[0].joints)
                document = json.loads(manifest.read_text(encoding="utf-8"))
                roles = document["roles"]
                self.assertIn("paw", set(roles.values()), name)
                self.assertIn("limb", set(roles.values()), name)
                self.assertIn("body", set(roles.values()), name)
                anim = json.loads((self.root / f"{name}.anim.json").read_text(encoding="utf-8"))
                clip_names = {clip["name"] for clip in anim["clips"]}
                self.assertIn("Idle1", clip_names, name)
                self.assertIn("Walk", clip_names, name)
                text = xml.read_text(encoding="utf-8")
                self.assertIn('name="Prefab"', text)
                self.assertIn('name="Mesh"', text)
                self.assertIn('name="UserSpawnType" value="Menu"', text)

    def test_bird_torso_is_longer_front_to_back_than_tall(self) -> None:
        """A bird body is a keel along Z, not a vertical can of Y-cylinders."""
        out = self.root / "bird-torso.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "bird"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints
        torso = [
            position
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if scene.nodes[skin_joints[joint_row[0]]].name in {"Pelvis", "Spine", "Chest"}
        ]
        self.assertTrue(torso)
        span_z = max(p[2] for p in torso) - min(p[2] for p in torso)
        span_y = max(p[1] for p in torso) - min(p[1] for p in torso)
        self.assertGreater(span_z, span_y)

    def test_bird_feet_meet_the_lower_legs(self) -> None:
        """Lower-leg cylinders span down to the foot boxes; no floating feet."""
        out = self.root / "bird-feet.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "bird"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints

        def verts(name: str) -> list[tuple[float, float, float]]:
            return [
                position
                for position, joint_row in zip(primitive.positions, joints, strict=True)
                if scene.nodes[skin_joints[joint_row[0]]].name == name
            ]

        lower, foot = verts("LeftLegLower"), verts("LeftFoot")
        self.assertTrue(lower and foot)
        self.assertLessEqual(min(p[1] for p in lower), max(p[1] for p in foot) + 0.02)

    def test_bird_wings_span_wider_than_the_legs(self) -> None:
        """Improved bird: wing plates span further outboard than the perch legs.

        The construction-bar bird used matchstick boxes whose |x| barely beat
        the legs; a wing that reads as a wing has a chord and a span, so the
        mesh's wing vertices reach further in X than any leg/foot vertex.
        """
        out = self.root / "bird.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "bird"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints
        wing_x: list[float] = []
        leg_x: list[float] = []
        for position, joint_row in zip(primitive.positions, joints, strict=True):
            bone = scene.nodes[skin_joints[joint_row[0]]].name
            if "Wing" in bone:
                wing_x.append(abs(position[0]))
            elif "Leg" in bone or bone.endswith("Foot"):
                leg_x.append(abs(position[0]))
        self.assertTrue(wing_x and leg_x)
        self.assertGreater(max(wing_x), max(leg_x) * 1.8)

    def test_bird_head_meets_the_neck(self) -> None:
        """The neck box reaches the head joint: no floating-head gap."""
        out = self.root / "bird-neck.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "bird"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints

        def verts(name: str) -> list[tuple[float, float, float]]:
            return [
                position
                for position, joint_row in zip(primitive.positions, joints, strict=True)
                if scene.nodes[skin_joints[joint_row[0]]].name == name
            ]

        neck, head, chest = verts("Neck"), verts("Head"), verts("Chest")
        self.assertTrue(neck and head and chest)
        self.assertGreaterEqual(max(p[2] for p in neck), min(p[2] for p in head) - 0.02)
        self.assertLessEqual(min(p[2] for p in neck), max(p[2] for p in chest) + 0.02)

    def test_crocodile_is_a_long_low_hull(self) -> None:
        """A crocodile is much longer in Z than it is tall, with the tail on the pelvis."""
        out = self.root / "croc-hull.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "crocodile"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        zs = [p[2] for p in primitive.positions]
        ys = [p[1] for p in primitive.positions]
        self.assertGreater(max(zs) - min(zs), (max(ys) - min(ys)) * 3.0)
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints

        def verts(name: str) -> list[tuple[float, float, float]]:
            return [
                position
                for position, joint_row in zip(primitive.positions, joints, strict=True)
                if scene.nodes[skin_joints[joint_row[0]]].name == name
            ]

        tail, pelvis = verts("Tail1"), verts("Pelvis")
        self.assertTrue(tail and pelvis)
        self.assertGreaterEqual(max(p[2] for p in tail), min(p[2] for p in pelvis) - 0.02)
        pelvis_x = max(abs(p[0]) for p in pelvis)
        pelvis_y = max(p[1] for p in pelvis) - min(p[1] for p in pelvis)
        self.assertGreater(pelvis_x * 2, pelvis_y)
        upper = verts("LeftFrontUpper")
        self.assertTrue(upper)
        self.assertGreater(max(abs(p[0]) for p in upper), pelvis_x)
        self.assertFalse(verts("LeftFrontLower"))
        foot = verts("LeftFrontFoot")
        self.assertTrue(foot)
        self.assertGreater(max(abs(p[0]) for p in foot), pelvis_x)
        fang, head = verts("LeftFang"), verts("Head")
        self.assertTrue(fang and head)
        self.assertLess(min(p[1] for p in fang), min(p[1] for p in head))
        chest = verts("Chest")
        self.assertTrue(chest)
        self.assertLess(abs(max(p[1] for p in chest) - max(p[1] for p in pelvis)), 0.15)
        tail = verts("Tail1")
        tail_y = max(p[1] for p in tail) - min(p[1] for p in tail)
        tail_x = max(p[0] for p in tail) - min(p[0] for p in tail)
        self.assertGreater(tail_y, tail_x)
        scute = verts("LeftScute1")
        self.assertTrue(scute)
        self.assertGreater(max(p[1] for p in scute), max(p[1] for p in pelvis) - 0.02)

    def test_crocodile_head_is_a_forward_snout_not_a_vertical_tube(self) -> None:
        """The improved crocodile head is elongated in Z (a snout), not Y."""
        out = self.root / "croc.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "crocodile"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints
        head = [
            position
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if scene.nodes[skin_joints[joint_row[0]]].name == "Head"
        ]
        self.assertTrue(head)
        zs = [p[2] for p in head]
        ys = [p[1] for p in head]
        self.assertGreater(max(zs) - min(zs), (max(ys) - min(ys)) * 2.0)

    def test_part_offset_is_scaled_and_shifts_geometry(self) -> None:
        parts = self.root / "parts.json"
        parts.write_text(
            json.dumps(
                {
                    "parts": {
                        "Head": {
                            "shape": "box",
                            "width": 0.1,
                            "depth": 0.1,
                            "height": 0.1,
                            "offset": [0.0, 0.0, 0.4],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        out = self.root / "offset.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "humanoid", "--parts", str(parts), "--scale", "2"]),
            0,
        )
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        zs = [p[2] for p in primitive.positions]
        # Head sits at ~1.6 m Y; offset 0.4 * scale 2 = 0.8 m local Z.
        self.assertGreater(max(zs), 0.7)

    def test_scale_morph_of_a_shipped_rig_differs_in_size(self) -> None:
        """`--scale` on generate entity is the size morph; no mesh edit."""
        base = self.root / "dino.glb"
        tiny = self.root / "dino-tiny.glb"
        self.assertEqual(run("entity", [str(base), "--rig", "dinosaur"]), 0)
        self.assertEqual(run("entity", [str(tiny), "--rig", "dinosaur", "--scale", "0.4"]), 0)
        base_scene = parse_gltf(base)
        tiny_scene = parse_gltf(tiny)
        base_pelvis = next(node for node in base_scene.nodes if node.name == "Pelvis")
        tiny_pelvis = next(node for node in tiny_scene.nodes if node.name == "Pelvis")
        self.assertAlmostEqual(tiny_pelvis.translation[1], base_pelvis.translation[1] * 0.4)

    def test_idle_includes_an_in_place_walk_and_tail_sway(self) -> None:
        """Staged looks play Idle1: it must march in place, and a croc tail sways."""
        out = self.root / "croc-anim.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "crocodile", "--anim", "idle,head,walk"]), 0
        )
        anim = json.loads((self.root / "croc-anim.anim.json").read_text(encoding="utf-8"))
        idle = [c for c in anim["clips"] if c["name"] == "Idle1"]
        kinds = {c["kind"] for c in idle}
        self.assertIn("walk", kinds)
        self.assertIn("sway", kinds)
        self.assertIn("spin", kinds)
        spin = next(c for c in idle if c["kind"] == "spin")
        self.assertEqual(spin["bone"].rsplit("/", 1)[-1], "Root")
        walk = next(c for c in anim["clips"] if c["name"] == "Walk" and c["kind"] == "sway")
        self.assertTrue(any("Tail" in path for path in walk["bones"]))

    def test_dinosaur_idle_walk_uses_a_full_stride(self) -> None:
        """A staged dino look plays Idle1; 0.75 of 0.4 rad did not read as legs."""
        out = self.root / "dino-gait.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "dinosaur", "--anim", "idle,head,walk"]), 0
        )
        anim = json.loads((self.root / "dino-gait.anim.json").read_text(encoding="utf-8"))
        idle_walk = next(
            clip for clip in anim["clips"] if clip["name"] == "Idle1" and clip["kind"] == "walk"
        )
        self.assertGreaterEqual(idle_walk["amplitude"], 0.5)
        walk = next(
            clip for clip in anim["clips"] if clip["name"] == "Walk" and clip["kind"] == "walk"
        )
        self.assertGreaterEqual(walk["amplitude"], 0.5)

    def test_humanoid_idle_walk_uses_a_full_stride(self) -> None:
        """A staged humanoid look plays Idle1; 0.3 rad of T-pose twist did not read as a walk."""
        out = self.root / "human-gait.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "humanoid", "--anim", "idle,head,walk"]), 0
        )
        anim = json.loads((self.root / "human-gait.anim.json").read_text(encoding="utf-8"))
        idle_walk = next(
            clip for clip in anim["clips"] if clip["name"] == "Idle1" and clip["kind"] == "walk"
        )
        self.assertGreaterEqual(idle_walk["amplitude"], 0.5)
        self.assertTrue(any("Thigh" in path for path in idle_walk["bones"]))
        self.assertTrue(any("Shin" in path for path in idle_walk["lower_bones"]))
        self.assertTrue(any(path.rsplit("/", 1)[-1].endswith("Arm") for path in idle_walk["bones"]))
        walk = next(
            clip for clip in anim["clips"] if clip["name"] == "Walk" and clip["kind"] == "walk"
        )
        self.assertGreaterEqual(walk["amplitude"], 0.5)
        self.assertTrue(any(path.rsplit("/", 1)[-1].endswith("Arm") for path in walk["bones"]))

    def test_humanoid_arms_extend_along_x(self) -> None:
        """Arm boxes follow the X-chain, not a Y-cylinder standing on the shoulder."""
        out = self.root / "human.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "humanoid"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints
        arm_x = [
            abs(position[0])
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if "Arm" in scene.nodes[skin_joints[joint_row[0]]].name
            or "Hand" in scene.nodes[skin_joints[joint_row[0]]].name
        ]
        chest_x = [
            abs(position[0])
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if scene.nodes[skin_joints[joint_row[0]]].name == "Chest"
        ]
        self.assertTrue(arm_x and chest_x)
        self.assertGreater(max(arm_x), max(chest_x) * 1.3)

    def test_dinosaur_body_goes_forward_not_up(self) -> None:
        out = self.root / "dino-body.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "dinosaur"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints

        def named(name: str) -> list[tuple[float, float, float]]:
            return [
                position
                for position, joint_row in zip(primitive.positions, joints, strict=True)
                if scene.nodes[skin_joints[joint_row[0]]].name == name
            ]

        pelvis, chest = named("Pelvis"), named("Chest")
        self.assertTrue(pelvis and chest)
        self.assertGreater(max(p[2] for p in chest), max(p[2] for p in pelvis))
        tail, neck, head = named("Tail1"), named("Neck"), named("Head")
        self.assertTrue(tail and neck and head)
        self.assertGreaterEqual(max(p[2] for p in tail), min(p[2] for p in pelvis) - 0.02)
        self.assertGreaterEqual(max(p[2] for p in neck), min(p[2] for p in head) - 0.02)
        thigh, shin = named("LeftThigh"), named("LeftShin")
        self.assertTrue(thigh and shin)
        self.assertLessEqual(min(p[1] for p in thigh), max(p[1] for p in shin) + 0.02)

    def test_arachnid_abdomen_is_flatter_than_wide(self) -> None:
        out = self.root / "spider.glb"
        self.assertEqual(run("entity", [str(out), "--rig", "arachnid"]), 0)
        scene = parse_gltf(out)
        primitive = scene.meshes[0].primitive
        joints = primitive.joints
        assert joints is not None
        skin_joints = scene.skins[0].joints
        abdomen = [
            position
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if scene.nodes[skin_joints[joint_row[0]]].name == "Abdomen"
        ]
        span_y = max(p[1] for p in abdomen) - min(p[1] for p in abdomen)
        span_x = max(p[0] for p in abdomen) - min(p[0] for p in abdomen)
        self.assertGreater(span_x, span_y * 1.4)
        # Legs splay outboard of the abdomen, not hang as table posts under it.
        leg_x = [
            abs(position[0])
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if "Leg" in scene.nodes[skin_joints[joint_row[0]]].name
        ]
        abdomen_x = [abs(p[0]) for p in abdomen]
        self.assertTrue(leg_x and abdomen_x)
        self.assertGreater(max(leg_x), max(abdomen_x) * 1.3)
        # Middle/Lower hang in Y under the body; meshing them doubled the
        # legs (outboard uppers + hanging children = 16).
        extra = [
            position
            for position, joint_row in zip(primitive.positions, joints, strict=True)
            if "Middle" in scene.nodes[skin_joints[joint_row[0]]].name
        ]
        self.assertFalse(extra)

    def test_creature_one_shot_calls_entity_and_hide(self) -> None:
        """`generate creature` is the easy on-ramp: atlas + anim + hide."""
        if not has_capability("pillow"):
            self.skipTest("the hide half needs Pillow")
        out = self.root / "raptor.glb"
        self.assertEqual(
            run("creature", [str(out), "--rig", "dinosaur", "--coat", "olive", "--seed", "7"]),
            0,
        )
        self.assertTrue(out.is_file())
        self.assertTrue((self.root / "raptor.atlas.json").is_file())
        self.assertTrue((self.root / "raptor.anim.json").is_file())
        albedo = self.root / "raptor_albedo.png"
        self.assertTrue(albedo.is_file())
        self.assertGreater(albedo.stat().st_size, 0)
        anim = json.loads((self.root / "raptor.anim.json").read_text(encoding="utf-8"))
        self.assertEqual({clip["name"] for clip in anim["clips"]}, {"Idle1", "Walk"})


if __name__ == "__main__":
    unittest.main()
