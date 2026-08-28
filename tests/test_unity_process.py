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

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline.icon_render import _graphics_device_args
from sevendtd_asset_pipeline.unity_process import (
    ABORT_SIGNATURE,
    ABORTED,
    MAX_ATTEMPTS,
    editor_data_dir,
    run_unity,
    windows_standalone_support,
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


def _alive(pid: int) -> bool:
    """Whether a process id still names *something*, zombies included."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@unittest.skipUnless(os.name == "posix", "process groups are POSIX")
class BoundedKillTests(unittest.TestCase):
    """A timed-out editor must take the worker children it spawned with it.

    A batch-mode editor runs AssetImportWorker subprocesses; killing only the
    direct child orphans them against Library/ and the next launch hangs on
    the lock. These tests use a shell that forks its own child so the group
    actually has two members to lose.
    """

    GRACE_SECONDS = 5.0

    def test_a_child_that_finishes_in_time_returns_normally(self) -> None:
        self.assertEqual(run_unity(["true"], timeout=30).returncode, 0)

    def test_timeout_raises_and_leaves_no_orphan_behind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pids_file = Path(directory) / "pids"
            # `sleep` is exec'd directly by some shells when it is the only
            # command; backgrounding it guarantees a real grandchild.
            script = f"echo $$ > {pids_file}; sleep 30 & echo $! >> {pids_file}; wait"
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                run_unity(["bash", "-c", script], timeout=1.0)
            # The kill must have been prompt, not the timeout silently ignored.
            self.assertLess(time.monotonic() - started, 10.0)
            pids = [int(value) for value in pids_file.read_text(encoding="utf-8").split()]
            deadline = time.monotonic() + self.GRACE_SECONDS
            while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
                time.sleep(0.05)
            for pid in pids:
                self.assertFalse(_alive(pid), f"pid {pid} survived the timeout")


class EditorDataDirTests(unittest.TestCase):
    """UNITY_EDITOR's assembly root is probed from the binary, not the OS name.

    `doctor` and `build` look for Windows Build Support under this directory.
    A macOS Hub install puts the binary at Contents/MacOS/Unity and the
    assemblies at Contents/, so dirname/Data is the wrong tree.
    """

    def test_linux_and_windows_layout_is_editor_slash_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "Editor" / "Data"
            (data / "Managed").mkdir(parents=True)
            editor = root / "Editor" / "Unity"
            editor.write_text("", encoding="utf-8")
            self.assertEqual(editor_data_dir(editor), data)
            self.assertEqual(
                windows_standalone_support(editor),
                data
                / "PlaybackEngines"
                / "WindowsStandaloneSupport"
                / "UnityEditor.WindowsStandalone.Extensions.dll",
            )

    def test_macos_app_bundle_layout_is_contents_not_macos_slash_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contents = Path(temp) / "Unity.app" / "Contents"
            macos = contents / "MacOS"
            macos.mkdir(parents=True)
            (contents / "Managed").mkdir()
            editor = macos / "Unity"
            editor.write_text("", encoding="utf-8")
            self.assertEqual(editor_data_dir(editor), contents)
            self.assertEqual(
                windows_standalone_support(editor),
                contents
                / "PlaybackEngines"
                / "WindowsStandaloneSupport"
                / "UnityEditor.WindowsStandalone.Extensions.dll",
            )

    def test_a_missing_tree_still_reports_the_linux_spelling(self) -> None:
        editor = Path("Editor") / "Unity"
        self.assertEqual(editor_data_dir(editor), Path("Editor") / "Data")


class GraphicsDeviceArgsTests(unittest.TestCase):
    """render-icon must not pin GLCore on hosts whose editor is Metal or D3D11."""

    def test_linux_asks_for_glcore(self) -> None:
        with mock.patch("sevendtd_asset_pipeline.icon_render.sys.platform", "linux"):
            self.assertEqual(_graphics_device_args(), ["-force-glcore"])

    def test_macos_and_windows_leave_the_editor_to_pick(self) -> None:
        with mock.patch("sevendtd_asset_pipeline.icon_render.sys.platform", "darwin"):
            self.assertEqual(_graphics_device_args(), [])
        with mock.patch("sevendtd_asset_pipeline.icon_render.sys.platform", "win32"):
            self.assertEqual(_graphics_device_args(), [])


if __name__ == "__main__":
    unittest.main()
