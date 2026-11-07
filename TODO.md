# TODO

Live checklist only. Ordered so nothing expensive happens before it has been validated for free.

Status: `[ ]` todo · `[~]` in progress · `[x]` done

**Where things live**

| File | What it holds |
|---|---|
| **TODO.md** (this file) | What is still to do |
| [docs/findings.md](docs/findings.md) | Measured facts — prices, model behaviour, API quirks, GUI pitfalls. **Read before touching provider, pricing or layout code.** |
| [docs/session-log.md](docs/session-log.md) | What each session did and found, chronologically |
| [docs/gateway-models-todo.md](docs/gateway-models-todo.md) | The 8 Cloudflare AI Gateway models. **All eight ship as of 2026-09-05 — the model lineup is complete.** Kept for the per-model quirks and the "Unverified" table. |
| [CLAUDE.md](CLAUDE.md) | Project background, architecture and confirmed decisions |

**Keep this file short.** When a session ends, put the write-up in `docs/session-log.md` and any durable measured fact in `docs/findings.md` — tick the box here and move on. Notes piled into this file make it expensive to load as context every session.

---

## How to run the sessions

Do **not** try to do this in one session. The phases below are deliberately grouped so each one ends at a natural stopping point with something working. Suggested split:

| Session | Covers | Why it ends here |
|---|---|---|
| **1. Spike** | Phase 1 | Answers the open unknowns (do `$0` models burn neurons? what does a 429 look like?) with a throwaway script. **Cheap to redo, and everything downstream depends on it.** Don't build the app first. |
| **2. Core** ✅ | Phases 2–3 | Provider layer + batch engine + SQLite, driven from the CLI. Fully testable with no GUI. |
| **3. GUI** ✅ | Phase 4 | Wraps the working engine. Big session; keep it separate so UI fiddling never destabilises the engine. |
| **4. Art direction** | the styling brainstorm | Uses the finished tool. Human-judgement work, not coding — needs fresh context and the inspo folders. |
| **5. Release** ✅ | Phase 6 | Follows `RC prompt to make releases easier.md`. **Reordered 2026-08-31 to come BEFORE the mods:** the program is finished and shipping it is not blocked on anything, whereas the mods need generated images that do not exist yet. |
| **6. Art direction + Mods** ✅ | Phase 5 | Moved to its own project (Commander Wars Developer). |

Sessions 2 and 3 can merge if things go smoothly; 1 and 4 should stay separate. Start each session by reading `CLAUDE.md` and this file, then continue from the first unchecked box.

## Post-release features

