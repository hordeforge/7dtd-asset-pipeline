"""Disk-backed scratch directories for the lanes that shell out.

`tempfile` defaults to `/tmp`, which is tmpfs on most Linux hosts: RAM, not
disk. The working files here are not small (a decoded WAV, a rasterized sheet,
a Blender render, a compiled shader blob), so the default location charges
them against memory and loses the cache on reboot. Everything short-lived goes
under the user cache directory instead (`XDG_CACHE_HOME`, else `~/.cache` on
Linux, `~/Library/Caches` on macOS, `%LOCALAPPDATA%` on Windows), which is on
disk and survives.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

CACHE_DIR_NAME = "shamway"


def _default_cache_base() -> Path:
    """The host's usual user-cache directory when `XDG_CACHE_HOME` is unset.

    Linux: ``~/.cache``. macOS: ``~/Library/Caches``. Windows: ``%LOCALAPPDATA%``.
    `XDG_CACHE_HOME` still wins on every host, including a Windows or macOS
    shell that exported it.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) if local else Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path.home() / ".cache"


def cache_root() -> Path:
    """The disk-backed base for scratch work, honouring `XDG_CACHE_HOME`."""
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured) if configured else _default_cache_base()
    root = base / CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def scratch_dir(prefix: str) -> Iterator[Path]:
    """Yield an empty directory under `cache_root`, removed on exit."""
    with tempfile.TemporaryDirectory(prefix=prefix, dir=cache_root()) as directory:
        yield Path(directory)
