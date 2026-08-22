"""Small dependency-free UnityFS and SerializedFile metadata reader.

It intentionally reads only enough data to establish the bundle revision and
serialized class IDs. That is sufficient for the class-142 AssetBundle gate.
It does not claim to deserialize or render assets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError

ASSET_BUNDLE_CLASS_ID = 142


@dataclass(frozen=True)
class BundleInfo:
    path: Path
    unity_version: str
    archive_format: int
    class_ids: tuple[int, ...]

    @property
    def has_assetbundle_object(self) -> bool:
        return ASSET_BUNDLE_CLASS_ID in self.class_ids


def _c_string(data: bytes, offset: int) -> tuple[str, int]:
    try:
        end = data.index(b"\x00", offset)
    except ValueError as exc:
        raise PipelineError("unterminated string in Unity bundle") from exc
    return data[offset:end].decode("utf-8", "replace"), end + 1


def _need(data: bytes | memoryview, offset: int, length: int, label: str) -> None:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise PipelineError(f"truncated Unity bundle while reading {label}")


def _lz4_decompress(source: bytes, expected_size: int) -> bytes:
    output = bytearray()
    position = 0
    while position < len(source):
        token = source[position]
        position += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                _need(source, position, 1, "LZ4 literal length")
                extra = source[position]
                position += 1
                literal_length += extra
                if extra != 255:
                    break
        _need(source, position, literal_length, "LZ4 literals")
        output.extend(source[position : position + literal_length])
        position += literal_length
        if position == len(source):
            break
        _need(source, position, 2, "LZ4 match offset")
        match_offset = source[position] | (source[position + 1] << 8)
        position += 2
        if match_offset == 0 or match_offset > len(output):
            raise PipelineError("invalid LZ4 match offset in Unity bundle")
        match_length = token & 0x0F
        if match_length == 15:
            while True:
                _need(source, position, 1, "LZ4 match length")
                extra = source[position]
                position += 1
                match_length += extra
                if extra != 255:
                    break
        match_length += 4
        start = len(output) - match_offset
        for index in range(match_length):
            output.append(output[start + index])
        if len(output) > expected_size:
            raise PipelineError("LZ4 block expands beyond its declared size")
    if len(output) != expected_size:
        raise PipelineError(
            f"LZ4 block size mismatch: expected {expected_size}, got {len(output)}"
        )
    return bytes(output)


def _decompress(chunk: bytes, size: int, flags: int) -> bytes:
    compression = flags & 0x3F
    if compression == 0:
        if len(chunk) != size:
            raise PipelineError("uncompressed UnityFS block has the wrong size")
        return chunk
    if compression in (2, 3):
        return _lz4_decompress(chunk, size)
    if compression == 1:
        raise PipelineError("LZMA-compressed UnityFS metadata is not supported; build with LZ4")
    raise PipelineError(f"unsupported UnityFS compression mode {compression}")


def _class_ids(serialized: bytes) -> tuple[int, ...]:
    _need(serialized, 0, 20, "SerializedFile header")
    version = struct.unpack_from(">I", serialized, 8)[0]
    cursor = 20
    if version >= 22:
        _need(serialized, cursor, 28, "extended SerializedFile header")
        cursor += 28
    _unity_version, cursor = _c_string(serialized, cursor)
    _need(serialized, cursor, 9, "SerializedFile platform/type header")
    cursor += 4
    has_type_tree = serialized[cursor]
    cursor += 1
    type_count = struct.unpack_from("<I", serialized, cursor)[0]
    cursor += 4
    if type_count > 100_000:
        raise PipelineError("implausible SerializedFile type count")

    result: list[int] = []
    for _ in range(type_count):
        _need(serialized, cursor, 23, "SerializedFile type")
        class_id = struct.unpack_from("<i", serialized, cursor)[0]
        cursor += 7
        if class_id == 114:
            _need(serialized, cursor, 16, "MonoBehaviour script ID")
            cursor += 16
        cursor += 16
        result.append(class_id)
        if has_type_tree:
            _need(serialized, cursor, 8, "type tree header")
            node_count, string_size = struct.unpack_from("<II", serialized, cursor)
            cursor += 8
            tree_size = node_count * 32 + string_size
            _need(serialized, cursor, tree_size, "type tree")
            cursor += tree_size
            if version >= 21:
                _need(serialized, cursor, 4, "type dependency count")
                dependency_count = struct.unpack_from("<I", serialized, cursor)[0]
                cursor += 4
                _need(serialized, cursor, dependency_count * 4, "type dependencies")
                cursor += dependency_count * 4
    return tuple(result)


def inspect_bundle(path: Path) -> BundleInfo:
    path = path.resolve()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read bundle {path}: {exc}") from exc
    if not data.startswith(b"UnityFS\x00"):
        raise PipelineError(f"{path} is not a UnityFS asset bundle")
    position = len(b"UnityFS\x00")
    _need(data, position, 4, "archive format")
    archive_format = struct.unpack_from(">I", data, position)[0]
    position += 4
    _engine_version, position = _c_string(data, position)
    unity_version, position = _c_string(data, position)
    _need(data, position, 20, "UnityFS sizes and flags")
    _archive_size, table_compressed, table_uncompressed, flags = struct.unpack_from(
        ">QIII", data, position
    )
    position += 20
    if archive_format >= 7:
        position += (-position) % 16

    if flags & 0x80:
        table_start = len(data) - table_compressed
        _need(data, table_start, table_compressed, "block table")
        raw_table = data[table_start:]
    else:
        _need(data, position, table_compressed, "block table")
        raw_table = data[position : position + table_compressed]
        position += table_compressed
    table = _decompress(raw_table, table_uncompressed, flags)
    _need(table, 16, 4, "block count")
    cursor = 16
    block_count = struct.unpack_from(">I", table, cursor)[0]
    cursor += 4
    blocks: list[tuple[int, int, int]] = []
    for _ in range(block_count):
        _need(table, cursor, 10, "block descriptor")
        blocks.append(struct.unpack_from(">IIH", table, cursor))
        cursor += 10
    _need(table, cursor, 4, "node count")
    node_count = struct.unpack_from(">I", table, cursor)[0]
    cursor += 4
    if node_count == 0:
        raise PipelineError(f"{path} has no UnityFS directory nodes")
    _need(table, cursor, 20, "first node")
    node_offset, node_size, _node_flags = struct.unpack_from(">QQI", table, cursor)
    _node_name, _ = _c_string(table, cursor + 20)
    if flags & 0x200:
        position += (-position) % 16

    payload = bytearray()
    needed = node_offset + node_size
    for uncompressed, compressed, block_flags in blocks:
        _need(data, position, compressed, "payload block")
        payload.extend(_decompress(data[position : position + compressed], uncompressed, block_flags))
        position += compressed
        if len(payload) >= needed:
            break
    if len(payload) < needed:
        raise PipelineError("UnityFS payload does not contain the first directory node")
    serialized = bytes(payload[node_offset:needed])
    return BundleInfo(path, unity_version, archive_format, _class_ids(serialized))
