from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unityfs import _lz4_decompress, inspect_bundle
from sevendtd_asset_pipeline.validation import validate_bundle

from fixtures import build_bundle, lz4_block, lz4_bundle, serialized_file, unityfs_bundle


class BundleCase(unittest.TestCase):
    """A temp home for hand-built bundles, so each test owns its file."""

    def write(self, data: bytes) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "test.unity3d"
        path.write_bytes(data)
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return path


class UnityFsTests(BundleCase):
    def write(self, data: bytes) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "test.unity3d"
        path.write_bytes(data)
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        return path

    def test_reads_revision_and_class_ids(self) -> None:
        info = inspect_bundle(self.write(unityfs_bundle([1, 21, 142])))
        self.assertEqual("2022.3.62f2", info.unity_version)
        self.assertEqual((1, 21, 142), info.class_ids)
        self.assertTrue(info.has_assetbundle_object)

    def test_reads_a_mono_behaviour_script_id(self) -> None:
        """Class 114 carries a 16-byte script ID that shifts every later entry."""
        info = inspect_bundle(self.write(unityfs_bundle([114, 142])))
        self.assertEqual((114, 142), info.class_ids)

    def test_rejects_bundle_without_class_142(self) -> None:
        with self.assertRaisesRegex(PipelineError, "class-142"):
            validate_bundle(self.write(unityfs_bundle([1, 21, 28])))

    def test_rejects_wrong_unity_revision(self) -> None:
        path = self.write(unityfs_bundle([142], "2021.3.1f1"))
        with self.assertRaisesRegex(PipelineError, "installed game uses"):
            validate_bundle(path, "2022.3.62f2")

    def test_rejects_non_bundle(self) -> None:
        with self.assertRaisesRegex(PipelineError, "not a UnityFS"):
            inspect_bundle(self.write(b"not a bundle"))


class Lz4Tests(BundleCase):
    """The LZ4 reader is hand-rolled, so its failure modes get their own pins."""

    def test_decodes_a_compressed_block_end_to_end(self) -> None:
        # Enough class IDs to force literal runs past the nibble cap and match
        # lengths past theirs, including overlapping back-references.
        info = inspect_bundle(self.write(lz4_bundle([142] * 40)))
        self.assertEqual((142,) * 40, info.class_ids)
        self.assertTrue(info.has_assetbundle_object)

    def test_overlapping_matches_replicate_their_source_bytes(self) -> None:
        """An offset shorter than the match re-copies its own output, byte-exact."""
        # Run-length: four literals, then five copies of the last one.
        self.assertEqual(
            b"ABCDDDDDD",
            _lz4_decompress(bytes([0x41]) + b"ABCD" + struct.pack("<H", 1), 9),
        )
        # Period three, exact multiple: "GHI" then nine more from those three.
        self.assertEqual(
            b"GHI" * 4,
            _lz4_decompress(bytes([0x35]) + b"GHI" + struct.pack("<H", 3), 12),
        )
        # Period three, ragged: eight copied bytes truncate the last repetition.
        self.assertEqual(
            b"GHI" + b"GHIGHIGH",
            _lz4_decompress(bytes([0x34]) + b"GHI" + struct.pack("<H", 3), 11),
        )

    def test_an_overlap_only_block_decodes_through_a_real_bundle(self) -> None:
        """A shipped-style payload whose tail expands through an offset-1 match."""
        payload = serialized_file([142])
        head, tail = payload[:-8], payload[-8:]
        self.assertEqual(b"\x00" * 8, tail)  # the padding the match will replicate
        literal_parts = bytearray([(15 << 4) | 4])  # extended literal count + match of 8
        remaining = len(head) - 15
        while remaining >= 255:
            literal_parts.append(255)
            remaining -= 255
        literal_parts.append(remaining)
        block = bytes(literal_parts) + head + struct.pack("<H", 1)
        info = inspect_bundle(self.write(build_bundle([(block, len(payload), 2)], node_size=len(payload))))
        self.assertEqual((142,), info.class_ids)

    def test_rejects_an_invalid_match_offset(self) -> None:
        # One literal, then an offset of zero: nothing can be referenced.
        block = bytes([0x10, ord("A"), 0x00, 0x00])
        with self.assertRaisesRegex(PipelineError, "invalid LZ4 match offset"):
            inspect_bundle(self.write(build_bundle([(block, 64, 2)], node_size=64)))

    def test_rejects_expansion_past_the_declared_size(self) -> None:
        # Four literals, then eight copies of the last one: twelve from four.
        block = bytes([0x44]) + b"AAAA" + struct.pack("<H", 1)
        with self.assertRaisesRegex(PipelineError, "expands beyond its declared size"):
            inspect_bundle(self.write(build_bundle([(block, 4, 2)], node_size=4)))

    def test_rejects_a_size_mismatch(self) -> None:
        block = bytes([0x50]) + b"hello"  # five literals, none missing
        with self.assertRaisesRegex(PipelineError, "LZ4 block size mismatch"):
            inspect_bundle(self.write(build_bundle([(block, 4, 2)], node_size=4)))

    def test_rejects_truncated_literals(self) -> None:
        block = bytes([0xA0, 65, 66])  # token promises ten literals, two follow
        with self.assertRaisesRegex(PipelineError, "truncated.*LZ4 literals"):
            inspect_bundle(self.write(build_bundle([(block, 10, 2)], node_size=10)))


