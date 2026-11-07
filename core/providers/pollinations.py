"""Pollinations.ai — keyless free fallback.

No credentials at all: the request is a plain GET whose path carries the
URL-encoded prompt. That makes it the zero-setup lane when Cloudflare
credentials are missing or its free tier is unavailable.

MEASURED 2026-08-31, superseding the earlier guesses here:

  * Keyless allows roughly one request per 15 seconds, so the default
    inter-request delay is deliberately 15s rather than the engine's usual
    value. `nologo=true` is always sent and no watermark was seen on any
    output, keyed or keyless.
  * An API key raises the quota and shortens that gap to about 1s, but does
    NOT lift the one-request-per-IP queue limit -- see `max_concurrency`.

The key is OPTIONAL and read from POLLINATIONS_API_KEY, so the keyless path
stays fully supported rather than being a fallback.
"""

from __future__ import annotations

import os
import time
import urllib.parse

import httpx

from .. import imagecheck
from ..models import ModelSpec, tile_count
from .base import (
    ContentBlocked,
    GenerationResult,
    PermanentError,
    Provider,
    RateLimited,
    TransientError,
)

BASE_URL = "https://image.pollinations.ai/prompt"

# The anonymous tier is roughly 1 request / 15s. The engine reads this so it
# paces itself correctly without the user having to know.
MIN_INTERVAL_SECONDS = 15.0


class PollinationsProvider(Provider):
    name = "pollinations"

    def __init__(
        self, api_key: str | None = None, client: httpx.Client | None = None
    ):
        # None means "use whatever is configured"; an empty string means
        # "deliberately send NO key" -- the GUI's keyless mode relies on being
        # able to say that even when a key is saved. `or` would conflate them.
        if api_key is None:
            api_key = os.environ.get("POLLINATIONS_API_KEY", "")
        self.api_key = api_key.strip()
        self._client = client
        self._owns_client = client is None

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    @property
    def min_interval(self) -> float:
        """Seconds to leave between requests.

        MEASURED: with a key, six back-to-back serial requests with no delay
        all succeeded, so 1s here is politeness rather than a required cap.
        Keyless still needs the full interval."""
        return 1.0 if self.has_key else MIN_INTERVAL_SECONDS

    @property
    def max_concurrency(self) -> int:
        """Requests that may be IN FLIGHT at once. One, key or no key.

        MEASURED 2026-08-31, and this corrects an earlier guess of 4-with-key.
        Pollinations queues exactly ONE request per IP ADDRESS and rejects the
        rest outright --

            "Queue full for IP: ...: 1 requests already queued (max: 1)"

        An API key does NOT lift this. It is keyed to the IP, not the account.
        Probed directly: 6 serial requests with a key and no delay at all
        succeeded 6/6, while overlapping pairs kept returning 429 whether the
        key was sent as a Bearer header or as a `token` query parameter.

        (Concurrent bursts do sometimes appear to succeed, but only because a
        repeated prompt+seed is served from cache in under a second rather
        than being generated. That made an earlier probe read as 2/2 and is
        why this needs measuring with unique prompts.)

        A second worker therefore cannot help; it can only produce 429s that
        burn each job's retry budget.
        """
        return 1

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.has_key else {}

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(follow_redirects=True)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def check(self) -> tuple[bool, str]:
        try:
            r = self.client.get(
                f"{BASE_URL}/{urllib.parse.quote('a small blue square')}",
                params={"width": 256, "height": 256, "nologo": "true"},
                headers=self._headers(),
                timeout=60.0,
            )
        except Exception as e:
            return False, f"could not reach Pollinations: {type(e).__name__}: {e}"
        if r.status_code == 200 and imagecheck.decodes(r.content):
            mode = "with API key" if self.has_key else "keyless (no key needed)"
            return True, f"Pollinations reachable — {mode}"
        return False, f"Pollinations check failed: HTTP {r.status_code}"

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
        prompt_expansion: str | None = None,   # not supported here; ignored
        content_filter: str | None = None,     # no filter control; ignored
        reference: object = None,              # txt2img only; ignored
    ) -> GenerationResult:
        errs = model.validate_size(width, height)
        if errs:
            raise PermanentError("; ".join(errs))

        params: dict[str, str] = {
            "model": model.id,
            "width": str(width),
            "height": str(height),
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = str(seed)

        url = f"{BASE_URL}/{urllib.parse.quote(prompt, safe='')}"
        t0 = time.time()
        try:
            r = self.client.get(
                url, params=params, headers=self._headers(), timeout=timeout
            )
        except httpx.TimeoutException as e:
            raise TransientError(f"request timed out after {timeout}s: {e}") from e
        except httpx.HTTPError as e:
            raise TransientError(f"{type(e).__name__}: {e}") from e
        elapsed = time.time() - t0

        if r.status_code == 429:
            ra = r.headers.get("retry-after")
            try:
                retry_after = float(ra) if ra else MIN_INTERVAL_SECONDS
            except ValueError:
                retry_after = MIN_INTERVAL_SECONDS
            raise RateLimited(f"rate limited (429): {r.text[:300]}", retry_after)
        if r.status_code in (401, 403):
            raise PermanentError(f"HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code != 200:
            raise TransientError(f"HTTP {r.status_code}: {r.text[:300]}")

        data = r.content
        if not imagecheck.decodes(data):
            raise TransientError(
                f"response is not a decodable image ({len(data)} bytes)"
            )
        if imagecheck.is_blank(data):
            raise ContentBlocked(
                "provider returned a flat-colour frame — content filter refused."
            )

        return GenerationResult(
            image_bytes=data,
            ext=imagecheck.sniff_ext(data),
            width=width,
            height=height,
            model=model.key,
            model_id=model.id,
            provider="pollinations",
            seed=seed,
            elapsed=round(elapsed, 2),
            cost_estimate=0.0,
            tiles=tile_count(width, height),
            response_encoding="raw",
            declared_content_type=r.headers.get("content-type", ""),
            actual_dimensions=imagecheck.dimensions(data),
        )
