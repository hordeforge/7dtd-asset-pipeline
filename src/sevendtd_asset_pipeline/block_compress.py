"""Block-compress texture pixels into the formats Unity's runtime decodes.

The editorless writer shipped textures as raw RGBA32, which is correct and
roughly 4-8x larger than what Unity's own importer would have produced
(`docs/status/improvements.md` 4). This closes the texture half of that gap
with no new dependency: BC1 (`DXT1`) and BC3 (`DXT5`) are simple enough to
encode here, and both are `TextureFormat` values the shipped game decodes in
hardware.

BC7 is deliberately **not** attempted in Python. It has 8 block modes and a
partition table, and a mediocre BC7 encoder is worse than a good BC1 one at
the same size; the registry offers `bc7enc`/`Compressonator` for it instead,
and says so when asked.

Compression is lossy and this project does not change what an author signed
off on without saying so, so it is opt-in and every call reports the PSNR it
achieved. A block-compressed texture is also **not** a free win on tiny art:
a 4x4 icon cell is one block either way.

The encoder is the classic bounding-box fit: take each 4x4 block's per-channel
min and max as the two endpoints, build the implied 4-colour ramp, and pick
the nearest entry per texel. That is what fast production encoders do before
their refinement passes, and the refinement is what `bc7enc`'s RDO modes buy.
"""

from __future__ import annotations

from typing import Any

from .capabilities import require_capability
from .errors import PipelineError

# Unity TextureFormat values, from the enum the runtime switches on.
TEXTURE_DXT1 = 10
TEXTURE_DXT5 = 12

BLOCK = 4


def _to_565(colour: Any) -> Any:
    """Pack an (N, 3) uint8 array into RGB565, the endpoint format BCn stores."""
    red = (colour[:, 0].astype("uint16") >> 3) & 0x1F
    green = (colour[:, 1].astype("uint16") >> 2) & 0x3F
    blue = (colour[:, 2].astype("uint16") >> 3) & 0x1F
    return (red << 11) | (green << 5) | blue


def _from_565(packed: Any, numpy: Any) -> Any:
    """Expand RGB565 back to 8-bit, the way a GPU decoder does.

    The endpoints are quantized *before* the ramp is built, so the encoder has
    to compare texels against the colours the decoder will actually produce,
    not against the ones it started from. Rounding this differently is how an
    encoder ends up systematically off by a few levels.
    """
    red = ((packed >> 11) & 0x1F).astype("uint16")
    green = ((packed >> 5) & 0x3F).astype("uint16")
    blue = (packed & 0x1F).astype("uint16")
    out = numpy.empty((packed.shape[0], 3), dtype="int16")
    out[:, 0] = (red << 3) | (red >> 2)
    out[:, 1] = (green << 2) | (green >> 4)
    out[:, 2] = (blue << 3) | (blue >> 2)
    return out


