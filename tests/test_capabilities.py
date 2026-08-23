from __future__ import annotations

import unittest
from unittest import mock

from sevendtd_asset_pipeline import PipelineError, capabilities
from sevendtd_asset_pipeline.capabilities import REGISTRY, _availability, require_capability


class CapabilityTests(unittest.TestCase):
    def tearDown(self) -> None:
        _availability.cache_clear()

    def test_every_capability_declares_what_it_unlocks_and_how_to_install(self) -> None:
        for capability in capabilities():
            with self.subTest(capability.name):
                self.assertIn(capability.kind, ("command", "any-command", "module"))
                self.assertTrue(capability.unlocks, "must name what it unlocks")
                self.assertTrue(capability.purpose)
                self.assertTrue(capability.install, "must name an install command")
                self.assertIsInstance(capability.available, bool)

    def test_report_is_json_serializable(self) -> None:
        import json

        payload = json.dumps([capability.as_dict() for capability in capabilities()])
        self.assertEqual(len(REGISTRY), len(json.loads(payload)))

    def test_require_names_the_capability_and_its_install_command(self) -> None:
        _availability.cache_clear()
        with mock.patch(
            "sevendtd_asset_pipeline.capabilities._availability", return_value={"UnityPy": False}
        ):
            with self.assertRaises(PipelineError) as caught:
                require_capability("UnityPy")
        message = str(caught.exception)
        self.assertIn("UnityPy", message)
        self.assertIn("inspect --deep", message)
        self.assertIn("uv pip install", message)

    def test_require_passes_when_available(self) -> None:
        with mock.patch(
            "sevendtd_asset_pipeline.capabilities._availability", return_value={"UnityPy": True}
        ):
            require_capability("UnityPy")

    def test_unknown_capability_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unknown capability"):
            require_capability("no-such-tool")


class OptionalFeatureTests(unittest.TestCase):
    """The optional features must degrade with an actionable message, never a traceback."""

    def tearDown(self) -> None:
        _availability.cache_clear()

    def test_deep_inspect_without_unitypy_explains_itself(self) -> None:
        from pathlib import Path

        from sevendtd_asset_pipeline.deep_inspect import deep_inspect

        with mock.patch(
            "sevendtd_asset_pipeline.capabilities._availability", return_value={"UnityPy": False}
        ):
            with self.assertRaisesRegex(PipelineError, "uv pip install"):
                deep_inspect(Path("/nonexistent.unity3d"))

    def test_check_mesh_without_any_tooling_explains_itself(self) -> None:
        import tempfile
        from pathlib import Path

        from sevendtd_asset_pipeline.mesh_check import check_mesh

        with tempfile.NamedTemporaryFile(suffix=".glb") as handle:
            with mock.patch(
                "sevendtd_asset_pipeline.capabilities._availability", return_value={"trimesh": False}
            ), mock.patch("sevendtd_asset_pipeline.mesh_check.shutil.which", return_value=None):
                with self.assertRaisesRegex(PipelineError, "install-tools|uv pip install"):
                    check_mesh(Path(handle.name))


if __name__ == "__main__":
    unittest.main()
