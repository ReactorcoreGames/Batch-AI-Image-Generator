"""Probe whether klein can be routed through AI Gateway (unified billing) yet.

BACKGROUND. Cloudflare's AI Gateway lets Workers AI requests draw on prepaid
CREDIT instead of the daily free neuron allowance, by adding the header
`cf-aig-gateway-id`. Measured 2026-09-09 and re-measured 2026-09-12: this works
for the JSON-bodied models and is IMPOSSIBLE for the two FLUX.2 klein models,
whose two requirements contradict each other --

    klein requires multipart/form-data      (JSON  + header -> 400 / 5006)
    the gateway path accepts only JSON      (multi + header -> 500 / 7000)

No body satisfies both, so klein -- the best per-dollar model in the lineup --
is the one model unified billing cannot reach. Reported upstream 2026-09-09
(community forum, Discord, cloudflare/cloudflare-docs). See docs/findings.md
and docs/unified-billing-todo.md.

WHAT THIS SCRIPT IS FOR. Re-running that measurement cheaply, so a future
session can tell in one command whether Cloudflare has fixed it and the
unified-billing feature is worth building.

COST. Effectively nothing, but not literally zero. The two klein attempts are
rejected BEFORE generation (that is what 5006/7000 mean) and the account-setting
check is a plain GET, so those are free. The step-3 CONTROL does generate one
sdxl-lightning image, which under unified billing bills to credit -- a small
fraction of a cent, and it is the only thing that proves a failure is the klein
bug rather than a broken account. --generate adds ONE further klein image, and
only if the bug is fixed.

USAGE
    python tools/probe_unified_billing.py              # free, read-only
    python tools/probe_unified_billing.py --generate   # one billed image IF fixed
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.credentials import effective_value  # noqa: E402

BASE = "https://api.cloudflare.com/client/v4"
KLEIN = "@cf/black-forest-labs/flux-2-klein-4b"
LIGHTNING = "@cf/bytedance/stable-diffusion-xl-lightning"
GATEWAY_ID = "default"

# Standard 16:9 for klein, per core/models.py. Multiples of 16, under the 1920 cap.
W, H = 1536, 864
SEED = 4242
PROMPT = "a red cube on a white table"


def _code(r: httpx.Response) -> int | None:
    """Cloudflare's internal error code, which is what actually distinguishes cases."""
    try:
        errs = r.json().get("errors") or []
        return errs[0].get("code") if errs else None
    except Exception:
        return None


