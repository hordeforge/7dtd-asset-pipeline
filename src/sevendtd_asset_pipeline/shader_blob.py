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

import ctypes
import ctypes.util
import functools
import os
import shutil
import struct
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PipelineError
from .workdir import scratch_dir

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
        CBufferMember("unity_AmbientSky", 16),
        CBufferMember("unity_AmbientEquator", 32),
        CBufferMember("unity_AmbientGround", 48),
        CBufferMember("unity_IndirectSpecColor", 64),
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
    // Unity's own UnityPerFrame carries four ambient float4s here. This shader
    // reads none of them, and they still have to occupy their 64 bytes: the
    // runtime fills the buffer to *its* layout, and the bytecode reads it by
    // offset. Omitting them packed everything after this point 64 bytes early,
    // so `unity_MatrixVP` compiled to offset 208 while Unity writes it at 272 -
    // the shader sampled the tail of `unity_MatrixInvV` as its view-projection
    // matrix, put the geometry nowhere, and drew nothing. No error, on d3d11
    // only: GLSL binds uniforms by name, so OpenGL Core was immune and the
    // same bundle rendered there. `assert_cbuffer_layout` now refuses this.
    float4 unity_AmbientSky;
    float4 unity_AmbientEquator;
    float4 unity_AmbientGround;
    float4 unity_IndirectSpecColor;
    float4x4 glstate_matrix_projection;
    float4x4 unity_MatrixV;
    float4x4 unity_MatrixInvV;
    float4x4 unity_MatrixVP;
    float4 unity_StereoEyeIndex;
};
"""

UNLIT_VERTEX_HLSL = (
    _UNITY_CBUFFERS_HLSL
    + """
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
)

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
// Required, not decoration: `layout(location = ...)` is not in GLSL 150, and
// without this line the fragment half fails to compile with
// "'location' : not supported for this version or the enabled extensions".
// The runtime reports none of that - it says "Failed to load GpuProgram from
// binary shader data", the shader is unsupported, and a prop using it draws
// nothing. Stock GLCore fragment programs carry the same line.
#extension GL_ARB_explicit_attrib_location : require

uniform sampler2D _MainTex;

in vec2 vs_TEXCOORD0;
layout(location = 0) out vec4 SV_Target0;

void main()
{
    SV_Target0 = texture(_MainTex, vs_TEXCOORD0);
}
#endif
"""


# Unity's `VertexAttribute` enum, as the trailing mask of a GLCore code record
# indexes it. Derived on 2026-08-24 from two stock records in
# `Legacy Shaders/Transparent/Cutout/VertexLit`: one declaring
# POSITION+NORMAL+TEXCOORD0 with mask 19 (bits 0,1,4) and one declaring
# POSITION+COLOR+TEXCOORD0+TEXCOORD1 with mask 57 (bits 0,3,4,5). The two share
# exactly POSITION and TEXCOORD0, and exactly bits 0 and 4.
VERTEX_ATTRIBUTE_POSITION = 0
VERTEX_ATTRIBUTE_NORMAL = 1
VERTEX_ATTRIBUTE_TANGENT = 2
VERTEX_ATTRIBUTE_COLOR = 3
VERTEX_ATTRIBUTE_TEXCOORD0 = 4
VERTEX_ATTRIBUTE_TEXCOORD1 = 5

# What `UNLIT_GLSL` declares: `in vec3 in_POSITION0` and `in vec2 in_TEXCOORD0`.
UNLIT_VERTEX_ATTRIBUTES = (1 << VERTEX_ATTRIBUTE_POSITION) | (1 << VERTEX_ATTRIBUTE_TEXCOORD0)


def source_blob(program_type: int, source: str, vertex_attributes: int = 0) -> bytes:
    """A code-blob record whose program data is source text, not bytecode.

    OpenGLCore sub-programs carry GLSL directly, with no program-data header -
    the 38-byte DX11 header is a d3d11 thing.

    The record does not end at the source. Every one of the twelve type-6
    records in a stock GLCore shader carries **two further u32 words** after the
    padded source: the vertex-attribute mask above, and a zero. This writer
    omitted both until 2026-08-24, so the runtime read a record eight bytes
    shorter than the format it was decoding and answered `Failed to load
    GpuProgram from binary shader data` - with no mention of a length.
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
    writer.i32(vertex_attributes)
    writer.i32(0)
    return bytes(writer.out)


# A compiler that never answers must not hold its caller forever: build and
# pack are published operations reachable through `shamway serve`, where one
# wedged vkd3d-compiler would block the whole session past any consumer's
# patience. Compiling one short HLSL file is sub-second work, so this bounds a
# hung tool rather than a slow one.
SHADER_COMPILE_TIMEOUT = 60


