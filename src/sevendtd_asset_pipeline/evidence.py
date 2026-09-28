"""Shared plumbing for the review and capture evidence lanes.

`audio_review.py`, `video_review.py`, and `capture.py` all record hash-addressed
evidence and redact credential-bearing keys before anything is stored. The
helpers below are that one copy: intent documents are decoded and read by the
per-lane `parse_intent` these modules own, so only the decode, read, hashing,
and redaction halves live here.

Redaction also abbreviates the host's home directory. An evidence document is
written to be read by somebody else, and an absolute path carries the account
name of whoever ran the review: `/home/<user>/...` names a person in every
document that cites a clip, an intent file, or an asset source. The path stays
citeable as `~/...`, which is all a reader ever used it for.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import PipelineError

# Keys whose names look credential-bearing are dropped wherever they would
# otherwise land in stored evidence. Credentials are never accepted as
# arguments in the first place; this is the backstop for parameters a caller
# hands the API directly.
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)

# A provider's usage block reports its cost through names like
# `totalTokenCount`, so it cannot share the broad rule above: there "token"
# is billing, not authentication. It keeps every count and still drops the
# names a secret actually travels in.
USAGE_SENSITIVE_KEY_PARTS = tuple(part for part in SENSITIVE_KEY_PARTS if part != "token")


def _is_sensitive_key(key: str, parts: tuple[str, ...] = SENSITIVE_KEY_PARTS) -> bool:
    lowered = key.lower()
    return lowered == "key" or any(part in lowered for part in parts)


def _home_prefix() -> str:
    """This host's home directory as a literal prefix, or `""` when it has none.

    `expanduser("~")` rather than `Path.home()`: a host with no home set
    (`HOME=""`) expands to nothing, and matching the empty string would rewrite
    every string in the document.
    """
    home = os.path.expanduser("~")
    if not home or home == os.sep:
        return ""
    return os.path.normpath(home) + os.sep


def abbreviate_home(text: str) -> str:
    """`/home/someone/...` becomes `~/...`, leaving every other path untouched.

    Only the home prefix goes: the rest of a path is what makes an evidence
    document citeable, and a Windows or relative path that happens to contain
    the same word is not this host's account.
    """
    prefix = _home_prefix()
    if not prefix:
        return text
    if text == prefix.rstrip(os.sep):
        return "~"
    if text.startswith(prefix):
        return "~/" + text[len(prefix) :]
    return text


def redact(value: Any, parts: tuple[str, ...] = SENSITIVE_KEY_PARTS) -> Any:
    """Deep-copy a JSON-shaped value, dropping credential-bearing mapping keys.

    Every string is passed through `abbreviate_home`, so a stored document
    never names the account that produced it.
    """
    if isinstance(value, dict):
        return {
            key: redact(item, parts)
            for key, item in value.items()
            if isinstance(key, str) and not _is_sensitive_key(key, parts)
        }
    if isinstance(value, list):
        return [redact(item, parts) for item in value]
    if isinstance(value, str):
        return abbreviate_home(value)
    return value


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def decode_json(raw: bytes, origin: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{origin} is not valid JSON: {exc}") from exc


def string_field(data: dict[str, Any], key: str, origin: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PipelineError(f"{origin}: field {key!r} must be a string, got {type(value).__name__}")
    return value.strip()


def string_list(data: dict[str, Any], key: str, origin: str) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PipelineError(f"{origin}: field {key!r} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def load_intent_file(path: Path, parse: Callable[[Any, str], Any]) -> tuple[Any, bytes]:
    """Read an intent file, validate it with the lane's `parse`, return both.

    `parse` is the per-lane validator (`parse_intent`), which owns the intent
    shape: audio and video record different fields.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read intent file {path}: {exc}") from exc
    return parse(decode_json(raw, f"intent file {path}"), f"intent file {path}"), raw


def parse_intent_text(text: str, parse: Callable[[Any, str], Any]) -> tuple[Any, bytes]:
    """Validate an inline intent document with the lane's `parse`; return both."""
    raw = text.encode("utf-8")
    return parse(decode_json(raw, "--intent-text"), "--intent-text"), raw
