# UI/UX sanity pass — plan and working notes

Started 2026-09-05. **Written to survive a session boundary:** if this work is picked up in a later session, everything needed is here, including the measured findings that were made while planning. Tick boxes as they land.

## Why this exists

The program was designed around **five** Cloudflare-native models (3 free SD + 2 klein). Eight AI Gateway models were then added, and they break the assumptions the GUI copy was written against: they bill flat-per-image from **prepaid credit** rather than per-tile from the **free daily neuron allowance**, most of them have no quality-tier ladder at all, one of them (nano-banana-2) uses the tier as a **price** lever, and several accept no seed, no negative prompt, no guidance and no steps.

The result is a UI whose labels, tooltips and layout still describe the old five-model world. This pass fixes that. **No new models, no new providers** — the lineup is closed per CLAUDE.md.

---

## Measured findings made while planning

These were probed live during planning and are **new** — they are not yet in `docs/findings.md` and must be written there as part of this work.

### Pollinations silently CLAMPS to ~0.59 MP, preserving aspect ratio

This started as a question about whether FLUX.1 schnell on Pollinations only supports 1:1. **It does not** — non-square ratios work fine. The real problem is different and worse.

Probed 2026-09-05 with unique prompts (cache-defeating), both models:

| Requested | Returned | Result |
|---|---|---|
| 768x432 (16:9) | 768x432 | match |
| 512x512 (1:1) | 512x512 | match |
| 432x768 (9:16) | 432x768 | match |
| 1024x576 (0.59 MP) | 1024x576 | match |
| **1152x648** (0.75 MP) | **1024x576** | **clamped** |
| **1280x720** (0.92 MP) | **1024x576** | **clamped** |
| **1536x864** (1.33 MP) | **1024x576** | **clamped** |
| **1024x1024** (1.05 MP) | **768x768** | **clamped** |
| **1024x1536** (1.57 MP) | **627x940** | **clamped** |

Confirmed on `dreamshaper` as well as `flux`, so it is a Pollinations platform cap, not a model quirk.

**The cap is ~589,824 px (0.5625 MP)** — 1024x576 and 768x768 both land exactly there. Aspect ratio is preserved; the image is simply scaled down. It returns **HTTP 200 with no error and no warning**.

Two consequences:

1. **`max_dimension=2048` on both Pollinations specs is wrong by roughly 3.5x.** At the program's Standard tier the user asks for 1536x864 and silently receives 1024x576.
2. **This is a correctness bug, not only a UI one.** `GenerationResult` is constructed with the *requested* `width`/`height`, so the sidecar JSON records a size the file does not have. `actual_dimensions` is captured but not used to correct the record.

Note this is the *same class* of fault as the black-image content filter: HTTP 200, no error, wrong result. Consistent with the project's standing rule — **trust the bytes, not the response.**

### `reserve_lines` was a one-way ratchet, and that was wrong for user-driven text

Found 2026-09-05 from user feedback during the Phase 1 review. Selecting Nano Banana 2 (a 3-line note) and then returning to SDXL Lightning (1 line) left **two blank lines of dead space that never closed** — in the model note and again in the Cost Calculator.

Cause: `reserve_lines` in `gui/scroll.py` tracked a high-water mark and only ever grew (`if capped > state["peak"]`). That is right for status text that changes on its own — a credential check, a batch result — where an unprompted resize reads as the section jumping. It is **wrong for text driven by an explicit user choice**: when the user has just picked a different model, the panel resizing IS the expected response, and holding the tallest model's height forever leaves visible dead space under every shorter one.

Fixed with a `sticky_height` flag, defaulting True (existing behaviour) and set False on the seven labels that re-render on model selection: `model_note`, `credit_note`, `calc_note`, `budget_label`, `param_note`, `format_native`, `size_warning`.

**The general lesson:** a "don't let it jump" guard has to ask *what caused the change*. Suppressing a resize the user just asked for is not stability, it is a stale layout.

### Cost bands replaced the "over budget" wording (2026-09-05)

From user feedback during the Phase 2 review. The label read *"OVER BUDGET — $18.97 per 1000 exceeds the $5.00 ceiling for this project. Available, but never the default."* Two faults: it described **this project's internal budget policy**, which the user has never heard of and cannot act on, and it was **binary** — $5.01 and $151 got the identical sentence.

Replaced with a five-band scale, in the user's own thresholds:

| Band | Per 1000 images | Marker | Models |
|---|---|---|---|
| **FREE (Neurons)** | $0 | *(none)* | 3 SD + both Pollinations |
| **LOW COST** | ≤ $5 | `$` | klein-4B $1.72, p-image $5.00 |
| **MEDIUM COST** | ≤ $20 | `$$` | klein-9B $16.94, Krea Turbo $15 |
| **HIGH COST** | ≤ $50 | `$$$` | Krea Medium, flux-2-pro, both Recraft, nano-Lite |
| **EXTREME COST** | > $50 | `$$$$` | nano-banana-2 ($67/$101/$151) |

Bounds are **inclusive**, so a model exactly on a round number lands in the cheaper band — p-image at exactly $5.00 is LOW COST. A boundary that punishes a model for sitting exactly on it reads as a bug to anyone who checks the arithmetic.

Notes:

- `COST_BAND_LIMITS` is the **only** place a threshold is written; labels, markers and ttk styles all derive from `cost_band()`. The old marker and the old over-budget warning were computed separately and could describe different things.
- The marker gained a fourth level (`$$$$`), so `$$$` now means HIGH rather than "the most expensive". Six tests encoded the old three-band scheme and were updated.
- **The calculator grades the SELECTED size, not the reference size.** On nano-banana-2 the tier moves the price across bands, so grading at the fixed browsing reference would understate what the user is about to pay.
- **LOW and FREE print no warning line at all.** Repeating "LOW COST" as a warning trains users to ignore the line that matters.
- **`test_no_source_file_still_uses_the_old_budget_vocabulary` scans the source.** Five separate sites had each written their own version of the old sentence; a scan is what stops a sixth appearing.

### Neurons are front-loaded on all five native models (2026-09-05)

Also from review feedback. The free SD models said "Cloudflare charges nothing" without saying *why*, and only klein-4B mentioned the daily allowance at all — so a user had no way to understand why one free model differs from another, or why a paid model can cost nothing for the first few hundred images.

All five Cloudflare-native notes now lead with the **10,000 neurons/day free allowance**, glossed on first use as "their compute credit", and distinguish the two cases honestly: the three SD models **measured zero consumption**, while the klein pair genuinely consume and eventually bill.

This also **reversed a rule from the previous round**: `neurons` had been added to the banned-vocabulary test as jargon. That was wrong — it is Cloudflare's own published term, it appears in their dashboard, and the allowance cannot be explained without it. The ban now covers only vocabulary internal to *this project* ("ceiling", "tolerance"), plus scores and billing units a user cannot act on.

### Cloudflare gateway access — what the dashboard actually requires

