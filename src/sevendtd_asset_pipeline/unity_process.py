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

The same care applies to the *other* way a Unity invocation ends: the timeout.
A batch-mode editor spawns worker children of its own (AssetImportWorker
processes during the import pass), and killing only the direct child orphans
them — they keep running against ``Library/`` and hold it against the next
launch, which reads as a hung project rather than a killed one. So a bounded
invocation puts the child alone in its own session and, when the deadline
fires, signals that whole session; every descendant the editor created dies
with it. Where there are no process groups (Windows), the direct-child kill is
all the platform offers and all that happens.
"""

from __future__ import annotations

import os
import signal
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
    result = _run(command, timeout)
    for attempt in range(2, MAX_ATTEMPTS + 1):
        if not _is_intermittent_abort(result, log):
            return result
        print(
            f"note: Unity aborted on the known intermittent mono assertion; "
            f"retrying ({attempt}/{MAX_ATTEMPTS})",
            file=sys.stderr,
        )
        result = _run(command, timeout)
    return result


def _run(command: Sequence[str], timeout: float | None) -> subprocess.CompletedProcess[bytes]:
    """One invocation. A bounded one kills the child's whole session on expiry.

    The unbounded path stays on :func:`subprocess.run` so a caller (and the
    tests) can observe it exactly as before.
    """
    if timeout is None:
        return subprocess.run(list(command), check=False)
    process = subprocess.Popen(
        list(command),
        # False where there are no sessions (Windows); True nowhere else.
        start_new_session=hasattr(os, "setsid"),
    )
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        raise
    return subprocess.CompletedProcess(list(command), returncode)


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL the child's whole process group, then reap it.

    With ``start_new_session`` the child's group id *is* its pid, so one
    signal reaches every worker it spawned. A child that already exited races
    the signal and loses silently; the direct-child kill covers the case
    where no groups exist.
    """
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


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
