"""Advisory semantic review of an adopted clip by a configured vision model.

`render-icon` renders a candidate mesh with headless Blender: fast, no editor,
but no lighting, no animation, no pose, no engine. `client capture` proves a
person looked at a real, in-game moment, but it is one frame, chosen and
framed by a human at capture time. Neither shows a worn, placed, or moving
asset the way a player actually sees it, and a still cannot show a defect that
only exists in motion: a garment that clips only mid-turn, a prop whose
silhouette reads wrong only while carried, a shader that pops at an angle the
render never sampled.

This module submits an already-captured clip (adopted with `shamway client
capture --clip`, so the frames, the observable, and the capture's own hashes
are on record) plus the asset's recorded intent to the **deadeye** gateway —
the shared vision-model review component in `hordeforge/7dtd-vision-review` —
and normalizes what comes back into the same result family the audio review
uses, so a caller handling both review kinds reads one shape.

Three boundaries are load-bearing, mirroring the audio-review lane:

- **Consent comes before everything.** The submission is networked, billable,
  and sends an authored asset to a third party. Every refusal below happens
  before anything is uploaded, and the consent gate comes first of all.
- **The result schema is ours, not the vendor's.** deadeye validates the model
  payload at its boundary; this module re-validates the shared result shape as
  the offline backstop. A raw response is preserved only when explicitly
  requested, redacted either way.
- **A verdict here is evidence, never acceptance.** Nothing in this module can
  mark an asset accepted; that remains the human look in a fresh client.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import atomic
from ._version import __version__
from .capture import DEFAULT_ROOT, read_manifest
from .config import PipelineConfig
from .errors import PipelineError
from .references import manifest_assets

if TYPE_CHECKING:
    from collections.abc import Sequence

INTENT_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1

DEFAULT_PROVIDER = "gemini"
DEFAULT_TIMEOUT_SECONDS = 120.0

CAMERA_PATHS = ("turntable", "walk-cycle", "fixed", "first-person")

ADVISORY_NOTE = (
    "Advisory only: a model critique is evidence about the submitted clip "
    "under the recorded intent. It cannot satisfy the fresh-client human-look "
    "acceptance gate."
)

GATEWAY = "deadeye"
GATEWAY_INSTALL_HINT = (
    "install the deadeye gateway from hordeforge/7dtd-vision-review and put it "
    "on PATH, e.g. with: uv tool install --from git+https://github.com/hordeforge/7dtd-vision-review"
)

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


# -- intent -------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceMedia:
    """A comparison asset the author supplies, and why it is worth seeing."""

    path: Path
    purpose: str


@dataclass(frozen=True)
class VideoReviewIntent:
    """The recorded intended use a reviewer needs besides the footage."""

    purpose: str
    subject: str
    camera_path: str
    desired_qualities: str
    avoid: tuple[str, ...]
    references: tuple[ReferenceMedia, ...]
    questions: tuple[str, ...]
    suite: str
    case: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "subject": self.subject,
            "camera_path": self.camera_path,
            "desired_qualities": self.desired_qualities,
            "avoid": list(self.avoid),
            "references": [
                {"path": str(item.path), "purpose": item.purpose} for item in self.references
            ],
            "questions": list(self.questions),
            "suite": self.suite,
            "case": self.case,
        }


def _string_field(data: dict[str, Any], key: str, origin: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PipelineError(f"{origin}: field {key!r} must be a string, got {type(value).__name__}")
    return value.strip()


def _string_list(data: dict[str, Any], key: str, origin: str) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PipelineError(f"{origin}: field {key!r} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def parse_intent(data: Any, origin: str) -> VideoReviewIntent:
    """Validate one intent document, refusing with every missing requirement.

    The context is never inferred from the filename: an empty `purpose` is
    refused here instead of sent to a model to guess at.
    """
    if not isinstance(data, dict):
        raise PipelineError(f"{origin}: the intent must be a JSON object")
    allowed = {
        "schema_version",
        "purpose",
        "subject",
        "camera_path",
        "desired_qualities",
        "avoid",
        "references",
        "questions",
        "suite",
        "case",
    }
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise PipelineError(
            f"{origin}: unknown intent field(s) {', '.join(unknown)}; expected: "
            + ", ".join(sorted(allowed))
        )
    version = data.get("schema_version", INTENT_SCHEMA_VERSION)
    if version != INTENT_SCHEMA_VERSION:
        raise PipelineError(
            f"{origin}: intent schema_version {version!r} is not supported by this "
            f"tool (it speaks version {INTENT_SCHEMA_VERSION}); re-record the intent "
            "against the current schema"
        )
    if "purpose" not in data:
        raise PipelineError(f"{origin}: intent is missing required field 'purpose'")
    purpose = _string_field(data, "purpose", origin)
    if not purpose:
        raise PipelineError(
            f"{origin}: 'purpose' must not be empty; context is never inferred from a filename"
        )

    references: list[ReferenceMedia] = []
    raw_references = data.get("references")
    if raw_references is not None:
        if not isinstance(raw_references, list):
            raise PipelineError(f"{origin}: 'references' must be a list")
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
                ReferenceMedia(path=Path(reference_path), purpose=reference_purpose.strip())
            )

    return VideoReviewIntent(
        purpose=purpose,
        subject=_string_field(data, "subject", origin),
        camera_path=_string_field(data, "camera_path", origin),
        desired_qualities=_string_field(data, "desired_qualities", origin),
        avoid=_string_list(data, "avoid", origin),
        references=tuple(references),
        questions=_string_list(data, "questions", origin),
        suite=_string_field(data, "suite", origin),
        case=_string_field(data, "case", origin),
    )


def load_intent_file(path: Path) -> tuple[VideoReviewIntent, bytes]:
    """Read and validate an intent file; return it with its exact bytes."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read intent file {path}: {exc}") from exc
    return parse_intent(_decode_json(raw, f"intent file {path}"), f"intent file {path}"), raw


