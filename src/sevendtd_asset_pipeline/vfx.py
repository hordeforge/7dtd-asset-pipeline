"""Versioned declarative VFX source for editorless ParticleSystem graphs.

glTF cannot represent emission, lifetime, curves, shape, simulation space or
renderer mode. This format is the asset's authoritative source for those
fields — not metadata that can drift from a prefab. Unknown modules, mixed
curve modes, missing card references and over-budget systems fail here, before
a component is written.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PipelineError

FORMAT = "shamway.vfx"
VERSION = 1
MAX_BUDGET = 10_000
MAX_KEYFRAMES = 8
MAX_BURSTS = 8
MAX_SYSTEMS = 16

SHAPE_TYPES = {
    "sphere": 0,
    "hemisphere": 2,
    "cone": 4,
    "box": 5,
    "circle": 10,
}
RENDER_MODES = {
    "billboard": 0,
    "stretched_billboard": 1,
    "horizontal_billboard": 2,
}
SIMULATION_SPACES = {"local": 0, "world": 1}
SCALING_MODES = {"hierarchy": 0, "local": 1, "shape": 2}
BLEND_MODES = {"alpha": "alpha", "additive": "additive"}
CURVE_CONSTANT = 0
CURVE_CURVE = 1
CURVE_TWO_CONSTANTS = 2
CURVE_TWO_CURVES = 3
SUPPORTED_SYSTEM_KEYS = frozenset(
    {
        "name",
        "duration",
        "looping",
        "play_on_awake",
        "start_delay",
        "simulation_space",
        "scaling_mode",
        "max_particles",
        "start_lifetime",
        "start_speed",
        "start_size",
        "start_rotation",
        "start_color",
        "emission",
        "shape",
        "velocity_over_lifetime",
        "limit_velocity",
        "size_over_lifetime",
        "rotation_over_lifetime",
        "color_over_lifetime",
        "renderer",
    }
)
SUPPORTED_TOP_KEYS = frozenset({"format", "version", "budget", "systems", "materials"})


@dataclass(frozen=True)
class Keyframe:
    time: float
    value: float


@dataclass(frozen=True)
class Curve:
    """A MinMaxCurve in the four Unity modes this writer will serialize."""

    state: int
    scalar: float
    min_scalar: float
    max_keys: tuple[Keyframe, ...]
    min_keys: tuple[Keyframe, ...]


@dataclass(frozen=True)
class GradientStop:
    time: float
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class Gradient:
    state: int
    color: tuple[float, float, float, float]
    stops: tuple[GradientStop, ...]


@dataclass(frozen=True)
class Burst:
    time: float
    count: int
    cycles: int
    interval: float


@dataclass(frozen=True)
class Emission:
    rate: float
    bursts: tuple[Burst, ...]


@dataclass(frozen=True)
class Shape:
    type: int
    type_name: str
    radius: float
    angle: float
    length: float
    radius_thickness: float
    arc: float
    scale: tuple[float, float, float]
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]


@dataclass(frozen=True)
class VelocityOverLifetime:
    x: Curve
    y: Curve
    z: Curve
    world_space: bool


@dataclass(frozen=True)
class LimitVelocity:
    dampen: float
    magnitude: float


@dataclass(frozen=True)
class Renderer:
    mode: int
    mode_name: str
    material: str
    length_scale: float
    velocity_scale: float


@dataclass(frozen=True)
class VfxMaterial:
    name: str
    blend: str
    texture: str


@dataclass(frozen=True)
class VfxSystem:
    name: str
    duration: float
    looping: bool
    play_on_awake: bool
    start_delay: float
    simulation_space: int
    scaling_mode: int
    max_particles: int
    start_lifetime: Curve
    start_speed: Curve
    start_size: Curve
    start_rotation: Curve
    start_color: Gradient
    emission: Emission
    shape: Shape
    velocity: VelocityOverLifetime | None
    limit_velocity: LimitVelocity | None
    size_over_lifetime: Curve | None
    rotation_over_lifetime: Curve | None
    color_over_lifetime: Gradient | None
    renderer: Renderer


@dataclass(frozen=True)
class VfxDeclaration:
    source: Path
    budget: int
    systems: tuple[VfxSystem, ...]
    materials: tuple[VfxMaterial, ...]


def parse_vfx(source: Path) -> VfxDeclaration:
    """Load a `.vfx` JSON document and reject anything this writer will not encode."""
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read VFX {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PipelineError(f"{source.name} is not a JSON object")
    unknown = sorted(set(raw) - SUPPORTED_TOP_KEYS)
    if unknown:
        raise PipelineError(
            f"{source.name} declares unsupported top-level keys {unknown}; "
            f"this format is {FORMAT} version {VERSION}"
        )
    if raw.get("format") != FORMAT:
        raise PipelineError(f"{source.name} is not {FORMAT!r} (got {raw.get('format')!r})")
    if raw.get("version") != VERSION:
        raise PipelineError(
            f"{source.name} is version {raw.get('version')!r}; this writer reads version {VERSION}"
        )
    budget = raw.get("budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise PipelineError(f"{source.name} budget must be a positive integer")
    if budget > MAX_BUDGET:
        raise PipelineError(
            f"{source.name} budget {budget} exceeds the writer cap of {MAX_BUDGET} live particles"
        )
    materials_raw = raw.get("materials")
    if not isinstance(materials_raw, list) or not materials_raw:
        raise PipelineError(f"{source.name} must declare at least one material")
    materials = tuple(
        _parse_material(item, source, index) for index, item in enumerate(materials_raw)
    )
    names = [item.name for item in materials]
    if len(names) != len(set(names)):
        raise PipelineError(f"{source.name} declares two materials with the same name")
    material_names = set(names)
    systems_raw = raw.get("systems")
    if not isinstance(systems_raw, list) or not systems_raw:
        raise PipelineError(f"{source.name} must declare at least one system")
    if len(systems_raw) > MAX_SYSTEMS:
        raise PipelineError(
            f"{source.name} declares {len(systems_raw)} systems; the cap is {MAX_SYSTEMS}"
        )
    systems = tuple(
        _parse_system(item, source, index, material_names) for index, item in enumerate(systems_raw)
    )
    system_names = [item.name for item in systems]
    if len(system_names) != len(set(system_names)):
        raise PipelineError(f"{source.name} declares two systems with the same name")
    total = sum(item.max_particles for item in systems)
    if total > budget:
        raise PipelineError(
            f"{source.name} allows {total} live particles, over its budget of {budget}. "
            "Lower max_particles, or raise the budget deliberately."
        )
    used = {item.renderer.material for item in systems}
    unused = sorted(material_names - used)
    if unused:
        raise PipelineError(f"{source.name} materials {unused} are never referenced by a renderer")
    return VfxDeclaration(source, budget, systems, materials)


def _parse_material(item: Any, source: Path, index: int) -> VfxMaterial:
    if not isinstance(item, dict):
        raise PipelineError(f"{source.name} material {index} is not an object")
    name = item.get("name")
    blend = item.get("blend")
    texture = item.get("texture")
    extra = sorted(set(item) - {"name", "blend", "texture"})
    if extra:
        raise PipelineError(f"{source.name} material {name!r} has unsupported keys {extra}")
    if not isinstance(name, str) or not name:
        raise PipelineError(f"{source.name} material {index} needs a name")
    if blend not in BLEND_MODES:
        raise PipelineError(
            f"{source.name} material {name!r} blend {blend!r} is not one of {sorted(BLEND_MODES)}"
        )
    if not isinstance(texture, str) or not texture:
        raise PipelineError(f"{source.name} material {name!r} needs a texture stem")
    return VfxMaterial(name, blend, texture)


def _parse_system(item: Any, source: Path, index: int, materials: set[str]) -> VfxSystem:
    if not isinstance(item, dict):
        raise PipelineError(f"{source.name} system {index} is not an object")
    extra = sorted(set(item) - SUPPORTED_SYSTEM_KEYS)
    if extra:
        raise PipelineError(
            f"{source.name} system {item.get('name', index)!r} declares unsupported modules {extra}"
        )
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise PipelineError(f"{source.name} system {index} needs a name")
    where = f"{source.name} system {name!r}"
    max_particles = item.get("max_particles")
    if not isinstance(max_particles, int) or isinstance(max_particles, bool) or max_particles < 1:
        raise PipelineError(f"{where} max_particles must be a positive integer")
    renderer = _parse_renderer(item.get("renderer"), where, materials)
    return VfxSystem(
        name=name,
        duration=_positive_float(item.get("duration", 5.0), where, "duration"),
        looping=_bool(item.get("looping", False), where, "looping"),
        play_on_awake=_bool(item.get("play_on_awake", True), where, "play_on_awake"),
        start_delay=_non_negative_float(item.get("start_delay", 0.0), where, "start_delay"),
        simulation_space=_enum(
            item.get("simulation_space", "local"), SIMULATION_SPACES, where, "simulation_space"
        ),
        scaling_mode=_enum(
            item.get("scaling_mode", "hierarchy"), SCALING_MODES, where, "scaling_mode"
        ),
        max_particles=max_particles,
        start_lifetime=_curve(item.get("start_lifetime", 5.0), where, "start_lifetime"),
        start_speed=_curve(item.get("start_speed", 0.0), where, "start_speed"),
        start_size=_curve(item.get("start_size", 1.0), where, "start_size"),
        start_rotation=_degrees_curve(item.get("start_rotation", 0.0), where, "start_rotation"),
        start_color=_gradient(item.get("start_color", [1, 1, 1, 1]), where, "start_color"),
        emission=_parse_emission(item.get("emission"), where),
        shape=_parse_shape(item.get("shape"), where),
        velocity=_parse_velocity(item.get("velocity_over_lifetime"), where),
        limit_velocity=_parse_limit(item.get("limit_velocity"), where),
        size_over_lifetime=_optional_curve(
            item.get("size_over_lifetime"), where, "size_over_lifetime"
        ),
        rotation_over_lifetime=_optional_degrees_curve(
            item.get("rotation_over_lifetime"), where, "rotation_over_lifetime"
        ),
        color_over_lifetime=_optional_gradient(
            item.get("color_over_lifetime"), where, "color_over_lifetime"
        ),
        renderer=renderer,
    )


def _parse_emission(item: Any, where: str) -> Emission:
    if item is None:
        return Emission(0.0, ())
    if not isinstance(item, dict):
        raise PipelineError(f"{where} emission must be an object")
    extra = sorted(set(item) - {"rate", "bursts"})
    if extra:
        raise PipelineError(f"{where} emission has unsupported keys {extra}")
    rate = _non_negative_float(item.get("rate", 0.0), where, "emission.rate")
    bursts_raw = item.get("bursts") or []
    if not isinstance(bursts_raw, list):
        raise PipelineError(f"{where} emission.bursts must be a list")
    if len(bursts_raw) > MAX_BURSTS:
        raise PipelineError(f"{where} has {len(bursts_raw)} bursts; the cap is {MAX_BURSTS}")
    bursts = []
    for index, burst in enumerate(bursts_raw):
        if not isinstance(burst, dict):
            raise PipelineError(f"{where} burst {index} is not an object")
        count = burst.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise PipelineError(f"{where} burst {index} count must be a positive integer")
        cycles = burst.get("cycles", 1)
        if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles < 1:
            raise PipelineError(f"{where} burst {index} cycles must be a positive integer")
        bursts.append(
            Burst(
                time=_non_negative_float(burst.get("time", 0.0), where, f"burst {index} time"),
                count=count,
                cycles=cycles,
                interval=_positive_float(
                    burst.get("interval", 0.01), where, f"burst {index} interval"
                ),
            )
        )
    return Emission(rate, tuple(bursts))


def _parse_shape(item: Any, where: str) -> Shape:
    if not isinstance(item, dict) or "type" not in item:
        raise PipelineError(f"{where} needs a shape with a type")
    extra = sorted(
        set(item)
        - {
            "type",
            "radius",
            "angle",
            "length",
            "radius_thickness",
            "arc",
            "scale",
            "position",
            "rotation",
        }
    )
    if extra:
        raise PipelineError(f"{where} shape has unsupported keys {extra}")
    type_name = item["type"]
    if type_name not in SHAPE_TYPES:
        raise PipelineError(f"{where} shape type {type_name!r} is not one of {sorted(SHAPE_TYPES)}")
    return Shape(
        type=SHAPE_TYPES[type_name],
        type_name=type_name,
        radius=_non_negative_float(item.get("radius", 1.0), where, "shape.radius"),
        angle=_non_negative_float(item.get("angle", 25.0), where, "shape.angle"),
        length=_positive_float(item.get("length", 5.0), where, "shape.length"),
        radius_thickness=_unit_float(
            item.get("radius_thickness", 1.0), where, "shape.radius_thickness"
        ),
        arc=_clamped_float(item.get("arc", 360.0), 0.0, 360.0, where, "shape.arc"),
        scale=_vec3(item.get("scale", [1, 1, 1]), where, "shape.scale"),
        position=_vec3(item.get("position", [0, 0, 0]), where, "shape.position"),
        rotation=_vec3(item.get("rotation", [0, 0, 0]), where, "shape.rotation"),
    )


def _parse_velocity(item: Any, where: str) -> VelocityOverLifetime | None:
    if item is None:
        return None
    if not isinstance(item, dict):
        raise PipelineError(f"{where} velocity_over_lifetime must be an object")
    extra = sorted(set(item) - {"x", "y", "z", "space"})
    if extra:
        raise PipelineError(f"{where} velocity_over_lifetime has unsupported keys {extra}")
    x = _curve(item.get("x", 0.0), where, "velocity.x")
    y = _curve(item.get("y", 0.0), where, "velocity.y")
    z = _curve(item.get("z", 0.0), where, "velocity.z")
    if not (x.state == y.state == z.state):
        raise PipelineError(
            f"{where} velocity_over_lifetime axes must share one curve mode "
            f"(got x={x.state} y={y.state} z={z.state}); Unity logs "
            "'Particle Velocity curves must all be in the same mode' on every update otherwise"
        )
    space = item.get("space", "local")
    if space not in SIMULATION_SPACES:
        raise PipelineError(f"{where} velocity space {space!r} is not local or world")
    return VelocityOverLifetime(x, y, z, world_space=space == "world")


def _parse_limit(item: Any, where: str) -> LimitVelocity | None:
    if item is None:
        return None
    if not isinstance(item, dict):
        raise PipelineError(f"{where} limit_velocity must be an object")
    extra = sorted(set(item) - {"dampen", "magnitude"})
    if extra:
        raise PipelineError(f"{where} limit_velocity has unsupported keys {extra}")
    return LimitVelocity(
        dampen=_unit_float(item.get("dampen", 0.0), where, "limit_velocity.dampen"),
        magnitude=_non_negative_float(
            item.get("magnitude", 1.0), where, "limit_velocity.magnitude"
        ),
    )


def _parse_renderer(item: Any, where: str, materials: set[str]) -> Renderer:
    if not isinstance(item, dict):
        raise PipelineError(f"{where} needs a renderer")
    extra = sorted(set(item) - {"mode", "material", "length_scale", "velocity_scale"})
    if extra:
        raise PipelineError(f"{where} renderer has unsupported keys {extra}")
    mode_name = item.get("mode", "billboard")
    if mode_name not in RENDER_MODES:
        raise PipelineError(
            f"{where} renderer mode {mode_name!r} is not one of {sorted(RENDER_MODES)}"
        )
    material = item.get("material")
    if not isinstance(material, str) or material not in materials:
        raise PipelineError(
            f"{where} renderer material {material!r} is not one of {sorted(materials)}"
        )
    return Renderer(
        mode=RENDER_MODES[mode_name],
        mode_name=mode_name,
        material=material,
        length_scale=_finite_float(item.get("length_scale", 2.0), where, "renderer.length_scale"),
        velocity_scale=_finite_float(
            item.get("velocity_scale", 0.0), where, "renderer.velocity_scale"
        ),
    )


def _curve(value: Any, where: str, field: str) -> Curve:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = _finite_float(value, where, field)
        return Curve(CURVE_CONSTANT, number, number, (), ())
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) for v in value)
    ):
        lo = _finite_float(value[0], where, field)
        hi = _finite_float(value[1], where, field)
        return Curve(CURVE_TWO_CONSTANTS, hi, lo, (), ())
    if isinstance(value, dict) and "curve" in value:
        extra = sorted(set(value) - {"curve"})
        if extra:
            raise PipelineError(f"{where} {field} has unsupported keys {extra}")
        keys = _keyframes(value["curve"], where, field)
        return Curve(CURVE_CURVE, 1.0, 1.0, keys, ())
    if isinstance(value, dict) and "min_curve" in value and "max_curve" in value:
        extra = sorted(set(value) - {"min_curve", "max_curve"})
        if extra:
            raise PipelineError(f"{where} {field} has unsupported keys {extra}")
        return Curve(
            CURVE_TWO_CURVES,
            1.0,
            1.0,
            _keyframes(value["max_curve"], where, field),
            _keyframes(value["min_curve"], where, field),
        )
    raise PipelineError(
        f"{where} {field} is not a constant, [min, max] pair, curve, or two-curve pair"
    )


def _optional_curve(value: Any, where: str, field: str) -> Curve | None:
    return None if value is None else _curve(value, where, field)


def _degrees_curve(value: Any, where: str, field: str) -> Curve:
    curve = _curve(value, where, field)
    return Curve(
        curve.state,
        math.radians(curve.scalar),
        math.radians(curve.min_scalar),
        tuple(Keyframe(k.time, math.radians(k.value)) for k in curve.max_keys),
        tuple(Keyframe(k.time, math.radians(k.value)) for k in curve.min_keys),
    )


def _optional_degrees_curve(value: Any, where: str, field: str) -> Curve | None:
    return None if value is None else _degrees_curve(value, where, field)


def _keyframes(value: Any, where: str, field: str) -> tuple[Keyframe, ...]:
    if not isinstance(value, list) or not value:
        raise PipelineError(f"{where} {field} curve needs at least one keyframe")
    if len(value) > MAX_KEYFRAMES:
        raise PipelineError(
            f"{where} {field} has {len(value)} keyframes; the cap is {MAX_KEYFRAMES}"
        )
    keys = []
    previous = -1.0
    for index, item in enumerate(value):
        if not isinstance(item, list) or len(item) != 2:
            raise PipelineError(f"{where} {field} keyframe {index} must be [time, value]")
        time = _unit_float(item[0], where, f"{field} key {index} time")
        if time < previous:
            raise PipelineError(f"{where} {field} keyframes must be in non-decreasing time order")
        previous = time
        keys.append(Keyframe(time, _finite_float(item[1], where, f"{field} key {index} value")))
    return tuple(keys)


def _gradient(value: Any, where: str, field: str) -> Gradient:
    if (
        isinstance(value, list)
        and len(value) in (3, 4)
        and all(isinstance(v, (int, float)) for v in value)
    ):
        color = _color(value, where, field)
        return Gradient(CURVE_CONSTANT, color, ())
    if isinstance(value, dict) and "gradient" in value:
        extra = sorted(set(value) - {"gradient"})
        if extra:
            raise PipelineError(f"{where} {field} has unsupported keys {extra}")
        stops_raw = value["gradient"]
        if not isinstance(stops_raw, list) or not stops_raw:
            raise PipelineError(f"{where} {field} gradient needs at least one stop")
        if len(stops_raw) > 8:
            raise PipelineError(f"{where} {field} gradient has more than 8 stops")
        stops = []
        previous = -1.0
        for index, stop in enumerate(stops_raw):
            if not isinstance(stop, dict) or "t" not in stop or "color" not in stop:
                raise PipelineError(f"{where} {field} stop {index} needs t and color")
            time = _unit_float(stop["t"], where, f"{field} stop {index} t")
            if time < previous:
                raise PipelineError(
                    f"{where} {field} gradient stops must be in non-decreasing time"
                )
            previous = time
            stops.append(GradientStop(time, _color(stop["color"], where, f"{field} stop {index}")))
        return Gradient(CURVE_CURVE, stops[0].color, tuple(stops))
    raise PipelineError(f"{where} {field} is not a colour or a gradient")


def _optional_gradient(value: Any, where: str, field: str) -> Gradient | None:
    return None if value is None else _gradient(value, where, field)


def _color(value: Any, where: str, field: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) not in (3, 4):
        raise PipelineError(f"{where} {field} colour must be [r,g,b] or [r,g,b,a]")
    channels = [_unit_float(channel, where, field) for channel in value]
    if len(channels) == 3:
        channels.append(1.0)
    return (channels[0], channels[1], channels[2], channels[3])


def _enum(value: Any, table: dict[str, int], where: str, field: str) -> int:
    if value not in table:
        raise PipelineError(f"{where} {field} {value!r} is not one of {sorted(table)}")
    return table[value]


def _bool(value: Any, where: str, field: str) -> bool:
    if not isinstance(value, bool):
        raise PipelineError(f"{where} {field} must be a boolean")
    return value


def _finite_float(value: Any, where: str, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineError(f"{where} {field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise PipelineError(f"{where} {field} is not finite")
    return number


def _non_negative_float(value: Any, where: str, field: str) -> float:
    number = _finite_float(value, where, field)
    if number < 0:
        raise PipelineError(f"{where} {field} must be >= 0")
    return number


def _positive_float(value: Any, where: str, field: str) -> float:
    number = _finite_float(value, where, field)
    if number <= 0:
        raise PipelineError(f"{where} {field} must be > 0")
    return number


def _unit_float(value: Any, where: str, field: str) -> float:
    return _clamped_float(value, 0.0, 1.0, where, field)


def _clamped_float(value: Any, lo: float, hi: float, where: str, field: str) -> float:
    number = _finite_float(value, where, field)
    if number < lo or number > hi:
        raise PipelineError(f"{where} {field} must be between {lo} and {hi}")
    return number


def _vec3(value: Any, where: str, field: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise PipelineError(f"{where} {field} must be three numbers")
    return (
        _finite_float(value[0], where, field),
        _finite_float(value[1], where, field),
        _finite_float(value[2], where, field),
    )
