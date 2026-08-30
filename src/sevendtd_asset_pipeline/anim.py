"""Legacy animation clips for generated entities, expressed as type trees.

A 7 Days to Die animal moves through `GameObjectAnimalAnimation : AvatarController`
(dedicated-server IL, `GameObjectAnimalAnimation.il.txt`): the entity class
sets `AvatarController = GameObjectAnimalAnimation`, the controller grabs the
model's legacy `UnityEngine.Animation` component and plays clips by name —
`Idle1`, `Idle2`, `Attack1/2`, `Pain`, `Jump`, `Death`, `Run`, `Walk`, `Swim`
— switching on motion state.

The enabling fact, measured from the installed game's
`automatic_assets_entities/animals.bundle`: a **legacy** `AnimationClip`
carries its curves directly in `m_RotationCurves` / `m_PositionCurves` /
`m_ScaleCurves` and has `m_MuscleClipSize = 0` — no compiled `m_Clip` stream
(the `run` Mecanim clip in the same bundle carries 25568 bytes there). So a
legacy clip is fully expressible through the class's type tree, and this
module builds that dict the same way the writer builds every other object.

Curve shape mirrors `_Take 001` from that bundle: one entry per bone path
(`Root/Pelvis/...`, slash-separated), each with 2+ keyframes of
`{time, value, inSlope, outSlope, weightedMode, inWeight, outWeight}` and
`m_PreInfinity`/`m_PostInfinity` = 2, `m_RotationOrder` = 4.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PipelineError

# The curve-write flags Unity uses on the animation component.
ANIMATION_CLIP = 74
ANIMATION_COMPONENT = 111

# WrapMode: Loop makes a legacy clip repeat; the game's imported takes carry
# Default (0) and loop through the component/settings, Loop is the safe
# explicit choice for a synthesized idle.
WRAP_LOOP = 2
PRE_POST_INFINITY = 2
ROTATION_ORDER = 4


def _keyframe(
    time: float,
    value: dict[str, float],
    slope: float = 0.0,
) -> dict[str, Any]:
    """One keyframe, in the shape the game's own legacy clips carry."""
    axes = list(value)
    weights = dict.fromkeys(axes, 0.3333333432674408)
    return {
        "time": time,
        "value": {axis: value[axis] for axis in axes},
        "inSlope": dict.fromkeys(axes, slope),
        "outSlope": dict.fromkeys(axes, slope),
        "weightedMode": 0,
        "inWeight": weights,
        "outWeight": dict(weights),
    }


def _curve(keyframes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "m_Curve": keyframes,
        "m_PreInfinity": PRE_POST_INFINITY,
        "m_PostInfinity": PRE_POST_INFINITY,
        "m_RotationOrder": ROTATION_ORDER,
    }


def _typetree_default(node: Any) -> Any:
    """A default value for every type-tree node, mirroring particles.py.

    The writer's `write_typetree` requires every field the tree names, so a
    clip dict is the tree's defaults deep-merged with the fields this module
    authors. The walker is small; duplicating it beats importing a sibling
    module's private.
    """
    kind = node.m_Type
    children = list(node.m_Children or [])
    if kind in {
        "int",
        "SInt32",
        "UInt32",
        "unsigned int",
        "SInt64",
        "UInt64",
        "SInt16",
        "UInt16",
        "UInt8",
        "SInt8",
        "char",
        "short",
        "unsigned short",
        "long long",
        "unsigned long long",
    }:
        return 0
    if kind in {"float", "double"}:
        return 0.0
    if kind == "bool":
        return False
    if kind == "string":
        return ""
    if kind == "TypelessData":
        return b""
    if kind.startswith("PPtr"):
        return {"m_FileID": 0, "m_PathID": 0}
    if kind in {"vector", "staticvector", "Array", "map"}:
        return []
    fields: dict[str, Any] = {}
    for child in children:
        if child.m_Type == "Array" and child.m_Name == "Array":
            return []
        fields[child.m_Name] = _typetree_default(child)
    return fields


