"""Legacy animation clips for generated entities: serialization round-trip.

A legacy `AnimationClip` carries its curves directly (m_MuscleClipSize = 0,
measured from the game's own animals.bundle), so a clip dict serializes
through the writer's type-tree walk and must come back through UnityPy —
which parses Unity's format with none of this repository's code — with the
curves, the legacy flag and the empty compiled stream intact.
"""

from __future__ import annotations

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
            ('{"clips": [{"name": "Walk", "kind": "walk", "bone": "Root"}]}', "must be"),
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
