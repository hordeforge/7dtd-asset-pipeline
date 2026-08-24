"""Advisory semantic review of an authored clip by a configured audio model.

`check-sound` measures what is measurable, and a fresh client proves the game
plays the clip. Neither answers whether the sound *fits its purpose* — whether
a falling whistle reads as mass moving through air rather than as a comic
slide-whistle. That judgement needs the actual audio together with the intent
behind it: the same rising tone is right for an interface warning and wrong for
an entity-bound three-dimensional bomb cue. So this module submits the clip's
bytes, plus an intent file the author commits beside the source, to a provider
from `providers/`, and normalizes whatever comes back into a pipeline-owned
result.

Three boundaries are load-bearing here:

- **Consent comes before everything.** The submission is networked, billable,
  and sends an authored asset to a third party. Every refusal below happens
  before the credential check except the consent gate itself, which happens
  first of all.
- **The result schema is ours, not the vendor's.** Provider payloads stay at
  the adapter boundary; callers see `validate_result`'s output. A raw response
  is preserved only when explicitly requested, redacted either way.
- **A verdict here is evidence, never acceptance.** Nothing in this module can
  mark an asset accepted; that remains the human listen in a fresh client.

The judgement is traceable (hashes, versions, timestamps) but never
deterministic: two runs may disagree, and disagreement is preserved rather
than averaged.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import atomic
from ._version import __version__
from .errors import PipelineError
from .providers.base import AudioPayload, ReviewRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from .providers.base import AudioReviewProvider

INTENT_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION = 1
RUBRIC_VERSION = "1"
PROMPT_VERSION = "1"

DEFAULT_PROVIDER = "gemini"
DEFAULT_TIMEOUT_SECONDS = 120.0

ONE_SHOT = "one-shot"
LOOP = "loop"
PLAYBACK_MODES = (ONE_SHOT, LOOP)

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

ADVISORY_NOTE = (
    "Advisory only: a model critique is evidence about the submitted bytes "
    "under the recorded intent. It cannot satisfy the fresh-client human-listen "
    "acceptance gate."
)


# -- intent -------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceClip:
    """A comparison clip the author supplies, and why it is worth hearing."""

    path: Path
    purpose: str


@dataclass(frozen=True)
class AudioReviewIntent:
    """The recorded intended use a reviewer needs besides the waveform."""

    purpose: str
    playback_mode: str
    expected_duration_seconds: float | None
    repeat_rate_seconds: float | None
    pitch_variation: str
    spatial_context: str
    mix_context: str
    listener: str
    desired_qualities: str
    avoid: tuple[str, ...]
    questions: tuple[str, ...]
    references: tuple[ReferenceClip, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "playback": {
                "mode": self.playback_mode,
                "expected_duration_seconds": self.expected_duration_seconds,
                "repeat_rate_seconds": self.repeat_rate_seconds,
                "pitch_variation": self.pitch_variation,
            },
            "spatial_context": self.spatial_context,
            "mix_context": self.mix_context,
            "listener": self.listener,
            "desired_qualities": self.desired_qualities,
            "avoid": list(self.avoid),
            "questions": list(self.questions),
            "references": [
                {"path": str(item.path), "purpose": item.purpose} for item in self.references
            ],
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


def parse_intent(data: Any, origin: str) -> AudioReviewIntent:
    """Validate one intent document, refusing with every missing requirement.

    The context is never inferred from the filename: an empty `purpose`, or no
    `playback` block, is refused here instead of sent to a model to guess at.
    """
    if not isinstance(data, dict):
        raise PipelineError(f"{origin}: the intent must be a JSON object")
    allowed = {
        "schema_version",
        "purpose",
        "playback",
        "spatial_context",
        "mix_context",
        "listener",
        "desired_qualities",
        "avoid",
        "questions",
        "references",
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

    missing = [name for name in ("purpose", "playback") if name not in data]
    if missing:
        raise PipelineError(f"{origin}: intent is missing required field(s): {', '.join(missing)}")
    purpose = _string_field(data, "purpose", origin)
    if not purpose:
        raise PipelineError(
            f"{origin}: 'purpose' must not be empty; context is never inferred from a filename"
        )

    playback = data["playback"]
    if not isinstance(playback, dict):
        raise PipelineError(f"{origin}: 'playback' must be a JSON object")
    playback_allowed = {
        "mode",
        "expected_duration_seconds",
        "repeat_rate_seconds",
        "pitch_variation",
    }
    playback_unknown = sorted(set(playback) - playback_allowed)
    if playback_unknown:
        raise PipelineError(
            f"{origin}: unknown playback field(s) {', '.join(playback_unknown)}; "
            "expected: " + ", ".join(sorted(playback_allowed))
        )
    mode = playback.get("mode")
    if mode not in PLAYBACK_MODES:
        raise PipelineError(
            f"{origin}: playback.mode must be one of {', '.join(PLAYBACK_MODES)}, got {mode!r}"
        )

    def positive(key: str) -> float | None:
        value = playback.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise PipelineError(f"{origin}: playback.{key} must be a positive number")
        return float(value)

    references: list[ReferenceClip] = []
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
                ReferenceClip(path=Path(reference_path), purpose=reference_purpose.strip())
            )

    return AudioReviewIntent(
        purpose=purpose,
        playback_mode=mode,
        expected_duration_seconds=positive("expected_duration_seconds"),
        repeat_rate_seconds=positive("repeat_rate_seconds"),
        pitch_variation=_string_field(playback, "pitch_variation", origin),
        spatial_context=_string_field(data, "spatial_context", origin),
        mix_context=_string_field(data, "mix_context", origin),
        listener=_string_field(data, "listener", origin),
        desired_qualities=_string_field(data, "desired_qualities", origin),
        avoid=_string_list(data, "avoid", origin),
        questions=_string_list(data, "questions", origin),
        references=tuple(references),
    )


def load_intent_file(path: Path) -> tuple[AudioReviewIntent, bytes]:
    """Read and validate an intent file; return it with its exact bytes."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read intent file {path}: {exc}") from exc
    return parse_intent(_decode_json(raw, f"intent file {path}"), f"intent file {path}"), raw


