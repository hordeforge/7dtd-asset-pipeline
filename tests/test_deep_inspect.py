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
            self.assertEqual(["mymodnote"], [entry.asset_stem for entry in report.entries])
        finally:
            gc.enable()
        self.assertEqual(before, open_descriptor_count())

    def test_a_missing_bundle_is_named_not_loaded(self) -> None:
        with self.assertRaisesRegex(Exception, "no such file"):
            deep_inspect(self.root / "absent.unity3d")


if __name__ == "__main__":
    unittest.main()
