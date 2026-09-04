from __future__ import annotations

import json
import struct
from pathlib import Path


def static_triangle_glb(path: Path) -> Path:
    """A one-triangle GLB `parse_gltf` accepts, with no extra named nodes.

    Acceptance membership tests used to write empty `.glb` bytes and rely on
    the writer swallowing a parse error and inventing a static prefab. A
    broken skin must fail that parse, so the dummy has to be a real document.
    """
    positions = struct.pack("<9f", 1, 0, 0, 0, 1, 0, 0, 0, 1)
    normals = struct.pack("<9f", 0, 0, 1, 0, 0, 1, 0, 0, 1)
    uvs = struct.pack("<6f", 0, 0, 1, 0, 0, 1)
    indices = struct.pack("<3H", 0, 1, 2)
    blob = positions + normals + uvs + indices
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Cube", "mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}
                ]
            }
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 36},
            {"buffer": 0, "byteOffset": 72, "byteLength": 24},
            {"buffer": 0, "byteOffset": 96, "byteLength": 6},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    json_chunk = 0x4E4F534A
    bin_chunk = 0x004E4942
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    chunks = struct.pack("<II", len(encoded), json_chunk) + encoded
    padded = blob + b"\x00" * ((-len(blob)) % 4)
    chunks += struct.pack("<II", len(padded), bin_chunk) + padded
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks)
    return path


def filesystem_is_case_insensitive(directory: Path) -> bool:
    """Probe whether `directory` sits on a case-insensitive filesystem.

    macOS's default APFS and Windows's NTFS fold name case; most Linux
    filesystems do not. The probe writes one lowercase name and asks for its
    uppercase spelling, which is a capability question about the volume, not
    about the operating system.
    """
    probe = directory / "shamway_case_probe"
    probe.write_bytes(b"")
    try:
        return probe.with_name("SHAMWAY_CASE_PROBE").exists()
    finally:
        probe.unlink(missing_ok=True)


def serialized_file(
    class_ids: list[int],
    unity_version: str = "2022.3.62f2",
    has_type_tree: bool = False,
) -> bytes:
    """A complete, object-free SerializedFile v22 for reader fixtures.

    `has_type_tree` emits, after every type entry, one 32-byte tree node plus a
    four-byte string buffer and an empty dependency table — the shape the
    shipped game's bundles carry (`docs/research/research-provenance.md`: nodes are 32
    bytes, type trees present). The trailing zero-count tables and v22 header
    make this an independently parseable file rather than the metadata prefix
    the removed pipeline-local parser used to tolerate.
    """
    metadata = bytearray(unity_version.encode() + b"\x00")
    metadata.extend(struct.pack("<I", 19))
    metadata.append(1 if has_type_tree else 0)
    metadata.extend(struct.pack("<I", len(class_ids)))
    for class_id in class_ids:
        metadata.extend(struct.pack("<iBh", class_id, 0, 0))
        if class_id == 114:
            metadata.extend(bytes(16))
        metadata.extend(bytes(16))
        if has_type_tree:
            metadata.extend(struct.pack("<II", 1, 4))  # one node, four string bytes
            metadata.extend(bytes(32))  # the node itself
            metadata.extend(b"tree")  # the string buffer
            metadata.extend(struct.pack("<I", 0))  # no type dependencies
    metadata.extend(struct.pack("<I", len(class_ids)))
    for index in range(len(class_ids)):
        metadata.extend(bytes((-len(metadata)) % 4))
        metadata.extend(struct.pack("<qqII", index + 1, 0, 0, index))
    metadata.extend(struct.pack("<III", 0, 0, 0))
    metadata.append(0)  # empty user_information C string

    metadata_size = len(metadata)
    data_offset = 48 + metadata_size
    header = bytearray(48)
    struct.pack_into(">IIII", header, 0, 0, 0, 22, 0)
    header[16] = 0  # little-endian metadata
    struct.pack_into(">Iqqq", header, 20, metadata_size, data_offset, data_offset, 0)
    return bytes(header + metadata)


def _count_parts(value: int) -> tuple[int, bytes]:
    """A sequence length as (token nibble, extension bytes), per LZ4's format."""
    if value < 15:
        return value, b""
    extra = bytearray()
    remaining = value - 15
    while remaining >= 255:
        extra.append(255)
        remaining -= 255
    extra.append(remaining)
    return 15, bytes(extra)


