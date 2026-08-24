"""deep_inspect must not hold the bundle's descriptor after it returns.

UnityPy keeps every loaded file open inside a reference-cyclic reader graph,
and its Environment has no close(): loading from a path left one descriptor
behind per call until the cyclic collector happened to run. Inside a long-lived
`shamway serve` session that is an accumulation on every inspect_deep request.
deep_inspect now hands UnityPy bytes instead, so no descriptor is ever held;
this test pins that with the cycle collector switched off, so any return to
path-based loading fails here rather than silently re-leaking.
"""

from __future__ import annotations

import gc
import os
import tempfile
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.bundle_writer import build_bundle, text_asset
from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.deep_inspect import deep_inspect
from sevendtd_asset_pipeline.errors import PipelineError

REVISION = "2022.3.62f2"


def open_descriptor_count() -> int | None:
    """How many descriptors this process holds, or None off /proc hosts."""
    directory = "/proc/self/fd"
    if not os.path.isdir(directory):
        return None
    return len(os.listdir(directory))


@unittest.skipUnless(has_capability("UnityPy"), "deep_inspect needs UnityPy")
class DeepInspectResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "inspect.unity3d"
        self.bundle.write_bytes(
            build_bundle([text_asset("myModNote", "hello")], REVISION, "inspect.unity3d")
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repeated_inspections_do_not_accumulate_descriptors(self) -> None:
        before = open_descriptor_count()
        if before is None:
            self.skipTest("no /proc/self/fd on this host")
        # Collector off: refcounting alone must reclaim everything the call
        # acquired, because nothing outside the call can reach it.
        gc.disable()
        try:
            report = None
            for _ in range(50):
                report = deep_inspect(self.bundle)
            assert report is not None, "deep_inspect returned no report in 50 runs"
            self.assertEqual(["mymodnote"], [entry.asset_stem for entry in report.entries])
        finally:
            gc.enable()
        after = open_descriptor_count()
        assert after is not None  # `before` already proved /proc/self/fd exists
        # Not `assertEqual`: the count is process-wide, so a descriptor another
        # test left reachable can be released *during* this one and the total
        # drops. CI caught exactly that — 10 before, 7 after — and a decrease
        # is not the failure this test is named for. Accumulation is, and 50
        # iterations make even a one-per-call leak show as +50.
        self.assertLessEqual(
            after, before, f"deep_inspect accumulated {after - before} descriptors"
        )

    def test_a_missing_bundle_is_a_pipeline_error_not_a_raw_os_error(self) -> None:
        # deep_inspect is diagnostic: every failure it reports must be
        # actionable (PipelineError), never a bare OSError from UnityPy.
        with self.assertRaisesRegex(PipelineError, "no such file"):
            deep_inspect(self.root / "absent.unity3d")


if __name__ == "__main__":
    unittest.main()
