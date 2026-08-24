#!/usr/bin/env python3
"""Print the download URL of the first release asset matching a selector.

install-tools.sh pipes a GitHub releases API response here rather than
embedding a JSON program: one language per file, and this parser gets syntax
checking and linting like every other file in the tree.

Usage:
    github_asset_url.py --name NAME    # match an asset by its exact file name
    github_asset_url.py --suffix SUF   # match the first name ending in SUF

The payload on stdin is either a single release object (the /releases/latest
endpoint) or a list of releases (the /releases endpoint), newest first. The
first matching asset in that order wins. No match, unparsable input, or a
changed API shape prints nothing and still exits zero: the callers treat empty
output as "could not resolve" and skip the optional install, so this
best-effort resolver must never fail the install it serves.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator


def _assets(payload: object) -> Iterator[tuple[str, str]]:
    """Every (file name, download URL) in the payload, releases in order."""
    releases = payload if isinstance(payload, list) else [payload]
    for release in releases:
        if not isinstance(release, dict):
            continue
        for asset in release.get("assets", []):
            if not isinstance(asset, dict):
                continue
            name = asset.get("name")
            url = asset.get("browser_download_url")
            if isinstance(name, str) and isinstance(url, str):
                yield name, url


def main() -> int:
    parser = argparse.ArgumentParser(description="resolve one GitHub release asset URL")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--name", help="the exact asset file name to find")
    selector.add_argument("--suffix", help="the file-name ending to find")
    arguments = parser.parse_args()

    try:
        payload: object = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return 0
    for name, url in _assets(payload):
        if name == arguments.name or (
            arguments.suffix is not None and name.endswith(arguments.suffix)
        ):
            print(url)
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
