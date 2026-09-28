"""Pin a helper script's stdio to UTF-8, whatever the host locale says.

CPython derives a stream's encoding from the process locale, so a host running
`LC_ALL=C` hands these scripts ASCII stdio. A non-ASCII path does not then
raise: `errors="surrogateescape"` decodes each stray byte to U+DC80..U+DCFF and
re-encodes it unchanged, so the bytes survive the round trip and the wrong
characters come out. `json_field.py` exists to hand a shell a filesystem path,
and a path made of lone surrogates is not one any command can open.

A sibling of `cli._utf8_console`, which does the same for the CLI's own output.
It lives beside the scripts rather than in the package so a shell can call them
with a bare `python3`, with no install and no import path to set.
"""

from __future__ import annotations

import sys

_STREAMS = ("stdin", "stdout", "stderr")


def _restore_argv(argv: list[str]) -> list[str]:
    """The UTF-8 the caller typed, recovered from what a non-UTF-8 locale decoded.

    The kernel hands a process raw bytes. A locale that is not UTF-8 decodes
    them as the filesystem encoding with `surrogateescape`, so a non-ASCII
    argument arrives as lone surrogates. Re-encoding with that same pair and
    decoding as UTF-8 gives back the text, and comparing it against a stdin
    payload decoded as UTF-8 then matches instead of silently differing.
    """
    encoding = sys.getfilesystemencoding()
    restored: list[str] = []
    for argument in argv:
        try:
            restored.append(argument.encode(encoding, "surrogateescape").decode("utf-8"))
        except (UnicodeDecodeError, UnicodeEncodeError):
            restored.append(argument)
    return restored


def configure() -> None:
    """Decode and encode this process's stdio and argv as UTF-8.

    A stream with no `reconfigure` (a captured pipe, a StringIO) is left alone,
    as is a detached stream whose buffers are already gone.
    """
    sys.argv[1:] = _restore_argv(sys.argv[1:])
    for name in _STREAMS:
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):  # pragma: no cover - detached stream
            continue
