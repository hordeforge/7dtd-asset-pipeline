"""The editorless bundle writer: what it accepts, and what it refuses.

A writer that can only produce files its own reader likes has not been tested,
so every acceptance here is read back with `unityfs.py` *and* — where the
optional reader is installed — with UnityPy, which parses Unity's format
without any of this repository's code. The runtime half of the evidence (a real
editor loading the result) is `shamway verify-bundle`; it needs Unity and so
cannot live in this suite. What it proved is recorded in
docs/research-provenance.md and docs/blockers.md.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from sevendtd_asset_pipeline.bundle_writer import (
    audio_clip,
    build_bundle,
    collect_sources,
    pack_directory,
    render_manifest,
    text_asset,
    texture_2d,
)
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.references import manifest_assets
from sevendtd_asset_pipeline.unityfs import inspect_bundle

REVISION = "2022.3.62f2"
needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"), "the writer needs UnityPy for the engine's type trees"
)


def write_wav(path: Path, *, rate: int = 44100, channels: int = 1, width: int = 2) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", (index * 137) % 8000 - 4000) for index in range(200 * channels)
        )
        handle.writeframes(frames if width == 2 else bytes(len(frames)))
    return path


def write_png(path: Path, size: tuple[int, int] = (4, 2)) -> Path:
    from PIL import Image

    image = Image.new("RGBA", size, (10, 20, 30, 255))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(path)
    return path


@needs_unitypy
class WriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_written_bundle_carries_the_container_object_and_the_revision(self) -> None:
        bundle = self.root / "written.unity3d"
        bundle.write_bytes(
            build_bundle([text_asset("myModNote", "hello")], REVISION, "written.unity3d")
        )
        info = inspect_bundle(bundle)
        self.assertEqual(REVISION, info.unity_version)
        self.assertEqual(8, info.archive_format)
        # 142 is the gate every other consumer of this pipeline depends on.
        self.assertTrue(info.has_assetbundle_object)
        self.assertIn(49, info.class_ids)

    def test_unitypy_reads_back_every_field_this_writer_wrote(self) -> None:
        # An independent reader of Unity's format, with none of our code in it.
        import UnityPy

        bundle = self.root / "readback.unity3d"
        bundle.write_bytes(
            build_bundle(
                [
                    text_asset("myModNote", "hello from shamway"),
                    texture_2d("myModPanel", write_png(self.root / "panel.png")),
                    audio_clip("myModBlast", write_wav(self.root / "blast.wav")),
                ],
                REVISION,
                "readback.unity3d",
            )
        )
        objects = {
            int(obj.type.value): obj.read_typetree() for obj in UnityPy.load(str(bundle)).objects
        }
        self.assertEqual("hello from shamway", objects[49]["m_Script"])
        self.assertEqual((4, 2), (objects[28]["m_Width"], objects[28]["m_Height"]))
        self.assertEqual(4, objects[28]["m_TextureFormat"])  # RGBA32
        self.assertEqual(44100, objects[83]["m_Frequency"])
        self.assertEqual(1, objects[83]["m_Channels"])
        self.assertEqual(0, objects[83]["m_CompressionFormat"])  # PCM, not Vorbis
        container = dict(objects[142]["m_Container"])
        self.assertEqual({"mymodnote", "mymodpanel", "mymodblast"}, set(container))

    def test_the_clip_resource_is_an_fsb5_bank_the_object_points_into(self) -> None:
        import UnityPy

        bundle = self.root / "clip.unity3d"
        bundle.write_bytes(
            build_bundle(
                [audio_clip("myModBlast", write_wav(self.root / "blast.wav"))],
                REVISION,
                "clip.unity3d",
            )
        )
        environment = UnityPy.load(str(bundle))
        clip = next(obj.read_typetree() for obj in environment.objects if obj.type.value == 83)
        streams = {
            name: bytes(reader.bytes)
            for file in environment.files.values()
            for name, reader in file.files.items()
            if name.endswith(".resource")
        }
        self.assertEqual(1, len(streams))
        name, data = next(iter(streams.items()))
        self.assertTrue(clip["m_Resource"]["m_Source"].endswith(name))
        self.assertEqual(b"FSB5", data[:4])
        self.assertGreaterEqual(len(data), clip["m_Resource"]["m_Size"])

    def test_two_builds_of_unchanged_input_are_byte_identical(self) -> None:
        # A rebuild that moves bytes makes every review of the artifact useless.
        objects = [text_asset("myModNote", "hello")]
        first = build_bundle(objects, REVISION, "same.unity3d")
        second = build_bundle([text_asset("myModNote", "hello")], REVISION, "same.unity3d")
        self.assertEqual(first, second)

    def test_two_assets_may_not_answer_to_the_same_name(self) -> None:
        with self.assertRaisesRegex(PipelineError, "same name"):
            build_bundle(
                [text_asset("myModNote", "a"), text_asset("myModNote", "b")],
                REVISION,
                "collide.unity3d",
            )

    def test_a_bundle_with_no_assets_is_refused(self) -> None:
        with self.assertRaisesRegex(PipelineError, "at least one asset"):
            build_bundle([], REVISION, "empty.unity3d")

    def test_a_revision_from_another_era_fails_loudly_rather_than_silently(self) -> None:
        # Type trees are versioned in ranges, so a wrong revision does not come
        # back empty: it comes back as some *other* version's field layout. The
        # writer must refuse to fill a shape it was not given, which is what
        # keeps a mistyped revision from producing a plausible wrong bundle.
        with self.assertRaisesRegex(PipelineError, "cannot serialize"):
            build_bundle([text_asset("x", "y")], "3.4.0f1", "old.unity3d")

    def test_an_unparsable_revision_is_refused(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no type tree"):
            build_bundle([text_asset("x", "y")], "not-a-revision", "bad.unity3d")

    def test_a_clip_at_an_unlisted_sample_rate_is_refused_with_the_fix(self) -> None:
        clip = write_wav(self.root / "odd.wav", rate=12345)
        with self.assertRaisesRegex(PipelineError, "frequency chunk"):
            audio_clip("myModOdd", clip)

    def test_an_eight_bit_clip_is_refused(self) -> None:
        clip = write_wav(self.root / "eight.wav", width=1)
        with self.assertRaisesRegex(PipelineError, "16-bit"):
            audio_clip("myModEight", clip)

    def test_a_clip_whose_header_declares_no_channels_is_a_pipeline_error(self) -> None:
        # `wave` refuses a zero-channel header itself (wave.Error), and
        # audio_clip wraps that: a damaged header must fail as the package's
        # own error, never as a ZeroDivisionError past every handler.
        clip = write_wav(self.root / "zero.wav")
        raw = bytearray(clip.read_bytes())
        raw[22:24] = b"\x00\x00"
        clip.write_bytes(bytes(raw))
        with self.assertRaisesRegex(PipelineError, "cannot read clip"):
            audio_clip("myModZero", clip)

    def test_a_texture_over_pillows_decompression_limit_is_refused_not_crashed(self) -> None:
        # DecompressionBombError subclasses Exception directly, so an OSError-
        # only catch let it escape cli.main's handler as a raw traceback.
        from PIL import Image

        png = write_png(self.root / "big.png", size=(200, 200))
        original = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = 100
        try:
            with self.assertRaisesRegex(PipelineError, "cannot read texture"):
                texture_2d("myModBig", png)
        finally:
            Image.MAX_IMAGE_PIXELS = original


@needs_unitypy
class SourceDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = self.root / "bundle"
        self.sources.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_a_directory_becomes_a_bundle_and_its_membership_manifest(self) -> None:
        (self.sources / "myModNote.txt").write_text("hello", encoding="utf-8")
        write_png(self.sources / "myModPanel.png")
        bundle, manifest_text = pack_directory(self.sources, "mod.unity3d", REVISION)
        manifest = self.root / "mod.unity3d.manifest"
        manifest.write_text(manifest_text, encoding="utf-8")
        # The manifest is read by the same parser that reads Unity's own, so
        # `validate` cannot tell the backends apart.
        self.assertEqual(
            ["bundle/myModNote.txt", "bundle/myModPanel.png"], sorted(manifest_assets(manifest))
        )
        written = self.root / "mod.unity3d"
        written.write_bytes(bundle)
        self.assertTrue(inspect_bundle(written).has_assetbundle_object)

    def test_a_file_this_backend_cannot_write_is_named_not_skipped(self) -> None:
        (self.sources / "myModNote.txt").write_text("hello", encoding="utf-8")
        (self.sources / "myModThing.prefab").write_text("...", encoding="utf-8")
        with self.assertRaisesRegex(PipelineError, "myModThing.prefab"):
            collect_sources(self.sources)

    def test_meta_and_gitkeep_files_are_not_assets(self) -> None:
        (self.sources / ".gitkeep").write_text("", encoding="utf-8")
        (self.sources / "myModNote.txt").write_text("hello", encoding="utf-8")
        (self.sources / "myModNote.txt.meta").write_text("guid: 1", encoding="utf-8")
        self.assertEqual(["myModNote.txt"], [path.name for path in collect_sources(self.sources)])

    def test_an_empty_source_directory_is_refused(self) -> None:
        with self.assertRaisesRegex(PipelineError, "no assets"):
            collect_sources(self.sources)

    def test_a_missing_source_directory_names_what_it_is_for(self) -> None:
        with self.assertRaisesRegex(PipelineError, "bundle source directory"):
            collect_sources(self.root / "absent")


class ManifestTests(unittest.TestCase):
    """The manifest text needs no writer, so it is checked without UnityPy."""

    def test_the_manifest_round_trips_through_unitys_own_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "mod.unity3d.manifest"
            manifest.write_text(
                render_manifest("mod.unity3d", ["bundle/a.png", "bundle/b.wav"]),
                encoding="utf-8",
            )
            self.assertEqual(["bundle/a.png", "bundle/b.wav"], manifest_assets(manifest))


if __name__ == "__main__":
    unittest.main()
