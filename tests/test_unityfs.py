from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.errors import PipelineError
from sevendtd_asset_pipeline.unityfs import inspect_bundle
from sevendtd_asset_pipeline.validation import validate_bundle

from fixtures import unityfs_bundle


class UnityFsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
