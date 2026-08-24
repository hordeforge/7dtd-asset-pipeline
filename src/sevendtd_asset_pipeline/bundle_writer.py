"""Write a Unity asset bundle without Unity.

`unityfs.py` reads the container; this writes one. It is the other half of the
same format, and it exists so that a mod whose assets are textures, text and
sound can produce `Resources/<name>.unity3d` on a machine with no editor —
CI, a headless agent host, a laptop that will never install several gigabytes
of Unity.

What it emits is the structure Unity itself emits, established by dissecting
the bundles the installed game ships (`docs/research/research-provenance.md`):

    UnityFS header, format 8, revision <the game's own>
      block table: one uncompressed block
      directory:   CAB-<hex>  and, when a clip is present, CAB-<hex>.resource
    SerializedFile version 22, little-endian metadata, type trees written
      types:    one per class, with the release type tree for this revision
      objects:  8-byte aligned, byte_start relative to data_offset
      data:     each object serialized by walking its own type tree

The type trees come from UnityPy's per-version database, which is why this
backend declares the `UnityPy` capability: a type tree is the engine's own
field layout for a class at an exact revision, and guessing one is how a
bundle becomes a silent load failure. The same library then serializes each
object by walking that tree, so the field order, array shape and alignment
rules are the ones a reader of Unity's format already agrees on.

The proof boundary is narrow and stated in `docs/bundles/no-unity.md`: this writes
containers and objects for a bounded set of classes. It does not replace
Unity's importers, its shader compiler, or its prefab serialization, and an
offline parse of what it wrote proves construction, never acceptance.
"""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .capabilities import require_capability
from .errors import PipelineError

ASSET_BUNDLE = 142
TEXT_ASSET = 49
TEXTURE_2D = 28
AUDIO_CLIP = 83
MESH = 43

SERIALIZED_VERSION = 22
# BuildTarget.StandaloneWindows64. The shipped client loads a Windows-target
# bundle even under Proton, which is why the whole pipeline defaults to it.
STANDALONE_WINDOWS64 = 19


@dataclass
class BundleObject:
    """One serialized object: its class, its name, and its typetree fields."""

    class_id: int
    name: str
    fields: dict[str, Any]
    resource: bytes = b""
    """Bytes to append to the bundle's `.resource` stream.

    An AudioClip does not carry its samples in the object; it carries an offset
    and a length into a resource stream stored beside the serialized file. The
    builder appends these bytes and patches the object's offset, because only
    the builder knows the final layout.
    """
    resource_field: tuple[str, ...] = ()
    """Path to the `StreamedResource` sub-object whose offset must be patched."""


@dataclass
class _Serialized:
    metadata: bytes
    data: bytes
    resource: bytes = b""


def _node(class_id: int, unity_version: str) -> Any:
    """The release type tree for one class at one exact Unity revision.

    The node type belongs to UnityPy, an untyped boundary here; callers pass
    it straight back into that library.
    """
    require_capability("UnityPy")
    from UnityPy.helpers.Tpk import get_typetree_node
    from UnityPy.helpers.UnityVersion import UnityVersion

    try:
        return get_typetree_node(class_id, UnityVersion.from_str(unity_version))
    except Exception as exc:
        raise PipelineError(
            f"no type tree for class {class_id} at Unity {unity_version}: {exc}. "
            "The type tree is the engine's own field layout; without it this "
            "backend will not guess one."
        ) from exc


def _write_object(value: dict[str, Any], node: Any) -> bytes:
    from UnityPy.helpers.TypeTreeHelper import write_typetree
    from UnityPy.streams import EndianBinaryWriter

    writer = EndianBinaryWriter(endian="<")
    try:
        write_typetree(value, node, writer)
    except Exception as exc:
        raise PipelineError(
            f"cannot serialize a {node.m_Type} object: {exc}. Every field the "
            "type tree names must be present and of the right shape."
        ) from exc
    return cast(bytes, writer.bytes)


