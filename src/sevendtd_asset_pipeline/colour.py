"""Colour-space conversion, and the checks that keep a generated texture honest.

Every mod on this pipeline eventually generates an albedo rather than painting
one — a tileable fabric, a detail surface, a placard — and generating one means
choosing its colour numerically instead of by eye. That is where the same
mistake keeps being available, and it is not a mistake anyone makes twice
knowingly:

**A colour you set on a material is gamma, not linear.** Unity converts shader
properties declared as ``Color`` from gamma to linear when it uploads them in a
linear-space project. So ``material.color = new Color(0.46f, 0.39f, 0.15f)``
does not put 0.46 into the lighting equation; it puts
``srgb_to_linear(0.46) = 0.179`` there. The triple is sRGB, and the byte values
it corresponds to are ``(117, 99, 38)``.

Generate a texture to replace that flat colour, read the same triple as linear,
and encode it on the way out, and the PNG lands at byte ``(138, 126, 76)``:
brighter, and with double the blue. It renders cream where the material rendered
olive, and — this is the expensive part — it looks exactly like a colour that
needs darkening, so the next change is a fix applied to the wrong thing.

So the rule, stated once:

    A generated albedo replacing a flat ``material.color`` must have that
    colour's **sRGB byte values** as its mean. Not those numbers read as linear.

And because light does not add in gamma space, any *mixing* — grime toward a
dirtier tone, wear toward a bleached one, a weave modulating brightness — has to
happen in linear, between one decode and one encode.

``check_texture`` makes both halves checkable rather than merely written down:
``matches`` pins the mean against the material colour it stands in for, and
``tileable`` catches a detail texture that has stopped wrapping.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

from .capabilities import extra_install, has_capability
from .errors import PipelineError

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# The sRGB transfer function's breakpoints and exponents, from IEC 61966-2-1.
# Named rather than inlined because the two directions must use the same pair,
# and a transfer function that is almost its own inverse is worse than one that
# is obviously not.
_SRGB_LINEAR_CUTOFF = 0.0031308
_SRGB_ENCODED_CUTOFF = 0.04045
_SRGB_SLOPE = 12.92
_SRGB_ALPHA = 0.055
_SRGB_GAMMA = 2.4

# A perfectly tileable field's wrap seam is the size of any interior step. Real
# noise wanders, so the ratio is never exactly one; a texture that has stopped
# wrapping — cropped, resized, or blurred with clamped edges — lands in the
# multiples, not just above one.
DEFAULT_TILE_RATIO = 1.6

# 8-bit quantisation is worth about 1/255; a couple of levels of slack absorbs
# it without admitting a colour that has actually moved.
DEFAULT_COLOUR_TOLERANCE = 6.0 / 255.0


@overload
def srgb_to_linear(value: float) -> float: ...


@overload
def srgb_to_linear(value: Sequence[float] | NDArray[np.float64]) -> NDArray[np.float64]: ...


def srgb_to_linear(value: Any) -> Any:
    """Encoded sRGB in 0..1, linear out. Accepts a scalar, sequence, or array."""
    import numpy as np

    encoded = np.clip(np.asarray(value, dtype=np.float64), 0.0, 1.0)
    linear = np.where(
        encoded <= _SRGB_ENCODED_CUTOFF,
        encoded / _SRGB_SLOPE,
        ((encoded + _SRGB_ALPHA) / (1.0 + _SRGB_ALPHA)) ** _SRGB_GAMMA,
    )
    return float(linear) if np.isscalar(value) else linear


@overload
def linear_to_srgb(value: float) -> float: ...


@overload
def linear_to_srgb(value: Sequence[float] | NDArray[np.float64]) -> NDArray[np.float64]: ...


def linear_to_srgb(value: Any) -> Any:
    """Linear in 0..1, encoded sRGB out. The exact inverse of the above."""
    import numpy as np

    linear = np.clip(np.asarray(value, dtype=np.float64), 0.0, 1.0)
    encoded = np.where(
        linear <= _SRGB_LINEAR_CUTOFF,
        linear * _SRGB_SLOPE,
        (1.0 + _SRGB_ALPHA) * linear ** (1.0 / _SRGB_GAMMA) - _SRGB_ALPHA,
    )
    return float(encoded) if np.isscalar(value) else encoded


def material_colour_to_albedo_bytes(colour: Sequence[float]) -> tuple[int, int, int]:
    """The PNG bytes a generated albedo needs to match a flat ``material.color``.

    The identity function on 0..255, effectively — which is the point. The
    triple is already sRGB, so matching it needs no conversion at all, and the
    whole failure this module exists for is performing one.
    """
    red, green, blue = (round(min(max(channel, 0.0), 1.0) * 255.0) for channel in colour)
    return red, green, blue


@dataclass
class TextureReport:
    path: str
    size: list[int] | None = None
    mean_srgb: list[float] | None = None
    mean_bytes: list[int] | None = None
    mean_linear: list[float] | None = None
    expected_srgb: list[float] | None = None
    colour_drift: float | None = None
    tile_ratio: float | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ok"] = self.ok
        return data


def _tile_ratio(plane: NDArray[np.float64]) -> float:
    """How much worse the wrap seam is than a typical interior step, worst axis."""
    import numpy as np

    worst = 0.0
    for axis in (0, 1):
        seam = float(np.abs(np.take(plane, 0, axis) - np.take(plane, -1, axis)).mean())
        interior = float(np.abs(np.diff(plane, axis=axis)).mean())
        if interior > 1e-12:
            worst = max(worst, seam / interior)
    return worst


def check_texture(
    path: Path,
    matches: tuple[float, float, float] | None = None,
    tolerance: float = DEFAULT_COLOUR_TOLERANCE,
    tileable: bool = False,
    max_tile_ratio: float = DEFAULT_TILE_RATIO,
) -> TextureReport:
    """Measure a generated texture against the two things generation gets wrong.

    ``matches`` is the ``material.color`` triple this texture stands in for,
    exactly as it is written in the asset builder. It is compared in **sRGB**,
    because that is the space the triple is already in; see the module
    docstring for why comparing in linear is the trap rather than the fix.

    ``tileable`` asserts the image still wraps, for a texture tiled across a
    surface larger than itself.
    """
    for capability in ("numpy", "pillow"):
        if not has_capability(capability):
            raise PipelineError(
                f"check-texture needs the '{capability}' capability: " + extra_install("authoring")
            )
    import numpy as np
    from PIL import Image

    path = Path(path).resolve()
    if not path.is_file():
        raise PipelineError(f"no such texture: {path}")

    with Image.open(path) as handle:
        image = handle.convert("RGB")
        report = TextureReport(path=str(path), size=[image.width, image.height])
        encoded = np.asarray(image, dtype=np.float64) / 255.0

    mean_srgb = encoded.reshape(-1, 3).mean(axis=0)
    report.mean_srgb = [round(float(v), 5) for v in mean_srgb]
    report.mean_bytes = [round(float(v) * 255.0) for v in mean_srgb]
    report.mean_linear = [round(float(v), 5) for v in srgb_to_linear(mean_srgb)]

    if matches is not None:
        expected = np.asarray(matches, dtype=np.float64)
        report.expected_srgb = [round(float(v), 5) for v in expected]
        drift = float(np.abs(mean_srgb - expected).max())
        report.colour_drift = round(drift, 5)
        if drift > tolerance:
            wanted = material_colour_to_albedo_bytes(matches)
            report.problems.append(
                f"mean is byte {tuple(report.mean_bytes)} but the material colour it replaces "
                f"is byte {wanted}; drift {drift:.4f} exceeds {tolerance:.4f}. A material "
                f"colour is sRGB — match its byte values, do not read it as linear and encode "
                f"it (that lands ~18% brighter and roughly doubles the blue)"
            )

    if tileable:
        ratio = _tile_ratio(srgb_to_linear(encoded)[..., 0])
        report.tile_ratio = round(ratio, 4)
        if ratio > max_tile_ratio:
            report.problems.append(
                f"wrap seam is {ratio:.2f}x a typical interior step, over {max_tile_ratio:.1f}x; "
                f"the texture has stopped tiling (a crop, a resize, or an edge-clamped blur "
                f"will each do this)"
            )
    else:
        report.notes.append("tiling not checked; pass tileable to assert the image wraps")

    if matches is None:
        report.notes.append(
            "colour not checked; pass matches with the material.color triple this texture replaces"
        )
    return report
