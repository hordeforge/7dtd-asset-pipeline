"""Small dependency-free UnityFS and SerializedFile metadata reader.

It intentionally reads only enough data to establish the bundle revision and
serialized class IDs. That is sufficient for the class-142 AssetBundle gate.
It does not claim to deserialize or render assets.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

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
        # Copies are the decoder's hot loop; a Python-level per-byte append is
        # orders of magnitude slower than block copies, so slice whenever the
        # source does not overlap the destination and tile when it does.
        if match_offset >= match_length:
            output.extend(output[start : start + match_length])
        else:
            pattern = bytes(output[start:])
            repeats = -(-match_length // match_offset)
            output.extend((pattern * repeats)[:match_length])
        if len(output) > expected_size:
            raise PipelineError("LZ4 block expands beyond its declared size")
    if len(output) != expected_size:
        raise PipelineError(f"LZ4 block size mismatch: expected {expected_size}, got {len(output)}")
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


HEADER_WINDOW = 4096
# The class table sits at the start of the serialized file, so decompressing a
# small prefix answers the gate, and every window below is tried before the
# whole node is read. Shipped game bundles hold serialized files of hundreds of
# megabytes and pure-Python LZ4 costs seconds per tens of megabytes, and this
# reader runs on every doctor/status/validate call against those bundles:
# measured on the game's own Entities/trees bundle (650 MB archive, 111 MB
# serialized node), the type table ends 125 KiB into the node while a fixed
# 32 MiB window decompressed 257 blocks to reach it (research-provenance.md,
# "Class-table prefix window"). The initial window covers tables many times
# larger than that one; growth quadruples twice before the full node is read.
TYPE_TABLE_PREFIX = 1024 * 1024
TYPE_TABLE_MAX = 32 * 1024 * 1024


def _read_at(handle: BinaryIO, offset: int, length: int, label: str) -> bytes:
    """Read exactly `length` bytes at `offset`, or fail with a bounded error."""
    if offset < 0 or length < 0:
        raise PipelineError(f"truncated Unity bundle while reading {label}")
    handle.seek(offset)
    chunk = handle.read(length)
    if len(chunk) != length:
        raise PipelineError(f"truncated Unity bundle while reading {label}")
    return chunk


def inspect_bundle(path: Path) -> BundleInfo:
    """Read revision and serialized class IDs without loading the whole file.

    Shipped game bundles reach hundreds of megabytes, and this runs on every
    doctor/build/validate call, so only the header, the block table, and the
    blocks covering the first directory node are ever read.
    """
    path = path.resolve()
    try:
        with path.open("rb") as handle:
            file_size = path.stat().st_size
            header = handle.read(HEADER_WINDOW)
            if not header.startswith(b"UnityFS\x00"):
                raise PipelineError(f"{path} is not a UnityFS asset bundle")
            position = len(b"UnityFS\x00")
            _need(header, position, 4, "archive format")
            archive_format = struct.unpack_from(">I", header, position)[0]
            position += 4
            _engine_version, position = _c_string(header, position)
            unity_version, position = _c_string(header, position)
            _need(header, position, 20, "UnityFS sizes and flags")
            _archive_size, table_compressed, table_uncompressed, flags = struct.unpack_from(
                ">QIII", header, position
            )
            position += 20
            if archive_format >= 7:
                position += (-position) % 16

            if flags & 0x80:
                raw_table = _read_at(
                    handle, file_size - table_compressed, table_compressed, "block table"
                )
            else:
                raw_table = _read_at(handle, position, table_compressed, "block table")
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

            needed = node_offset + node_size

            def read_payload(limit: int) -> bytes:
                payload = bytearray()
                cursor = position
                for uncompressed, compressed, block_flags in blocks:
                    chunk = _read_at(handle, cursor, compressed, "payload block")
                    payload.extend(_decompress(chunk, uncompressed, block_flags))
                    cursor += compressed
                    if len(payload) >= limit:
                        break
                if len(payload) < min(limit, needed):
                    raise PipelineError("UnityFS payload does not contain the first directory node")
                return bytes(payload[node_offset : min(len(payload), needed)])

            # The gate reads the smallest window that holds the class table:
            # a table inside the first window answers immediately, a larger
            # one pays only the ladder up to its own size, and a truncated or
            # corrupt file still fails with the same bounded error once the
            # whole node has been tried. A failure at one window is also how
            # "the table continues past this window" is detected, so the
            # ladder re-parses from the start of the payload each rung.
            window = TYPE_TABLE_PREFIX
            while True:
                prefix_limit = min(needed, node_offset + window)
                try:
                    class_ids = _class_ids(read_payload(prefix_limit))
                    break
                except PipelineError:
                    if prefix_limit >= needed:
                        raise
                    window = needed if window >= TYPE_TABLE_MAX else min(window * 4, TYPE_TABLE_MAX)
    except OSError as exc:
        raise PipelineError(f"cannot read bundle {path}: {exc}") from exc
    return BundleInfo(path, unity_version, archive_format, class_ids)