def _common_strings() -> dict[str, int]:
    """Unity's built-in type-tree string table, reversed into name -> offset.

    Unity writes a type tree's field and type names as offsets: into the local
    string buffer, or — with the high bit set — into this table it already has
    in memory. Real bundles use it for nearly every name, so this writer does
    too; a local copy would work, and would also be the first structural
    difference from Unity's own output that a diff would show.
    """
    from UnityPy.helpers.Tpk import get_common_strings

    reverse: dict[str, int] = {}
    for offset, text in get_common_strings().items():
        reverse.setdefault(text, offset)
    return reverse


def _type_tree(node: Any, common: dict[str, int]) -> bytes:
    """Serialize one class's type tree, as the metadata's per-type payload.

    The node is UnityPy's own tree object; this repository treats that
    library as an untyped boundary (see pyproject), so its shape is Any here.
    """
    nodes: list[tuple[Any, int]] = []

    def walk(current: Any, level: int) -> None:
        nodes.append((current, level))
        for child in current.m_Children:
            walk(child, level + 1)

    walk(node, 0)

    strings = bytearray()
    offsets: dict[str, int] = {}

    def string_offset(text: str) -> int:
        if text in common:
            return common[text] | 0x80000000
        if text not in offsets:
            offsets[text] = len(strings)
            strings.extend(text.encode("utf-8") + b"\x00")
        return offsets[text]

    body = bytearray()
    for index, (current, level) in enumerate(nodes):
        # An array node is flagged, not inferred from its name, because the
        # reader uses the flag to decide the size-prefixed layout.
        type_flags = 1 if current.m_Type == "Array" else 0
        body.extend(
            struct.pack(
                "<HBBIIiiIQ",
                current.m_Version,
                level,
                type_flags,
                string_offset(current.m_Type),
                string_offset(current.m_Name),
                current.m_ByteSize if current.m_ByteSize is not None else -1,
                index,
                current.m_MetaFlag or 0,
                0,
            )
        )
    return struct.pack("<II", len(nodes), len(strings)) + bytes(body) + bytes(strings)


def _align(data: bytearray, boundary: int) -> None:
    data.extend(b"\x00" * ((-len(data)) % boundary))


def _serialize(
    objects: list[BundleObject], unity_version: str, target: int, cab: str
) -> _Serialized:
    """Build the SerializedFile metadata and data sections."""
    class_ids: list[int] = []
    for obj in objects:
        if obj.class_id not in class_ids:
            class_ids.append(obj.class_id)

    common = _common_strings()
    trees = {class_id: _node(class_id, unity_version) for class_id in class_ids}

    resource = bytearray()
    for obj in objects:
        if not obj.resource:
            continue
        # Resource offsets are only knowable once every clip has a place, so
        # the object is patched here rather than by whoever described it.
        target_field: Any = obj.fields
        for key in obj.resource_field[:-1]:
            target_field = target_field[key]
        streamed = target_field[obj.resource_field[-1]]
        streamed["m_Source"] = f"archive:/{cab}/{cab}.resource"
        streamed["m_Offset"] = len(resource)
        streamed["m_Size"] = len(obj.resource)
        resource.extend(obj.resource)
        _align(resource, 16)

    data = bytearray()
    entries: list[tuple[int, int, int, int]] = []
    for index, obj in enumerate(objects, start=1):
        _align(data, 8)
        start = len(data)
        data.extend(_write_object(obj.fields, trees[obj.class_id]))
        entries.append((index, start, len(data) - start, class_ids.index(obj.class_id)))

    metadata = bytearray()
    metadata.extend(unity_version.encode("utf-8") + b"\x00")
    metadata.extend(struct.pack("<i", target))
    metadata.append(1)  # type trees are written; the game's own bundles do
    metadata.extend(struct.pack("<I", len(class_ids)))
    for class_id in class_ids:
        metadata.extend(struct.pack("<ibh", class_id, 0, -1))
        # The old type hash Unity stores is a compatibility record for the
        # tree that follows it. The tree is written in full, so a reader has
        # the layout regardless; this is left zero deliberately.
        metadata.extend(bytes(16))
        metadata.extend(_type_tree(trees[class_id], common))
        metadata.extend(struct.pack("<I", 0))  # no type dependencies
    metadata.extend(struct.pack("<I", len(entries)))
    for path_id, start, size, type_index in entries:
        _align(metadata, 4)
        metadata.extend(struct.pack("<qQii", path_id, start, size, type_index))
    metadata.extend(struct.pack("<I", 0))  # script types
    metadata.extend(struct.pack("<I", 0))  # externals
    metadata.extend(struct.pack("<I", 0))  # reference types
    metadata.extend(b"\x00")  # userInformation

    return _Serialized(bytes(metadata), bytes(data), bytes(resource))


