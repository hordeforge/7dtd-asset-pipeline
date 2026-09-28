"""Property-based fuzzing of the untrusted-input parsers.

Every harness here crosses a trust boundary, which is what makes them worth
running under a generator rather than as a handful of hand-written cases:

- `unityfs.bundle_info` maps a `unityz info --json` report onto `BundleInfo`.
  unityz is a separately versioned reader speaking to the Python gate over a
  pipe, so every field is foreign, and a malformed report must end as an
  actionable `PipelineError` rather than a traceback from the mapping layer.
- `references` parses the mod's own `Config/**.xml`, `ModInfo.xml` and
  tracked manifest, all of which arrive from a modlet this repository did not
  write.
- `shader_blob` reads DXBC shader containers: a chunk table, an SHDR token
  stream, an RDEF constant-buffer table and an ISGN signature, each addressed
  by offsets and lengths the container itself declares. The bytes come from a
  compiler or from a bundle, so every one of those fields is input, and a
  truncated or mis-declared container must end as a `PipelineError` naming the
  field rather than as a `struct.error` from the middle of the module.
- `block_compress.decode` reads a BC1/BC3 block stream, whose length has to
  agree with the dimensions it is decoded at, with no third field to catch it.

A fuzzer proves a bug exists; the assertions here are what make a *correct*
parser's output into a liveness failure when it stops being one, so the
harness reports a broken invariant rather than a silent drift. Seeds are real
shapes from the parsers' own tests, not zero-filled input: a generator that
never reaches the accepting branch proves nothing about it.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hypothesis import example, given, settings
from hypothesis import strategies as st

from sevendtd_asset_pipeline import block_compress, shader_blob
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.references import (
    MODFOLDER,
    AssetReference,
    manifest_assets,
    parse_reference,
    read_mod_info,
)
from sevendtd_asset_pipeline.unityfs import ASSET_BUNDLE_CLASS_ID, bundle_info

# Neither parser touches the filesystem, so the subjects are names, not files.
BUNDLE = Path("fuzz-bundle.unity3d")
SOURCE = Path("Config/items.xml")

# Where a DXBC container's chunk offset table starts, per the format layout the
# builder above reproduces. The reader derives its own from the module.
DXBC_CHUNK_TABLE = 0x20

# Enough structure to reach every branch of every parser without shrinking the
# inputs so far that a malformed node list or chunk table is never generated.
MAX_EXAMPLES = 400

json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=16),
    st.floats(allow_nan=True, allow_infinity=True),
)
json_values = st.recursive(
    json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=6), children, max_size=4),
    ),
    max_leaves=12,
)
json_objects = st.dictionaries(st.text(max_size=8), json_values, min_size=0, max_size=6)

uri_bodies = st.text(max_size=40)
manifest_lines = st.lists(st.text(max_size=24), max_size=8)
mod_info_xml = st.builds(
    lambda body: f"<ModInfo>{body}</ModInfo>",
    st.lists(st.text(max_size=32), max_size=4),
)

# Pure JSON generation almost never builds a report a reader accepts: the
# node list, the SerializedFile metadata and the class IDs each have to be
# present, nested and correctly typed at once. This strategy builds those
# shapes first and then breaks one field at a time, so both the accepting
# branch and every rejection it must be able to reach are sampled directly.
REVISIONS = ("2022.3.62f2", "2021.3.1f1")
# Each field is generated valid more often than not: a report only reaches the
# accepting branch when every field is valid at once, so an all-broken strategy
# would fuzz the rejection path and never the one the gate runs on.
class_ids = st.one_of(
    st.lists(st.integers(min_value=0, max_value=2048), max_size=4),
    st.lists(st.one_of(st.text(max_size=3), st.none(), st.booleans()), max_size=3),
    st.text(max_size=4),
    st.none(),
)
revisions = st.one_of(
    st.sampled_from(REVISIONS),
    st.text(max_size=8),
    st.integers(),
    st.just(""),
)
serialized_metadata = st.fixed_dictionaries(
    {},
    optional={
        "unity": revisions,
        "class_ids": class_ids,
        "path": st.text(max_size=4),
    },
)
node_values = st.one_of(
    st.builds(
        lambda metadata: {"path": "CAB-0123456789abcdef", "serialized": metadata},
        serialized_metadata,
    ),
    st.builds(
        lambda revision, ids: {"serialized": {"unity": revision, "class_ids": ids}},
        st.sampled_from(REVISIONS),
        st.lists(st.integers(min_value=0, max_value=2048), max_size=4),
    ),
    st.fixed_dictionaries({}, optional={"serialized": serialized_metadata}),
    st.just({"serialized": None}),
    st.just({}),
    st.text(max_size=4),
    st.none(),
)
unityz_reports = st.builds(
    lambda report_type, version, nodes: {
        "type": report_type,
        "version": version,
        "nodes_list": nodes,
    },
    st.sampled_from(("UnityFS", "UnityFS", "UnityFS", "SerializedFile", "", 7)),
    st.one_of(st.integers(min_value=-2, max_value=64), st.text(max_size=3), st.none()),
    st.lists(node_values, max_size=3),
)
reports = st.one_of(json_objects, unityz_reports)


# A DXBC container in the layout the format specifies: the fourcc, a 16-byte
# digest, the version word, the total size, the chunk count at 0x1C, one dword
# per chunk offset from 0x20, then the chunks. Random bytes never reach the
# accepting branch, because a valid container needs its table, its offsets and
# its sizes to agree at once, so the seeds are built from that layout and
# `broken` then replaces one dword: that is what turns a good count, offset or
# size into the four-billion case the bound checks exist for.
def dxbc_container(chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = bytearray()
    offsets = []
    for fourcc, payload in chunks:
        offsets.append(DXBC_CHUNK_TABLE + 4 * len(chunks) + len(body))
        body += fourcc + struct.pack("<I", len(payload)) + payload
    total = DXBC_CHUNK_TABLE + 4 * len(chunks) + len(body)
    header = shader_blob.DXBC_MAGIC + b"\x00" * 16
    header += struct.pack("<3I", 1, total, len(chunks))
    header += b"".join(struct.pack("<I", offset) for offset in offsets)
    return bytes(header) + bytes(body)


def dcl(opcode: int, operand: int) -> bytes:
    """One two-dword declaration token, as a compiler emits it."""
    return struct.pack("<I", opcode | (2 << 24)) + struct.pack("<I", operand)


def shdr_payload(*tokens: bytes) -> bytes:
    """An SHDR/SHEX chunk: version, dword count, then the token stream."""
    stream = b"".join(tokens)
    return struct.pack("<2I", 1, 2 + len(stream) // 4) + stream


# `dcl_temps 7` and `dcl_constantbuffer` are the two declarations the header
# this module builds is read back from, so a container carrying them is the
# shape the accepting branch actually sees.
REAL_CHUNKS = (
    (b"SHDR", shdr_payload(dcl(104, 7), dcl(89, 0), dcl(90, 0))),
    # One ISGN element: the count and the header word, a 24-byte element whose
    # name offset points at the string table that follows it.
    (b"ISGN", struct.pack("<4I", 1, 8, 32, 0) + b"\x00" * 16 + b"POSITION\x00"),
    (b"RDEF", struct.pack("<2I", 0, 0)),
)
fourccs = st.sampled_from((b"SHDR", b"SHEX", b"ISGN", b"RDEF", b"XXXX", b"\xff\xfe\x00\x01"))
chunk_lists = st.lists(st.tuples(fourccs, st.binary(max_size=32)), max_size=3)
containers = st.builds(dxbc_container, chunk_lists)
# One dword anywhere in the container replaced with an arbitrary one: the count
# at 0x1C, an offset in the table, a size in a chunk header, or a length the
# chunk body itself declares.
broken = containers.flatmap(
    lambda container: st.tuples(
        st.integers(min_value=0, max_value=max(0, len(container) // 4 - 1)),
        st.integers(min_value=0, max_value=0xFFFFFFFF),
    ).map(
        lambda pick: b"".join(
            struct.pack("<I", pick[1]) if index == pick[0] else container[4 * index : 4 * index + 4]
            for index in range(len(container) // 4)
        )
    )
)
dxbc_containers = st.one_of(containers, broken, st.binary(max_size=96))

# A block stream, with the two fields a decoder has to check it against: the
# Unity texture format and the dimensions it is being read at.
block_streams = st.tuples(
    st.binary(max_size=64),
    st.sampled_from((block_compress.TEXTURE_DXT1, block_compress.TEXTURE_DXT5, 7, 99)),
    st.integers(min_value=0, max_value=16),
    st.integers(min_value=0, max_value=16),
)


def unityz_report(revision: str, class_ids: list[object]) -> dict[str, object]:
    """The report shape unityz prints for a real generated bundle."""
    return {
        "type": "UnityFS",
        "version": 8,
        "nodes_list": [
            {
                "path": "CAB-0123456789abcdef0123456789abcdef",
                "serialized": {"unity": revision, "class_ids": class_ids},
            }
        ],
    }


def multi_node_report(revisions: list[str], class_ids: list[object]) -> dict[str, object]:
    """One UnityFS container over several SerializedFiles, as unityz reports it."""
    return {
        "type": "UnityFS",
        "version": 8,
        "nodes_list": [
            {"path": f"CAB-{index:032x}", "serialized": {"unity": rev, "class_ids": class_ids}}
            for index, rev in enumerate(revisions)
        ],
    }


class UnityzReportMappingTests(unittest.TestCase):
    """`unityfs.bundle_info` over arbitrary unityz JSON reports."""

    @example(report=unityz_report("2022.3.62f2", [142, 28]))
    @example(report=unityz_report("", [142]))
    @example(report=unityz_report("2022.3.62f2", [142, "28"]))
    @example(report={"type": "UnityFS", "version": 8, "nodes_list": []})
    @example(report={"type": "UnityFS", "version": 8, "nodes_list": [{}, 7]})
    @example(report={"type": "UnityFS", "nodes_list": [{"serialized": {"unity": "a"}}]})
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(report=reports)
    def test_mapping_is_total_and_its_result_is_well_formed(self, report: dict[str, Any]) -> None:
        try:
            info = bundle_info(report, BUNDLE)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"bundle_info raised {type(exc).__name__} on {report!r}: {exc}")

        self.assertIsInstance(info.unity_version, str)
        self.assertTrue(info.unity_version, f"empty revision accepted from {report!r}")
        self.assertIsInstance(info.archive_format, int)
        self.assertNotIsInstance(info.archive_format, bool)
        self.assertEqual(
            len(set(info.class_ids)),
            len(info.class_ids),
            f"duplicate class IDs survived into {info.class_ids!r}",
        )
        for class_id in info.class_ids:
            self.assertIsInstance(class_id, int)
            self.assertNotIsInstance(class_id, bool)
        self.assertEqual(
            info.has_assetbundle_object,
            ASSET_BUNDLE_CLASS_ID in info.class_ids,
        )
        self.assertIs(info.path, BUNDLE)

    @example(report=multi_node_report(["2022.3.62f2"], [1, 142]))
    @example(report=multi_node_report(["2022.3.62f2", "2022.3.62f2"], [1, 142]))
    # Two SerializedFiles of different revisions: the case that must be
    # rejected, pinned so the generator cannot simply stop producing it.
    @example(report=multi_node_report(["2022.3.62f2", "2021.3.1f1"], [142]))
    @example(
        report={
            "type": "UnityFS",
            "version": 8,
            "nodes_list": [
                {"serialized": {"unity": "2022.3.62f2", "class_ids": [1, 142]}},
                {"serialized": {"unity": "2022.3.62f2", "class_ids": [142, 28]}},
            ],
        }
    )
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(report=reports)
    def test_a_bundle_is_accepted_only_when_every_node_agrees(self, report: dict[str, Any]) -> None:
        """Two SerializedFiles of one revision merge; anything else is rejected.

        This is the class-142 gate's own precondition, so it is asserted
        rather than left to the fuzzer: a mapping that accepted mixed
        revisions would report a bundle the installed game cannot load.
        """
        try:
            bundle_info(report, BUNDLE)
        except PipelineError:
            return
        nodes = report.get("nodes_list")
        if not isinstance(nodes, list):
            self.fail(f"accepted a report with no node list: {report!r}")
        revisions = {
            node["serialized"]["unity"]
            for node in nodes
            if isinstance(node, dict)
            and isinstance(node.get("serialized"), dict)
            and isinstance(node["serialized"].get("unity"), str)
        }
        self.assertLessEqual(len(revisions), 1, f"mixed revisions accepted from {report!r}")


class ModReferenceParsingTests(unittest.TestCase):
    """`references` over arbitrary URIs, manifests and ModInfo.xml documents."""

    def setUp(self) -> None:
        # One directory per test rather than per generated example: a fresh
        # TemporaryDirectory per example costs more than the parser it feeds,
        # and these tests already run hundreds of examples.
        self._scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self._scratch.cleanup)
        self._writes = 0

    def _subject(self, name: str, text: str) -> Path:
        self._writes += 1
        path = Path(self._scratch.name) / f"{self._writes:06d}-{name}"
        path.write_text(text, encoding="utf-8")
        return path

    @example(uri="#@modfolder():assets/items.unity3d?myItem")
    @example(uri="#@modfolder(MyMod):assets/items.unity3d?myItem")
    @example(uri="#no-question-mark")
    @example(uri="#?")
    @example(uri="#@modfolder():x?")
    @example(uri="#@modfolder():#?a")
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(uri=uri_bodies)
    def test_uri_parsing_is_total_and_its_result_is_internally_consistent(self, uri: str) -> None:
        try:
            reference = parse_reference(SOURCE, uri)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"parse_reference raised {type(exc).__name__} on {uri!r}: {exc}")

        self.assertIsInstance(reference, AssetReference)
        self.assertEqual(reference.source, SOURCE)
        self.assertEqual(reference.uri, uri)
        body, separator, asset = uri[1:].partition("?")
        self.assertTrue(separator and asset, f"accepted a URI with no asset: {uri!r}")
        self.assertEqual(reference.asset_name, asset)
        self.assertEqual(reference.is_modfolder, MODFOLDER.search(body) is not None)
        if reference.is_modfolder:
            # The token is rewritten away before the path reaches the filesystem.
            self.assertNotIn("@modfolder", reference.bundle_path.lower())
            self.assertTrue(reference.mod_name is None or reference.mod_name)
        else:
            self.assertIsNone(reference.mod_name)
            self.assertEqual(reference.bundle_path, body)
        self.assertEqual(
            reference.asset_stem,
            Path(reference.asset_name.replace("\\", "/")).stem,
        )

    @example(lines=["Assets:", "- shamwayselftest"])
    @example(lines=["Assets:"])
    @example(lines=["- only-a-list"])
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(lines=manifest_lines)
    def test_manifest_parsing_is_total_and_never_returns_empty_entries(
        self, lines: list[str]
    ) -> None:
        manifest = self._subject("manifest.txt", "\n".join(lines))
        try:
            assets = manifest_assets(manifest)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"manifest_assets raised {type(exc).__name__} on {lines!r}: {exc}")
        self.assertTrue(assets, "manifest_assets returned an empty list instead of an error")
        for entry in assets:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.strip(), f"blank manifest entry from {lines!r}")

    @example(document='<ModInfo><Name value="SelfTestMod"/><Version value="1.0.0"/></ModInfo>')
    @example(document="<ModInfo></ModInfo>")
    @example(document='<ModInfo><Name value=""/></ModInfo>')
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(document=mod_info_xml)
    def test_mod_info_parsing_is_total_and_always_names_the_mod(self, document: str) -> None:
        mod_info = self._subject("ModInfo.xml", document)
        try:
            info = read_mod_info(mod_info)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"read_mod_info raised {type(exc).__name__} on {document!r}: {exc}")
        self.assertTrue(info.name.strip(), f"blank mod name accepted from {document!r}")


class DxbcContainerTests(unittest.TestCase):
    """`shader_blob` over arbitrary DXBC containers.

    Every field that decides where a read happens - the chunk count, the chunk
    table, a chunk offset, a chunk size, the SHDR dword count, an RDEF or ISGN
    string offset - is data the container carries, so all of them have to end as
    a `PipelineError` rather than as `struct.error`, `ValueError` or a truncated
    table read as if it were whole.

    The seeds are built to the header layout D3D documents, which is what makes
    the accepting branch reachable at all; a container `vkd3d-compiler`
    actually produced is not among them, because the harness must run on a host
    without the compiler. `tests/test_shader_writer.py` reads real compiled
    containers through the same reader and skips when it is absent.
    """

    @example(container=dxbc_container(list(REAL_CHUNKS)))
    @example(container=dxbc_container([(b"SHDR", shdr_payload(dcl(104, 7)))]))
    @example(container=dxbc_container([]))
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(container=dxbc_containers)
    def test_the_chunk_table_yields_only_payloads_the_container_actually_holds(
        self, container: bytes
    ) -> None:
        try:
            chunks = shader_blob.dxbc_chunks(container)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"dxbc_chunks raised {type(exc).__name__} on {container!r}: {exc}")

        # Pair assertions across the parse: every payload is the slice the chunk
        # table's own offsets and sizes name, so a chunk the header mis-declares
        # is refused rather than handed back short, and no more chunks come back
        # than the count field admitted to.
        declared = struct.unpack_from("<I", container, 0x1C)[0]
        self.assertLessEqual(len(chunks), declared, f"more chunks than declared: {container!r}")
        table = struct.unpack_from(f"<{declared}I", container, DXBC_CHUNK_TABLE)
        expected = {
            container[at : at + 4].decode("ascii", "replace"): container[
                at + 8 : at + 8 + struct.unpack_from("<I", container, at + 4)[0]
            ]
            for at in table
        }
        self.assertEqual(chunks, expected, "chunks do not match the container's own table")

    @example(container=dxbc_container(list(REAL_CHUNKS)))
    @example(container=dxbc_container([(b"SHEX", shdr_payload(dcl(88, 1)))]))
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(container=dxbc_containers)
    def test_walking_the_token_stream_is_total_bounded_and_repeatable(
        self, container: bytes
    ) -> None:
        for read in (shader_blob.temp_register_count, shader_blob.declaration_counts):
            try:
                first = read(container)
            except PipelineError:
                continue
            except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
                self.fail(f"{read.__name__} raised {type(exc).__name__} on {container!r}: {exc}")
            self.assertEqual(read(container), first, f"{read.__name__} is not repeatable")
            for value in first if isinstance(first, tuple) else (first,):
                self.assertIsInstance(value, int)
                self.assertGreaterEqual(value, 0, f"{read.__name__} counted backwards")

        # The walk advances by at least one dword per token or it raises, so a
        # container that comes back with a count has been walked in a bounded
        # number of steps rather than spun on, and no count can exceed the
        # tokens the chunk actually carries.
        code = self._accepted(shader_blob.dxbc_chunks, container) or {}
        code = code.get("SHDR") or code.get("SHEX")
        counts = self._accepted(shader_blob.declaration_counts, container)
        if code is None or len(code) < 8 or counts is None:
            return
        walked = min(struct.unpack_from("<I", code, 4)[0], len(code) // 4)
        self.assertGreaterEqual(walked, 2, "a code chunk with no token stream was walked")
        self.assertLessEqual(sum(counts), walked)

    @example(container=dxbc_container(list(REAL_CHUNKS)))
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(container=dxbc_containers)
    def test_the_cbuffer_table_and_input_signature_name_offsets_that_exist(
        self, container: bytes
    ) -> None:
        layout = self._accepted(shader_blob.compiled_cbuffer_layout, container) or {}
        for buffer, members in layout.items():
            self.assertIsInstance(buffer, str)
            for member, offset in members.items():
                self.assertIsInstance(member, str)
                self.assertIsInstance(offset, int)
                self.assertGreaterEqual(offset, 0, f"{buffer}.{member} is packed before byte 0")

        semantics = self._accepted(shader_blob.input_semantics, container) or []
        for semantic, index in semantics:
            self.assertIsInstance(semantic, str)
            self.assertIsInstance(index, int)
            self.assertGreaterEqual(index, 0)

    @example(container=dxbc_container(list(REAL_CHUNKS)))
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(container=dxbc_containers)
    def test_a_program_data_header_agrees_with_the_bytecode_it_wraps(
        self, container: bytes
    ) -> None:
        payload = self._accepted(shader_blob.program_data, container)
        if payload is None:
            return
        self.assertEqual(payload[shader_blob.PROGRAM_DATA_HEADER :], container)
        # The three count fields are the bytecode's own declarations, not the
        # HLSL author's: a header that disagrees with what it wraps is a
        # mis-bound sub-program that renders wrong instead of failing.
        srv, cbuffer, sampler = shader_blob.declaration_counts(container)
        self.assertEqual((payload[1], payload[2], payload[3]), (srv, cbuffer, sampler))

    @staticmethod
    def _accepted(read: Any, container: bytes) -> Any:
        """`read(container)`, or `None` when it refused the container."""
        try:
            result = read(container)
        except PipelineError:
            return None
        except Exception as exc:
            raise AssertionError(f"raised {type(exc).__name__} on {container!r}: {exc}") from exc
        return result


@unittest.skipUnless(has_capability("numpy"), "the block codec is NumPy arithmetic")
class BlockStreamTests(unittest.TestCase):
    """`block_compress.decode` over arbitrary block streams.

    A block stream carries no dimensions: the length has to agree with the
    width and height it is decoded at, or the decode is a `reshape` of noise.
    """

    @example(stream=(b"\x00" * 8, block_compress.TEXTURE_DXT1, 4, 4))
    @example(stream=(b"\x00" * 16, block_compress.TEXTURE_DXT5, 4, 4))
    @example(stream=(b"\xff\x00\xff\x7f" * 4, block_compress.TEXTURE_DXT1, 8, 4))
    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(stream=block_streams)
    def test_decoding_either_refuses_the_stream_or_returns_the_image_it_was_asked_for(
        self, stream: tuple[bytes, int, int, int]
    ) -> None:
        import numpy

        blocks, texture_format, width, height = stream
        try:
            image = block_compress.decode(blocks, width, height, texture_format)
        except PipelineError:
            return
        except Exception as exc:  # noqa: BLE001 - the finding this harness exists for
            self.fail(f"decode raised {type(exc).__name__} on {len(blocks)} bytes: {exc}")

        self.assertEqual(image.shape, (height, width, 4))
        self.assertEqual(image.dtype, numpy.dtype("uint8"))
        # BC1 has no alpha channel, so it decodes opaque whatever the stream
        # claims; every value it did claim is a colour in 0..255.
        if texture_format == block_compress.TEXTURE_DXT1:
            self.assertTrue((image[..., 3] == 255).all(), "a BC1 block decoded a transparent texel")

    @settings(max_examples=MAX_EXAMPLES, deadline=None)
    @given(
        width=st.integers(min_value=4, max_value=32).map(lambda v: v - v % 4),
        height=st.integers(min_value=4, max_value=32).map(lambda v: v - v % 4),
        alpha=st.booleans(),
    )
    def test_a_round_trip_returns_an_image_of_the_shape_it_was_compressed_from(
        self, width: int, height: int, alpha: bool
    ) -> None:
        import numpy

        generator = numpy.random.default_rng(0)
        pixels = generator.integers(0, 256, (height, width, 4), dtype="uint8")
        blocks, texture_format = block_compress.compress(pixels, alpha=alpha)
        decoded = block_compress.decode(blocks, width, height, texture_format)
        self.assertEqual(decoded.shape, (height, width, 4))
        expected = block_compress.TEXTURE_DXT5 if alpha else block_compress.TEXTURE_DXT1
        self.assertEqual(texture_format, expected)


if __name__ == "__main__":
    unittest.main()
