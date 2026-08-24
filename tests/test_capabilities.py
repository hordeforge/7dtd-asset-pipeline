from __future__ import annotations

import unittest
from unittest import mock

from sevendtd_asset_pipeline import PipelineError, capabilities
from sevendtd_asset_pipeline.capabilities import (
    REGISTRY,
    SOURCE_URL,
    Capability,
    require_capability,
)


class CapabilityTests(unittest.TestCase):
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
        with (
            mock.patch(
                "sevendtd_asset_pipeline.capabilities._availability",
                return_value={"UnityPy": False},
            ),
            self.assertRaises(PipelineError) as caught,
        ):
            require_capability("UnityPy")
        message = str(caught.exception)
        self.assertIn("UnityPy", message)
        self.assertIn("inspect --deep", message)
        self.assertIn("uv pip install", message)

    def test_no_install_hint_resolves_the_bare_name_from_an_index(self) -> None:
        """The project is not on PyPI, so a bare-name hint is dependency confusion.

        `uv pip install '7dtd-asset-pipeline[all]'` resolves against the public
        index, where this name is unregistered: it fails today and installs
        whoever registers the name first tomorrow. Every hint the registry
        emits must pin the canonical git source instead.
        """
        for capability in capabilities():
            with self.subTest(capability.name):
                if "7dtd-asset-pipeline[" in capability.install:
                    self.assertIn("@ " + SOURCE_URL, capability.install)

    def test_require_passes_when_available(self) -> None:
        with mock.patch(
            "sevendtd_asset_pipeline.capabilities._availability", return_value={"UnityPy": True}
        ):
            require_capability("UnityPy")

    def test_unknown_capability_is_rejected(self) -> None:
        with self.assertRaisesRegex(PipelineError, "unknown capability"):
            require_capability("no-such-tool")

    def test_an_install_landing_mid_session_is_honored_without_a_restart(self) -> None:
        """`serve` outlives the installs its own error messages call for.

        `require_capability` and the `capabilities` operation must read the same
        answer, or a consumer that installs a capability and retries over the
        same serve session is refused forever while `capabilities --json`
        reports it present.
        """
        from sevendtd_asset_pipeline.capabilities import has_capability

        with mock.patch(
            "sevendtd_asset_pipeline.capabilities.importlib.util.find_spec",
            return_value=None,
        ):
            self.assertFalse(has_capability("UnityPy"))
            with self.assertRaises(PipelineError):
                require_capability("UnityPy")
        # The install lands; nothing is cached, so the next ask sees it.
        with mock.patch(
            "sevendtd_asset_pipeline.capabilities.importlib.util.find_spec",
            return_value=object(),
        ):
            self.assertTrue(has_capability("UnityPy"))
            require_capability("UnityPy")


class OptionalFeatureTests(unittest.TestCase):
    """The optional features must degrade with an actionable message, never a traceback."""

    def test_deep_inspect_without_unitypy_explains_itself(self) -> None:
        from pathlib import Path

        from sevendtd_asset_pipeline.deep_inspect import deep_inspect

        with (
            mock.patch(
                "sevendtd_asset_pipeline.capabilities._availability",
                return_value={"UnityPy": False},
            ),
            self.assertRaisesRegex(PipelineError, "uv pip install"),
        ):
            deep_inspect(Path("/nonexistent.unity3d"))

    def test_check_mesh_without_any_tooling_explains_itself(self) -> None:
        import tempfile
        from pathlib import Path

        from sevendtd_asset_pipeline.mesh_check import check_mesh

        with (
            tempfile.NamedTemporaryFile(suffix=".glb") as handle,
            mock.patch(
                "sevendtd_asset_pipeline.capabilities._availability",
                return_value={"trimesh": False},
            ),
            mock.patch("sevendtd_asset_pipeline.mesh_check.shutil.which", return_value=None),
            self.assertRaisesRegex(PipelineError, "install-tools|uv pip install"),
        ):
            check_mesh(Path(handle.name))


