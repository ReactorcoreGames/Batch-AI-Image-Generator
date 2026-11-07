# Gateway models — implementation checklist

Tracking doc for adding the 8 Cloudflare **AI Gateway** models to the program, one family at a time.

**STATUS 2026-09-05: ALL EIGHT SHIP. The model lineup is complete.** What remains is cross-cutting — the `guide.md` / `readme.md` / `promo.md` documentation pass (deferred to its own session by decision, and to include a sanity check over the whole lineup), then the exe build. The per-family content-refusal check and the flagged Advance Wars prompt both remain blocked on the neuron allowance.

Source of truth for the model facts: `List of Cloudflares Text-to-Image to consider for our program.md` in the repo root. That document's field lists were verified against the live API at zero cost (a malformed request returns 400 naming every legal field; a well-formed one returns 402 Insufficient balance, which proves the model id and request shape without generating anything). **Do not re-derive those field lists — read them from that doc.**

Status: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Ground rules for this work

- **No live testing.** No prepaid credits are available to spend. Every implementation is written against documentation and the already-verified field lists. Anything that genuinely cannot be settled without a paid call goes in the "Unverified — needs a paid call to confirm" table at the bottom of this file, and is coded defensively rather than guessed at silently.
- **One family per session.** (Exception taken 2026-09-05: the Recraft pair was done in one session, because the second model is the same field list, the same size enum and the same response shape as the first — the risk the rule guards against was not present. The pair still got its own review, and it caught a real billed-size bug.) The whole point of the phased order is that each model's quirks — its size vocabulary, its price shape, its filter controls, its labels and tooltips — get the same care the existing five got. Batching them would produce eight half-configured models.
- **The existing 5 native models must not regress.** Run `python tests/test_engine.py` (49/49 as of the Recraft pair, offline) after every phase.
- **`core/models.py` stays the single source of truth.** No model fact gets hardcoded in a provider or in the GUI.

---

## Phase 0 — Shared groundwork (do this once, alongside p-image)

These pieces of machinery do not exist yet and *every* gateway model needs all of them. They are listed separately because they are the actual risk in this project; the per-model work afterwards is mostly careful data entry.

- [x] **Gateway call shape.** DONE — `ModelSpec.call_style` (`native`/`gateway`); `CloudflareProvider.generate` branches on it and `_gateway_payload()` builds the body.
  ORIGINAL: Gateway models POST to `/accounts/{id}/ai/run` with `{"model": ..., "input": {...}}` in the **body** — the model is not in the URL path. `core/providers/cloudflare.py` currently hardcodes `url = f"{BASE_URL}/accounts/{self.account_id}/ai/run/{model.id}"`. Needs a branch: either a `ModelSpec.call_style` of `"native"` vs `"gateway"`, or a separate `CloudflareGatewayProvider`. Decide when writing it.
- [x] **Gateway error taxonomy.** DONE — 7003 is a *named* `PermanentError`; **402 maps to `QuotaExhausted`** (fatal, never retried) because gateway models draw on prepaid credit rather than the neuron allowance.
  ORIGINAL: Gateway errors arrive as HTTP 400 with `code 7003`, distinct from the native models' `5006`. `_raise_for_status` needs to recognise it and classify correctly. Also confirm whether `402 Insufficient balance` is reachable in normal use and map it to a clear permanent error — "you have no prepaid credit", not "bad request".
- [x] **Flat per-image pricing.** DONE — `_flat_per_image()`, plus `ModelSpec.bills_per_tile` / `Estimate.bills_per_tile`. Tile counts are suppressed in the GUI size readout, `cli estimate` and `cli dry-run`; `free_images_per_day` returns None. **Bug caught doing this:** the old CLI `else` branch printed "free model — no neuron cost" for *any* None, which was flatly wrong for a paid gateway model. Now three distinct branches.
  ORIGINAL: Every existing `price_fn` is tile-based or per-megapixel. Gateway models bill **per image**, flat. Add `_flat_per_image(usd)`. Then audit everything downstream that assumes tiles are meaningful: `Estimate.tiles`, `Estimate.free_images_per_day`, the GUI cost readout, and the CLI estimate output. A tile count shown next to a flat-priced model is misleading and should be suppressed, not shown as a meaningless number.