def _clip_defaults() -> dict[str, Any]:
    from UnityPy.helpers.Tpk import get_typetree_node
    from UnityPy.helpers.UnityVersion import UnityVersion

    node = get_typetree_node(ANIMATION_CLIP, UnityVersion.from_str("2022.3.62f2"))
    default = _typetree_default(node)
    return dict(default)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """`override` onto `base`, recursing into dicts, replacing lists/scalars."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _deep_merge(base[key], value)
        else:
            out[key] = value
    return out


def legacy_clip(
    name: str,
    rotation_curves: list[dict[str, Any]],
    position_curves: list[dict[str, Any]],
    scale_curves: list[dict[str, Any]],
    sample_rate: float = 30.0,
    wrap_mode: int = WRAP_LOOP,
) -> dict[str, Any]:
    """An `AnimationClip` type-tree dict a legacy `Animation` can play.

    `m_Legacy = true` and `m_MuscleClipSize = 0` are the two fields that
    make the runtime use these curves: that is exactly what the game's own
    legacy clips serialize (animals.bundle `_Take 001`). Every other field
    comes from the class's type-tree defaults.
    """
    return _deep_merge(
        _clip_defaults(),
        {
            "m_Name": name,
            "m_Legacy": True,
            "m_UseHighQualityCurve": True,
            "m_RotationCurves": rotation_curves,
            "m_PositionCurves": position_curves,
            "m_ScaleCurves": scale_curves,
            "m_SampleRate": sample_rate,
            "m_WrapMode": wrap_mode,
            "m_MuscleClipSize": 0,
        },
    )


def rotation_curve(path: str, keyframes: list[dict[str, Any]]) -> dict[str, Any]:
    """One rotation curve entry bound to a bone path."""
    return {"curve": _curve(keyframes), "path": path}


def position_curve(path: str, keyframes: list[dict[str, Any]]) -> dict[str, Any]:
    """One position curve entry bound to a bone path."""
    return {"curve": _curve(keyframes), "path": path}


def animation_component(
    clip_path_ids: list[int],
    play_automatically: bool = True,
    wrap_mode: int = WRAP_LOOP,
) -> dict[str, Any]:
    """The legacy `Animation` component a generated entity prefab carries.

    `m_Animations` lists the clip PPtrs; `GameObjectAnimalAnimation.Awake`
    then resolves `Idle1` etc. by name off this component.
    """
    return {
        "m_Animation": {"m_PathID": 0},
        "m_Animations": [{"m_PathID": path_id} for path_id in clip_path_ids],
        "m_PlayAutomatically": play_automatically,
        "m_AnimatePhysics": False,
        "m_CullingType": 0,
        "m_WrapMode": wrap_mode,
        "m_Enabled": True,
    }


def idle_bob_curves(
    rig: Any, pelvis_bone: str = "Pelvis", bob: float = 0.03
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """A looping whole-body bob for the rig, as rotation/position/scale curves.

    One visible idle: the pelvis (and everything above it) sinks and rises
    `bob` metres over a 1.5 s cycle. The engine's `GameObjectAnimalAnimation`
    plays `Idle1` by name; this is the clip it would play.
    """
    up = {"x": 0.0, "y": bob, "z": 0.0}
    rest = {"x": 0.0, "y": 0.0, "z": 0.0}
    position = position_curve(
        pelvis_bone,
        [
            _keyframe(0.0, rest),
            _keyframe(0.375, up),
            _keyframe(0.75, rest),
            _keyframe(1.125, up),
            _keyframe(1.5, rest),
        ],
    )
    return [], [position], []


def _quat_x(angle: float) -> dict[str, float]:
    """A rotation about the local X axis, as a quaternion dict."""
    half = angle / 2.0
    return {"x": math.sin(half), "y": 0.0, "z": 0.0, "w": math.cos(half)}


def _quat_y(angle: float) -> dict[str, float]:
    """A rotation about the local Y axis, as a quaternion dict."""
    half = angle / 2.0
    return {"x": 0.0, "y": math.sin(half), "z": 0.0, "w": math.cos(half)}


def _rotation_keyframes(
    axis: str, amplitude: float, seconds: float, phase: float = 0.0
) -> list[dict[str, Any]]:
    """One loop of `amplitude·sin(2πt/seconds + phase)` about an axis.

    Eight samples per cycle: enough for a smooth loop, cheap to serialize.
    A sine loop starts and ends at the same value with matching slopes, so
    the clip loops without a seam.
    """
    quat = _quat_x if axis == "x" else _quat_y
    return [
        {
            "time": seconds * index / 8.0,
            "value": quat(amplitude * math.sin(2 * math.pi * index / 8.0 + phase)),
            "inSlope": quat(0.0),
            "outSlope": quat(0.0),
            "weightedMode": 0,
            "inWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
            "outWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
        }
        for index in range(9)
    ]


def head_turn_curves(
    head_bone: str, amplitude: float = 0.35, seconds: float = 4.0
) -> list[dict[str, Any]]:
    """A slow side-to-side head turn: a yaw oscillation on the head bone.

    `amplitude` is the half-swing in radians (0.35 ≈ 20° each way over a
    4 s cycle). Merged into `Idle1`, it reads as a creature looking around.
    """
    return [rotation_curve(head_bone, _rotation_keyframes("y", amplitude, seconds))]


def walk_curves(
    legs: list[tuple[str, str]],
    body_bone: str,
    stride: float = 0.35,
    seconds: float = 1.2,
    body_dip: float = 0.03,
) -> list[dict[str, Any]]:
    """A trot gait: upper legs swing, knees bend, the body dips.

    One rotation curve per upper leg (`stride` half-swing about its local X)
    and one per lower leg bending the knee the opposite way (`0.6·stride`),
    so the paw stays roughly under the hip instead of sweeping a rigid arc —
    a rigid whole-leg rotation is the wind-up-toy look. Diagonal pairs move
    together (`LeftFront` with `RightRear`, `RightFront` with `LeftRear`),
    and a position curve on `body_bone` dips the body twice per stride as
    the weight transfers.
    """
    curves: list[dict[str, Any]] = []

    def phase(upper: str) -> float:
        front = "Front" in upper
        left = "/Left" in upper or upper.startswith("Left")
        if front:
            return 0.0 if left else math.pi
        return 0.0 if not left else math.pi

    for upper, lower in legs:
        phi = phase(upper)
        curves.append(rotation_curve(upper, _rotation_keyframes("x", stride, seconds, phi)))
        curves.append(rotation_curve(lower, _rotation_keyframes("x", -0.6 * stride, seconds, phi)))
    # The body dips twice per stride, at the weight transfers (quarter and
    # three-quarter points), never at the stride's end where a foot lands.
    rest = {"x": 0.0, "y": 0.0, "z": 0.0}
    keyframes = [
        {
            "time": seconds * index / 8.0,
            "value": {
                "x": 0.0,
                "y": -body_dip * (0.5 - 0.5 * math.cos(4 * math.pi * index / 8.0)),
                "z": 0.0,
            },
            "inSlope": rest,
            "outSlope": rest,
            "weightedMode": 0,
            "inWeight": dict.fromkeys(("x", "y", "z"), 0.3333333432674408),
            "outWeight": dict.fromkeys(("x", "y", "z"), 0.3333333432674408),
        }
        for index in range(9)
    ]
    curves.append(position_curve(body_bone, keyframes))
    return curves


def _jab_keyframes(axis: str, amplitude: float, seconds: float) -> list[dict[str, Any]]:
    """One forward jab and back: `amplitude·sin(πt/T)`, never past rest.

    A half-sine starts and ends at rest and peaks mid-clip, so the bone
    moves one way and returns. A full sine would swing past rest on the
    way back — two movements per clip, which reads as a nervous bob
    rather than a bite.
    """
    quat = _quat_x if axis == "x" else _quat_y
    return [
        {
            "time": seconds * index / 8.0,
            "value": quat(amplitude * math.sin(math.pi * index / 8.0)),
            "inSlope": quat(0.0),
            "outSlope": quat(0.0),
            "weightedMode": 0,
            "inWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
            "outWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
        }
        for index in range(9)
    ]


def attack_curves(
    head_bone: str, body_bone: str, lunge: float = 0.5, seconds: float = 0.8
) -> list[dict[str, Any]]:
    """A bite: the head lunges forward and returns over `seconds`.

    One forward jab on the head (`lunge` rad at mid-clip, back to rest at
    the end — never past rest, which reads as a nervous bob) and a
    shallower body pitch on `body_bone` so the strike has weight. The
    engine plays `Attack1` when the animal attacks.
    """
    curves = []
    for bone, amplitude in ((head_bone, lunge), (body_bone, 0.25 * lunge)):
        curves.append(rotation_curve(bone, _jab_keyframes("x", amplitude, seconds)))
    return curves


def death_curves(
    body_bone: str, roll: float = math.pi, seconds: float = 1.2
) -> list[dict[str, Any]]:
    """The body rolls over: a full rotation about local Z on `body_bone`.

    Rises fast, ends rolled — the clip's `loop` flag should be false so the
    animal stays down. The engine plays `Death` when the animal dies.
    """
    rest = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    keyframes = []
    for index in range(9):
        angle = roll * (index / 8.0) ** 2  # fast start, settle at rest
        keyframes.append(
            {
                "time": seconds * index / 8.0,
                "value": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": math.sin(angle / 2.0),
                    "w": math.cos(angle / 2.0),
                },
                "inSlope": rest,
                "outSlope": rest,
                "weightedMode": 0,
                "inWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
                "outWeight": dict.fromkeys(("x", "y", "z", "w"), 0.3333333432674408),
            }
        )
    return [rotation_curve(body_bone, keyframes)]


def jump_curves(body_bone: str, height: float = 0.2, seconds: float = 0.8) -> list[dict[str, Any]]:
    """A hop: the body rises `height` metres and lands, over `seconds`.

    A single smooth up-and-down on `body_bone`; the engine plays `Jump`
    when the animal jumps.
    """
    rest = {"x": 0.0, "y": 0.0, "z": 0.0}
    keyframes = [
        {
            "time": seconds * index / 8.0,
            "value": {"x": 0.0, "y": height * math.sin(math.pi * index / 8.0), "z": 0.0},
            "inSlope": rest,
            "outSlope": rest,
            "weightedMode": 0,
            "inWeight": dict.fromkeys(("x", "y", "z"), 0.3333333432674408),
            "outWeight": dict.fromkeys(("x", "y", "z"), 0.3333333432674408),
        }
        for index in range(9)
    ]
    return [position_curve(body_bone, keyframes)]


@dataclass(frozen=True)
class AnimClip:
    """One legacy clip a `.anim.json` declaration asks for.

    `kind` selects the curve builder: `bob` (a position bob on `bone`),
    `head` (a yaw turn on `bone`), `walk` (a trot gait across `bones`),
    `attack` (a lunge on `bone` with a body pitch on `body_bone`), `death`
    (a one-shot roll on `bone`), or `jump` (a hop on `bone`).
    `amplitude`/`seconds` scale the motion; a `walk` entry uses `bones`
    (the upper-leg paths) instead of `bone`, and `loop=False` makes the
    clip play once rather than wrap (a `Death` should not loop).
    """

    name: str
    kind: str
    bone: str = ""
    bones: tuple[str, ...] = ()
    lower_bones: tuple[str, ...] = ()
    body_bone: str = ""
    loop: bool = True
    amplitude: float = 0.03
    seconds: float = 1.5


@dataclass(frozen=True)
class AnimDeclaration:
    """A `.anim.json` beside a skinned source: the clips its prefab carries."""

    clips: tuple[AnimClip, ...]
    play_automatically: bool = True


def parse_anim(path: Path) -> AnimDeclaration:
    """Read a `.anim.json` declaration.

    The format is small — one looping legacy clip per entry, each a named
    motion:

        {"clips": [
            {"name": "Idle1", "kind": "bob", "bone": "Root/Pelvis",
             "amplitude": 0.03, "seconds": 1.5},
            {"name": "Idle1", "kind": "head", "bone": "Root/Neck/Head",
             "amplitude": 0.35, "seconds": 4.0},
            {"name": "Walk", "kind": "walk",
             "bones": ["Root/Pelvis/LeftRearUpper", "Root/Pelvis/RightRearUpper"],
             "stride": 0.5, "seconds": 1.2}
        ]}

    `kind` selects the curve builder: `bob` (position bob), `head` (yaw
    turn), `walk` (trot gait across the `bones` list), `attack` (a lunge
    on `bone` plus a body pitch on `body_bone`), `death` (a one-shot roll
    on `bone` — set `loop: false`), and `jump` (a hop on `bone`). Entries
    with the same `name` merge into one clip, so an `Idle1` can combine a
    bob and a head turn. The clip names are what `GameObjectAnimalAnimation`
    plays (`Idle1`, `Walk`, `Attack1`, …), so a declaration is how an entity
    gets movement clips without an editor.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PipelineError(f"anim declaration {path} does not exist") from None
    except json.JSONDecodeError as exc:
        raise PipelineError(f"anim declaration {path} is not valid JSON: {exc}") from None
    if not isinstance(document, dict):
        raise PipelineError(f"anim declaration {path} must be a JSON object")
    raw = document.get("clips")
    if not isinstance(raw, list) or not raw:
        raise PipelineError(f'anim declaration {path} needs a non-empty "clips" array')
    clips: list[AnimClip] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PipelineError(f"anim declaration {path} clip {index} is not an object")
        name = item.get("name")
        kind = item.get("kind")
        if not isinstance(name, str) or not name:
            raise PipelineError(f'anim declaration {path} clip {index} needs a "name"')
        if kind not in ("bob", "head", "walk", "attack", "death", "jump"):
            raise PipelineError(
                f"anim declaration {path} clip {name!r} kind must be bob, head, walk, "
                "attack, death or jump"
            )
        for key, default in (("amplitude", 0.03), ("seconds", 1.5)):
            value = item.get(key, default)
            if not isinstance(value, (int, float)) or value <= 0:
                raise PipelineError(
                    f"anim declaration {path} clip {name!r} {key!r} must be positive"
                )
        if kind == "walk":
            bones = item.get("bones")
            if (
                not isinstance(bones, list)
                or not bones
                or not all(isinstance(bone, str) and bone for bone in bones)
            ):
                raise PipelineError(
                    f'anim declaration {path} clip {name!r} needs a non-empty "bones" list'
                )
            lower = item.get("lower_bones", [])
            if not isinstance(lower, list) or not all(
                isinstance(bone, str) and bone for bone in lower
            ):
                raise PipelineError(
                    f'anim declaration {path} clip {name!r} "lower_bones" must be a list'
                )
            body_bone = item.get("body_bone", "")
            if not isinstance(body_bone, str):
                raise PipelineError(
                    f'anim declaration {path} clip {name!r} "body_bone" must be a string'
                )
            clips.append(
                AnimClip(
                    name=name,
                    kind=kind,
                    bones=tuple(bones),
                    lower_bones=tuple(lower),
                    body_bone=body_bone,
                    amplitude=float(item.get("amplitude", 0.35)),
                    seconds=float(item.get("seconds", 1.2)),
                )
            )
            continue
        bone = item.get("bone")
        if not isinstance(bone, str) or not bone:
            raise PipelineError(f'anim declaration {path} clip {name!r} needs a "bone" path')
        body_bone = item.get("body_bone", "")
        if not isinstance(body_bone, str):
            raise PipelineError(
                f'anim declaration {path} clip {name!r} "body_bone" must be a string'
            )
        loop = item.get("loop", True)
        if not isinstance(loop, bool):
            raise PipelineError(f'anim declaration {path} clip {name!r} "loop" must be a bool')
        clips.append(
            AnimClip(
                name=name,
                kind=kind,
                bone=bone,
                body_bone=body_bone,
                loop=loop,
                amplitude=float(item.get("amplitude", 0.03)),
                seconds=float(item.get("seconds", 1.5)),
            )
        )
    play = document.get("play_automatically", True)
    if not isinstance(play, bool):
        raise PipelineError(f'anim declaration {path} "play_automatically" must be a bool')
    return AnimDeclaration(clips=tuple(clips), play_automatically=play)


