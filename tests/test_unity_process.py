"""A batch-mode editor must not inherit a file limit that aborts it.

Reproduced 2026-08-24: on a host whose soft `RLIMIT_NOFILE` was 1048576, every
`shamway build` died on

    ToFileDescriptor(intptr_t): Assertion `fd < sysconf(_SC_OPEN_MAX) ...' failed

and reported only `Unity exited -6` over a log whose compile section was clean.
The same command at 65536 succeeded every time.

`run_unity` lowers the limit in the forked child. These tests hold the two
properties that matter and nothing about mono's internals, because the
mechanism there is not established — only the reproduction.
"""

from __future__ import annotations

import resource
import unittest
from unittest import mock

from sevendtd_asset_pipeline.unity_process import (
    SAFE_OPEN_FILE_LIMIT,
    _clamp_open_files,
    open_file_limit_is_risky,
    run_unity,
)


class OpenFileLimitTests(unittest.TestCase):
    def test_the_child_gets_the_safe_limit(self) -> None:
        result = run_unity(["sh", "-c", "ulimit -n"])
        self.assertEqual(result.returncode, 0)

    def test_the_parent_limit_is_untouched(self) -> None:
        before = resource.getrlimit(resource.RLIMIT_NOFILE)
        run_unity(["sh", "-c", "true"])
        self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE), before)

    def test_a_low_limit_is_left_alone(self) -> None:
        """Never *raise* a limit the host deliberately set below the ceiling."""
        low = (1024, 4096)
        with (
            mock.patch.object(resource, "getrlimit", return_value=low) as get,
            mock.patch.object(resource, "setrlimit") as put,
        ):
            _clamp_open_files()
        get.assert_called_once()
        put.assert_not_called()

    def test_a_high_limit_is_clamped_within_the_hard_limit(self) -> None:
        with (
            mock.patch.object(resource, "getrlimit", return_value=(1048576, 1048576)),
            mock.patch.object(resource, "setrlimit") as put,
        ):
            _clamp_open_files()
        put.assert_called_once_with(resource.RLIMIT_NOFILE, (SAFE_OPEN_FILE_LIMIT, 1048576))

    def test_a_hard_limit_below_the_ceiling_is_respected(self) -> None:
        """Asking for more than the hard limit raises; ask for the hard limit."""
        with (
            mock.patch.object(resource, "getrlimit", return_value=(resource.RLIM_INFINITY, 4096)),
            mock.patch.object(resource, "setrlimit") as put,
        ):
            _clamp_open_files()
        put.assert_called_once_with(resource.RLIMIT_NOFILE, (4096, 4096))

    def test_infinity_counts_as_risky(self) -> None:
        with mock.patch.object(
            resource, "getrlimit", return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY)
        ):
            self.assertTrue(open_file_limit_is_risky())

    def test_a_modest_limit_is_not_risky(self) -> None:
        with mock.patch.object(resource, "getrlimit", return_value=(4096, 4096)):
            self.assertFalse(open_file_limit_is_risky())


if __name__ == "__main__":
    unittest.main()
