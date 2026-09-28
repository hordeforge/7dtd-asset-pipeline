"""Google's Gemini as the first hosted adapter.

Chosen because its API accepts non-speech audio inline (base64, no upload
round trip), can be asked for JSON output, and needs only the standard
library to reach: no SDK, no new dependency for a mod author to audit. The
model identifier is a default, not a contract — providers and model names
change, so the caller can always pass `--model` and the capability registry
reports configuration rather than hard-coding one vendor.

The key arrives from `GEMINI_API_KEY` or `GOOGLE_API_KEY`, is sent in a
header (never a query string, so it cannot land in an access log), and is
never printed, logged, or written into evidence.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from ..errors import PipelineError
from .base import MIME_BY_SUFFIX, ProviderLimits, ReviewRequest, ReviewResponse

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
CREDENTIAL_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
# Interpolated into the request URL, so it must be a single path segment.
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# A filename is author-supplied data, and it is interpolated into a text part
# of the prompt. A name carrying a line break therefore opens a line that
# reads as the pipeline's own instruction rather than as a label, which is
# the same injection channel `fold_author_text` closes for every other author
# string. A newline in a filename is not a real case, so it is refused here
# rather than rewritten.
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
# Gemini's audio documentation lists these containers; the 20 MB figure is the
# published per-request budget for inline data.
SUPPORTED_SUFFIXES = (".wav", ".mp3", ".aiff", ".aac", ".ogg", ".flac")
MAX_REQUEST_BYTES = 20 * 1024 * 1024
# Every billable token of a generation is bounded by this one number. The
# rubric answer is roughly a thousand tokens; the rest is headroom, and on a
# 2.5 model the cap also bounds the reasoning tokens the model spends before
# it answers. Without it a model that loops or rambles is billed for as long
# as it keeps emitting, and nothing in this tool would notice until the
# invoice.
MAX_OUTPUT_TOKENS = 8192
# A 429 or a 5xx is the provider saying it did not take the request, so
# resubmitting it is not a second billable call. Nothing else is retried: a
# refused credential, a malformed model id, or a 4xx is this caller's problem
# and repeating it only multiplies the cost. The budget is three attempts
# total, and the wait between them is bounded whatever `Retry-After` asks
# for, because a provider that answers 429 with an hour is not one to sit in
# front of.
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_DELAY_SECONDS = 8.0
BASE_RETRY_DELAY_SECONDS = 1.0


class GeminiProvider:
    name = "gemini"
    endpoint_mode = "hosted-api:inline-base64"
    requires_credential = True

    @property
    def default_model(self) -> str:
        return "gemini-2.5-flash"

    @property
    def limits(self) -> ProviderLimits:
        return ProviderLimits(suffixes=SUPPORTED_SUFFIXES, max_bytes=MAX_REQUEST_BYTES)

    def mime_for(self, suffix: str) -> str:
        if suffix not in SUPPORTED_SUFFIXES:
            raise PipelineError(
                f"Gemini does not list {suffix} among its audio containers "
                f"({', '.join(SUPPORTED_SUFFIXES)})"
            )
        return MIME_BY_SUFFIX[suffix]

    def credential(self) -> str | None:
        """The configured key, or None. Never logged; callers send it only."""
        for name in CREDENTIAL_ENV_VARS:
            value = os.environ.get(name)
            if value:
                return value
        return None

    def is_configured(self) -> bool:
        return self.credential() is not None

    def configuration_hint(self) -> str:
        return (
            f"export {CREDENTIAL_ENV_VARS[0]}=<key> with a key from "
            "https://aistudio.google.com/apikey"
        )

    def review(self, request: ReviewRequest) -> ReviewResponse:
        credential = self.credential()
        if credential is None:
            raise PipelineError(f"provider 'gemini' has no credential; {self.configuration_hint()}")
        if not _MODEL_ID.fullmatch(request.model):
            raise PipelineError(
                f"provider 'gemini' model {request.model!r} is not a model identifier "
                "(letters, digits, '.', '_' and '-' only)"
            )
        parts: list[dict[str, object]] = [{"text": request.prompt}]
        for payload in request.audios:
            if _CONTROL_CHARACTERS.search(payload.name):
                raise PipelineError(
                    f"attachment name {payload.name!r} carries a control character; "
                    "an attachment label is a filename and must stay on one line"
                )
            parts.append({"text": f"audio attachment: {payload.name}"})
            parts.append(
                {
                    "inline_data": {
                        "mime_type": payload.mime_type,
                        "data": base64.b64encode(payload.data).decode("ascii"),
                    }
                }
            )
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
            },
        }
        # Both audited statements carry the same justification: the URL is
        # this module's fixed https constant plus the requested model name;
        # scheme and host are never caller-controlled.
        http_request = urllib.request.Request(  # noqa: S310
            f"{API_ROOT}/{urllib.parse.quote(request.model, safe='-._')}:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Header, not query parameter: the key must never appear in a URL.
                "x-goog-api-key": credential,
            },
            method="POST",
        )
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with urllib.request.urlopen(  # noqa: S310
                    http_request, timeout=request.timeout_seconds
                ) as response:
                    envelope = json.load(response)
                break
            except urllib.error.HTTPError as exc:
                # A body that cannot be read must degrade to the status line, not
                # to an unbound name when the message below formats it. The error
                # is a response object with an open socket: leaving it to the
                # collector emits a ResourceWarning from wherever the collection
                # happens to land, which in this suite is another test's captured
                # stderr.
                detail = ""
                with contextlib.suppress(OSError):
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                exc.close()
                if exc.code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    time.sleep(_retry_delay(exc, attempt))
                    continue
                attempts = f" after {attempt} attempt(s)" if attempt > 1 else ""
                if exc.code in (401, 403):
                    raise PipelineError(
                        f"provider 'gemini' rejected the credential (HTTP {exc.code}); "
                        "check the key in GEMINI_API_KEY / GOOGLE_API_KEY"
                    ) from exc
                if exc.code == 429:
                    raise PipelineError(
                        f"provider 'gemini' rate-limited or quota-exhausted the request "
                        f"(HTTP 429){attempts}: {detail}"
                    ) from exc
                raise PipelineError(
                    f"provider 'gemini' refused the review (HTTP {exc.code}){attempts}: {detail}"
                ) from exc
            except TimeoutError as exc:
                raise PipelineError(
                    f"provider 'gemini' did not answer within {request.timeout_seconds:g}s; "
                    "no verdict was produced"
                ) from exc
            except urllib.error.URLError as exc:
                raise PipelineError(
                    f"provider 'gemini' could not be reached: {exc.reason}; no verdict was produced"
                ) from exc
            except json.JSONDecodeError as exc:
                raise PipelineError(
                    f"provider 'gemini' returned a non-JSON envelope: {exc}"
                ) from exc
        if not isinstance(envelope, dict):
            raise PipelineError(
                "provider 'gemini' returned a "
                f"{type(envelope).__name__} envelope, not an object; no verdict was produced"
            )

        candidates = envelope.get("candidates") or []
        if not candidates:
            feedback = envelope.get("promptFeedback") or {}
            reason = feedback.get("blockReason")
            raise PipelineError(
                "provider 'gemini' returned no candidate"
                + (f" (blocked: {reason})" if reason else "")
                + "; no verdict was produced"
            )
        text = "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
            if isinstance(part, dict)
        )
        finish = candidates[0].get("finishReason")
        if finish == "MAX_TOKENS":
            # The answer was cut off mid-JSON. Reporting that as a model
            # refusal would hide the real cause, and accepting it would leave
            # the caller parsing a truncated object as if it were complete.
            raise PipelineError(
                f"provider 'gemini' stopped at the {MAX_OUTPUT_TOKENS}-token output cap "
                f"with the answer unfinished (finishReason {finish}); no verdict was "
                "produced"
            )
        if finish and finish != "STOP":
            raise PipelineError(
                f"provider 'gemini' ended the response early (finishReason {finish}); "
                "no verdict was produced"
            )
        usage = envelope.get("usageMetadata")
        return ReviewResponse(
            raw_text=text,
            usage=usage if isinstance(usage, dict) else None,
            model_reported=envelope.get("modelVersion"),
        )


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait before resubmitting, honouring `Retry-After` within its cap.

    The header is the provider naming its own backoff, so it is preferred
    when it parses; anything else, including a missing or malformed header,
    falls back to exponential backoff from the base delay. Both are clamped
    to `MAX_RETRY_DELAY_SECONDS`.
    """
    # Only the delta-seconds form of `Retry-After` is a delay; an HTTP-date
    # is not a number, and a missing header is not a wait at all.
    asked = str(exc.headers.get("Retry-After", "")).strip()
    if asked:
        try:
            return max(0.0, min(float(asked), MAX_RETRY_DELAY_SECONDS))
        except ValueError:
            pass
    backoff: float = BASE_RETRY_DELAY_SECONDS * 2.0 ** (attempt - 1)
    return min(backoff, MAX_RETRY_DELAY_SECONDS)