class PresenceIsNotCapabilityTests(unittest.TestCase):
    """A tool on PATH that cannot do the job must not report as available.

    Debian and Ubuntu package vkd3d 1.2, which predates the HLSL support this
    writer needs. Probing with `which` alone reported it available, let a build
    start, and failed half-way with the tool's own error — the exact
    silent-until-late failure this project exists to move earlier.
    """

    def _fake_vkd3d(self, source_types: str, returncode: int = 0) -> mock.MagicMock:
        return mock.MagicMock(returncode=returncode, stdout=source_types, stderr="")

    def _lane(self, run_result: object) -> Capability:
        from sevendtd_asset_pipeline.capabilities import capabilities

        with (
            mock.patch(
                "sevendtd_asset_pipeline.capabilities.shutil.which",
                lambda name: "/usr/bin/vkd3d-compiler" if name == "vkd3d-compiler" else None,
            ),
            mock.patch(
                "sevendtd_asset_pipeline.capabilities.subprocess.run", return_value=run_result
            ),
        ):
            return next(item for item in capabilities() if item.name == "vkd3d-compiler")

    def test_a_vkd3d_that_cannot_read_hlsl_is_not_available(self) -> None:
        lane = self._lane(self._fake_vkd3d("Supported source types:\n  dxbc-tpf\n  none\n"))
        self.assertFalse(lane.available)
        self.assertEqual("/usr/bin/vkd3d-compiler", lane.path)
        self.assertIn("older than vkd3d 1.3", lane.unusable_reason or "")

    def test_a_vkd3d_too_old_to_know_the_flag_is_not_available(self) -> None:
        lane = self._lane(self._fake_vkd3d("", returncode=1))
        self.assertFalse(lane.available)
        self.assertIn("older than vkd3d 1.3", lane.unusable_reason or "")

    def test_a_vkd3d_that_reads_hlsl_is_available_with_no_reason(self) -> None:
        lane = self._lane(self._fake_vkd3d("  dxbc-tpf\n  hlsl\n  d3dbc\n"))
        self.assertTrue(lane.available)
        self.assertIsNone(lane.unusable_reason)

    def test_the_build_caveat_distinguishes_absent_from_too_old(self) -> None:
        """ "Install it" is the least useful sentence for a tool already installed."""
        from sevendtd_asset_pipeline.build import synthesized_caveats
        from sevendtd_asset_pipeline.capabilities import Capability

        def lane(**kwargs: object) -> list[Capability]:
            base: dict[str, object] = {
                "name": "vkd3d-compiler",
                "kind": "command",
                "unlocks": (),
                "purpose": "",
                "install": "install me",
                "available": False,
            }
            return [Capability(**{**base, **kwargs})]  # type: ignore[arg-type]

        with mock.patch(
            "sevendtd_asset_pipeline.build.capabilities",
            return_value=lane(path="/usr/bin/vkd3d-compiler", unusable_reason="it is too old"),
        ):
            joined = " ".join(synthesized_caveats())
        self.assertIn("cannot be used", joined)
        self.assertIn("it is too old", joined)
        self.assertNotIn("is not installed", joined)

        with mock.patch("sevendtd_asset_pipeline.build.capabilities", return_value=lane(path=None)):
            joined = " ".join(synthesized_caveats())
        self.assertIn("is not installed", joined)

    def test_require_capability_does_not_tell_you_to_install_what_you_have(self) -> None:
        from sevendtd_asset_pipeline.capabilities import require_capability

        with (
            mock.patch(
                "sevendtd_asset_pipeline.capabilities.shutil.which",
                lambda name: "/usr/bin/vkd3d-compiler" if name == "vkd3d-compiler" else None,
            ),
            mock.patch(
                "sevendtd_asset_pipeline.capabilities.subprocess.run",
                return_value=self._fake_vkd3d("  dxbc-tpf\n"),
            ),
            self.assertRaisesRegex(PipelineError, "cannot be used"),
        ):
            require_capability("vkd3d-compiler")


if __name__ == "__main__":
    unittest.main()
