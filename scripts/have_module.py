#!/usr/bin/env python3
"""Exit zero when every named module imports in this interpreter.

install-tools.sh probes the optional Python capabilities this way rather than
with `python3 -c "import X"`, for the reason github_asset_url.py gives: one
language per file, and a file gets compiled and linted with the rest of the
tree. Importing is the probe rather than a metadata lookup, because importing
is what the lanes themselves do: a package whose metadata is present but whose
native extension will not load is not a usable capability.

Usage:
    have_module.py UnityPy
    have_module.py PIL numpy trimesh
"""

from __future__ import annotations

import importlib
import sys


def main(names: list[str]) -> int:
    for name in names:
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - a package that raises on import is not usable either
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
