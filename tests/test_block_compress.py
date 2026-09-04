"""Block compression: graded against an independent decoder, not our own.

An encoder checked only by the decoder that ships beside it has not been
checked — the pair can agree on a format nothing else reads. Where
`texture2ddecoder` is installed (declared beside UnityPy in the writer extra,
and it is what UnityPy uses on real game textures) the acceptance test decodes
our blocks with *that* and demands byte equality. A real Unity 2022.3.62f2
runtime also loaded one of these as `160x160 DXT5`; that half needs an editor
and is recorded in docs/research/research-provenance.md.
"""

from __future__ import annotations

import unittest
from typing import Any

from sevendtd_asset_pipeline import block_compress
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError

needs_numpy = unittest.skipUnless(has_capability("numpy"), "the encoder is NumPy arithmetic")


def solid(width: int, height: int, colour: tuple[int, int, int, int]) -> Any:
    import numpy

    image = numpy.empty((height, width, 4), dtype="uint8")
    image[..., 0], image[..., 1], image[..., 2], image[..., 3] = colour
    return image


@needs_numpy
class FormatTests(unittest.TestCase):
    def test_an_opaque_image_becomes_dxt1_at_an_eighth_the_size(self) -> None:
        image = solid(16, 16, (200, 100, 50, 255))
        blocks, texture_format = block_compress.compress(image, alpha=False)
        self.assertEqual(block_compress.TEXTURE_DXT1, texture_format)
        self.assertEqual(image.size // 8, len(blocks))

    def test_an_image_with_alpha_becomes_dxt5_at_a_quarter(self) -> None:
        image = solid(16, 16, (200, 100, 50, 128))
        blocks, texture_format = block_compress.compress(image, alpha=True)
        self.assertEqual(block_compress.TEXTURE_DXT5, texture_format)
        self.assertEqual(image.size // 4, len(blocks))

    def test_sides_that_are_not_a_multiple_of_four_are_refused(self) -> None:
        # Padding silently would move every atlas cell built on the old size.
        with self.assertRaisesRegex(PipelineError, "multiple of 4"):
            block_compress.compress(solid(6, 6, (0, 0, 0, 255)), alpha=False)


@needs_numpy
class QualityTests(unittest.TestCase):
    def test_a_flat_block_does_not_punch_a_transparent_hole(self) -> None:
        """The BC1 three-colour trap.

        When both endpoints quantize to the same value the decoder switches
        modes and index 3 becomes *transparent black*. An encoder that leaves
        a stray index 3 there puts holes in a flat opaque texture.
        """
        image = solid(8, 8, (200, 200, 200, 255))
        blocks, texture_format = block_compress.compress(image, alpha=False)
        back = block_compress.decode(blocks, 8, 8, texture_format)
        self.assertTrue((back[..., 3] == 255).all(), "a flat opaque block lost its alpha")
        # 5/6-bit endpoints cannot hold 200 exactly, but must land within a step.
        self.assertLess(int(abs(int(back[0, 0, 0]) - 200)), 8)

    def test_a_two_colour_image_survives_at_high_fidelity(self) -> None:
        import numpy

        image = solid(16, 16, (40, 40, 40, 255))
        image[:, 8:, :3] = 210
        blocks, texture_format = block_compress.compress(image, alpha=False)
        back = block_compress.decode(blocks, 16, 16, texture_format)
        # Two colours fit BC1's endpoints exactly bar 565 quantization.
        self.assertGreater(block_compress.psnr(image[..., :3], back[..., :3]), 35.0)
        self.assertFalse(numpy.array_equal(image[..., :3], back[..., :3]))

    def test_visible_psnr_ignores_pixels_nobody_can_see(self) -> None:
        """The metric trap that made a good encoder look broken.

        A rendered icon carries renderer noise in the RGB of fully transparent
        pixels. Graded raw it scored 16.9 dB; composited, the same file scores
        about 40. `visible_psnr` measures what a viewer sees.
        """
        import numpy

        rng = numpy.random.default_rng(11)
        original = solid(16, 16, (30, 60, 90, 255))
        original[:, :8, 3] = 0
        decoded = original.copy()
        # Garbage only where alpha is zero.
        decoded[:, :8, :3] = rng.integers(0, 256, (16, 8, 3), dtype="uint8")

        self.assertLess(block_compress.psnr(original[..., :3], decoded[..., :3]), 20.0)
        self.assertEqual(float("inf"), block_compress.visible_psnr(original, decoded))


@unittest.skipUnless(
    has_capability("numpy") and has_capability("UnityPy"),
    "the cross-check needs texture2ddecoder, declared with UnityPy in the writer extra",
)
class IndependentDecoderTests(unittest.TestCase):
    """The acceptance half: a decoder this project did not write."""

    def decode_with_library(self, blocks: bytes, width: int, height: int, alpha: bool) -> Any:
        import numpy
        import texture2ddecoder

        raw = (
            texture2ddecoder.decode_bc3(blocks, width, height)
            if alpha
            else texture2ddecoder.decode_bc1(blocks, width, height)
        )
        image = numpy.frombuffer(raw, dtype="uint8").reshape(height, width, 4)
        return image[..., [2, 1, 0, 3]]  # the library returns BGRA

    def test_dxt5_blocks_decode_identically_in_an_independent_library(self) -> None:
        import numpy

        rng = numpy.random.default_rng(3)
        image = numpy.empty((32, 32, 4), dtype="uint8")
        image[..., :3] = rng.integers(0, 256, (32, 32, 3), dtype="uint8")
        image[..., 3] = rng.integers(0, 256, (32, 32), dtype="uint8")
        blocks, texture_format = block_compress.compress(image, alpha=True)
        self.assertEqual(block_compress.TEXTURE_DXT5, texture_format)
        mine = block_compress.decode(blocks, 32, 32, texture_format)
        theirs = self.decode_with_library(blocks, 32, 32, alpha=True)
        self.assertTrue(numpy.array_equal(mine, theirs), "our decoder and the library disagree")

    def test_dxt1_blocks_decode_identically_in_an_independent_library(self) -> None:
        import numpy

        image = solid(16, 16, (12, 200, 90, 255))
        image[4:8, 4:8, :3] = 250
        blocks, texture_format = block_compress.compress(image, alpha=False)
        mine = block_compress.decode(blocks, 16, 16, texture_format)
        theirs = self.decode_with_library(blocks, 16, 16, alpha=False)
        self.assertTrue(numpy.array_equal(mine[..., :3], theirs[..., :3]))


if __name__ == "__main__":
    unittest.main()
