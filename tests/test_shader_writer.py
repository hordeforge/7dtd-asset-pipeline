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

import collections
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from sevendtd_asset_pipeline import bundle_writer, shader_blob
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
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

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
        record = shader_blob.code_blob(shader_blob.DX11_PIXEL_SM40, fragment, bind_inputs=False)
        self.assertEqual(record[-8:], struct.pack("<ii", 0, 0))

    def test_a_record_without_its_channel_block_is_short(self) -> None:
        """The omission that made a real runtime refuse the program."""
        fragment = shader_blob.compile_hlsl(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        full = shader_blob.code_blob(shader_blob.DX11_PIXEL_SM40, fragment)
        self.assertEqual(len(full) - len(full[:-8]), 8)


@needs_unitypy
@needs_vkd3d
class ShaderObjectTests(unittest.TestCase):
    def read_back(self, objects: list[Any], name: str = "shaders.unity3d") -> dict[str, Any]:
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
        self.assertEqual(next(iter(parsed.stageCounts)), 2)

    def test_every_code_blob_puts_dxbc_at_offset_38(self) -> None:
        from UnityPy.helpers import CompressionHelper

        parsed = self.read_back([shader(UNLIT_SHADER_NAME)])["Shader"]
        index = list(parsed.platforms).index(shader_blob.SHADER_COMPILER_PLATFORM_D3D11)
        blob = bytes(parsed.compressedBlob)
        start = parsed.offsets[index][0]
        data = CompressionHelper.decompress_lz4(
            blob[start : start + parsed.compressedLengths[index][0]],
            parsed.decompressedLengths[index][0],
        )
        count = struct.unpack_from("<I", data, 0)[0]
        found = 0
        for i in range(count):
            offset, _length, segment = struct.unpack_from("<III", data, 4 + i * 12)
            self.assertEqual(segment, 0, "stock records carry a zero segment word")
            if struct.unpack_from("<I", data, offset + 4)[0] in (
                shader_blob.DX11_VERTEX_SM40,
                shader_blob.DX11_PIXEL_SM40,
            ):
                position = offset + 24
                keywords = struct.unpack_from("<I", data, position)[0]
                self.assertEqual(keywords, 0, "this writer emits no keyword variants")
                size = struct.unpack_from("<I", data, position + 4)[0]
                payload = bytes(data[position + 8 : position + 8 + size])
                self.assertEqual(payload[38:42], b"DXBC")
                found += 1
        self.assertEqual(found, 2, "one vertex and one fragment sub-program")

    def test_a_material_binds_its_shader_and_texture_by_path_id(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            png = one_pixel_png(Path(work) / "albedo.png")
            read = self.read_back(
                [
                    shader(UNLIT_SHADER_NAME),
                    texture_2d("albedo", png),
                    material("propmat", UNLIT_SHADER_NAME, "albedo"),
                ]
            )
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
                REVISION,
                "x.unity3d",
            )
        self.assertIn("absentTexture", str(caught.exception))

    def test_two_shaders_with_one_name_are_refused(self) -> None:
        with self.assertRaises(PipelineError):
            build_bundle(
                [shader(UNLIT_SHADER_NAME), shader(UNLIT_SHADER_NAME)], REVISION, "x.unity3d"
            )


def textured_box(path: Path) -> Path:
    """A box carrying UV0, which is what a mesh with a texture must have.

    `trimesh.creation.box` has no UVs, and the writer now refuses a mesh with
    an `<stem>_albedo` beside it and nothing to sample it with — so a fixture
    that wants the texture bound has to supply the channel a real export does.
    """
    import numpy
    import trimesh

    box = trimesh.creation.box(extents=(1, 1, 1))
    # Any well-formed UV0 will do here: what is under test is that the channel
    # exists and reaches the bundle, not what it maps to.
    extent = box.vertices.max(axis=0) - box.vertices.min(axis=0)
    uv = (box.vertices[:, :2] - box.vertices[:, :2].min(axis=0)) / extent[:2]
    box.visual = trimesh.visual.TextureVisuals(uv=numpy.asarray(uv, dtype=float))
    box.export(path)
    return path


@needs_unitypy
class SourceLaneTests(unittest.TestCase):
    """A mesh source file becomes a prefab only where a shader compiler exists."""

    def pack(self, work: Path) -> collections.Counter[str]:
        return collections.Counter(obj.type.name for obj in self.packed_objects(work))

    def packed_objects(self, work: Path) -> list[Any]:
        import UnityPy

        from sevendtd_asset_pipeline.bundle_writer import pack_directory

        bundle, _manifest = pack_directory(work, "lane.unity3d", REVISION)
        path = work / "out.unity3d"
        path.write_bytes(bundle)
        return list(UnityPy.load(str(path)).objects)

    def source_tree(self, work: Path) -> None:
        textured_box(work / "prop.glb")
        one_pixel_png(work / "prop_albedo.png")

    @unittest.skipUnless(has_capability("trimesh"), "the mesh lane needs trimesh")
    @needs_vkd3d
    def test_a_mesh_becomes_a_prefab_with_a_material_and_a_shader(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self.source_tree(work)
            kinds = self.pack(work)
        self.assertEqual(kinds["GameObject"], 1, "the prefab the game resolves")
        self.assertEqual(kinds["Mesh"], 1)
        self.assertEqual(kinds["Material"], 1)
        self.assertEqual(kinds["Shader"], 1, "one shader shared across the bundle")

    @unittest.skipUnless(has_capability("trimesh"), "the mesh lane needs trimesh")
    def test_without_a_shader_compiler_the_lane_writes_the_bare_mesh(self) -> None:
        """The previous behaviour, kept: packing less, not failing."""
        import shutil
        import unittest.mock

        real = shutil.which
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            self.source_tree(work)
            with unittest.mock.patch(
                "shutil.which",
                lambda name, *a, **k: None if name == "vkd3d-compiler" else real(name, *a, **k),
            ):
                kinds = self.pack(work)
        self.assertEqual(kinds["Mesh"], 1)
        self.assertEqual(kinds["Shader"], 0)
        self.assertEqual(kinds["GameObject"], 0)

    @unittest.skipUnless(has_capability("trimesh"), "the mesh lane needs trimesh")
    @needs_vkd3d
    def test_an_albedo_in_any_texture_format_is_bound_to_the_material(self) -> None:
        """`<stem>_albedo` decided the binding by suffix, not by asset kind.

        Eight suffixes become a Texture2D, and only `.png` was matched, so a
        `.tga` or `.jpg` albedo drew the shader's default white and no gate
        anywhere said why.
        """
        from PIL import Image

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            textured_box(work / "prop.glb")
            Image.new("RGBA", (1, 1), (9, 9, 9, 255)).save(work / "prop_albedo.tga")
            objects = self.packed_objects(work)
        materials = [obj.read() for obj in objects if obj.type.name == "Material"]
        self.assertEqual(len(materials), 1)
        envs = dict(materials[0].m_SavedProperties.m_TexEnvs)
        self.assertNotEqual(
            envs["_MainTex"].m_Texture.m_PathID, 0, "an unbound _MainTex draws the default white"
        )


class UvGuardTests(unittest.TestCase):
    """A texture that can never be sampled is refused, not shipped.

    Blender's glTF exporter drops a UV layer no material samples, so every mesh
    `shamway generate mesh` produced arrived without UVs. The writer bound
    `<stem>_albedo` to the prefab's material anyway, the shader had nothing to
    sample, and the prop drew one flat colour — with the mesh, the material and
    the texture all loading green in a live client.
    """

    @unittest.skipUnless(has_capability("trimesh"), "the mesh lane needs trimesh")
    def test_an_albedo_on_a_mesh_without_uvs_is_refused(self) -> None:
        import trimesh

        from sevendtd_asset_pipeline.bundle_writer import prefab_objects

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            trimesh.creation.box(extents=(1, 1, 1)).export(work / "prop.glb")
            with self.assertRaisesRegex(PipelineError, "no UV channel"):
                prefab_objects(work / "prop.glb", {"prop_albedo"})

    @unittest.skipUnless(has_capability("trimesh"), "the mesh lane needs trimesh")
    def test_a_mesh_without_uvs_and_without_a_texture_is_fine(self) -> None:
        """An untextured prop is a legitimate thing to ship."""
        import trimesh

        from sevendtd_asset_pipeline.bundle_writer import prefab_objects

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            trimesh.creation.box(extents=(1, 1, 1)).export(work / "prop.glb")
            self.assertTrue(prefab_objects(work / "prop.glb", set()))


class DegradedLaneReportTests(unittest.TestCase):
    """A lane that quietly packs less must say so, like every unrun gate here."""

    def caveats(self, compiler_present: bool) -> tuple[str, ...]:
        import shutil
        import unittest.mock

        from sevendtd_asset_pipeline.build import synthesized_caveats

        real = shutil.which
        with unittest.mock.patch(
            "shutil.which",
            lambda name, *a, **k: (
                real(name, *a, **k) if compiler_present or name != "vkd3d-compiler" else None
            ),
        ):
            return synthesized_caveats()

    def test_a_missing_shader_compiler_is_reported_with_what_it_costs(self) -> None:
        joined = " ".join(self.caveats(compiler_present=False))
        self.assertIn("vkd3d-compiler", joined)
        self.assertIn("bare Mesh", joined)

    @needs_vkd3d
    def test_nothing_extra_is_claimed_when_the_lane_is_whole(self) -> None:
        from sevendtd_asset_pipeline.build import SYNTHESIZED_CAVEATS

        self.assertEqual(SYNTHESIZED_CAVEATS, self.caveats(compiler_present=True))


if __name__ == "__main__":
    unittest.main()


class GLCoreRecordTailTests(unittest.TestCase):
    """The eight bytes a GLCore code record carries after its source.

    Both facts here were measured on 2026-08-24 against the twelve type-6
    records in a stock `Legacy Shaders/Transparent/Cutout/VertexLit` taken from
    the installed game, and both were absent from this writer until then. The
    runtime's answer to either was `Failed to load GpuProgram from binary shader
    data` and `Shader.isSupported == False` - naming neither a length nor a
    line - so a unit test is the only place the difference is legible.
    """

    def test_a_source_record_does_not_end_at_its_source(self) -> None:
        blob = shader_blob.source_blob(shader_blob.GL_CORE_32, "x", 17)
        length = struct.unpack_from("<I", blob, 24 + 4)[0]
        end = (24 + 8 + length + 3) & ~3
        self.assertEqual(
            len(blob) - end,
            8,
            "every stock GLCore record carries two further u32 words; a record "
            "that stops at the padded source is eight bytes short of the format "
            "the runtime decodes",
        )
        self.assertEqual(struct.unpack_from("<2I", blob, end), (17, 0))

    def test_the_unlit_mask_names_the_attributes_the_glsl_declares(self) -> None:
        declared = {
            name for name in ("in_POSITION0", "in_TEXCOORD0") if name in shader_blob.UNLIT_GLSL
        }
        self.assertEqual(declared, {"in_POSITION0", "in_TEXCOORD0"})
        self.assertEqual(
            shader_blob.UNLIT_VERTEX_ATTRIBUTES,
            (1 << shader_blob.VERTEX_ATTRIBUTE_POSITION)
            | (1 << shader_blob.VERTEX_ATTRIBUTE_TEXCOORD0),
        )

    def test_both_glsl_halves_declare_the_extension_their_layout_needs(self) -> None:
        """`layout(location = ...)` is not in GLSL 150.

        The fragment half used it without the extension, and glslangValidator
        answered `'location' : not supported for this version or the enabled
        extensions`. Unity reported no such thing - it reported an unsupported
        shader, and the prop drew nothing.
        """
        for half in ("VERTEX", "FRAGMENT"):
            body = shader_blob.UNLIT_GLSL.split(f"#ifdef {half}", 1)[1].split("#endif", 1)[0]
            if "layout(location" not in body:
                continue
            self.assertIn(
                "#extension GL_ARB_explicit_attrib_location : require",
                body,
                f"the {half} half uses layout(location=...) under #version 150 without enabling it",
            )


class GLSLCompilesTests(unittest.TestCase):
    """Compile `UNLIT_GLSL` with a real GLSL compiler.

    The runtime's whole report of a GLSL error is that the shader is
    unsupported and the prop draws nothing. `glslangValidator` gives the line
    and the reason, offline, with no editor and no device - and would have
    caught the missing `GL_ARB_explicit_attrib_location` in one command.

    Skipped when the compiler is absent rather than asserted away: it is an
    optional capability, registered as one, and a host without it is not a
    failing host.
    """

    def _halves(self) -> dict[str, str]:
        source = shader_blob.UNLIT_GLSL
        split = source.index("#ifdef FRAGMENT")
        vertex = source[source.index("#ifdef VERTEX") + len("#ifdef VERTEX") : split]
        fragment = source[split + len("#ifdef FRAGMENT") :]
        # Unity defines the guard symbol and compiles what it wraps, so each
        # body is its section with the `#endif` that closes the guard removed.
        return {
            "vert": vertex.rstrip()[: -len("#endif")],
            "frag": fragment.rstrip()[: -len("#endif")],
        }

    def test_each_half_compiles(self) -> None:
        if shutil.which("glslangValidator") is None:
            self.skipTest("glslangValidator is not installed")
        with tempfile.TemporaryDirectory() as directory:
            for suffix, body in self._halves().items():
                path = Path(directory) / f"unlit.{suffix}"
                path.write_text(body, encoding="utf-8")
                finished = subprocess.run(
                    ["glslangValidator", str(path)],  # noqa: S607
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    finished.returncode,
                    0,
                    f"the {suffix} half does not compile:\n{finished.stdout}{finished.stderr}",
                )


class RenderStateSentinelTests(unittest.TestCase):
    """`name` in a shader render-state value is not free-form.

    A `SerializedShaderFloatValue` carries a constant in `val` **or** the name
    of a material property in `name`. Unity writes the sentinel `<noninit>`
    when there is no property. The empty string is not that sentinel - it is a
    property whose name happens to be empty, so the runtime looks it up, finds
    nothing, and takes 0.

    This writer wrote `""` for every field of every pass's render state, which
    made `colMask` 0: the pass wrote no colour channels and the object was
    invisible, while every symptom looked healthy. The shader loaded,
    `Shader.isSupported` was true, `Material.SetPass(0)` returned true, and
    Unity never fell back because it did not consider the shader failed.

    Found on 2026-08-24 by mutating a stock shader that draws toward this one a
    field at a time: restoring stock's `rtBlend0` alone brought the object back,
    and inside it every `val` already matched - only this string differed.
    """

    def _state(self) -> dict[str, Any]:
        return bundle_writer._shader_state("FORWARD")

    def test_no_render_state_value_carries_an_empty_property_name(self) -> None:
        empty: list[str] = []

        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                name = node.get("name")
                if isinstance(name, str) and name == "":
                    empty.append(path)
                for key, value in node.items():
                    walk(value, f"{path}.{key}")

        walk(self._state(), "m_State")
        self.assertEqual(
            empty,
            [],
            "an empty `name` is a property lookup that fails and yields 0; use "
            f"{bundle_writer.NO_PROPERTY!r}",
        )

    def test_the_colour_mask_survives_as_a_constant(self) -> None:
        """The specific field whose zero made the prop invisible."""
        mask = self._state()["rtBlend0"]["colMask"]
        self.assertEqual(mask["val"], 15.0)
        self.assertEqual(mask["name"], bundle_writer.NO_PROPERTY)


class CBufferLayoutGateTests(unittest.TestCase):
    """The bytecode must read a constant buffer where the runtime fills it.

    Unity fills a constant buffer to **its** layout and the bytecode reads it
    **by offset**, so the HLSL has to reproduce Unity's member order byte for
    byte - including members the shader never reads.

    This is the gate for a bug that was invisible on one graphics API and fatal
    on another: `UnityPerFrame` omitted Unity's four ambient `float4`s, so
    everything after them packed 64 bytes early and `unity_MatrixVP` compiled to
    offset 208 while the runtime writes it at 272. The vertex shader read the
    tail of `unity_MatrixInvV` as its view-projection matrix and put every
    vertex nowhere. No error anywhere, and only on d3d11 - GLSL binds by name,
    so the OpenGL Core sub-program from the same writer drew correctly.
    """

    def _dxbc(self) -> bytes:
        if not has_capability("vkd3d-compiler"):
            self.skipTest("vkd3d-compiler that reads HLSL is not installed")
        return shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")

    def test_the_shipped_shader_reads_every_matrix_where_unity_writes_it(self) -> None:
        packed = shader_blob.compiled_cbuffer_layout(self._dxbc())
        self.assertEqual(
            packed["UnityPerFrame"]["unity_MatrixVP"],
            272,
            "Unity writes the view-projection matrix at byte 272 of UnityPerFrame",
        )
        self.assertEqual(packed["UnityPerDraw"]["unity_ObjectToWorld"], 0)

    def test_the_gate_accepts_the_shipped_shader(self) -> None:
        shader_blob.assert_cbuffer_layout(
            self._dxbc(), (shader_blob.UNITY_PER_DRAW, shader_blob.UNITY_PER_FRAME)
        )

    def test_a_buffer_whose_members_moved_is_refused(self) -> None:
        """The bug itself: one member declared somewhere the bytecode does not read."""
        moved = shader_blob.CBuffer(
            "UnityPerFrame",
            368,
            (shader_blob.CBufferMember("unity_MatrixVP", 208, rows=4, columns=4, is_matrix=True),),
        )
        with self.assertRaisesRegex(PipelineError, "unity_MatrixVP is declared at byte 208"):
            shader_blob.assert_cbuffer_layout(self._dxbc(), (moved,))