- [x] **Size-expression abstraction.** DONE — `ModelSpec.size_style` plus `SIZE_TABLE_OVERRIDES`, so a model can own its whole size table rather than only substituting at High.
  ORIGINAL: `SIZES` / `size_for()` / `resolve_size()` return exact pixels, and the GUI's ratio+tier dropdowns assume that. The gateway models each speak a *different* size vocabulary:

  | Family | Speaks | Tiers available |
  |---|---|---|
  | native (existing 5) | exact `width`/`height` | Draft / Standard / High |
  | p-image | `aspect_ratio` enum, **or** `width`/`height` when `aspect_ratio="custom"` (256–1440, x16) | custom path only |
  | krea | `aspect_ratio` + `resolution`, **`1K` only** | one tier |
  | nano-banana | `aspect_ratio` + `resolution` `1K`/`2K`/`4K` | its own ladder |
  | recraft | opaque `size` enum, **one fixed size per ratio** | none |
  | flux-2-pro | true `width`/`height`, min 64, no x16 rule | free-form |

  Design this on p-image, which is the only model that can express size **both** ways and so exercises both paths.
- [x] **Cost tier labels `$`/`$$`/`$$$`** in the model dropdown. Scheme is DECIDED in the source doc. Derive from `cost_per_1000()` at a **fixed reference size** (Standard 16:9), not the user's current selection, so the label does not flicker as the tier changes. It is a browsing aid; the existing cost estimator remains the accurate number.
- [x] **Amend the `$5/1000` ceiling in CLAUDE.md.** DONE — recorded at `BUDGET_CEILING_PER_1000` in `core/models.py` and in CLAUDE.md.
  ORIGINAL: This is an explicit, recorded amendment, not an oversight: the ceiling now governs the `$` tier and the *default* model choice, while `$$`/`$$$` are opt-in and clearly marked. Write it down so a future session does not "fix" it back.

### Also worth doing while in this code

- [ ] **Error 4006 should halt the batch, not retry.** Already recognised as `QuotaExhausted` in `core/providers/cloudflare.py` — verify it actually halts the batch cleanly rather than burning each job's retry budget against a wall that will not move for hours. The batch is resumable by design, so stopping cleanly and resuming tomorrow is the correct behaviour.

---

## Implementation order

Cheapest-first, so mistakes cost least when the models are eventually run for real.

### 1. `pruna/p-image` — $5/1000 · `$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

The architectural pathfinder. Cheapest of the eight, sits exactly *on* the existing CLAUDE.md ceiling (so it needs no amendment of its own), and is the only model that expresses size both as an enum and as pixels — which makes it the right place to design the size abstraction.

- [x] Fields — implemented. `steps_settable`, `supports_guidance` and `supports_negative_prompt` are all False, and `_gateway_payload` asserts none of them are ever sent.
- [x] `aspect_ratio` — the program always sends `custom` with explicit width/height, since the bare enum would let the provider pick its own resolution and the program's sizes are chosen deliberately.
- [x] Sizes — **`SIZES_PIMAGE` in `core/models.py`, COMPUTED not eyeballed.** The x16 rule binds harder than the 1440 cap: 16:9 tops out at **1280x720**, *not* 1440x810, because 810 is not a multiple of 16. A first draft of the table had exactly that wrong and the check caught it. Standard and High are therefore the same size for 4 of 5 ratios, and the GUI says so explicitly rather than looking broken.
- [x] **`disable_safety_checker`** — DONE 2026-09-05, in the flux-2-pro session exactly as deferred. It is a BOOLEAN where flux-2-pro's field is an integer 0-5, and both are now driven by ONE program setting (`default`/`permissive`/`off`) mapped per-model by `filter_value_for()`. `permissive` and `off` mean the same thing here because the field is a boolean — stated rather than papered over with an invented third value.
- [x] **Response shape — RESOLVED 2026-09-05 from Cloudflare's own model pages, no spend.** It is **NOT a download URL**; the earlier note in the source doc was wrong and there is **no extra-GET mechanic to build**. The envelope is:

  ```json
  {"state": "Completed", "result": {"image": "data:image/jpeg;base64,..."}}
  ```

  Confirmed identical on `pruna/p-image` and `pruna/p-image-edit`, so it is family-wide rather than a doc typo.

  **The trap:** `result.image` is a **`data:` URI, not bare base64** — and klein returns *bare* base64 at the **exact same field path**. `_extract_image` currently calls `base64.b64decode()` straight on `result.image`, which would throw or silently decode garbage on this shape. Strip the `data:...;base64,` prefix when present. This needs a third response encoding (`json_data_uri`), not a reuse of `json_base64`.

  Also note the new **`state`** field, which the native models do not have. Only `"Completed"` is documented; other values are unknown, so treat a non-Completed state as a transient error rather than assuming success.
