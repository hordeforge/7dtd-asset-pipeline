"""Source formats the standard library cannot read, via FFmpeg and ImageMagick.

These lanes exist so an author can drop what they actually have on disk into
`assets-src/bundle/`. Each test skips when its converter is absent, because
neither is a requirement — a WAV or a PNG still needs nothing installed.

A real Unity 2022.3.62f2 runtime loaded a bundle built this way from an
`.ogg`, an `.mp3` and an `.svg`; that half is in
docs/research/research-provenance.md.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import transcode
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError

has_ffmpeg = shutil.which("ffmpeg") is not None
has_magick = shutil.which("magick") or shutil.which("convert")
# Two of the image tests read the result back with Pillow, which is an
# optional capability of its own: ImageMagick rasterizes, Pillow inspects.
# Gating the class on the rasterizer alone made those two fail on a host that
# had one and not the other.
has_pillow = has_capability("pillow")

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" '
    'viewBox="0 0 40 40"><rect x="4" y="4" width="32" height="32" fill="#b64a2a"/></svg>\n'
)


class PassThroughTests(unittest.TestCase):
    """A format the standard library already reads must cost nothing."""

    def test_a_wav_is_yielded_unchanged_and_starts_no_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.wav"
            source.write_bytes(b"RIFF")
            with transcode.as_wav(source) as result:
                self.assertEqual(source, result)

    def test_a_png_is_yielded_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "panel.png"
            source.write_bytes(b"\x89PNG")
            with transcode.as_png(source) as result:
                self.assertEqual(source, result)


@unittest.skipUnless(has_ffmpeg, "decoding compressed audio needs FFmpeg")
class AudioTests(unittest.TestCase):
    def encode(self, directory: Path, name: str) -> Path:
        source = directory / name
        # ffmpeg by name is deliberate: has_ffmpeg gates this class on the
        # same PATH lookup the pipeline itself uses.
        subprocess.run(
            [  # noqa: S607
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.25",
                "-ac",
                "1",
                "-ar",
                "44100",
                str(source),
            ],
            check=True,
        )
        return source

    def test_an_ogg_decodes_to_a_wav_the_standard_library_reads(self) -> None:
        import wave

        with tempfile.TemporaryDirectory() as directory:
            source = self.encode(Path(directory), "beep.ogg")
            with transcode.as_wav(source) as decoded:
                self.assertNotEqual(source, decoded)
                with wave.open(str(decoded), "rb") as handle:
                    self.assertEqual(2, handle.getsampwidth(), "not 16-bit PCM")
                    self.assertEqual(44100, handle.getframerate())
                    self.assertGreater(handle.getnframes(), 0)

    def test_the_decoded_file_is_temporary_and_the_original_survives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.encode(Path(directory), "beep.ogg")
            before = source.read_bytes()
            with transcode.as_wav(source) as decoded:
                leaked = decoded
            self.assertFalse(leaked.exists(), "the temporary decode outlived its context")
            self.assertEqual(before, source.read_bytes(), "the lossy original was modified")

    def test_a_rate_request_is_honoured(self) -> None:
        import wave

        with tempfile.TemporaryDirectory() as directory:
            source = self.encode(Path(directory), "beep.ogg")
            with (
                transcode.as_wav(source, rate=22050) as decoded,
                wave.open(str(decoded), "rb") as handle,
            ):
                self.assertEqual(22050, handle.getframerate())

    def test_a_file_ffmpeg_cannot_read_fails_with_its_own_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.ogg"
            source.write_bytes(b"not an ogg stream at all")
            with (
                self.assertRaisesRegex(PipelineError, "ffmpeg could not convert"),
                transcode.as_wav(source),
            ):
                pass


@unittest.skipUnless(bool(has_magick), "rasterizing vector art needs ImageMagick")
class ImageTests(unittest.TestCase):
    """Rasterization through ImageMagick; the size checks also need Pillow."""

    @unittest.skipUnless(has_pillow, "reading the raster back needs Pillow")
    def test_an_svg_rasterizes_at_density_over_ninety_six(self) -> None:
        """SVG's user unit is 1/96 inch, so the scale factor is density/96.

        Measured: a 40x40 SVG at the 384 default renders 160x160. Pinning it
        means an author can predict the size instead of discovering it.
        """
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "glyph.svg"
            source.write_text(SVG, encoding="utf-8")
            with transcode.as_png(source) as rendered:
                self.assertNotEqual(source, rendered)
                with Image.open(rendered) as image:
                    self.assertEqual((160, 160), image.size)

            with (
                transcode.as_png(source, density=96) as rendered,
                Image.open(rendered) as image,
            ):
                self.assertEqual((40, 40), image.size)

    @unittest.skipUnless(has_pillow, "reading the raster back needs Pillow")
    def test_a_rasterized_svg_keeps_its_transparent_background(self) -> None:
        # Without -background none, ImageMagick fills SVG transparency white,
        # which reaches the atlas as an opaque card behind every icon.
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "glyph.svg"
            source.write_text(SVG, encoding="utf-8")
            with (
                transcode.as_png(source, density=96) as rendered,
                Image.open(rendered) as image,
            ):
                self.assertEqual(0, image.convert("RGBA").getpixel((1, 1))[3])


if __name__ == "__main__":
    unittest.main()
