"""The gamma trap, held shut in both directions.

`colour.check_texture` exists because of one specific and expensive mistake, and
these tests are that mistake written down as code. A mod generated a tileable
albedo to replace a flat `material.color` of (0.46, 0.39, 0.15), read those
numbers as *linear*, and encoded them to sRGB on the way into the PNG. Unity had
always been treating them as gamma. The texture landed at byte (138, 126, 76)
where the material had rendered byte (117, 99, 38) — brighter, with double the
blue — and mustard came out cream.

What makes it worth a gate rather than a paragraph is the second half: the
result looks exactly like a colour that needs darkening. The next change is
therefore a correction applied to the wrong thing, and it makes the texture
*more* wrong while looking like progress.

So the checks below pin, in order: that the two transfer functions are actually
inverses; that the wrong reading is detected and the right one passes; that the
error message points at the cause rather than the symptom; and that tiling
survives the three operations that silently destroy it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.colour import (
    check_texture,
    linear_to_srgb,
    material_colour_to_albedo_bytes,
    srgb_to_linear,
)
from sevendtd_asset_pipeline.errors import PipelineError

# numpy and Pillow are optional extras, and the base CI job installs neither.
# Importing them at module scope made this whole file an ImportError there
# rather than a skip, which turned a green suite red for a reason that had
# nothing to do with the change under test.
try:  # pragma: no cover - exercised by whether the extra is installed
    import numpy as np
    from PIL import Image, ImageFilter

    HAVE_IMAGING = True
except ImportError:  # pragma: no cover
    HAVE_IMAGING = False

# The material colour from the incident, exactly as an asset builder writes it.
MATERIAL_COLOUR = (0.46, 0.39, 0.15)


def _solid(path: Path, rgb: tuple[int, int, int], size: int = 64) -> Path:
    Image.new("RGB", (size, size), rgb).save(path)
    return path


def _tileable_noise(size: int, seed: int) -> np.ndarray:
    """Periodic noise, by construction: white noise shaped in the frequency domain."""
    rng = np.random.default_rng(seed)
    field = rng.standard_normal((size, size))
    fy = np.fft.fftfreq(size)[:, None]
    fx = np.fft.fftfreq(size)[None, :]
    radius = np.sqrt(fx**2 + fy**2)
    radius[0, 0] = 1e-6
    shaped = np.fft.ifft2(np.fft.fft2(field) * radius**-1.2).real
    shaped -= shaped.mean()
    peak = np.abs(shaped).max()
    return shaped / peak if peak > 1e-9 else shaped


@unittest.skipUnless(HAVE_IMAGING, "the colour lane needs numpy and Pillow")
class TransferFunctionTests(unittest.TestCase):
    def test_round_trips(self) -> None:
        # Away from the breakpoint the pair is exact to floating point.
        for value in (0.0, 0.002, 0.02, 0.15, 0.46, 0.9, 1.0):
            self.assertAlmostEqual(linear_to_srgb(srgb_to_linear(value)), value, places=12)
            self.assertAlmostEqual(srgb_to_linear(linear_to_srgb(value)), value, places=12)

    def test_the_breakpoint_is_the_standard_not_us(self) -> None:
        """sRGB's published constants do not quite meet, and that is not a bug here.

        IEC 61966-2-1 rounds its breakpoints to 0.0031308 and 0.04045 and its
        slope to 12.92, and those rounded values are mutually inconsistent: the
        linear segment and the power segment miss each other by about 3e-8 at
        the join. Asserting an exact round trip there would fail forever, and
        "fix" it by inventing constants that are not the standard's.

        Pinned rather than skipped, so a future edit that *widens* the gap —
        a typo in an exponent, a different alpha — is still caught. 3e-8 is
        1e-5 of one 8-bit level; nothing in a texture can carry it.
        """
        for value in (0.0031308, 0.04045):
            error = abs(linear_to_srgb(srgb_to_linear(value)) - value)
            self.assertLess(error, 1e-7)

    def test_known_values(self) -> None:
        # The number the incident turned on: 0.46 as a material colour is 0.179
        # in the lighting equation, not 0.46.
        self.assertAlmostEqual(srgb_to_linear(0.46), 0.178868, places=6)
        # Below the breakpoint the curve is linear, not a power.
        self.assertAlmostEqual(srgb_to_linear(0.02), 0.02 / 12.92, places=12)

    def test_a_material_colour_is_already_srgb(self) -> None:
        self.assertEqual(material_colour_to_albedo_bytes(MATERIAL_COLOUR), (117, 99, 38))


@unittest.skipUnless(HAVE_IMAGING, "the colour lane needs numpy and Pillow")
class ColourMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_correct_reading_passes(self) -> None:
        texture = _solid(self.root / "right.png", (117, 99, 38))
        report = check_texture(texture, matches=MATERIAL_COLOUR)
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.mean_bytes, [117, 99, 38])

    def test_the_incident_is_rejected(self) -> None:
        """Reading the material colour as linear and encoding it: the actual bug."""
        red, green, blue = (
            round(float(c) * 255) for c in linear_to_srgb(np.asarray(MATERIAL_COLOUR))
        )
        wrong = (red, green, blue)
        self.assertEqual(wrong, (181, 168, 108))
        report = check_texture(_solid(self.root / "wrong.png", wrong), matches=MATERIAL_COLOUR)
        self.assertFalse(report.ok)
        # The message has to name the cause. A drift number alone is what sends
        # the next session off darkening the colour instead.
        joined = " ".join(report.problems)
        self.assertIn("sRGB", joined)
        self.assertIn("do not read it as linear", joined)

    def test_darkening_the_wrong_thing_is_also_rejected(self) -> None:
        """The plausible 'fix' for the symptom stays a failure."""
        red, green, blue = (
            round(float(c) * 255) for c in linear_to_srgb(np.asarray(MATERIAL_COLOUR) * 0.55)
        )
        report = check_texture(
            _solid(self.root / "dark.png", (red, green, blue)), matches=MATERIAL_COLOUR
        )
        self.assertFalse(report.ok)

    def test_quantisation_is_within_tolerance(self) -> None:
        report = check_texture(
            _solid(self.root / "off.png", (118, 100, 39)), matches=MATERIAL_COLOUR
        )
        self.assertTrue(report.ok, report.problems)

    def test_colour_is_not_checked_unless_asked(self) -> None:
        report = check_texture(_solid(self.root / "any.png", (5, 5, 5)))
        self.assertTrue(report.ok)
        self.assertTrue(any("colour not checked" in note for note in report.notes))

    def test_missing_file(self) -> None:
        with self.assertRaises(PipelineError):
            check_texture(self.root / "absent.png", matches=MATERIAL_COLOUR)


@unittest.skipUnless(HAVE_IMAGING, "the colour lane needs numpy and Pillow")
class TilingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        field = _tileable_noise(128, seed=7)
        self.pixels = np.clip(0.45 + field * 0.12, 0.0, 1.0)
        self.tileable = self.root / "tileable.png"
        self._save(self.pixels, self.tileable)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _save(self, plane: np.ndarray, path: Path) -> Path:
        rgb = np.repeat((plane * 255).astype(np.uint8)[..., None], 3, axis=2)
        Image.fromarray(rgb, "RGB").save(path)
        return path

    def test_tileable_passes(self) -> None:
        report = check_texture(self.tileable, tileable=True)
        self.assertTrue(report.ok, report.problems)
        self.assertIsNotNone(report.tile_ratio)
        assert report.tile_ratio is not None
        self.assertLess(report.tile_ratio, 1.6)

    def test_edge_clamped_blur_is_caught(self) -> None:
        with Image.open(self.tileable) as handle:
            blurred = handle.convert("RGB").filter(ImageFilter.GaussianBlur(3))
        path = self.root / "blurred.png"
        blurred.save(path)
        report = check_texture(path, tileable=True)
        self.assertFalse(report.ok)
        self.assertIn("stopped tiling", " ".join(report.problems))

    def test_crop_and_resize_is_caught(self) -> None:
        with Image.open(self.tileable) as handle:
            image = handle.convert("RGB")
            cropped = image.crop((12, 12, image.width - 12, image.height - 12))
            resized = cropped.resize(image.size, Image.LANCZOS)
        path = self.root / "cropped.png"
        resized.save(path)
        report = check_texture(path, tileable=True)
        self.assertFalse(report.ok)

    def test_rolling_preserves_tiling(self) -> None:
        """A control: rolling a periodic field cannot break its periodicity."""
        path = self._save(np.roll(self.pixels, 41, axis=1), self.root / "rolled.png")
        self.assertTrue(check_texture(path, tileable=True).ok)

    def test_tiling_is_not_checked_unless_asked(self) -> None:
        report = check_texture(self.tileable)
        self.assertIsNone(report.tile_ratio)
        self.assertTrue(any("tiling not checked" in note for note in report.notes))


@unittest.skipUnless(HAVE_IMAGING, "the colour lane needs numpy and Pillow")
class DeterminismTests(unittest.TestCase):
    def test_same_file_gives_the_same_report_twice(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            texture = _solid(Path(name) / "t.png", (117, 99, 38))
            first = check_texture(texture, matches=MATERIAL_COLOUR, tileable=True)
            second = check_texture(texture, matches=MATERIAL_COLOUR, tileable=True)
            self.assertEqual(first.as_dict(), second.as_dict())


if __name__ == "__main__":
    unittest.main()