def _serialized_file(serialized: _Serialized) -> bytes:
    """Wrap metadata and data in the SerializedFile header (version 22)."""
    header_size = 48
    metadata_size = len(serialized.metadata)
    data_offset = header_size + metadata_size
    data_offset += (-data_offset) % 8
    file_size = data_offset + len(serialized.data)
    header = bytearray()
    # The four legacy fields are zero from version 22 on; the real values live
    # in the extended header below, which is where a reader of a modern file
    # looks. Both are big-endian: only the metadata that follows honours the
    # endianness byte.
    header.extend(struct.pack(">IIII", 0, 0, SERIALIZED_VERSION, 0))
    header.append(0)  # little-endian metadata
    header.extend(bytes(3))
    header.extend(struct.pack(">IqqQ", metadata_size, file_size, data_offset, 0))
    body = bytearray(header)
    body.extend(serialized.metadata)
    body.extend(b"\x00" * (data_offset - len(body)))
    body.extend(serialized.data)
    return bytes(body)


def _cab_name(bundle_name: str) -> str:
    """A stable CAB id.

    Unity generates one per build; deriving it from the bundle name keeps two
    builds of unchanged inputs byte-identical, which is what makes a rebuild
    reviewable in git.
    """
    return "CAB-" + hashlib.md5(bundle_name.encode("utf-8")).hexdigest()  # noqa: S324


def _container(revision: str, nodes: list[tuple[str, bytes]]) -> bytes:
    """Assemble the UnityFS archive around one or more directory nodes."""
    payload = bytearray()
    directory: list[tuple[int, int, int, str]] = []
    for name, content in nodes:
        # Flag 4 marks the serialized file; the resource stream beside it
        # carries none, exactly as the directory of a Unity-built bundle does.
        flags = 0 if name.endswith(".resource") else 4
        directory.append((len(payload), len(content), flags, name))
        payload.extend(content)

    table = bytearray(bytes(16))  # the uncompressed-data hash Unity leaves zero
    table.extend(struct.pack(">I", 1))
    table.extend(struct.pack(">IIH", len(payload), len(payload), 0))  # one stored block
    table.extend(struct.pack(">I", len(directory)))
    for offset, size, flags, name in directory:
        table.extend(struct.pack(">QQI", offset, size, flags))
        table.extend(name.encode("utf-8") + b"\x00")

    header = bytearray(b"UnityFS\x00")
    header.extend(struct.pack(">I", 8))  # archive format 8, as the game ships
    header.extend(b"5.x.x\x00")
    header.extend(revision.encode("utf-8") + b"\x00")
    size_offset = len(header)
    header.extend(bytes(20))
    header.extend(b"\x00" * ((-len(header)) % 16))
    # Flags 0x40: the block table sits at the head of the archive, uncompressed.
    struct.pack_into(
        ">QIII",
        header,
        size_offset,
        len(header) + len(table) + len(payload),
        len(table),
        len(table),
        0x40,
    )
    return bytes(header) + bytes(table) + bytes(payload)