- [x] Prompt limit — set to 800/1000 as an explicitly UNVERIFIED middle ground, with the reasoning in a code comment (automatic prompt enhancement means neither the CLIP nor the klein budget is the right analogy). Nothing truncates, as everywhere else. Pick a defensible `prompt_soft_limit`/`prompt_hard_limit` and mark it unverified in a comment. Note the model does **automatic prompt enhancement**, which may make the limit behave unusually.
- [x] Labels + tooltips — done: dropdown marker, flat-pricing note, prepaid-credit explanation, and the 1280x720 caveat. Combobox widened 44→52 to fit. TODO: flat per-image price, no tier ladder, filter opt-out, prompt enhancement, 2-stage refinement.

### 2. `krea/krea-2-medium-turbo` — $15/1000 · `$$`  — **IMPLEMENTED 2026-09-05**

Best Elo-per-dollar on the list (1211). Second because it is the simplest *remaining* size story: locked to one resolution, so it tests the "this model has no tier ladder" path without Recraft's opaque enum.

- [x] Fields — implemented. Only `prompt`, `aspect_ratio`, `resolution` and `seed` are sent; the rest are optional and deliberately omitted.
- [x] `aspect_ratio` + `resolution` — both sent, always. `_ratio_key_for()` recovers the ratio NAME from the pixel size everything upstream carries, matching on the numeric ratio so it survives the size estimates later being corrected.
- [x] `resolution: 1K` — **worse than expected: krea cannot serve Standard either**, not just High. 1K at 16:9 is ~1328x752 against the program's Standard 1536x864. New `has_tier_ladder()` returns False, which **disables the tier dropdown** and explains why, rather than leaving a control that silently does nothing.
- [x] Style dials — **researched, then deliberately NOT sent.** Ranges are now documented in `KREA_STYLE_DIALS`: `creativity` is `raw|low|medium|high` (default `low`), and `intensity`/`complexity`/`movement` are integers -100..100 (default 0). **Every default is the neutral value**, so omitting them is exactly equivalent to sending them — nothing is being missed. Left out because a single global dial applied to every prompt in a batch is already what the style-suffix file does, in plain text the user can read and edit. If ever exposed, `creativity: raw` is the one worth having: it DISABLES prompt expansion.
- [x] Label + tooltip say so — "expressive/illustration", with the anime/painting/graphic-styles detail in the dropdown tooltip.

### 3. `krea/krea-2-medium` — $30/1000 · `$$`  — **IMPLEMENTED 2026-09-05**

Same fields as turbo; the stable/consistent sibling. Ships as a pair by decision — do **not** optimise the pair down to one. Nearly free to add once turbo is done.

- [x] Added; field list **confirmed identical** on both Cloudflare model pages, so the pair shares one `_KREA_COMMON` dict and differs only in id, label and price.
- [x] Tooltip is blunt about it: Turbo is the one to use; Medium costs DOUBLE for a marginal gain and earns its place only when run-to-run consistency matters more than price.

### 4. `black-forest-labs/flux-2-pro-preview` — $30/1000 · `$$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

Bought for **`safety_tolerance`**, not Elo (1207 — *below* the cheaper Krea Turbo). The only user-facing content-filter lever in the entire lineup.

