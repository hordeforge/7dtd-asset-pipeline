"""The editorless shader and material lane: what it accepts, and what it refuses.

The container these tests exercise is specified in `hordeforge/7dtd-engine-research`,
`docs/shader-subprogram-blob.md`, and that repository's `tools/shader_blob_dump.py`
re-checks a bundle against it. Acceptance here is read back with the pinned
unityz CLI, which parses Unity's format with none of this repository's writer
code.

The runtime half of the evidence — a real editor reporting `Shader.isSupported`
— is `shamway verify-bundle` and needs Unity, so it cannot live in this suite.
What it proved is recorded in docs/research/research-provenance.md.
"""

from __future__ import annotations

import collections
import ctypes
import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from unityz_readback import ReadbackObject, read_bundle, show_object

from sevendtd_asset_pipeline import bundle_writer, shader_blob
from sevendtd_asset_pipeline.bundle_writer import (
    GAME_OBJECT,
    MATERIAL,
    MESH,
    SHADER,
    UNLIT_SHADER_NAME,
    build_bundle,
    material,
    shader,
    texture_2d,
)
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError

REVISION = "2022.3.62f2"
needs_unityz = unittest.skipUnless(
    has_capability("unityz"), "the writer needs unityz for the engine's type trees"
)
needs_vkd3d = unittest.skipUnless(
    has_capability("vkd3d-compiler"), "the shader lane compiles HLSL with vkd3d-compiler"
)
needs_lz4 = unittest.skipUnless(
    importlib.util.find_spec("lz4") is not None,
    "shader blob compression needs the lz4 writer extra (declared in the writer extra)",
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
        """The omission that made a real runtime refuse the program.

        The block is pinned on a vertex record, whose table is non-empty:
        a pixel record's empty table is indistinguishable from no table at
        all in a length check.
        """
        vertex = shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        record = shader_blob.code_blob(shader_blob.DX11_VERTEX_SM40, vertex)
        block = shader_blob.bind_channels(vertex)
        self.assertGreater(len(block), 8, "the fixture must bind channels to be evidence")
        self.assertTrue(
            record.endswith(block),
            "the code blob ends with its channel table; dropping it is the "
            "omission that made the runtime refuse the program",
        )


class CompileTimeoutTests(unittest.TestCase):
    """Every compiler run is bounded, and a wedged one dies as a named error.

    `build` and `pack` are published operations reachable through
    `shamway serve`, so one hung vkd3d-compiler would block that long-lived
    session on a request forever. The bound is pinned here without needing a
    real compiler installed: `which` and `subprocess.run` are both faked.
    """

    @staticmethod
    def compile_calls() -> list[tuple[collections.abc.Callable[[], Any], str]]:
        """Each compiler entry point with the tool it must name on expiry."""
        return [
            (
                lambda: shader_blob.compile_hlsl(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0"),
                "vkd3d-compiler",
            ),
            (lambda: shader_blob.compile_spirv(b"DXBC"), "vkd3d-compiler"),
            (
                lambda: shader_blob.compile_spirv_glslang(shader_blob.UNLIT_VERTEX_HLSL, "vert"),
                "glslangValidator",
            ),
        ]

    def test_every_compile_runs_under_a_timeout(self) -> None:
        """The bound reaches subprocess.run, proven on the success path.

        The fake run writes a plausible artifact beside `-o`, so the action
        completes instead of dying on a missing file: an unrelated failure
        cannot mask whether the timeout kwarg was passed.
        """

        def successful_run(seen: dict[str, Any]) -> collections.abc.Callable[..., Any]:
            def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
                seen.update(kwargs)
                out = Path(command[command.index("-o") + 1])
                payload = b"DXBC" + b"\x00" * 64
                if "spirv-binary" in command or "--target-env" in command:
                    payload = struct.pack("<I", shader_blob.SPIRV_MAGIC) + b"\x00" * 64
                out.write_bytes(payload)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            return run

        for action, _tool in self.compile_calls():
            seen: dict[str, Any] = {}
            with (
                mock.patch(
                    "sevendtd_asset_pipeline.shader_blob.shutil.which",
                    side_effect=lambda name: "/usr/bin/fake-tool",
                ),
                mock.patch(
                    "sevendtd_asset_pipeline.shader_blob.subprocess.run",
                    side_effect=successful_run(seen),
                ),
            ):
                action()
            self.assertEqual(shader_blob.SHADER_COMPILE_TIMEOUT, seen.get("timeout"))

    def test_a_wedged_compiler_is_killed_and_named(self) -> None:
        for action, tool in self.compile_calls():

            def wedge(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
                raise subprocess.TimeoutExpired(command[0], shader_blob.SHADER_COMPILE_TIMEOUT)

            with (
                mock.patch(
                    "sevendtd_asset_pipeline.shader_blob.shutil.which",
                    return_value="/usr/bin/fake-tool",
                ),
                mock.patch(
                    "sevendtd_asset_pipeline.shader_blob.subprocess.run",
                    side_effect=wedge,
                ),
                self.assertRaises(PipelineError) as caught,
            ):
                action()
            message = str(caught.exception)
            self.assertIn(tool, message)
            self.assertIn("killed", message)


@needs_unityz
@needs_vkd3d
@needs_lz4
class ShaderObjectTests(unittest.TestCase):
    def read_back(
        self, objects: list[Any], name: str = "shaders.unity3d"
    ) -> dict[int, list[dict[str, Any]]]:
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / name
            path.write_bytes(build_bundle(objects, REVISION, name))
            return read_bundle(path).trees_by_class()

    def read_shader(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "shaders.unity3d"
            path.write_bytes(build_bundle([shader(UNLIT_SHADER_NAME)], REVISION, path.name))
            return show_object(path, SHADER)

    def test_a_shader_reads_back_as_class_48_with_its_name(self) -> None:
        read = self.read_back([shader(UNLIT_SHADER_NAME)])
        self.assertIn(SHADER, read)
        self.assertEqual(read[SHADER][0]["m_ParsedForm"]["m_Name"], UNLIT_SHADER_NAME)

    def test_the_shader_declares_one_pass_and_the_platforms_it_compiled(self) -> None:
        parsed = self.read_shader()
        sub_shaders = parsed["m_ParsedForm"]["m_SubShaders"]
        self.assertEqual(len(sub_shaders), 1)
        self.assertEqual(len(sub_shaders[0]["m_Passes"]), 1)
        self.assertIn(shader_blob.SHADER_COMPILER_PLATFORM_D3D11, parsed["platforms"])
        # d3d11 keeps vertex and fragment as separate programs; OpenGLCore
        # carries both stages in one source.
        self.assertEqual(parsed["stageCounts"][0], 2)

    def test_unityz_decodes_both_dxbc_program_records(self) -> None:
        decoded = self.read_shader()["shaderBlob"]
        records = [record for record in decoded["records"] if record["kind"] == "code"]
        self.assertEqual({record["stage"] for record in records}, {"vertex", "fragment"})
        self.assertEqual(
            {record["programType"] for record in records},
            {shader_blob.DX11_VERTEX_SM40, shader_blob.DX11_PIXEL_SM40},
        )
        for record in records:
            self.assertEqual(record["segment"], 0, "stock records carry a zero segment word")
            self.assertIn("SHDR", record["dxbc"]["chunks"])

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
        found = read[MATERIAL][0]
        self.assertEqual(found["m_Name"], "propmat")
        self.assertNotEqual(
            found["m_Shader"]["m_PathID"], 0, "a null shader is the magenta failure"
        )
        texture_envs = dict(found["m_SavedProperties"]["m_TexEnvs"])
        self.assertIn("_MainTex", texture_envs)
        self.assertNotEqual(texture_envs["_MainTex"]["m_Texture"]["m_PathID"], 0)

    def test_a_material_may_leave_its_texture_unbound(self) -> None:
        read = self.read_back([shader(UNLIT_SHADER_NAME), material("m", UNLIT_SHADER_NAME, None)])
        envs = dict(read[MATERIAL][0]["m_SavedProperties"]["m_TexEnvs"])
        self.assertEqual(envs["_MainTex"]["m_Texture"]["m_PathID"], 0)


@needs_unityz
@needs_vkd3d
class RejectionTests(unittest.TestCase):
    def test_a_material_pointing_at_no_shader_is_refused(self) -> None:
        with self.assertRaises(PipelineError) as caught:
            build_bundle([material("m", "Shamway/Absent", None)], REVISION, "x.unity3d")
        self.assertIn("Shamway/Absent", str(caught.exception))

    @needs_lz4
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


@needs_unityz
class SourceLaneTests(unittest.TestCase):
    """A mesh source file becomes a prefab only where a shader compiler exists."""

    def pack(self, work: Path) -> collections.Counter[int]:
        return collections.Counter(obj.class_id for obj in self.packed_objects(work))

    def packed_objects(self, work: Path) -> tuple[ReadbackObject, ...]:
        from sevendtd_asset_pipeline.bundle_writer import pack_directory

        bundle, _manifest = pack_directory(work, "lane.unity3d", REVISION)
        path = work / "out.unity3d"
        path.write_bytes(bundle)
        return read_bundle(path).objects

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
        self.assertEqual(kinds[GAME_OBJECT], 1, "the prefab the game resolves")
        self.assertEqual(kinds[MESH], 1)
        self.assertEqual(kinds[MATERIAL], 1)
        self.assertEqual(kinds[SHADER], 1, "one shader shared across the bundle")

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
        self.assertEqual(kinds[MESH], 1)
        self.assertEqual(kinds[SHADER], 0)
        self.assertEqual(kinds[GAME_OBJECT], 0)

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
        materials = [obj.tree for obj in objects if obj.class_id == MATERIAL]
        self.assertEqual(len(materials), 1)
        envs = dict(materials[0]["m_SavedProperties"]["m_TexEnvs"])
        self.assertNotEqual(
            envs["_MainTex"]["m_Texture"]["m_PathID"],
            0,
            "an unbound _MainTex draws the default white",
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

        from sevendtd_asset_pipeline.bundle_writer import (
            BOX_COLLIDER,
            GAME_OBJECT,
            MATERIAL,
            MESH,
            MESH_FILTER,
            MESH_RENDERER,
            TRANSFORM,
            prefab_objects,
        )

        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            trimesh.creation.box(extents=(1, 1, 1)).export(work / "prop.glb")
            objects = prefab_objects(work / "prop.glb", set())
            kinds = {o.class_id for o in objects}
            self.assertEqual(
                {GAME_OBJECT, TRANSFORM, MESH, MESH_FILTER, MESH_RENDERER, MATERIAL, BOX_COLLIDER},
                kinds,
                "an untextured mesh still ships a complete, collider-bearing prefab group",
            )


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


class VulkanSubProgramTests(unittest.TestCase):
    """Platform 18: two SMOL-V modules behind a 176-byte header.

    Decoded from shipped 2022.3 bundles. The invariants here are the ones
    measured across four stock shaders, so a record that breaks one is wrong
    before any runtime sees it.
    """

    def test_the_record_satisfies_every_measured_invariant(self) -> None:
        fragment, vertex = b"F" * 391, b"V" * 4123
        record = shader_blob.vulkan_code_blob(fragment, vertex)
        self.assertEqual(struct.unpack_from("<I", record, 4)[0], shader_blob.VULKAN_PROGRAM)
        payload_length = struct.unpack_from("<I", record, 28)[0]
        payload = record[32 : 32 + payload_length]
        word0, section_a, section_b, header, a_payload, word5 = struct.unpack_from(
            "<6I", payload, 0
        )
        self.assertEqual(word0, 0x02000060)
        self.assertEqual(header, shader_blob.VULKAN_SECTION_HEADER)
        self.assertEqual(a_payload, section_a - shader_blob.VULKAN_SECTION_HEADER)
        self.assertEqual(word5, 0)
        # The payload length is padded to 4 so the bind-channels block that
        # follows it is never read from mid-padding (a 882-byte payload made a
        # live Vulkan draw fault that way); the two sections sum to the
        # unpadded length, so they are within 0..3 bytes of the field.
        unpadded = section_a + section_b
        self.assertLessEqual(unpadded, payload_length)
        self.assertLess(payload_length - unpadded, 4)
        self.assertEqual(payload_length % 4, 0, "payload length is 4-aligned")
        self.assertEqual(struct.unpack_from("<I", payload, 19 * 4)[0], 1)

    def test_both_sections_carry_their_module(self) -> None:
        fragment, vertex = b"F" * 391, b"V" * 4123
        record = shader_blob.vulkan_code_blob(fragment, vertex)
        payload_length = struct.unpack_from("<I", record, 28)[0]
        payload = record[32 : 32 + payload_length]
        section_a = struct.unpack_from("<I", payload, 4)[0]
        self.assertEqual(payload[shader_blob.VULKAN_SECTION_HEADER :][: len(fragment)], fragment)
        self.assertEqual(payload[section_a:][: len(vertex)], vertex)

    def test_the_record_ends_with_its_bind_channels(self) -> None:
        """The block whose absence drew the prop as the magenta shader.

        A stock Vulkan code record carries a `ParserBindChannels` table after
        its payload, exactly as a d3d11 vertex record does. Ours omitted it and
        was refused with no log line - found by byte-diffing against a stock
        record with the same modules: identical but for the (unvalidated) hash,
        and stock was 32 bytes longer, this block.

        The targets are the vertex-input declaration slots offset by 13, not
        the d3d11 vertex-component slots and not the bare SPIR-V locations:
        reusing the d3d11 targets fed the vertex shader the wrong stream and
        hung a live client mid-draw. Measured across seven stock shaders in
        the installed game - VertexLit (0,13)(1,14)(4,15) for SPIR-V locations
        0,1,2, Bumped Diffuse (0,13)(1,14)(2,15)(4,16), Particles/Additive
        (0,13)(3,14)(4,15) - so every target is location + 13. Our glslang
        vertex module declares location 0 (Position) and 1 (TexCoord0).
        """
        fragment, vertex = b"F" * 391, b"V" * 4123
        record = shader_blob.vulkan_code_blob(fragment, vertex)
        payload_length = struct.unpack_from("<I", record, 28)[0]
        tail = record[32 + payload_length :]
        expected = shader_blob.vulkan_bind_channels()
        self.assertEqual(tail[len(tail) - len(expected) :], expected)
        mask, count = struct.unpack_from("<2I", expected, 0)
        self.assertEqual(mask, (1 << 0) | (1 << 4), "Position and TexCoord0")
        self.assertEqual(count, 2)
        pairs = [struct.unpack_from("<2I", expected, 8 + i * 8) for i in range(count)]
        self.assertEqual(
            pairs,
            [(0, 13), (4, 14)],
            "targets are the vertex-input declaration slots + 13, the stock convention",
        )

    @needs_lz4
    def test_the_platform_is_absent_without_the_encoder(self) -> None:
        """A host without the codec builds what it always did, rather than failing."""
        if not has_capability("vkd3d-compiler"):
            self.skipTest("vkd3d-compiler that reads HLSL is not installed")
        with mock.patch.object(shader_blob, "smolv_library", return_value=None):
            platforms = [p.platform for p in shader_blob.unlit_textured().platforms]
        self.assertNotIn(shader_blob.SHADER_COMPILER_PLATFORM_VULKAN, platforms)
        self.assertIn(shader_blob.SHADER_COMPILER_PLATFORM_D3D11, platforms)

    def test_the_vulkan_fragment_is_one_combined_image_sampler(self) -> None:
        """The module shape every stock fragment module has, and the HLSL form lacks.

        Unity's own Vulkan modules are glslang output on the GLSL its HLSLCC
        emits, so `uniform sampler2D` becomes a single `OpTypeSampledImage`
        variable at set 0, binding 0. The HLSL form (`Texture2D` +
        `SamplerState`) makes glslang emit an image **and** a sampler as two
        variables on the same binding - a shape no stock module carries, and
        one whose draw killed a live client on AMD RADV (device lost, no log
        line). This pins the GLSL form so a future refactor cannot regress it
        back to the split.
        """
        if shutil.which("glslangValidator") is None:
            self.skipTest("glslangValidator that compiles the GLSL is not installed")
        spirv = shader_blob.compile_spirv_glslang(
            shader_blob.UNLIT_FRAGMENT_GLSL_VULKAN, "frag", language="glsl"
        )
        words = struct.unpack(f"<{len(spirv) // 4}I", spirv)
        types: dict[int, int] = {}  # id -> opcode (25 image, 26 sampler, 27 sampled-image)
        pointers: dict[int, int] = {}  # id -> target id
        variables: dict[int, int] = {}  # id -> type id
        decorations: dict[int, dict[int, int]] = {}
        index = 5  # after the SPIR-V header
        while index < len(words):
            word = words[index]
            count, opcode = word >> 16, word & 0xFFFF
            operands = words[index + 1 : index + count]
            if opcode in (25, 26, 27):
                types[operands[0]] = opcode
            elif opcode == 32:  # OpTypePointer: result, storage, target
                pointers[operands[0]] = operands[2]
            elif opcode == 59:  # OpVariable: result-type, result, storage
                variables[operands[1]] = operands[0]
            elif opcode == 71 and len(operands) >= 3 and operands[1] in (33, 34):
                # OpDecorate: target, decoration (33=set, 34=binding), value
                decorations.setdefault(operands[0], {})[operands[1]] = operands[2]
            index += count
        sampled_images = [
            var_id
            for var_id, type_id in variables.items()
            if types.get(pointers.get(type_id, type_id)) == 27
        ]
        self.assertEqual(len(sampled_images), 1, "exactly one combined image-sampler variable")
        var_id = sampled_images[0]
        self.assertEqual(
            decorations[var_id].get(33, None), 0, "descriptor set 0, as stock declares"
        )
        self.assertEqual(decorations[var_id].get(34, None), 0, "binding 0, as stock declares")
        self.assertNotIn(
            26,
            {types.get(t) for t in variables.values()},
            "no bare sampler variable: the split form is what a live client's draw killed",
        )

    @needs_lz4
    def test_the_vulkan_texture_entry_uses_the_stock_index(self) -> None:
        """The material binder keys on the texture entry's index, and stock
        records encode it as `(fragment stage << 24) | slot` = 0x08000000 for
        `_MainTex` - an index of 0 made the Vulkan draw fault (AMD RADV,
        device lost, no log line) with every other dimension of the record
        stock-shaped. The module's own descriptor binding stays 0; the runtime
        derives the binding from the module, not this index."""
        if shader_blob.smolv_library() is None:
            self.skipTest("the SMOL-V encoder is not loadable")
        compiled = shader_blob.unlit_textured()
        vulkan = next(p for p in compiled.platforms if p.platform == 18)
        raw = __import__("lz4").block.decompress(
            vulkan.blob, uncompressed_size=vulkan.decompressed_size
        )
        count = struct.unpack_from("<I", raw, 0)[0]
        self.assertGreaterEqual(count, 1, "the container declares at least one record")
        off, ln, _ = struct.unpack_from("<III", raw, 4)
        param = raw[off : off + ln]
        index = param.find(b"_MainTex")
        self.assertGreater(index, 40, "the texture entry is inside the parameter record")
        fstart = (index + len(b"_MainTex") + 3) & ~3
        entry = struct.unpack_from("<4I", param, fstart)
        self.assertEqual(entry[1], 0x08000000, "fragment stage, slot 0 - the measured stock value")
        self.assertEqual(entry[2], 0xFFFFFFFF, "no separate sampler, as stock declares")

    @needs_lz4
    def test_the_vulkan_cbuffer_entry_uses_the_stock_index(self) -> None:
        """The vertex program binds its globals buffer through the entry index,
        which stock encodes as `(vertex stage << 24) | kind | slot` = 0x04010000
        for `VGlobals` in a vertex parameter record - ours wrote a plain 0 with
        array size 1, and the Vulkan draw faulted (AMD RADV, device lost, no
        log line) while every other dimension of the record was stock-shaped.
        """
        if shader_blob.smolv_library() is None:
            self.skipTest("the SMOL-V encoder is not loadable")
        compiled = shader_blob.unlit_textured()
        vulkan = next(p for p in compiled.platforms if p.platform == 18)
        raw = __import__("lz4").block.decompress(
            vulkan.blob, uncompressed_size=vulkan.decompressed_size
        )
        off, ln, _ = struct.unpack_from("<III", raw, 4)
        param = raw[off : off + ln]
        # The buffer section names the same buffer first; the binding entry is
        # the last occurrence of the name in the record.
        index = param.rfind(b"VGlobals")
        self.assertGreater(index, 40, "the binding entry is inside the parameter record")
        fstart = (index + len(b"VGlobals") + 3) & ~3
        entry = struct.unpack_from("<3I", param, fstart)
        self.assertEqual(entry[0], 1, "cbuffer entry kind, as stock writes")
        self.assertEqual(entry[1], 0x04010000, "vertex stage, slot 0 - the measured stock value")
        self.assertEqual(entry[2], 0, "array size 0, as stock writes")


class LibraryDiscoveryTests(unittest.TestCase):
    """The zmol-v search order, on every host the CLI claims to run on.

    `ZMOLV_LIBRARY` must win over everything; the platform's own library
    search (`ctypes.util.find_library`, which names `.dylib`/`.dll` correctly
    per host) comes next; the Linux directories stay as the last leg for a
    freshly installed library the linker cache has not picked up yet.
    """

    def test_an_explicit_override_outranks_every_discovery_route(self) -> None:
        with (
            mock.patch.dict("os.environ", {"ZMOLV_LIBRARY": "/opt/zmolv/libzmolv.so"}),
            mock.patch.object(ctypes.util, "find_library", return_value=None),
        ):
            candidates = shader_blob._library_candidates()
        self.assertEqual(candidates[0], Path("/opt/zmolv/libzmolv.so"))

    def test_the_platform_library_search_is_consulted(self) -> None:
        with (
            mock.patch.dict("os.environ", {"ZMOLV_LIBRARY": ""}),
            mock.patch.object(ctypes.util, "find_library", return_value="/usr/lib/libzmolv.dylib"),
        ):
            candidates = shader_blob._library_candidates()
        self.assertIn(Path("/usr/lib/libzmolv.dylib"), candidates)
        self.assertEqual(candidates.index(Path("/usr/lib/libzmolv.dylib")), 0)

    def test_the_checkout_local_lib_is_searched_before_the_system_directories(self) -> None:
        """`scripts/install-tools.sh` builds zmol-v into the checkout's own
        gitignored .local/lib, so that path must be a default - the /tmp build
        it replaces evaporated on reboot and silently dropped the Vulkan lane."""
        with (
            mock.patch.dict("os.environ", {"ZMOLV_LIBRARY": ""}),
            mock.patch.object(ctypes.util, "find_library", return_value=None),
        ):
            candidates = shader_blob._library_candidates()
        checkout = Path(shader_blob.__file__).resolve().parents[2]
        native = shader_blob._shared_library_filenames()[0]
        self.assertEqual(candidates[0], checkout / ".local" / "lib" / native)

    def test_the_system_directories_include_this_host_library_name(self) -> None:
        with (
            mock.patch.dict("os.environ", {"ZMOLV_LIBRARY": ""}),
            mock.patch.object(ctypes.util, "find_library", return_value=None),
        ):
            candidates = shader_blob._library_candidates()
        native = shader_blob._shared_library_filenames()[0]
        checkout = Path(shader_blob.__file__).resolve().parents[2] / ".local" / "lib" / native
        system = Path("/usr/local/lib") / native
        self.assertIn(system, candidates)
        self.assertIn(Path("/usr/lib") / native, candidates)
        self.assertLess(candidates.index(checkout), candidates.index(system))
        self.assertNotIn(None, candidates)

    def test_every_host_library_name_is_a_candidate(self) -> None:
        """A copied .dylib or .dll must not be invisible on a Linux authoring host."""
        with (
            mock.patch.dict("os.environ", {"ZMOLV_LIBRARY": ""}),
            mock.patch.object(ctypes.util, "find_library", return_value=None),
        ):
            candidates = shader_blob._library_candidates()
        names = {path.name for path in candidates}
        self.assertIn("libzmolv.so", names)
        self.assertIn("libzmolv.dylib", names)
        self.assertTrue({"zmolv.dll", "libzmolv.dll"} & names)


class DescriptorSetTests(unittest.TestCase):
    """Unity binds constant buffers in descriptor set 1, not set 0.

    A translator such as `vkd3d-compiler` puts every resource in set 0. Unity's
    own Vulkan modules, decoded from a shipped bundle, put a texture in set 0
    and a constant buffer in **set 1** - so a module that follows the
    translator's convention collides with the set Unity reserves for resources,
    and the runtime refuses it. It refuses it silently: the shader loads, no log
    line says anything, and the prop draws in the magenta error shader.

    `spirv-val` passes on the module either way, which is why this needed a live
    client on `-force-vulkan` to find at all.
    """

    def _spirv(self, hlsl: str, profile: str) -> bytes:
        if not has_capability("vkd3d-compiler"):
            self.skipTest("vkd3d-compiler that reads HLSL is not installed")
        return shader_blob.compile_spirv(shader_blob.compile_hlsl(hlsl, profile))

    @staticmethod
    def _descriptor_sets(spirv: bytes) -> dict[int, int]:
        """`{id: descriptor set}` for every decorated variable."""
        words = struct.unpack(f"<{len(spirv) // 4}I", spirv)
        sets: dict[int, int] = {}
        index = 5
        while index < len(words):
            length, opcode = words[index] >> 16, words[index] & 0xFFFF
            if length < 1:
                break
            if opcode == 71 and length >= 4 and words[index + 2] == 34:
                sets[words[index + 1]] = words[index + 3]
            index += length
        return sets

    def test_constant_buffers_move_to_set_one(self) -> None:
        spirv = self._spirv(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        before = set(self._descriptor_sets(spirv).values())
        after = set(self._descriptor_sets(shader_blob.unity_descriptor_sets(spirv)).values())
        self.assertEqual(before, {0}, "vkd3d puts everything in set 0")
        self.assertEqual(
            after,
            {shader_blob.UNITY_SET_CONSTANT_BUFFERS},
            "the vertex program's only resources are constant buffers",
        )

    def test_textures_and_samplers_stay_in_set_zero(self) -> None:
        spirv = self._spirv(shader_blob.UNLIT_FRAGMENT_HLSL, "ps_4_0")
        after = set(self._descriptor_sets(shader_blob.unity_descriptor_sets(spirv)).values())
        self.assertEqual(
            after,
            {shader_blob.UNITY_SET_RESOURCES},
            "a texture and its sampler belong to the set Unity reserves for resources",
        )

    def test_the_rewrite_changes_nothing_but_the_set(self) -> None:
        spirv = self._spirv(shader_blob.UNLIT_VERTEX_HLSL, "vs_4_0")
        rewritten = shader_blob.unity_descriptor_sets(spirv)
        self.assertEqual(len(rewritten), len(spirv), "the module keeps its length")
        self.assertEqual(rewritten[:20], spirv[:20], "the SPIR-V header is untouched")
        differing = sum(1 for a, b in zip(spirv, rewritten, strict=True) if a != b)
        self.assertLessEqual(
            differing, 8, "only the descriptor-set literals should differ, one byte each"
        )


if __name__ == "__main__":
    unittest.main()
