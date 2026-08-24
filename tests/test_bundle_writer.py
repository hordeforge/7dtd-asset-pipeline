"""The editorless bundle writer: what it accepts, and what it refuses.

A writer that can only produce files its own reader likes has not been tested,
so every acceptance here is read back with `unityfs.py` *and* — where the
optional reader is installed — with UnityPy, which parses Unity's format
without any of this repository's code. The runtime half of the evidence (a real
editor loading the result) is `shamway verify-bundle`; it needs Unity and so
cannot live in this suite. What it proved is recorded in
docs/research/research-provenance.md and docs/status/blockers.md.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline.bundle_writer import (
    audio_clip,
    build_bundle,
    collect_sources,
    mesh,
    mesh_prefab,
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
needs_trimesh = unittest.skipUnless(
    has_capability("trimesh"), "the mesh lane reads interchange files through trimesh"
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


def write_obj(path: Path, *, uvs: bool = False, faces: bool = True) -> Path:
    """A tetrahedron in plain OBJ text, so the fixture needs no mesh library.

    The first vertex sits at x=+1 and the first face is 1/2/3, which is what
    the handedness assertions below read back out of the written stream.
    """
    lines = ["v 1 0 0", "v 0 1 0", "v 0 0 1", "v 0 0 0"]
    if uvs:
        lines += ["vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1"]
        if faces:
            lines += ["f 1/1 2/2 3/3", "f 1/1 3/3 4/4", "f 1/1 4/4 2/2", "f 2/2 4/4 3/3"]
    elif faces:
        lines += ["f 1 2 3", "f 1 3 4", "f 1 4 2", "f 2 4 3"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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


@needs_unitypy
@needs_trimesh
class MeshTests(unittest.TestCase):
    """The mesh lane: what a real runtime later confirmed, asserted offline.

    A Unity 2022.3.62f2 runtime read both shapes below back through
    `shamway verify-bundle` (docs/research/research-provenance.md, "Mesh
    finding"). These tests hold the layout that made that work.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read_back(self, source: Path) -> dict[str, Any]:
        import UnityPy

        bundle = self.root / "mesh.unity3d"
        bundle.write_bytes(build_bundle([mesh("myModThing", source)], REVISION, "mesh.unity3d"))
        objects = {
            int(obj.type.value): obj.read_typetree() for obj in UnityPy.load(str(bundle)).objects
        }
        self.assertIn(43, objects, "no Mesh object survived the round trip")
        tree: dict[str, Any] = objects[43]
        return tree

    def test_a_mesh_without_uvs_takes_the_short_vertex_stride(self) -> None:
        tree = self.read_back(write_obj(self.root / "myModThing.obj"))
        data = tree["m_VertexData"]
        self.assertEqual(4, data["m_VertexCount"])
        self.assertEqual(24, len(bytes(data["m_DataSize"])) // 4)  # position + normal
        filled = [channel for channel in data["m_Channels"] if channel["dimension"]]
        self.assertEqual([3, 3], [channel["dimension"] for channel in filled])
        self.assertEqual(14, len(data["m_Channels"]), "the full channel table is always declared")

    def test_a_mesh_with_uvs_declares_the_uv0_channel_after_the_normal(self) -> None:
        tree = self.read_back(write_obj(self.root / "myModThing.obj", uvs=True))
        channels = tree["m_VertexData"]["m_Channels"]
        self.assertEqual(
            {"stream": 0, "offset": 24, "format": 0, "dimension": 2},
            channels[4],
            "UV0 lives in slot 4 at the offset the position and normal leave",
        )
        self.assertEqual(
            32 * tree["m_VertexData"]["m_VertexCount"],
            len(bytes(tree["m_VertexData"]["m_DataSize"])),
        )

    def test_the_right_handed_source_is_converted_rather_than_mirrored(self) -> None:
        # The single check that separates a correct mesh from one that loads
        # perfectly and is inside-out: X negated *and* winding reversed.
        tree = self.read_back(write_obj(self.root / "myModThing.obj"))
        stream = bytes(tree["m_VertexData"]["m_DataSize"])
        first_x = struct.unpack_from("<f", stream, 0)[0]
        self.assertEqual(-1.0, first_x, "the OBJ's x=+1 vertex must arrive at x=-1")
        indices = struct.unpack_from("<3H", bytes(tree["m_IndexBuffer"]), 0)
        self.assertEqual((2, 1, 0), indices, "face 1/2/3 must be written back to front")

    def test_the_submesh_and_bounds_describe_the_whole_geometry(self) -> None:
        tree = self.read_back(write_obj(self.root / "myModThing.obj"))
        submesh = tree["m_SubMeshes"][0]
        self.assertEqual(1, len(tree["m_SubMeshes"]))
        self.assertEqual(12, submesh["indexCount"])  # four triangles
        self.assertEqual(0, submesh["topology"])
        self.assertEqual(4, submesh["vertexCount"])
        self.assertEqual(tree["m_LocalAABB"], submesh["localAABB"])
        self.assertAlmostEqual(0.5, tree["m_LocalAABB"]["m_Extent"]["x"], places=5)

    def test_a_mesh_file_with_no_triangles_is_refused_and_names_the_gate(self) -> None:
        empty = write_obj(self.root / "myModThing.obj", faces=False)
        with self.assertRaisesRegex(PipelineError, "check-mesh"):
            mesh("myModThing", empty)

    def test_a_file_trimesh_cannot_parse_is_refused_not_crashed(self) -> None:
        broken = self.root / "myModThing.glb"
        broken.write_bytes(b"not a glb at all")
        with self.assertRaisesRegex(PipelineError, "cannot read mesh"):
            mesh("myModThing", broken)

    def test_a_mesh_is_a_bundle_member_like_any_other_source_file(self) -> None:
        sources = self.root / "bundle"
        sources.mkdir()
        write_obj(sources / "myModThing.obj")
        (sources / "myModNote.txt").write_text("hello", encoding="utf-8")
        bundle, manifest_text = pack_directory(sources, "mod.unity3d", REVISION)
        written = self.root / "mod.unity3d"
        written.write_bytes(bundle)
        self.assertIn(43, inspect_bundle(written).class_ids)
        self.assertIn("bundle/myModThing.obj", manifest_text)


@needs_unitypy
@needs_trimesh
class PrefabTests(unittest.TestCase):
    """Cross-object references, and the prefab they exist for.

    A real 2022.3.62f2 runtime loaded this graph and resolved it
    (`components=3 mesh=... materials=0`); these hold the wiring offline.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self) -> dict[int, list[dict[str, Any]]]:
        import UnityPy

        source = write_obj(self.root / "myModThing.obj")
        objects = [
            mesh("myModThing", source),
            *mesh_prefab("myModProp", "myModThing"),
        ]
        bundle = self.root / "prefab.unity3d"
        bundle.write_bytes(build_bundle(objects, REVISION, "prefab.unity3d"))
        found: dict[int, list[dict[str, Any]]] = {}
        self.ids: dict[int, int] = {}
        for obj in UnityPy.load(str(bundle)).objects:
            found.setdefault(int(obj.type.value), []).append(obj.read_typetree())
            self.ids.setdefault(int(obj.type.value), obj.path_id)
        return found

    def test_every_component_points_back_at_its_game_object(self) -> None:
        objects = self.build()
        game_object = self.ids[1]
        for class_id in (4, 33, 23):
            self.assertEqual(
                game_object,
                objects[class_id][0]["m_GameObject"]["m_PathID"],
                f"class {class_id} lost its GameObject",
            )

    def test_the_mesh_filter_resolves_to_the_mesh_in_the_same_bundle(self) -> None:
        objects = self.build()
        self.assertEqual(self.ids[43], objects[33][0]["m_Mesh"]["m_PathID"])
        self.assertNotEqual(0, objects[33][0]["m_Mesh"]["m_PathID"])

    def test_components_stay_out_of_the_container_but_the_prefab_does_not(self) -> None:
        objects = self.build()
        container = dict(objects[142][0]["m_Container"])
        # Only loadable assets are addressable; four objects, two entries.
        self.assertEqual(["mymodprop", "mymodthing"], sorted(container))

    def test_a_reference_to_an_absent_object_is_refused_by_name(self) -> None:
        # A null PPtr is a prefab that loads and draws nothing, so the writer
        # will not emit one by accident.
        with self.assertRaisesRegex(PipelineError, "absentMesh"):
            build_bundle(mesh_prefab("myModProp", "absentMesh"), REVISION, "dangling.unity3d")

    def test_two_objects_may_not_share_a_reference_key(self) -> None:
        source = write_obj(self.root / "myModThing.obj")
        objects = [mesh("myModThing", source), mesh("myModOther", source)]
        objects[1].key = "myModThing"
        with self.assertRaisesRegex(PipelineError, "reference key"):
            build_bundle(objects, REVISION, "collide.unity3d")


@unittest.skipUnless(
    has_capability("fsb5"), "the independent bank reader needs the 'fsb5' capability"
)
class FsbRoundTripTests(unittest.TestCase):
    """The FSB5 bank, read back by a decoder this project did not write.

    `_fsb5_pcm16` hand-builds the bank byte by byte, so grading it with our own
    parser would grade nothing. python-fsb5 is the same kind of check
    `texture2ddecoder` gives the block compressor. FMOD inside a real Unity
    runtime is the other half, and it is in research-provenance.md.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_an_independent_reader_recovers_the_exact_samples(self) -> None:
        import io
        import wave as wave_module

        import fsb5

        source = write_wav(self.root / "blast.wav")
        with wave_module.open(str(source), "rb") as handle:
            expected = handle.readframes(handle.getnframes())
            channels = handle.getnchannels()
            rate = handle.getframerate()
            frames = handle.getnframes()

        bank = audio_clip("myModBlast", source).resource
        parsed = fsb5.FSB5(bank)
        self.assertEqual(1, parsed.header.numSamples)
        self.assertEqual(2, parsed.header.mode, "the bank should declare PCM16")

        sample = parsed.samples[0]
        self.assertEqual(rate, sample.frequency, "the frequency index decoded wrong")
        self.assertEqual(channels, sample.channels)
        self.assertEqual(frames, sample.samples, "the sample count decoded wrong")

        with wave_module.open(io.BytesIO(parsed.rebuild_sample(sample)), "rb") as handle:
            recovered = handle.readframes(handle.getnframes())
        self.assertEqual(expected, recovered, "PCM did not survive the bank round trip")

    def test_a_stereo_clip_declares_two_channels_to_the_reader(self) -> None:
        # The channel bit is one bit of a packed 64-bit header; getting it
        # wrong halves or doubles the playback rate rather than erroring.
        import fsb5

        source = write_wav(self.root / "stereo.wav", channels=2)
        parsed = fsb5.FSB5(audio_clip("myModStereo", source).resource)
        self.assertEqual(2, parsed.samples[0].channels)


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