def build_bundle(
    objects: list[BundleObject],
    unity_version: str,
    bundle_name: str,
    target: int = STANDALONE_WINDOWS64,
) -> bytes:
    """Write a loadable `.unity3d` containing `objects`, with no editor.

    The class-142 `AssetBundle` object is added here rather than by the
    caller: it is the container the runtime asks for, its `m_Container` table
    is what makes each asset reachable by name, and a bundle that lacks it is
    the exact failure every gate in this repository exists to catch.
    """
    if not objects:
        raise PipelineError("a bundle needs at least one asset")
    counts = Counter(obj.name for obj in objects)
    duplicates = {stem for stem, count in counts.items() if count > 1}
    if duplicates:
        raise PipelineError(
            "two assets would answer the same name: " + ", ".join(sorted(duplicates))
        )

    cab = _cab_name(bundle_name)
    # The AssetBundle object is written first so it takes path id 1, as Unity's
    # own bundles do, and so every container entry can name a later id.
    container = [
        (
            obj.name.lower(),
            {
                "preloadIndex": 0,
                "preloadSize": 0,
                "asset": {"m_FileID": 0, "m_PathID": index},
            },
        )
        for index, obj in enumerate(objects, start=2)
    ]
    bundle_object = BundleObject(
        class_id=ASSET_BUNDLE,
        name=bundle_name,
        fields={
            "m_Name": bundle_name,
            "m_PreloadTable": [],
            "m_Container": container,
            "m_MainAsset": {
                "preloadIndex": 0,
                "preloadSize": 0,
                "asset": {"m_FileID": 0, "m_PathID": 0},
            },
            "m_RuntimeCompatibility": 1,
            "m_AssetBundleName": bundle_name,
            "m_Dependencies": [],
            "m_IsStreamedSceneAssetBundle": False,
            "m_ExplicitDataLayout": 0,
            "m_PathFlags": 7,
            "m_SceneHashes": [],
        },
    )
    serialized = _serialize([bundle_object, *objects], unity_version, target, cab)
    nodes = [(cab, _serialized_file(serialized))]
    if serialized.resource:
        nodes.append((f"{cab}.resource", serialized.resource))
    return _container(unity_version, nodes)


# -- assets -----------------------------------------------------------------
#
# One constructor per class this backend can write. Each returns the object in
# the shape its type tree expects; the values that are not obvious were read
# back out of a bundle a real editor built from the same source file, so the
# defaults are Unity's, not invented (docs/research/research-provenance.md).

# FMOD's sample-rate table, indexed by the sample header's 4-bit field. A rate
# outside it needs a frequency chunk; the pipeline rejects it instead and says
# how to resample, because a silently retuned clip is worse than a refusal.
FSB5_FREQUENCIES = {
    8000: 1,
    11000: 2,
    11025: 3,
    16000: 4,
    22050: 5,
    24000: 6,
    32000: 7,
    44100: 8,
    48000: 9,
    96000: 10,
}
FSB5_PCM16 = 2
AUDIO_PCM = 0
TEXTURE_RGBA32 = 4

# VertexData always declares the engine's full channel table and leaves the
# slots a mesh does not use zeroed. The count and the slot order were read out
# of `Data/Bundles/Standalone/Entities/trees` in the installed game with
# UnityPy (research-provenance.md, "Mesh finding"), not from a wiki.
MESH_CHANNELS = 14
CHANNEL_POSITION = 0
CHANNEL_NORMAL = 1
CHANNEL_UV0 = 4
VERTEX_FORMAT_FLOAT = 0
INDEX_FORMAT_UINT16 = 0
INDEX_FORMAT_UINT32 = 1
TOPOLOGY_TRIANGLES = 0
# PhysX cooking flags as the game's own meshes carry them; a MeshCollider
# built from this mesh cooks at load rather than reading a baked blob.
MESH_COOKING_OPTIONS = 30


def text_asset(name: str, text: str) -> BundleObject:
    """A TextAsset: the mod's own data files, readable with `LoadAsset<TextAsset>`."""
    return BundleObject(TEXT_ASSET, name, {"m_Name": name, "m_Script": text})


