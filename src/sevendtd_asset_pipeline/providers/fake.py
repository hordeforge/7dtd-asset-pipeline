"""The offline stand-in adapter.

It answers from the request metadata alone and hears nothing, which is the
point: the tests assert on what it *received* — the exact audio bytes, by
hash, and the complete prompt — so the boundary's contract is pinned without
any network. It is also the dry-run lane for a caller who wants to prove an
intent file and evidence plumbing end to end before paying for a real
submission.
"""

from __future__ import annotations

import hashlib
import json

from .base import ProviderLimits, ReviewRequest, ReviewResponse, mime_for_suffix


class FakeProvider:
    name = "fake"
    endpoint_mode = "in-process-fake"
    requires_credential = False
    _limits = ProviderLimits(suffixes=(".wav", ".mp3", ".ogg", ".flac"), max_bytes=4 * 1024 * 1024)

    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    @property
    def default_model(self) -> str:
        return "shamway-audio-auditor-v1"

    @property
    def limits(self) -> ProviderLimits:
        return self._limits

    def mime_for(self, suffix: str) -> str:
        return mime_for_suffix(suffix)

    def is_configured(self) -> bool:
        return True

    def configuration_hint(self) -> str:
        return "the fake provider needs no credentials; it exists for offline plumbing checks"

    def review(self, request: ReviewRequest) -> ReviewResponse:
        self.requests.append(request)
        digests = {
            payload.name: hashlib.sha256(payload.data).hexdigest() for payload in request.audios
        }
        candidate = request.audios[0]
        candidate_digest = digests[candidate.name]
        payload = {
            "summary": (
                f"Received {len(candidate.data)} bytes named {candidate.name!r} "
                f"(sha256 {candidate_digest[:16]}). The fake provider hears nothing "
                "and critiques from the request envelope only."
            ),
            "strengths": ["the submission crossed the provider boundary intact"],
            "issues": [
                {
                    "description": (
                        "every submitted byte is suspect by construction: this "
                        "verdict came from the fake provider, not from listening"
                    ),
                    "at_seconds": [0.0, 0.5],
                }
            ],
            "recommended_changes": [
                "rerun against a configured real provider for an actual audition"
            ],
            "rubric_scores": {"semantic_fit": None, "harshness_risk": None},
            "confidence": 0.42,
            "limitations": [
                "the fake adapter received bytes and prompt but cannot hear",
                f"prompt digest prefix {hashlib.sha256(request.prompt.encode('utf-8')).hexdigest()[:16]}",
            ],
        }
        # usage stays None on purpose: unavailable must be reported as
        # unavailable, never estimated.
        return ReviewResponse(
            raw_text=json.dumps(payload), usage=None, model_reported=self.default_model
        )
