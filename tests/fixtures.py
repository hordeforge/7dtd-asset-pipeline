from __future__ import annotations

import struct


def serialized_file(
    class_ids: list[int],
    unity_version: str = "2022.3.62f2",
    has_type_tree: bool = False,
) -> bytes:
    """A SerializedFile the way `unityfs._class_ids` reads one.

    `has_type_tree` emits, after every type entry, one 32-byte tree node plus a
    four-byte string buffer and an empty dependency table — the shape the
    shipped game's bundles carry (`docs/research-provenance.md`: nodes are 32
    bytes, type trees present). Every real bundle takes that branch; the
    default keeps the older, shorter fixtures byte-stable.
    """
    data = bytearray(20)
    struct.pack_into(">I", data, 8, 22)
    data.extend(bytes(28))
    data.extend(unity_version.encode() + b"\x00")
    data.extend(struct.pack("<I", 19))
    data.append(1 if has_type_tree else 0)
    data.extend(struct.pack("<I", len(class_ids)))
    for class_id in class_ids:
        data.extend(struct.pack("<iBh", class_id, 0, 0))
        if class_id == 114:
            data.extend(bytes(16))
        data.extend(bytes(16))
        if has_type_tree:
            data.extend(struct.pack("<II", 1, 4))  # one node, four string bytes
            data.extend(bytes(32))  # the node itself
            data.extend(b"tree")  # the string buffer
            data.extend(struct.pack("<I", 0))  # no ref dependencies
    return bytes(data)


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