def clip_fields(declaration: AnimDeclaration) -> tuple[dict[str, Any], ...]:
    """One `AnimationClip` type-tree dict per declared clip name.

    Entries sharing a name merge into one clip (an `Idle1` can combine a
    bob and a head turn). A `bob` yields a position curve on its bone; a
    `head` a yaw rotation on its bone; an `attack` a lunge rotation pair;
    a `death` a one-shot roll; a `jump` a hop position curve; a `walk` a
    trot of rotation curves across its `bones`. A clip whose entries all
    loop wraps (`WRAP_LOOP`); one with any non-looping entry (a `Death`)
    plays once (`WRAP_ONCE`).
    """
    grouped: dict[str, list[AnimClip]] = {}
    for clip in declaration.clips:
        grouped.setdefault(clip.name, []).append(clip)

    def rescaled(curves: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
        return [
            {
                "curve": {
                    "m_Curve": [
                        {**keyframe, "time": keyframe["time"] * factor}
                        for keyframe in curve["curve"]["m_Curve"]
                    ],
                    "m_PreInfinity": curve["curve"]["m_PreInfinity"],
                    "m_PostInfinity": curve["curve"]["m_PostInfinity"],
                    "m_RotationOrder": curve["curve"]["m_RotationOrder"],
                },
                "path": curve["path"],
            }
            for curve in curves
        ]

    out: list[dict[str, Any]] = []
    for name, entries in grouped.items():
        rotations: list[dict[str, Any]] = []
        positions: list[dict[str, Any]] = []
        scales: list[dict[str, Any]] = []
        for clip in entries:
            if clip.kind == "bob":
                _, bob_positions, _ = idle_bob_curves(
                    None, pelvis_bone=clip.bone, bob=clip.amplitude
                )
                positions += rescaled(bob_positions, clip.seconds / 1.5)
            elif clip.kind == "head":
                rotations += rescaled(
                    head_turn_curves(clip.bone, clip.amplitude, clip.seconds), 1.0
                )
            elif clip.kind == "attack":
                rotations += rescaled(
                    attack_curves(clip.bone, clip.body_bone, clip.amplitude, clip.seconds), 1.0
                )
            elif clip.kind == "death":
                rotations += rescaled(death_curves(clip.bone, clip.amplitude, clip.seconds), 1.0)
            elif clip.kind == "jump":
                positions += rescaled(jump_curves(clip.bone, clip.amplitude, clip.seconds), 1.0)
            else:  # walk — rotation curves on the legs, a position curve on the body
                legs = [
                    (upper, lower)
                    for upper, lower in zip(clip.bones, clip.lower_bones, strict=False)
                    if lower
                ]
                for curve in walk_curves(legs, clip.body_bone, clip.amplitude, clip.seconds):
                    is_rotation = len(curve["curve"]["m_Curve"][0]["value"]) == 4
                    (rotations if is_rotation else positions).append(rescaled([curve], 1.0)[0])
        wrap = WRAP_LOOP if all(clip.loop for clip in entries) else 1
        out.append(
            legacy_clip(name, rotations, positions, scales, sample_rate=30.0, wrap_mode=wrap)
        )
    return tuple(out)
