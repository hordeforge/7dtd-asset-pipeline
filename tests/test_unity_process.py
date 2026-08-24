"""An intermittent editor abort must be retried, and nothing else must be.

Observed 2026-08-24: a batch-mode Unity build dies on

    ToFileDescriptor(intptr_t): Assertion `fd < sysconf(_SC_OPEN_MAX) ...' failed

roughly twice in a dozen runs on one host, and the same command in the same
environment succeeds on an immediate retry.

The first version of this module blamed the host's soft RLIMIT_NOFILE and
clamped it. That was wrong — the abort recurred with the clamp active — and the
tests below are written to keep the correction honest rather than to defend the
retry: the narrow cases are the ones that check a retry does *not* happen, so a
future widening that quietly swallows real build failures fails here.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.unity_process import (
    ABORT_SIGNATURE,
    ABORTED,
    MAX_ATTEMPTS,
    run_unity,
)

COMMAND = ["unity", "-batchmode"]


def _result(code: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(COMMAND, code, b"", b"")


class RetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.log = Path(self.temporary.name) / "unity-build.log"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_success_runs_once(self) -> None:
        with mock.patch.object(subprocess, "run", return_value=_result(0)) as run:
            self.assertEqual(run_unity(COMMAND).returncode, 0)
        self.assertEqual(run.call_count, 1)

    def test_the_known_abort_is_retried_and_can_succeed(self) -> None:
        self.log.write_text("... " + ABORT_SIGNATURE + " ...", encoding="utf-8")
        with mock.patch.object(
            subprocess, "run", side_effect=[_result(ABORTED), _result(0)]
        ) as run:
            self.assertEqual(run_unity(COMMAND, log=self.log).returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_a_persistent_abort_gives_up_and_reports_it(self) -> None:
        """Three aborts is a real failure, not flakiness to hide."""
        self.log.write_text(ABORT_SIGNATURE, encoding="utf-8")
        with mock.patch.object(
            subprocess, "run", side_effect=[_result(ABORTED)] * MAX_ATTEMPTS
        ) as run:
            self.assertEqual(run_unity(COMMAND, log=self.log).returncode, ABORTED)
        self.assertEqual(run.call_count, MAX_ATTEMPTS)

    def test_an_ordinary_failure_is_never_retried(self) -> None:
        """The whole point: a compile error must fail once, loudly."""
        with mock.patch.object(subprocess, "run", return_value=_result(1)) as run:
            self.assertEqual(run_unity(COMMAND, log=self.log).returncode, 1)
        self.assertEqual(run.call_count, 1)

    def test_an_abort_whose_log_says_otherwise_is_not_retried(self) -> None:
        """A SIGABRT from some other cause is a real crash worth reporting."""
        self.log.write_text("segfault in the importer", encoding="utf-8")
        with mock.patch.object(subprocess, "run", return_value=_result(ABORTED)) as run:
            self.assertEqual(run_unity(COMMAND, log=self.log).returncode, ABORTED)
        self.assertEqual(run.call_count, 1)

    def test_without_a_log_an_abort_is_retried(self) -> None:
        """Weaker evidence, but a SIGABRT is never a successful build.

        A retry here cannot turn a green run into a different green run, so the
        cautious direction is to retry rather than to fail on a crash that is
        usually this one.
        """
        with mock.patch.object(
            subprocess, "run", side_effect=[_result(ABORTED), _result(0)]
        ) as run:
            self.assertEqual(run_unity(COMMAND).returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_an_unreadable_log_does_not_retry(self) -> None:
        missing = Path(self.temporary.name) / "absent.log"
        with mock.patch.object(subprocess, "run", return_value=_result(ABORTED)) as run:
            self.assertEqual(run_unity(COMMAND, log=missing).returncode, ABORTED)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