def _blocks(pixels: Any) -> Any:
    """Reorder (H, W, 4) pixels into (N, 16, 4) blocks in BCn's texel order."""
    height, width = pixels.shape[0], pixels.shape[1]
    grid = pixels.reshape(height // BLOCK, BLOCK, width // BLOCK, BLOCK, 4)
    return grid.transpose(0, 2, 1, 3, 4).reshape(-1, BLOCK * BLOCK, 4)


def _colour_blocks(blocks: Any, numpy: Any) -> tuple[Any, Any, Any]:
    """The 8-byte BC1 colour block for every input block."""
    rgb = blocks[:, :, :3].astype("int16")
    high = rgb.max(axis=1)
    low = rgb.min(axis=1)
    c0 = _to_565(high.astype("uint8"))
    c1 = _to_565(low.astype("uint8"))

    # A flat block quantizes to c0 == c1. Left alone the decoder would read
    # that as three-colour mode, where index 3 is *transparent black* — a
    # punch-through hole in an opaque texture. Every index is forced to 0,
    # which is the same colour in either mode.
    flat = c0 <= c1
    c0 = numpy.where(flat, c1, c0)

    p0 = _from_565(c0, numpy)
    p1 = _from_565(c1, numpy)
    palette = numpy.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=1)  # (N, 4, 3)

    distance = ((rgb[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(axis=-1)
    indices = distance.argmin(axis=-1).astype("uint32")
    indices[flat] = 0
    return c0, c1, indices


def _pack_indices(indices: Any, bits: int, numpy: Any) -> Any:
    """Pack per-texel indices little-endian, `bits` each, texel 0 lowest."""
    shifts = (numpy.arange(indices.shape[1], dtype="uint64") * bits).astype("uint64")
    return (indices.astype("uint64") << shifts[None, :]).sum(axis=1)


def _alpha_blocks(blocks: Any, numpy: Any) -> tuple[Any, Any, Any]:
    """The 8-byte BC3 alpha block: two endpoints and 3-bit indices."""
    alpha = blocks[:, :, 3].astype("int16")
    a0 = alpha.max(axis=1)
    a1 = alpha.min(axis=1)
    # Eight-value mode: a0 > a1 and six interpolants between them.
    ramp = numpy.stack([a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)], axis=1)
    distance = numpy.abs(alpha[:, :, None] - ramp[:, None, :])
    indices = distance.argmin(axis=-1).astype("uint32")
    indices[a0 <= a1] = 0
    return a0.astype("uint8"), a1.astype("uint8"), indices


def compress(pixels: Any, alpha: bool) -> tuple[bytes, int]:
    """Block-compress `pixels`, an (H, W, 4) uint8 array, bottom row first.

    Returns the raw block stream and the Unity `TextureFormat` it is in.
    Dimensions must be multiples of four; a block format cannot express
    anything else, and silently padding would change the UVs of every atlas
    cell built on the old size.
    """
    require_capability("numpy")
    import numpy

    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    if height % BLOCK or width % BLOCK:
        raise PipelineError(
            f"{width}x{height} cannot be block-compressed: both sides must be a "
            "multiple of 4. Resize the source, or leave this texture uncompressed."
        )

    blocks = _blocks(pixels)
    c0, c1, colour_indices = _colour_blocks(blocks, numpy)
    packed_colour = _pack_indices(colour_indices, 2, numpy)

    count = blocks.shape[0]
    if not alpha:
        out = numpy.empty((count, 8), dtype="uint8")
        out[:, 0] = c0 & 0xFF
        out[:, 1] = (c0 >> 8) & 0xFF
        out[:, 2] = c1 & 0xFF
        out[:, 3] = (c1 >> 8) & 0xFF
        for byte in range(4):
            out[:, 4 + byte] = (packed_colour >> (8 * byte)) & 0xFF
        return out.tobytes(), TEXTURE_DXT1

    a0, a1, alpha_indices = _alpha_blocks(blocks, numpy)
    packed_alpha = _pack_indices(alpha_indices, 3, numpy)
    out = numpy.empty((count, 16), dtype="uint8")
    out[:, 0] = a0
    out[:, 1] = a1
    for byte in range(6):
        out[:, 2 + byte] = (packed_alpha >> (8 * byte)) & 0xFF
    out[:, 8] = c0 & 0xFF
    out[:, 9] = (c0 >> 8) & 0xFF
    out[:, 10] = c1 & 0xFF
    out[:, 11] = (c1 >> 8) & 0xFF
    for byte in range(4):
        out[:, 12 + byte] = (packed_colour >> (8 * byte)) & 0xFF
    return out.tobytes(), TEXTURE_DXT5


def decode(blocks: bytes, width: int, height: int, texture_format: int) -> Any:
    """Decode a block stream back to (H, W, 4) uint8, for the quality report.

    An encoder graded by its own arithmetic has not been graded. This decodes
    the way a GPU does so `psnr` compares against what a player would see.
    """
    require_capability("numpy")
    import numpy

    stride = 8 if texture_format == TEXTURE_DXT1 else 16
    raw = numpy.frombuffer(blocks, dtype="uint8").reshape(-1, stride)
    offset = 0 if texture_format == TEXTURE_DXT1 else 8
    c0 = raw[:, offset].astype("uint16") | (raw[:, offset + 1].astype("uint16") << 8)
    c1 = raw[:, offset + 2].astype("uint16") | (raw[:, offset + 3].astype("uint16") << 8)
    packed = numpy.zeros(raw.shape[0], dtype="uint64")
    for byte in range(4):
        packed |= raw[:, offset + 4 + byte].astype("uint64") << (8 * byte)
    indices = numpy.stack([(packed >> (2 * i)) & 0x3 for i in range(16)], axis=1)

    p0 = _from_565(c0, numpy)
    p1 = _from_565(c1, numpy)
    palette = numpy.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=1)
    texels = numpy.take_along_axis(palette, indices[:, :, None], axis=1)

    out = numpy.empty((raw.shape[0], 16, 4), dtype="uint8")
    out[:, :, :3] = texels.astype("uint8")
    if texture_format == TEXTURE_DXT1:
        out[:, :, 3] = 255
    else:
        a0 = raw[:, 0].astype("int16")
        a1 = raw[:, 1].astype("int16")
        ramp = numpy.stack([a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)], axis=1)
        bits = numpy.zeros(raw.shape[0], dtype="uint64")
        for byte in range(6):
            bits |= raw[:, 2 + byte].astype("uint64") << (8 * byte)
        alpha_indices = numpy.stack([(bits >> (3 * i)) & 0x7 for i in range(16)], axis=1)
        out[:, :, 3] = numpy.take_along_axis(ramp, alpha_indices.astype("int64"), axis=1)

    grid = out.reshape(height // BLOCK, width // BLOCK, BLOCK, BLOCK, 4)
    return grid.transpose(0, 2, 1, 3, 4).reshape(height, width, 4)


def psnr(original: Any, decoded: Any) -> float:
    """Peak signal-to-noise ratio in dB; infinite when the two are identical."""
    require_capability("numpy")
    import numpy

    error = (original.astype("float64") - decoded.astype("float64")) ** 2
    mean = float(error.mean())
    if mean == 0.0:
        return float("inf")
    return float(10.0 * numpy.log10((255.0**2) / mean))


def visible_psnr(original: Any, decoded: Any) -> float:
    """PSNR of what a viewer actually sees: both images composited first.

    Measuring raw RGB on an image with transparency reports a failure that is
    not there. A rendered icon's fully transparent pixels carry whatever RGB
    the renderer left behind — Blender's Cycles leaves *noise*, measured at
    min 0, max 255, standard deviation 27.7 on a real `generate mesh-icon`
    output — and BC1's shared colour endpoints spend real precision trying to
    fit it. Graded raw, that icon scored 16.9 dB and looked broken. Composited
    over black and over white, the same file scores 39.9 and 40.2 dB, and the
    opaque pixels alone score 36.3.

    So the number this returns is the worse of the two composites: the honest
    answer to "how much worse does this look", and immune to garbage nobody
    can see. Reported rather than enforced, because the right threshold
    depends on the art — a flat UI panel survives BC1 where a normal map does
    not.
    """
    require_capability("numpy")
    import numpy

    def over(image: Any, background: int) -> Any:
        alpha = image[..., 3:4].astype("float64") / 255.0
        colour = image[..., :3].astype("float64")
        return colour * alpha + background * (1.0 - alpha)

    if original.shape[-1] < 4:
        return psnr(original, decoded)
    return float(
        numpy.minimum(
            psnr(over(original, 0), over(decoded, 0)),
            psnr(over(original, 255), over(decoded, 255)),
        )
    )
