"""Cloudflare Workers AI provider.

Request code lifted from spike/spike_cloudflare.py, which is already validated
against the live API. The two encodings are NOT interchangeable:

    JSON body        — the three SD-family models
    multipart/form   — both klein models (and `steps` is fixed at 4, not settable)

And the two response shapes are not interchangeable either:

    raw          — SD-family return image bytes directly in the HTTP body
    json_base64  — klein returns base64 inside a JSON envelope at result.image
"""

from __future__ import annotations

import base64
import json
import os
import time

import httpx

from .. import imagecheck
from ..reference import (
    WIRE_CONTENT_TYPE as REFERENCE_CONTENT_TYPE,
    WIRE_FILENAME as REFERENCE_FILENAME,
    PreparedReference,
)
from ..models import (
    DEFAULT_PROMPT_EXPANSION,
    NANO_BANANA_TIER_RESOLUTION,
    PROMPT_EXPANSION_MODES,
    RATIOS,
    RATIO_TO_ENUM,
    SIZES_NANO_BANANA,
    TIERS,
    ModelSpec,
    filter_value_for,
    nano_banana_resolution,
    recraft_size_string,
    tile_count,
    wire_output_format,
)
from .base import (
    AuthError,
    ContentBlocked,
    GenerationResult,
    PermanentError,
    Provider,
    QuotaExhausted,
    RateLimited,
    TransientError,
)

# 429 error code for "daily free neuron allowance spent". Verbatim body
# (measured 2026-09-05):
#   {"code":4006,"message":"AiError: AiError: you have used up your daily
#   free allocation of 10,000 neurons, please upgrade to Cloudflare's Workers
#   Paid plan if you would like to continue usage."}
# Cloudflare documents the reset as 00:00 UTC but it was measured still
# blocking 7 hours past that, with the GraphQL usage counter reading 0 — a
# known upstream bug. The true duration is not predictable and must not be
# waited out in-process; see docs/findings.md.
QUOTA_EXHAUSTED_CODE = 4006

# Gateway models report request-validation errors as HTTP 400 with code 7003,
# distinct from the native models' 5006. Verified 2026-09-04: the gateway
# validates BEFORE charging, so a malformed request costs nothing and the 400
# body names every legal field. See docs/gateway-models-todo.md.
GATEWAY_BAD_REQUEST_CODE = 7003

BASE_URL = "https://api.cloudflare.com/client/v4"

# Cloudflare's own dashboard is the only trustworthy usage readout: the API's
# totalNeurons reads 0 even for models that definitely bill. See SPIKE_RESULTS §2.
#
# TWO dashboards, because the two model families are billed from entirely
# different pots and each page is meaningless for the other family:
#   * native models  -> Workers AI, which shows the free daily NEURON allowance
#   * gateway models -> AI Gateway, which shows the prepaid CREDIT balance
# Sending a gateway user to the neuron page (which is what this program did
# until 2026-09-05) shows them a quota their batch does not draw on at all.
USAGE_DASHBOARD_URL = "https://dash.cloudflare.com/?to=/:account/ai/workers-ai"
CREDITS_DASHBOARD_URL = "https://dash.cloudflare.com/?to=/:account/ai/ai-gateway"

# Cloudflare applies a 5% fee on credit purchases: $100 of credit costs $105.
# Documented at developers.cloudflare.com/ai-gateway/features/unified-billing/.
# Kept here rather than written into a GUI string so there is one place to
# correct if Cloudflare changes it. DOC-DERIVED, not measured.
CREDIT_PURCHASE_FEE_PERCENT = 5


def reference_data_uri(reference: PreparedReference) -> str:
    """A prepared reference as a `data:image/png;base64,...` URI.

    The gateway families that take a reference want it inline rather than as
    a file part, and both spell it as a data URI in a list. Built here rather
    than in core.reference because it is a wire detail of this provider --
    the prepared object stays plain bytes so a future provider can encode it
    however it needs to.
    """
    encoded = base64.b64encode(reference.data).decode("ascii")
    return f"data:{REFERENCE_CONTENT_TYPE};base64,{encoded}"


class _PresignedURL(str):
    """Marker for a result.image that is a URL rather than image bytes.

    A str subclass so it cannot be mistaken for bytes anywhere downstream --
    anything that tries to treat it as image data fails loudly and immediately
    rather than writing a text file full of a URL and calling it a PNG.
    """


