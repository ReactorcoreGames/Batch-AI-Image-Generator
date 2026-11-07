"""Probe how the gateway models accept a REFERENCE IMAGE, without paying for one.

BACKGROUND. Adding a single global "style reference" image is under
consideration (2026-09-19). Feasibility turns entirely on ENCODING -- not on
whether a model has a reference field, but on whether it will take the bytes of
a LOCAL file. Three shapes exist across the lineup:

    flux-2-klein-4b/9b   input_image_0..3   multipart BINARY  -- local file, direct
    flux-2-pro-preview   input_images[]     https URL *or* data:...;base64
    nano-banana-2/Lite   image_input[]      bare {"type":"string"} -- UNDOCUMENTED
    krea x2              image_style_references[].url  format:uri -- URL ONLY
    p-image              (no field at all)

nano-banana is the open question this script exists to close. Its schema says
only "array of string", with no format, no description and no example, and it
is the most expensive model in the lineup ($67-$151 per 1000) -- so guessing is
the one thing not to do.

WHY THIS IS FREE. The gateway validates a request body BEFORE forwarding it to
the provider for generation. A malformed body returns 400 (code 7003) naming
the problem; a well-formed one gets far enough to be billed. So this script
sends bodies that are well-SHAPED but carry an image the provider cannot
possibly generate from -- an unreachable URL and a 1x1 PNG -- and reads the
ERROR TEXT. The error distinguishes "I refuse this encoding" from "I accepted
this encoding and then failed to fetch/decode it", which is the actual
question, and neither outcome produces an image.

    A 400 naming `image_input` as a URI problem  -> the field takes URLs only.
    A 400/5xx complaining the URL could not be FETCHED -> URLs accepted.
    A 200, or an error about the IMAGE CONTENT   -> base64 was accepted.

THE RISK, STATED PLAINLY. This is not provably zero-cost the way the
unified-billing probe is. If the gateway forwards a well-formed body with a
VALID tiny image, nano-banana may generate and bill one image (~$0.07-$0.15).
The 1x1 PNG is chosen to be structurally valid but useless, and --safe (the
default) sends ONLY the two encodings that cannot generate anything: an
unreachable URL and a deliberately corrupt base64 payload. Pass --real-image
to add the valid-1x1 test, which is the only one that could conceivably bill.

USAGE
    python tools/probe_reference_image.py              # free: refusal-shape only
    python tools/probe_reference_image.py --real-image # adds the one billable test
    python tools/probe_reference_image.py --model nano-banana-2-lite

Watch the AI Gateway dashboard log while this runs: it shows what the gateway
forwarded and what came back, which is the ground truth if the error text is
ambiguous.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.credentials import effective_value  # noqa: E402

BASE = "https://api.cloudflare.com/client/v4"

# The models with an undocumented or URL-shaped reference field. klein is NOT
# here: its multipart binary path is documented with a curl example, so there
# is nothing to discover.
TARGETS = {
    "nano-banana-2-lite": ("google/nano-banana-2-lite", "image_input", "array"),
    "nano-banana-2": ("google/nano-banana-2", "image_input", "array"),
    "flux2pro": ("black-forest-labs/flux-2-pro-preview", "input_images", "array"),
    "krea-turbo": ("krea/krea-2-medium-turbo", "image_style_references", "krea"),
}

# Minimum viable request per model, WITHOUT the reference field. Each is the
# shape core/providers/cloudflare.py already sends, so a failure here means the
# probe is wrong rather than the finding being interesting.
BASES = {
    "nano-banana-2-lite": {"aspect_ratio": "16:9", "resolution": "1K", "output_format": "jpg"},
    "nano-banana-2": {"aspect_ratio": "16:9", "resolution": "1K", "output_format": "jpg"},
    "flux2pro": {"width": 1536, "height": 864, "output_format": "jpeg"},
    "krea-turbo": {"aspect_ratio": "16:9", "resolution": "1K", "creativity": "medium"},
}

PROMPT = "a red cube on a white table"

# A structurally valid 1x1 transparent PNG. Small enough to be unmistakable in
# a gateway log, valid enough that a decoder will accept it.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# A host that resolves to nothing. If the provider ACCEPTS urls, this produces
# a fetch failure -- which is the positive signal. If it rejects the field
# shape first, we never get that far.
DEAD_URL = "https://invalid.invalid/reference.png"


def _err(r: httpx.Response) -> str:
    """The most informative text the response carries, trimmed."""
    try:
        payload = r.json()
    except Exception:
        return r.text[:300]
    errs = payload.get("errors") or []
    if errs:
        return json.dumps(errs)[:400]
    return json.dumps(payload)[:400]


def _code(r: httpx.Response) -> int | None:
    try:
        errs = r.json().get("errors") or []
        return errs[0].get("code") if errs else None
    except Exception:
        return None


def _verdict(r: httpx.Response) -> str:
    """Classify what the response tells us about the ENCODING."""
    text = _err(r).lower()
    if r.status_code == 200:
        return "ACCEPTED (200) -- encoding is valid. CHECK THE DASHBOARD FOR A CHARGE."
    if any(w in text for w in ("fetch", "download", "retrieve", "unreachable",
                               "resolve", "timeout", "could not load")):
        return "ACCEPTED the shape, FAILED to fetch -> this field takes URLs."
    if any(w in text for w in ("uri", "url", "format", "must be a valid")):
        return "REJECTED as not-a-URI -> this field is URL-ONLY."
    if any(w in text for w in ("decode", "base64", "invalid image", "corrupt",
                               "unsupported image")):
        return "ACCEPTED base64 shape, FAILED to decode -> base64 IS supported."
    return "UNCLEAR -- read the raw error and the gateway dashboard log."


def _post(c: httpx.Client, root: str, auth: dict, model_id: str,
          inp: dict, label: str) -> None:
    print(f"\n-- {label}")
    try:
        r = c.post(f"{root}/ai/run/", headers=auth,
                   json={"model": model_id, "input": inp})
    except Exception as e:
        print(f"   request failed: {type(e).__name__}: {e}")
        return
    code = _code(r)
    print(f"   HTTP {r.status_code}" + (f" / {code}" if code else ""))
    print(f"   {_verdict(r)}")
    print(f"   raw: {_err(r)[:300]}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="nano-banana-2-lite",
                    choices=sorted(TARGETS), help="which model to probe")
    ap.add_argument("--real-image", action="store_true",
                    help="also send a VALID 1x1 png. This is the only test that "
                         "could conceivably generate and bill an image.")
    args = ap.parse_args()

    acct, _ = effective_value("CLOUDFLARE_ACCOUNT_ID")
    tok, _ = effective_value("CLOUDFLARE_API_TOKEN")
    if not acct or not tok:
        print("FAIL: no Cloudflare credentials. Set them in the GUI or as env vars.")
        return 2

    model_id, field, shape = TARGETS[args.model]
    root = f"{BASE}/accounts/{acct}"
    auth = {"Authorization": f"Bearer {tok}"}
    base_inp = {"prompt": PROMPT, **BASES[args.model]}

    print(f"== probing {args.model} ({model_id}) ==")
    print(f"   reference field: {field!r}")
    print(f"   Watch: dash.cloudflare.com -> AI -> AI Gateway -> Logs")

    def wrap(value):
        """Put one image value into the field, in that model's shape."""
        if shape == "krea":
            return [{"url": value, "strength": 0.5}]
        return [value]

    with httpx.Client(timeout=180.0) as c:
        # 0. CONTROL. The body WITHOUT the reference field must be accepted --
        #    otherwise every result below is measuring a different mistake.
        #    Deliberately NOT sent: it would generate and bill. Instead the
        #    control is an obviously-bad ENUM, which proves the gateway is
        #    validating this model's body at all.
        print("\n== 0. control: does the gateway validate this model's body? ==")
        bad = {**base_inp, "aspect_ratio": "definitely-not-a-ratio"}
        _post(c, root, auth, model_id, bad,
              "known-bad aspect_ratio (expect 400 naming the enum)")

        # 1. Is the field even known? An unknown property on a schema with
        #    additionalProperties:false is rejected by NAME, which tells us the
        #    field exists on the gateway path rather than only in the docs.
        print("\n== 1. is the field recognised at all? ==")
        _post(c, root, auth, model_id,
              {**base_inp, field + "_typo_xyz": wrap(DEAD_URL)},
              f"bogus field {field}_typo_xyz (expect rejection by NAME)")

        # 2. THE URL TEST. Unreachable host. If URLs are accepted, the failure
        #    is a FETCH failure, which is the signal.
        print("\n== 2. URL encoding ==")
        _post(c, root, auth, model_id, {**base_inp, field: wrap(DEAD_URL)},
              "unreachable https URL")

        # 3. THE BASE64 TEST. Deliberately CORRUPT payload: right shape, wrong
        #    bytes. Cannot generate anything, so it cannot bill -- but a
        #    decoder error proves the data: form was accepted.
        print("\n== 3. base64 data URI encoding (corrupt payload, cannot bill) ==")
        corrupt = "data:image/png;base64,####not-valid-base64####"
        _post(c, root, auth, model_id, {**base_inp, field: wrap(corrupt)},
              "data: URI with a corrupt payload")

        # 4. BARE base64, no data: prefix. A distinct encoding: klein returns
        #    bare base64 at result.image, so the family demonstrably speaks it.
        print("\n== 4. bare base64, no data: prefix (corrupt payload) ==")
        _post(c, root, auth, model_id, {**base_inp, field: wrap("####not-valid-base64####")},
              "bare base64, corrupt")

        # 5. The one that could cost money. Opt-in only.
        if args.real_image:
            print("\n== 5. VALID 1x1 png (THIS ONE CAN BILL) ==")
            uri = "data:image/png;base64," + base64.b64encode(PNG_1X1).decode()
            _post(c, root, auth, model_id, {**base_inp, field: wrap(uri)},
                  "data: URI, valid 1x1 png")
        else:
            print("\n== 5. skipped (pass --real-image to run the billable test) ==")

    print("\nDone. The gateway dashboard log is the tiebreaker if any verdict "
          "reads UNCLEAR -- it shows the forwarded body and the provider's reply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
