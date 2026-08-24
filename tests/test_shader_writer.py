"""The editorless shader and material lane: what it accepts, and what it refuses.

The container these tests exercise is specified in `hordeforge/7dtd-engine-research`,
`docs/shader-subprogram-blob.md`, and that repository's `tools/shader_blob_dump.py`
re-checks a bundle against it. Acceptance here is read back with UnityPy, which
parses Unity's format with none of this repository's code.

The runtime half of the evidence — a real editor reporting `Shader.isSupported`
— is `shamway verify-bundle` and needs Unity, so it cannot live in this suite.
What it proved is recorded in docs/research/research-provenance.md.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline import shader_blob
from sevendtd_asset_pipeline.bundle_writer import (
    UNLIT_SHADER_NAME,
    build_bundle,
    material,
    shader,
    texture_2d,
)
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError

REVISION = "2022.3.62f2"
needs_unitypy = unittest.skipUnless(
    has_capability("UnityPy"), "the writer needs UnityPy for the engine's type trees"
)
needs_vkd3d = unittest.skipUnless(
    has_capability("vkd3d-compiler"), "the shader lane compiles HLSL with vkd3d-compiler"
)


def one_pixel_png(path: Path) -> Path:
    """A 1x1 opaque PNG, written by hand so the suite needs no image library."""
    import zlib

    raw = b"\x00\xff\x00\x00\xff"
    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


@needs_vkd3d
class CompileTests(unittest.TestCase):
    def test_the_compiler_emits_a_dxbc_container(self) -> None:
        data = shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        self.assertEqual(data[:4], b"DXBC")
        self.assertIn("SHDR", shader_blob.dxbc_chunks(data))

    def test_bad_hlsl_is_refused_with_the_compiler_message(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            shader_blob.compile_hlsl("void main() { this is not hlsl }", "vs_4_0")
        self.assertIn("vkd3d-compiler failed", str(caught.exception))

    def test_declaration_counts_come_from_the_bytecode(self) -> None:
        vertex = shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        fragment = shader_blob.compile_hlsl(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        # The vertex pass reads two constant buffers and samples nothing; the
        # fragment pass samples one texture through one sampler.
        self.assertEqual(shader_blob.declaration_counts(vertex), (0, 2, 0))
        self.assertEqual(shader_blob.declaration_counts(fragment), (1, 0, 1))

    def test_the_program_data_header_is_38_bytes_then_dxbc(self) -> None:
        dxbc = shader_blob.compile_hlsl(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        payload = shader_blob.program_data(dxbc)
        self.assertEqual(payload[38:42], b"DXBC")
        srv, cbuffer, sampler = shader_blob.declaration_counts(dxbc)
        self.assertEqual(payload[0], 2)
        self.assertEqual((payload[1], payload[2], payload[3]), (srv, cbuffer, sampler))
        self.assertEqual(payload[4:6], b"\x00\x00")
        self.assertEqual(payload[6:38], b"\x00" * 32)

    def test_a_program_that_is_not_dxbc_is_refused(self) -> None:
        with self.assertRaises(PipelineError):
            shader_blob.declaration_counts(b"NOTDXBC" + b"\x00" * 64)

    def test_the_temp_register_count_is_read_from_the_bytecode(self) -> None:
        vertex = shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        # The stock VertexLit programs put dcl_temps in this word; a zero here
        # is what the runtime refuses.
        self.assertGreater(shader_blob.temp_register_count(vertex), 0)

    def test_a_vertex_record_carries_its_bind_channels(self) -> None:
        vertex = shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        block = shader_blob.bind_channels(vertex)
        source_map, count = struct.unpack_from("<ii", block, 0)
        channels = [struct.unpack_from("<ii", block, 8 + i * 8) for i in range(count)]
        # POSITION -> (0, 0) and TEXCOORD0 -> (4, 5), the measured mapping.
        self.assertEqual(channels, [(0, 0), (4, 5)])
        for source, _target in channels:
            self.assertTrue(source_map & (1 << source), "sourceMap omits a bound channel")

    def test_a_pixel_record_still_writes_an_empty_channel_block(self) -> None:
        fragment = shader_blob.compile_hlsl(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        record = shader_blob.code_blob(
            shader_blob.DX11_PIXEL_SM40, fragment, bind_inputs=False
        )
        self.assertEqual(record[-8:], struct.pack("<ii", 0, 0))

    def test_a_record_without_its_channel_block_is_short(self) -> None:
        """The omission that made a real runtime refuse the program."""
        fragment = shader_blob.compile_hlsl(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        full = shader_blob.code_blob(shader_blob.DX11_PIXEL_SM40, fragment)
        self.assertEqual(len(full) - len(full[:-8]), 8)


@needs_unitypy
@needs_vkd3d
class ShaderObjectTests(unittest.TestCase):
    def read_back(self, objects: list, name: str = "shaders.unity3d"):
        import UnityPy

        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / name
            path.write_bytes(build_bundle(objects, REVISION, name))
            env = UnityPy.load(str(path))
            return {obj.type.name: obj.read() for obj in env.objects}

    def test_a_shader_reads_back_as_class_48_with_its_name(self) -> None:
        read = self.read_back([shader(UNLIT_SHADER_NAME)])
        self.assertIn("Shader", read)
        self.assertEqual(read["Shader"].m_ParsedForm.m_Name, UNLIT_SHADER_NAME)

    def test_the_shader_declares_one_pass_and_the_platforms_it_compiled(self) -> None:
        parsed = self.read_back([shader(UNLIT_SHADER_NAME)])["Shader"]
        sub_shaders = parsed.m_ParsedForm.m_SubShaders
        self.assertEqual(len(sub_shaders), 1)
        self.assertEqual(len(sub_shaders[0].m_Passes), 1)
        self.assertIn(shader_blob.SHADER_COMPILER_PLATFORM_D3D11, list(parsed.platforms))
        # d3d11 keeps vertex and fragment as separate programs; OpenGLCore
        # carries both stages in one source.
        self.assertEqual(list(parsed.stageCounts)[0], 2)

    def test_every_code_blob_puts_dxbc_at_offset_38(self) -> None:
        from UnityPy.helpers import CompressionHelper

        parsed = self.read_back([shader(UNLIT_SHADER_NAME)])["Shader"]
        index = list(parsed.platforms).index(shader_blob.SHADER_COMPILER_PLATFORM_D3D11)
        blob = bytes(parsed.compressedBlob)
        start = parsed.offsets[index][0]
        data = CompressionHelper.decompress_lz4(
            blob[start:start + parsed.compressedLengths[index][0]],
            parsed.decompressedLengths[index][0],
        )
        count = struct.unpack_from("<I", data, 0)[0]
        found = 0
        for i in range(count):
            offset, _length, segment = struct.unpack_from("<III", data, 4 + i * 12)
            self.assertEqual(segment, 0, "stock records carry a zero segment word")
            if struct.unpack_from("<I", data, offset + 4)[0] in (
                shader_blob.DX11_VERTEX_SM40, shader_blob.DX11_PIXEL_SM40
            ):
                position = offset + 24
                keywords = struct.unpack_from("<I", data, position)[0]
                self.assertEqual(keywords, 0, "this writer emits no keyword variants")
                size = struct.unpack_from("<I", data, position + 4)[0]
                payload = bytes(data[position + 8:position + 8 + size])
                self.assertEqual(payload[38:42], b"DXBC")
                found += 1
        self.assertEqual(found, 2, "one vertex and one fragment sub-program")

    def test_a_material_binds_its_shader_and_texture_by_path_id(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            png = one_pixel_png(Path(work) / "albedo.png")
            read = self.read_back([
                shader(UNLIT_SHADER_NAME),
                texture_2d("albedo", png),
                material("propmat", UNLIT_SHADER_NAME, "albedo"),
            ])
        found = read["Material"]
        self.assertEqual(found.m_Name, "propmat")
        self.assertNotEqual(found.m_Shader.m_PathID, 0, "a null shader is the magenta failure")
        texture_envs = dict(found.m_SavedProperties.m_TexEnvs)
        self.assertIn("_MainTex", texture_envs)
        self.assertNotEqual(texture_envs["_MainTex"].m_Texture.m_PathID, 0)

    def test_a_material_may_leave_its_texture_unbound(self) -> None:
        read = self.read_back([shader(UNLIT_SHADER_NAME), material("m", UNLIT_SHADER_NAME, None)])
        envs = dict(read["Material"].m_SavedProperties.m_TexEnvs)
        self.assertEqual(envs["_MainTex"].m_Texture.m_PathID, 0)


@needs_unitypy
@needs_vkd3d
class RejectionTests(unittest.TestCase):
    def test_a_material_pointing_at_no_shader_is_refused(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            build_bundle([material("m", "Shamway/Absent", None)], REVISION, "x.unity3d")
        self.assertIn("Shamway/Absent", str(caught.exception))

    def test_a_material_pointing_at_a_missing_texture_is_refused(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            build_bundle(
                [shader(UNLIT_SHADER_NAME), material("m", UNLIT_SHADER_NAME, "absentTexture")],
                REVISION, "x.unity3d",
            )
        self.assertIn("absentTexture", str(caught.exception))

    def test_two_shaders_with_one_name_are_refused(self) -> None:
        with self.assertRaises(PipelineError):
            build_bundle(
                [shader(UNLIT_SHADER_NAME), shader(UNLIT_SHADER_NAME)], REVISION, "x.unity3d"
            )


if __name__ == "__main__":
    unittest.main()