def parse_intent_text(text: str) -> tuple[AudioReviewIntent, bytes]:
    """Validate an inline intent document; return it with its exact bytes."""
    raw = text.encode("utf-8")
    return parse_intent(_decode_json(raw, "--intent-text"), "--intent-text"), raw


def _decode_json(raw: bytes, origin: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"{origin} is not valid JSON: {exc}") from exc


# -- rubric and prompt --------------------------------------------------------


@dataclass(frozen=True)
class RubricDimension:
    """One property every review scores, and what a low score means."""

    key: str
    question: str


BASE_RUBRIC: tuple[RubricDimension, ...] = (
    RubricDimension("semantic_fit", "does it fit the stated event and source"),
    RubricDimension("timbre_quality", "is the timbre clean and intentional"),
    RubricDimension("pitch_contour", "does the pitch motion suit the stated source"),
    RubricDimension("dynamics", "is the loudness arc deliberate and readable"),
    RubricDimension("transient_definition", "is the attack defined where it should be"),
    RubricDimension("tail_behaviour", "does the tail end deliberately, without clicks"),
    RubricDimension("perceived_scale", "does it sound like the stated size and distance"),
    RubricDimension("harshness_risk", "is anything fatiguing or harsh on repeat"),
    RubricDimension("artificiality_risk", "does it read as synthetic in a bad way"),
    RubricDimension("comedy_risk", "could it read as comic where the event is serious"),
    RubricDimension("repetition_fatigue_risk", "would frequent repeats grate"),
    RubricDimension("masking_risk", "in the described mix, could it be masked or mask others"),
    RubricDimension("spatial_plausibility", "is it plausible for the stated spatial context"),
    RubricDimension("motion_plausibility", "is motion implied by sound plausible for the source"),
)

