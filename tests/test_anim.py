"""Legacy animation clips for generated entities: serialization round-trip.

A legacy `AnimationClip` carries its curves directly (m_MuscleClipSize = 0,
measured from the game's own animals.bundle), so a clip dict serializes
through the writer's type-tree walk and must come back through UnityPy —
which parses Unity's format with none of this repository's code — with the
curves, the legacy flag and the empty compiled stream intact.
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.anim import (
    animation_component,
    idle_bob_curves,
    legacy_clip,
    rotation_curve,
)
from sevendtd_asset_pipeline.bundle_writer import BundleObject, build_bundle
from sevendtd_asset_pipeline.capabilities import has_capability

REVISION = "2022.3.62f2"
needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"), "the writer needs UnityPy for the engine's type trees"
)


def read_objects(bundle: Path) -> dict[int, list[dict[str, Any]]]:
    import UnityPy

    found: dict[int, list[dict[str, Any]]] = {}
    for obj in UnityPy.load(str(bundle)).objects:
        found.setdefault(int(obj.type.value), []).append(obj.read_typetree())
    return found


@needs_unitypy
class LegacyClipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def round_trip(self, clip: dict[str, Any]) -> dict[str, Any]:
        objects = [BundleObject(74, clip["m_Name"], clip, key=f"clip_{clip['m_Name']}")]
        bundle = self.root / "clip.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "clip.unity3d"))
        trees = read_objects(bundle)
        self.assertIn(74, trees)
        self.assertEqual(len(trees[74]), 1)
        return trees[74][0]

    def test_a_legacy_clip_survives_serialization(self) -> None:
        clip = legacy_clip("Idle1", [], [], [])
        back = self.round_trip(clip)
        self.assertEqual(back["m_Name"], "Idle1")
        self.assertTrue(back["m_Legacy"])
        self.assertEqual(back["m_MuscleClipSize"], 0)
        self.assertEqual(back["m_SampleRate"], 30.0)
        self.assertEqual(back["m_WrapMode"], 2)

    def test_curves_come_back_with_their_keyframes(self) -> None:
        rotations, positions, scales = idle_bob_curves(None, pelvis_bone="Root/Pelvis", bob=0.03)
        self.assertEqual(rotations, [])
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["path"], "Root/Pelvis")
        clip = legacy_clip("Idle1", rotations, positions, scales)
        back = self.round_trip(clip)
        positions_back = back["m_PositionCurves"]
        self.assertEqual(len(positions_back), 1)
        self.assertEqual(positions_back[0]["path"], "Root/Pelvis")
        keyframes = positions_back[0]["curve"]["m_Curve"]
        self.assertEqual(len(keyframes), 5)
        self.assertEqual(keyframes[0]["time"], 0.0)
        self.assertEqual(keyframes[0]["value"]["y"], 0.0)
        self.assertEqual(keyframes[1]["time"], 0.375)
        self.assertAlmostEqual(keyframes[1]["value"]["y"], 0.03)
        self.assertEqual(keyframes[-1]["value"]["y"], 0.0)

    def test_a_rotation_curve_round_trips(self) -> None:
        quarter = {"x": 0.0, "y": 0.0, "z": 0.7071068, "w": 0.7071068}
        identity = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
        curves = [
            rotation_curve(
                "Root/Pelvis",
                [
                    {
                        "time": 0.0,
                        "value": identity,
                        "inSlope": identity,
                        "outSlope": identity,
                        "weightedMode": 0,
                        "inWeight": identity,
                        "outWeight": identity,
                    },
                    {
                        "time": 1.0,
                        "value": quarter,
                        "inSlope": identity,
                        "outSlope": identity,
                        "weightedMode": 0,
                        "inWeight": identity,
                        "outWeight": identity,
                    },
                ],
            )
        ]
        back = self.round_trip(legacy_clip("Idle2", curves, [], []))
        rot = back["m_RotationCurves"]
        self.assertEqual(len(rot), 1)
        self.assertEqual(rot[0]["path"], "Root/Pelvis")
        self.assertEqual(len(rot[0]["curve"]["m_Curve"]), 2)
        self.assertAlmostEqual(rot[0]["curve"]["m_Curve"][1]["value"]["z"], 0.7071068, places=5)

    def test_animation_component_lists_the_clips(self) -> None:
        component = animation_component([12, 34])
        self.assertEqual(component["m_Animations"], [{"m_PathID": 12}, {"m_PathID": 34}])
        self.assertTrue(component["m_PlayAutomatically"])
        self.assertEqual(component["m_WrapMode"], 2)


if __name__ == "__main__":
    unittest.main()


class AnimDeclarationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parse_anim_reads_a_bob_declaration(self) -> None:
        from sevendtd_asset_pipeline.anim import parse_anim

        path = self.root / "creature.anim.json"
        path.write_text(
            '{"clips": [{"name": "Idle1", "kind": "bob", "bone": "Root/Pelvis",'
            ' "amplitude": 0.05, "seconds": 2.0}], "play_automatically": false}',
            encoding="utf-8",
        )
        declaration = parse_anim(path)
        self.assertEqual(len(declaration.clips), 1)
        clip = declaration.clips[0]
        self.assertEqual(clip.name, "Idle1")
        self.assertEqual(clip.bone, "Root/Pelvis")
        self.assertAlmostEqual(clip.amplitude, 0.05)
        self.assertFalse(declaration.play_automatically)

    def test_parse_anim_refuses_unknown_kinds_and_missing_bones(self) -> None:
        from sevendtd_asset_pipeline.anim import parse_anim
        from sevendtd_asset_pipeline.errors import PipelineError

        for body, fragment in (
            (
                '{"clips": [{"name": "Run", "kind": "sprint", "bone": "Root"}]}',
                "bob, head, walk, attack, death or jump",
            ),
            ('{"clips": [{"name": "Walk", "kind": "walk", "bone": "Root"}]}', '"bones"'),
            ('{"clips": [{"name": "Idle1", "kind": "bob"}]}', '"bone"'),
        ):
            with self.subTest(body=body):
                path = self.root / "bad.anim.json"
                path.write_text(body, encoding="utf-8")
                with self.assertRaisesRegex(PipelineError, fragment):
                    parse_anim(path)


@needs_unitypy
class AnimOnPrefabTests(unittest.TestCase):
    """A `.anim.json` beside a skinned source: the prefab carries an Animation
    component with the declared legacy clip."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generate_entity_with_anim_writes_the_declaration_and_avatar(self) -> None:
        from sevendtd_asset_pipeline.generators import run

        out = self.root / "creature.glb"
        xml = self.root / "entityclasses.xml"
        self.assertEqual(
            run(
                "entity",
                [
                    str(out),
                    "--rig",
                    "quadruped",
                    "--anim",
                    "--mod",
                    "M",
                    "--bundle",
                    "b",
                    "--xml",
                    str(xml),
                ],
            ),
            0,
        )
        declaration = (self.root / "creature.anim.json").read_text(encoding="utf-8")
        self.assertIn('"name": "Idle1"', declaration)
        self.assertIn('"bone": "Root/Pelvis"', declaration)
        self.assertIn(
            'name="AvatarController" value="GameObjectAnimalAnimation"',
            xml.read_text(encoding="utf-8"),
        )

    def test_the_prefab_carries_the_animation_component_and_clip(self) -> None:
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader

        out = self.root / "creature.glb"
        from sevendtd_asset_pipeline.generators import run

        self.assertEqual(run("entity", [str(out), "--rig", "bird", "--anim"]), 0)
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "anim.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "anim.unity3d"))
        trees = read_objects(bundle)
        self.assertIn(74, trees)  # the clip
        self.assertIn(111, trees)  # the legacy Animation component
        clip = trees[74][0]
        self.assertEqual(clip["m_Name"], "Idle1")
        self.assertTrue(clip["m_Legacy"])
        self.assertEqual(clip["m_MuscleClipSize"], 0)
        self.assertEqual(len(clip["m_PositionCurves"]), 1)
        animation = trees[111][0]
        self.assertTrue(animation["m_PlayAutomatically"])
        self.assertEqual(len(animation["m_Animations"]), 1)
        self.assertNotEqual(animation["m_GameObject"]["m_PathID"], 0)

    def test_the_animation_sits_on_a_figure_under_the_model_root(self) -> None:
        """GameObjectAnimalAnimation reads the legacy Animation off the model
        root's first *active child*, not off the root: spawned entities NRE'd
        every frame when the Animation was on the prefab root. The writer now
        inserts a figure GameObject between the root and its children and puts
        the Animation on it, with the root bone as the figure's child so the
        clip paths still resolve."""
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader

        out = self.root / "creature.glb"
        from sevendtd_asset_pipeline.generators import run

        self.assertEqual(run("entity", [str(out), "--rig", "quadruped", "--anim"]), 0)
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "figure.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "figure.unity3d"))
        trees = read_objects(bundle)
        animation = trees[111][0]
        # The Animation lives on a GameObject that is a child of the prefab root
        # and is NOT the root itself (the controller grabs the first child).
        anim_go = animation["m_GameObject"]["m_PathID"]
        # Recover GameObjects/Transforms from the object tree via UnityPy.
        import UnityPy

        env = UnityPy.load(str(bundle))
        gameobjects, transforms = {}, {}
        for obj in env.objects:
            if obj.type.name == "GameObject":
                gameobjects[obj.path_id] = obj.read_typetree()
            elif obj.type.name == "Transform":
                t = obj.read_typetree()
                transforms[obj.path_id] = t
        go_to_transform = {t["m_GameObject"]["m_PathID"]: ptr for ptr, t in transforms.items()}
        anim_go_name = gameobjects[anim_go]["m_Name"]
        # Prefab root is the file stem; the Animation must be on the 'figure'.
        self.assertEqual(anim_go_name, "figure")
        anim_transform = go_to_transform[anim_go]
        figure_parent = transforms[anim_transform]["m_Father"]["m_PathID"]
        root_transform = transforms[figure_parent]
        root_go = root_transform["m_GameObject"]["m_PathID"]
        self.assertEqual(gameobjects[root_go]["m_Name"], "creature")
        # The figure is the root's only child, and the root bone hangs off it.
        figure_children = transforms[anim_transform]["m_Children"]
        self.assertEqual(len(figure_children), 1)
        root_bone_go = gameobjects[
            transforms[figure_children[0]["m_PathID"]]["m_GameObject"]["m_PathID"]
        ]
        self.assertEqual(root_bone_go["m_Name"], "Root")

    def test_a_source_without_a_declaration_gets_no_animation(self) -> None:
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader

        out = self.root / "creature.glb"
        from sevendtd_asset_pipeline.generators import run

        self.assertEqual(run("entity", [str(out), "--rig", "bird"]), 0)
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "plain.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "plain.unity3d"))
        trees = read_objects(bundle)
        self.assertNotIn(74, trees)
        self.assertNotIn(111, trees)


