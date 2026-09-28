#!/usr/bin/env python3
"""Rewrite a built sdist with normalized archive metadata.

`uv build` already honors SOURCE_DATE_EPOCH for the wheel's zip entries, and
the payload of both artifacts is deterministic. The sdist is not: setuptools'
archive carries the build machine's clock (every member mtime, plus the gzip
header), the build user's uid, gid, uname and gname, and whatever mode the
checkout happened to have. Two builds of one commit therefore differ, which is
what makes "rebuild and compare" impossible to run without noise.

`make dist` calls this on every `.tar.gz` it just built. It changes no file
content: `uv build` already produces the same bytes for the same inputs, and
this only replaces the metadata around them.

Also usable directly: `scripts/normalize_dist.py dist/*.tar.gz`.
"""

from __future__ import annotations

import argparse
import gzip
import io
import tarfile
from pathlib import Path

# Everything the archive records about the machine that built it, replaced with
# values that depend only on the source tree.
FIXED_MTIME = 0
FIXED_UID = 0
FIXED_GID = 0
FIXED_UNAME = ""
FIXED_GNAME = ""
DIR_MODE = 0o755
FILE_MODE = 0o644
# A wheel's zip is already byte-stable under SOURCE_DATE_EPOCH, and rewriting
# one would mean re-implementing zip ordering; the sdist is the artifact that
# needs this, so only tarballs are accepted.
SDIST_SUFFIXES = (".tar.gz",)


def normalized_sdist(data: bytes, epoch: int) -> bytes:
    """The same tar, with sorted members and machine-independent metadata."""
    with tarfile.open(fileobj=io.BytesIO(data)) as source:
        members = sorted(source.getmembers(), key=lambda member: member.name)
        payload = {
            member.name: (handle.read() if (handle := source.extractfile(member)) else b"")
            for member in members
            if member.isfile()
        }
        scratch = io.BytesIO()
        # format=PAX because that is what setuptools writes, and a tar read
        # back by pip must be the same dialect it was written in.
        with tarfile.open(fileobj=scratch, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for member in members:
                # TarInfo is mutable, so this rewrites the members the source
                # archive handed over rather than copying each one field by field.
                entry = member
                # A PAX archive keeps the precise mtime in a pax header record,
                # and that record wins over the field when the member is written
                # back out. setuptools writes one per member, so it is dropped
                # with the rest rather than re-asserting the build clock.
                entry.pax_headers = {}
                entry.uid = FIXED_UID
                entry.gid = FIXED_GID
                entry.uname = FIXED_UNAME
                entry.gname = FIXED_GNAME
                entry.mtime = epoch
                entry.mode = DIR_MODE if member.isdir() else FILE_MODE
                if member.isfile():
                    archive.addfile(entry, io.BytesIO(payload[member.name]))
                else:
                    archive.addfile(entry)
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=epoch) as wrapper:
        wrapper.write(scratch.getvalue())
    return compressed.getvalue()


def normalize(path: Path, epoch: int) -> bool:
    """Normalize one sdist in place. Returns whether the bytes changed.

    A path that is not a tarball is left exactly as it is: the wheel is already
    byte-stable under SOURCE_DATE_EPOCH, and rewriting a zip here would mean
    re-implementing its central directory.
    """
    if not path.name.endswith(SDIST_SUFFIXES):
        return False
    original = path.read_bytes()
    rewritten = normalized_sdist(original, epoch)
    if rewritten == original:
        return False
    path.write_bytes(rewritten)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--epoch",
        type=int,
        required=True,
        help="the mtime every member gets; the build's SOURCE_DATE_EPOCH",
    )
    parser.add_argument("artifacts", nargs="+", type=Path, help="the built files to normalize")
    args = parser.parse_args(argv)
    for path in args.artifacts:
        if normalize(path, args.epoch):
            print(f"normalized {path}")
        elif path.name.endswith(SDIST_SUFFIXES):
            print(f"unchanged {path}")
        else:
            print(f"skipped {path} (not a tarball)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