- [x] Fields — implemented. `prompt`, `seed`, `width`, `height`, `safety_tolerance`, `output_format`. `input_images` is a PERMANENT skip (img2img-shaped) and is covered by the existing test.
- [x] True `width`/`height`, min **64**, **no x16 rule**, no upper bound found — and the shared `SIZES` table maps on with **NO override and a full Draft/Standard/High ladder**, the first gateway model for which that is true. CHECKED, not eyeballed: every tabled size is >= 64 in both dimensions.
- [x] **`safety_tolerance`: 0 = STRICTEST, 5 = MOST PERMISSIVE, API default 2.** Confirmed from Cloudflare's published schema (read twice, independently) — the source doc's reading was right. Pinned by `SAFETY_TOLERANCE_MIN`/`_MAX`/`_API_DEFAULT` and by a test whose only job is to stop a later edit inverting it. **DOC-DERIVED, not measured** — still in the Unverified table.
- [x] **Exposed in the GUI**, together with p-image's boolean, as ONE three-mode setting (`default`/`permissive`/`off`). Combo enables on exactly those two models and disables elsewhere with an inline note saying that a refused prompt comes back as a black frame. Also `--content-filter` on the CLI and `BatchConfig.content_filter`. The `default` mode **sends NOTHING** rather than pinning the documented `2` — the opposite call from `creativity`, deliberately: a filter's provider default IS the neutral choice, whereas krea's expansion default is not. **But the PROGRAM defaults to `permissive`, not `default`** (decided the same day, reversing a first draft): a batch tool pays for a spurious refusal with a slot in an overnight run rather than a rerun, and Cloudflare's vision check over the OUTPUT image makes false flags a live annoyance rather than a hypothetical. It does not disable moderation.
- [x] `output_format`: **defaults to `jpeg`, which is NOT neutral**, so it is sent explicitly. Wire spelling derived by `wire_output_format()` from a per-family vocabulary table — `jpeg` here, `jpg` on nano-banana — never written out by hand at a call site. Magic bytes still sniffed regardless.
- [x] **Response shape — RESOLVED from Cloudflare's schema, no spend.** `result.image` is declared `"string" format: uri`: a **PRESIGNED URL**, i.e. krea's shape, reusing `json_url` and the existing presigned fetch unchanged. That makes **three incompatible encodings at the one `result.image` path** (klein bare base64 / p-image data URI / krea+flux2pro URL), which is why the shape is sniffed from content and never inferred from the field name.
- [ ] Prerequisite, **still blocked and left open**: re-run the flagged Advance Wars prompt on klein 4B at a fixed explicit seed once the neuron allowance clears. The 3030 flag judges the *output* image, not the prompt text, so it is plausibly seed-dependent. **The model and the filter controls were built anyway** — they are worth having either way; only the *urgency* depended on this test.

### 5. `recraft/recraftv4-1-utility` — $35/1000 · `$$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

Elo 1218 — the same as its $210 Pro sibling, and higher than plain V4.1 for the same money. General-purpose.