def texture_2d(name: str, png: Path, readable: bool = False) -> BundleObject:
    """A Texture2D from a PNG, uncompressed RGBA32 with its pixels inline.

    Unity streams texture pixels into a side file and generates mip maps; both
    are optimisations, and neither is required for the runtime to accept the
    texture. Inline `image data` with `m_StreamData` empty is the shape every
    Unity reader (including the engine's own) treats as complete.

    `readable` keeps a CPU copy of the pixels, which is Unity's own default of
    off: it doubles the texture's memory and only a mod that reads pixels from
    script needs it.
    """
    require_capability("pillow")
    from PIL import Image

    try:
        with Image.open(png) as handle:
            image = handle.convert("RGBA")
            width, height = image.size
            # Unity's first row is the bottom one; a texture written top-down
            # loads fine and renders upside down, which no gate would catch.
            pixels = image.transpose(Image.FLIP_TOP_BOTTOM).tobytes()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        # DecompressionBombError subclasses Exception directly, and some decode
        # paths raise ValueError, so OSError alone let both escape as tracebacks.
        raise PipelineError(f"cannot read texture {png}: {exc}") from exc

    return BundleObject(
        TEXTURE_2D,
        name,
        {
            "m_Name": name,
            "m_ForcedFallbackFormat": 4,
            "m_DownscaleFallback": False,
            "m_IsAlphaChannelOptional": False,
            "m_Width": width,
            "m_Height": height,
            "m_CompleteImageSize": len(pixels),
            "m_MipsStripped": 0,
            "m_TextureFormat": TEXTURE_RGBA32,
            "m_MipCount": 1,
            "m_IsReadable": readable,
            "m_IsPreProcessed": False,
            "m_IgnoreMipmapLimit": False,
            "m_MipmapLimitGroupName": "",
            "m_StreamingMipmaps": False,
            "m_StreamingMipmapsPriority": 0,
            "m_ImageCount": 1,
            "m_TextureDimension": 2,
            "m_TextureSettings": {
                "m_FilterMode": 1,
                "m_Aniso": 1,
                "m_MipBias": 0.0,
                "m_WrapU": 0,
                "m_WrapV": 0,
                "m_WrapW": 0,
            },
            "m_LightmapFormat": 0,
            "m_ColorSpace": 1,
            "m_PlatformBlob": [],
            "image data": pixels,
            "m_StreamData": {"offset": 0, "size": 0, "path": ""},
        },
    )


def _vertex_channels(has_uv: bool) -> list[dict[str, int]]:
    """The full channel table, with only the slots this writer fills set."""
    channels = [
        {"stream": 0, "offset": 0, "format": 0, "dimension": 0} for _ in range(MESH_CHANNELS)
    ]
    channels[CHANNEL_POSITION] = {
        "stream": 0,
        "offset": 0,
        "format": VERTEX_FORMAT_FLOAT,
        "dimension": 3,
    }
    channels[CHANNEL_NORMAL] = {
        "stream": 0,
        "offset": 12,
        "format": VERTEX_FORMAT_FLOAT,
        "dimension": 3,
    }
    if has_uv:
        channels[CHANNEL_UV0] = {
            "stream": 0,
            "offset": 24,
            "format": VERTEX_FORMAT_FLOAT,
            "dimension": 2,
        }
    return channels


