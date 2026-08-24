"""Compiled-shader blobs for the editorless bundle writer.

The container this module writes is documented in
`hordeforge/7dtd-engine-research`, `docs/shader-subprogram-blob.md`: the
per-platform LZ4 blob, the 12-byte record table, the code-blob record, the
38-byte DX11 program-data header, and the parameter blob. Every structural
claim here was measured there against the stock install, and that page's
`tools/shader_blob_dump.py` re-checks it in one command. This module is the
writer for the format that page specifies; it does not restate the evidence.

The bytecode itself comes from `vkd3d-compiler` (WineHQ, LGPL), which emits
real `DXBC` shader model 4 - exactly the `DX11VertexSM40` / `DX11PixelSM40`
sub-programs the game carries. No Unity is involved in producing it.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PipelineError

BLOB_VERSION = 202012090
"""Unity's `LoadGpuProgramFromData` tag for 2021.2 and up."""

DX11_VERTEX_SM40 = 15
DX11_PIXEL_SM40 = 17
GL_CORE_32 = 6
"""`kShaderGpuProgramGLCore32`. An OpenGLCore sub-program's code is GLSL
source text, not bytecode: no program-data header, no compiler involved."""

SHADER_COMPILER_PLATFORM_D3D11 = 4
SHADER_COMPILER_PLATFORM_GL_CORE = 15

PROGRAM_DATA_HEADER = 38
"""6-byte base header plus the 0x20 block a header version of 2 adds."""

# D3D10/11 declaration opcodes, from d3d10TokenizedProgramFormat.
_OP_CUSTOMDATA = 53
_OP_DCL_RESOURCE = 88
_OP_DCL_CONSTANT_BUFFER = 89
_OP_DCL_SAMPLER = 90
_OP_DCL_TEMPS = 104
_OP_DCL_RESOURCE_RAW = 161
_OP_DCL_RESOURCE_STRUCTURED = 162
_SRV_OPCODES = (_OP_DCL_RESOURCE, _OP_DCL_RESOURCE_RAW, _OP_DCL_RESOURCE_STRUCTURED)


class _Writer:
    """Little-endian writer with Unity's 4-byte string padding."""

    def __init__(self) -> None:
        self.out = bytearray()

    def i32(self, value: int) -> None:
        self.out += struct.pack("<i", value)

    def u32(self, value: int) -> None:
        self.out += struct.pack("<I", value)

    def string(self, value: str) -> None:
        raw = value.encode("utf-8")
        self.i32(len(raw))
        self.out += raw
        while len(self.out) % 4:
            self.out += b"\x00"


@dataclass(frozen=True)
class CBufferMember:
    """One member of a constant buffer, at a byte offset Unity chooses."""

    name: str
    index: int
    rows: int = 1
    columns: int = 4
    is_matrix: bool = False
    array_size: int = 0
    param_type: int = 0


@dataclass(frozen=True)
class CBuffer:
    name: str
    used_size: int
    members: tuple[CBufferMember, ...] = ()


