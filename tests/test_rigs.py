"""Rig authoring: spec validation, the humanoid template, armature emission.

The armature GLB is read back with `gltf_scene.parse_gltf` — the same reader
the bundle writer uses — so an acceptance here is exactly what the skinned
lane will consume. The matrix spot-checks are hand-computed expectations
(sums of local translations, a 90-degree rotation), independent of the
module's own helpers.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.bundle_writer import bone_name_hash
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.generators import run
from sevendtd_asset_pipeline.gltf_scene import parse_gltf
from sevendtd_asset_pipeline.rigs import Rig, load_rig, rig_to_glb, scaled

HUMANOID_BONE_COUNT = 20


def spec(*bones: dict[str, Any], name: str = "testRig") -> dict[str, Any]:
    """A rig spec document from bone entries, with a valid default."""

    def entry(bone: dict[str, Any]) -> dict[str, Any]:
        out = {
            "name": bone["name"],
            "parent": bone.get("parent"),
            "pos": bone.get("pos", [0, 0, 0]),
        }
        for key in ("rot", "scale"):
            if key in bone:
                out[key] = bone[key]
        return out

    return {"name": name, "bones": [entry(bone) for bone in bones]}


def write_spec(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _mul4(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[i * 4 + r] * b[c * 4 + i] for i in range(4)) for c in range(4) for r in range(4)]


def _trs4(
    t: tuple[float, float, float], r: tuple[float, float, float, float], s: float
) -> list[float]:
    x, y, z, w = r
    xx, yy, zz, xy, xz, yz, wx, wy, wz = (
        x * x,
        y * y,
        z * z,
        x * y,
        x * z,
        y * z,
        w * x,
        w * y,
        w * z,
    )
    return [
        (1 - 2 * (yy + zz)) * s,
        2 * (xy + wz) * s,
        2 * (xz - wy) * s,
        0.0,
        2 * (xy - wz) * s,
        (1 - 2 * (xx + zz)) * s,
        2 * (yz + wx) * s,
        0.0,
        2 * (xz + wy) * s,
        2 * (yz - wx) * s,
        (1 - 2 * (xx + yy)) * s,
        0.0,
        t[0],
        t[1],
        t[2],
        1.0,
    ]


def _world_from_nodes(scene: Any, index: int) -> list[float]:
    """World matrix of a node by re-walking the parsed hierarchy."""
    parent: dict[int, int] = {}
    for node in scene.nodes:
        for child in node.children:
            parent[child] = node.index
    chain: list[int] = []
    cursor: int | None = index
    while cursor is not None:
        chain.append(cursor)
        cursor = parent.get(cursor)
    matrix = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    for node_index in reversed(chain):
        node = scene.nodes[node_index]
        matrix = _mul4(
            matrix,
            _trs4(node.translation, node.rotation, node.scale[0]),
        )
    return matrix


class RigValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def expect_error(self, document: dict[str, Any], fragment: str) -> None:
        path = write_spec(self.tmp / "rig.json", document)
        with self.assertRaisesRegex(PipelineError, fragment):
            load_rig(path)

    def test_empty_bones_are_refused(self) -> None:
        self.expect_error({"name": "r", "bones": []}, "non-empty")

    def test_duplicate_names_are_refused(self) -> None:
        self.expect_error(
            spec({"name": "A"}, {"name": "A", "parent": "A"}), "duplicate bone name 'A'"
        )

    def test_two_roots_are_refused(self) -> None:
        self.expect_error(spec({"name": "A"}, {"name": "B"}), "exactly one root bone")

    def test_unknown_parent_is_refused(self) -> None:
        self.expect_error(
            spec({"name": "A"}, {"name": "B", "parent": "Ghost"}), "unknown parent 'Ghost'"
        )

    def test_cycle_detection_reaches_the_walk(self) -> None:
        # A multi-node cycle always has no bone with parent null, so the
        # one-root check catches it first. The only cycle that gets past that
        # check is a bone that is its own parent, and it must be caught here
        # rather than by an infinite walk.
        self.expect_error(spec({"name": "A"}, {"name": "B", "parent": "B"}), "cyclic")

    def test_cycle_detection_is_robust(self) -> None:
        document = {
            "name": "r",
            "bones": [
                {"name": "A", "parent": None, "pos": [0, 0, 0]},
                {"name": "B", "parent": "A", "pos": [0, 0, 0]},
                {"name": "C", "parent": "B", "pos": [0, 0, 0]},
                {"name": "D", "parent": "C", "pos": [0, 0, 0]},
                {"name": "E", "parent": "B", "pos": [0, 0, 0]},
            ],
        }
        # No cycle: E hangs off B. The validator must not reject it.
        rig = load_rig(write_spec(self.tmp / "ok.json", document))
        self.assertEqual(rig.index("E"), 4)

    def test_non_finite_pos_is_refused(self) -> None:
        self.expect_error(
            {"name": "r", "bones": [{"name": "A", "parent": None, "pos": [0, float("nan"), 0]}]},
            "non-finite",
        )

    def test_non_unit_quat_is_refused(self) -> None:
        self.expect_error(
            {
                "name": "r",
                "bones": [{"name": "A", "parent": None, "pos": [0, 0, 0], "rot": [1, 1, 1, 1]}],
            },
            "not a unit quaternion",
        )

    def test_bad_pos_shape_is_refused(self) -> None:
        self.expect_error(
            {"name": "r", "bones": [{"name": "A", "parent": None, "pos": [0, 0]}]},
            r"must be \[x, y, z\]",
        )

    def test_non_positive_scale_is_refused(self) -> None:
        self.expect_error(
            {"name": "r", "bones": [{"name": "A", "parent": None, "pos": [0, 0, 0], "scale": 0}]},
            "scale must be a positive number",
        )

    def test_bad_json_is_refused(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "not valid JSON"):
            load_rig(path)


class HumanoidTemplateTests(unittest.TestCase):
    def test_named_template_loads(self) -> None:
        rig = load_rig("humanoid")
        self.assertEqual(rig.name, "humanoid")
        self.assertEqual(len(rig.bones), HUMANOID_BONE_COUNT)
        self.assertEqual(rig.root().name, "Root")

    def test_hierarchy_is_the_expected_tree(self) -> None:
        rig = load_rig("humanoid")
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["Hips"].parent, "Root")
        self.assertEqual(by_name["Spine"].parent, "Hips")
        self.assertEqual(by_name["Head"].parent, "Neck")
        self.assertEqual(by_name["LeftHand"].parent, "LeftForearm")
        self.assertEqual(by_name["RightFoot"].parent, "RightShin")

    def test_every_parent_is_a_bone(self) -> None:
        rig = load_rig("humanoid")
        names = {bone.name for bone in rig.bones}
        for bone in rig.bones:
            if bone.parent is not None:
                self.assertIn(bone.parent, names)

    def test_template_positions_are_reasonable(self) -> None:
        rig = load_rig("humanoid")
        by_name = {bone.name: bone for bone in rig.bones}
        # Feet rest just above the root; the head tops out around 1.6 m.
        self.assertLess(by_name["LeftFoot"].pos[1], 0.0)
        head_height = 0.0
        cursor: str | None = "Head"
        while cursor is not None:
            head_height += by_name[cursor].pos[1]
            cursor = by_name[cursor].parent
        self.assertAlmostEqual(head_height, 1.59, places=2)


class AnimalRigTests(unittest.TestCase):
    """The shipped non-humanoid rigs: structure, size variants, and `scale`."""

    QUADRUPED_BONES = 19

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_quadruped_is_a_four_legged_animal(self) -> None:
        rig = load_rig("quadruped")
        self.assertEqual(rig.name, "quadruped")
        self.assertEqual(len(rig.bones), self.QUADRUPED_BONES)
        self.assertEqual(rig.scale, 1.0)
        self.assertEqual(rig.root().name, "Root")
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["Pelvis"].parent, "Root")
        self.assertEqual(by_name["Tail"].parent, "Pelvis")
        self.assertEqual(by_name["LeftFrontUpper"].parent, "Chest")
        self.assertEqual(by_name["LeftFrontPaw"].parent, "LeftFrontLower")
        self.assertEqual(by_name["RightRearUpper"].parent, "Pelvis")
        self.assertEqual(by_name["RightRearPaw"].parent, "RightRearLower")

    def test_quadruped_size_variants_scale_the_base(self) -> None:
        medium = load_rig("quadruped")
        small = load_rig("quadruped-small")
        large = load_rig("quadruped-large")
        self.assertEqual(small.name, "quadruped-small")
        self.assertAlmostEqual(small.scale, 0.45)
        self.assertAlmostEqual(large.scale, 1.5)
        self.assertEqual([bone.name for bone in small.bones], [bone.name for bone in medium.bones])
        pelvis = small.index("Pelvis")
        self.assertAlmostEqual(small.bones[pelvis].pos[1], 0.6 * 0.45, places=4)
        chest = large.index("Chest")
        self.assertAlmostEqual(large.bones[chest].pos[1], 0.1 * 1.5, places=4)

    def test_bird_has_wings_and_legs(self) -> None:
        rig = load_rig("bird")
        self.assertEqual(len(rig.bones), self.QUADRUPED_BONES)
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["LeftWingUpper"].parent, "Chest")
        self.assertEqual(by_name["LeftWingTip"].parent, "LeftWingLower")
        self.assertEqual(by_name["RightFoot"].parent, "RightLegLower")
        self.assertEqual(by_name["Tail"].parent, "Pelvis")

    def test_dinosaur_is_a_bipedal_theropod(self) -> None:
        rig = load_rig("dinosaur")
        self.assertEqual(len(rig.bones), 19)
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["Tail2"].parent, "Tail1")
        self.assertEqual(by_name["Tail3"].parent, "Tail2")
        self.assertEqual(by_name["LeftThigh"].parent, "Pelvis")
        self.assertEqual(by_name["LeftFoot"].parent, "LeftShin")
        # The tiny arms hang off the chest, well behind the head.
        self.assertEqual(by_name["LeftArm"].parent, "Chest")
        self.assertEqual(by_name["LeftForearm"].parent, "LeftArm")

    def test_arachnid_has_eight_legs(self) -> None:
        rig = load_rig("arachnid")
        self.assertEqual(len(rig.bones), 29)
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["Abdomen"].parent, "Prosoma")
        self.assertEqual(by_name["LeftPedipalp"].parent, "Prosoma")
        for side in ("Left", "Right"):
            for index in range(1, 5):
                upper = f"{side}Leg{index}Upper"
                middle = f"{side}Leg{index}Middle"
                lower = f"{side}Leg{index}Lower"
                self.assertEqual(by_name[upper].parent, "Prosoma", upper)
                self.assertEqual(by_name[middle].parent, upper, middle)
                self.assertEqual(by_name[lower].parent, middle, lower)

    def test_crocodile_is_long_and_low(self) -> None:
        rig = load_rig("crocodile")
        self.assertEqual(len(rig.bones), 22)
        by_name = {bone.name: bone for bone in rig.bones}
        self.assertEqual(by_name["Spine2"].parent, "Spine1")
        self.assertEqual(by_name["Chest"].parent, "Spine2")
        self.assertEqual(by_name["Head"].parent, "Neck")
        self.assertEqual(by_name["Tail3"].parent, "Tail2")
        self.assertEqual(by_name["LeftFrontUpper"].parent, "Chest")
        self.assertEqual(by_name["LeftRearUpper"].parent, "Pelvis")

    def test_a_rig_cannot_extend_itself(self) -> None:
        path = write_spec(
            self.tmp / "selfie.json", {"name": "selfie", "base": str(self.tmp / "selfie.json")}
        )
        with self.assertRaisesRegex(PipelineError, "base chain"):
            load_rig(path)

    def test_a_spec_scale_must_be_positive(self) -> None:
        for value in (0, -1, "big"):
            with self.subTest(value):
                path = write_spec(
                    self.tmp / "bad.json",
                    {"name": "bad", "scale": value, "bones": [{"name": "A", "parent": None}]},
                )
                with self.assertRaisesRegex(PipelineError, "must be a"):
                    load_rig(path)

    def test_scaled_resizes_positions_and_scale_together(self) -> None:
        rig = load_rig("quadruped")
        double = scaled(rig, 2.0)
        self.assertAlmostEqual(double.scale, 2.0)
        pelvis = double.index("Pelvis")
        self.assertAlmostEqual(double.bones[pelvis].pos[1], 1.2, places=4)
        # A second call compounds, exactly like --scale on a size variant.
        quadruple = scaled(double, 2.0)
        self.assertAlmostEqual(quadruple.scale, 4.0)


class ArmatureRoundTripTests(unittest.TestCase):
    """The emitted GLB must parse with the writer's own reader, and its
    matrices must agree with hand-computed expectations."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def parse(self, rig: Rig) -> Any:
        path = self.tmp / "armature.glb"
        path.write_bytes(rig_to_glb(rig))
        return parse_gltf(path)

    def test_humanoid_round_trip(self) -> None:
        rig = load_rig("humanoid")
        scene = self.parse(rig)
        self.assertEqual(len(scene.nodes), HUMANOID_BONE_COUNT)
        self.assertEqual([node.name for node in scene.nodes], [bone.name for bone in rig.bones])
        self.assertEqual(len(scene.skins), 1)
        skin = scene.skins[0]
        self.assertEqual(skin.joints, tuple(range(HUMANOID_BONE_COUNT)))
        self.assertEqual(len(skin.inverse_bind), HUMANOID_BONE_COUNT)
        self.assertEqual(scene.roots, (rig.index(rig.root().name),))
        self.assertEqual(skin.skeleton, rig.index("Root"))

    def test_hierarchy_survives(self) -> None:
        rig = load_rig("humanoid")
        scene = self.parse(rig)
        parent: dict[int, int] = {}
        for node in scene.nodes:
            for child in node.children:
                parent[child] = node.index
        for bone in rig.bones:
            index = rig.index(bone.name)
            expected = None if bone.parent is None else rig.index(bone.parent)
            self.assertEqual(parent.get(index), expected, bone.name)
            self.assertEqual(
                set(scene.nodes[index].children),
                {
                    rig.index(candidate.name)
                    for candidate in rig.bones
                    if candidate.parent == bone.name
                },
                bone.name,
            )

    def test_inverse_bind_matrices_are_exact_inverses(self) -> None:
        rig = load_rig("humanoid")
        scene = self.parse(rig)
        skin = scene.skins[0]
        identity = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
        for joint, ibm in zip(skin.joints, skin.inverse_bind, strict=True):
            world = _world_from_nodes(scene, joint)
            product = _mul4(world, list(ibm))
            for value, want in zip(product, identity, strict=True):
                self.assertAlmostEqual(value, want, places=5)

    def test_translation_columns_match_hand_computed_world_positions(self) -> None:
        """The IBM translation column is -world-position for a rigid transform.

        Hand-computed: with identity rotations the world position is the sum of
        local positions up the chain. Hips = (0, 0.98, 0); Head = (0, 1.59, 0);
        LeftHand = (-0.69, 1.47, 0).
        """
        rig = load_rig("humanoid")
        scene = self.parse(rig)
        skin = scene.skins[0]
        ibm_by_name = {
            scene.nodes[joint].name: list(ibm)
            for joint, ibm in zip(skin.joints, skin.inverse_bind, strict=True)
        }
        for name, expected in {
            "Hips": (0.0, 0.98, 0.0),
            "Head": (0.0, 1.59, 0.0),
            "LeftHand": (-0.69, 1.47, 0.0),
            "RightFoot": (0.09, 0.06, 0.0),
        }.items():
            matrix = ibm_by_name[name]
            self.assertAlmostEqual(matrix[12], -expected[0], places=4, msg=name)
            self.assertAlmostEqual(matrix[13], -expected[1], places=4, msg=name)
            self.assertAlmostEqual(matrix[14], -expected[2], places=4, msg=name)

    def test_rotation_is_serialized(self) -> None:
        """A 90-degree twist about Z on the hand rotates the *finger's* offset.

        A node's own rotation moves nothing of itself — it transforms the space
        its children live in. So Hand sits at (0.3, 0, 0) (the arm's 0.1 plus
        its own 0.2), and Finger — 0.05 m along the hand's +X — lands at
        (0.3, 0.05, 0) once the twist is composed in.
        """
        rig = load_rig(
            write_spec(
                self.tmp / "rotated.json",
                spec(
                    {"name": "Root"},
                    {"name": "Arm", "parent": "Root", "pos": [0.1, 0, 0]},
                    {
                        "name": "Hand",
                        "parent": "Arm",
                        "pos": [0.2, 0, 0],
                        "rot": [0, 0, 0.7071068, 0.7071068],
                    },
                    {"name": "Finger", "parent": "Hand", "pos": [0.05, 0, 0]},
                ),
            )
        )
        scene = self.parse(rig)
        by_name = {node.name: node.index for node in scene.nodes}
        for name, expected in {
            "Arm": (0.1, 0.0, 0.0),
            "Hand": (0.3, 0.0, 0.0),
            "Finger": (0.3, 0.05, 0.0),
        }.items():
            world = _world_from_nodes(scene, by_name[name])
            self.assertAlmostEqual(world[12], expected[0], places=4, msg=name)
            self.assertAlmostEqual(world[13], expected[1], places=4, msg=name)
            self.assertAlmostEqual(world[14], expected[2], places=4, msg=name)


class GeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generate_rig_writes_a_parseable_armature(self) -> None:
        out = self.tmp / "armature.glb"
        self.assertEqual(run("rig", [str(out)]), 0)
        scene = parse_gltf(out)
        self.assertEqual(len(scene.skins), 1)
        self.assertEqual(len(scene.nodes), HUMANOID_BONE_COUNT)

    def test_generate_rig_accepts_a_custom_spec(self) -> None:
        spec_path = write_spec(
            self.tmp / "myRig.json",
            spec(
                {"name": "Trunk"},
                {"name": "Branch", "parent": "Trunk", "pos": [0, 0.3, 0]},
                {"name": "Twig", "parent": "Branch", "pos": [0.1, 0, 0]},
            ),
        )
        out = self.tmp / "tree.glb"
        self.assertEqual(run("rig", [str(out), "--rig", str(spec_path)]), 0)
        scene = parse_gltf(out)
        self.assertEqual([node.name for node in scene.nodes], ["Trunk", "Branch", "Twig"])
        self.assertEqual(scene.skins[0].skeleton, 0)

    def test_generate_rig_refuses_a_missing_spec(self) -> None:
        out = self.tmp / "x.glb"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run("rig", [str(out), "--rig", str(self.tmp / "nope.json")])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", stderr.getvalue())

    def test_generate_rig_prints_the_bone_table(self) -> None:
        out = self.tmp / "armature.glb"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(run("rig", [str(out)]), 0)
        text = stdout.getvalue()
        self.assertIn(f"wrote {out}", text)
        self.assertIn("root: Root", text)
        self.assertIn("Hips", text)


class BoneHashCompatibilityTests(unittest.TestCase):
    """The writer stores crc32 of each joint name on the Mesh (`m_BoneNameHashes`)
    and the same digest as `m_RootBoneNameHash`. So the hash the template's
    names produce must be crc32 of those exact strings, or the two copies of
    the name (GameObject vs mesh field) disagree. Note this repository's own
    skinned fixtures hash their joint names as-authored — `hips` in
    test_editorless_prefabs — so casing is preserved end to end."""

    def test_every_template_bone_hashes_to_its_own_digest(self) -> None:
        import zlib

        rig = load_rig("humanoid")
        for bone in rig.bones:
            with self.subTest(bone.name):
                self.assertEqual(
                    bone_name_hash(bone.name),
                    zlib.crc32(bone.name.encode("utf-8")) & 0xFFFFFFFF,
                )


if __name__ == "__main__":
    unittest.main()
