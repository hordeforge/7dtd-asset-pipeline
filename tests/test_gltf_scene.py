"""glTF document reading: external buffer URIs are confined to the document's directory.

A `.gltf` is untrusted input. Its buffer `uri` is joined onto the document's
directory and read as vertex data, so a URI that escapes would read any file
the build process can read and hand its bytes to the writer. The reader
refuses a URI that leaves; these tests pin the refusal and the one legal
layout (a buffer beside the document).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.gltf_scene import parse_gltf


class BufferUriContainment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.source = self.root / "model" / "scene.gltf"
        self.source.parent.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _document(self, uri: str) -> None:
        self.source.write_text(
            json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": uri, "byteLength": 4}]}),
            encoding="utf-8",
        )

    def test_sibling_buffer_is_allowed(self) -> None:
        (self.source.parent / "body.bin").write_bytes(b"\x00\x00\x00\x00")
        self._document("body.bin")
        self.assertEqual(parse_gltf(self.source).source, self.source)

    def test_parent_traversal_is_refused(self) -> None:
        (self.root / "secret.bin").write_bytes(b"k\x00e\x00y\x00")
        self._document("../secret.bin")
        with self.assertRaisesRegex(PipelineError, "leaves"):
            parse_gltf(self.source)

    def test_absolute_path_is_refused(self) -> None:
        self._document("/etc/passwd")
        with self.assertRaisesRegex(PipelineError, "leaves"):
            parse_gltf(self.source)

    def test_percent_escaped_traversal_is_refused(self) -> None:
        self._document("%2e%2e/secret.bin")
        with self.assertRaisesRegex(PipelineError, "plain relative path"):
            parse_gltf(self.source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
