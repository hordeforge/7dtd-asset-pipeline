"""The release-asset resolver install-tools.sh pipes GitHub JSON through.

The shell treats empty output as "could not resolve" and skips an optional
install, so this helper must answer exactly one URL for a match and stay
silent and successful for every non-match, including unparsable input.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "github_asset_url.py"

UV_RELEASE = {
    "tag_name": "0.9.0",
    "assets": [
        {"name": "uv-src.tar.gz", "browser_download_url": "https://example/src.tar.gz"},
        {
            "name": "uv-x86_64-unknown-linux-gnu.tar.gz",
            "browser_download_url": "https://example/uv-linux.tar.gz",
        },
        {"name": "uv-x86_64-apple-darwin.tar.gz", "browser_download_url": "https://example/mac"},
    ],
}


GLTF_RELEASES = [
    {
        "tag_name": "4.1.0",
        "assets": [{"name": "windows.zip", "browser_download_url": "https://example/win"}],
    },
    {
        "tag_name": "4.0.0",
        "assets": [
            {
                "name": "gltf-validator-4.0.0-linux64.tar.xz",
                "browser_download_url": "https://example/validator.tar.xz",
            }
        ],
    },
]


def run(payload: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *arguments],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class GithubAssetUrlTests(unittest.TestCase):
    def test_matches_one_exact_name_in_a_single_release(self) -> None:
        result = run(json.dumps(UV_RELEASE), "--name", "uv-x86_64-unknown-linux-gnu.tar.gz")
        self.assertEqual(0, result.returncode)
        self.assertEqual("https://example/uv-linux.tar.gz\n", result.stdout)

    def test_matches_the_first_suffix_hit_across_a_release_list(self) -> None:
        result = run(json.dumps(GLTF_RELEASES), "--suffix=-linux64.tar.xz")
        self.assertEqual(0, result.returncode)
        self.assertEqual("https://example/validator.tar.xz\n", result.stdout)

    def test_a_release_object_and_a_list_answer_alike(self) -> None:
        single = run(json.dumps(UV_RELEASE), "--name", "uv-src.tar.gz")
        listed = run(json.dumps([UV_RELEASE]), "--name", "uv-src.tar.gz")
        self.assertEqual(single.stdout, listed.stdout)
        self.assertEqual("https://example/src.tar.gz\n", single.stdout)

    def test_no_match_prints_nothing_and_exits_zero(self) -> None:
        result = run(json.dumps(UV_RELEASE), "--suffix=-linux64.tar.xz")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_unparsable_input_prints_nothing_and_exits_zero(self) -> None:
        result = run("<html>gateway timeout</html>", "--name", "anything")
        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stdout)

    def test_malformed_entries_are_skipped_without_failing(self) -> None:
        payload = ["not-a-release", 7, {"assets": "not-a-list"}, UV_RELEASE]
        result = run(json.dumps(payload), "--name", "uv-x86_64-unknown-linux-gnu.tar.gz")
        self.assertEqual(0, result.returncode)
        self.assertEqual("https://example/uv-linux.tar.gz\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
