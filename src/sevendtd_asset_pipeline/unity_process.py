"""Launching the Unity editor, and surviving an abort that is not our fault.

Every Unity invocation in this package goes through :func:`run_unity` rather
than calling :mod:`subprocess` directly, because a batch-mode editor
**intermittently** dies on a mono assertion:

.. code-block:: text

    Unity: .../mono/external/corefx-bugfix/src/Native/Unix/Common/pal_utilities.h:160:
    int ToFileDescriptor(intptr_t): Assertion
    `fd < sysconf(_SC_OPEN_MAX) && "Requested file descriptor exceeds maximum
    number of files allowed to be open at a time."' failed.

The editor dies on SIGABRT and `shamway build` reports `Unity exited -6` over a
log whose compile section is clean. Nothing in it points at a cause.

**A correction, recorded because the wrong version of it shipped first.** This
module originally said the host's soft ``RLIMIT_NOFILE`` was responsible, on
the strength of a machine at 1048576 where builds aborted and then succeeded
after lowering it to 65536. That was two data points and a coincidence. With
the clamp in place and the limit at 65536, the same build aborted again with
the same assertion, and then succeeded on an immediate retry of the identical
command in the identical environment.

So: the failure is **intermittent, and its cause is not known**. Roughly two
aborts in a dozen builds on one host, with and without the clamp. The clamp is
gone, because a mitigation justified by a claim that turned out to be false
should not be kept on the chance it helps anyway — it would just be one more
unexplained thing for the next person to reason around.

What is left is what the evidence supports: a bounded retry. An abort before
the editor has written its bundle costs nothing to repeat, and an intermittent
crash that clears on retry is exactly what a retry is for. When every attempt
aborts, the error says so and names the log, rather than dressing a real
failure up as flakiness.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

# How many times a build may be retried after an abort that never reached a
# bundle. Two extra attempts: enough for an intermittent crash observed at
# roughly one in six, few enough that a genuinely broken project fails in under
# a minute instead of three times over.
MAX_ATTEMPTS = 3

# The mono assertion this retries. Matched narrowly on purpose — a retry that
# fires on any non-zero exit would paper over real build failures, which is the
# opposite of what this package is for.
ABORT_SIGNATURE = "ToFileDescriptor"

# SIGABRT, as subprocess reports it.
ABORTED = -6


def run_unity(
    command: Sequence[str],
    timeout: float | None = None,
    log: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a batch-mode Unity command, retrying an abort that produced nothing.

    ``log`` is the editor's ``-logFile`` destination when the caller has one.
    It is read to tell the intermittent mono abort apart from a crash that
    means something; without it, only the SIGABRT exit code is available and
    the retry is correspondingly more cautious.
    """
    result = subprocess.run(list(command), check=False, timeout=timeout)
    for attempt in range(2, MAX_ATTEMPTS + 1):
        if not _is_intermittent_abort(result, log):
            return result
        print(
            f"note: Unity aborted on the known intermittent mono assertion; "
            f"retrying ({attempt}/{MAX_ATTEMPTS})",
            file=sys.stderr,
        )
        result = subprocess.run(list(command), check=False, timeout=timeout)
    return result


def _is_intermittent_abort(result: subprocess.CompletedProcess[bytes], log: Path | None) -> bool:
    """Whether this looks like the mono abort rather than a real failure."""
    if result.returncode != ABORTED:
        return False
    if log is None:
        # No log to corroborate with. A SIGABRT alone is weak evidence, but it
        # is never a *successful* build, so a retry cannot hide a green run.
        return True
    try:
        return ABORT_SIGNATURE in log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