class CloudflareProvider(Provider):
    name = "cloudflare"

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        client: httpx.Client | None = None,
    ):
        self.account_id = (account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")).strip()
        self.api_token = (api_token or os.environ.get("CLOUDFLARE_API_TOKEN", "")).strip()
        self._client = client
        self._owns_client = client is None

    # -- plumbing ---------------------------------------------------------

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def _require_creds(self) -> None:
        missing = [
            n
            for n, v in (
                ("CLOUDFLARE_ACCOUNT_ID", self.account_id),
                ("CLOUDFLARE_API_TOKEN", self.api_token),
            )
            if not v
        ]
        if missing:
            raise AuthError(
                "missing credential(s): "
                + ", ".join(missing)
                + ". Set them as environment variables, then open a new shell "
                "(setx does not affect the current one)."
            )

    def check(self) -> tuple[bool, str]:
        """Validate the token.

        GOTCHA: use /accounts/{id}/tokens/verify, NOT /user/tokens/verify —
        the latter returns 401 for a perfectly valid *account* token.
        """
        try:
            self._require_creds()
        except AuthError as e:
            return False, str(e)
        url = f"{BASE_URL}/accounts/{self.account_id}/tokens/verify"
        try:
            r = self.client.get(url, headers=self._headers(), timeout=30.0)
        except Exception as e:
            return False, f"could not reach Cloudflare: {type(e).__name__}: {e}"
        if r.status_code == 200:
            try:
                msg = r.json()["result"]["status"]
            except Exception:
                msg = "valid"
            return True, f"Cloudflare token {msg} (account {self.account_id[:8]}...)"
        return False, f"token verify failed: HTTP {r.status_code} {r.text[:300]}"

    # -- generation -------------------------------------------------------

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
        reference: PreparedReference | None = None,
    ) -> GenerationResult:
        self._require_creds()

        errs = model.validate_size(width, height)
        if errs:
            # A size the model cannot accept will never succeed on retry.
            raise PermanentError("; ".join(errs))

        # A reference is DROPPED, never forwarded, on a model that cannot take
        # one. The caller passes it unconditionally (the same convention
        # prompt_expansion and content_filter follow), and `reference_field is
        # None` is the single gate -- no model list is written here, because
        # core.models owns that question.
        if reference is not None and model.reference_field is None:
            reference = None

        if reference is not None:
            # Belt and braces against a reference prepared for a different
            # model. The floor and ceiling are per-model, and a reference that
            # violates them is refused with a generic HTTP 400 naming neither
            # the field nor the size -- on a PAID model that 400 is free, but
            # the user is left with nothing to act on, which is the whole
            # reason the check exists client-side.
            self._validate_reference(model, reference)

        # Native models put the model id in the URL PATH. Gateway models post
        # to the bare /ai/run endpoint with the id in the request BODY.
        if model.call_style == "gateway":
            url = f"{BASE_URL}/accounts/{self.account_id}/ai/run"
        else:
            url = f"{BASE_URL}/accounts/{self.account_id}/ai/run/{model.id}"
        t0 = time.time()

        try:
            if model.call_style == "gateway":
                r = self.client.post(
                    url,
                    headers=self._headers(),
                    json=self._gateway_payload(
                        model, prompt, width, height, seed, prompt_expansion,
                        content_filter, reference,
                    ),
                    timeout=timeout,
                )
            elif model.request_encoding == "json":
                payload: dict = {"prompt": prompt, "width": width, "height": height}
                if seed is not None:
                    payload["seed"] = seed
                if negative_prompt and model.supports_negative_prompt:
                    payload["negative_prompt"] = negative_prompt
                if model.supports_guidance:
                    g = guidance if guidance is not None else model.default_guidance
                    if g is not None:
                        payload["guidance"] = g
                if model.steps_settable:
                    n = steps if steps is not None else model.default_steps
                    if n is not None:
                        if model.max_steps is not None:
                            n = min(n, model.max_steps)
                        payload["num_steps"] = n
                r = self.client.post(
                    url, headers=self._headers(), json=payload, timeout=timeout
                )
            else:
                # multipart/form-data. `steps` is fixed at 4 and NOT settable —
                # sending it is rejected, so it is never included.
                fields: dict[str, tuple[None, str]] = {
                    "prompt": (None, prompt),
                    "width": (None, str(width)),
                    "height": (None, str(height)),
                }
                if seed is not None:
                    fields["seed"] = (None, str(seed))
                if model.supports_guidance:
                    g = guidance if guidance is not None else model.default_guidance
                    if g is not None:
                        fields["guidance"] = (None, str(g))
                # The style reference is ONE MORE multipart part, carrying the
                # raw file bytes with a filename and a content-type. MEASURED
                # 2026-09-19: this is the whole change for klein, and it works
                # exactly as Cloudflare's own curl example shows.
                #
                # Always index 0, and never more than one. The field is
                # `input_image_0..3` and the models accept up to four, but
                # multi-image and per-image weighting are single-image EDITING
                # features -- this is a batch STYLE lever, by decision.
                if reference is not None:
                    fields[model.reference_field] = (
                        REFERENCE_FILENAME, reference.data, REFERENCE_CONTENT_TYPE
                    )
                r = self.client.post(
                    url, headers=self._headers(), files=fields, timeout=timeout
                )
        except httpx.TimeoutException as e:
            raise TransientError(f"request timed out after {timeout}s: {e}") from e
        except httpx.HTTPError as e:
            raise TransientError(f"{type(e).__name__}: {e}") from e

        elapsed = time.time() - t0
        self._raise_for_status(r)

        data = self._extract_image(r, model)
        if isinstance(data, _PresignedURL):
            data = self._fetch_presigned(str(data), timeout)
            # The second request is part of generating this image, so its time
            # belongs in the elapsed figure the run tab reports.
            elapsed = time.time() - t0
        return self._finish(data, r, model, prompt, width, height, seed, elapsed)

    @staticmethod
    def _validate_reference(model: ModelSpec, reference: PreparedReference) -> None:
        """Refuse a reference this model cannot accept, with a real message.

        MEASURED 2026-09-19: klein rejects an out-of-range reference with a
        generic HTTP 400 `AiError: Invalid input` (code 8001) that names
        neither the field nor the size. A user who sent a 32x32 sprite would
        get an unexplainable failure on every line of the batch, so the check
        belongs here, where the numbers are still known.

        core.reference.prepare() already brings every image into range, so
        reaching this is a programming error rather than a user one -- but a
        reference prepared against one model's limits and sent to another
        with a lower ceiling is exactly the kind of drift the per-model
        fields exist to allow, so it is checked rather than assumed.
        """
        lo, hi = model.reference_min_dimension, model.reference_max_dimension
        for name, v in (("width", reference.width), ("height", reference.height)):
            if v < lo:
                raise PermanentError(
                    f"reference image {name} {v}px is below {model.short_name}'s "
                    f"{lo}px minimum (it applies to each side, not the total)")
            if v > hi:
                raise PermanentError(
                    f"reference image {name} {v}px is above {model.short_name}'s "
                    f"{hi}px maximum")

    @staticmethod
    def _ratio_key_for(width: int, height: int) -> str | None:
        """Recover the program's ratio key from a pixel size.

        Enum-based models need the ratio NAME, but everything upstream passes
        pixels. Matching on the numeric ratio rather than the exact size means
        this keeps working if the krea size estimates are later corrected to
        measured values.

        The reference table is the program's OWN five ratios rather than any
        one model's size table: nano-banana's nominal "16:9" is 1344x768
        (1.750) where krea's estimate is 1328x752 (1.766), so a lookup keyed
        to krea's numbers alone would be matching one model's sizes against
        another model's request. The tolerance is widened to cover exactly
        that spread -- these nominal ratios drift up to ~1.6% from the true
        value, and 1:1 must still not collide with 3:2 (1.5) in either
        direction, which it comfortably does not.
        """
        if height <= 0:
            return None
        target = width / height
        best: tuple[float, str] | None = None
        for key in RATIOS:
            num, den = key.split(":")
            diff = abs(target - int(num) / int(den))
            if diff < 0.05 and (best is None or diff < best[0]):
                best = (diff, key)
        return best[1] if best is not None else None

    @staticmethod
    def _nano_banana_tier_for(
        model_key: str, ratio_key: str, width: int, height: int
    ) -> str | None:
        """Which program tier a nano-banana pixel size belongs to.

        Returns the FIRST tier whose mapped resolution produces this exact
        size. On a model pinned to one resolution every tier maps to the same
        pixels, so any of them is the right answer; on a laddered model the
        sizes are distinct and the match is unique either way.
        """
        per_ratio = SIZES_NANO_BANANA.get(ratio_key)
        if per_ratio is None:
            return None
        for tier in TIERS:
            res = NANO_BANANA_TIER_RESOLUTION[model_key].get(tier)
            if res is not None and per_ratio.get(res) == (width, height):
                return tier
        return None

    @staticmethod
    def _gateway_payload(
        model: ModelSpec,
        prompt: str,
        width: int,
        height: int,
        seed: int | None,
        prompt_expansion: str | None = None,
        content_filter: str | None = None,
        reference: PreparedReference | None = None,
    ) -> dict:
        """Build the gateway request body: {"model": id, "input": {...}}.

        Each gateway family speaks its own size vocabulary and rejects the
        others outright -- p-image rejects nothing but only honours
        width/height under aspect_ratio="custom", and Recraft rejects
        `aspect_ratio` entirely. The size_style on the spec picks the branch.
        """
        inp: dict = {"prompt": prompt}

        if model.size_style == "aspect_ratio":
            # p-image. Two ways to express size, and they are exclusive:
            # width/height are accepted ONLY when aspect_ratio="custom".
            # Pixels are sent, because the program's sizes are chosen
            # deliberately and the bare ratio enum would let the provider
            # pick its own resolution.
            inp["aspect_ratio"] = "custom"
            inp["width"] = width
            inp["height"] = height
        elif model.size_style == "aspect_ratio_resolution":
            # krea. Takes a ratio ENUM plus a resolution tier and rejects
            # width/height outright -- the pixels the rest of the app carries
            # around are a display estimate here, never a request parameter.
            # Both fields are REQUIRED; omitting either errors.
            ratio_key = CloudflareProvider._ratio_key_for(width, height)
            ratio = RATIO_TO_ENUM.get(ratio_key) if ratio_key else None
            if ratio is None:
                raise PermanentError(
                    f"{model.id} cannot serve a {width}x{height} image: its "
                    f"aspect_ratio is an enum and this size matches none of "
                    f"the program's ratios."
                )
            inp["aspect_ratio"] = ratio
            # `resolution` is a WORD, not pixels, and the two families in this
            # size_style disagree about which words are legal:
            #
            #   krea         "1K" only -- the validator accepts nothing else
            #   nano-banana  "1K"/"2K"/"4K" declared, and on the full model the
            #                PRICE CHANGES WITH IT
            #
            # So it cannot be a constant here. nano_banana_resolution() is the
            # only legal source of the value for that family, and it is looked
            # up from the model's own tier mapping rather than derived from the
            # tier name -- because nano-banana-2-lite is pinned to 1K at every
            # tier while its sibling is not. Getting this wrong is the single
            # most expensive mistake available in this file: on nano-banana-2
            # a 4K image costs 2.3x a 1K one, so a quoted price and a sent
            # resolution that disagree would bill the user for something the
            # estimate never showed them.
            #
            # The tier is recovered from the SIZE rather than passed down,
            # for the same reason the ratio is: the pixels are what every
            # caller already carries, and each entry in the family's size
            # table is distinct, so the recovery is exact.
            if model.key in NANO_BANANA_TIER_RESOLUTION:
                tier = CloudflareProvider._nano_banana_tier_for(
                    model.key, ratio_key, width, height)
                if tier is None:
                    raise PermanentError(
                        f"{model.id} cannot serve a {width}x{height} image: "
                        f"its resolution is an enum of 1K/2K/4K and this size "
                        f"matches none of its published dimensions."
                    )
                inp["resolution"] = nano_banana_resolution(model.key, tier)
            else:
                inp["resolution"] = "1K"   # krea: the only value it accepts
        elif model.size_style == "size_enum":
            # Recraft. An opaque enum of "WxH" STRINGS -- not aspect_ratio
            # (rejected outright) and not width/height either.
            #
            # This is the one gateway model whose size cannot be validated for
            # free. The gateway type-checks only that the value is a string
            # and defers the VALUE check to Recraft, so a bad size gets past
            # the gateway, is BILLED, and then fails at generation time.
            # recraft_size_string() checks it against the published enum here,
            # before the request leaves, which is the only point at which the
            # mistake is still free.
            #
            # Always sent: Recraft's own default is "1024x1024", a SQUARE, so
            # silence would quietly turn a 16:9 batch into 1:1 crops.
            try:
                inp["size"] = recraft_size_string(width, height)
            except ValueError as e:
                raise PermanentError(str(e)) from e
            # `style` / `substyle` are deliberately UNSET: both are optional,
            # their enum values are unconfirmed for the gateway path, and a
            # wrong one is a paid failure for the same reason `size` is.
            # `controls` (colors / background_color / image) is skipped too --
            # `controls.image` is reference-image shaped and permanently out
            # of scope for this txt2img program.
        elif model.size_style == "pixels":
            inp["width"] = width
            inp["height"] = height
        else:
            raise PermanentError(
                f"size_style {model.size_style!r} is not implemented yet for "
                f"{model.id}"
            )

        if seed is not None and model.supports_seed:
            inp["seed"] = seed

        if model.supports_prompt_expansion:
            # `creativity` is krea's prompt-expansion mode. Sent ALWAYS rather
            # than only when it differs from the API default, because the API
            # default ("low") is expansion ON -- staying silent would leave the
            # model rewriting prompts the user never asked it to touch.
            mode = prompt_expansion or DEFAULT_PROMPT_EXPANSION
            if mode not in PROMPT_EXPANSION_MODES:
                raise PermanentError(
                    f"unknown prompt expansion mode {mode!r}; expected one of "
                    + ", ".join(PROMPT_EXPANSION_MODES)
                )
            inp["creativity"] = mode

        # `output_format` is sent whenever the model accepts it, rather than
        # left to the provider. flux-2-pro's default is "jpeg", which is NOT a
        # neutral value -- it silently picks a lossy format for a batch the
        # user may want lossless. The same reasoning as krea's `creativity`:
        # a field whose default is not the neutral choice is worth stating.
        #
        # The wire spelling is derived, never written out here: this model
        # says "jpeg" and nano-banana says "jpg" for the same format.
        fmt = wire_output_format(model)
        if fmt is not None:
            inp["output_format"] = fmt

        # Content filter. Only two models in the whole lineup expose one, and
        # they take different field names and different value types -- the
        # mapping lives in core.models so nothing here has to know which.
        #
        # `filter_value_for` returns None for the "default" mode, and nothing
        # is sent: inheriting the provider's own default is expressed by
        # SILENCE rather than by pinning today's documented value, so the
        # program follows the provider if it ever moves.
        #
        # The PROGRAM's own default is "permissive", not "default" -- a batch
        # tool pays for a false refusal in a slot of an overnight run rather
        # than in a rerun, and these two models are the only lever against a
        # refusal that is otherwise invisible. See DEFAULT_CONTENT_FILTER.
        try:
            pair = filter_value_for(model, content_filter)
        except ValueError as e:
            raise PermanentError(str(e)) from e
        if pair is not None:
            inp[pair[0]] = pair[1]

        # The style reference, as a `data:` base64 URI inside a LIST. The
        # field NAME differs across the two families that take one --
        # `image_input` on nano-banana, `input_images` on flux-2-pro -- so it
        # is read from the spec rather than written here, the same discipline
        # `output_format`'s jpeg/jpg split taught.
        #
        # Exactly one entry, at index 0. Both families accept several; multi
        # image is an editing feature and is out of scope by decision.
        #
        # Gated on reference_field, so krea, Recraft and p-image cannot
        # receive one even if a caller hands one over -- krea would refuse a
        # data: URI outright ("Must be an HTTP(S) URL") and the other two have
        # no such field at all.
        if reference is not None and model.reference_encoding == "base64":
            inp[model.reference_field] = [reference_data_uri(reference)]

        return {"model": model.id, "input": inp}

    def _fetch_presigned(self, url: str, timeout: float) -> bytes:
        """GET the image bytes from a presigned URL (the krea response shape).

        Deliberately sends NO Authorization header: the URL is already signed,
        and forwarding the Cloudflare token to whatever host the signature
        points at would leak the credential to a third party.

        Every failure here is TRANSIENT. The image was generated and BILLED
        before this URL was handed over, so a failed fetch means a paid image
        was lost -- retrying is both correct and the only way to recover it.
        """
        if not url.startswith("https://"):
            # Refuse to fetch over plaintext; a signed URL should never be
            # http, and following one would be a downgrade.
            raise PermanentError(f"refusing non-HTTPS image URL: {url[:120]}")
        try:
            r = self.client.get(url, timeout=timeout, follow_redirects=True)
        except httpx.TimeoutException as e:
            raise TransientError(
                f"timed out fetching the generated image after {timeout}s "
                f"(the image was already generated and billed): {e}"
            ) from e
        except httpx.HTTPError as e:
            raise TransientError(
                f"could not fetch the generated image ({type(e).__name__}: {e}) "
                f"— it was already generated and billed"
            ) from e
        if r.status_code != 200:
            raise TransientError(
                f"HTTP {r.status_code} fetching the generated image "
                f"(already generated and billed): {r.text[:200]}"
            )
        if not r.content:
            raise TransientError("presigned URL returned an empty body")
        return r.content

    # -- response handling ------------------------------------------------

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        if r.status_code == 200:
            return
        body = r.text[:600]
        if r.status_code == 429:
            try:
                errors = r.json().get("errors") or []
                code = errors[0].get("code") if errors else None
            except Exception:
                code = None
            if code == QUOTA_EXHAUSTED_CODE:
                raise QuotaExhausted(
                    "Cloudflare daily free neuron allowance exhausted"
                )
            ra = r.headers.get("retry-after")
            try:
                retry_after = float(ra) if ra else None
            except ValueError:
                retry_after = None
            raise RateLimited(f"rate limited (429): {body}", retry_after)
        if r.status_code in (401, 403):
            raise AuthError(f"HTTP {r.status_code} — credentials rejected: {body}")
        if r.status_code == 402:
            # Gateway models draw on PREPAID CREDIT, not the daily free neuron
            # allowance -- a distinction the native models never surface. This
            # is fatal for the whole batch and retrying cannot fix it, so it
            # must not burn a job's retry budget.
            raise QuotaExhausted(
                "HTTP 402 — insufficient prepaid credit for this Cloudflare AI "
                "Gateway model. Gateway models are billed from prepaid credit "
                "rather than the daily free neuron allowance; add credit in the "
                "Cloudflare dashboard, or pick a free or native model."
            )
        if r.status_code == 400:
            # Gateway request-validation failures use code 7003 where the
            # native models use 5006. Both are permanent -- the request shape
            # is wrong and will be wrong again on retry -- but naming the
            # gateway case makes a misconfigured model obvious in the log
            # rather than looking like a generic bad request.
            try:
                errors = r.json().get("errors") or []
                code = errors[0].get("code") if errors else None
            except Exception:
                code = None
            if code == GATEWAY_BAD_REQUEST_CODE:
                raise PermanentError(
                    f"HTTP 400 (gateway code 7003) — the request shape is "
                    f"invalid for this model. The response names the legal "
                    f"fields: {body}"
                )
            raise PermanentError(f"HTTP 400 — bad request: {body}")
        if 500 <= r.status_code < 600 or r.status_code in (408, 409, 425):
            raise TransientError(f"HTTP {r.status_code}: {body}")
        raise PermanentError(f"HTTP {r.status_code}: {body}")

    @staticmethod
    def _unreadable(model: ModelSpec, msg: str) -> Exception:
        """Classify a 200 whose body could not be read as an image.

        On a FREE model this is transient: the request cost nothing, so trying
        again is the right move and might well succeed.

        On a PAID model the image was already generated and BILLED before the
        body reached us, and a retry does not re-fetch it -- it generates and
        bills a second one. Measured 2026-09-06: a parse bug against a valid
        p-image response bought four copies of one picture this way. If the
        program cannot read the response, that is a fault to surface, not one
        to pay for repeatedly.

        This is deliberately NOT applied to the presigned-URL fetch, where the
        image is already paid for and a retry re-downloads it rather than
        regenerating it.
        """
        if model.is_free:
            return TransientError(msg)
        return PermanentError(
            msg + " — not retried: this is a paid model and the image was "
            "already billed, so a retry would be charged again rather than "
            "recovering the one you paid for"
        )

    @staticmethod
    def _extract_image(r: httpx.Response, model: ModelSpec) -> bytes | _PresignedURL:
        """Pull image bytes out of the response.

        The registry says which encoding to expect, but the actual response is
        checked rather than assumed — a mismatch is worth surviving, not
        crashing on.
        """
        ctype = r.headers.get("content-type", "")
        looks_json = "application/json" in ctype

        if (
            model.response_encoding in ("json_base64", "json_data_uri")
            or looks_json
        ):
            try:
                payload = r.json()
            except Exception as e:
                if model.response_encoding == "raw":
                    return r.content
                raise CloudflareProvider._unreadable(
                    model, f"200 but unparseable JSON: {e}"
                ) from e
            if isinstance(payload, dict) and not payload.get("success", True):
                errors = payload.get("errors") or []
                raise PermanentError(
                    "provider reported failure: " + json.dumps(errors)[:500]
                )
            # MEASURED 2026-09-06: the gateway nests one level DEEPER than the
            # documentation implied. The live shape is
            #     {"result": {"state": "Completed", "result": {"image": ...}}}
            # so both `state` and `image` sit inside `result`, not beside it.
            # Reading payload["result"]["image"] therefore yielded None on a
            # perfectly good response, which the code raised as transient and
            # RETRIED -- four billed generations for one wanted image. Walk the
            # `result` chain instead of assuming a fixed depth, so that either
            # nesting parses and a future change of depth cannot cost money.
            node = payload if isinstance(payload, dict) else {}
            b64 = None
            for _ in range(4):
                # Only "Completed" is documented; anything else is treated as
                # not yet done rather than assumed successful. Checked at every
                # level, since the field moved once already.
                state = node.get("state")
                if state is not None and state != "Completed":
                    raise TransientError(
                        f"provider state is {state!r}, not Completed"
                    )
                candidate = node.get("image")
                if isinstance(candidate, str) and candidate:
                    b64 = candidate
                    break
                inner = node.get("result")
                if not isinstance(inner, dict):
                    break
                node = inner
            if not b64:
                raise CloudflareProvider._unreadable(
                    model,
                    "200 with no result.image field: " + json.dumps(payload)[:400],
                )
            # krea returns a PRESIGNED URL here rather than image data, so
            # there is nothing to decode -- the bytes need a second HTTP GET,
            # which the caller performs (a staticmethod has no client).
            if model.response_encoding == "json_url" or b64.startswith(
                ("http://", "https://")
            ):
                return _PresignedURL(b64)

            # THE TRAP: klein returns BARE base64 at result.image, while the
            # Pruna/gateway models return a full `data:image/jpeg;base64,...`
            # URI at the SAME field path. Decoding one as the other yields
            # garbage rather than an error. Strip the prefix whenever it is
            # present rather than trusting the declared encoding, since the
            # two shapes are indistinguishable by field name alone.
            if b64.startswith("data:"):
                _, _, b64 = b64.partition(",")
                if not b64:
                    raise CloudflareProvider._unreadable(
                        model, "result.image is a data: URI with no payload"
                    )
            try:
                return base64.b64decode(b64)
            except Exception as e:
                raise CloudflareProvider._unreadable(
                    model, f"result.image is not valid base64: {e}"
                ) from e

        return r.content

    @staticmethod
    def _finish(
        data: bytes,
        r: httpx.Response,
        model: ModelSpec,
        prompt: str,
        width: int,
        height: int,
        seed: int | None,
        elapsed: float,
    ) -> GenerationResult:
        if not data:
            raise TransientError("empty response body")

        # Corrupt/truncated bytes are a TRANSIENT failure. A decodable but
        # flat-colour frame is a content block, which is PERMANENT. Getting
        # these two the wrong way round would either retry forever on a
        # blocked prompt or discard a recoverable one.
        if not imagecheck.decodes(data):
            raise TransientError(
                f"response is not a decodable image ({len(data)} bytes, "
                f"content-type {r.headers.get('content-type', '?')})"
            )
        if imagecheck.is_blank(data):
            raise ContentBlocked(
                "provider returned a flat-colour (black) frame — its content "
                "filter refused this prompt. Rewrite the prompt; retrying will "
                "not help."
            )

        return GenerationResult(
            image_bytes=data,
            ext=imagecheck.sniff_ext(data),
            width=width,
            height=height,
            model=model.key,
            model_id=model.id,
            provider="cloudflare",
            # A seed that was never SENT must not be recorded as though it
            # were. Recraft accepts no seed field at all, so writing the
            # engine's generated number into the sidecar would promise a
            # reproducibility that does not exist -- someone re-running with
            # that seed would get a different image and have no way to know
            # why. None is the honest value.
            seed=seed if model.supports_seed else None,
            elapsed=round(elapsed, 2),
            cost_estimate=model.cost_per_image(width, height),
            tiles=tile_count(width, height),
            response_encoding=model.response_encoding,
            declared_content_type=r.headers.get("content-type", ""),
            actual_dimensions=imagecheck.dimensions(data),
        )