def _sequence(out: bytearray, literals: bytes, offset: int, match_length: int) -> None:
    lit_nibble, lit_extra = _count_parts(len(literals))
    if match_length:
        match_nibble, match_extra = _count_parts(match_length - 4)
        out.append((lit_nibble << 4) | match_nibble)
        out.extend(lit_extra)
        out.extend(literals)
        out.extend(struct.pack("<H", offset))
        out.extend(match_extra)
    else:
        out.append(lit_nibble << 4)
        out.extend(lit_extra)
        out.extend(literals)


def lz4_block(data: bytes) -> bytes:
    """Encode `data` as one spec-valid LZ4 block: greedy literals plus matches.

    The point is a fixture the pipeline's own decoder can be held against, so it
    exercises literal runs past the nibble cap, match lengths past theirs, and
    back-references at real distances — including overlapping copies.
    """
    out = bytearray()
    size = len(data)
    position = 0
    literal_start = 0
    # A match may never consume the final five bytes; that tail stays literal.
    match_limit = size - 5
    while position < size:
        best_length, best_offset = 0, 0
        for start in range(max(0, position - 65535), position):
            length = 0
            while (
                position + length < match_limit and data[start + length] == data[position + length]
            ):
                length += 1
            if length > best_length:
                best_length, best_offset = length, position - start
        if best_length >= 4:
            _sequence(out, data[literal_start:position], best_offset, best_length)
            position += best_length
            literal_start = position
        else:
            position += 1
    _sequence(out, data[literal_start:size], 0, 0)
    return bytes(out)


def build_bundle(
    blocks: list[tuple[bytes, int, int]],
    *,
    unity_version: str = "2022.3.62f2",
    node_size: int,
    header_flags: int = 0x40,
    node_count: int = 1,
    table_at_end: bool = False,
    truncate_table: int = 0,
    node_offset: int = 0,
) -> bytes:
    """Assemble a UnityFS archive from raw blocks.

    Each block is `(compressed_bytes, declared_uncompressed_size, flags)`; every
    field stays caller-controlled so malformed archives stay expressible.
    """
    payload = bytearray()
    descriptors = []
    for chunk, uncompressed, flags in blocks:
        descriptors.append((uncompressed, len(chunk), flags))
        payload.extend(chunk)

    def make_table() -> bytes:
        table = bytearray(16)
        table.extend(struct.pack(">I", len(descriptors)))
        for uncompressed, compressed, flags in descriptors:
            table.extend(struct.pack(">IIH", uncompressed, compressed, flags))
        table.extend(struct.pack(">I", node_count))
        if node_count:
            table.extend(struct.pack(">QQI", node_offset, node_size, 0))
            table.extend(b"CAB-test\x00")
        return bytes(table)

    table = make_table()
    prefix = bytearray(b"UnityFS\x00")
    prefix.extend(struct.pack(">I", 7))
    prefix.extend(b"2022.3.62f2\x00")
    prefix.extend(unity_version.encode() + b"\x00")
    size_offset = len(prefix)
    prefix.extend(bytes(20))
    while len(prefix) % 16:
        prefix.append(0)
    # The reader aligns the payload to 16 when the padding bit is set; the
    # fixture must place the blocks where the reader will look for them. With
    # the table at the end, the read position is already block-aligned.
    pad_to_block = (-(len(prefix) + len(table))) % 16 if header_flags & 0x200 else 0
    if table_at_end:
        body = bytes(payload) + table
        header_flags |= 0x80
    else:
        body = table + bytes(pad_to_block) + bytes(payload)
    kept = len(body) - truncate_table
    struct.pack_into(
        ">QIII",
        prefix,
        size_offset,
        len(prefix) + kept,
        len(table),
        len(table),
        header_flags,
    )
    return bytes(prefix + body[:kept])


def unityfs_bundle(
    class_ids: list[int], unity_version: str = "2022.3.62f2", has_type_tree: bool = False
) -> bytes:
    payload = serialized_file(class_ids, unity_version, has_type_tree)
    return build_bundle(
        [(payload, len(payload), 0)], unity_version=unity_version, node_size=len(payload)
    )


def lz4_bundle(
    class_ids: list[int], unity_version: str = "2022.3.62f2", has_type_tree: bool = False
) -> bytes:
    payload = serialized_file(class_ids, unity_version, has_type_tree)
    compressed = lz4_block(payload)
    return build_bundle(
        [(compressed, len(payload), 2)], unity_version=unity_version, node_size=len(payload)
    )