# Unity's own constant buffers, at the exact layout measured across 3403 stock
# parameter blobs (engine-research docs/shader-subprogram-blob.md). These
# offsets are the engine's, not this project's: getting one wrong renders the
# mesh at the wrong place rather than failing, so none of them is invented.
UNITY_PER_DRAW = CBuffer(
    "UnityPerDraw",
    176,
    (
        CBufferMember("unity_ObjectToWorld", 0, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_WorldToObject", 64, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_LODFade", 128),
        CBufferMember("unity_WorldTransformParams", 144),
    ),
)
UNITY_PER_FRAME = CBuffer(
    "UnityPerFrame",
    368,
    (
        CBufferMember("glstate_lightmodel_ambient", 0),
        CBufferMember("glstate_matrix_projection", 80, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_MatrixV", 144, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_MatrixInvV", 208, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_MatrixVP", 272, rows=4, columns=4, is_matrix=True),
    ),
)

# The HLSL below declares the full buffers so the register offsets vkd3d
# assigns line up with the offsets Unity fills, member for member. Trailing
# members this shader never reads still have to occupy their bytes.
_UNITY_CBUFFERS_HLSL = """
cbuffer UnityPerDraw : register(b0)
{
    float4x4 unity_ObjectToWorld;
    float4x4 unity_WorldToObject;
    float4 unity_LODFade;
    float4 unity_WorldTransformParams;
    float4 unity_RenderingLayer;
};

cbuffer UnityPerFrame : register(b1)
{
    float4 glstate_lightmodel_ambient;
    float4x4 glstate_matrix_projection;
    float4x4 unity_MatrixV;
    float4x4 unity_MatrixInvV;
    float4x4 unity_MatrixVP;
    float4 unity_StereoEyeIndex;
};
"""

UNLIT_VERTEX_HLSL = _UNITY_CBUFFERS_HLSL + """
struct VertexIn
{
    float4 vertex : POSITION;
    float2 uv : TEXCOORD0;
};

struct VertexOut
{
    float4 position : SV_POSITION;
    float2 uv : TEXCOORD0;
};

VertexOut main(VertexIn input)
{
    VertexOut output;
    float4 world = mul(unity_ObjectToWorld, input.vertex);
    output.position = mul(unity_MatrixVP, world);
    output.uv = input.uv;
    return output;
}
"""

UNLIT_FRAGMENT_HLSL = """
Texture2D<float4> _MainTex : register(t0);
SamplerState sampler_MainTex : register(s0);

struct PixelIn
{
    float4 position : SV_POSITION;
    float2 uv : TEXCOORD0;
};

float4 main(PixelIn input) : SV_Target
{
    return _MainTex.Sample(sampler_MainTex, input.uv);
}
"""


# Unity's OpenGLCore convention, read out of the stock
# `Legacy Shaders/Transparent/Cutout/VertexLit` GL blob: one source carrying
# both stages behind `#ifdef VERTEX` / `#ifdef FRAGMENT`, matrices flattened
# to four `vec4` rows under an `hlslcc_mtx4x4` prefix, attributes named
# `in_SEMANTIC0` and varyings `vs_SEMANTIC0`.
UNLIT_GLSL = """
#ifdef VERTEX
#version 150
#extension GL_ARB_explicit_attrib_location : require

uniform vec4 hlslcc_mtx4x4unity_ObjectToWorld[4];
uniform vec4 hlslcc_mtx4x4unity_MatrixVP[4];

in vec3 in_POSITION0;
in vec2 in_TEXCOORD0;
out vec2 vs_TEXCOORD0;

void main()
{
    vec4 world = hlslcc_mtx4x4unity_ObjectToWorld[0] * in_POSITION0.x
               + hlslcc_mtx4x4unity_ObjectToWorld[1] * in_POSITION0.y
               + hlslcc_mtx4x4unity_ObjectToWorld[2] * in_POSITION0.z
               + hlslcc_mtx4x4unity_ObjectToWorld[3];
    gl_Position = hlslcc_mtx4x4unity_MatrixVP[0] * world.x
                + hlslcc_mtx4x4unity_MatrixVP[1] * world.y
                + hlslcc_mtx4x4unity_MatrixVP[2] * world.z
                + hlslcc_mtx4x4unity_MatrixVP[3] * world.w;
    vs_TEXCOORD0 = in_TEXCOORD0;
}
#endif
#ifdef FRAGMENT
#version 150

uniform sampler2D _MainTex;

in vec2 vs_TEXCOORD0;
layout(location = 0) out vec4 SV_Target0;

void main()
{
    SV_Target0 = texture(_MainTex, vs_TEXCOORD0);
}
#endif
"""


def source_blob(program_type: int, source: str) -> bytes:
    """A code-blob record whose program data is source text, not bytecode.

    OpenGLCore sub-programs carry GLSL directly, with no program-data header -
    the 38-byte DX11 header is a d3d11 thing.
    """
    writer = _Writer()
    writer.i32(BLOB_VERSION)
    writer.i32(program_type)
    for _ in range(4):
        writer.i32(0)
    writer.i32(0)
    payload = source.encode("utf-8")
    writer.i32(len(payload))
    writer.out += payload
    while len(writer.out) % 4:
        writer.out += b"\x00"
    return bytes(writer.out)


def compile_hlsl(source: str, profile: str) -> bytes:
    """Compile one HLSL entry point to a DXBC container with `vkd3d-compiler`.

    `dxbc-tpf` is vkd3d's shader-model-4 target and its default for HLSL,
    which is the bytecode `DX11VertexSM40` and `DX11PixelSM40` carry.
    """
    binary = shutil.which("vkd3d-compiler")
    if binary is None:
        raise PipelineError(
            "vkd3d-compiler is not installed; it compiles the HLSL this writer "
            "turns into a shader's DXBC bytecode. Install it with "
            "'shamway script install-tools --with-authoring', or declare "
            "bundle_source other than \"synthesized\" for a bundle with a shader."
        )
    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / "shader.hlsl"
        out = Path(work) / "shader.dxbc"
        src.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [binary, "-x", "hlsl", "-b", "dxbc-tpf", "-p", profile,
             "-e", "main", str(src), "-o", str(out)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0 or not out.exists():
            detail = (result.stderr or result.stdout).strip()
            raise PipelineError(f"vkd3d-compiler failed for profile {profile}: {detail}")
        data = out.read_bytes()
    if data[:4] != b"DXBC":
        raise PipelineError(
            f"vkd3d-compiler produced {len(data)} bytes that are not a DXBC "
            "container; this writer will not wrap bytes it cannot identify."
        )
    return data


def dxbc_chunks(data: bytes) -> dict[str, bytes]:
    """`{fourcc: payload}` for a DXBC container."""
    count = struct.unpack_from("<I", data, 0x1C)[0]
    chunks: dict[str, bytes] = {}
    for offset in struct.unpack_from(f"<{count}I", data, 0x20):
        size = struct.unpack_from("<I", data, offset + 4)[0]
        chunks[data[offset:offset + 4].decode("ascii", "replace")] = data[
            offset + 8:offset + 8 + size
        ]
    return chunks


def _walk_tokens(data: bytes):
    """Yield `(opcode, operand_word)` for each instruction in a DXBC container."""
    chunks = dxbc_chunks(data)
    code = chunks.get("SHDR") or chunks.get("SHEX")
    if code is None:
        raise PipelineError("DXBC container has no SHDR/SHEX chunk to walk")
    declared = struct.unpack_from("<I", code, 4)[0]
    words = struct.unpack_from(f"<{min(declared, len(code) // 4)}I", code, 0)
    index = 2
    while index < len(words):
        token = words[index]
        opcode = token & 0x7FF
        length = (token >> 24) & 0x7F
        if opcode == _OP_CUSTOMDATA:      # length is the following dword
            length = words[index + 1] if index + 1 < len(words) else 2
        if length == 0:
            raise PipelineError(
                f"cannot walk the shader token stream: zero-length token "
                f"{token:#x} (opcode {opcode}) at dword {index}"
            )
        yield opcode, (words[index + 1] if index + 1 < len(words) else 0)
        index += length


def temp_register_count(data: bytes) -> int:
    """The `dcl_temps` count a DXBC container declares.

    This is the fourth statistic word in a code blob, and it is not
    decorative: it was measured equal to `dcl_temps` on the stock
    `VertexLit` vertex and fragment programs (7 and 2). A blob that
    under-declares the registers its own bytecode uses is one the runtime
    refuses with "Failed to load GpuProgram from binary shader data".
    """
    for opcode, operand in _walk_tokens(data):
        if opcode == _OP_DCL_TEMPS:
            return operand
    return 0


def declaration_counts(data: bytes) -> tuple[int, int, int]:
    """`(srv, constant_buffer, sampler)` declared by a DXBC container.

    These are the three counts Unity's program-data header carries, and they
    are derived from the bytecode rather than from what the HLSL was meant to
    say — a header that disagrees with its own bytecode is a mis-bound
    sub-program, which renders wrong instead of failing.
    """
    srv = cbuffer = sampler = 0
    for opcode, _operand in _walk_tokens(data):
        if opcode in _SRV_OPCODES:
            srv += 1
        elif opcode == _OP_DCL_CONSTANT_BUFFER:
            cbuffer += 1
        elif opcode == _OP_DCL_SAMPLER:
            sampler += 1
    return srv, cbuffer, sampler


def program_data(dxbc: bytes, gs_input_primitive: int = 0) -> bytes:
    """Unity's 38-byte DX11 header followed by the DXBC container."""
    srv, cbuffer, sampler = declaration_counts(dxbc)
    for label, value in (("SRV", srv), ("constant buffer", cbuffer), ("sampler", sampler)):
        if not 0 <= value <= 255:
            raise PipelineError(f"{label} count {value} does not fit the one-byte header field")
    header = bytes([2, srv, cbuffer, sampler, 0, gs_input_primitive]) + b"\x00" * 32
    assert len(header) == PROGRAM_DATA_HEADER
    return header + dxbc


# Unity's vertex bind channels, measured over the stock `Entities/trees`
# d3d11 vertex programs by correlating each blob's trailing channel list
# against its own DXBC input signature. `source` is the mesh channel Unity
# reads; `target` is the shader input it feeds.
_BIND_CHANNELS = {
    ("POSITION", 0): (0, 0),
    ("NORMAL", 0): (1, 1),
    ("TANGENT", 0): (2, 2),
    ("COLOR", 0): (3, 4),
}
_TEXCOORD_SOURCE = 4
_TEXCOORD_TARGET = 5


def input_semantics(data: bytes) -> list[tuple[str, int]]:
    """`(semantic, index)` for each element of a DXBC input signature."""
    isgn = dxbc_chunks(data).get("ISGN")
    if isgn is None:
        return []
    count = struct.unpack_from("<I", isgn, 0)[0]
    out = []
    for i in range(count):
        name_offset, index = struct.unpack_from("<II", isgn, 8 + i * 24)
        end = isgn.index(b"\x00", name_offset)
        out.append((isgn[name_offset:end].decode("ascii"), index))
    return out


def bind_channels(data: bytes) -> bytes:
    """The `ParserBindChannels` block that closes a vertex code-blob record.

    Unity binds mesh data to shader inputs through this table, not through the
    DXBC signature - the signature says what the bytecode wants, this says
    where the engine gets it. A record without it is 32 bytes short of what
    the runtime reads, which is why omitting it produces "Failed to load
    GpuProgram from binary shader data" rather than a wrong-looking mesh.
    """
    channels = []
    for semantic, index in input_semantics(data):
        if semantic == "TEXCOORD":
            channels.append((_TEXCOORD_SOURCE + index, _TEXCOORD_TARGET + index))
        elif (semantic, index) in _BIND_CHANNELS:
            channels.append(_BIND_CHANNELS[(semantic, index)])
        # Anything else (SV_InstanceID and friends) is generated, not bound.
    source_map = 0
    for source, _target in channels:
        source_map |= 1 << source
    writer = _Writer()
    writer.i32(source_map)
    writer.i32(len(channels))
    for source, target in channels:
        writer.i32(source)
        writer.i32(target)
    return bytes(writer.out)


def code_blob(program_type: int, dxbc: bytes, bind_inputs: bool = True) -> bytes:
    """One code-blob record: the sub-program header, then the program data.

    The first three statistic words (ALU, texture and flow instruction counts)
    are what Unity's own tooling reports and are written as zero: this writer
    has no compiler statistics, and a fabricated instruction count is a claim
    about bytecode it did not analyse. The fourth is **not** a statistic - it
    is the temp-register count, and it is read back out of the bytecode.
    """
    writer = _Writer()
    writer.i32(BLOB_VERSION)
    writer.i32(program_type)
    for _ in range(3):                    # ALU, TEX, flow instruction counts
        writer.i32(0)
    writer.i32(temp_register_count(dxbc))
    writer.i32(0)                         # keyword count: this writer emits no variants
    payload = program_data(dxbc)
    writer.i32(len(payload))
    writer.out += payload
    while len(writer.out) % 4:
        writer.out += b"\x00"
    # A pixel program takes its inputs from the vertex program's outputs, so
    # its channel table is empty - but the eight bytes are still written, as
    # every stock pixel record does.
    writer.out += bind_channels(dxbc) if bind_inputs else struct.pack("<ii", 0, 0)
    return bytes(writer.out)


@dataclass(frozen=True)
class TextureEntry:
    name: str
    index: int
    sampler_index: int
    dimension: int = 2                     # Tex2D
    multi_sampled: bool = False


@dataclass(frozen=True)
class CBufferBinding:
    name: str
    index: int
    array_size: int = 1


@dataclass(frozen=True)
class SamplerEntry:
    name: str
    bind_point: int
    sampler: int


@dataclass(frozen=True)
class ParameterBlob:
    """The binding table Unity keeps instead of the stripped DXBC `RDEF`."""

    buffers: tuple[CBuffer, ...] = ()
    textures: tuple[TextureEntry, ...] = ()
    bindings: tuple[CBufferBinding, ...] = ()
    samplers: tuple[SamplerEntry, ...] = ()

    def to_bytes(self) -> bytes:
        writer = _Writer()
        writer.i32(BLOB_VERSION)
        # Stock blobs always open with a nameless, zero-size buffer: it is the
        # "base" constant buffer, and every one of the 3403 measured records
        # has it.
        buffers = (CBuffer("", 0),) + self.buffers
        writer.i32(len(buffers))
        for buffer in buffers:
            writer.string(buffer.name)
            writer.i32(buffer.used_size)
            writer.i32(len(buffer.members))
            for member in buffer.members:
                writer.string(member.name)
                writer.i32(member.param_type)
                writer.i32(member.rows)
                writer.i32(member.columns)
                writer.i32(1 if member.is_matrix else 0)
                writer.i32(member.array_size)
                writer.i32(member.index)
            writer.i32(0)                  # struct params: none
        entries = len(self.textures) + len(self.bindings) + len(self.samplers)
        writer.i32(entries)
        for texture in self.textures:
            writer.string(texture.name)
            writer.i32(0)
            writer.i32(texture.index)
            writer.i32(texture.sampler_index)
            writer.u32((texture.dimension << 1) | (1 if texture.multi_sampled else 0))
        for binding in self.bindings:
            writer.string(binding.name)
            writer.i32(1)
            writer.i32(binding.index)
            writer.i32(binding.array_size)
        for sampler in self.samplers:
            writer.string(sampler.name)
            writer.i32(4)
            writer.i32(sampler.bind_point)
            writer.u32(sampler.sampler)
        return bytes(writer.out)


def assemble_blob(records: list[bytes]) -> bytes:
    """The record table followed by its payload, tiled contiguously."""
    offset = 4 + len(records) * 12
    table = _Writer()
    table.u32(len(records))
    payload = bytearray()
    for record in records:
        table.u32(offset + len(payload))
        table.u32(len(record))
        table.u32(0)                       # segment: 0 in every stock record
        payload += record
    return bytes(table.out) + bytes(payload)


def compress_lz4(data: bytes) -> bytes:
    """LZ4 block compression, the codec every stock platform blob uses."""
    try:
        import lz4.block
    except ImportError as exc:            # pragma: no cover - capability gated
        raise PipelineError(
            "the lz4 module is required to compress a shader blob; it ships "
            "with the UnityPy extra."
        ) from exc
    return bytes(lz4.block.compress(data, mode="high_compression", store_size=False))


@dataclass(frozen=True)
class PlatformBlob:
    """One `ShaderCompilerPlatform`'s blob and the indices addressing it."""

    platform: int
    blob: bytes
    decompressed_size: int
    vertex_program_type: int
    fragment_program_type: int
    vertex_parameter_index: int
    fragment_parameter_index: int
    vertex_blob_index: int
    fragment_blob_index: int
    stage_count: int
    """`stageCounts` for this platform.

    Measured as a per-platform constant across all ten stock `Entities/trees`
    shaders, independent of tier count: d3d11 is 2 (vertex and fragment are
    separate programs), OpenGLCore and Vulkan are 1 (one source carries both
    stages behind `#ifdef VERTEX` / `#ifdef FRAGMENT`).
    """


@dataclass
class CompiledShader:
    """A finished single-pass shader across one or more platforms."""

    platforms: tuple[PlatformBlob, ...]
    texture_name: str
    dxbc: dict[str, bytes] = field(default_factory=dict)

    @property
    def compressed_blob(self) -> bytes:
        """Every platform blob concatenated, which is what `compressedBlob` is."""
        return b"".join(p.blob for p in self.platforms)

    @property
    def offsets(self) -> list[list[int]]:
        out, cursor = [], 0
        for platform in self.platforms:
            out.append([cursor])
            cursor += len(platform.blob)
        return out


def unlit_textured(texture_property: str = "_MainTex") -> CompiledShader:
    """Compile the one-pass unlit textured shader this writer ships.

    Vertex: object space through `unity_ObjectToWorld` then `unity_MatrixVP`.
    Fragment: a single `Texture2D` sample. No keywords, no variants, one
    hardware tier, d3d11 only.
    """
    fragment_source = UNLIT_FRAGMENT_HLSL
    if texture_property != "_MainTex":
        fragment_source = fragment_source.replace("_MainTex", texture_property)
    vertex_dxbc = compile_hlsl(UNLIT_VERTEX_HLSL, "vs_4_0")
    fragment_dxbc = compile_hlsl(fragment_source, "ps_4_0")

    vertex_parameters = ParameterBlob(
        buffers=(UNITY_PER_DRAW, UNITY_PER_FRAME),
        bindings=(CBufferBinding("UnityPerDraw", 0), CBufferBinding("UnityPerFrame", 1)),
    )
    fragment_parameters = ParameterBlob(
        textures=(TextureEntry(texture_property, index=0, sampler_index=0),),
        samplers=(SamplerEntry(f"sampler{texture_property}", bind_point=0, sampler=0),),
    )
    d3d11_raw = assemble_blob([
        vertex_parameters.to_bytes(),
        fragment_parameters.to_bytes(),
        code_blob(DX11_VERTEX_SM40, vertex_dxbc),
        code_blob(DX11_PIXEL_SM40, fragment_dxbc, bind_inputs=False),
    ])
    # The OpenGLCore variant exists so a Linux editor can actually load a
    # sub-program: a d3d11-only shader has nothing that host can create, and
    # `shamway verify-bundle` then reports it unsupported for a reason that
    # says nothing about the bundle. The game runs d3d11 under Proton.
    glsl = UNLIT_GLSL if texture_property == "_MainTex" else UNLIT_GLSL.replace(
        "_MainTex", texture_property
    )
    gl_raw = assemble_blob([
        vertex_parameters.to_bytes(),
        fragment_parameters.to_bytes(),
        source_blob(GL_CORE_32, glsl),
        source_blob(GL_CORE_32, glsl),
    ])
    return CompiledShader(
        platforms=(
            PlatformBlob(
                SHADER_COMPILER_PLATFORM_D3D11, compress_lz4(d3d11_raw), len(d3d11_raw),
                DX11_VERTEX_SM40, DX11_PIXEL_SM40, 0, 1, 2, 3, stage_count=2,
            ),
            PlatformBlob(
                SHADER_COMPILER_PLATFORM_GL_CORE, compress_lz4(gl_raw), len(gl_raw),
                GL_CORE_32, GL_CORE_32, 0, 1, 2, 3, stage_count=1,
            ),
        ),
        texture_name=texture_property,
        dxbc={"vertex": vertex_dxbc, "fragment": fragment_dxbc},
    )
