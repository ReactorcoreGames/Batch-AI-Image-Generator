# Unified billing (AI Gateway credit for native models) — SPECIFIED, NOT BUILT

**Status: blocked on Cloudflare, deliberately.** Everything here was designed and costed on 2026-09-09 and then not implemented, because the model that motivated it — `flux-2-klein-4b` — is the one model the feature cannot reach. Pick this up when the upstream bug is fixed. The measurements behind every claim are in [findings.md](findings.md) under *"Unified billing reaches the JSON models and not klein"*; read that first.

## The problem this solves

Cloudflare gives 10,000 free neurons a day. When they run out, native models return `429` / `4006` and the batch stops — even if the account holds prepaid AI Gateway credit, because credit and neurons are different pots and the native path only ever draws on neurons.

Adding `cf-aig-gateway-id: default` to a native request routes it through the gateway, where it draws credit instead. That is the whole feature.

## Why it is not built

Two measured facts, either of which alone would justify waiting:

1. **klein cannot be gateway-routed.** It requires `multipart/form-data`; the gateway path rejects multipart with `7000 Invalid request body` and rejects JSON with `5006 required properties at '/' are 'multipart'`. No body satisfies both. So the feature covers `lightning`, `sdxl` and `dreamshaper` only — and *not* the two klein models, which are the paid ones a user actually wants unblocked.
2. **It makes the three free models cost money.** Measured: under unified billing, `sdxl-lightning` bills credit. So the feature's entire reachable scope is "make your free models paid", which is close to an anti-feature on its own.

Together: the feature currently unblocks nothing anyone wants unblocked. Ship it when klein works.

## Unblock condition

**Run `python tools/probe_unified_billing.py`.** It checks the account setting, runs both klein encodings and a control, and prints STILL BROKEN or FIXED. Exit code 1 = still broken, 0 = fixed, 2 = inconclusive (bad credentials, or unified billing switched off). Re-tested 2026-09-12: still broken, unchanged.

The script is the maintained version of the check. The raw curl, if you want it by hand:

```bash
curl -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-2-klein-4b" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "cf-aig-gateway-id: default" \
  -F "prompt=a red cube on a white table" \
  -F "width=1536" -F "height=864" -F "seed=4242"
```

Tracking: Cloudflare community forum + Discord + a `cloudflare/cloudflare-docs` issue, all filed 2026-09-09. Drafts at [cloudflare-klein-gateway-bug-report.md](cloudflare-klein-gateway-bug-report.md) and [cloudflare-docs-issue.md](cloudflare-docs-issue.md).

## The design, as settled

A **program-level setting**, not a per-model one — it reflects how the *account* is configured, and applies to every native request.

- **Config key:** `use_unified_billing`, default `false`.
- **GUI:** a checkbox on the Provider tab, near the credentials block rather than the model dropdown, since it is an account fact.
- **Label:** name the consequence, not the mechanism — the house rule from the UI sanity pass. Something like *"Bill Cloudflare models to AI Gateway credit instead of the daily free neurons"*.
- **Behaviour when on:** send `cf-aig-gateway-id: default` on native requests. Gateway models are unaffected — they already route by default and must not gain the header.

### The five things that must move together

1. **The header, in `core/providers/cloudflare.py`.** `_headers()` is shared by every call including `check()`; add it on the *generation* path only, and only for `call_style == "native"`. Do not put it in `_headers()`.

2. **The retry cap — the sharp edge.** `_attempt_budget()` at [../core/engine.py:514](../core/engine.py#L514) branches on `M.get_model(...).is_free`. Under unified billing a "free" model is billed, so that branch hands a paying model the free lane's 3 attempts and can buy three copies of one image — the same class of failure that bought four copies of a p-image generation on 2026-09-06. **Key the cap on the effective billing state, not on `is_free`.** The 429 exemption stays exactly as it is: a rate limit is refused before generating, costs nothing, and must still back off normally.

3. **`is_free` stops being true.** It is a static `ModelSpec` property and cannot see the setting. Everything derived from it — the cost estimate, `Estimate.free_images_per_day`, the "free daily, then …" model labels, `cli estimate` and `cli dry-run` — reads wrong while the setting is on. Introduce an *effective* billing state that takes the setting into account and route these through it; do not mutate the specs.

4. **The dashboard link flips** to `CREDITS_DASHBOARD_URL`. The comment at [../core/providers/cloudflare.py:76](../core/providers/cloudflare.py#L76) already makes this argument for gateway models — sending someone to the neuron page when their batch does not draw on neurons shows them a quota that is not theirs. Same reasoning, newly true of the native five.

5. **klein must say why it is excluded.** A user turning this on is almost certainly trying to unblock klein. Silently not applying the header there reads as the setting being broken. State it: klein cannot use gateway credit, and stays on the daily neuron allowance. **Grey out, never hide** — house rule.

### Two things NOT to do

- **Do not add a `call_style` for this.** Measured: klein still answers `5006 ... are 'multipart'` on the header path, so the existing multipart encoding is correct and unchanged. This is a header, not a new call shape.
- **Do not touch `max_concurrency`.** Unified billing raises frontier-model limits from 20 to 50 req/min, and that headroom is deliberately declined — politeness is a requirement, not a setting. Confirmed by the user 2026-09-09.

### Worth doing, cheap

Read `workers_ai_billing_mode` from `GET /accounts/{id}/ai-gateway/gateways/default` and use it to tell "you have not switched your account to unified billing" apart from "this is genuinely failing". It ships as `"postpaid"`; the feature does nothing until it reads `"unified"`, and no error on the request path distinguishes those two cases. One GET, no generation, no charge.

## Test notes

The whole thing is testable offline except the final header behaviour. Worth pinning:

- the header is absent when the setting is off, present on native models when on, and **never present on the two klein models**;
- gateway models are unchanged in both states;
- the attempt budget is 1 for a native model while the setting is on, and 3 while it is off;
- a 429 still gets the full budget in both states.