- [x] Fields — implemented. Only `prompt` and `size` are sent. `style`, `substyle` and `controls` are all left unset; `controls.image` is reference-image shaped and is covered by the (extended) banned-fields test.
- [x] **Uses `size`, NOT `aspect_ratio`, and NOT width/height.** `SIZES_RECRAFT` + `RECRAFT_SIZE_ENUM` in `core/models.py`, and the fifth `size_style` (`"size_enum"`) — which until now was declared in the `SizeStyle` Literal and raised `PermanentError` when reached. All five program ratios are covered.
- [x] **No tier ladder** — `has_tier_ladder()` returns False, the tier dropdown disables, and the explanation is now model-specific rather than krea's "locked to 1K" (printing krea's reason for Recraft would have been a plausible-sounding lie). The 1344x768-vs-1536x864 point is in the size warning, the model tooltip and `price_note`.
- [x] **Client-side `size` validation — THE point of this model.** `recraft_size_string()` is the only legal source of a `size` value, and `validate_size()` routes enum models through it too, so the GUI readout and `cli dry-run` refuse a bad size as well — not just the provider at request time. Verified: `--width 1024 --height 768` is inside Recraft's 768–1344 bounds and is still refused, which a min/max check alone would have waved through.
- [x] **No seed.** `supports_seed=False`; the GUI disables the checkbox, the label and the entry, and `_param_note` says reproducibility is impossible rather than just greying a box. `_finish` also records `seed=None` for a seedless model — writing the engine's generated number into the sidecar would promise a reproducibility that does not exist.
- [x] **Response shape — RESOLVED from Cloudflare's model pages, no spend.** Read on `recraftv4-1-utility` and independently on `recraftv4-1`, and cross-checked against a third-party listing of the same response: `result.image` is an `https://...` **presigned URL** (the krea/flux-2-pro shape), the envelope carries `state: "Completed"`, and the example URL ends `.png`. Reuses `json_url` and the existing presigned fetch unchanged. DOC-DERIVED, not measured.
- [x] **Non-neutral default found and stated.** Recraft's own default for `size` is **`1024x1024` — a SQUARE**, so silence would quietly turn a 16:9 batch into 1:1 crops. `size` is therefore sent always, the same call made for krea's `creativity` and flux-2-pro's `output_format`. Pinned by a test.
- [ ] `style`/`substyle` values remain **unconfirmed** for the gateway path and both stay unset. Recraft's own API docs name `realistic_image` as the default style with `digital_illustration` among the alternatives, but that is the *native* Recraft API and the gateway's behaviour when the field is omitted was not confirmed. Left in the Unverified table. Research the enum only if it turns out to matter.

### 6. `recraft/recraftv4-1` — $35/1000 · `$$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

Art-directed sibling to Utility's general-purpose. Ships as a pair by decision. Elo 1198 — *lower* than Utility for identical money, so the label must not imply it is the upgrade.

- [x] Added; field list **confirmed identical** on both Cloudflare model pages (`prompt`, `size`, `style`, `substyle`, `controls`, `image`; no seed, no width/height, no `aspect_ratio`), and the response is the same presigned URL with `state: "Completed"`. The pair therefore shares one `_RECRAFT_COMMON` dict and differs only in id, label and price note — the same structure the krea pair uses.
- [x] Tooltip and `price_note` are honest about the ranking: same price, same fixed sizes, **lower** Elo (1198 vs 1218). Both say to pick it for art direction — high aesthetics, strong composition, accurate text rendering — and to pick Utility for everyday work. Neither is presented as the other's upgrade.
- [x] **A real bug was caught adding this one, and is now pinned by a test.** The second model of the pair needs its OWN `SIZE_TABLE_OVERRIDES` entry; without it `size_for()` silently falls back to the shared `SIZES` table and yields 1536x864 at Standard 16:9 — not a legal Recraft size. On any other gateway model that request is rejected for free; on this family it is **billed and then refused**. `test_every_size_enum_model_owns_a_size_table` now asserts that every `size_enum` model owns a table *and* that every ratio×tier it produces passes `validate_size`. Verified the test fails when the override is removed.

### 7. `google/nano-banana-2-lite` — $34/1000 at 1K · `$$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

Elo 1290 — the strongest score per dollar on the paid lineup, above both Krea models and above both Recraft models for slightly less money. Left near-last because the 1K/2K/4K ladder maps onto the tier dropdown *deceptively* well and prices differently at each tier: the highest risk of a subtly wrong cost estimate.

