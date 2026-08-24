"""The package's one atomic-publish pattern.

Every writer here publishes through a unique temporary name in the
destination's directory plus one rename: a body written straight to the
destination that dies midway (disk full, Ctrl+C) leaves a truncated artifact
at the final path, indistinguishable from a complete one until something
fails to load it. The temporary name carries this process's pid plus a random
suffix — a fixed `<name>.tmp` is shared by two concurrent writers truncating
one file — and is unlinked on every exit path, so an interrupted run strands
no dotfile.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def staged_write(destination: Path) -> Iterator[Path]:
    """Yield a unique temporary path beside `destination`, then publish it.

    The caller fills the yielded path by any means (bytes, a library writer,
    a copy) and the rename happens only when the body completed. A failure at
    any point removes the temporary; after a successful publish the unlink is
    a no-op, because the rename already moved the file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    )
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def write(path: Path, payload: bytes | str) -> None:
    """Write bytes or text to `path` through `staged_write`."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    with staged_write(path) as staged:
        staged.write_bytes(data)