def mesh(name: str, source: Path) -> BundleObject:
    """A Mesh from any geometry file trimesh reads: glTF, GLB, OBJ, STL, PLY.

    The interchange file is the editable source and this is its Unity form —
    positions, normals and, when the file has them, UV0, interleaved in one
    vertex stream with 16- or 32-bit indices. The layout is the one the game's
    own meshes use, read out of a shipped bundle rather than reconstructed
    from notes (`docs/research/research-provenance.md`).

    Two conversions happen here, and both are the kind of silent wrong that no
    offline gate catches, so they are done rather than left to the author:

    - glTF, OBJ, STL and PLY are right-handed; Unity is left-handed. X is
      negated and triangle winding reversed, which is the same conversion
      Unity's own importers and every glTF runtime for Unity apply. A mesh
      converted without it loads perfectly and is mirrored.
    - the file must be Y-up. A Z-up export arrives lying on its face, which is
      an exporter setting, not something this can detect from the geometry.

    What it does not write: tangents, vertex colours, blend shapes, skinning,
    and more than one submesh. A normal-mapped material needs tangents, and a
    material needs a shader, which is the wall in `docs/bundles/no-unity.md`.
    """
    require_capability("trimesh")
    import logging

    import trimesh

    # Without scipy, trimesh's vertex-normal path prints an ImportError
    # traceback to stderr, falls back, and succeeds. Its logger has no handler,
    # so Python's last-resort one prints it; a NullHandler keeps a working code
    # path from reading as a crash in every report this writer appears in.
    logging.getLogger("trimesh").addHandler(logging.NullHandler())

    try:
        loaded = trimesh.load(str(source), force="mesh")
    except Exception as exc:  # noqa: BLE001 - trimesh raises many unrelated types
        raise PipelineError(f"cannot read mesh {source}: {exc}") from exc

    vertices = getattr(loaded, "vertices", None)
    faces = getattr(loaded, "faces", None)
    if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
        raise PipelineError(
            f"{source.name} has no triangles to write. `shamway check-mesh {source}` "
            "reports what the file actually contains."
        )
    if len(vertices) > 0xFFFFFFFF:
        raise PipelineError(f"{source.name} has {len(vertices)} vertices; Unity's limit is 2^32")

    import numpy

    positions = numpy.asarray(vertices, dtype="<f4").reshape(-1, 3).copy()
    normals = numpy.asarray(loaded.vertex_normals, dtype="<f4").reshape(-1, 3).copy()
    # Right-handed to left-handed: negate X, then reverse each triangle so its
    # faces still point outward. Doing only one of the two is a mesh whose
    # normals and geometry disagree — lit inside-out in the client.
    positions[:, 0] *= -1.0
    normals[:, 0] *= -1.0
    triangles = numpy.asarray(faces, dtype="<u4")[:, ::-1]

    uv = getattr(getattr(loaded, "visual", None), "uv", None)
    has_uv = uv is not None and len(uv) == len(positions)
    stride = 32 if has_uv else 24
    stream = numpy.zeros((len(positions), stride // 4), dtype="<f4")
    stream[:, 0:3] = positions
    stream[:, 3:6] = normals
    if has_uv:
        stream[:, 6:8] = numpy.asarray(uv, dtype="<f4").reshape(-1, 2)

    wide = len(positions) > 0xFFFF
    indices = triangles.astype("<u4" if wide else "<u2").tobytes()
    low = positions.min(axis=0)
    high = positions.max(axis=0)
    centre = (high + low) / 2.0
    extent = (high - low) / 2.0
    aabb = {
        "m_Center": {"x": float(centre[0]), "y": float(centre[1]), "z": float(centre[2])},
        "m_Extent": {"x": float(extent[0]), "y": float(extent[1]), "z": float(extent[2])},
    }

    return BundleObject(
        MESH,
        name,
        {
            "m_Name": name,
            "m_SubMeshes": [
                {
                    "firstByte": 0,
                    "indexCount": int(triangles.size),
                    "topology": TOPOLOGY_TRIANGLES,
                    "baseVertex": 0,
                    "firstVertex": 0,
                    "vertexCount": len(positions),
                    "localAABB": aabb,
                }
            ],
            "m_Shapes": {"vertices": [], "shapes": [], "channels": [], "fullWeights": []},
            "m_BindPose": [],
            "m_BoneNameHashes": [],
            "m_RootBoneNameHash": 0,
            "m_BonesAABB": [],
            "m_VariableBoneCountWeights": {"m_Data": []},
            "m_MeshCompression": 0,
            # Unity's own default is off, but a mesh a mod ships is one another
            # mod or a Harmony patch may want to read, and the game's shipped
            # meshes carry it on.
            "m_IsReadable": True,
            "m_KeepVertices": True,
            "m_KeepIndices": True,
            "m_IndexFormat": INDEX_FORMAT_UINT32 if wide else INDEX_FORMAT_UINT16,
            "m_IndexBuffer": indices,
            "m_VertexData": {
                "m_VertexCount": len(positions),
                "m_Channels": _vertex_channels(has_uv),
                "m_DataSize": stream.tobytes(),
            },
            "m_CompressedMesh": _empty_compressed_mesh(),
            "m_LocalAABB": aabb,
            "m_MeshUsageFlags": 0,
            "m_CookingOptions": MESH_COOKING_OPTIONS,
            "m_BakedConvexCollisionMesh": b"",
            "m_BakedTriangleCollisionMesh": b"",
            "m_MeshMetrics[0]": 1.0,
            "m_MeshMetrics[1]": 1.0,
            "m_StreamData": {"offset": 0, "size": 0, "path": ""},
        },
    )


def _empty_compressed_mesh() -> dict[str, Any]:
    """`m_CompressedMesh` with every vector empty: this writer never packs one."""
    ranged = {"m_NumItems": 0, "m_Range": 0.0, "m_Start": 0.0, "m_Data": [], "m_BitSize": 0}
    plain = {"m_NumItems": 0, "m_Data": [], "m_BitSize": 0}
    return {
        "m_Vertices": dict(ranged),
        "m_UV": dict(ranged),
        "m_Normals": dict(ranged),
        "m_Tangents": dict(ranged),
        "m_Weights": dict(plain),
        "m_NormalSigns": dict(plain),
        "m_TangentSigns": dict(plain),
        "m_FloatColors": dict(ranged),
        "m_BoneIndices": dict(plain),
        "m_Triangles": dict(plain),
        "m_UVInfo": 0,
    }


def _fsb5_pcm16(pcm: bytes, channels: int, rate: int) -> bytes:
    """Wrap raw PCM in the FMOD sound bank Unity's audio resource always is.

    An AudioClip object carries no samples: it carries an offset into a
    resource stream that the runtime hands to FMOD, and FMOD reads an FSB5
    container there. The layout below was read out of the `.resource` stream of
    a bundle this repository's own editor built (`FSB5`, version 1, one sample,
    the 64-bit sample header's frequency/channel/offset/sample-count fields).
    """
    index = FSB5_FREQUENCIES.get(rate)
    if index is None:
        supported = ", ".join(str(value) for value in sorted(FSB5_FREQUENCIES))
        raise PipelineError(
            f"{rate} Hz cannot be written without a frequency chunk; FMOD's table "
            f"holds {supported}. Resample first: "
            "ffmpeg -i in.wav -ar 44100 out.wav"
        )
    if channels not in (1, 2):
        raise PipelineError(f"{channels}-channel audio needs a channel chunk; write mono or stereo")
    samples = len(pcm) // (2 * channels)
    sample_header = struct.pack("<Q", (index << 1) | ((channels - 1) << 5) | (samples << 34))
    # FMOD reads the data section at 60 + sampleHeadersSize + nameTableSize;
    # Unity pads that start to 32, so the same padding is applied here.
    padding = (-(60 + len(sample_header))) % 32
    headers_size = len(sample_header) + padding
    data = pcm + b"\x00" * ((-len(pcm)) % 32)
    header = b"FSB5" + struct.pack("<IIIIII", 1, 1, headers_size, 0, len(data), FSB5_PCM16)
    header += struct.pack("<I", 1) + bytes(4) + bytes(16) + bytes(8)
    return header + sample_header + bytes(padding) + data


def audio_clip(name: str, wav: Path) -> BundleObject:
    """An AudioClip from a mono/stereo 16-bit WAV, stored uncompressed.

    `shamway check-sound` gates the clip itself; this only carries it. Unity
    would encode to Vorbis, which needs an encoder and changes the samples a
    listener signed off on. PCM is larger and is exactly what was authored.
    """
    import wave

    try:
        with wave.open(str(wav), "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            width = handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
    except (OSError, wave.Error) as exc:
        raise PipelineError(f"cannot read clip {wav}: {exc}") from exc
    if width != 2:
        raise PipelineError(
            f"{wav.name} is {width * 8}-bit; write 16-bit PCM "
            "(ffmpeg -i in.wav -c:a pcm_s16le out.wav)"
        )
    samples = len(frames) // (2 * channels)
    return BundleObject(
        AUDIO_CLIP,
        name,
        {
            "m_Name": name,
            "m_LoadType": 0,
            "m_Channels": channels,
            "m_Frequency": rate,
            "m_BitsPerSample": 16,
            "m_Length": samples / rate if rate else 0.0,
            "m_IsTrackerFormat": False,
            "m_Ambisonic": False,
            "m_SubsoundIndex": 0,
            "m_PreloadAudioData": False,
            "m_LoadInBackground": False,
            "m_Legacy3D": True,
            "m_Resource": {"m_Source": "", "m_Offset": 0, "m_Size": 0},
            "m_CompressionFormat": AUDIO_PCM,
        },
        resource=_fsb5_pcm16(frames, channels, rate),
        resource_field=("m_Resource",),
    )


# -- the source directory ---------------------------------------------------

# What a file below the bundle source folder becomes. The extension decides,
# because the alternative is a per-asset declaration file that drifts from the
# folder it describes. Anything else is refused by name rather than skipped
# quietly: a source file nobody built is exactly the kind of silence this
# pipeline exists to remove.
ASSET_KINDS: dict[str, str] = {
    ".png": "Texture2D",
    ".wav": "AudioClip",
    ".txt": "TextAsset",
    ".json": "TextAsset",
    ".csv": "TextAsset",
    ".glb": "Mesh",
    ".gltf": "Mesh",
    ".obj": "Mesh",
    ".stl": "Mesh",
    ".ply": "Mesh",
}
MESH_SUFFIXES = tuple(suffix for suffix, kind in ASSET_KINDS.items() if kind == "Mesh")
IGNORED_NAMES = {".gitkeep", ".gitignore"}
IGNORED_SUFFIXES = {".meta"}


def collect_sources(source_dir: Path) -> list[Path]:
    """Every buildable file below `source_dir`, sorted for a reproducible build."""
    if not source_dir.is_dir():
        raise PipelineError(
            f"no bundle source directory at {source_dir}. It is the folder whose "
            "contents become the bundle; create it and put the mod's textures, "
            "clips and text files in it."
        )
    found: list[Path] = []
    unknown: list[str] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
            continue
        if path.suffix.lower() not in ASSET_KINDS:
            unknown.append(str(path.relative_to(source_dir)))
            continue
        found.append(path)
    if unknown:
        kinds = ", ".join(sorted(ASSET_KINDS))
        raise PipelineError(
            "this backend cannot build " + ", ".join(unknown[:5]) + f"; it writes {kinds}. "
            "A prefab, material or shader still needs Unity, because a shader in a "
            "bundle is compiled platform bytecode — see 'shamway docs no-unity'."
        )
    if not found:
        raise PipelineError(f"{source_dir} holds no assets to build")
    return found


def object_for(path: Path) -> BundleObject:
    """Turn one source file into the object its extension names."""
    stem = path.stem
    suffix = path.suffix.lower()
    if suffix == ".png":
        return texture_2d(stem, path)
    if suffix == ".wav":
        return audio_clip(stem, path)
    if suffix in MESH_SUFFIXES:
        return mesh(stem, path)
    try:
        return text_asset(stem, path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise PipelineError(f"cannot read text asset {path}: {exc}") from exc


def render_manifest(bundle_name: str, assets: list[str]) -> str:
    """Unity's own manifest shape, so one validator serves both backends.

    `validate` reads membership from the tracked manifest and knows nothing
    about which backend produced the bundle. Emitting the same file keeps the
    stem, case and reference gates working unchanged.
    """
    lines = [
        "ManifestFileVersion: 0",
        f"AssetBundleManifest: {bundle_name}",
        "Assets:",
        *[f"- {asset}" for asset in assets],
        "Dependencies: []",
    ]
    return "\n".join(lines) + "\n"


def pack_directory(
    source_dir: Path, bundle_name: str, unity_version: str, target: int = STANDALONE_WINDOWS64
) -> tuple[bytes, str]:
    """Build a bundle from a directory of source files, with no editor.

    Returns the bundle bytes and the manifest text that records what went into
    it, which is the pair `build` stages together.
    """
    sources = collect_sources(source_dir)
    objects = [object_for(path) for path in sources]
    bundle = build_bundle(objects, unity_version, bundle_name, target)
    members = [f"{source_dir.name}/{path.relative_to(source_dir).as_posix()}" for path in sources]
    return bundle, render_manifest(bundle_name, members)