class LimbAnimTests(unittest.TestCase):
    """The walk gait and head-turn curve kinds, and the merged Idle1 clip."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parse_anim_accepts_walk_and_head(self) -> None:
        from sevendtd_asset_pipeline.anim import parse_anim

        path = self.root / "a.anim.json"
        path.write_text(
            '{"clips": [{"name": "Idle1", "kind": "head", "bone": "Root/Neck/Head"},'
            ' {"name": "Walk", "kind": "walk",'
            ' "bones": ["Root/Pelvis/LeftRearUpper", "Root/Pelvis/RightRearUpper"]}]}',
            encoding="utf-8",
        )
        declaration = parse_anim(path)
        self.assertEqual(len(declaration.clips), 2)
        head = declaration.clips[0]
        self.assertEqual((head.kind, head.bone), ("head", "Root/Neck/Head"))
        walk = declaration.clips[1]
        self.assertEqual(walk.kind, "walk")
        self.assertEqual(len(walk.bones), 2)

    def test_parse_anim_refuses_unknown_kind(self) -> None:
        from sevendtd_asset_pipeline.anim import parse_anim
        from sevendtd_asset_pipeline.errors import PipelineError

        path = self.root / "bad.anim.json"
        path.write_text(
            '{"clips": [{"name": "Run", "kind": "sprint", "bone": "Root"}]}', encoding="utf-8"
        )
        with self.assertRaisesRegex(PipelineError, "bob, head, walk, attack, death or jump"):
            parse_anim(path)

    def test_walk_curves_bend_knees_and_alternate_diagonally(self) -> None:
        from sevendtd_asset_pipeline.anim import walk_curves

        legs = [
            ("Root/Pelvis/LeftFrontUpper", "Root/Pelvis/LeftFrontLower"),
            ("Root/Pelvis/RightRearUpper", "Root/Pelvis/RightRearLower"),
            ("Root/Pelvis/RightFrontUpper", "Root/Pelvis/RightFrontLower"),
            ("Root/Pelvis/LeftRearUpper", "Root/Pelvis/LeftRearLower"),
        ]
        curves = walk_curves(legs, "Root/Pelvis", stride=0.35, seconds=1.2)
        self.assertEqual(len(curves), 9)  # upper+lower per leg, plus the body dip
        upper = {c["path"]: c["curve"]["m_Curve"] for c in curves[:8] if "Upper" in c["path"]}
        lower = {c["path"]: c["curve"]["m_Curve"] for c in curves[:8] if "Lower" in c["path"]}
        # Trot: LeftFront pairs with RightRear (phase 0), RightFront with
        # LeftRear (phase π). At a quarter cycle the phase-0 legs are +stride.
        for left_front, right_rear in ((legs[0], legs[1]),):
            self.assertGreater(upper[left_front[0]][2]["value"]["x"], 0.15)
            self.assertGreater(upper[right_rear[0]][2]["value"]["x"], 0.15)
        self.assertLess(upper[legs[2][0]][2]["value"]["x"], -0.15)
        self.assertLess(upper[legs[3][0]][2]["value"]["x"], -0.15)
        # The knee bends the opposite way: lower-leg rotation is inverted.
        self.assertLess(lower[legs[0][1]][2]["value"]["x"], -0.05)
        self.assertGreater(lower[legs[2][1]][2]["value"]["x"], 0.05)
        # Loops start and end at the same value (no seam).
        for curve in curves:
            self.assertAlmostEqual(
                curve["curve"]["m_Curve"][0]["value"]["x"],
                curve["curve"]["m_Curve"][-1]["value"]["x"],
                places=6,
            )
        # The body dips twice per stride on the body bone.
        body = next(c for c in curves if c["path"] == "Root/Pelvis")
        ys = [kf["value"]["y"] for kf in body["curve"]["m_Curve"]]
        self.assertLess(min(ys), -0.01)
        self.assertAlmostEqual(ys[0], 0.0, places=6)

    @needs_unitypy
    def test_same_name_entries_merge_into_one_clip(self) -> None:
        from sevendtd_asset_pipeline.anim import clip_fields, parse_anim

        path = self.root / "merge.anim.json"
        path.write_text(
            '{"clips": [{"name": "Idle1", "kind": "bob", "bone": "Root/Pelvis"},'
            ' {"name": "Idle1", "kind": "head", "bone": "Root/Neck/Head"}]}',
            encoding="utf-8",
        )
        fields = clip_fields(parse_anim(path))
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]["m_Name"], "Idle1")
        self.assertEqual(len(fields[0]["m_PositionCurves"]), 1)
        self.assertEqual(len(fields[0]["m_RotationCurves"]), 1)
        self.assertEqual(fields[0]["m_RotationCurves"][0]["path"], "Root/Neck/Head")


class CombatAnimTests(unittest.TestCase):
    """The attack / death / jump curve kinds: parse, shape, wrap mode."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_parse_anim_accepts_attack_death_jump(self) -> None:
        from sevendtd_asset_pipeline.anim import parse_anim

        path = self.root / "kinds.anim.json"
        path.write_text(
            '{"clips": ['
            ' {"name": "Attack1", "kind": "attack", "bone": "Root/Neck/Head",'
            '  "body_bone": "Root/Pelvis", "amplitude": 0.5, "seconds": 0.6},'
            ' {"name": "Death", "kind": "death", "bone": "Root/Pelvis",'
            '  "loop": false, "amplitude": 3.14159, "seconds": 1.2},'
            ' {"name": "Jump", "kind": "jump", "bone": "Root/Pelvis",'
            '  "amplitude": 0.2, "seconds": 0.8}]}',
            encoding="utf-8",
        )
        declaration = parse_anim(path)
        self.assertEqual(len(declaration.clips), 3)
        attack, death, jump = declaration.clips
        self.assertEqual(
            (attack.kind, attack.bone, attack.body_bone),
            ("attack", "Root/Neck/Head", "Root/Pelvis"),
        )
        self.assertEqual((death.kind, death.loop), ("death", False))
        self.assertEqual((jump.kind, jump.bone), ("jump", "Root/Pelvis"))

    def test_attack_curves_jab_head_and_pitch_body(self) -> None:
        from sevendtd_asset_pipeline.anim import attack_curves

        curves = attack_curves("Root/Neck/Head", "Root/Pelvis", lunge=0.5, seconds=0.8)
        self.assertEqual(len(curves), 2)
        self.assertEqual({c["path"] for c in curves}, {"Root/Neck/Head", "Root/Pelvis"})
        head = next(c for c in curves if c["path"] == "Root/Neck/Head")
        body = next(c for c in curves if c["path"] == "Root/Pelvis")
        for curve in (head, body):
            keyframes = curve["curve"]["m_Curve"]
            self.assertEqual(len(keyframes), 9)
            # A jab: at rest, one forward excursion that never goes past rest
            # (a backward overshoot is the nervous-bob look), back to rest.
            self.assertAlmostEqual(keyframes[0]["value"]["x"], 0.0, places=6)
            self.assertAlmostEqual(keyframes[-1]["value"]["x"], 0.0, places=6)
            self.assertGreaterEqual(min(kf["value"]["x"] for kf in keyframes), 0.0)
        # The head peaks mid-clip (index 4) and more than the body pitches.
        self.assertGreater(head["curve"]["m_Curve"][4]["value"]["x"], 0.15)
        head_peak = max(kf["value"]["x"] for kf in head["curve"]["m_Curve"])
        body_peak = max(kf["value"]["x"] for kf in body["curve"]["m_Curve"])
        self.assertGreater(head_peak, body_peak)

    def test_death_rolls_once_and_jump_hops(self) -> None:
        from sevendtd_asset_pipeline.anim import death_curves, jump_curves

        death = death_curves("Root/Pelvis", roll=math.pi, seconds=1.2)
        self.assertEqual(len(death), 1)
        keyframes = death[0]["curve"]["m_Curve"]
        # Ends fully rolled about local Z: quat (sin π/2, cos π/2) = (1, 0).
        self.assertAlmostEqual(keyframes[-1]["value"]["z"], 1.0, places=5)
        self.assertAlmostEqual(keyframes[-1]["value"]["w"], 0.0, places=5)
        self.assertGreater(abs(keyframes[1]["value"]["z"]), 0.02)  # fast start
        jump = jump_curves("Root/Pelvis", height=0.2, seconds=0.8)
        self.assertEqual(len(jump), 1)
        self.assertEqual(jump[0]["path"], "Root/Pelvis")
        ys = [kf["value"]["y"] for kf in jump[0]["curve"]["m_Curve"]]
        self.assertGreater(max(ys), 0.1)
        self.assertAlmostEqual(ys[0], 0.0, places=6)
        self.assertAlmostEqual(ys[-1], 0.0, places=6)