- [x] Fields — implemented. Only `prompt`, `aspect_ratio`, `resolution` and `output_format` are sent. No width/height (the model has no such field), no steps, no guidance, no negative_prompt, no seed.
- [x] `aspect_ratio` — all five program ratios are covered by the enum and are sent by ratio KEY, never recovered from a numeric ratio: the labels are nominal, and "16:9" is 1344x768 (1.750, not 1.778).
- [x] **`resolution` — and the thing that actually mattered here is that LITE IS PINNED TO 1K.** A genuine source conflict: Cloudflare's schema declares `1K|2K|4K`, but OpenRouter, fal.ai and a pricing breakdown all say Lite renders 1K only, and **Google publishes no 2K or 4K rate for Lite**. The unpriceability is what decides it — this program's contract is that it can quote a batch before you run it, and 2K on Lite is a request whose cost cannot be estimated from anything. `NANO_BANANA_TIER_RESOLUTION` holds the per-model mapping; `nano_banana_resolution()` is the only legal source of the value, **looked up rather than derived from the tier name**, precisely because the two models in the family will not agree.
- [x] **Per-resolution pricing built AND tested, even though Lite cannot exercise it.** `_per_resolution()` recovers the tier from the pixel size and is tested against a full 1K/2K/4K ladder at nano-banana-2's real prices, so the mechanism is not left untested until the expensive model lands. An unrecognised size falls back to the **dearest** price, never the cheapest. `cli estimate`, `cli dry-run` and the GUI cost readout all follow it; on Lite all three correctly quote $34.00 at every tier rather than inventing variation.
- [x] **Sizes are PUBLISHED, unlike krea's**, and cross-checked against two independent sources. Every tier is an exact 2x of the one below, asserted rather than trusted. This broke a UI string: the `~ estimated` size readout was keyed on `size_style`, which was right while krea was the only model with that style and wrong the moment a second one shared it. Now keyed on the new `ModelSpec.sizes_published`, which asks the honest question directly. **Second time a string keyed on `size_style` proved to be keyed on the wrong thing** — the first was Recraft's "locked to 1K".
- [x] **Both flagged strings checked by LAUNCHING THE GUI**, not by reading the code, as instructed. nano-banana shows an exact `1344 x 768`, krea still shows `~1328 x 752 (~1.00 MP, estimated)`, and the disabled-tier reason now has three distinct branches that each say the true thing: krea is genuinely locked, Recraft has one fixed published size, and nano-banana **is pinned by this program's choice** — saying "locked to 1K" there would have been the same lie the Recraft session fixed.
- [x] `output_format`: `jpg` here, `jpeg` on flux-2-pro, derived by `wire_output_format()` and never written at a call site. **The default is UNKNOWN rather than merely non-neutral** — neither Cloudflare nor Google publishes one — so it is sent explicitly on the grounds that an unknown default cannot be assumed neutral. Magic bytes sniffed regardless, and they matter *more* here: this is the only family where the program asks for a format, and a requested format is a weaker claim than a declared one.
- [x] **No seed.** `supports_seed=False` was the whole of the work, as predicted. Verified rather than re-implemented: a seed passed in is dropped, `_finish` records None, and the GUI disables the checkbox, label and entry. Both assertions were checked to FAIL when the flag is flipped.
- [x] **Response shape — RESOLVED from Cloudflare's model page, no spend.** Read on `nano-banana-2-lite` and cross-checked against the `nano-banana-2` page: `result.image` is an **https presigned URL** (the doc example ends `.jpg`), with `state: "Completed"` and `gatewayMetadata`. Reuses `json_url` and the existing presigned fetch unchanged. DOC-DERIVED, not measured.
- [x] **A latent bug found and fixed:** `_ratio_key_for` was matching against `SIZES_KREA` specifically. Harmless while krea was the only caller, but it would have compared krea's estimated 1328x752 (1.766) against nano-banana's 1344x768 (1.750) — one model's sizes answering another model's request. Now matched against the program's own five ratios, with a tolerance covering the drift these nominal labels carry.
- [x] `image_input` is a PERMANENT skip and is covered by the extended banned-fields test. It is the model's entire optional surface on Lite, so nothing else was left unexposed.
- [x] Tests: 56/56 offline (49 before). Seven new nano-banana tests plus two extended (banned fields, seedless metadata).

### 8. `google/nano-banana-2` — $67 (1K) · $101 (2K) · $151 (4K) · `$$$`  — **IMPLEMENTED 2026-09-05** (untested against the live API by design)

Highest quality on the list (Elo 1320) and **over tolerance at every tier**. Last by design: deliberate, occasional "hero image" use.

