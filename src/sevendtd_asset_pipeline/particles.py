"""ParticleSystem / ParticleSystemRenderer field graphs for the editorless writer.

Every default that is not an obvious zero comes from a real 2022.3.62f2
artifact (see docs/research/research-provenance.md): type trees from UnityPy,
ParticleSystem objects in the installed game's `zombies/lab.bundle`, and the
editor-authored AtomicDoomsday `atomicDoomsdayNukeDetonationVfxLow.prefab`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .capabilities import require_capability
from .errors import PipelineError
from .vfx import (
    CURVE_CONSTANT,
    CURVE_CURVE,
    CURVE_TWO_CURVES,
    Curve,
    Gradient,
    Keyframe,
    VfxSystem,
)

# ParticleSystemShapeType / ParticleSystemRenderMode, as Unity 2022.3 serializes
# them and as lab.bundle / AtomicDoomsday YAML prefabs carry them.
SHAPE_SPHERE = 0
SHAPE_HEMISPHERE = 2
SHAPE_CONE = 4
SHAPE_BOX = 5
SHAPE_CIRCLE = 10
RENDER_BILLBOARD = 0
RENDER_STRETCH = 1
RENDER_HORIZONTAL = 2

# AnimationCurve wrap: 2 = Loop, harvested on every MinMaxCurve in lab.bundle
# and in AtomicDoomsday YAML (`m_PreInfinity: 2`, `m_PostInfinity: 2`,
# `m_RotationOrder: 4`).
CURVE_WRAP = 2
CURVE_ROTATION_ORDER = 4
GRADIENT_TIME_END = 65535


def particle_system_fields(system: VfxSystem, game_object: Any) -> dict[str, Any]:
    """A complete class-198 field tree for one declared system."""
    fields = _class_default(198)
    fields["m_GameObject"] = game_object
    fields["lengthInSec"] = float(system.duration)
    fields["simulationSpeed"] = 1.0
    fields["stopAction"] = 0
    fields["cullingMode"] = 0
    fields["ringBufferMode"] = 0
    fields["ringBufferLoopRange"] = {"x": 0.0, "y": 1.0}
    fields["emitterVelocityMode"] = 1
    fields["looping"] = system.looping
    fields["prewarm"] = False
    fields["playOnAwake"] = system.play_on_awake
    fields["useUnscaledTime"] = False
    fields["autoRandomSeed"] = True
    fields["startDelay"] = _minmax_curve(
        Curve(CURVE_CONSTANT, system.start_delay, system.start_delay, (), ())
    )
    fields["moveWithTransform"] = system.simulation_space
    fields["scalingMode"] = system.scaling_mode
    fields["randomSeed"] = 0
    initial = fields["InitialModule"]
    initial["enabled"] = True
    initial["startLifetime"] = _minmax_curve(system.start_lifetime)
    initial["startSpeed"] = _minmax_curve(system.start_speed)
    initial["startSize"] = _minmax_curve(system.start_size)
    initial["startSizeY"] = _minmax_curve(Curve(CURVE_CONSTANT, 1.0, 1.0, (), ()))
    initial["startSizeZ"] = _minmax_curve(Curve(CURVE_CONSTANT, 1.0, 1.0, (), ()))
    initial["startRotation"] = _minmax_curve(system.start_rotation)
    initial["startColor"] = _minmax_gradient(system.start_color)
    initial["maxNumParticles"] = system.max_particles
    initial["size3D"] = False
    initial["rotation3D"] = False
    initial["gravityModifier"] = _minmax_curve(Curve(CURVE_CONSTANT, 0.0, 0.0, (), ()))
    fields["EmissionModule"] = _emission_module(fields["EmissionModule"], system)
    fields["ShapeModule"] = _shape_module(fields["ShapeModule"], system)
    if system.velocity is not None:
        fields["VelocityModule"] = _velocity_module(fields["VelocityModule"], system)
    if system.limit_velocity is not None:
        fields["ClampVelocityModule"] = _clamp_module(fields["ClampVelocityModule"], system)
    if system.size_over_lifetime is not None:
        fields["SizeModule"] = _size_module(fields["SizeModule"], system.size_over_lifetime)
    if system.rotation_over_lifetime is not None:
        fields["RotationModule"] = _rotation_module(
            fields["RotationModule"], system.rotation_over_lifetime
        )
    if system.color_over_lifetime is not None:
        fields["ColorModule"] = _color_module(fields["ColorModule"], system.color_over_lifetime)
    return fields


def particle_renderer_fields(system: VfxSystem, game_object: Any, material: Any) -> dict[str, Any]:
    """A complete class-199 field tree.

    Billboard defaults (custom vertex streams off, streams `0,1,3,4`,
    `m_MaxParticleSize` 0.5, `m_LengthScale` 2, `m_NormalDirection` 1,
    `m_CastShadows` 0) were read from AtomicDoomsday's editor-authored
    `atomicDoomsdayNukeDetonationVfxLow.prefab` ParticleSystemRenderer
    (class 199, serializedVersion 6).
    """
    fields = _class_default(199)
    fields["m_GameObject"] = game_object
    fields["m_Enabled"] = True
    fields["m_CastShadows"] = 0
    fields["m_ReceiveShadows"] = 0
    fields["m_DynamicOccludee"] = 1
    fields["m_StaticShadowCaster"] = 0
    fields["m_MotionVectors"] = 1
    fields["m_LightProbeUsage"] = 0
    fields["m_ReflectionProbeUsage"] = 0
    fields["m_RayTracingMode"] = 0
    fields["m_RayTraceProcedural"] = 0
    fields["m_RenderingLayerMask"] = 1
    fields["m_RendererPriority"] = 0
    fields["m_LightmapIndex"] = 65535
    fields["m_LightmapIndexDynamic"] = 65535
    fields["m_LightmapTilingOffset"] = {"x": 1.0, "y": 1.0, "z": 0.0, "w": 0.0}
    fields["m_LightmapTilingOffsetDynamic"] = {"x": 1.0, "y": 1.0, "z": 0.0, "w": 0.0}
    fields["m_Materials"] = [material]
    fields["m_StaticBatchInfo"] = {"firstSubMesh": 0, "subMeshCount": 0}
    fields["m_SortingLayerID"] = 0
    fields["m_SortingLayer"] = 0
    fields["m_SortingOrder"] = 0
    fields["m_RenderMode"] = system.renderer.mode
    fields["m_MeshDistribution"] = 0
    fields["m_SortMode"] = 0
    fields["m_MinParticleSize"] = 0.0
    fields["m_MaxParticleSize"] = 0.5
    fields["m_CameraVelocityScale"] = 0.0
    fields["m_VelocityScale"] = float(system.renderer.velocity_scale)
    fields["m_LengthScale"] = float(system.renderer.length_scale)
    fields["m_SortingFudge"] = 0.0
    fields["m_NormalDirection"] = 1.0
    fields["m_ShadowBias"] = 0.0
    fields["m_RenderAlignment"] = 3 if system.renderer.mode == RENDER_STRETCH else 0
    fields["m_Pivot"] = {"x": 0.0, "y": 0.0, "z": 0.0}
    fields["m_Flip"] = {"x": 0.0, "y": 0.0, "z": 0.0}
    fields["m_EnableGPUInstancing"] = True
    fields["m_ApplyActiveColorSpace"] = True
    fields["m_AllowRoll"] = True
    fields["m_FreeformStretching"] = False
    fields["m_RotateWithStretchDirection"] = True
    fields["m_UseCustomVertexStreams"] = False
    fields["m_VertexStreams"] = [0, 1, 3, 4]
    fields["m_UseCustomTrailVertexStreams"] = False
    fields["m_TrailVertexStreams"] = [0, 1, 3, 4]
    fields["m_MeshWeighting"] = 1.0
    fields["m_MeshWeighting1"] = 1.0
    fields["m_MeshWeighting2"] = 1.0
    fields["m_MeshWeighting3"] = 1.0
    fields["m_MaskInteraction"] = 0
    return fields


def _emission_module(module: dict[str, Any], system: VfxSystem) -> dict[str, Any]:
    module["enabled"] = True
    module["rateOverTime"] = _minmax_curve(
        Curve(CURVE_CONSTANT, system.emission.rate, system.emission.rate, (), ())
    )
    module["rateOverDistance"] = _minmax_curve(Curve(CURVE_CONSTANT, 0.0, 0.0, (), ()))
    bursts = []
    for burst in system.emission.bursts:
        count = Curve(CURVE_CONSTANT, float(burst.count), float(burst.count), (), ())
        bursts.append(
            {
                "time": float(burst.time),
                "countCurve": _minmax_curve(count),
                "cycleCount": burst.cycles,
                "repeatInterval": float(burst.interval),
                "probability": 1.0,
            }
        )
    module["m_BurstCount"] = len(bursts)
    module["m_Bursts"] = bursts
    return module


def _shape_module(module: dict[str, Any], system: VfxSystem) -> dict[str, Any]:
    shape = system.shape
    module["enabled"] = True
    module["type"] = shape.type
    module["angle"] = float(shape.angle)
    module["length"] = float(shape.length)
    module["radiusThickness"] = float(shape.radius_thickness)
    module["m_Position"] = {"x": shape.position[0], "y": shape.position[1], "z": shape.position[2]}
    module["m_Rotation"] = {"x": shape.rotation[0], "y": shape.rotation[1], "z": shape.rotation[2]}
    module["m_Scale"] = {"x": shape.scale[0], "y": shape.scale[1], "z": shape.scale[2]}
    module["radius"] = _multi_mode_parameter(shape.radius)
    module["arc"] = _multi_mode_parameter(shape.arc)
    return module


def _velocity_module(module: dict[str, Any], system: VfxSystem) -> dict[str, Any]:
    velocity = system.velocity
    if velocity is None:
        return module
    module["enabled"] = True
    module["x"] = _minmax_curve(velocity.x)
    module["y"] = _minmax_curve(velocity.y)
    module["z"] = _minmax_curve(velocity.z)
    module["inWorldSpace"] = velocity.world_space
    module["speedModifier"] = _minmax_curve(Curve(CURVE_CONSTANT, 1.0, 1.0, (), ()))
    return module


def _clamp_module(module: dict[str, Any], system: VfxSystem) -> dict[str, Any]:
    limit = system.limit_velocity
    if limit is None:
        return module
    module["enabled"] = True
    module["dampen"] = float(limit.dampen)
    module["magnitude"] = _minmax_curve(
        Curve(
            CURVE_CONSTANT,
            limit.magnitude,
            limit.magnitude,
            (),
            (),
        )
    )
    module["separateAxis"] = False
    return module


def _size_module(module: dict[str, Any], curve: Curve) -> dict[str, Any]:
    module["enabled"] = True
    module["curve"] = _minmax_curve(curve)
    module["separateAxes"] = False
    return module


def _rotation_module(module: dict[str, Any], curve: Curve) -> dict[str, Any]:
    module["enabled"] = True
    module["curve"] = _minmax_curve(curve)
    module["separateAxes"] = False
    return module


def _color_module(module: dict[str, Any], gradient: Gradient) -> dict[str, Any]:
    module["enabled"] = True
    module["gradient"] = _minmax_gradient(gradient)
    return module


def _minmax_curve(curve: Curve) -> dict[str, Any]:
    return {
        "minMaxState": curve.state,
        "scalar": float(curve.scalar),
        "minScalar": float(curve.min_scalar),
        "maxCurve": _animation_curve(
            curve.max_keys, curve.state in (CURVE_CURVE, CURVE_TWO_CURVES)
        ),
        "minCurve": _animation_curve(curve.min_keys, curve.state == CURVE_TWO_CURVES),
    }


def _animation_curve(keys: tuple[Any, ...], required: bool) -> dict[str, Any]:
    # Harvested unused curves are empty; a Curve-mode MinMaxCurve with no
    # keyframes is the "Particle curves must all be in the same mode" flood.
    # Constant mode may stay empty (lab.bundle startDelay, rateOverDistance).
    points = list(keys)
    if required and not points:
        points = [Keyframe(0.0, 1.0), Keyframe(1.0, 1.0)]
    return {
        "m_Curve": [
            {
                "time": float(key.time),
                "value": float(key.value),
                "inSlope": 0.0,
                "outSlope": 0.0,
                "weightedMode": 0,
                "inWeight": 0.3333333432674408,
                "outWeight": 0.3333333432674408,
            }
            for key in points
        ],
        "m_PreInfinity": CURVE_WRAP,
        "m_PostInfinity": CURVE_WRAP,
        "m_RotationOrder": CURVE_ROTATION_ORDER,
    }


def _minmax_gradient(gradient: Gradient) -> dict[str, Any]:
    payload = _gradient_payload(gradient)
    return {
        "minMaxState": gradient.state
        if gradient.state in (CURVE_CONSTANT, CURVE_CURVE)
        else CURVE_CONSTANT,
        "minColor": _color(gradient.color),
        "maxColor": _color(gradient.color),
        "maxGradient": payload,
        "minGradient": deepcopy(payload),
    }


def _gradient_payload(gradient: Gradient) -> dict[str, Any]:
    # Unity Gradient: eight colour keys and eight alpha keys, times as uint16
    # in 0..65535. Harvested default (lab.bundle unused gradients): key0/key1
    # white, ctime0=0, ctime1=65535, m_ColorSpace=-1, two keys.
    payload = _empty_gradient()
    if gradient.state == CURVE_CURVE and gradient.stops:
        payload["m_NumColorKeys"] = len(gradient.stops)
        payload["m_NumAlphaKeys"] = len(gradient.stops)
        for index, stop in enumerate(gradient.stops):
            payload[f"key{index}"] = _color(stop.color)
            ticks = round(stop.time * GRADIENT_TIME_END)
            payload[f"ctime{index}"] = ticks
            payload[f"atime{index}"] = ticks
        return payload
    payload["key0"] = _color(gradient.color)
    payload["key1"] = _color(gradient.color)
    payload["ctime1"] = GRADIENT_TIME_END
    payload["atime1"] = GRADIENT_TIME_END
    payload["m_NumColorKeys"] = 2
    payload["m_NumAlphaKeys"] = 2
    return payload


def _empty_gradient() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for index in range(8):
        payload[f"key{index}"] = {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0}
        payload[f"ctime{index}"] = 0
        payload[f"atime{index}"] = 0
    payload["key0"] = {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
    payload["key1"] = {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
    payload["ctime1"] = GRADIENT_TIME_END
    payload["atime1"] = GRADIENT_TIME_END
    payload["m_Mode"] = 0
    payload["m_ColorSpace"] = -1
    payload["m_NumColorKeys"] = 2
    payload["m_NumAlphaKeys"] = 2
    return payload


def _color(color: tuple[float, float, float, float]) -> dict[str, float]:
    return {"r": float(color[0]), "g": float(color[1]), "b": float(color[2]), "a": float(color[3])}


def _multi_mode_parameter(value: float) -> dict[str, Any]:
    # ShapeModule.radius / arc: harvested as value + mode 0 (Random) + spread 0
    # + speed MinMaxCurve scalar 1, empty curves, wrap 2 / rotation 4.
    return {
        "value": float(value),
        "mode": 0,
        "spread": 0.0,
        "speed": _minmax_curve(Curve(CURVE_CONSTANT, 1.0, 1.0, (), ())),
    }


_DEFAULTS: dict[int, dict[str, Any]] = {}


def _class_default(class_id: int) -> dict[str, Any]:
    cached = _DEFAULTS.get(class_id)
    if cached is None:
        cached = _typetree_default(_release_node(class_id))
        _fix_curves_and_gradients(cached)
        _DEFAULTS[class_id] = cached
    return deepcopy(cached)


def _release_node(class_id: int) -> Any:
    from UnityPy.helpers.Tpk import get_typetree_node
    from UnityPy.helpers.UnityVersion import UnityVersion

    require_capability("UnityPy")
    try:
        return get_typetree_node(class_id, UnityVersion.from_str("2022.3.62f2"))
    except Exception as exc:
        raise PipelineError(
            f"no type tree for class {class_id} at Unity 2022.3.62f2: {exc}"
        ) from exc


def _typetree_default(node: Any) -> Any:
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


def _fix_curves_and_gradients(value: Any) -> None:
    if isinstance(value, dict):
        if "m_Curve" in value and "m_PreInfinity" in value:
            value["m_PreInfinity"] = CURVE_WRAP
            value["m_PostInfinity"] = CURVE_WRAP
            value["m_RotationOrder"] = CURVE_ROTATION_ORDER
        if "m_NumColorKeys" in value:
            value.update(_empty_gradient())
        for item in value.values():
            _fix_curves_and_gradients(item)
    elif isinstance(value, list):
        for item in value:
            _fix_curves_and_gradients(item)
