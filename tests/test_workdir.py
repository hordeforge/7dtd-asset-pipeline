"""Scratch directories must land on disk, never in tmpfs.

`tempfile`'s default is `/tmp`, which is tmpfs on most Linux hosts. The lanes
that shell out stage real payloads there — a decoded WAV, a rasterized sheet,
a Blender render, a compiled shader blob — so the default charges them against
RAM and loses them on reboot. Every one of those call sites goes through
`workdir.scratch_dir`, and these tests pin the two things that makes true: the
base is the host's user cache directory, and the directory is cleaned up.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sevendtd_asset_pipeline import workdir


class CacheRootTests(unittest.TestCase):
    def test_honours_xdg_cache_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": temp}):
                root = workdir.cache_root()
            self.assertEqual(Path(temp) / "shamway", root)
            self.assertTrue(root.is_dir())

    def test_falls_back_to_dot_cache_under_home_on_linux(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with (
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch.object(Path, "home", return_value=home),
                mock.patch("sevendtd_asset_pipeline.workdir.sys.platform", "linux"),
            ):
                root = workdir.cache_root()
            self.assertEqual(home / ".cache" / "shamway", root)
            self.assertTrue(root.is_dir())

    def test_falls_back_to_library_caches_on_macos(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with (
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch.object(Path, "home", return_value=home),
                mock.patch("sevendtd_asset_pipeline.workdir.sys.platform", "darwin"),
            ):
                root = workdir.cache_root()
            self.assertEqual(home / "Library" / "Caches" / "shamway", root)
            self.assertTrue(root.is_dir())

    def test_falls_back_to_localappdata_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            local = Path(temp) / "Local"
            local.mkdir()
            with (
                mock.patch.dict("os.environ", {"LOCALAPPDATA": str(local)}, clear=True),
                mock.patch("sevendtd_asset_pipeline.workdir.sys.platform", "win32"),
            ):
                root = workdir.cache_root()
            self.assertEqual(local / "shamway", root)
            self.assertTrue(root.is_dir())


class ScratchDirTests(unittest.TestCase):
    def test_the_directory_sits_under_the_cache_root_not_the_default_tempdir(self) -> None:
        """The whole point: `dir=` is passed, so tempfile's /tmp default is unused."""
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
            workdir.scratch_dir("probe-") as scratch,
        ):
            self.assertEqual(Path(temp) / "shamway", scratch.parent)
            self.assertTrue(scratch.is_dir())
            self.assertTrue(scratch.name.startswith("probe-"))

    def test_the_directory_and_its_contents_are_removed_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with (
                mock.patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
                workdir.scratch_dir("probe-") as scratch,
            ):
                (scratch / "payload.bin").write_bytes(b"x" * 1024)
                staged = scratch
            self.assertFalse(staged.exists())

    def test_two_scratch_dirs_never_collide(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.dict("os.environ", {"XDG_CACHE_HOME": temp}),
            workdir.scratch_dir("probe-") as first,
            workdir.scratch_dir("probe-") as second,
        ):
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
