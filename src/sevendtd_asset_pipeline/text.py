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

import unicodedata

# What every child's stdout and stderr is decoded as. UTF-8 is the encoding
# these tools emit on every platform this pipeline is used on, and the one
# this pipeline writes and reads its own files in.
CHILD_ENCODING = "utf-8"
# A diagnostic is evidence, so an undecodable byte in it is replaced rather
# than raised: the caller still gets the line, and no traceback replaces the
# single ERROR line the CLI promises.
CHILD_DECODE_ERRORS = "replace"


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