LOOP_RUBRIC: tuple[RubricDimension, ...] = (
    RubricDimension("loop_seam_risk", "for a loop: is the seam audible"),
)

RUBRIC_DIMENSIONS = BASE_RUBRIC + LOOP_RUBRIC


def rubric_for(intent: AudioReviewIntent) -> tuple[RubricDimension, ...]:
    """Loop-seam scoring applies only when playback says the clip loops."""
    dimensions = list(BASE_RUBRIC)
    if intent.playback_mode == LOOP:
        dimensions.extend(LOOP_RUBRIC)
    return tuple(dimensions)


RESULT_KEYS = (
    "summary",
    "strengths",
    "issues",
    "recommended_changes",
    "rubric_scores",
    "confidence",
    "limitations",
)


def build_prompt(intent: AudioReviewIntent, dimensions: tuple[RubricDimension, ...]) -> str:
    """The full reviewer instruction: rubric, result shape, and the intent."""
    lines = [
        "You are auditioning a game-audio candidate. Judge ONLY the attached audio;",
        "you are given the author's statement of intended use because fitness is a",
        "property of audio-in-context, not of the waveform alone.",
        "",
        "Answer with exactly one JSON object, no prose outside it, with these keys:",
        '  "summary": string - overall reading in two or three sentences;',
        '  "strengths": array of strings;',
        '  "issues": array of {"description": string, "at_seconds": [start, end] | null}',
        "    - concrete problems tied to audible moments where you can place them;",
        '  "recommended_changes": array of strings - actionable revision advice;',
        '  "rubric_scores": object mapping each dimension below to a number 0-5 or null',
        "    - diagnostic only, never pass/fail; use null, plus a note under",
        '    "limitations", whenever a property cannot be judged from one submitted',
        "    file (for example spatial behaviour without in-game spatialisation);",
        '  "confidence": number 0-1 - confidence in this whole assessment;',
        '  "limitations": array of strings - what you could not assess and why.',
        "",
        "Score every dimension listed; score nothing that is not listed:",
    ]
    lines.extend(f"  - {item.key}: {item.question}" for item in dimensions)
    lines.extend(["", "Author's statement of intended use:", f"  purpose: {intent.purpose}"])
    playback = f"  playback: {intent.playback_mode}"
    if intent.expected_duration_seconds is not None:
        playback += f", expected duration {intent.expected_duration_seconds:g} s"
    if intent.repeat_rate_seconds is not None:
        playback += f", repeats about every {intent.repeat_rate_seconds:g} s"
    if intent.pitch_variation:
        playback += f", pitch variation: {intent.pitch_variation}"
    lines.append(playback)
    optional = (
        ("spatial_context", intent.spatial_context),
        ("mix_context", intent.mix_context),
        ("listener", intent.listener),
        ("desired_qualities", intent.desired_qualities),
    )
    lines.extend(f"  {name}: {value}" for name, value in optional if value)
    if intent.avoid:
        lines.append("  qualities to avoid (flag any you hear): " + "; ".join(intent.avoid))
    if intent.questions:
        lines.append("  the author specifically asks: " + " | ".join(intent.questions))
    if intent.references:
        lines.append("  reference clips, in attachment order after the candidate:")
        lines.extend(
            f"    - {reference.purpose} ({reference.path.name})" for reference in intent.references
        )

    # The attachment order is fixed and announced, so multi-file submissions
    # (candidate plus references) stay addressable from the text side.
    lines.append("")
    lines.append(
        "Attachments arrive in a fixed order: the FIRST audio attachment is the "
        "candidate under review; each further attachment is a reference clip, "
        "labelled with its stated purpose. Compare against references only as "
        "context; critique the candidate."
    )
    lines.append("")
    lines.append("Respond with the JSON object and nothing else.")
    return "\n".join(lines)


# -- structured result --------------------------------------------------------


