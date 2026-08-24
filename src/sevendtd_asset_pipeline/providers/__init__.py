"""The provider registry for `shamway review-audio`.

`resolve_provider` is the only way the operation obtains an adapter, so a
provider name is validated in exactly one place. `configuration_state` is what
the capability registry reads: it answers from environment presence alone and
never contacts a provider, which keeps discovery, `doctor`, and `status`
offline.
"""

from __future__ import annotations

from collections.abc import Callable

from ..errors import PipelineError
from .base import AudioReviewProvider
from .fake import FakeProvider
from .gemini import GeminiProvider

PROVIDERS: dict[str, Callable[[], AudioReviewProvider]] = {
    "gemini": GeminiProvider,
    "fake": FakeProvider,
}

CONFIGURED = "configured"
UNAVAILABLE = "unavailable"


def resolve_provider(name: str) -> AudioReviewProvider:
    factory = PROVIDERS.get(name)
    if factory is None:
        raise PipelineError(
            f"unknown provider {name!r}; expected one of: {', '.join(sorted(PROVIDERS))}"
        )
    return factory()


def configuration_state() -> dict[str, str]:
    """Per-provider CONFIGURED or UNAVAILABLE, from credential presence alone."""
    state: dict[str, str] = {}
    for name, factory in sorted(PROVIDERS.items()):
        provider = factory()
        if not provider.requires_credential:
            continue
        state[name] = CONFIGURED if provider.is_configured() else UNAVAILABLE
    return state