- [x] **`google_search` / `image_search` — RESEARCHED, and deliberately NOT sent.** They are Google Search grounding, not (only) img2img: the model searches before generating to ground the image in real-world fact. **The disqualifying fact is billing** — $14 per 1000 search queries after 5000 free per *month*, and Google's docs state that one prompt may trigger several billable queries. Through a pass-through gateway against an allowance the client cannot see, that is unpriceable by construction and would break the cost estimate on the dearest model here. Recorded as a **cost** decision (revisitable if the charge ever becomes visible) rather than an architectural one, in `NANO_BANANA_GROUNDING_FIELDS` with the rates alongside. `image_search` is also reference-image shaped, so it is doubly excluded.
- [x] `$$$` at every tier — verified across all five ratios and all three tiers, so the fixed dropdown label is honest. Pinned by a test that fails if any tier drops to or below the $50/1000 tolerance.
- [x] **The over-budget warning now has a second band.** The old text was identical at $15 and would have been identical at $151 — a warning that reads the same across a 10x range is one users skip. The `$$$` band leads with the **batch total and the image count** rather than the per-1000 rate, and says "beyond the tolerance", not "over the ceiling". GUI, `cli estimate` and `cli dry-run` all updated; verified by launching the GUI and by running both CLI paths.
- [x] **The tier ladder was free to add, as planned.** One `NANO_BANANA_TIER_RESOLUTION` entry (draft/standard/high → 1K/2K/4K), one derived `SIZE_TABLE_OVERRIDES` line, one `_per_resolution` price_fn. `has_tier_ladder()` returns True on its own and the tier dropdown enables itself. The machinery built during the Lite session needed no changes — which was the point of building it then.
- [x] **Draft/Standard/High rather than a bespoke "Ultra" tier.** Considered and declined: the tier names are a program-wide vocabulary meaning a quality *intent*, not an absolute pixel promise (klein's Draft is 768x432, Recraft's Standard is 1344x768), and a fourth rung existing for one model in fourteen would be dead on every other one. The size readout always shows real pixels. 1K at Draft reads oddly against the usual ~1024px Standard; that is the cost of a consistent vocabulary and it is the cheaper cost.
- [x] Added to `NANO_BANANA_MODELS` in the tests, so every existing nano-banana test covers both models.
- [x] **4K needed a per-model safe ceiling.** 5376x3072 is five times anything else in the lineup and the shared 1024px `max_safe_dimension` would have fired the SD degradation warning on a model natively specified to 4K — wrong, and harmful, since a warning that cries wolf teaches users to ignore it where it is real. Pinned by a test that also asserts the SD warning still fires.
- [x] **A latent marker bug fixed on the way.** `cost_tier_marker()` prices at a fixed 1536x864 reference, which is not a nano-banana size — so it was landing on `_per_resolution`'s unknown-size fallback and quoting the dearest tier. Right answer, wrong route. Override models are now marked at their own Standard size; no marker in the lineup changed, and a test pins that every override model is priced at a size it can serve.
- [x] Tests: 61/61 offline (56 before). Five new, one corrected (the shared nano-banana test hardcoded `$$` for the family and now asserts per model).

---

## Cross-cutting, once the models exist