Doc-derived (Cloudflare's own docs), **not** measured — no prepaid credit is available to spend. Sources at the bottom of this file.

- **Endpoint is already correct.** `POST /accounts/{id}/ai/run` with the model id in the body. No gateway id belongs in the URL path.
- **Gateway routing uses the `cf-aig-gateway-id` HTTP header**, not the path. For **third-party models it is optional** — requests route through the account's **default gateway**, and *"if the gateway does not exist, AI Gateway creates it on the first authenticated request."* So the program sending no such header is fine. Worth a code comment so a later session doesn't "fix" it.
- **Token permission: Account → Workers AI → Read** is required for all `/accounts/{id}/ai/*` endpoints, third-party models included. The **"Read all resources"** template includes this, so `guide.md`'s existing advice still stands — but it was verified against native models only, so the guide should say which part is measured and which is inferred.
- **Credits must be loaded in the dashboard before any gateway model will run.** AI Gateway page → **Credits Available** card (top right) → **Manage** → **Top-up credits**. Optional auto-top-up with a threshold and recharge amount.
- **There is a 5% fee on credit purchases** ($100 of credit costs $105). The program mentions prepaid credit but has never mentioned this.
- Without credit the API returns **HTTP 402**, which the provider already maps to a fatal `QuotaExhausted`. That part is correct.

---

## Phase 1 — Correctness

- [x] **1.1 Fix the tooltip off-screen clamp.** `gui/tooltip.py:_position` computes `y = max(_MARGIN, min(y, screen_h - tip_h - _MARGIN))`. When `tip_h` exceeds the screen height that inner term goes **negative**, the window is placed with its top above the screen, and Tk clips the bottom — which is the reported "text cut off at the bottom". Clamp to `_MARGIN` when the tooltip cannot fit, and widen `wraplength` for long tooltips so they are wide-and-short rather than narrow-and-tall.
- [x] **1.2 Split the oversized model tooltip.** It is ~9 paragraphs and has grown by accretion — every model added appended its own. Replace with a short "how to read this list" tooltip (what the markers mean, what the format suffix means, which model is the default). Per-model prose moves to the **`price_note` / licence area already below the dropdown**, which updates on selection and is readable without hovering. This removes the growth pattern permanently rather than trimming it once.
- [x] **1.3 Make the usage link model-aware.** `USAGE_DASHBOARD_URL` points at `/ai/workers-ai`, the **neuron** dashboard — meaningless for all eight gateway models. Show "Check usage ↗" (neurons) for native models and "Check credits ↗" (AI Gateway) for gateway models. Rewrite its tooltip, which currently names only the original five.
- [x] **1.4 Add the AI Gateway dashboard link.** (Bonus request.) Constant beside `USAGE_DASHBOARD_URL` in `core/providers/cloudflare.py`, so no URL is hardcoded in the GUI.
- [x] **1.5 Surface the prepaid-credit prerequisite BEFORE it bites.** Today it appears only in a Cost Calculator note, below the fold and after the model is chosen. Add a short line beside the model dropdown when a gateway model is selected: needs prepaid credit, load it in the dashboard, 5% purchase fee, link. This is the single biggest UX gap — a user can currently configure a whole batch and only discover at run time that it cannot run.

## Phase 2 — The quality tier control

- [x] **2.1 Make `TIER_LABELS` model-aware.** It is currently a module constant reading *"High — biggest; klein models only, and ~64% slower"*, which is wrong or irrelevant for 8 of 13 models. Three cases, and the code already distinguishes them:
  - **no ladder** (krea x2, recraft x2, nano-banana-lite) — dropdown already disables, keep as is;
  - **size-only ladder** (SD x3, klein x2, flux-2-pro, pollinations x2) — current wording, minus the klein-specific aside;
  - **price ladder** (nano-banana-2 ONLY) — labels must carry the price, e.g. *"High — 4K, $151 per 1000"*, so the dropdown itself shows that changing it changes the bill.
- [x] **2.2 Rename the caption** to "Size / quality tier" — it selects a resolution, and on one model a price. "Quality" alone implies a fidelity knob it is not.
- [x] **2.3 Move the klein "64% slower" note** out of the tier label into the existing per-model warning label, where that class of note already lives.

### Phase 2 notes (done 2026-09-05)

- `tier_changes_price()` is **computed from the price function**, not from a list of model keys: a future by-resolution model picks the behaviour up with no edit. Today it is True for nano-banana-2 **and both klein models** (klein bills per tile, so a bigger tier really does cost more) and False for everything flat or free.
- **Three caption sets, not one.** "Draft - smallest and cheapest" is a FALSEHOOD on a flat-priced model, where Draft costs exactly what High costs; it would push users to fewer pixels for a saving that does not exist. `TIER_INTENT_PRICED` / `_FLAT` / `_FREE` pick the honest wording, and a test pins that no flat model says "cheap".
- **Price decimals are chosen so two tiers cannot print the same number.** At zero places klein-4b read "$1 / $2 / $2". Below $10 the labels use two decimals.
- **The tier is tracked by INDEX, not by reading the label back.** The labels are per-model now, so the old reverse lookup on visible text would have silently reset the user's tier to Draft the moment the list was rebuilt. Verified: setting High on one model and walking all thirteen keeps High.
- Labels were **measured across every model x tier x ratio** (longest 69 chars) rather than eyeballed; the combobox is 70 wide and a test pins it. The first draft was 83 chars against a 56-wide box.

## Phase 3 — Generation Settings layout (grouping only)

**DECIDED: group, do NOT hide.** Hiding controls when the model changes reads as the app losing settings. Everything stays visible; grouping and disabled-state clarity do the work.

- [x] **3.1 Group into two labelled sub-areas** inside the existing frame: *Negative prompt* (layers + box + counter) and *Model parameters* (guidance, steps, prompt expansion, content filter, seed). The current flat 4-column grid is why the panel looks like an odd one out — columns 2 and 3 are used by only two widgets, so Guidance and Steps sit at opposite ends of an otherwise empty row.
- [x] **3.2 Make disabled controls actually read as disabled.** Guidance and Steps currently grey out into *empty boxes* indistinguishable from "not filled in yet". Give them a placeholder showing the value being used, or an explicit "not used by this model".
- [x] **3.3 Keep `param_note` intact.** Its per-model explanations of *why* something is unavailable are good and hard-won; grouping must not drop them.

### Phase 3 notes (done 2026-09-05)

- **Two sub-groups: "Negative prompt" and "Model parameters".** The old flat 4-column grid existed only because Steps and Fixed seed needed columns 2 and 3, which stranded Guidance at one end of a row with Steps at the other. Each group now uses the columns that suit it.
- **The Guidance box was never disabled at all.** It was built as a local `g`, so nothing could reach it — it stayed editable on the eight models that accept no guidance, while `param_note` said the opposite two lines below. Now `self.guidance_entry`, disabled with the rest.
- **Disabled boxes state what is used instead.** A greyed empty `ttk.Entry` is indistinguishable from one waiting for input. klein shows its fixed `4` steps; models with no such parameter show `n/a`.
- **The placeholder must never be persisted.** Both vars have `trace_add` handlers writing to config, so showing `n/a` would have saved it as the user's step count and sent it to the next model that does accept one. Guarded by `_placeholding`. VERIFIED: setting steps=12/guidance=7.5, walking all thirteen models and returning leaves both the vars and `config.json` untouched.
- **The negative group COLLAPSES on models that ignore it** (decided with the user mid-phase, amending the no-hiding rule). It is 431px of layer checkboxes and text box, dead on 10 of the 13 models. The group frame and a line saying *why* stay on screen — the feature never vanishes — but the contents fold, taking the panel from 725px to ~450px. The user's layers, text and config survive the round trip; verified.

**Amendment to the no-hiding rule, recorded deliberately:** the rule was "hiding controls reads as the app losing settings". That holds for a control the user might want. It does not hold for a whole feature the selected model *cannot use*, where the honest thing is to say so once rather than show twenty dead checkboxes. What must never disappear is the *explanation* — which is why the group and its reason stay, and only the controls fold.

## Phase 4 — Bonus items

- [x] **4.1 Model dropdown shows 15 rows.** `self.model_combo.configure(height=15)` — Tk's combobox `height` is measured in rows. 13 models exist today, so this shows the whole list without scrolling.
- [x] **4.2 Make the size readout more prominent.** It is the answer to "what am I actually getting", currently rendered in the same weight as its neighbours. Increase size/weight, and tighten its relationship to the ratio and tier dropdowns that produce it.
- [x] **4.3 Fix the Pollinations size specs — CORRECTNESS, not cosmetics.** See the measured table above.
  - Set the real cap on both Pollinations specs (~0.59 MP; `max_dimension` 2048 is wrong).
  - Give Pollinations a `SIZE_TABLE_OVERRIDES` entry with sizes at or under the cap, so the program stops requesting sizes that are silently downscaled.
  - **Do not** add auto-cropping. Cropping was requested as the fix for a suspected 1:1-only limit, but the measurement shows this is **not** a ratio problem — ratios are honoured, the image is scaled down. Cropping would discard pixels to fix a problem that does not exist; the right fix is to ask for a size the service will actually deliver. **Confirmed with the user 2026-09-05: the cropping idea is withdrawn, do the size table instead.**
  - Record the requested-vs-actual mismatch in the sidecar, or correct the record from `actual_dimensions`, so metadata stops asserting a size the file does not have.

### Phase 4 notes (done 2026-09-05)

- **4.1** Model dropdown shows 15 rows (done in Phase 1); combobox widened to 60 to fit the longest label, pinned by a test.
- **4.2** The size readout is now a **figure**, not a line of body text: pixel dimensions large, tiles/megapixels small underneath, spanning both control rows so it reads as the RESULT of the two dropdowns rather than a third setting. **Tiles are now shown only where they are a billing fact** — a paid, tile-priced model. Free models were printing a tile count because `bills_per_tile` defaults True and none of them overrode it; on a free model that number has no consequence, and on a flat-priced one it implies headroom that does not exist.
- **4.3** Pollinations size tables added and the correctness bug closed. See below.

#### The Pollinations fix, verified end to end

`SIZES_POLLINATIONS` was **computed** (CLAUDE.md's rule) against the measured 589,824 px cap, then **verified against the live API**: 1024x576, 936x624, 768x768 and 576x1024 were each requested and each came back at exactly the requested size. `max_dimension` corrected from 2048 to 1024 on both specs.

The second half of the bug was the sidecar. `GenerationResult` is built from the REQUESTED size, so a clamped image was recorded as the size that was asked for. Now:

- the sidecar carries **`size_mismatch`**, stating outright whether the provider resized the image, rather than leaving two similar keys (`width`/`height` vs `actual_dimensions`) to be compared by a reader who never does;
- the engine **logs a warning** when they differ, because a batch that quietly delivers smaller files while reporting 100% success is the same failure shape as the black-image content filter.

Verified with a real 2-image run: files delivered at 1024x576, sidecar records 1024x576, `size_mismatch: false`. Then verified the *detection* by deliberately bypassing the table with a 1536x864 request — returned 1024x576, mismatch correctly detected.

**No auto-cropping**, per the amended decision: ratios were never the problem.

## Phase 5 — Documentation rewrite

**COMPLETE 2026-09-05.** All eight items landed in the fresh session this section was written for. `changelog.md` is new and ships; `promo.md` no longer does. Pricing is recorded as settled at **$8 paid**. Tests still 73/73 after the `build_release.bat` change. **One follow-up left, tracked in `TODO.md`:** the promo images still carry a "Free" tag and need re-rendering before the next store upload.

Original handoff note, kept for the record: **DEFERRED TO A FRESH SESSION by decision (2026-09-05).** Phases 1-4 are complete, tested and verified in the running GUI. This section is written to be picked up cold.

### What a new session needs to know

Read `CLAUDE.md` first, then this file's "Measured findings" section above — it holds facts not yet in `docs/findings.md`.

**State of the code as of the handoff:** 73/73 tests pass (`python tests/test_engine.py`, offline). The GUI launches clean and every model has been walked. Nothing is half-finished.

**What changed in Phases 1-4 that the docs do NOT yet reflect** — this is the actual content of the rewrite:

1. **Cost bands replaced "over budget" everywhere.** FREE (Neurons) / LOW / MEDIUM / HIGH / EXTREME, thresholds $5 / $20 / $50. The docs still describe a `$`/`$$`/`$$$` scheme and a "$5 per 1000 project ceiling".
2. **The marker gained a fourth level** (`$$$$`), so `$$$` now means HIGH rather than "most expensive".
3. **Gateway models need prepaid credit**, loaded on the AI Gateway dashboard page, with a **5% purchase fee**. `guide.md` does not mention credit at all.
4. **The token needs Account -> Workers AI -> Read**; "Read all resources" includes it. `guide.md`'s existing advice stands but should say which part is measured (native models) and which is doc-derived (gateway).
5. **Pollinations is capped at ~0.59 MP** — 16:9 is 1024x576, not the 1536x864 the docs quote as universal.
6. **The tier dropdown is per model** and disabled entirely on five models; on nano-banana-2 it changes the PRICE.
7. **klein-9B's label changed** from "(paid, OVER BUDGET)" to "(paid, slower, pricier than 4B)".
8. **The licence label was removed** from the GUI (the fact remains in `ModelSpec.licence`).
9. **All 15 model notes were rewritten** for a layperson — no internal vocabulary, always "per 1000 images".

### The work

- [x] **5.1 `guide.md`** — shipped user guide, opened by the Help button. Add the credit prerequisite and dashboard steps, the cost bands, which models have no tier/seed/negative prompt, the corrected Pollinations sizes.
- [x] **5.2 `readme.md`** — public overview + licence. Update the model lineup and feature list.
- [x] **5.3 `promo.md`** — **the pricing decision has CHANGED**: the program is **paid at $8** and has **2 paying customers** already. The file currently argues for free/name-your-own-price at a $0 minimum; the author note at line 42 records the counter-argument (a paywall filters abuse of an external service; "someone could build this in a weekend" undersells the required knowhow). Rewrite the pricing section as settled, and fix the itch settings block. Keep the customer count in planning sections only, not in customer-facing copy.
- [x] **5.4 Stop shipping `promo.md` in the release.** DECIDED: it is dev-only — store copy, marketing plan, pricing strategy — with no business in a customer's download. Remove the copy line from `build_release.bat` (line 62). It stays in the repo.
- [x] **5.5 No manual line wrapping** in any of them — one continuous line per paragraph, per CLAUDE.md and the user's global preference.
- [x] **5.6 Write `changelog.md` — a NEW file, for the public "v2.0 Release".** This is what the itch.io devlog post is built from, so it is written for **paying laypeople**, not for developers. Group under **Added / Changed / Fixed / Removed**. Lead each entry with what the user gets, not what the code does.

  What belongs in it, from this pass and the gateway work before it:

  - **Added** — eight new models via Cloudflare's AI Gateway (P-Image, both Krea, FLUX.2 pro, both Recraft, both Nano Banana), taking the lineup from 5 to 13; an adjustable content filter on the two models that offer one; prompt-expansion control; the AI Gateway credits link.
  - **Changed** — the five-band cost scale (FREE/LOW/MEDIUM/HIGH/EXTREME) replacing the old over-budget warning; per-model size/quality tier options that now show the real size and, on Nano Banana 2, the real price; every model description rewritten in plain language; the Generation Settings panel reorganised into two groups; a more prominent size readout; the model list showing all 13 at once.
  - **Fixed** — the model tooltip whose text was cut off the bottom of the screen; Pollinations images silently arriving smaller than requested **and being recorded at the wrong size** (this is the one worth stating plainly — it affected files people already generated); the Guidance box accepting input on models that ignore it; panels leaving blank gaps after switching models.
  - **Removed** — the licence line under the model dropdown (you own what you generate; it was telling people something they already assumed).

  **Honesty note for this entry:** the eight gateway models are implemented against published documentation and have **not been run against the live API**, because they bill from prepaid credit and none was available. Say so. A paying customer discovering it themselves is far worse than being told up front, and it is genuinely useful information: the free lane is fully tested, the paid gateway lane is not yet.

  **Do NOT put in it:** internal vocabulary, test counts, file or function names, or anything from `docs/`. If an entry cannot be phrased as something the user notices, it does not belong.

- [x] **5.7 `build_release.bat`: drop `promo.md`, add `changelog.md`.** Two changes to the same block of copy lines (currently 60-64). `promo.md` is dev-only and must stop shipping (5.4); `changelog.md` is customer-facing and must start. Check nothing else references the removed file.
- [x] **5.8 Update `CLAUDE.md` itself** — it says the test suite is 49/49; it is 73/73. It also still describes the `$`/`$$`/`$$$` scheme and the `$5/1000` ceiling as the governing vocabulary.

## Phase 6 — Verification

- [x] **6.1** `python tests/test_engine.py` — green throughout. **49/49 at the start of this pass, 73/73 now.**
- [x] **6.2** Tests added for everything newly pinned: the Pollinations cap and exact ratios, the sidecar mismatch flag, the five cost bands and their boundaries, the tier-label branch per model class, label widths for both comboboxes, the layperson vocabulary rule, and a source scan that stops the old budget wording reappearing.
- [x] **6.3** GUI launched and every model walked after each phase, per CLAUDE.md's standing rule. Also verified end to end with a real 2-image Pollinations run (free): files delivered at 1024x576, sidecar records 1024x576, `size_mismatch: false` — then the detection itself verified by deliberately bypassing the table with a 1536x864 request, which returned 1024x576 and was correctly flagged.
- [x] **6.4** `docs/findings.md` updated with the Pollinations clamp, the gateway-access facts and the three GUI pitfalls; `docs/session-log.md` has this session's entry. `TODO.md` and the `CLAUDE.md` corrections were both done in the Phase 5 session, as planned.

---

## Rules for this work

- **The model and provider lineup is CLOSED.** This pass changes presentation, sizes and docs — it adds nothing.
- **`core/models.py` stays the single source of truth.** No model fact gets hardcoded in the GUI. The tier-label work in Phase 2 must read from the registry, not from a lookup table of model keys in the GUI layer.
- **Doc-derived facts are labelled as such.** The gateway-access notes above could not be measured; a later measurement beats them.
- **Key user-facing explanations on the fact they assert, not on a field that happens to correlate.** This has already caused two shipped bugs (the "locked to 1K" reason, and the "~ estimated" size readout).

## Sources

- [Cloudflare AI Gateway — REST API](https://developers.cloudflare.com/ai-gateway/usage/rest-api/) — endpoint shape, `cf-aig-gateway-id` header, Workers AI → Read token permission
- [Cloudflare AI Gateway — Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/) — credit top-up steps, auto top-up, 5% fee
- [Workers AI and AI Gateway unify model access and billing (changelog)](https://developers.cloudflare.com/changelog/post/2026-08-07-workers-ai-unified-billing/)
- [Default gateway (changelog)](https://developers.cloudflare.com/changelog/2026-03-02-default-gateway) — auto-creation of the default gateway on first authenticated request
