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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import atomic
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


def publish_review(path: Path, payload: str, *, force: bool) -> Path:
    """Publish a review document, never silently replacing an earlier one.

    A review is evidence, and a second run of the same lane against the same
    output path is the normal shape of a retry. Asking whether the file exists
    and then writing it is not that guarantee: the two are separate steps, so
    a run that dies, a second session, or a fresh review that arrives in the
    gap replaces the first document with no trace it was there. The exclusive
    create is one step, so the loser learns the path is taken instead of
    destroying the winner's verdict.

    `force` is the deliberate overwrite, and it is the only way one review
    replaces another.
    """
    try:
        if force:
            atomic.write(path, payload)
        else:
            atomic.write_new(path, payload)
    except FileExistsError as exc:
        raise PipelineError(
            f"{path} already holds an earlier review and a later review never "
            "overwrites one by default; compare the documents, or pass --force"
        ) from exc
    return path


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


@dataclass(frozen=True)
class ReferenceAsset:
    """A comparison asset the author supplies, and what it is being compared for.

    Audio names one a clip and video names one a medium; the intent document
    carries the same two fields either way, so this is the one shape both
    lanes read.
    """

    path: Path
    purpose: str


def parse_references(data: dict[str, Any], origin: str) -> tuple[ReferenceAsset, ...]:
    """Read an intent document's `references` array, or nothing when it is absent.

    An absent array is an empty tuple; a present one must be a list whose every
    entry names exactly a `path` and a `purpose`, because a reference with no
    stated purpose gives a reviewer nothing to compare against.
    """
    raw_references = data.get("references")
    if raw_references is None:
        return ()
    if not isinstance(raw_references, list):
        raise PipelineError(f"{origin}: 'references' must be a list")
    references: list[ReferenceAsset] = []
    for index, entry in enumerate(raw_references):
        label = f"{origin}: reference #{index + 1}"
        if not isinstance(entry, dict) or set(entry) != {"path", "purpose"}:
            raise PipelineError(f"{label}: each reference needs exactly 'path' and 'purpose'")
        reference_path = entry["path"]
        reference_purpose = entry["purpose"]
        if not isinstance(reference_path, str) or not reference_path:
            raise PipelineError(f"{label}: 'path' must be a non-empty string")
        if not isinstance(reference_purpose, str) or not reference_purpose.strip():
            raise PipelineError(f"{label}: 'purpose' must state what the comparison is for")
        references.append(
            ReferenceAsset(path=Path(reference_path), purpose=reference_purpose.strip())
        )
    return tuple(references)


# A review's own confidence, in 0-1, and every rubric dimension's score, in
# 0-5. Both ranges are the seven-key result shape the deadeye gateway and the
# audio lane agree on, so they are named once rather than repeated as literals.
CONFIDENCE_RANGE = (0.0, 1.0)
SCORE_RANGE = (0.0, 5.0)


def read_scores(
    raw_scores: Any, known: frozenset[str] | None = None
) -> tuple[dict[str, float | None], list[str]]:
    """Read a `rubric_scores` object, returning the scores and every problem.

    A value is a score inside `SCORE_RANGE`, or an explicit null for a
    dimension the reviewer could not judge. `known` pins the dimension names
    when the lane owns its rubric: a lane that defers the names to the
    gateway passes None and has only the values checked.
    """
    if not isinstance(raw_scores, dict):
        return {}, ["rubric_scores must be an object keyed by rubric dimension"]
    problems: list[str] = []
    scores: dict[str, float | None] = {}
    if known is not None:
        unscored = sorted(known - set(raw_scores))
        if unscored:
            # The prompt asks for every dimension, and a verdict that silently
            # omits one reads to a reviewer as a dimension that was scored and
            # found fine. An unjudgeable dimension is spelled null instead.
            problems.append(
                "rubric_scores leaves dimension(s) unstated: "
                + ", ".join(unscored)
                + " (score each one, or use null)"
            )
    for key, value in raw_scores.items():
        if known is not None and key not in known:
            problems.append(
                f"rubric_scores names unknown dimension {key!r}; expected: "
                + ", ".join(sorted(known))
            )
            continue
        if value is None:
            scores[key] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"rubric_scores[{key!r}] must be a number or null")
        elif not SCORE_RANGE[0] <= value <= SCORE_RANGE[1]:
            problems.append(
                f"rubric_scores[{key!r}] must be within {SCORE_RANGE[0]:g}-{SCORE_RANGE[1]:g}"
            )
        else:
            scores[key] = float(value)
    return scores, problems


def read_confidence(value: Any) -> tuple[float, str | None]:
    """Read a `confidence` inside `CONFIDENCE_RANGE`, returning it or the problem."""
    low, high = CONFIDENCE_RANGE
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        return 0.0, f"confidence must be a number between {low:g} and {high:g}"
    return float(value), None


# The seven keys every review answer carries, whatever produced it. The audio
# lane sends this shape to a model and the video lane reads it back from the
# deadeye gateway; both refuse a deviation rather than coercing one.
RESULT_KEYS = (
    "summary",
    "strengths",
    "issues",
    "recommended_changes",
    "rubric_scores",
    "confidence",
    "limitations",
)


def check_result_keys(data: dict[str, Any], origin: str) -> None:
    """Raise unless `data` carries exactly `RESULT_KEYS`, naming every deviation."""
    problems: list[str] = []
    missing = [key for key in RESULT_KEYS if key not in data]
    if missing:
        problems.append(f"missing key(s): {', '.join(missing)}")
    extra = sorted(set(data) - set(RESULT_KEYS))
    if extra:
        problems.append(f"unexpected key(s): {', '.join(extra)}")
    if problems:
        raise PipelineError(f"{origin} returned an invalid structure: {'; '.join(problems)}")


def read_string_list(value: Any, key: str) -> tuple[list[str], str | None]:
    """Read one of the result's string arrays, returning it or the problem."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [], f"{key} must be an array of strings"
    return [item for item in value if item.strip()], None


def read_summary(value: Any) -> tuple[str, str | None]:
    """Read the result's one-sentence verdict, returning it or the problem."""
    if not isinstance(value, str) or not value.strip():
        return "", "summary must be a non-empty string"
    return value.strip(), None