- [x] **Style reference image — BUILT 2026-09-19.** One global reference image steering every image in the batch, on the **5** models that accept a **local file** (both klein via multipart binary, both nano-banana via base64, flux-2-pro via base64 — the plan said 4 and then listed 5). Full spec, measurements and build order in **[docs/reference-image-plan.md](docs/reference-image-plan.md)** — read it first; it is a complete plan, not a sketch. Partially reverses the "img2img is a permanent skip" ruling, with the user's approval. krea/recraft/p-image stay excluded (measured impossible). Key trap: the 64px-per-side minimum is **undocumented**, so a 16x16 sprite is rejected outright and must be NEAREST-upscaled first.
- [x] Generate slider — cap a run at the first N prompts, for style tests (2026-09-02)
- [x] Negative prompt presets, with one built-in (2026-09-02)
- [x] Soft per-model prompt length counters (2026-09-02)
- [x] Stackable negative layers — checkboxes, deduplicated composition (2026-09-02)
- [x] `prompting.md` and `recipes.md` shipped alongside `guide.md` (2026-09-02)
- [x] Cloudflare truncation probe — CONFIRMED, SD models truncate; ~300 char advice is correct (2026-09-02)
- [x] **Preset naming scheme** — `NN GROUP - NAME`, user presets sorted above the built-ins with a `*` prefix (2026-09-03). Scheme in [docs/preset-naming-scheme.md](docs/preset-naming-scheme.md)
- [x] **Style preset content pass** — 55 built-ins across 10 groups, all 300–500 chars, style-only outside the deliberate `06 COOL` / `07 BEAUTY` exceptions (2026-09-03)
- [x] **Negative preset brainstorm** — `negatives.txt` overhauled into 20 single-concern stackable layers, including deliberately inverted ones (2026-09-03)
- [x] **Cloudflare AI Gateway models — ALL EIGHT SHIP (2026-09-05).** p-image, krea x2, flux-2-pro, recraft x2, nano-banana-2-lite, nano-banana-2. 61/61 offline tests. The model lineup is now closed. Detail in [docs/gateway-models-todo.md](docs/gateway-models-todo.md).
- [x] **Documentation pass for the gateway lineup — DONE 2026-09-05.** `guide.md`, `readme.md`, `promo.md` and `CLAUDE.md` all rewritten for the thirteen-model lineup, plus a new customer-facing `changelog.md` for the v2.0 itch devlog. Cost bands replace the old budget vocabulary throughout; the prepaid-credit prerequisite, the 5% purchase fee and the corrected Pollinations sizes are documented; per-model tables cover which models accept no tier, no seed and no negative prompt. **Pricing settled at $8 paid**, and `promo.md` no longer ships in the release. Phase 5 of [docs/ui-sanity-pass-plan.md](docs/ui-sanity-pass-plan.md). Remaining before upload: **re-render the promo images**, which still carry a misleading "Free" tag, then the exe build.
- [x] **UI/UX sanity pass — COMPLETE 2026-09-05.** Six phases against a GUI still written for the original five models: tooltip clamp and split, model-aware usage links, the prepaid-credit warning surfaced before it bites, per-model size/quality tier labels, the Generation Settings regrouping, a prominent size readout, the five-band cost scale replacing the over-budget warning, and the **Pollinations size clamp fixed as a correctness bug** (images were arriving smaller than requested and being recorded at the wrong size). 49/49 tests at the start, **73/73 now**. Plan and findings in [docs/ui-sanity-pass-plan.md](docs/ui-sanity-pass-plan.md).
- [x] **Paid gateway model testing — PLAN READY, awaiting credit.** $5 of prepaid credit goes on 2026-09-06; the plan spends **$0.25** of it to prove all eight gateway request paths end to end, using the two real Commander Wars mod prompts so the output is usable art rather than throwaway probes. Full plan, exact per-model costs and the check-after-each-image list: `docs/paid-model-test-plan.md` (archived locally in `old wip/`). **Credit loaded 2026-09-06: $10** (Cloudflare's minimum is $10-50, not $5; cost $10.50 with the 5% fee, and a credit/debit card is required — PayPal is offered but refused). **The session must STOP after ONE paid image and ask for approval before continuing** — user's instruction, recorded in both the plan and the session prompt. Prompts in **`paid_test_prompts_safe.txt`** (filter-safe rewording plus two main-menu variants); the original warzone wording is kept in `paid_test_prompts.txt` to be tested on the free lane only. Session prompt ready in `docs/NEXT-SESSION-PROMPT.md` (archived locally in `old wip/`). **Run Phase 0 (free) first.** Afterwards: correct the honesty note in `changelog.md`, record measurements in `docs/findings.md`, and settle whether a blocked prompt is actually billed.
- [x] **First-time setup page (`setup.html`)** — deferred until AFTER the paid testing session by decision 2026-09-06, because that session settles the open API-token permission question and the page should state the right answer, not the ambiguous one. A tickable checklist that walks a new user through the whole Cloudflare setup in the ORDER THAT ACTUALLY WORKS (billing page → add card → AI Gateway credits → top up), which is the real pain: going to the credits page first bounces you around. Include the `promo/!cloudflare info/` screenshots as popups, plus permanent reference links to the Workers AI usage page (neuron stats) and the API token page. Opens from the Help area; `webbrowser` and the URL constants already exist in `core/providers/cloudflare.py`. Needs a `build_release.bat` copy line.
- [x] **`08 GAMES` expansion** — needs per-title research into camera and rendering conventions (isometric vs side-on, FOV, pixel vs low-poly). Four entries shipped; the 60-title list in `positives.txt` is a wishlist to be trimmed by hand first.
- [x] **Super Metroid pixel preset** — a dark atmospheric pixel mood, the opposite of the bright pixel presets. Identified as a genuine gap during the content pass.
- [x] **DreamShaper quality-risk probe — ROOT CAUSE FOUND AND FIXED 2026-09-04.** What looked like an aspect-ratio problem, then a green-content problem, then a size/tier problem, turned out to be a missing `guidance` (CFG) default: `core/providers/cloudflare.py` never sent one, so DreamShaper (an LCM model that wants ~1) rode Cloudflare's default meant for non-LCM SDXL. Fixed via a new `ModelSpec.default_guidance` field, set to 1.0 for dreamshaper. **Lightning, SDXL-base, and klein4b/9b were all measured too (not assumed safe or unsafe):** Lightning actually wants guidance~8 (corrected after first assuming "no preference" — guidance=1 looked over-sharpened on closer visual comparison); SDXL-base gets WORSE at guidance=1 (melted textures) and needed no override, since its default already lands in its working 3-8 range; klein4b/9b got `default_guidance=1.0` from Black Forest Labs' own guidance-distilled model card, confirmed harmless (no visible difference 1-8) by a local probe. Four models, four different stories — no blanket fix applied. 15/15 offline tests pass. Full story in `docs/dreamshaper-quality-probe.md` (archived locally in `old wip/`) and `docs/findings.md`.
- [x] **klein4b "free images per day" was undercounting by ~5.7x — FIXED 2026-09-04.** Found while investigating the guidance question above: the GUI derived the free-tier estimate from the $1.72/1000 price (which assumes Cloudflare's published 26.05 neurons/tile), but two independent measurements via Cloudflare's own GraphQL usage API (a 108-image real batch, and a fresh 6-image check, agreeing to within 0.1%) show the real rate is ~4.61 neurons/tile — about 361 free images/day at Standard 16:9, not the 63 previously shown. Added `ModelSpec.measured_neurons_per_tile`, wired into `Estimate.free_images_per_day`. GUI copy (model tooltip, cost calculator note, usage-link tooltip) and guide.md rewritten — they previously implied the neuron meter was broken for all paid models, which was true for the free SD models' 0-billing but had never actually been re-tested against klein.
- [x] **Preset dropdown polish pass** — all preset names switched from ALL CAPS to Title Case (group names too); `09 Artist` entries renamed to full name + `(Title of their most popular work)`; `08 Games` entries got a genre/graphics-style suffix e.g. `(Action/3D)`; Painterly and Comic promoted from seeded user presets to official `01 Main` built-ins, joined by a new `01 Main - Digital Anime 90s`; dropdown widened ~24%; the Advance-Wars-referencing tooltip rewritten; the dreamshaper green-outdoor-scene warning removed from the user-facing price note (still recorded in `docs/findings.md`) (2026-09-03)

## Phase 0 — Setup decisions ✅

All settled: architecture, ttkbootstrap, Python 3.13.1 environment, PyInstaller `--onedir`, custom teal/cyan theme with Segoe UI, `assets/icon.ico`. Rationale in [CLAUDE.md](CLAUDE.md).

## Phase 1 — Free provider validation (costs $0, do this first)

Model schemas and pricing are already verified (see CLAUDE.md). What's left is empirical checks that only a live account can answer.

- [x] ~~Resolve the Cloudflare aspect-ratio question~~ — **answered.** FLUX.2 models take `multipart/form-data` with `width`/`height` (256–1920) and support 16:9 natively. `flux-1-schnell` genuinely has no size params — fixed 1024x1024 square only, so it's demoted.
- [x] ~~Measure whether the `$0/step` models draw down the neuron budget~~ — **answered 2026-08-30.** 15 images across all three SD models billed **0 neurons**. They are the default lane. **But `totalNeurons` also reads 0 for klein-4b, which definitely bills — so the API cannot back a quota UI. Track spend client-side.** See `spike/SPIKE_RESULTS.md`.
- [x] ~~Create a Cloudflare API token + account ID~~ — **done.** Both persisted as user env vars (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`). All 5 in-scope models confirmed callable. **Gotcha: validate with `/accounts/{id}/tokens/verify`, NOT `/user/tokens/verify` — the latter 401s on a valid account token.**
- [x] ~~**Content-filter refusal**~~ — **ANSWERED; the spike's biggest finding.** It is *not* an error — blocked prompts return **HTTP 200 with an all-black image**. Must decode every image and treat flat-colour output as a permanent failure. Detector validated, zero false positives.
- [x] ~~Capture the real 429 shape~~ — **WON'T DO, by decision.** Deliberately exhausting a shared free tier risks the account for little gain. 429 handling is written *defensively* instead: honour `Retry-After` if present, else exponential backoff with jitter; treat as retry-with-patience, never a permanent fail.
- [x] ~~Verify real per-day throughput~~ — **moot for the free lane.** The 3 SD models bill 0 neurons, so there is no daily image cap to verify; the binding constraint is politeness/rate, not quota. Paid klein-4b throughput stays a *calculated* figure. Measured speed: lightning 1.6–3.0s, sdxl-base 3.1–5.1s, dreamshaper 3.6–4.7s, klein-4b ~4s (512x512).
- [x] Quality shootout on one identical prompt at 1280x720: SDXL-Lightning vs. dreamshaper-8-lcm vs. SDXL-base vs. flux-2-klein-4b. Judge **composited over a game screenshot**, not standalone. Use the 512 baseline to keep this iteration cheap.
- [x] ~~Try Pollinations, keyed and keyless~~ — **done 2026-08-31. Both work.** A key raises quota and shortens the gap between requests (15s → 1s) but does **not** lift the one-request-per-IP queue limit. `nologo=true` is sent, and no watermark was seen on any output. Measurements in [docs/findings.md](docs/findings.md).
- [x] Judge whether Pollinations output quality is good enough to be a real lane rather than a zero-setup fallback. Throughput is ~45s per image regardless of key, so it will never suit a large batch.

## Phase 1.5 — Decisions taken after the spike ✅

No live quota readout · CLI is a documented feature · test material chosen · sprite compositing is a separate session. Detail in [CLAUDE.md](CLAUDE.md) and [docs/findings.md](docs/findings.md).

## Phase 2 — Provider layer ✅

**Done — Session 2.** Provider interface, model capability registry, both Cloudflare request encodings (JSON + multipart), per-model response decoding, magic-byte sniffing, blank-image guard, size/tier selector, cost calculator, Pollinations, politeness layer, timeouts, seed handling. See [docs/session-log.md](docs/session-log.md).

- [-] Free-budget tracking with persistence across runs; warn before the daily allowance runs out and make "resume tomorrow after 00:00 UTC reset" a natural workflow rather than a wall of failures.
- [-] fal.ai / Together / Replicate: **deferred.** fal does not publish per-model pricing for its wider catalogue, so a cost estimator cannot be built against it. Revisit only if Cloudflare proves insufficient.

## Phase 3 — Batch engine ✅

**Done — Session 2.** SQLite job store, prompt loader, deterministic filenames, sidecar metadata, worker pool, retry taxonomy with backoff, immediate download, resume, overwrite protection, dry-run. See [docs/session-log.md](docs/session-log.md).

## Phase 4 — GUI (ttkbootstrap, per house standard) ✅

**Done — Sessions 3, 3b, 3c, 3d.** Custom teal/cyan theme, three tabs, live cost calculator, credential entry via `credentials.json`, dry-run, pause/resume/cancel/retry, format selector, politeness controls. Structure: `main.py`, `gui/app.py`, `gui/theme.py`, `gui/tabs/`, `gui/scroll.py`, `gui/tooltip.py`, `utils/`.

Two follow-up rounds of hands-on feedback are folded in. See [docs/session-log.md](docs/session-log.md) for what changed and [docs/findings.md](docs/findings.md) for the ttkbootstrap pitfalls worth remembering.

## Phase 5 — Commander Wars mods ✅

**Moved out of this project.** The mods consume this tool's output and now live in their own project, `C:\ClaudeWorkspace\Commander Wars Developer`.

## Phase 6 — Release ✅

**Done — Session 5.** All three phases of `RC prompt to make releases easier.md` are complete: `guide.md`, `promo.md`, `readme.md`, the 630x500 itch thumbnail and 1280x720 cover, `build_release.bat`, and the project cleanup. Verified: tests 11/11, GUI opens maximized, and the packaged `dist/` folder runs from a clean directory with no credentials picked up. Development artifacts moved to `old wip/`; `CLAUDE.md` rewritten for post-release maintenance. See [docs/session-log.md](docs/session-log.md).

Remaining before upload — **user's call, not blockers:**

- [x] Delete `credentials.json` and `config.json` from the project root before publishing anything (they are gitignored, and `build_release.bat` refuses to ship them — this is just belt-and-braces).
- [x] Zip `dist/Batch AI Image Generator/` and upload to itch.io, using the copy in [promo.md](promo.md).
- [x] **Re-render the promo images — DONE 2026-09-05.** The misleading "Free" tag is gone: the thumbnail badge now reads **13 MODELS** and the cover bullet reads **"13 models — free and paid"**, both claims about the product rather than its price. The generator is now **`make_promo_images.py` in the repo** — the original lived in a scratch folder and was lost, which turned a one-word text change into rewriting the whole script. The copy lives in constants at the top of that file.
- [x] **Verify each subreddit's rules before posting.** Reddit was unreachable from the machine `promo.md` was written on, so those recommendations are unverified — this is flagged at the top of that file.
- [x] Upload the v2.2 build to itch.io.
- [ ] Record the YouTube trailer and walkthrough — **after v2.3 ships**. Shot plans in [docs/video-plan.md](docs/video-plan.md).

## v2.3 — Cloudflare model deprecation (2026-11-20)

Cloudflare retires models on **2026-11-20**: [changelog post](https://developers.cloudflare.com/changelog/post/2026-11-05-planned-model-deprecations/). After that date they return `410 Gone`, error code `5028`. **All three free SD models are on the list**: `stable-diffusion-xl-lightning` (**the current default**), `stable-diffusion-xl-base-1.0` and `dreamshaper-8-lcm`. Cloudflare suggests `flux-2-klein-9b` as the replacement. klein 4B, both Pollinations models and all eight gateway models are unaffected. Lineup goes 13 → 10.

- [ ] Wait for the date and confirm the 410 / 5028 with a free probe, in case Cloudflare moves the date again (it already slipped once, from 11-15).
- [ ] Choose the new default model. Cloudflare suggests klein 9B (~7 free/day); klein 4B (~75 free/day) is likely the better default.
- [ ] Remove the three from `core/models.py`, and handle a saved `config.json` that still names one, so an existing user doesn't start up on a dead model.
- [ ] Decide whether a 410 / 5028 gets its own permanent "model retired" failure rather than a generic error.
- [ ] Re-check everything that leaned on the SD models: the SD-only `SIZE_TABLE_OVERRIDES`, the 77-token prompt-length story, negative-prompt support, the `max_safe_dimension` warning, and the tests that pin them.
- [ ] Rewrite the "free" pitch everywhere: `guide.md`, `readme.md`, the two setup tutorial HTML pages, `promo.md`, the promo images (`13 MODELS` → `make_promo_images.py`) and `CLAUDE.md`. Free is now klein 4B's daily allowance + Pollinations, not "three models bill nothing".
- [ ] Changelog entry + devlog, rebuild, upload.

## Blocked on Cloudflare

- [x] **Unified billing: use AI Gateway credit for the native Cloudflare models.** Fully specified in [docs/unified-billing-todo.md](docs/unified-billing-todo.md); **not built on purpose.** `flux-2-klein-4b` requires multipart and the gateway path rejects multipart (`7000`), so the feature currently reaches only the three JSON models — and measurably makes those three *cost money*, since "free" belongs to the neuron path rather than the model. Reported upstream 2026-09-09 (forum, Discord, `cloudflare-docs` issue). **Re-test with `python tools/probe_unified_billing.py`** (free; prints STILL BROKEN / FIXED). Do not start this without running it first. Last checked 2026-09-12 — still broken.

## Later / optional

- [x] ~~Additional providers if quality demands~~ — **CLOSED by decision 2026-08-31.** The existing five-model Cloudflare lineup plus Pollinations is enough, and most of it is free. The genuinely better generators are priced far above what is comfortable for batch work; for one-off high-quality images the answer is a free arena site, not another paid integration here. fal.ai / Together / Replicate are dropped rather than deferred.
- [x] ~~In-app prompt template expansion (`[biome]` × `[time]` combinatorics)~~ — **CUT by decision 2026-08-31.** Too niche and too specific to belong in this program; the brainstorm's own argument against it won. The need is real but becomes its own project, **Omni Prompt Builder** — a dedicated tool shipping curated wildcard `.txt` lists that generate exactly the prompt files this program consumes. Brainstorm kept at [docs/prompt-builder-ideas.md](docs/prompt-builder-ideas.md) as input to that project.
- [x] A styling-brainstorm session for menu vs. far-background art, using the inspo folders (see the "blurry" note in CLAUDE.md).