def _describe(r: httpx.Response) -> str:
    code = _code(r)
    known = {
        4006: "daily neuron allowance exhausted",
        5006: "model rejected the body (wants multipart)",
        6003: "endpoint wants JSON",
        7000: "gateway rejected the body (the bug)",
        7003: "gateway validation",
    }
    note = known.get(code, "")
    return f"HTTP {r.status_code}" + (f" / {code}" if code else "") + (f" -- {note}" if note else "")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--generate",
        action="store_true",
        help="if the bug is fixed, spend ONE billed klein image to prove it end to end",
    )
    args = ap.parse_args()

    acct, _ = effective_value("CLOUDFLARE_ACCOUNT_ID")
    tok, _ = effective_value("CLOUDFLARE_API_TOKEN")
    if not acct or not tok:
        print("FAIL: no Cloudflare credentials. Set them in the GUI or as env vars.")
        return 2

    root = f"{BASE}/accounts/{acct}"
    auth = {"Authorization": f"Bearer {tok}"}
    gw = {**auth, "cf-aig-gateway-id": GATEWAY_ID}
    form = {"prompt": PROMPT, "width": str(W), "height": str(H), "seed": str(SEED)}
    body = {"prompt": PROMPT, "width": W, "height": H, "seed": SEED}

    with httpx.Client(timeout=240.0) as c:
        # 0. The PREREQUISITE. Unified billing is an ACCOUNT setting; no header
        #    substitutes for it. Ships as "postpaid"; must read "unified" or
        #    every result below is meaningless.
        print("== 0. account setting ==")
        try:
            r = c.get(f"{root}/ai-gateway/gateways/{GATEWAY_ID}", headers=auth)
            mode = (r.json().get("result") or {}).get("workers_ai_billing_mode")
        except Exception as e:
            print(f"  could not read gateway {GATEWAY_ID!r}: {e}")
            return 2
        print(f"  workers_ai_billing_mode = {mode!r}")
        if mode != "unified":
            print("  -> NOT unified. Dashboard -> AI Gateway -> Workers AI Billing ->")
            print("     Unified billing. Until then this probe cannot test anything.")
            return 2

        # 1. THE BUG. multipart + gateway header. 7000 = still broken.
        print("\n== 1. klein: multipart + gateway header (THE TEST) ==")
        r1 = c.post(f"{root}/ai/run/{KLEIN}", headers=gw, data=form)
        print(f"  {_describe(r1)}")
        multipart_ok = r1.status_code == 200

        # 2. The other half of the contradiction, and proof the model still
        #    wants multipart at all rather than having quietly switched to JSON.
        print("\n== 2. klein: JSON + gateway header (the contradiction) ==")
        r2 = c.post(f"{root}/ai/run/{KLEIN}", headers=gw, json=body)
        print(f"  {_describe(r2)}")
        json_ok = r2.status_code == 200

        # 3. CONTROL. A JSON model through the same header. Isolates the failure
        #    to the encoding: if this fails too, the problem is the account,
        #    the token or the gateway -- not the bug being probed.
        print("\n== 3. control: sdxl-lightning JSON + gateway header ==")
        r3 = c.post(
            f"{root}/ai/run/{LIGHTNING}",
            headers=gw,
            json={"prompt": PROMPT, "width": 1024, "height": 576, "num_steps": 8, "seed": SEED},
        )
        ctrl = r3.status_code == 200
        print(f"  {_describe(r3)}" + ("  (NOTE: this one BILLED credit)" if ctrl else ""))

        print("\n" + "=" * 60)
        if multipart_ok or json_ok:
            which = "multipart" if multipart_ok else "JSON"
            print(f"*** FIXED -- klein answered 200 on the gateway path ({which}). ***")
            print("Build the feature: docs/unified-billing-todo.md.")
            print("Re-read it first; the retry cap at core/engine.py:_attempt_budget")
            print("branches on is_free and WILL buy duplicate images if left alone.")
            if args.generate:
                print("\n-- spending one billed image to confirm end to end --")
                t0 = time.time()
                rg = (
                    c.post(f"{root}/ai/run/{KLEIN}", headers=gw, data=form)
                    if multipart_ok
                    else c.post(f"{root}/ai/run/{KLEIN}", headers=gw, json=body)
                )
                dt = time.time() - t0
                print(f"  {_describe(rg)}  {dt:.1f}s")
                try:
                    img = (rg.json().get("result") or {}).get("image")
                    if isinstance(img, str):
                        raw = base64.b64decode(img)
                        ext = "jpg" if raw[:2] == b"\xff\xd8" else "png"
                        out = Path(__file__).parent / f"probe_klein_gateway.{ext}"
                        out.write_bytes(raw)
                        print(f"  saved {out} ({len(raw)} bytes)")
                except Exception as e:
                    print(f"  could not decode: {e}")
            else:
                print("\nPass --generate to spend one billed image confirming it end to end.")
            return 0

        if not ctrl:
            print("INCONCLUSIVE -- the control failed too, so this is not the klein bug.")
            print("Check credit balance (402 = empty), the token, and the gateway id.")
            return 2

        print("STILL BROKEN -- unchanged. klein cannot use gateway credit.")
        print("The control passed, so the account, token and gateway are all fine;")
        print("the failure is the multipart encoding, exactly as reported.")
        print("Both klein attempts were rejected pre-generation and cost nothing;")
        print("the control in step 3 DID generate, so it billed one image to credit.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
