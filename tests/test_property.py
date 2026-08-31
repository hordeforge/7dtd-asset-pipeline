"""Property-based tests for the UnityFS/SerializedFile reader.

`unityfs` is the parser every gate depends on, and a format reader is exactly
the code where generated inputs pay. The existing `test_unityfs.py` fixtures
are hand-built vectors — good ones, but fixed. Here Hypothesis generates the
inputs: arbitrary bytes, hostile class IDs, hostile file nodes/truncation, and
hostile LZ4 payloads. The property is one and the same — `inspect_bundle` must
either succeed or raise the reader's own bounded `PipelineError`; a leaked
`struct.error` / `IndexError` / `UnicodeDecodeError` / endless-loop is a bug,
because a caller (doctor/status/validate) turns that into a traceback instead
of a named gate failure.

Hypothesis is a dev-group dependency; without it the class is skipped so a bare
`make test` still passes.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from hypothesis import given, settings, strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover - a bare env without the dev group
    HAS_HYPOTHESIS = False


from fixtures import build_bundle, serialized_file, unityfs_bundle

from sevendtd_asset_pipeline import unityfs
from sevendtd_asset_pipeline.errors import PipelineError


def _assert_bounded(case: unittest.TestCase, data: bytes) -> None:
    """`inspect_bundle` on `data` must succeed or raise `PipelineError` only."""
    directory = Path(tempfile.mkdtemp())
    try:
        path = directory / "t.unity3d"
        path.write_bytes(data)
        try:
            unityfs.inspect_bundle(path)
        except PipelineError:
            return  # the reader's own bounded error; the good case
        except Exception as exc:  # a leaked non-named error is the bug
            case.fail(
                f"inspect_bundle raised {type(exc).__name__} on {len(data)} input "
                f"bytes (not a PipelineError): {exc}"
            )
    finally:
        __import__("shutil").rmtree(directory)


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed (dev group)")
class ParserPropertyTests(unittest.TestCase):
    @given(st.binary(max_size=16 * 1024))
    @settings(max_examples=150, deadline=None)
    def test_arbitrary_bytes_never_leak_a_raw_error(self, data: bytes) -> None:
        _assert_bounded(self, data)

    @given(st.lists(st.integers(min_value=0, max_value=0x10000), max_size=16))
    @settings(max_examples=100, deadline=None)
    def test_hostile_class_ids_are_bounded(self, class_ids: list[int]) -> None:
        _assert_bounded(self, unityfs_bundle(class_ids))

    @given(
        st.integers(min_value=0, max_value=0x200000),
        st.integers(min_value=0, max_value=0xFF),
        st.integers(min_value=0, max_value=0x4000),
        st.booleans(),
    )
    @settings(max_examples=100, deadline=None)
    def test_hostile_node_and_truncation_are_bounded(
        self, node_size: int, header_flags: int, truncate: int, tree: bool
    ) -> None:
        payload = serialized_file([142], has_type_tree=tree)
        original = build_bundle(
            [(payload, len(payload), 0)],
            node_size=node_size,
            header_flags=0x40 | 0x200 | (header_flags & 0x180),
        )
        # Truncate the assembled archive at a Hypothesis-chosen byte: hostile
        # truncation is the reader's own job to bound, not the fixture's.
        data = original[: max(0, len(original) - truncate)]
        _assert_bounded(self, data)

    @given(st.binary(max_size=8 * 1024))
    @settings(max_examples=120, deadline=None)
    def test_hostile_lz4_block_is_bounded(self, block: bytes) -> None:
        # flags 2 = LZ4-compressed; the declared uncompressed size is the real
        # SerializedFile, so a valid decode proceeds to _class_ids and a bad one
        # must fail as a bounded LZ4 error rather than a raw one.
        payload = serialized_file([142])
        data = build_bundle([(block, len(payload), 2)], node_size=len(payload))
        _assert_bounded(self, data)
