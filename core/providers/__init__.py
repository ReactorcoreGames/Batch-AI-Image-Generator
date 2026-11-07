"""Provider registry and factory."""

from __future__ import annotations

from .base import (
    AuthError,
    ContentBlocked,
    GenerationResult,
    PermanentError,
    Provider,
    ProviderError,
    RateLimited,
    TransientError,
)
from .cloudflare import CloudflareProvider
from .pollinations import PollinationsProvider

PROVIDERS: dict[str, type[Provider]] = {
    "cloudflare": CloudflareProvider,
    "pollinations": PollinationsProvider,
}

DEFAULT_PROVIDER = "cloudflare"


def get_provider(name: str, **kwargs) -> Provider:
    try:
        cls = PROVIDERS[name]
    except KeyError:
        raise KeyError(
            f"unknown provider {name!r}. Known: {', '.join(sorted(PROVIDERS))}"
        ) from None
    return cls(**kwargs)


def provider_for_model(model_key: str, **kwargs) -> Provider:
    """Build the provider that serves a given model key."""
    from ..models import get_model

    return get_provider(get_model(model_key).provider, **kwargs)


__all__ = [
    "AuthError",
    "CloudflareProvider",
    "ContentBlocked",
    "DEFAULT_PROVIDER",
    "GenerationResult",
    "PermanentError",
    "PROVIDERS",
    "PollinationsProvider",
    "Provider",
    "ProviderError",
    "RateLimited",
    "TransientError",
    "get_provider",
    "provider_for_model",
]
