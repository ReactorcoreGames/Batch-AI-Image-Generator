"""Provider interface.

Deliberately tiny: prompt + size -> image bytes. Everything model-specific
(request encoding, response decoding, pricing) lives inside the implementation
and is described by the registry in core.models.

Failure taxonomy matters more than the happy path. The engine's retry logic is
driven entirely by which exception it catches:

    TransientError   — retry with backoff (network, 5xx, corrupt response)
    RateLimited      — retry with patience (429; honour Retry-After)
    PermanentError   — never retry (bad request, auth, content block)
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from ..models import ModelSpec
from ..reference import PreparedReference


class ProviderError(Exception):
    """Base for anything a provider raises during generation."""


class TransientError(ProviderError):
    """Worth retrying with exponential backoff."""


class RateLimited(TransientError):
    """HTTP 429 or an explicit provider rate limit.

    Carries the server's Retry-After when it gave one, so the engine can wait
    exactly as long as asked rather than guessing.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(ProviderError):
    """Retrying will not help — bad params, bad credentials, or a refusal."""


class ContentBlocked(PermanentError):
    """The provider returned a blank frame: its content filter refused.

    Kept distinct from PermanentError so the UI and logs can say 'rewrite this
    prompt' rather than 'something broke'.
    """


class AuthError(PermanentError):
    """Missing or rejected credentials. Fatal for the whole batch, not one job."""


class QuotaExhausted(PermanentError):
    """Daily free allowance spent. Not retryable; not the user's fault.

    Distinct from RateLimited: a 429 for this reason will not clear with
    backoff — it does not move for hours, and the provider exposes no way to
    poll for recovery. Fatal for the whole batch, like AuthError, but the job
    that surfaced it was never given a fair attempt and must not be marked
    failed.
    """


@dataclass
class GenerationResult:
    image_bytes: bytes
    ext: str                    # sniffed from magic bytes, never from headers
    width: int
    height: int
    model: str                  # registry key
    model_id: str               # provider-side id
    provider: str
    seed: int | None
    elapsed: float
    cost_estimate: float
    tiles: int
    response_encoding: str
    declared_content_type: str = ""
    actual_dimensions: tuple[int, int] | None = None
    extra: dict = field(default_factory=dict)


class Provider(abc.ABC):
    """One provider, potentially serving several models."""

    name: str = "provider"

    @abc.abstractmethod
    def generate(
        self,
        model: ModelSpec,
        prompt: str,
        width: int,
        height: int,
        seed: int | None = None,
        negative_prompt: str | None = None,
        guidance: float | None = None,
        steps: int | None = None,
        timeout: float = 180.0,
        prompt_expansion: str | None = None,
        content_filter: str | None = None,
        reference: "PreparedReference | None" = None,
    ) -> GenerationResult:
        """Generate one image, or raise one of the errors above.

        `prompt_expansion` is honoured only by models whose spec sets
        supports_prompt_expansion; everywhere else it is ignored rather than
        rejected, so callers need not know which models have it.

        `content_filter` behaves the same way: it is honoured only by models
        whose spec names a content_filter_field (p-image and flux-2-pro), and
        is ignored everywhere else. Callers pass it unconditionally.

        `reference` is a prepared style reference image (core.reference), and
        follows the same convention once more: it is honoured only by models
        whose spec names a reference_field, and ignored rather than rejected
        everywhere else. The caller prepares it ONCE before the batch and
        passes the same object to every generation -- preparing it per image
        would decode and resize the same file hundreds of times.
        """

    max_concurrency: int = 0        # 0 = no provider-imposed limit

    def check(self) -> tuple[bool, str]:
        """Validate credentials/reachability. (ok, human-readable message)."""
        return True, f"{self.name}: no credential check implemented"

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