def parse_model_json(raw_text: str) -> dict[str, Any]:
    """Extract the JSON object from a model response, refusing anything else."""
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PipelineError(
            f"model returned invalid structure (not JSON): {exc}; rerun with "
            "--keep-raw-response to preserve a redacted copy for debugging"
        ) from exc
    if not isinstance(parsed, dict):
        raise PipelineError(
            "model returned invalid structure (a JSON "
            f"{type(parsed).__name__}, not an object); rerun with "
            "--keep-raw-response to preserve a redacted copy for debugging"
        )
    return parsed


def validate_result(
    data: dict[str, Any],
    dimensions: tuple[RubricDimension, ...],
    origin: str = "model response",
) -> dict[str, Any]:
    """Normalize a model answer into the pipeline-owned result shape.

    Every deviation is a hard failure naming what was wrong: a silently
    coerced field would put words into the reviewer's mouth. Scores are
    validated as diagnostics in 0-5 or an explicit null; a null must be
    explained under `limitations` by convention, but the shape alone does not
    enforce that.
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
            unexpected = sorted(set(entry) - {"description", "at_seconds"})
            if unexpected:
                problems.append(
                    f"issue #{index + 1} has unexpected key(s): {', '.join(unexpected)}"
                )
                continue
            description = entry["description"]
            if not isinstance(description, str) or not description.strip():
                problems.append(f"issue #{index + 1} needs a non-empty description")
                continue
            issue: dict[str, Any] = {"description": description.strip(), "at_seconds": None}
            moment = entry.get("at_seconds")
            if moment is not None:
                valid_range = (
                    isinstance(moment, list)
                    and len(moment) == 2
                    and all(isinstance(bound, (int, float)) for bound in moment)
                    and moment[0] <= moment[1]
                )
                if not valid_range:
                    problems.append(
                        f"issue #{index + 1} at_seconds must be [start, end] numbers "
                        "with start <= end"
                    )
                    continue
                issue["at_seconds"] = [float(moment[0]), float(moment[1])]
            issues.append(issue)

    known = {item.key for item in dimensions}
    scores: dict[str, float | None] = {}
    raw_scores = data["rubric_scores"]
    if not isinstance(raw_scores, dict):
        problems.append("rubric_scores must be an object keyed by rubric dimension")
    else:
        for key, value in raw_scores.items():
            if key not in known:
                problems.append(
                    f"rubric_scores names unknown dimension {key!r}; expected: "
                    + ", ".join(sorted(known))
                )
                continue
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


def redact(value: Any) -> Any:
    """Deep-copy a JSON-shaped value, dropping credential-bearing mapping keys."""
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if isinstance(key, str) and not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered == "key" or any(part in lowered for part in SENSITIVE_KEY_PARTS)


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


# -- orchestration ------------------------------------------------------------


def run_review(
    clip: Path,
    *,
    provider: AudioReviewProvider,
    intent_path: Path | None = None,
    intent_text: str | None = None,
    model: str | None = None,
    allow_network: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    keep_raw_response: bool = False,
    output: Path | None = None,
    force: bool = False,
    notify: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Submit the actual clip bytes plus recorded intent, return the verdict.

    Order matters and is tested: consent gate, local intent validation,
    provider configuration, local format/size limits, disclosure, submission,
    structural validation, evidence. A failure at any step raises one
    user-actionable message and preserves no partial verdict as a completed
    review.
    """
    if not allow_network:
        # First of all, before credentials are read or anything is contacted.
        raise PipelineError(
            "review-audio sends the authored audio to a third-party service; pass "
            "--allow-network (CLI) or allow_network=true (call/serve/API) to consent "
            "to that upload"
        )
    if intent_path is not None and intent_text is not None:
        raise PipelineError(
            "review-audio takes exactly one of --intent PATH or --intent-text JSON, never both"
        )
    if intent_path is not None:
        intent, intent_raw = load_intent_file(Path(intent_path))
    elif intent_text is not None:
        intent, intent_raw = parse_intent_text(intent_text)
    else:
        raise PipelineError(
            "review-audio needs exactly one of --intent PATH (the reproducible route, "
            "committed beside the source) or --intent-text JSON"
        )

    if not clip.is_file():
        raise PipelineError(f"no such clip: {clip}")

    resolved_model = model or provider.default_model
    limits = provider.limits
    if not provider.is_configured():
        raise PipelineError(
            f"provider {provider.name!r} is not configured and shamway review-audio "
            f"is gated on the 'model-audio-review' capability: "
            f"{provider.configuration_hint()}"
        )

    uploads: list[tuple[str, Path]] = [(clip.name, clip)] + [
        (reference.path.name, reference.path) for reference in intent.references
    ]
    for _, path in uploads:
        if path.suffix.lower() not in limits.suffixes:
            raise PipelineError(
                f"{path} ({path.suffix or 'no suffix'}) is not a format provider "
                f"{provider.name!r} accepts ({', '.join(limits.suffixes)}); convert it "
                "first, e.g. with ffmpeg or 'shamway generate audio convert'"
            )
        if not path.is_file():
            raise PipelineError(f"no such file: {path}")
    digests = {str(path): sha256_file(path) for _, path in uploads}
    total_bytes = sum(size for _, size in digests.values())
    if limits.max_bytes is not None and total_bytes > limits.max_bytes:
        raise PipelineError(
            f"submission is {total_bytes} bytes; provider {provider.name!r} accepts at "
            f"most {limits.max_bytes} per request. Shorten or downmix the clip, or "
            "drop reference clips"
        )

    if notify is not None:
        notify(f"provider: {provider.name} ({provider.endpoint_mode})")
        notify(f"model: {resolved_model}")
        notify(
            f"uploading {len(uploads)} file(s), {total_bytes} bytes: "
            + ", ".join(name for name, _ in uploads)
        )
        notify(
            f"warning: the audio leaves this machine for {provider.name}; retention is "
            "governed by that provider's terms, so send only assets you may disclose"
        )

    dimensions = rubric_for(intent)
    prompt = build_prompt(intent, dimensions)

    audios = tuple(
        AudioPayload(
            name=name,
            mime_type=provider.mime_for(path.suffix.lower()),
            data=path.read_bytes(),
        )
        for name, path in uploads
    )
    labelled = [f"[1] candidate: {clip.name}"] + [
        f"[{index + 2}] reference ({reference.purpose}): {reference.path.name}"
        for index, reference in enumerate(intent.references)
    ]
    request = ReviewRequest(
        prompt=prompt + "\nAttachment labels:\n" + "\n".join(labelled),
        audios=audios,
        model=resolved_model,
        timeout_seconds=timeout_seconds,
    )
    try:
        response = provider.review(request)
    except TimeoutError as exc:
        raise PipelineError(
            f"provider {provider.name!r} did not answer within "
            f"{timeout_seconds:g}s; no verdict was produced"
        ) from exc

    try:
        parsed = parse_model_json(response.raw_text)
        result = validate_result(parsed, dimensions)
    except PipelineError:
        if keep_raw_response and output is not None:
            atomic.write(
                output,
                json.dumps(
                    _evidence(
                        clip=clip,
                        intent=intent,
                        intent_raw=intent_raw,
                        digests=digests,
                        provider_name=provider.name,
                        endpoint_mode=provider.endpoint_mode,
                        model_requested=resolved_model,
                        model_reported=response.model_reported,
                        prompt=prompt,
                        result=None,
                        error="the model response failed structural validation; see "
                        "raw_provider_response",
                        raw_response=redact(response.raw_text),
                        usage=response.usage,
                        total_bytes=total_bytes,
                        params={},
                    ),
                    indent=2,
                    sort_keys=True,
                ),
            )
            raise PipelineError(
                "the model response failed structural validation; a redacted raw "
                f"response was preserved at {output} because keep-raw was requested"
            ) from None
        raise

    params = {
        "clip": str(clip),
        "intent": str(intent_path) if intent_path is not None else "(inline text)",
        "provider": provider.name,
        "model": resolved_model,
        "timeout_seconds": timeout_seconds,
        "keep_raw_response": keep_raw_response,
        "force": force,
        "allow_network": True,
    }
    document = _evidence(
        clip=clip,
        intent=intent,
        intent_raw=intent_raw,
        digests=digests,
        provider_name=provider.name,
        endpoint_mode=provider.endpoint_mode,
        model_requested=resolved_model,
        model_reported=response.model_reported,
        prompt=prompt,
        result=result,
        error=None,
        raw_response=redact(response.raw_text) if keep_raw_response else None,
        usage=response.usage,
        total_bytes=total_bytes,
        params=params,
    )

    evidence_path: Path | None = None
    evidence_sha256: str | None = None
    if output is not None:
        if output.is_file() and not force:
            raise PipelineError(
                f"{output} already holds an earlier review and a later review never "
                "overwrites one by default; compare the documents, or pass --force"
            )
        payload = json.dumps(document, indent=2, sort_keys=True)
        atomic.write(output, payload)
        evidence_path = output
        evidence_sha256 = sha256_bytes(payload.encode("utf-8"))

    usage: dict[str, Any] = dict(response.usage) if response.usage else {}
    usage.setdefault("reported_by_provider", response.usage is not None)
    return {
        "advisory_only": True,
        "note": ADVISORY_NOTE,
        "clip": str(clip),
        "provider": provider.name,
        "model": response.model_reported or resolved_model,
        "review": result,
        "usage": usage,
        "disclosure": {
            "network_consent": True,
            "third_party": provider.name,
            "file_count": len(uploads),
            "total_bytes": total_bytes,
        },
        "evidence": {
            "path": str(evidence_path) if evidence_path else None,
            "sha256": evidence_sha256,
        },
        "_document": document,
    }


