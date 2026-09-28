"""The sdist normalizer must erase the build machine and touch no content.

`make reproducible` is the only gate that notices a timestamp or a uid reaching
the published sdist, and it is a slow one. These tests drive the normalizer
directly: they hand it two archives built with different clocks and different
owners and require the same bytes out, with every file's content preserved.
"""

from __future__ import annotations

import gzip
import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import normalize_dist

EPOCH = 1700000000


def sdist(entries: dict[str, bytes], mtime: int, uid: int, uname: str) -> bytes:
    """A tarball shaped like the one setuptools writes, built at `mtime`.

    The sub-second part is deliberate: a float mtime is what makes tarfile
    write a PAX header record, and setuptools' members all carry one.
    """
    scratch = io.BytesIO()
    with tarfile.open(fileobj=scratch, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = float(mtime) + 0.25
            info.mode = 0o600
            info.uid = uid
            info.gid = uid
            info.uname = uname
            info.gname = uname
            archive.addfile(info, io.BytesIO(payload))
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=mtime) as archive:
        archive.write(scratch.getvalue())
    return out.getvalue()


def _body(archive: tarfile.TarFile, entry: tarfile.TarInfo) -> bytes:
    if not entry.isfile():
        return b""
    handle = archive.extractfile(entry)
    return b"" if handle is None else handle.read()


def members(data: bytes) -> dict[str, tuple[tarfile.TarInfo, bytes]]:
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return {entry.name: (entry, _body(archive, entry)) for entry in archive.getmembers()}


class NormalizedSdistTests(unittest.TestCase):
    def test_two_builds_of_one_tree_normalize_to_the_same_bytes(self) -> None:
        entries = {"pkg-0.1.0/PKG-INFO": b"Name: pkg\n", "pkg-0.1.0/mod.py": b"x = 1\n"}
        first = normalize_dist.normalized_sdist(sdist(entries, 1600000000, 1000, "alice"), EPOCH)
        second = normalize_dist.normalized_sdist(sdist(entries, 1700000123, 0, "buildbot"), EPOCH)
        self.assertEqual(first, second)

    def test_content_survives_and_is_identical(self) -> None:
        entries = {"pkg-0.1.0/mod.py": b"x = 1\n", "pkg-0.1.0/data/payload": b"\x00\xff bytes"}
        rewritten = members(
            normalize_dist.normalized_sdist(sdist(entries, 1600000000, 7, "a"), EPOCH)
        )
        self.assertEqual({name: body for name, (_, body) in rewritten.items()}, entries)

    def test_machine_metadata_is_gone(self) -> None:
        rewritten = members(
            normalize_dist.normalized_sdist(sdist({"pkg/mod.py": b""}, 1, 4242, "ci"), EPOCH)
        )
        for name, (info, _) in rewritten.items():
            with self.subTest(name=name):
                self.assertEqual(info.mtime, EPOCH)
                self.assertEqual((info.uid, info.gid), (0, 0))
                self.assertEqual((info.uname, info.gname), ("", ""))
                self.assertEqual(info.mode, 0o644)

    def test_a_pax_mtime_record_does_not_survive_the_rewrite(self) -> None:
        # setuptools writes a sub-second mtime, which tarfile carries in a PAX
        # header record rather than the member field, and that record wins when
        # the member is written back out. Normalizing only the field left the
        # build clock in every entry.
        original = sdist({"pkg/mod.py": b""}, 1600000000, 0, "u")
        with tarfile.open(fileobj=io.BytesIO(original)) as archive:
            self.assertTrue(any("mtime" in entry.pax_headers for entry in archive.getmembers()))
        rewritten = members(normalize_dist.normalized_sdist(original, EPOCH))
        for name, (info, _) in rewritten.items():
            with self.subTest(name=name):
                self.assertEqual(info.mtime, EPOCH)

    def test_directories_keep_the_executable_bit(self) -> None:
        scratch = io.BytesIO()
        with tarfile.open(fileobj=scratch, mode="w", format=tarfile.PAX_FORMAT) as archive:
            entry = tarfile.TarInfo("pkg-0.1.0")
            entry.type = tarfile.DIRTYPE
            archive.addfile(entry)
        rewritten = members(normalize_dist.normalized_sdist(scratch.getvalue(), EPOCH))
        self.assertEqual(rewritten["pkg-0.1.0"][0].mode, 0o755)

    def test_member_order_does_not_depend_on_the_source_order(self) -> None:
        forward = sdist({"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"}, 1, 0, "u")
        backward = sdist({"c.txt": b"c", "b.txt": b"b", "a.txt": b"a"}, 1, 0, "u")
        self.assertEqual(
            normalize_dist.normalized_sdist(forward, EPOCH),
            normalize_dist.normalized_sdist(backward, EPOCH),
        )


class NormalizeFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_normalize_reports_whether_it_changed_anything(self) -> None:
        path = self.root / "pkg-0.1.0.tar.gz"
        path.write_bytes(sdist({"pkg/mod.py": b"x = 1\n"}, 1600000000, 1000, "alice"))
        self.assertTrue(normalize_dist.normalize(path, EPOCH))
        self.assertFalse(normalize_dist.normalize(path, EPOCH))

    def test_a_wheel_is_left_alone_and_named(self) -> None:
        path = self.root / "pkg-0.1.0-py3-none-any.whl"
        path.write_bytes(b"PK\x03\x04not really a wheel")
        self.assertFalse(normalize_dist.normalize(path, EPOCH))
        self.assertEqual(path.read_bytes(), b"PK\x03\x04not really a wheel")
