"""Performance budget for metadata-only `unityz info` on the trees fallback.

The 621 MB `Data/Bundles/Standalone/Entities/trees` bundle is the measured
sidecar-backed case: a 1.15 GB `.resS` node that default `info` must not
decompress. unityz 0.1.6 reads 0.006 s / 13.5 MB RSS here. LZMA and LZHAM
blocks are absent from this game's stock UnityFS set (288 files).
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import time
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.unityz import invoke

# Measured 0.006 s / 13768 kB on the installed trees bundle (unityz 0.1.6).
INFO_BUDGET_SECONDS = 0.2
INFO_BUDGET_RSS_KB = 64 * 1024


def _trees_bundle() -> Path | None:
    game = os.environ.get("SEVEN_DAYS_TO_DIE_DIR")
    if not game:
        return None
    path = Path(game) / "Data" / "Bundles" / "Standalone" / "Entities" / "trees"
    return path if path.is_file() else None


class UnityzInfoBudgetTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("unityz"), "needs unityz")
    def test_trees_fallback_info_stays_inside_the_metadata_budget(self) -> None:
        trees = _trees_bundle()
        if trees is None:
            self.skipTest(
                "SEVEN_DAYS_TO_DIE_DIR is unset or has no Data/Bundles/Standalone/Entities/trees"
            )

        _ = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        result = invoke("info", str(trees), "--json", subject=str(trees))
        elapsed = time.perf_counter() - started
        rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report.get("type"), "UnityFS")
        serialized = [
            node.get("serialized")
            for node in report.get("nodes_list") or []
            if node.get("serialized")
        ]
        self.assertTrue(serialized)
        self.assertEqual(serialized[0].get("unity"), "2022.3.62f2")

        self.assertLess(
            elapsed,
            INFO_BUDGET_SECONDS,
            f"unityz info --json on {trees} took {elapsed:.3f}s "
            f"(budget {INFO_BUDGET_SECONDS}s; whole-container was 1.22s)",
        )
        self.assertLess(
            rss_kb,
            INFO_BUDGET_RSS_KB,
            f"unityz info --json on {trees} peaked at {rss_kb} kB "
            f"(budget {INFO_BUDGET_RSS_KB} kB; file is 621 MB with a 1.15 GB sidecar)",
        )
