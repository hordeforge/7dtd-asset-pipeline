"""Launching the Unity editor, with the one host limit that stops it dead.

Every Unity invocation in this package goes through :func:`run_unity` rather
than calling :mod:`subprocess` directly, because a batch-mode editor inherits
the shell's file-descriptor limit and **crashes when that limit is large**.

The failure is loud but says nothing about its cause:

.. code-block:: text

    Unity: .../mono/external/corefx-bugfix/src/Native/Unix/Common/pal_utilities.h:160:
    int ToFileDescriptor(intptr_t): Assertion
    `fd < sysconf(_SC_OPEN_MAX) && "Requested file descriptor exceeds maximum
    number of files allowed to be open at a time."' failed.

and the editor dies on SIGABRT — `shamway build` reports `Unity exited -6` with
a log whose compile section is clean. Nothing in it points at the host.

**Reproduced 2026-08-24** on a machine whose soft `RLIMIT_NOFILE` was
1048576: builds aborted every time. Lowering it to 65536 for the same command,
same project, same editor, made them succeed every time. The exact mechanism
inside mono is *not* established here — the assertion reads as though a large
`_SC_OPEN_MAX` should make it easier to satisfy, not harder — so what is
recorded is the reproduction and the mitigation, not a diagnosis. Do not write
this up as understood.

Lowering the limit for a child process is a standard mitigation for this class
of bug and costs nothing: 65536 open files is far beyond anything an asset
build opens, and the parent's own limit is untouched.
"""

from __future__ import annotations

import resource
import subprocess
from collections.abc import Sequence

# Comfortably above what any asset build needs, and comfortably below the
# limits that trip the assertion above.
SAFE_OPEN_FILE_LIMIT = 65536


def _clamp_open_files() -> None:
    """Lower this process's soft file limit, in the child, before exec."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == resource.RLIM_INFINITY or soft > SAFE_OPEN_FILE_LIMIT:
        ceiling = SAFE_OPEN_FILE_LIMIT
        if hard != resource.RLIM_INFINITY:
            ceiling = min(ceiling, hard)
        resource.setrlimit(resource.RLIMIT_NOFILE, (ceiling, hard))


def open_file_limit_is_risky() -> bool:
    """Whether this host's soft limit is one that has been seen to abort Unity."""
    soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
    return soft == resource.RLIM_INFINITY or soft > SAFE_OPEN_FILE_LIMIT


def run_unity(
    command: Sequence[str], timeout: float | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run a batch-mode Unity command with a file limit it survives.

    ``preexec_fn`` runs in the forked child, so the clamp applies to the editor
    and to nothing else in this process tree.
    """
    return subprocess.run(
        list(command),
        check=False,
        timeout=timeout,
        preexec_fn=_clamp_open_files,
    )
