"""Performance budget for metadata-only `unityz info` on the trees fallback.

The 621 MB `Data/Bundles/Standalone/Entities/trees` bundle is the measured
sidecar-backed case: a 1.15 GB `.resS` node that default `info` must not
decompress. unityz 0.1.6 reads 0.006 s / 13.5 MB RSS here. LZMA and LZHAM
blocks are absent from this game's stock UnityFS set (288 files).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.unityz import executable, invoke

# Measured 0.006 s / 13768 kB on the installed trees bundle (unityz 0.1.6).
INFO_BUDGET_SECONDS = 0.2
INFO_BUDGET_RSS_KB = 64 * 1024


def _trees_bundle() -> Path | None:
    game = os.environ.get("SEVEN_DAYS_TO_DIE_DIR")
    if not game:
        return None
    path = Path(game) / "Data" / "Bundles" / "Standalone" / "Entities" / "trees"
    return path if path.is_file() else None


def _peak_rss_kb(argv: list[str]) -> int:
    """The peak RSS of one specific child, in kB.

    `getrusage(RUSAGE_CHILDREN)` is a high-water mark over *every* child the
    test process has ever reaped, so reading it after one run reports whichever
    earlier test spawned the ffmpeg or Blender that used the most memory, not
    this process, and the budget then fails for a caller that is not under
    measurement. `os.wait4` reports the rusage of the one pid it reaped.
    """
    with subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as probe:
        _, status, usage = os.wait4(probe.pid, 0)
        # Reaped above, so the context manager's own wait() has nothing to do.
        probe.returncode = os.waitstatus_to_exitcode(status)
    if probe.returncode != 0:
        raise AssertionError(f"{argv[0]} exited {probe.returncode} while being measured")
    return int(usage.ru_maxrss)


class UnityzInfoBudgetTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("unityz"), "needs unityz")
    def test_trees_fallback_info_stays_inside_the_metadata_budget(self) -> None:
        trees = _trees_bundle()
        if trees is None:
            self.skipTest(
                "SEVEN_DAYS_TO_DIE_DIR is unset or has no Data/Bundles/Standalone/Entities/trees"
            )

        started = time.perf_counter()
        result = invoke("info", str(trees), "--json", subject=str(trees))
        elapsed = time.perf_counter() - started

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

        rss_kb = _peak_rss_kb([executable(), "info", str(trees), "--json"])
        self.assertLess(
            rss_kb,
            INFO_BUDGET_RSS_KB,
            f"unityz info --json on {trees} peaked at {rss_kb} kB "
            f"(budget {INFO_BUDGET_RSS_KB} kB; file is 621 MB with a 1.15 GB sidecar)",
        )
