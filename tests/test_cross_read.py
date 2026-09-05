"""The independent second reader of a synthesized bundle.

unityz creates the bundle and re-reads it before the file lands, so the
writer and its check share one implementation. `scripts/cross-read.sh` reads
the same file with AssetsTools.NET, which shares no code with either, and
this compares what the two readers see. It proves construction only; the
fresh-client acceptance remains the gate for whether the engine accepts it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from sevendtd_asset_pipeline.capabilities import has_capability
from sevendtd_asset_pipeline.scripts import path as script_path

BASH = shutil.which("bash") or "/bin/bash"

BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "SelfTestMod"
    / "Resources"
    / "shamwayselftest.unity3d"
)


class CrossReadTests(unittest.TestCase):
    def test_a_missing_bundle_is_one_error_line(self) -> None:
        result = subprocess.run(
            [BASH, str(script_path("cross-read")), "/nonexistent/bundle.unity3d"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("ERROR: no bundle at "), result.stderr)

    @unittest.skipUnless(shutil.which("dotnet"), "needs the .NET SDK")
    @unittest.skipUnless(has_capability("unityz"), "needs unityz")
    def test_assetstools_and_unityz_see_the_same_objects(self) -> None:
        result = subprocess.run(
            [BASH, str(script_path("cross-read")), str(BUNDLE)],
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        seen = json.loads(result.stdout)

        unityz = shutil.which("unityz")
        assert unityz is not None
        info = json.loads(
            subprocess.check_output([unityz, "info", str(BUNDLE), "--json", "--objects"], text=True)
        )
        serialized = info["nodes_list"][0]["serialized"]
        self.assertEqual(seen["revision"], serialized["unity"])
        self.assertEqual(seen["platform"], serialized["platform"])
        self.assertTrue(seen["typeTree"])
        self.assertEqual(seen["node"], info["nodes_list"][0]["path"])

        ours = [(o["pathId"], o["classId"], o["name"]) for o in seen["objects"]]
        theirs = [(o["path_id"], o["class"], o.get("name", "")) for o in info["object_list"]]
        self.assertEqual(ours, theirs)

        container = json.loads(
            subprocess.check_output([unityz, "show", str(BUNDLE), "1"], text=True)
        )
        self.assertEqual(seen["container"], [name for name, _entry in container["m_Container"]])
