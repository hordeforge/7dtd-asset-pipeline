"""The two text policies this package applies at its own boundaries.

Bytes arriving from outside, and names used as identity, are the two places
where this package's text handling was once implicit. Both are now one named
answer, and every boundary imports it rather than restating a policy.

**Bytes in.** A child's stdout, an external tool's diagnostics, a file on disk:
each has a declared or expected encoding, and each is decoded as one rather
than as the host's preferred codec. `subprocess(..., text=True)` without an
`encoding` decodes with `locale.getpreferredencoding(False)`, so the same
command yields different text on a German, a Turkish and a C-locale host, and
raises `UnicodeDecodeError` on the first byte a child emitted in anything else
(a Windows tool's local codepage, a filename in a legacy encoding) rather
than reporting the diagnostic that byte was part of. `CHILD_ENCODING` and
`CHILD_DECODE_ERRORS` are the answer: UTF-8, with undecodable bytes replaced
so a diagnostic survives the trip that produced it.

**A file's own encoding statement.** A file on disk names its encoding twice
over, in two statements that stand in for each other, and a decoder has to
read whichever one it can. An XML declaration is readable, but only out of
bytes that are already text, so it answers for a legacy code page and not for
UTF-16 or UTF-32, whose declaration is ASCII sitting among bytes that are not.
A byte-order mark is the reverse: it is readable from any bytes, and it is the
only statement a Windows editor's "Unicode" save, Visual Studio, or a .NET
`Encoding.Unicode` writer puts in the file. `bom_encoding` is that answer, and
a boundary that has a declaration reads the mark first and the declaration
only once the bytes are decoded far enough to hold one.

**Names in.** A bundle member, an atlas PNG, a `CustomIcon` key and a
`Localization.csv` row are all identity: 7DTD resolves an asset by its name,
so two spellings of one name are two names. `folded` is what two names are
compared as, so a name copied out of a macOS filename (NFD) and the same word
typed into `Config/` (NFC) are one key rather than a lookup that misses.
Folding is for the *comparison* only. Where the two names are not
byte-identical the callers report the pair by name (`spelling_differences`
exists for that message), because the engine resolves against the table it
loaded and a fold here is not a fold there: silently treating them as equal
would turn a gate into a pass the game does not reproduce.

A name is also a path component on a host this package does not choose, and
Windows refuses more of them than every other target does. The reserved
characters and device names below are the shared answer, so a name a
generator writes on Linux is the same name one written on Windows.
"""

from __future__ import annotations

import codecs
import re
import unicodedata
from collections.abc import Iterator, Sequence
from functools import cache

# What every child's stdout and stderr is decoded as. UTF-8 is the encoding
# these tools emit on every platform this pipeline is used on, and the one
# this pipeline writes and reads its own files in.
CHILD_ENCODING = "utf-8"
# A diagnostic is evidence, so an undecodable byte in it is replaced rather
# than raised: the caller still gets the line, and no traceback replaces the
# single ERROR line the CLI promises.
CHILD_DECODE_ERRORS = "replace"

# A byte-order mark is the one encoding statement that is readable from bytes
# that are not yet decoded: the four Unicode marks, longest first, because
# UTF-32LE begins with the UTF-16LE mark. `utf-16` and `utf-32` are the
# endianness-detecting codecs, so one entry answers both byte orders and
# consumes the mark; `utf-8-sig` consumes the UTF-8 one the same way.
UTF8_BOM_ENCODING = "utf-8-sig"
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
    (codecs.BOM_UTF8, UTF8_BOM_ENCODING),
)


def bom_encoding(raw: bytes) -> str | None:
    """The codec a leading byte-order mark names, or `None` when there is none.

    A file's own declaration cannot be read out of a UTF-16 or UTF-32 file: the
    declaration is ASCII sitting among bytes that are not, so the question has
    to be answered before the bytes are text. The mark is the standard answer
    and it is what the writers emit: a Windows editor's "Unicode" save, Visual
    Studio, Excel's "Unicode Text", and every .NET `Encoding.Unicode` /
    `Encoding.BigEndianUnicode` writer put one at the front and say nothing
    else. A reader that skips the mark has no declaration to fall back on
    either, and reports the whole file as undecodable.

    `UTF8_BOM_ENCODING` is the one answer that is not the whole statement: a
    UTF-8 file may still carry a declaration, and a boundary that reads
    declarations has to read it.
    """
    for mark, encoding in _BOMS:
        if raw.startswith(mark):
            return encoding
    return None


def nfc(text: str) -> str:
    """The composed (NFC) spelling of `text`, as ICU's `uconv -x Any-NFC` writes it."""
    return unicodedata.normalize("NFC", text)


def folded(text: str) -> str:
    """`text` composed and case-folded: the key every name comparison shares.

    Case folding rather than `lower()`, so a comparison is not decided by the
    host's locale the way a Turkish dotless `i` would decide it.
    """
    return nfc(text).casefold()


CASES = "case"
NORMALIZATION = "Unicode normalization form, one composed and one decomposed"


@cache
def _value_pattern(name: str) -> re.Pattern[str]:
    """`name`/`value` in either order, cached: the discovery functions below
    run this against every Config/ XML, and compiling inside that loop paid a
    cache miss per file for nothing."""
    return re.compile(
        rf'name\s*=\s*"{name}"\s+value\s*=\s*"([^"]+)"|'
        rf'value\s*=\s*"([^"]+)"\s+name\s*=\s*"{name}"'
    )


def attribute_values(text: str, names: Sequence[str]) -> Iterator[str]:
    """Every value of a `<property name=... value=.../>` in `text`.

    A regex rather than a parse, and the reason is the input: a mod's Config/
    files are XPath patch fragments, and a fragment with several roots is not a
    document. Duplicates are kept, because the caller maps each value to the
    file that asked for it and a name referenced twice in one file is one fact
    about that file.
    """
    for name in names:
        for match in _value_pattern(name).finditer(text):
            yield (match.group(1) or match.group(2)).strip()


def spelling_differences(left: str, right: str) -> tuple[str, ...]:
    """The ways two names that fold to one key are still different strings.

    A macOS filename arrives decomposed, the key an author typed is composed,
    and a stem typed in a different case is a different stem: each pair folds
    alike and is not the same string, so a comparison that folded alone would
    call it resolved and the engine would not.

    The two aspects are answered apart and both are reported when both apply,
    because a name differing in case *and* in composition needs both renamed
    and a message naming one of them brings the reader back with the same
    failure. The two are compared composed, so neither answer is decided by the
    other: `mymodthing` against `myModThing` is a case difference, and
    `café` against the same word decomposed is a normalization one.
    """
    composed, other = nfc(left), nfc(right)
    differences: list[str] = []
    if composed != other:
        differences.append(CASES)
    if left != composed or other != composed:
        differences.append(NORMALIZATION)
    return tuple(differences)


# What a path component may not be, on the platform that refuses the most.
# Every POSIX host accepts these names, so one carrying any of them is created
# without complaint on Linux and refused inside the next `mkdir` on Windows,
# as a raw OSError rather than the PipelineError the caller promised.
WINDOWS_RESERVED_CHARS = frozenset(': * ? " < > |')
# A reserved device name stays reserved behind any extension, so `CON.png` is
# the console device and not a file.
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def names_windows_device(name: str) -> bool:
    """Whether a path component names a reserved Windows device.

    The device is named by the part before the first dot, so the extension a
    caller appends later does not change the answer.
    """
    return name.partition(".")[0].upper() in WINDOWS_RESERVED_NAMES