- [ ] **Verify the black-image content check per family.** CLAUDE.md calls this the single most important behaviour in the program, and each provider may signal refusal differently — p-image and flux-2-pro have explicit filter controls, Google and Recraft have their own policies. Some may return an API error (like klein's 3030) rather than a black frame; some may do both. **This costs real money to test, so do it on p-image first at $0.005 a shot.**
- [ ] Update `guide.md` with the new models, their quirks, and what the `$`/`$$`/`$$$` labels mean.
- [ ] Update `readme.md` and `promo.md` model lists.
- [ ] Record durable measured facts in `docs/findings.md`; session narrative in `docs/session-log.md`.

---

## Unverified — needs a paid call to confirm

Everything here is coded defensively rather than guessed at silently. **Do not quietly resolve one of these by assumption** — that is exactly the failure mode CLAUDE.md's "measure, do not assume" rule exists to prevent (two shipped bugs came from writing down a plausible number instead of testing one).

| Question | Affects | Current handling |
|---|---|---|
| Response: base64 or download URL? | 5 of 8 (**p-image**: data-URI base64. **krea x2 + flux-2-pro**: a PRESIGNED URL — the extra-GET mechanic is real after all, just not where the wishlist predicted) | Both shapes implemented and tested |
| What pixel size `1K` resolves to per ratio | krea x2 | Krea does not publish it. Estimated at ~1 MP exact-ratio; **never sent** to the model (it takes a ratio enum), so a wrong guess cannot break a request — it only affects a displayed number, shown with a `~` and the word "estimated". True size is sniffed into the sidecar metadata on the first real run. |
| What `state` values exist besides `"Completed"` | pruna | Non-Completed treated as transient |
| Prompt length limits | all 8 | Soft counters set defensively, marked unverified in comments |
| How each family signals a content refusal | all 8 | Assume it may be either an API error or a black frame; both paths already exist |
| `style`/`substyle` enum values | recraft x2 | Left unset (both optional). Recraft's OWN API docs give `realistic_image` as the default style, but that is the native Recraft API, not the gateway path, and whether omitting the field on the gateway inherits it was not confirmed. |
| Does the gateway apply a default `style` when the field is omitted? | recraft x2 | Nothing is sent; whatever the provider does is what the user gets. Unlike `size`, a style default cannot produce a *wrong-shaped* image, so silence is the safe call here. |
| Does Recraft's post-billing `size` validation behave as documented? | recraft x2 | The asymmetry is doc-derived. Coded as though it is true: `size` is validated against the published enum client-side, in `validate_size()` as well as the provider, so the question never has to be answered at the user's expense. |
| ~~`creativity`/`intensity`/`complexity`/`movement` ranges~~ | ~~krea x2~~ | **RESOLVED.** `creativity` is now EXPOSED and always sent, defaulting to `raw` (off) — its API default is `low`, i.e. expansion on. The other three stay unset; their defaults are genuinely neutral. |
| **Does Lite actually honour 2K/4K, and at what price?** | **nano-banana-2-lite** | **Pinned to 1K.** Cloudflare's schema declares `1K\|2K\|4K`; OpenRouter, fal.ai and a pricing breakdown all say Lite renders 1K only, and Google publishes NO 2K/4K rate for it. Sending an unpriceable resolution would break the program's core promise that a batch can be quoted before it runs, so the tier is pinned and the GUI says plainly that this is the PROGRAM's choice rather than an API limit. One paid call settles it; unpin only alongside real published prices. |
| What pixel size `1K`/`2K`/`4K` resolves to per ratio | nano-banana x2 | **Published**, unlike krea's — cross-checked against two independent sources, every tier an exact 2x. Still doc-derived, and still never SENT (the model takes a ratio enum and a resolution word), so a wrong value affects only a displayed number. |
| Default value of `output_format` | nano-banana x2 | **Unknown** — neither Cloudflare nor Google publishes one, which is weaker than flux-2-pro's documented non-neutral `jpeg`. Sent explicitly for exactly that reason; magic bytes sniffed regardless, so a wrong or ignored value cannot mislabel a file. |
| ~~What `google_search`/`image_search` do~~ | ~~nano-banana-2~~ | **RESOLVED 2026-09-05.** Google Search grounding, billed SEPARATELY at $14/1000 queries after 5000 free per month, with one prompt able to trigger several billable queries. Unpriceable through a pass-through gateway, so neither is sent. A cost decision, revisitable if the charge becomes client-visible — not the permanent architectural skip the img2img fields get. |
| Is `safety_tolerance: 5` really the permissive end? | flux-2-pro | **Direction CONFIRMED from Cloudflare's published schema 2026-09-05** ("0 is the strictest, 5 the most permissive"), read twice independently — but still DOC-DERIVED, never called. Pinned by constants and a dedicated test. Verify on first paid use: one prompt that reliably trips the native klein filter, generated at 5 and at 0 (~$0.06). |
| Does `disable_safety_checker: true` actually loosen p-image? | p-image | Field confirmed legal by the zero-cost 400-rejection probe; its *behaviour* is unverified. Sent only on the `permissive`/`off` modes, never by default. |
| Does `output_format` change anything the sniffer cannot see? | flux-2-pro | Sent explicitly as `jpeg`; magic bytes sniffed regardless, so a wrong or ignored value cannot mislabel a file. |
| Does 402 surface cleanly with no prepaid credit? | all 8 | Mapped to a clear permanent error |
