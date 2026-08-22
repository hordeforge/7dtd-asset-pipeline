from __future__ import annotations

import struct


def serialized_file(class_ids: list[int], unity_version: str = "2022.3.62f2") -> bytes:
    data = bytearray(20)
    struct.pack_into(">I", data, 8, 22)
    data.extend(bytes(28))
    data.extend(unity_version.encode() + b"\x00")
    data.extend(struct.pack("<I", 19))
    data.append(0)  # no type trees
    data.extend(struct.pack("<I", len(class_ids)))
    for class_id in class_ids:
        data.extend(struct.pack("<iBh", class_id, 0, 0))
        if class_id == 114:
            data.extend(bytes(16))
        data.extend(bytes(16))
    return bytes(data)


def unityfs_bundle(class_ids: list[int], unity_version: str = "2022.3.62f2") -> bytes:
    payload = serialized_file(class_ids, unity_version)
    table = bytearray(16)
    table.extend(struct.pack(">I", 1))
    table.extend(struct.pack(">IIH", len(payload), len(payload), 0))
    table.extend(struct.pack(">I", 1))
    table.extend(struct.pack(">QQI", 0, len(payload), 0))
    table.extend(b"CAB-test\x00")

    prefix = bytearray(b"UnityFS\x00")
    prefix.extend(struct.pack(">I", 7))
    prefix.extend(b"2022.3.62f2\x00")
    prefix.extend(unity_version.encode() + b"\x00")
    size_offset = len(prefix)
    prefix.extend(bytes(20))
    while len(prefix) % 16:
        prefix.append(0)
    archive_size = len(prefix) + len(table) + len(payload)
    struct.pack_into(">QIII", prefix, size_offset, archive_size, len(table), len(table), 0x40)
    return bytes(prefix + table + payload)
