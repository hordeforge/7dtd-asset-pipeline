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
import urllib.error
import urllib.request

from ..errors import PipelineError
from .base import MIME_BY_SUFFIX, ProviderLimits, ReviewRequest, ReviewResponse

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
CREDENTIAL_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
# Gemini's audio documentation lists these containers; the 20 MB figure is the
# published per-request budget for inline data.
SUPPORTED_SUFFIXES = (".wav", ".mp3", ".aiff", ".aac", ".ogg", ".flac")
MAX_REQUEST_BYTES = 20 * 1024 * 1024


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
        parts: list[dict[str, object]] = [{"text": request.prompt}]
        for payload in request.audios:
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
            "generationConfig": {"response_mime_type": "application/json"},
        }
        # Both audited statements carry the same justification: the URL is
        # this module's fixed https constant plus the requested model name;
        # scheme and host are never caller-controlled.
        http_request = urllib.request.Request(  # noqa: S310
            f"{API_ROOT}/{request.model}:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # Header, not query parameter: the key must never appear in a URL.
                "x-goog-api-key": credential,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                http_request, timeout=request.timeout_seconds
            ) as response:
                envelope = json.load(response)
        except urllib.error.HTTPError as exc:
            with contextlib.suppress(OSError):
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            if exc.code in (401, 403):
                raise PipelineError(
                    f"provider 'gemini' rejected the credential (HTTP {exc.code}); "
                    "check the key in GEMINI_API_KEY / GOOGLE_API_KEY"
                ) from exc
            if exc.code == 429:
                raise PipelineError(
                    f"provider 'gemini' rate-limited or quota-exhausted the request "
                    f"(HTTP 429): {detail}"
                ) from exc
            raise PipelineError(
                f"provider 'gemini' refused the review (HTTP {exc.code}): {detail}"
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
            raise PipelineError(f"provider 'gemini' returned a non-JSON envelope: {exc}") from exc

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
        if finish and finish not in ("STOP", "MAX_TOKENS"):
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
