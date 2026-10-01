"""Shared plumbing for the review and capture evidence lanes.

`audio_review.py`, `video_review.py`, and `capture.py` all record hash-addressed
evidence and redact credential-bearing keys before anything is stored. The
helpers below are that one copy: intent documents are decoded and read by the
per-lane `parse_intent` these modules own, so only the decode, read, hashing,
and redaction halves live here.

Redaction also abbreviates the host's home directory, and scrubs this host's
own credentials out of free text. An evidence document is written to be read
by somebody else, and an absolute path carries the account name of whoever ran
the review: `/home/<user>/...` names a person in every document that cites a
clip, an intent file, or an asset source. The path stays citeable as
`~/...`, which is all a reader ever used it for. A credential reaches the same
document the same way when the gateway inherits this environment and an error
envelope quotes the request that carried the key, and that one has no citeable
part worth keeping.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping
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
    for home in (prefix, os.path.realpath(prefix) + os.sep):
        if text == home.rstrip(os.sep):
            return "~"
        if text.startswith(home):
            return "~/" + text[len(home) :]
    return text


REDACTED = "[redacted]"
# A secret shorter than this is not worth replacing every occurrence of: the
# shortest credential a provider issues is far longer, and a two-character
# "secret" in the environment would otherwise rewrite half the document.
MIN_SECRET_VALUE_LENGTH = 8
# A credential named in free text rather than under a key the drop rule can
# see: an HTTP layer quoting the request that carried it, a gateway envelope
# echoing an Authorization header, a traceback with the URL it was refused
# for. The two markers such a leak carries are the field name it was sent
# under and the scheme that introduces it; the named form is tried first
# because `Authorization: Bearer <key>` is one match, not two.
INLINE_CREDENTIAL = re.compile(
    r"(?i)(?:x-goog-api-key|x-api-key|api[-_]?key|apikey|access[-_]?token"
    r"|auth[-_]?token|authorization|password|secret)[\"']?\s*[:=]\s*[\"']?"
    r"(?:bearer\s+|basic\s+)?[A-Za-z0-9._~+/=-]{8,}"
    r"|\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"
)


def environment_secrets(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The credential-bearing values in this process's environment.

    A provider key is never an argument and never under a key this module can
    drop, so the only place it can reach a stored document is inside a string
    somebody else wrote: the gateway inherits the whole environment, and an
    error envelope from it can quote the request that carried the key. The
    value is known here, so free text can be compared against it.
    """
    environment = os.environ if env is None else env
    return tuple(
        value
        for name, value in environment.items()
        if len(value) >= MIN_SECRET_VALUE_LENGTH
        and _is_sensitive_key(name)
        # A variable named for a token can hold a path instead of a token
        # (`*_FREETOKEN_PATH` names a directory), and a path is already
        # abbreviated to `~/...` where it appears. Replacing one would strip
        # the citation an evidence document exists to keep.
        and not os.path.exists(value)
    )


def scrub(value: str, secrets: tuple[str, ...] | None = None) -> str:
    """Replace this host's credentials, and inline credential syntax, in one string.

    Two passes, because the two leaks have different shapes: a known secret
    has no marker to look for, and an unknown one has no value to compare
    against. Longest first, so a secret that contains another is replaced
    whole rather than leaving a tail behind.
    """
    known = secrets if secrets is not None else environment_secrets()
    for secret in sorted(known, key=len, reverse=True):
        if secret in value:
            value = value.replace(secret, REDACTED)
    return INLINE_CREDENTIAL.sub(REDACTED, value)


def redact(value: Any, parts: tuple[str, ...] = SENSITIVE_KEY_PARTS) -> Any:
    """Deep-copy a JSON-shaped value, dropping credential-bearing mapping keys.

    Every string is passed through `abbreviate_home` and `scrub`, so a stored
    document never names the account that produced it and never carries a
    credential the key-drop rule cannot see.
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
        return scrub(abbreviate_home(value))
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


def refuse_existing_review(path: Path, *, force: bool) -> None:
    """Refuse a re-run whose evidence path is already taken, before anything is spent.

    The exclusive create in :func:`publish_review` is the race-safe half of
    this rule, and it runs after the provider has answered. A review is a
    billable call that also uploads the author's asset to a third party, so
    the same command a retry issues reaches the provider, is charged, and
    only then discovers the path is occupied and raises. This is that same
    check ahead of the call: the evidence path names the logical operation,
    and a run that would be refused at the end is refused before the money
    moves and the bytes leave the machine.

    It is a pre-check, not a substitute. Two runs that pass it together are
    still separated by the exclusive create, which is why both exist.
    """
    if force or not Path(path).exists():
        return
    raise PipelineError(
        f"{path} already holds an earlier review and a later review never "
        "overwrites one by default; compare the documents, or pass --force"
    )


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
    check_intent_size(raw, f"intent file {path}")
    return parse(decode_json(raw, f"intent file {path}"), f"intent file {path}"), raw


def parse_intent_text(text: str, parse: Callable[[Any, str], Any]) -> tuple[Any, bytes]:
    """Validate an inline intent document with the lane's `parse`; return both."""
    raw = text.encode("utf-8")
    check_intent_size(raw, "--intent-text")
    return parse(decode_json(raw, "--intent-text"), "--intent-text"), raw


# -- submission budget --------------------------------------------------------

# What one submission may carry before it is refused locally. The provider
# adapters cap the answer (`MAX_OUTPUT_TOKENS`) and the media
# (`ProviderLimits.max_bytes`); nothing capped what the caller put into the
# prompt, so a large intent document was submitted, tokenized, and billed
# without a limit on either side. An intent is a short record of purpose and
# constraints, so a document past these figures is a mistake rather than a
# use, and the refusal costs nothing while the submission would.
MAX_INTENT_BYTES = 64 * 1024
MAX_PROMPT_CHARACTERS = 32_000
# A wait past this is a wedged provider or a caller who walked away, and either
# way a review that takes a quarter of an hour is not one anybody is waiting
# on. A non-positive or non-finite timeout is not a long wait at all: it
# reaches `socket.settimeout` and fails there, which is a traceback rather
# than the single ERROR line the command surface promises.
MAX_TIMEOUT_SECONDS = 900.0


def check_intent_size(raw: bytes, origin: str) -> None:
    """Refuse an intent document too large to be a recorded intent."""
    if len(raw) > MAX_INTENT_BYTES:
        raise PipelineError(
            f"{origin} is {len(raw)} bytes; an intent document may be at most "
            f"{MAX_INTENT_BYTES}. Record the purpose and the constraints, not "
            "an essay, and point at the source for the rest"
        )


def check_prompt_size(prompt: str, origin: str) -> None:
    """Refuse a prompt whose assembled text is past the submission budget."""
    if len(prompt) > MAX_PROMPT_CHARACTERS:
        raise PipelineError(
            f"the assembled {origin} prompt is {len(prompt)} characters; at most "
            f"{MAX_PROMPT_CHARACTERS} are submitted. Shorten the intent's free "
            "text fields or drop reference clips"
        )


def check_timeout_seconds(value: float, origin: str) -> float:
    """Return a usable timeout, or refuse the one that would fail downstream."""
    if not math.isfinite(value) or value <= 0:
        raise PipelineError(f"{origin} must be a positive number of seconds, got {value!r}")
    if value > MAX_TIMEOUT_SECONDS:
        raise PipelineError(f"{origin} may be at most {MAX_TIMEOUT_SECONDS:g}s, got {value:g}")
    return float(value)


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
