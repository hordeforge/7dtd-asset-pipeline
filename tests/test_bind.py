"""`shamway generate bind` skins an authored mesh onto a shipped rig."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.generators import run
from sevendtd_asset_pipeline.gltf_scene import parse_gltf


class BindGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_refuses_a_missing_source_before_starting_blender(self) -> None:
        out = self.root / "bound.glb"
        code = run("bind", [str(self.root / "nope.glb"), str(out), "--rig", "humanoid"])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())

    def test_refuses_a_non_glb_target(self) -> None:
        source = self.root / "a.glb"
        source.write_bytes(b"not a glb")
        code = run("bind", [str(source), str(self.root / "out.obj"), "--rig", "humanoid"])
        self.assertEqual(code, 1)

    def test_bind_is_byte_stable_and_keeps_generate_entity_bone_paths(self) -> None:
        """Same flags, same bytes. Idle1 names Root/... so the scene root is Root."""
        if not has_capability("blender"):
            self.skipTest("bind needs Blender")
        mesh = self.root / "box.glb"
        self.assertEqual(run("mesh", [str(mesh), "--shape", "box", "--size", "1", "1", "1"]), 0)
        first = self.root / "one.glb"
        second = self.root / "two.glb"
        flags = ["--rig", "humanoid", "--height", "1.6", "--anim"]
        self.assertEqual(run("bind", [str(mesh), str(first), *flags]), 0)
        self.assertEqual(run("bind", [str(mesh), str(second), *flags]), 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        scene = parse_gltf(first)
        self.assertEqual([scene.nodes[i].name for i in scene.roots], ["Root"])
        self.assertTrue(scene.skins)
        self.assertIsNotNone(scene.meshes[0].primitive.uvs)
        anim = first.with_suffix(".anim.json")
        self.assertTrue(anim.is_file())
        text = anim.read_text(encoding="utf-8")
        self.assertIn('"Idle1"', text)
        self.assertIn('"Walk"', text)

    def test_refuses_a_non_positive_stretch(self) -> None:
        source = self.root / "a.glb"
        source.write_bytes(b"not a glb")
        code = run(
            "bind",
            [str(source), str(self.root / "out.glb"), "--rig", "humanoid", "--stretch-y", "0"],
        )
        self.assertEqual(code, 1)

    def test_stretch_changes_bounds_and_double_sided_adds_vertices(self) -> None:
        """A coat swap is not a distinct mesh; --stretch-* changes the vertex set."""
        if not has_capability("blender"):
            self.skipTest("bind needs Blender")
        mesh = self.root / "box.glb"
        self.assertEqual(run("mesh", [str(mesh), "--shape", "box", "--size", "1", "1", "1"]), 0)
        plain = self.root / "plain.glb"
        stretched = self.root / "stretched.glb"
        doubled = self.root / "doubled.glb"
        flags = ["--rig", "humanoid", "--height", "1.6"]
        self.assertEqual(run("bind", [str(mesh), str(plain), *flags]), 0)
        self.assertEqual(run("bind", [str(mesh), str(stretched), *flags, "--stretch-x", "1.3"]), 0)
        self.assertEqual(run("bind", [str(mesh), str(doubled), *flags, "--double-sided"]), 0)
        plain_scene = parse_gltf(plain)
        stretch_scene = parse_gltf(stretched)
        doubled_scene = parse_gltf(doubled)
        self.assertNotEqual(plain.read_bytes(), stretched.read_bytes())
        self.assertGreater(
            max(abs(p[0]) for p in stretch_scene.meshes[0].primitive.positions),
            max(abs(p[0]) for p in plain_scene.meshes[0].primitive.positions),
        )
        self.assertGreater(
            len(doubled_scene.meshes[0].primitive.positions),
            len(plain_scene.meshes[0].primitive.positions),
        )

    def test_refuses_a_negative_neck(self) -> None:
        source = self.root / "a.glb"
        source.write_bytes(b"not a glb")
        code = run(
            "bind",
            [str(source), str(self.root / "out.glb"), "--rig", "humanoid", "--neck", "-0.1"],
        )
        self.assertEqual(code, 1)

    def test_neck_lifts_the_head_and_adds_vertices(self) -> None:
        """`--neck` fills the gap `--head-lift` leaves; origin-lift buried a 7DTD head."""
        if not has_capability("blender"):
            self.skipTest("bind needs Blender")
        body = self.root / "body.glb"
        head = self.root / "head.glb"
        self.assertEqual(
            run(
                "mesh",
                [str(body), "--shape", "box", "--size", "0.4", "0.3", "1.2", "--name", "body"],
            ),
            0,
        )
        self.assertEqual(
            run(
                "mesh",
                [str(head), "--shape", "box", "--size", "0.25", "0.25", "0.3", "--name", "head"],
            ),
            0,
        )
        lifted = self.root / "lifted.glb"
        necked = self.root / "necked.glb"
        flags = ["--rig", "humanoid", "--extra", str(head), "--head-lift"]
        self.assertEqual(run("bind", [str(body), str(lifted), *flags]), 0)
        self.assertEqual(run("bind", [str(body), str(necked), *flags, "--neck", "0.12"]), 0)
        lifted_scene = parse_gltf(lifted)
        necked_scene = parse_gltf(necked)
        lifted_z = [p[1] for p in lifted_scene.meshes[0].primitive.positions]
        necked_z = [p[1] for p in necked_scene.meshes[0].primitive.positions]
        self.assertGreater(max(necked_z), max(lifted_z) + 0.05)
        self.assertGreater(
            len(necked_scene.meshes[0].primitive.positions),
            len(lifted_scene.meshes[0].primitive.positions),
        )
        self.assertTrue(lifted_scene.skins)
        self.assertTrue(necked_scene.skins)

    def test_voxel_fuses_meshes_and_keeps_a_skin(self) -> None:
        """--voxel remeshes overlapping extras into one surface with weights."""
        if not has_capability("blender"):
            self.skipTest("bind needs Blender")
        body = self.root / "body.glb"
        extra = self.root / "extra.glb"
        self.assertEqual(
            run(
                "mesh",
                [str(body), "--shape", "box", "--size", "0.4", "0.3", "1.2", "--name", "body"],
            ),
            0,
        )
        self.assertEqual(
            run(
                "mesh",
                [str(extra), "--shape", "box", "--size", "0.5", "0.4", "1.0", "--name", "extra"],
            ),
            0,
        )
        joined = self.root / "joined.glb"
        fused = self.root / "fused.glb"
        flags = ["--rig", "humanoid", "--extra", str(extra)]
        self.assertEqual(run("bind", [str(body), str(joined), *flags]), 0)
        self.assertEqual(run("bind", [str(body), str(fused), *flags, "--voxel", "0.08"]), 0)
        fused_scene = parse_gltf(fused)
        self.assertTrue(fused_scene.skins)
        self.assertNotEqual(joined.read_bytes(), fused.read_bytes())
        self.assertGreater(len(fused_scene.meshes[0].primitive.positions), 8)

    def test_hip_band_is_not_weighted_to_thighs(self) -> None:
        """Idle1 walk crumples the butt if heat-weight leaves glutes on Thigh.

        The pelvis pins to Hips; the thigh/shin/foot *shafts* keep their
        bones. A height slab that ate the upper thigh made jello legs with
        stiff shins (Idle1 swings Thigh, Shin has no verts).
        """
        if not has_capability("blender"):
            self.skipTest("bind needs Blender")
        mesh = self.root / "box.glb"
        self.assertEqual(
            run("mesh", [str(mesh), "--shape", "box", "--size", "0.4", "0.3", "1.6"]),
            0,
        )
        out = self.root / "human.glb"
        self.assertEqual(
            run("bind", [str(mesh), str(out), "--rig", "humanoid", "--height", "1.6"]),
            0,
        )
        scene = parse_gltf(out)
        prim = scene.meshes[0].primitive
        joints = prim.joints
        weights = prim.weights
        self.assertIsNotNone(joints)
        self.assertIsNotNone(weights)
        assert joints is not None
        assert weights is not None
        spans = [
            (max(p[axis] for p in prim.positions) - min(p[axis] for p in prim.positions), axis)
            for axis in range(3)
        ]
        up = max(spans)[1]
        lo = min(p[up] for p in prim.positions)
        hi = max(p[up] for p in prim.positions)
        # Top 45% is chest/head, not thigh. A box's corners miss the
        # shafts; shin/foot paint is gated on the voxel-fused mesh.
        high = lo + 0.55 * (hi - lo)
        names = [scene.nodes[joint].name for joint in scene.skins[0].joints]
        thigh = {i for i, name in enumerate(names) if "Thigh" in name}
        self.assertTrue(thigh)
        sampled = 0
        thigh_on_torso = 0
        for pos, joint_row, weight_row in zip(prim.positions, joints, weights, strict=True):
            if pos[up] < high:
                continue
            sampled += 1
            thigh_w = sum(
                weight for j, weight in zip(joint_row, weight_row, strict=True) if j in thigh
            )
            if thigh_w > 0.05:
                thigh_on_torso += 1
        self.assertGreater(sampled, 0)
        self.assertEqual(thigh_on_torso, 0)
