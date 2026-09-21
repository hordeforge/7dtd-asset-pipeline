"""Shared plumbing for the review and capture evidence lanes.

`audio_review.py`, `video_review.py`, and `capture.py` all record hash-addressed
evidence and redact credential-bearing keys before anything is stored. The
helpers below are that one copy: intent documents are decoded and read by the
per-lane `parse_intent` these modules own, so only the decode, read, hashing,
and redaction halves live here.
"""

from __future__ import annotations

import hashlib
import json
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


def redact(value: Any, parts: tuple[str, ...] = SENSITIVE_KEY_PARTS) -> Any:
    """Deep-copy a JSON-shaped value, dropping credential-bearing mapping keys."""
    if isinstance(value, dict):
        return {
            key: redact(item, parts)
            for key, item in value.items()
            if isinstance(key, str) and not _is_sensitive_key(key, parts)
        }
    if isinstance(value, list):
        return [redact(item, parts) for item in value]
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