def _compile(argv: list[str], tool: str, what: str) -> subprocess.CompletedProcess[str]:
    """Run one shader compiler bounded by `SHADER_COMPILE_TIMEOUT`.

    `subprocess.run` kills the child when the bound fires; the timeout reaches
    the caller as a named error instead of an eternal wait.
    """
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=SHADER_COMPILE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipelineError(
            f"{tool} did not finish {what} within {SHADER_COMPILE_TIMEOUT}s and was killed"
        ) from exc


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
            'bundle_source other than "synthesized" for a bundle with a shader.'
        )
    with scratch_dir("shader-dxbc-") as work:
        src = work / "shader.hlsl"
        out = work / "shader.dxbc"
        src.write_text(source, encoding="utf-8")
        result = _compile(
            [
                binary,
                "-x",
                "hlsl",
                "-b",
                "dxbc-tpf",
                "-p",
                profile,
                "-e",
                "main",
                str(src),
                "-o",
                str(out),
            ],
            "vkd3d-compiler",
            f"compiling the {profile} stage",
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


SPIRV_MAGIC = 0x07230203
SMOLV_MAGIC = 0x534D4F4C
# `ShaderCompilerPlatform.Vulkan`, and the program type its code records use.
SHADER_COMPILER_PLATFORM_VULKAN = 18
VULKAN_PROGRAM = 25
# Every stock Vulkan record puts section A's payload 176 bytes in.
VULKAN_SECTION_HEADER = 176


def compile_spirv(dxbc: bytes) -> bytes:
    """Translate a DXBC container to SPIR-V with `vkd3d-compiler`.

    The same translation DXVK performs at runtime, which is why this needs no
    second compiler: the HLSL is already compiled, and Vulkan wants the same
    program in SPIR-V rather than a differently-authored one.
    """
    binary = shutil.which("vkd3d-compiler")
    if binary is None:
        raise PipelineError(
            "vkd3d-compiler is not installed; it translates this writer's DXBC "
            "into the SPIR-V a Vulkan sub-program carries. Install it with "
            "'shamway script install-tools'."
        )
    with scratch_dir("shader-spv-") as work:
        src = work / "shader.dxbc"
        out = work / "shader.spv"
        src.write_bytes(dxbc)
        result = _compile(
            [binary, "-x", "dxbc-tpf", "-b", "spirv-binary", str(src), "-o", str(out)],
            "vkd3d-compiler",
            "translating the DXBC to SPIR-V",
        )
        if result.returncode != 0 or not out.exists():
            detail = (result.stderr or result.stdout).strip()
            raise PipelineError(f"vkd3d-compiler could not produce SPIR-V: {detail}")
        data = out.read_bytes()
    if len(data) < 4 or struct.unpack_from("<I", data, 0)[0] != SPIRV_MAGIC:
        raise PipelineError(
            f"vkd3d-compiler produced {len(data)} bytes that are not a SPIR-V module"
        )
    return data


# Unity's Vulkan sub-programs do not use the d3d11 constant-buffer names. Their
# parameter records declare one buffer per stage - `VGlobals<hash>` for the
# vertex stage, `PGlobals<hash>` for the pixel stage - and the built-in
# constants live inside those rather than in `UnityPerDraw`/`UnityPerFrame`.
# Decoded from `Legacy Shaders/Transparent/Cutout/VertexLit`, whose Vulkan
# records name `unity_ObjectToWorld`, `unity_MatrixVP` and the rest inside them.
VULKAN_VERTEX_GLOBALS = "VGlobals"
VULKAN_PIXEL_GLOBALS = "PGlobals"

# One buffer, this writer's own layout, because Unity fills a per-shader globals
# buffer at the offsets the parameter record declares - unlike `UnityPerFrame`,
# whose layout is the runtime's and which this writer had to match byte for byte.
VULKAN_VERTEX_CBUFFER = CBuffer(
    VULKAN_VERTEX_GLOBALS,
    128,
    (
        CBufferMember("unity_ObjectToWorld", 0, rows=4, columns=4, is_matrix=True),
        CBufferMember("unity_MatrixVP", 64, rows=4, columns=4, is_matrix=True),
    ),
)

# The Vulkan vertex stage reads one buffer, so it declares one. `register(b0)`
# rather than the d3d11 pair, and glslang maps it to a single uniform block.
UNLIT_VERTEX_HLSL_VULKAN = """
cbuffer VGlobals : register(b0)
{
    float4x4 unity_ObjectToWorld;
    float4x4 unity_MatrixVP;
};

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
    // Vulkan's clip space points Y down where d3d11's points up, and Unity
    // compensates in the shader rather than with a negative viewport: without
    // this flip the live draw is mirrored vertically - the block's albedo
    // upside down, its top face swapped, the mirror pivot moving with the
    // camera. Measured by A/B on a live Vulkan client (GFX_API=vulkan),
    // d3d11 as the unflipped control.
    output.position.y = -output.position.y;
    output.uv = input.uv;
    return output;
}
"""

# The Vulkan fragment half is **GLSL, not HLSL**, and that is deliberate: Unity's
# own Vulkan modules are compiled by glslang from the GLSL its HLSLCC emits, so
# a `uniform sampler2D` becomes one combined image-sampler variable. The HLSL
# form (`Texture2D` + `SamplerState`) makes glslang emit two variables on the
# same binding - an image and a sampler - a shape **no stock module has** (all
# six measured stock fragment modules are a single `OpTypeSampledImage` at
# descriptor set 0, binding 0). GLSL 450 with explicit locations reproduces the
# stock shape exactly. Whether the split form was the live client's crash is
# not isolated: with the combined form in place the draw still dies on this
# host's AMD RADV, so the crash's cause is still open - this change removes a
# measured deviation from stock, not the whole blocker.
UNLIT_FRAGMENT_GLSL_VULKAN = """
#version 450
layout(location = 0) in vec2 vs_TEXCOORD0;
layout(location = 0) out vec4 SV_Target0;
layout(binding = 0) uniform sampler2D _MainTex;
void main()
{
    SV_Target0 = texture(_MainTex, vs_TEXCOORD0);
}
"""


def compile_spirv_glslang(source: str, stage: str, language: str = "hlsl") -> bytes:
    """Compile a shader straight to SPIR-V with `glslangValidator`.

    **Unity's own Vulkan modules are glslang output** - decoded from a shipped
    bundle, their generator is `Khronos Glslang Reference Front End` - so this
    reaches SPIR-V the same way Unity does rather than translating the d3d11
    bytecode. Translating with `vkd3d-compiler` also produces valid SPIR-V, and
    a live client refused it: that module declared a `gl_PointSize` output Unity
    never emits, carried no `GLSL.std.450` import, and had five times the id
    count for the same shader.

    The cost is that the d3d11 and Vulkan sub-programs no longer come from one
    compiler. They still come from **one HLSL source**, so the two can differ
    only in how a compiler renders the same program, not in what the program
    says. The Vulkan fragment half is the exception: Unity compiles its Vulkan
    modules from the GLSL its HLSLCC emits, and only GLSL yields the combined
    image-sampler every stock module carries - so that half is authored in GLSL
    and compiled with `language="glsl"`, which drops the HLSL `-D` flag.
    """
    binary = shutil.which("glslangValidator")
    if binary is None:
        raise PipelineError(
            "glslangValidator is not installed; it compiles this writer's HLSL to the "
            "SPIR-V a Vulkan sub-program carries. Install it with "
            "'shamway script install-tools'."
        )
    with scratch_dir("shader-glsl-") as work:
        src = work / f"shader.{stage}.{language}"
        out = work / "shader.spv"
        src.write_text(source, encoding="utf-8")
        command = [
            binary,
            "-D",  # the source is HLSL
            "-e",
            "main",
            "-S",
            stage,
            "--target-env",
            "vulkan1.0",
            str(src),
            "-o",
            str(out),
        ]
        if language != "hlsl":
            command.remove("-D")
        result = _compile(
            command,
            "glslangValidator",
            f"compiling the {stage} stage",
        )
        if result.returncode != 0 or not out.exists():
            detail = (result.stdout or result.stderr).strip()
            raise PipelineError(f"glslangValidator could not compile the {stage} stage: {detail}")
        data = out.read_bytes()
    if len(data) < 4 or struct.unpack_from("<I", data, 0)[0] != SPIRV_MAGIC:
        raise PipelineError(
            f"glslangValidator produced {len(data)} bytes that are not a SPIR-V module"
        )
    return data


def compress_smolv(spirv: bytes) -> bytes:
    """Compress a SPIR-V module to SMOL-V, which is what Unity stores.

    Unity does not put SPIR-V in a Vulkan sub-program; it puts SMOL-V, Aras
    Pranckevicius's compressed form of it. The encoder is **not** vendored
    here - a SPIR-V codec has nothing to do with this game, so it lives in
    https://github.com/ywy50/zmol-v and is loaded through its C ABI. See
    `docs/sibling-repos.md`, "Outside the organization".
    """
    library = smolv_library()
    if library is None:
        raise PipelineError(
            "libzmolv is not installed; it compresses the SPIR-V a Vulkan "
            "sub-program carries. Build it from https://github.com/ywy50/zmol-v "
            "with 'zig build' and point ZMOLV_LIBRARY at the shared library it "
            "writes, or leave the Vulkan platform out."
        )
    out_ptr = ctypes.POINTER(ctypes.c_ubyte)()
    out_len = ctypes.c_size_t()
    code = library.zmolv_encode(spirv, len(spirv), ctypes.byref(out_ptr), ctypes.byref(out_len))
    if code != 0:
        reason = {1: "not SPIR-V", 2: "malformed SPIR-V", 3: "out of memory"}.get(code, str(code))
        raise PipelineError(f"zmolv could not encode the SPIR-V module: {reason}")
    try:
        # string_at reads the encoder's buffer in one C-level copy; indexing
        # out_ptr per byte is a Python round trip per byte of module.
        encoded = ctypes.string_at(out_ptr, out_len.value)
    finally:
        library.zmolv_free(out_ptr, out_len)
    if struct.unpack_from("<I", encoded, 0)[0] != SMOLV_MAGIC:
        raise PipelineError("zmolv returned bytes that do not start with the SMOL-V magic")
    return encoded


def _library_candidates() -> list[Path]:
    """Where to look for the zmol-v shared library, most explicit first.

    `ZMOLV_LIBRARY` wins, then the platform's own library search
    (`ctypes.util.find_library`, which resolves `libzmolv.so`, `libzmolv.dylib`
    and `zmolv.dll` per host), then this checkout's own gitignored
    `.local/lib` — where `scripts/install-tools.sh` builds the pinned zmol-v —
    then the two directories a plain `zig build -p /usr/local` install lands
    in on Linux. The explicit legs are fallbacks rather than the only route
    because find_library reads the linker cache, which a freshly copied
    library is absent from. A session-local build under /tmp is deliberately
    not a candidate: it evaporates on reboot, and a default that sometimes
    exists is how the Vulkan lane silently degraded on 2026-08-25. The
    checkout leg resolves from this file (src layout), so it exists only when
    the pipeline runs from a checkout; a wheel install relies on the other
    legs.
    """
    candidates: list[Path] = []
    override = os.environ.get("ZMOLV_LIBRARY")
    if override:
        candidates.append(Path(override))
    found = ctypes.util.find_library("zmolv")
    if found:
        candidates.append(Path(found))
    checkout = Path(__file__).resolve().parents[2]
    candidates.append(checkout / ".local" / "lib" / "libzmolv.so")
    for directory in ("/usr/local/lib", "/usr/lib"):
        candidates.append(Path(directory) / "libzmolv.so")
    return candidates


@functools.lru_cache(maxsize=1)
def smolv_library() -> ctypes.CDLL | None:
    """The zmol-v shared library, or None when it is not installed."""
    for candidate in _library_candidates():
        if not candidate.is_file():
            continue
        try:
            library = ctypes.CDLL(str(candidate))
        except OSError:
            continue
        library.zmolv_encode.argtypes = [
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        library.zmolv_encode.restype = ctypes.c_int
        library.zmolv_free.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t]
        library.zmolv_free.restype = None
        return library
    return None


# SPIR-V storage classes, and Unity's descriptor-set convention for them.
STORAGE_CLASS_UNIFORM_CONSTANT = 0  # images and samplers
STORAGE_CLASS_UNIFORM = 2  # constant buffers
UNITY_SET_RESOURCES = 0
UNITY_SET_CONSTANT_BUFFERS = 1
_OP_DECORATE = 71
_OP_VARIABLE = 59
_DECORATION_DESCRIPTOR_SET = 34


def unity_descriptor_sets(spirv: bytes) -> bytes:
    """Move constant buffers to descriptor set 1, where Unity binds them.

    `vkd3d-compiler` puts every resource in descriptor set 0. Unity does not:
    decoded from its own Vulkan modules, a texture sits in **set 0** and a
    constant buffer in **set 1**, so a module out of vkd3d collides with the
    set Unity reserves for resources.

    ```text
    stock fragment  set 0 binding 0   texture
                    set 1 binding 0   constant buffer
    stock vertex    set 1 binding 1   constant buffer
    ours (before)   set 0 binding 0   constant buffer   <- collides
    ```

    The storage class is what distinguishes them and it is in the bytecode:
    `Uniform` is a constant buffer, `UniformConstant` an image or sampler. Only
    the set is rewritten; bindings are left alone.
    """
    words = list(struct.unpack(f"<{len(spirv) // 4}I", spirv))
    constant_buffers = set()
    index = 5
    while index < len(words):
        length, opcode = words[index] >> 16, words[index] & 0xFFFF
        if length < 1:
            raise PipelineError("SPIR-V instruction with zero length")
        if opcode == _OP_VARIABLE and length >= 4 and words[index + 3] == STORAGE_CLASS_UNIFORM:
            constant_buffers.add(words[index + 2])
        index += length

    index = 5
    while index < len(words):
        length, opcode = words[index] >> 16, words[index] & 0xFFFF
        if (
            opcode == _OP_DECORATE
            and length >= 4
            and words[index + 2] == _DECORATION_DESCRIPTOR_SET
            and words[index + 1] in constant_buffers
        ):
            words[index + 3] = UNITY_SET_CONSTANT_BUFFERS
        index += length
    return struct.pack(f"<{len(words)}I", *words)


# A Vulkan bind-channels target is the shader input's **slot in the program's
# vertex-input declaration**, offset by 13 - not the d3d11 vertex-component
# slot and not the SPIR-V `Location` decoration as stored in the module.
# Measured across seven stock 2022.3 shaders in the installed game
# (`7DaysToDie_Data/data.unity3d`, Vulkan platform blobs):
#
#   VertexLit / Diffuse / Specular (Position, Normal, TexCoord0)
#       (0,13) (1,14) (4,15)   - the module's SPIR-V locations are 0, 1, 2
#   Bumped Diffuse (Position, Normal, Tangent, TexCoord0)
#       (0,13) (1,14) (2,15) (4,16)   - SPIR-V locations 0, 1, 2, 3
#   Particles/Additive (Position, Color, TexCoord0)
#       (0,13) (3,14) (4,15)   - SPIR-V locations 0, 1, 2
#
# In every record the target is the declaration-index (equivalently the SPIR-V
# location Unity assigned, which follows declaration order) plus 13, so the
# runtime's pipeline puts the attribute at the offset slot the shader's input
# list occupies. Our glslang vertex module declares `input.vertex` at location
# 0 and `input.uv` at location 1, so the targets are 13 and 14. Reusing the
# d3d11 targets or the bare locations (0 and 1) points the mesh binding at a
# slot the pipeline does not bind, which hung a live client mid-draw.
# (mesh channel source, target slot). Mesh Position is channel 0, TexCoord0
# is channel 4 - the same source numbers the d3d11 bind table uses.
VULKAN_BIND_CHANNELS = (
    (0, 13),  # Position -> input declaration slot 0 + 13
    (4, 14),  # TexCoord0 -> input declaration slot 1 + 13
)


def vulkan_bind_channels() -> bytes:
    """The `ParserBindChannels` tail for the unlit Vulkan vertex program."""
    writer = _Writer()
    source_map = 0
    for source, _target in VULKAN_BIND_CHANNELS:
        source_map |= 1 << source
    writer.i32(source_map)
    writer.i32(len(VULKAN_BIND_CHANNELS))
    for source, target in VULKAN_BIND_CHANNELS:
        writer.i32(source)
        writer.i32(target)
    return bytes(writer.out)


def vulkan_shader_hash(fragment_smolv: bytes, vertex_smolv: bytes) -> bytes:
    """The 32 bytes at payload words 20..27 of a Vulkan code record, as zero.

    An earlier session read these bytes as a content hash and spent ~1.5M
    seed sweeps trying to reproduce the stored halves
    `c9dae3ee4501d8bee8b28c965c85e3f9` / `c6db081ec58e178a3377170abf47ac70`
    from the SMOL-V or decoded SPIR-V modules. They are not validated: a live
    client rendered a stock blob with every byte of the field corrupted, and
    renders a synthesized record whose bytes here do not match stock's at all
    (see research-provenance.md, "The Vulkan hash is not validated"). The
    content is irrelevant, so the writer emits zeros.

    Returns a 32-byte field of zeros.
    """
    return b"\x00" * 32


def vulkan_code_blob(fragment_smolv: bytes, vertex_smolv: bytes) -> bytes:
    """One Vulkan code record: two SMOL-V modules behind a 176-byte header.

    Decoded from shipped 2022.3 bundles; see `docs/research/research-provenance.md`,
    "The Vulkan sub-program record". A Vulkan record is program type 25 and,
    unlike d3d11 and GLCore, carries **both stages** - which is why Unity
    reports `stageCounts` of 1 for Vulkan and 2 for d3d11.

    The section order was read as fragment-then-vertex from `OpEntryPoint` of
    the decoded modules (a size argument only, in the first survey), and the
    32 bytes at payload words 20..27 are not validated (measured: a live
    client renders a corrupted stock blob and a synthesized record with
    non-stock bytes there - see `vulkan_shader_hash`). What the live Vulkan
    acceptance proves is the whole shape: this record plus the parameter
    record's stock-shaped binding entries draws the textured prop in a fresh
    client, where every earlier shape drew the magenta error shader or lost
    the device.
    """
    hash_bytes = vulkan_shader_hash(fragment_smolv, vertex_smolv)
    header = bytearray(VULKAN_SECTION_HEADER)
    section_a = VULKAN_SECTION_HEADER + len(fragment_smolv)
    struct.pack_into(
        "<6I",
        header,
        0,
        0x02000060,  # version and flags, as every measured stock record carries
        section_a,
        len(vertex_smolv),
        VULKAN_SECTION_HEADER,
        len(fragment_smolv),
        0,
    )
    struct.pack_into("<I", header, 19 * 4, 1)
    payload = bytes(header) + fragment_smolv + vertex_smolv

    writer = _Writer()
    writer.i32(BLOB_VERSION)
    writer.i32(VULKAN_PROGRAM)
    for _ in range(4):
        writer.i32(0)
    writer.i32(0)  # keyword count
    # Inject the computed hash at payload words 20..27 (bytes 80..112).
    # `vulkan_shader_hash` returns zeros today, so the splice is
    # content-neutral until the recipe is known.
    payload_with_hash = payload[:80] + hash_bytes + payload[112:]
    # The runtime reads the record's payload length and then the bind-channels
    # block, so the length must be a multiple of 4 - a SMOL-V pair that sums to
    # 882 bytes made the runtime read the bind block from mid-padding and fault
    # the Vulkan draw (AMD RADV, device lost, no log line). The stock records
    # all carry a 4-aligned payload length.
    payload_with_hash += b"\x00" * (-len(payload_with_hash) % 4)
    writer.i32(len(payload_with_hash))
    writer.out += payload_with_hash
    while len(writer.out) % 4:
        writer.out += b"\x00"
    # The record does not end at its payload. A stock Vulkan code record carries
    # the same `ParserBindChannels` block a d3d11 vertex record does - a source
    # mask, a count, and (mesh channel, shader input) pairs - and a record
    # without it is refused: the shader loads and the prop draws in the magenta
    # error shader, with no log line. Found on 2026-08-25 by byte-diffing our
    # record against a stock one carrying the same SMOL-V modules: they matched
    # exactly but for the (unvalidated) hash, and stock was 32 bytes longer -
    # this block. The channels come from the vertex DXBC the SPIR-V was compiled
    # from, so the Vulkan and d3d11 lanes bind the same mesh data.
    writer.out += vulkan_bind_channels()
    return bytes(writer.out)


def dxbc_chunks(data: bytes) -> dict[str, bytes]:
    """`{fourcc: payload}` for a DXBC container."""
    count = struct.unpack_from("<I", data, 0x1C)[0]
    chunks: dict[str, bytes] = {}
    for offset in struct.unpack_from(f"<{count}I", data, 0x20):
        size = struct.unpack_from("<I", data, offset + 4)[0]
        chunks[data[offset : offset + 4].decode("ascii", "replace")] = data[
            offset + 8 : offset + 8 + size
        ]
    return chunks


def _walk_tokens(data: bytes) -> Iterator[tuple[int, int]]:
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
        if opcode == _OP_CUSTOMDATA:  # length is the following dword
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
            return int(operand)
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


def compiled_cbuffer_layout(dxbc: bytes) -> dict[str, dict[str, int]]:
    """`{buffer: {member: byte offset}}` as the compiler actually packed it.

    Read from the DXBC's `RDEF` chunk, which is the bytecode's own account of
    where it will look - not what the HLSL author believed.
    """
    rdef = dxbc_chunks(dxbc).get("RDEF")
    if rdef is None:
        return {}

    def cstr(offset: int) -> str:
        return rdef[offset : rdef.index(b"\x00", offset)].decode("ascii", "replace")

    buffers: dict[str, dict[str, int]] = {}
    count, table = struct.unpack_from("<2I", rdef, 0)
    for i in range(count):
        name_at, members, member_table, _size, _flags, _kind = struct.unpack_from(
            "<6I", rdef, table + i * 24
        )
        fields: dict[str, int] = {}
        for m in range(members):
            member_at, offset, _size2, _f, _t, _d = struct.unpack_from(
                "<6I", rdef, member_table + m * 24
            )
            fields[cstr(member_at)] = offset
        buffers[cstr(name_at)] = fields
    return buffers


def assert_cbuffer_layout(dxbc: bytes, buffers: tuple[CBuffer, ...]) -> None:
    """Refuse bytecode that reads a constant buffer at different offsets than declared.

    The runtime fills a constant buffer to **its** layout and the bytecode reads
    it **by offset**, so the HLSL must reproduce Unity's member order byte for
    byte - padding members it never reads included. Get it wrong and there is no
    error anywhere: the shader loads, the pass sets up, and it samples the wrong
    bytes.

    This gate exists because that happened. `UnityPerFrame` omitted Unity's four
    ambient `float4`s, so everything after them packed 64 bytes early and
    `unity_MatrixVP` compiled to offset 208 while the runtime writes it at 272.
    The vertex shader read the tail of `unity_MatrixInvV` as its view-projection
    matrix and put every vertex nowhere. **Only on d3d11**: GLSL binds uniforms
    by name, so the OpenGL Core sub-program out of the same writer rendered
    correctly, and a live client showed an invisible block on its default API
    and a correct one under `-force-glcore`.

    An offline check that reads the bytecode's own `RDEF` is the cheapest place
    to catch it; the alternative is a human looking at a block on two graphics
    APIs.
    """
    compiled = compiled_cbuffer_layout(dxbc)
    for buffer in buffers:
        packed = compiled.get(buffer.name)
        if packed is None:
            continue  # the shader does not reference this buffer at all
        for member in buffer.members:
            actual = packed.get(member.name)
            if actual is None:
                continue
            if actual != member.index:
                raise PipelineError(
                    f"{buffer.name}.{member.name} is declared at byte {member.index} but the "
                    f"compiled bytecode reads it at {actual}. The runtime fills this buffer to "
                    "its own layout, so the shader would read the wrong bytes and draw nothing, "
                    "with no error and only on d3d11. Add the members Unity has between them, "
                    "even ones this shader never reads."
                )


def program_data(dxbc: bytes, gs_input_primitive: int = 0) -> bytes:
    """Unity's 38-byte DX11 header followed by the DXBC container."""
    srv, cbuffer, sampler = declaration_counts(dxbc)
    for label, value in (("SRV", srv), ("constant buffer", cbuffer), ("sampler", sampler)):
        if not 0 <= value <= 255:
            raise PipelineError(f"{label} count {value} does not fit the one-byte header field")
    header = bytes([2, srv, cbuffer, sampler, 0, gs_input_primitive]) + b"\x00" * 32
    if len(header) != PROGRAM_DATA_HEADER:  # pragma: no cover - arithmetic guard
        raise PipelineError(
            f"built a {len(header)}-byte program-data header, not {PROGRAM_DATA_HEADER}"
        )
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
    for _ in range(3):  # ALU, TEX, flow instruction counts
        writer.i32(0)
    writer.i32(temp_register_count(dxbc))
    writer.i32(0)  # keyword count: this writer emits no variants
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
    dimension: int = 2  # Tex2D
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
        buffers = (CBuffer("", 0), *self.buffers)
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
            writer.i32(0)  # struct params: none
        entries = len(self.textures) + len(self.bindings) + len(self.samplers)
        writer.i32(entries)
        for texture in self.textures:
            writer.string(texture.name)
            writer.i32(0)
            writer.i32(texture.index)
            writer.u32(texture.sampler_index)  # 0xffffffff = the texture's own sampler
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
        table.u32(0)  # segment: 0 in every stock record
        payload += record
    return bytes(table.out) + bytes(payload)


def compress_lz4(data: bytes) -> bytes:
    """LZ4 block compression, the codec every stock platform blob uses."""
    try:
        import lz4.block
    except ImportError as exc:  # pragma: no cover - capability gated
        raise PipelineError(
            "the lz4 module is required to compress a shader blob; "
            "it is declared with UnityPy in the inspect extra."
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
    hardware tier, and two platforms: d3d11 (the one the game runs, through
    Proton) and OpenGLCore (so a Linux editor running `verify-bundle` has a
    sub-program it can actually create).
    """
    fragment_source = UNLIT_FRAGMENT_HLSL
    if texture_property != "_MainTex":
        fragment_source = fragment_source.replace("_MainTex", texture_property)
    vertex_dxbc = compile_hlsl(UNLIT_VERTEX_HLSL, "vs_4_0")
    fragment_dxbc = compile_hlsl(fragment_source, "ps_4_0")
    # Cheap, and it is the difference between a prop that draws on every
    # graphics API and one that draws on OpenGL only.
    assert_cbuffer_layout(vertex_dxbc, (UNITY_PER_DRAW, UNITY_PER_FRAME))

    vertex_parameters = ParameterBlob(
        buffers=(UNITY_PER_DRAW, UNITY_PER_FRAME),
        bindings=(CBufferBinding("UnityPerDraw", 0), CBufferBinding("UnityPerFrame", 1)),
    )
    fragment_parameters = ParameterBlob(
        textures=(TextureEntry(texture_property, index=0, sampler_index=0),),
        samplers=(SamplerEntry(f"sampler{texture_property}", bind_point=0, sampler=0),),
    )
    d3d11_raw = assemble_blob(
        [
            vertex_parameters.to_bytes(),
            fragment_parameters.to_bytes(),
            code_blob(DX11_VERTEX_SM40, vertex_dxbc),
            code_blob(DX11_PIXEL_SM40, fragment_dxbc, bind_inputs=False),
        ]
    )
    # The OpenGLCore variant exists so a Linux editor can actually load a
    # sub-program: a d3d11-only shader has nothing that host can create, and
    # `shamway verify-bundle` then reports it unsupported for a reason that
    # says nothing about the bundle. The game runs d3d11 under Proton.
    glsl = (
        UNLIT_GLSL
        if texture_property == "_MainTex"
        else UNLIT_GLSL.replace("_MainTex", texture_property)
    )
    gl_raw = assemble_blob(
        [
            vertex_parameters.to_bytes(),
            fragment_parameters.to_bytes(),
            source_blob(GL_CORE_32, glsl, UNLIT_VERTEX_ATTRIBUTES),
            source_blob(GL_CORE_32, glsl, UNLIT_VERTEX_ATTRIBUTES),
        ]
    )
    # Vulkan is additive and optional: a host without the SMOL-V encoder builds
    # exactly the two platforms it always did, rather than failing. The game
    # only reaches for platform 18 under `-force-vulkan`, so its absence costs
    # nothing on a default client.
    vulkan: tuple[PlatformBlob, ...] = ()
    if smolv_library() is not None:
        # One parameter record for both stages, because one Vulkan code record
        # carries both: a stock Vulkan parameter record declares `VGlobals` and
        # `PGlobals` together, where d3d11 keeps a record per stage.
        #
        # The fragment is GLSL (see UNLIT_FRAGMENT_GLSL_VULKAN) so the module
        # carries the one combined image-sampler every stock fragment module
        # has, and the parameter record mirrors stock: the texture entry names
        # its own sampler (0xffffffff = none) and there is no separate sampler
        # entry, exactly as the measured VertexLit record declares `_MainTex`.
        vulkan_fragment = (
            UNLIT_FRAGMENT_GLSL_VULKAN
            if texture_property == "_MainTex"
            else UNLIT_FRAGMENT_GLSL_VULKAN.replace("_MainTex", texture_property)
        )
        vulkan_parameters = ParameterBlob(
            buffers=(VULKAN_VERTEX_CBUFFER,),
            # The entry indices are the (stage, kind, slot) encoding every
            # measured stock record carries: VGlobals is bound by the vertex
            # program (0x04) as a constant buffer (0x01) at slot 0, the
            # texture by the fragment program (0x08) at slot 0. The material
            # binder finds the texture by name and reads the slot from this
            # index; an index of plain 8 - slot 8, stage 0 - makes the Vulkan
            # draw fault (AMD RADV, device lost, no log line) with everything
            # else stock-shaped. The module's own descriptor binding stays 0;
            # the runtime derives the binding from the module, not this index.
            bindings=(CBufferBinding(VULKAN_VERTEX_GLOBALS, 0x04010000, array_size=0),),
            textures=(TextureEntry(texture_property, index=0x08000000, sampler_index=0xFFFFFFFF),),
        )
        vulkan_raw = assemble_blob(
            [
                vulkan_parameters.to_bytes(),
                vulkan_code_blob(
                    compress_smolv(
                        unity_descriptor_sets(
                            compile_spirv_glslang(vulkan_fragment, "frag", language="glsl")
                        )
                    ),
                    compress_smolv(
                        unity_descriptor_sets(
                            compile_spirv_glslang(UNLIT_VERTEX_HLSL_VULKAN, "vert")
                        )
                    ),
                ),
            ]
        )
        vulkan = (
            PlatformBlob(
                SHADER_COMPILER_PLATFORM_VULKAN,
                compress_lz4(vulkan_raw),
                len(vulkan_raw),
                VULKAN_PROGRAM,
                VULKAN_PROGRAM,
                # One parameter record and one code record, both shared by the
                # two stages - the shape a stock Vulkan blob has.
                0,
                0,
                1,
                1,
                stage_count=1,
            ),
        )

    return CompiledShader(
        platforms=(
            PlatformBlob(
                SHADER_COMPILER_PLATFORM_D3D11,
                compress_lz4(d3d11_raw),
                len(d3d11_raw),
                DX11_VERTEX_SM40,
                DX11_PIXEL_SM40,
                0,
                1,
                2,
                3,
                stage_count=2,
            ),
            PlatformBlob(
                SHADER_COMPILER_PLATFORM_GL_CORE,
                compress_lz4(gl_raw),
                len(gl_raw),
                GL_CORE_32,
                GL_CORE_32,
                0,
                1,
                2,
                3,
                stage_count=1,
            ),
            *vulkan,
        ),
        texture_name=texture_property,
        dxbc={"vertex": vertex_dxbc, "fragment": fragment_dxbc},
    )
