"""Procedural noise shared by the generators that paint texture.

`hide` and `texture_maps` both need a field that wraps exactly at its own
edges, so this is the one definition rather than a copy each. It has no
`GENERATORS` entry because it draws nothing: it is a helper two generators
call, and both gate the optional dependency before they reach it (the numpy
import is deferred into the call for the same reason the rest of the package
defers it, so every module imports on a bare host).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# The zero-frequency bin is the field's mean, which the spectral slope would
# otherwise raise to a power and leave unbounded; it is floored rather than
# removed because the inverse transform still needs a finite multiplier there.
DC_FREQUENCY_FLOOR = 1e-6

# Below this a field is flat to within float noise, and dividing by its peak
# would amplify that noise into visible speckle.
PEAK_FLOOR = 1e-9


def tileable_noise(
    size: int, rng: np.random.Generator, exponent: float, anisotropy: float
) -> np.ndarray:
    """Periodic noise: white noise shaped in the frequency domain.

    Filtering an FFT and transforming back yields a field that wraps exactly,
    so a primitive's default UVs never show a seam. `exponent` is the spectral
    slope (more negative = smoother, larger features); `anisotropy` > 1
    stretches the surviving frequencies along V.
    """
    import numpy as np

    field = rng.standard_normal((size, size))
    fy = np.fft.fftfreq(size)[:, None]
    fx = np.fft.fftfreq(size)[None, :]
    radius = np.sqrt((fx * anisotropy) ** 2 + (fy / anisotropy) ** 2)
    radius[0, 0] = DC_FREQUENCY_FLOOR
    shaped = np.fft.ifft2(np.fft.fft2(field) * radius**exponent).real
    shaped -= shaped.mean()
    peak = np.abs(shaped).max()
    return shaped / peak if peak > PEAK_FLOOR else shaped