class HeaderTests(BundleCase):
    """Header and table paths: compression selection, layout, truncation."""

    def test_lzma_metadata_is_named_not_swallowed(self) -> None:
        payload = serialized_file([142])
        with self.assertRaisesRegex(PipelineError, "build with LZ4"):
            inspect_bundle(self.write(build_bundle([(payload[:5], len(payload), 1)], node_size=len(payload))))

    def test_unknown_compression_mode_is_named(self) -> None:
        payload = serialized_file([142])
        with self.assertRaisesRegex(PipelineError, "compression mode 60"):
            inspect_bundle(
                self.write(build_bundle([(payload[:5], len(payload), 0x3C)], node_size=len(payload)))
            )

    def test_uncompressed_block_with_the_wrong_declared_size_fails(self) -> None:
        payload = serialized_file([142])
        with self.assertRaisesRegex(PipelineError, "wrong size"):
            inspect_bundle(
                self.write(build_bundle([(payload, len(payload) + 1, 0)], node_size=len(payload)))
            )

    def test_a_block_table_at_the_end_of_the_file_still_parses(self) -> None:
        payload = serialized_file([1, 142])
        bundle = build_bundle(
            [(payload, len(payload), 0)], node_size=len(payload), table_at_end=True
        )
        info = inspect_bundle(self.write(bundle))
        self.assertEqual((1, 142), info.class_ids)

    def test_an_archive_with_no_directory_nodes_is_refused(self) -> None:
        payload = serialized_file([142])
        with self.assertRaisesRegex(PipelineError, "no UnityFS directory nodes"):
            inspect_bundle(
                self.write(
                    build_bundle([(payload, len(payload), 0)], node_size=len(payload), node_count=0)
                )
            )

    def test_a_truncated_table_is_a_bounded_error(self) -> None:
        payload = serialized_file([142])
        bundle = build_bundle([(payload, len(payload), 0)], node_size=len(payload))
        with self.assertRaisesRegex(PipelineError, "truncated Unity bundle"):
            inspect_bundle(self.write(bundle[:-8]))

    def test_a_missing_file_is_a_pipeline_error(self) -> None:
        with self.assertRaisesRegex(PipelineError, "cannot read bundle"):
            inspect_bundle(Path("/nonexistent/dir/bundle.unity3d"))


if __name__ == "__main__":
    unittest.main()
