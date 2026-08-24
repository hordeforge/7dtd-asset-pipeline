"""The provider boundary for model audio review.

An adapter is deliberately narrow: it knows its credential environment, the
audio formats and payload size it accepts, how to submit audio plus a prompt,
and how to bring back raw text plus usage metadata. Everything else — intent
validation, rubric, result schema, evidence — belongs to `audio_review.py` and
is identical across providers, so adding one never forks the contract.

Adapters speak HTTP with the standard library. A build tool that already
carries no SDK has no reason to grow one, and every dependency avoided here is
a supply-chain surface a mod author never has to audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..errors import PipelineError

# The container types any adapter may accept, mapped to their MIME names.
MIME_BY_SUFFIX = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
    ".aac": "audio/aac",
}


@dataclass(frozen=True)
class ProviderLimits:
    """What this provider accepts, so refusal happens locally and cheaply."""

    suffixes: tuple[str, ...]
    """Filename suffixes (lowercase, dot included) the endpoint consumes."""
    max_bytes: int | None
    """Total audio bytes per request; None when the provider publishes no bound."""


@dataclass(frozen=True)
class AudioPayload:
    """One submitted file's exact bytes, name, and content type."""

    name: str
    mime_type: str
    data: bytes


@dataclass(frozen=True)
class ReviewRequest:
    """Everything a submission needs, assembled by `audio_review.run_review`."""

    prompt: str
    audios: tuple[AudioPayload, ...]
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class ReviewResponse:
    """The boundary's output: raw text, verbatim usage, what the model said."""

    raw_text: str
    usage: dict[str, Any] | None
    """Provider-reported token counts, passed through untouched or None."""
    model_reported: str | None
    """The model identifier as the provider states it, when it does."""


class AudioReviewProvider(Protocol):
    """One hosted audio-capable model endpoint."""

    name: str
    endpoint_mode: str
    requires_credential: bool

    @property
    def default_model(self) -> str: ...

    @property
    def limits(self) -> ProviderLimits: ...

    def mime_for(self, suffix: str) -> str: ...

    def is_configured(self) -> bool:
        """Whether the credential material is present in the environment.

        Presence only: this must never contact the provider, so capability
        discovery, `doctor`, and `status` stay offline.
        """
        ...

    def configuration_hint(self) -> str:
        """How to configure it, naming the route and never any secret value."""
        ...

    def review(self, request: ReviewRequest) -> ReviewResponse:
        """Submit audio plus prompt; raise PipelineError on refusal or fault."""
        ...


def mime_for_suffix(suffix: str) -> str:
    try:
        return MIME_BY_SUFFIX[suffix]
    except KeyError:
        raise PipelineError(
            f"no MIME type is known for {suffix!r}; accepted containers are "
            + ", ".join(sorted(MIME_BY_SUFFIX))
        ) from None