def _evidence(
    *,
    clip: Path,
    intent: AudioReviewIntent,
    intent_raw: bytes,
    digests: dict[str, tuple[str, int]],
    provider_name: str,
    endpoint_mode: str,
    model_requested: str,
    model_reported: str | None,
    prompt: str,
    result: dict[str, Any] | None,
    error: str | None,
    raw_response: str | None,
    usage: dict[str, Any] | None,
    total_bytes: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    """The hash-addressed record that makes one review citable later."""
    clip_digest, clip_size = digests[str(clip)]
    return {
        "kind": "shamway-audio-review-evidence",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "tool_version": __version__,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "review_id": uuid.uuid4().hex,
        "clip": {"path": str(clip), "sha256": clip_digest, "bytes": clip_size},
        "references": [
            {
                "path": path,
                "sha256": digest,
                "bytes": size,
                "purpose": next(
                    item.purpose for item in intent.references if str(item.path) == path
                ),
            }
            for path, (digest, size) in digests.items()
            if path != str(clip)
        ],
        "intent": {
            "sha256": sha256_bytes(intent_raw),
            "schema_version": INTENT_SCHEMA_VERSION,
            "content": intent.as_dict(),
        },
        "provider": {
            "name": provider_name,
            "endpoint_mode": endpoint_mode,
            "model_requested": model_requested,
            "model_reported": model_reported,
        },
        "rubric_version": RUBRIC_VERSION,
        "prompt_version": PROMPT_VERSION,
        "prompt": prompt,
        "result": result,
        "error": error,
        # Raw responses are opt-in and redacted; they carry debugging value and
        # sometimes the provider's own request metadata.
        "raw_provider_response": raw_response,
        "usage": dict(usage) if usage else {"reported_by_provider": False},
        "disclosure": {
            "network_consent": True,
            "third_party": provider_name,
            "total_bytes": total_bytes,
        },
        "parameters": redact(params),
    }
