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


@dataclass(frozen=True)
class AnimClip:
    """One legacy clip a `.anim.json` declaration asks for."""

    name: str
    kind: str
    bone: str
    amplitude: float = 0.03
    seconds: float = 1.5


@dataclass(frozen=True)
class AnimDeclaration:
    """A `.anim.json` beside a skinned source: the clips its prefab carries."""

    clips: tuple[AnimClip, ...]
    play_automatically: bool = True


def parse_anim(path: Path) -> AnimDeclaration:
    """Read a `.anim.json` declaration.

    The format is deliberately small — one looping legacy clip per entry,
    each a named motion on one bone path:

        {"clips": [{"name": "Idle1", "kind": "bob", "bone": "Root/Pelvis",
                    "amplitude": 0.03, "seconds": 1.5}]}

    `kind` selects the curve builder; `bob` is the only kind today (a
    looping position bob on the bone path). The clip names are what
    `GameObjectAnimalAnimation` plays (`Idle1`, `Walk`, `Attack1`, …), so a
    declaration is how an entity gets a movement clip without an editor.
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
        bone = item.get("bone")
        if not isinstance(name, str) or not name:
            raise PipelineError(f'anim declaration {path} clip {index} needs a "name"')
        if kind not in ("bob",):
            raise PipelineError(
                f'anim declaration {path} clip {name!r} kind must be "bob" (the only kind today)'
            )
        if not isinstance(bone, str) or not bone:
            raise PipelineError(f'anim declaration {path} clip {name!r} needs a "bone" path')
        for key, default in (("amplitude", 0.03), ("seconds", 1.5)):
            value = item.get(key, default)
            if not isinstance(value, (int, float)) or value <= 0:
                raise PipelineError(
                    f"anim declaration {path} clip {name!r} {key!r} must be positive"
                )
        clips.append(
            AnimClip(
                name=name,
                kind=kind,
                bone=bone,
                amplitude=float(item.get("amplitude", 0.03)),
                seconds=float(item.get("seconds", 1.5)),
            )
        )
    play = document.get("play_automatically", True)
    if not isinstance(play, bool):
        raise PipelineError(f'anim declaration {path} "play_automatically" must be a bool')
    return AnimDeclaration(clips=tuple(clips), play_automatically=play)


def clip_fields(declaration: AnimDeclaration) -> tuple[dict[str, Any], ...]:
    """One `AnimationClip` type-tree dict per declared clip."""
    out: list[dict[str, Any]] = []
    for clip in declaration.clips:
        if clip.kind == "bob":
            rotations, positions, scales = idle_bob_curves(
                None, pelvis_bone=clip.bone, bob=clip.amplitude
            )
            # idle_bob_curves is a fixed 1.5 s cycle; rescale its keyframe
            # times to the declared duration.
            factor = clip.seconds / 1.5
            positions = [
                {
                    "curve": {
                        "m_Curve": [
                            {
                                **keyframe,
                                "time": keyframe["time"] * factor,
                            }
                            for keyframe in position["curve"]["m_Curve"]
                        ],
                        "m_PreInfinity": position["curve"]["m_PreInfinity"],
                        "m_PostInfinity": position["curve"]["m_PostInfinity"],
                        "m_RotationOrder": position["curve"]["m_RotationOrder"],
                    },
                    "path": position["path"],
                }
                for position in positions
            ]
            out.append(legacy_clip(clip.name, rotations, positions, scales, sample_rate=30.0))
    return tuple(out)
