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
