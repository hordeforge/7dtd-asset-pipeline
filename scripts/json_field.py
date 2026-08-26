#!/usr/bin/env python3
"""Print one top-level field of the JSON object on stdin.

The shell scripts here read fields out of `shamway ... --json` output. They
call this rather than embedding a JSON program, for the reason
github_asset_url.py gives: one language per file, and a parser in a file gets
compiled, linted and type-checked with everything else in the tree.

Usage:
    shamway client where --json | json_field.py log_dir

A null value prints an empty line, which is what a shell `[[ -z ]]` test
expects. A missing field, a payload that is not an object, or unparsable input
is an error: the callers substitute these values into paths they then write to,
so a silent empty string would aim a later command at the wrong place.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="print one field of a JSON object")
    parser.add_argument("field", help="the top-level key to print")
    arguments = parser.parse_args()

    try:
        payload: object = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"ERROR: stdin is not JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print(f"ERROR: expected a JSON object, got {type(payload).__name__}", file=sys.stderr)
        return 1
    if arguments.field not in payload:
        available = ", ".join(sorted(payload)) or "nothing"
        print(
            f"ERROR: no field {arguments.field!r}; the payload carries {available}", file=sys.stderr
        )
        return 1
    value = payload[arguments.field]
    print("" if value is None else value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