@needs_unitypy
class LimbAnimBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_anim_kinds_round_trip_through_the_bundle(self) -> None:
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader
        from sevendtd_asset_pipeline.generators import run

        out = self.root / "creature.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "quadruped", "--anim", "idle,head,walk"]), 0
        )
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "anim.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "anim.unity3d"))
        trees = read_objects(bundle)
        clips = {c["m_Name"]: c for c in trees[74]}
        self.assertEqual(set(clips), {"Idle1", "Walk"})
        self.assertEqual(len(clips["Walk"]["m_RotationCurves"]), 8)  # upper+lower per leg
        self.assertEqual(len(clips["Walk"]["m_PositionCurves"]), 1)  # body dip
        self.assertEqual(len(clips["Idle1"]["m_RotationCurves"]), 1)
        self.assertEqual(len(clips["Idle1"]["m_PositionCurves"]), 1)
        animation = trees[111][0]
        self.assertEqual(len(animation["m_Animations"]), 2)

    def test_attack_death_jump_round_trip_with_wrap(self) -> None:
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader
        from sevendtd_asset_pipeline.generators import run

        out = self.root / "creature.glb"
        self.assertEqual(
            run("entity", [str(out), "--rig", "quadruped", "--anim", "attack,death,jump"]), 0
        )
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "combat.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "combat.unity3d"))
        trees = read_objects(bundle)
        clips = {c["m_Name"]: c for c in trees[74]}
        self.assertEqual(set(clips), {"Attack1", "Death", "Jump"})
        self.assertEqual(len(clips["Attack1"]["m_RotationCurves"]), 2)  # head + chest
        self.assertEqual(
            clips["Attack1"]["m_RotationCurves"][0]["path"], "Root/Pelvis/Spine/Chest/Neck/Head"
        )
        self.assertEqual(clips["Attack1"]["m_RotationCurves"][1]["path"], "Root/Pelvis/Spine/Chest")
        self.assertEqual(len(clips["Death"]["m_RotationCurves"]), 1)
        self.assertEqual(clips["Death"]["m_WrapMode"], 1)  # plays once
        self.assertEqual(len(clips["Jump"]["m_PositionCurves"]), 1)
        self.assertEqual(clips["Jump"]["m_PositionCurves"][0]["path"], "Root/Pelvis")
        # The looping kinds wrap like every other clip.
        self.assertEqual(clips["Attack1"]["m_WrapMode"], 2)
        self.assertEqual(clips["Jump"]["m_WrapMode"], 2)

    def test_unknown_anim_kind_is_refused(self) -> None:
        from sevendtd_asset_pipeline.generators import run

        out = self.root / "x.glb"
        with self.assertRaises(SystemExit):
            run("entity", [str(out), "--rig", "humanoid", "--anim", "gallop"])


class BoneColliderTests(unittest.TestCase):
    """A generated entity's bones carry colliders, so the game's physics body
    builds real colliders (PhysicsBodyInstance.bindCollider finds a Box/Capsule/
    Sphere collider on the referenced bone; absent one it creates a
    PhysicsBodyNullCollider and the creature floats)."""

    @needs_unitypy
    def test_every_bone_has_a_collider_component(self) -> None:
        from sevendtd_asset_pipeline.bundle_writer import build_bundle, mesh_source_objects, shader

        out = self.root / "creature.glb"
        from sevendtd_asset_pipeline.generators import run

        self.assertEqual(run("entity", [str(out), "--rig", "quadruped"]), 0)
        objects = mesh_source_objects(out, set())
        objects.append(shader("Shamway/Unlit"))
        bundle = self.root / "bones.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "bones.unity3d"))
        trees = read_objects(bundle)
        # Box/Capsule/Sphere colliders on the creature's bone GameObjects.
        collider_kinds = {65}.intersection(trees)
        self.assertIn(65, trees, "no BoxCollider components: bindCollider makes null colliders")

    def setUp(self) -> None:
        import tempfile

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()