def parse_intent_text(text: str) -> tuple[VideoReviewIntent, bytes]:
    """Validate an inline intent document; return it with its exact bytes."""
    raw = text.encode("utf-8")
    return parse_intent(_decode_json(raw, "--intent-text"), "--intent-text"), raw


def _decode_json(raw: bytes, origin: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{origin} is not valid JSON: {exc}") from exc


# -- structured result --------------------------------------------------------


RESULT_KEYS = (
    "summary",
    "strengths",
    "issues",
    "recommended_changes",
    "rubric_scores",
    "confidence",
    "limitations",
)


def validate_result(data: dict[str, Any], origin: str = "gateway response") -> dict[str, Any]:
    """Normalize a review into the pipeline-owned result shape.

    The canonical validator lives in the deadeye gateway; this is the offline
    backstop a caller runs on what the gateway returned, mirroring
    `audio_review.validate_result` (the shared seven-key shape) with video's
    one addition: an issue may name its moment as `at_frame` as well as
    `at_seconds`. Every deviation is a hard failure naming what was wrong.
    """
    problems: list[str] = []
    missing = [key for key in RESULT_KEYS if key not in data]
    if missing:
        problems.append(f"missing key(s): {', '.join(missing)}")
    extra = sorted(set(data) - set(RESULT_KEYS))
    if extra:
        problems.append(f"unexpected key(s): {', '.join(extra)}")
    if problems:
        raise PipelineError(f"{origin} returned an invalid structure: {'; '.join(problems)}")

    def strings(key: str) -> list[str]:
        value = data[key]
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            problems.append(f"{key} must be an array of strings")
            return []
        return [item for item in value if item.strip()]

    summary = data["summary"]
    if not isinstance(summary, str) or not summary.strip():
        problems.append("summary must be a non-empty string")

    issues: list[dict[str, Any]] = []
    raw_issues = data["issues"]
    if not isinstance(raw_issues, list):
        problems.append("issues must be an array")
    else:
        for index, entry in enumerate(raw_issues):
            if not isinstance(entry, dict) or "description" not in entry:
                problems.append(f"issue #{index + 1} must be an object with 'description'")
                continue
            # Live models name a moment with the singular aliases `frame` /
            # `seconds` as often as `at_frame` / `at_seconds`; normalize them
            # before the shape check (canonical wins when both are present).
            if "frame" in entry:
                entry.setdefault("at_frame", entry.pop("frame"))
            if "seconds" in entry:
                entry.setdefault("at_seconds", entry.pop("seconds"))
            # Start/end pairs: {"start_frame": 9, "end_frame": 11} is the
            # same moment as {"at_frame": [9, 11]}.
            start, end = entry.pop("start_frame", None), entry.pop("end_frame", None)
            if "at_frame" not in entry and start is not None and end is not None:
                entry["at_frame"] = [start, end]
            start, end = entry.pop("start_seconds", None), entry.pop("end_seconds", None)
            if "at_seconds" not in entry and start is not None and end is not None:
                entry["at_seconds"] = [start, end]
            unexpected = sorted(set(entry) - {"description", "at_seconds", "at_frame"})
            if unexpected:
                problems.append(
                    f"issue #{index + 1} has unexpected key(s): {', '.join(unexpected)}"
                )
                continue
            description = entry["description"]
            if not isinstance(description, str) or not description.strip():
                problems.append(f"issue #{index + 1} needs a non-empty description")
                continue
            issue: dict[str, Any] = {"description": description.strip()}
            seconds = _moment(entry.get("at_seconds"), non_negative=False)
            if "at_seconds" in entry and entry["at_seconds"] is not None and seconds is None:
                problems.append(
                    f"issue #{index + 1} at_seconds must be [start, end] numbers "
                    "with start <= end, or a single second"
                )
                continue
            if seconds is not None:
                issue["at_seconds"] = seconds
            frame = _moment(entry.get("at_frame"), non_negative=True)
            if "at_frame" in entry and entry["at_frame"] is not None and frame is None:
                problems.append(
                    f"issue #{index + 1} at_frame must be [start, end] non-negative "
                    "numbers with start <= end, or a single frame index"
                )
                continue
            if frame is not None:
                issue["at_frame"] = frame
            issues.append(issue)

    # deadeye owns the rubric (see the gateway envelope); this backstop checks
    # score *values* without pinning dimension names, which live in the gateway.
    scores: dict[str, float | None] = {}
    raw_scores = data["rubric_scores"]
    if not isinstance(raw_scores, dict):
        problems.append("rubric_scores must be an object keyed by rubric dimension")
    else:
        for key, value in raw_scores.items():
            if value is None:
                scores[key] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"rubric_scores[{key!r}] must be a number or null")
            elif not 0 <= value <= 5:
                problems.append(f"rubric_scores[{key!r}] must be within 0-5")
            else:
                scores[key] = float(value)

    confidence = data["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        problems.append("confidence must be a number between 0 and 1")

    if problems:
        raise PipelineError(
            f"{origin} returned an invalid structure (schema mismatch): " + "; ".join(problems)
        )
    return {
        "summary": summary.strip(),
        "strengths": strings("strengths"),
        "issues": issues,
        "recommended_changes": strings("recommended_changes"),
        "rubric_scores": scores,
        "confidence": round(float(confidence), 4),
        "limitations": strings("limitations"),
    }


# -- redaction and hashing ----------------------------------------------------


def _moment(value: Any, *, non_negative: bool) -> list[float] | None:
    """Normalize an issue moment: `[start, end]` or a single value -> `[n, n]`.

    Mirrors the deadeye gateway's canonical validator: models point at a
    moment with either shape, and a single frame index or second is the
    natural way to name one frame.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if non_negative and value < 0:
            return None
        return [float(value), float(value)]
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in value)
        and (not non_negative or value[0] >= 0)
        and value[0] <= value[1]
    ):
        return [float(value[0]), float(value[1])]
    return None


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


def _is_sensitive_key(key: str, parts: tuple[str, ...] = SENSITIVE_KEY_PARTS) -> bool:
    lowered = key.lower()
    return lowered == "key" or any(part in lowered for part in parts)


USAGE_SENSITIVE_KEY_PARTS = tuple(part for part in SENSITIVE_KEY_PARTS if part != "token")


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


# -- the deadeye boundary -----------------------------------------------------


def deadeye_available() -> bool:
    """Whether the gateway CLI is on PATH. Presence only, never a network call."""
    return shutil.which(GATEWAY) is not None


Runner = Callable[["Sequence[str]", float], "subprocess.CompletedProcess[str]"]


def _default_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run the gateway in an isolated session and reap it on expiry.

    A gateway may start upload or model-worker children.  ``subprocess.run``
    only kills its direct child at a timeout, leaving those descendants alive
    after the request that owned them has already failed.  On POSIX, a fresh
    session gives this invocation one process group to terminate; Windows has
    no equivalent here, so retains the direct-child kill it already had.
    """
    try:
        process = subprocess.Popen(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            else:  # pragma: no cover - exercised on Windows
                process.kill()
            process.communicate()
            raise PipelineError(
                f"the {GATEWAY} gateway did not answer within {timeout:g}s; no verdict was produced"
            ) from exc
    except OSError as exc:
        raise PipelineError(f"could not run the {GATEWAY} gateway: {exc}") from exc
    return subprocess.CompletedProcess(list(argv), process.returncode, stdout, stderr)


def _adopted_clip_record(clip: Path, capture_root: Path) -> dict[str, Any] | None:
    """The capture-manifest entry for `clip`, or None when it was never adopted.

    `review-video` only ever reviews a recorded, hash-addressed capture: the
    same boundary `client capture` already draws between taking a screenshot
    and recording one somebody else took. An arbitrary directory is refused,
    not silently treated as evidence.
    """
    if not clip.is_relative_to(capture_root):
        return None
    for entry in read_manifest(capture_root):
        if entry.get("directory") == clip.name:
            return entry
    return None


def _asset_record(stem: str, config: PipelineConfig) -> dict[str, Any]:
    """What the pipeline actually knows about the candidate's provenance.

    The tracked manifest lists source paths, not generation arguments: this
    pipeline does not yet record per-asset `generate mesh` parameters (shape,
    size, seed), so the evidence names the source file and its SHA-256 as the
    comparable address, and says generation parameters are not recorded —
    never a guess.
    """
    source: Path | None = None
    if config.bundle_source == "synthesized":
        matches = [
            path
            for path in config.bundle_source_dir.iterdir()
            if path.is_file() and path.stem == stem
        ]
        if matches:
            source = min(matches, key=lambda path: (path.suffix != ".glb", path.name))
    else:
        for asset in manifest_assets(config.tracked_manifest):
            if Path(asset).stem == stem:
                candidate = config.mod_root / asset
                if candidate.is_file():
                    source = candidate
                    break
    if source is None:
        return {
            "stem": stem,
            "bundle_source": config.bundle_source,
            "source": None,
            "source_sha256": None,
            "generation_parameters": None,
            "note": "no source file recorded for this stem in the tracked manifest",
        }
    digest, size = sha256_file(source)
    return {
        "stem": stem,
        "bundle_source": config.bundle_source,
        "source": str(
            source.relative_to(config.mod_root)
            if source.is_relative_to(config.mod_root)
            else source
        ),
        "source_sha256": digest,
        "source_bytes": size,
        "generation_parameters": None,
        "note": "per-asset generation arguments are not recorded by this pipeline; "
        "the source file's SHA-256 is the comparable address between revisions",
    }


def run_review(
    stem: str,
    *,
    clip: Path,
    provider: str = DEFAULT_PROVIDER,
    intent_path: Path | None = None,
    intent_text: str | None = None,
    model: str | None = None,
    config: PipelineConfig,
    capture_root: Path | str = DEFAULT_ROOT,
    allow_network: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    keep_raw_response: bool = False,
    output: Path | None = None,
    force: bool = False,
    notify: Callable[[str], None] | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Submit the adopted clip plus recorded intent via deadeye, return the verdict.

    Order matters and is tested: consent gate, local intent validation, clip
    existence and adoption, gateway availability, provenance, disclosure,
    submission, structural validation, evidence. A failure at any step raises
    one user-actionable message and preserves no partial verdict as a
    completed review.
    """
    if not allow_network:
        # First of all, before anything is read or contacted.
        raise PipelineError(
            "review-video sends the authored clip to a third-party vision model; pass "
            "--allow-network (CLI) or allow_network=true (call/serve/API) to consent "
            "to that upload"
        )
    if intent_path is not None and intent_text is not None:
        raise PipelineError(
            "review-video takes exactly one of --intent PATH or --intent-text JSON, never both"
        )
    if intent_path is not None:
        intent, intent_raw = load_intent_file(Path(intent_path))
    elif intent_text is not None:
        intent, intent_raw = parse_intent_text(intent_text)
    else:
        raise PipelineError(
            "review-video needs exactly one of --intent PATH (the reproducible route, "
            "committed beside the source) or --intent-text JSON"
        )

    clip_path = Path(clip)
    if not clip_path.is_dir():
        raise PipelineError(f"no such clip directory: {clip_path}")
    record = _adopted_clip_record(clip_path, Path(capture_root))
    if record is None:
        raise PipelineError(
            f"{clip_path} was never adopted by `shamway client capture --clip`; review "
            "only ever runs against a recorded, hash-addressed capture. Adopt the "
            f"clip first, e.g.: shamway client capture {stem} --clip <capture-dir> "
            '--observable "..."'
        )
    if not deadeye_available():
        raise PipelineError(
            f"review-video is gated on the 'model-video-review' capability: the "
            f"{GATEWAY} gateway CLI is not on PATH. {GATEWAY_INSTALL_HINT}"
        )

    resolved_model = model or ""
    asset = _asset_record(stem, config)
    if notify is not None:
        notify(f"gateway: {GATEWAY} (provider {provider})")
        notify(f"model: {resolved_model or 'default per provider'}")
        notify(
            f"reviewing the adopted clip {clip_path} against {provider}; the media "
            "leaves this machine and retention is governed by that provider's terms"
        )

    argv: list[str] = [GATEWAY, "review", str(clip_path), "--provider", provider]
    if intent_path is not None:
        argv += ["--intent", str(intent_path)]
    else:
        argv += ["--intent-text", intent_text or ""]
    if model:
        argv += ["--model", model]
    argv += ["--allow-network", "--json", "--timeout", f"{timeout_seconds:g}"]
    if keep_raw_response:
        argv += ["--keep-raw-response"]

    execute = runner or _default_runner
    result = execute(argv, timeout_seconds)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().splitlines()
        raise PipelineError(
            f"the {GATEWAY} gateway refused the review" + (f": {message[-1]}" if message else "")
        )

    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"the {GATEWAY} gateway returned a non-JSON envelope: {exc}") from exc
    if not isinstance(envelope, dict) or envelope.get("kind") != "deadeye-review":
        raise PipelineError(
            f"the {GATEWAY} gateway returned an unexpected envelope; is the installed "
            "version the hordeforge gateway?"
        )
    if envelope.get("error") is not None:
        raise PipelineError(f"the {GATEWAY} gateway reported: {envelope['error']}")
    provider_block = envelope.get("provider")
    if not isinstance(provider_block, dict) or not isinstance(envelope.get("result"), dict):
        raise PipelineError("the gateway returned an incomplete envelope (no provider or result)")
    review = validate_result(envelope["result"])

    params = {
        "stem": stem,
        "clip": str(clip_path),
        "intent": str(intent_path) if intent_path is not None else "(inline text)",
        "provider": provider,
        "model": resolved_model,
        "timeout_seconds": timeout_seconds,
        "keep_raw_response": keep_raw_response,
        "force": force,
        "allow_network": True,
    }
    document = _evidence(
        clip=clip_path,
        record=record,
        intent=intent,
        intent_raw=intent_raw,
        asset=asset,
        envelope=envelope,
        review=review,
        provider_name=provider,
        model_requested=resolved_model,
        params=params,
        keep_raw_response=keep_raw_response,
    )

    evidence: dict[str, str | None] = {"path": None, "sha256": None}
    if output is not None:
        if output.is_file() and not force:
            raise PipelineError(
                f"{output} already holds an earlier review and a later review never "
                "overwrites one by default; compare the documents, or pass --force"
            )
        payload = json.dumps(document, indent=2, sort_keys=True)
        atomic.write(output, payload)
        evidence = {"path": str(output), "sha256": sha256_bytes(payload.encode("utf-8"))}
    document["evidence"] = evidence

    usage: dict[str, Any] = (
        redact(dict(envelope["usage"]), USAGE_SENSITIVE_KEY_PARTS) if envelope.get("usage") else {}
    )
    usage.setdefault("reported_by_provider", envelope.get("usage") is not None)
    return {
        "advisory_only": True,
        "note": ADVISORY_NOTE,
        "clip": str(clip_path),
        "provider": envelope["provider"]["name"],
        "model": envelope["provider"].get("model_reported") or resolved_model,
        "review": review,
        "usage": usage,
        "disclosure": envelope.get("disclosure", {}),
        "sampling": envelope.get("sampling", {}),
        "asset": asset,
        "evidence": evidence,
        "gateway": envelope,
        "_document": document,
    }


def _evidence(
    *,
    clip: Path,
    record: dict[str, Any],
    intent: VideoReviewIntent,
    intent_raw: bytes,
    asset: dict[str, Any],
    envelope: dict[str, Any],
    review: dict[str, Any],
    provider_name: str,
    model_requested: str,
    params: dict[str, Any],
    keep_raw_response: bool,
) -> dict[str, Any]:
    """The hash-addressed record that makes one review citable later."""
    media = envelope.get("media") or []
    return {
        "kind": "shamway-video-review-evidence",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "tool_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "review_id": uuid.uuid4().hex,
        "clip": {
            "path": str(clip),
            "directory": clip.name,
            "adopted": {
                "observable": record.get("observable"),
                "captured_at": record.get("captured_at"),
                "backend": record.get("backend"),
            },
            "files": media,
        },
        "intent": {
            "sha256": sha256_bytes(intent_raw),
            "schema_version": INTENT_SCHEMA_VERSION,
            "content": intent.as_dict(),
        },
        "asset": asset,
        "provider": {
            "name": provider_name,
            "endpoint_mode": envelope["provider"].get("endpoint_mode"),
            "model_requested": model_requested,
            "model_reported": envelope["provider"].get("model_reported"),
        },
        "sampling": envelope.get("sampling", {}),
        "rubric_version": envelope.get("rubric_version"),
        "prompt_version": envelope.get("prompt_version"),
        "prompt": envelope.get("prompt"),
        "result": review,
        "error": envelope.get("error"),
        "raw_provider_response": (
            redact(envelope["raw_provider_response"]) if keep_raw_response else None
        ),
        "usage": redact(dict(envelope["usage"]), USAGE_SENSITIVE_KEY_PARTS)
        if envelope.get("usage")
        else {"reported_by_provider": False},
        "disclosure": envelope.get("disclosure", {}),
        "gateway": envelope,
        "parameters": redact(params),
    }
