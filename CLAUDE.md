# CLAUDE.md — Batch AI Image Generator

## Start here

The program is **released and feature-complete**. This file is the maintenance context: what the thing is, how it's built, which facts were measured rather than assumed, and what is deliberately out of scope.

Two other files carry detail:

- **[docs/findings.md](docs/findings.md)** — measured facts: prices, model behaviour, API quirks, ttkbootstrap pitfalls. **Read this before changing provider, pricing, or layout code.** Several entries contradict the official documentation, and the measurement is the one that's right.
- **[docs/session-log.md](docs/session-log.md)** — chronological development history. Rarely needed now; useful when you want to know *why* something ended up a particular way.

**[TODO.md](TODO.md)** holds what is still open. Everything for the program itself is done.

## What this program is

A batch AI image generation desktop app. Feed it a `.txt` file with one prompt per line, it appends a configurable style suffix to each, sends them to a cloud image API, and downloads the results into a chosen folder with sidecar metadata. Resumable, concurrent, cost-aware.

It is a **general-purpose tool**. It was originally built to produce background art for Commander Wars mods, but that work now lives in its own project (`C:\ClaudeWorkspace\Commander Wars Developer`) and nothing about this program is coupled to that game. Keep it that way.

Cloud APIs rather than local generation because the target machine has 4 GB of VRAM — not enough for good local image models. That constraint is also a selling point: it runs on hardware that can't run ComfyUI.

**Budget:** free tiers are the default and paid options are an opt-in quality upgrade.

**AMENDED 2026-09-05, then SUPERSEDED the same day.** The **$5 per 1000** figure began as an absolute scope limit — anything pricier was out of scope entirely — and was then relaxed to govern only the `$` tier and the default model choice. It has since been **replaced outright as the governing vocabulary** by a five-band cost scale, because a project-internal "ceiling" and "tolerance" meant nothing to a user and could not carry a 10x price range in one sentence.

**The bands are the vocabulary now.** They are stated in plain money, and the bounds are **inclusive**, so a model sitting exactly on a round number lands in the cheaper band (p-image at exactly $5.00 is LOW COST — a boundary that punishes a model for sitting on it reads as a bug to anyone who checks the arithmetic).

| Band | Marker | Per 1000 images | Models |
|---|---|---|---|
| **FREE (Neurons)** | *(none)* | $0 | 3 SD + both Pollinations |
| **LOW COST** | **`$`** | ≤ $5 | klein-4B $1.72, p-image $5.00 |
| **MEDIUM COST** | **`$$`** | ≤ $20 | klein-9B $16.94, Krea Turbo $15 |
| **HIGH COST** | **`$$$`** | ≤ $50 | Krea Medium, flux-2-pro, both Recraft, nano-Lite |
| **EXTREME COST** | **`$$$$`** | > $50 | nano-banana-2 ($67/$101/$151) |

`COST_BAND_LIMITS` in `core/models.py` is the **only** place a threshold is written; labels, markers and ttk styles all derive from `cost_band()`. Before this, the marker and the over-budget warning were computed separately and could describe different things. **The marker now has four levels, so `$$$` means HIGH rather than "the most expensive"** — six tests encoded the old three-band scheme and were updated. **The calculator grades the SELECTED size, not the reference size**, because on nano-banana-2 the tier moves the price across bands. **LOW and FREE print no warning line at all**: repeating "LOW COST" as a warning trains users to ignore the line that matters.

`BUDGET_CEILING_PER_1000` still exists in `core/models.py` and still feeds the legacy `Estimate.over_budget` flag, but it is **no longer the user-facing vocabulary** and no GUI or CLI copy is keyed on it. `test_no_source_file_still_uses_the_old_budget_vocabulary` scans the source to stop the old wording reappearing — five separate sites had each written their own version of that sentence, which is why a scan rather than a fix was the answer.

This is a **recorded decision, not an oversight**. Do not "fix" it back to a hard ceiling, and do not reintroduce "ceiling" or "tolerance" into anything a user reads. Tracked in [docs/gateway-models-todo.md](docs/gateway-models-todo.md) and [docs/ui-sanity-pass-plan.md](docs/ui-sanity-pass-plan.md).

## Repository layout

```
main.py                          Entry point (GUI)
cli.py                           Command-line front end onto the same engine — a documented feature
build_release.bat                Produces dist/<name>/ ready to zip
core/                            models · providers/ · engine · db · prompts · imagecheck
core/recipes.py                  Parses recipes.md for the Helpers tab — that doc's FORMAT is load-bearing
core/reference.py                Style reference image: the WHOLE decision layer. GUI/CLI/engine render it, never decide
gui/                             app · theme · scroll · tooltip · tabs/ (prompts, provider, run, helpers)
utils/                           config.py (settings) · credentials.py (API keys)
tests/test_engine.py             Offline suite — 105/105, no network required
assets/                          icon.ico (multi-size) + icon og (2).jpg (1024x1024 master)
docs/findings.md                 Measured facts — read before touching providers/pricing/layout
docs/session-log.md              Development history
docs/prompt-builder-ideas.md     Input to a SEPARATE project (Omni Prompt Builder), not this one
docs/*-plan.md, *-todo.md        Design write-ups for finished features — cited from this file for the why
guide.md                         User guide. The GUI's Help button opens it — must ship beside the exe
recipes.md                       LLM prompt recipes. PARSED AT RUNTIME by the Helpers tab — must ship beside the exe
readme.md                        Public overview + licence
promo.md                         Store copy, marketing plan, launch copypastas. DEV-ONLY — never shipped
changelog.md                     Public release notes, written for laypeople. Ships beside the exe
promo/                           3 screenshots + 630x500 thumbnail + 1280x720 cover
make_promo_images.py             Regenerates the two store images. Edit the text constants at its top
make_model_collage.py            Regenerates promo/model_comparison.jpg from a collage batch; prices come from core/models.py
wildcard prompt maker/           Small standalone wildcard-to-prompt-file GUI. Kept in the repo, never built or shipped
tools/                           One-off maintenance probes. probe_unified_billing.py re-tests the klein gateway bug
test_prompts.txt                 Example prompt file (ships as example_prompts.txt)
test_style_prompt_addon.txt      Example style suffix (ships as example_style_suffix.txt)
old wip/                         Superseded development artifacts + house standards. Gitignored, local only. Don't mine it for truth.
```

`credentials.json` and `config.json` live beside the program at runtime and are gitignored. **They must never end up in a release zip** — `build_release.bat` checks for them and aborts if they appear.

## Architecture

**Provider abstraction, one app.** The interface is tiny (prompt + size → image bytes), so separate apps per provider would have duplicated the whole batch/resume/UI layer for nothing.

**SQLite for job state**, in `.batchgen.db` inside the output folder. This is what makes crash-resume and concurrent status updates correct rather than fragile.

**`core/models.py` is the single source of truth** for every model's dimensions, encoding, price, licence and delivered format. Nothing about a model is hardcoded anywhere else. Change it there or not at all.

**Stdlib `logging`.** No custom framework.

**Credentials:** entered in the GUI, saved to `credentials.json` beside the program (gitignored, `icacls`-restricted to the current user). Environment variables (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `POLLINATIONS_API_KEY`) are still read and **take priority**, so scripted setups keep working — they're simply not what a new user is told to configure. No encryption: encrypting a local key with a local key solves nothing. Keys never touch `config.json`, the job database, or image metadata.

**Politeness is a requirement, not a setting.** Default concurrency 2, a deliberate one-second inter-request delay, strict 429 backoff honouring `Retry-After`. Free tiers are a courtesy. Providers declare `max_concurrency` and the engine clamps to it.

## Measured provider facts

These were established empirically. Where they contradict the vendor documentation, **the measurement is correct** — several of these cost real debugging time to find.

### The five Cloudflare models (scope is locked)

| Model | Encoding | $/1000 @ Standard 16:9 | Role |
|---|---|---|---|
| `@cf/bytedance/stable-diffusion-xl-lightning` | JSON | **$0** | **Default.** 8-step distilled, 1.6–3.0s |
| `@cf/stabilityai/stable-diffusion-xl-base-1.0` | JSON | **$0** | Free, slower (20 steps), 3.1–5.1s |
| `@cf/lykon/dreamshaper-8-lcm` | JSON | **$0** | Free, LCM-fast, photoreal-leaning |
| `@cf/black-forest-labs/flux-2-klein-4b` | **multipart** | **$1.72** | **Best per-dollar.** **~75 free images/day** — free for most batches |
| `@cf/black-forest-labs/flux-2-klein-9b` | **multipart** | ~$17 | Over budget — offered, never default. **~7 free images/day** |

Plus the **AI Gateway** models (see below). All eight ship; the tier column below uses the five-band scale from the top of this file:

| Model | $/1000 | Tier | Note |
|---|---|---|---|
| `pruna/p-image` | $5.00 | `$` | Flat. Caps at 1440px, so 16:9 is 1280x720. Auto prompt enhancement. |
| `krea/krea-2-medium-turbo` | $15.00 | `$$` | Flat. Expressive/illustration. Locked to 1K — **no tier ladder at all**. |
| `krea/krea-2-medium` | $30.00 | `$$` | Flat. Double turbo's price for a marginal gain; pick it for batch consistency. |
| `black-forest-labs/flux-2-pro-preview` | $30.00 | `$$` | Flat. **True pixels** (min 64, no x16 rule), so the shared `SIZES` table maps on with no override and a full tier ladder — the only gateway model for which that is true. Bought for `safety_tolerance`, not Elo (1207, below the cheaper Krea Turbo). |
| `recraft/recraftv4-1-utility` | $35.00 | `$$` | Flat. Opaque `size` **enum** of `WxH` strings — rejects `aspect_ratio` and width/height alike. One fixed size per ratio, **no tier ladder**, and **no seed at all**. Its 16:9 is 1344x768, *smaller* than Standard. Elo 1218, matching Recraft's own $210/1000 Pro tier. |
| `recraft/recraftv4-1` | $35.00 | `$$` | Flat. Field list, size enum and response shape **confirmed identical** to Utility, so the pair shares one `_RECRAFT_COMMON`. **Not the upgrade:** same price, same fixed sizes, and a *lower* Elo (1198). Pick it for art direction — high aesthetics, composition, text rendering — not for score. |
| `google/nano-banana-2-lite` | $34.00 @ 1K | `$$` | **The only family where resolution is a real price lever** — but Lite is **pinned to 1K**, see below. Elo 1290, the best score per dollar on the paid lineup. Published sizes (16:9 → 1344x768), though **MEASURED 2026-09-06 the service actually returns 1376x768** — see findings. No image is lost; the sidecar records what arrived. No seed. `output_format` is spelled **`jpg`**, not `jpeg`. |
| `google/nano-banana-2` | **$67 / $101 / $151** @ 1K / 2K / 4K | `$$$$` | **The ONLY model where the quality tier changes the bill** — Draft/Standard/High map to 1K/2K/4K, and a High batch costs 2.25x a Draft one. Elo 1320, the highest here; EXTREME COST at every tier, so the `$$$$` marker is fixed. No seed. Grounding fields deliberately not sent — see below. |

**The gateway lineup is COMPLETE at eight models.** All eight ship; nothing further is planned. Do not add providers, and do not add models without a decision.

Plus **Pollinations** (keyless, two models) as a zero-setup secondary lane.

**The three SD models genuinely bill nothing.** 15 images across all three billed 0 neurons, with step counts recorded accurately — so telemetry was working, it simply charged nothing.

**But the API's neuron counter cannot back a quota UI.** In the same test, `flux-2-klein-4b` — which definitively bills $1.72/1000 — *also* reported 0 neurons. A billed model reading zero means `totalNeurons` is not a dependable meter for image models. **Spend is tracked client-side** from the model and tile count the app already knows, and "images remaining today" is labelled an *estimate* everywhere it appears. Never present it as measured.

### Two request encodings, not interchangeable

- **JSON body** — the three SD models. Params: `prompt`, `negative_prompt`, `width`, `height` (256–2048), `num_steps` (max 20), `guidance`, `seed`.
- **multipart/form-data** — both klein models. Fields: `prompt`, `width`, `height` (256–1920), `guidance`, `seed`, `input_image_0..3`. **`steps` is fixed at 4 and cannot be set** (distilled). Dimensions must be **multiples of 16**.

### Response encoding and format both lie

- **SD-family** return **raw image bytes** in the HTTP body. **klein** models return **base64** inside a JSON envelope at `result.image`.
- The declared `content-type` is unreliable. Measured delivered formats: lightning declares `image/png` and sends **JPEG**; sdxl-base and dreamshaper send real PNG; both klein models and both Pollinations models send JPEG.
- **Sniff magic bytes** (`89504e47` = PNG, `ffd8` = JPEG) to pick the extension. Never trust the header, never hardcode `.png`. Recorded as `ModelSpec.output_format` and surfaced in the model dropdown.

### The content filter returns HTTP 200 and a black image

Blocked prompts come back as `200 OK` with a byte-identical all-black frame. No error field, no distinct status code. **A batch with no content check would save hundreds of black images and report 100% success.** Every downloaded image is decoded and rejected if it is a single flat colour — as a **permanent** failure, never retried, because retrying identical text produces the same refusal. Detector validated with zero false positives.

This is the single most important behaviour in the program. Do not weaken it.

### Sizes: cost is a step function

Cloudflare bills per **512x512 tile**, so any size inside the same tile count costs exactly the same. The naive picks waste that headroom badly. Every size in `SIZES` is the **largest exact-ratio, multiple-of-16 size that still fits its tile count**.

| Ratio | Draft (2 tiles) | **Standard (6 tiles)** | High (12 tiles) |
|---|---|---|---|
| **16:9** | 768x432 | **1536x864** | 2048x1152 |
| 3:2 | 768x512 | 1536x1024 | 2016x1344 |
| 1:1 | 512x512 *(1t)* | 1024x1024 *(4t)* | 1536x1536 *(9t)* |
| 2:3 | 512x768 | 1024x1536 | 1344x2016 |
| 9:16 | 432x768 | 864x1536 | 1152x2048 |

At Standard, 16:9 is **1536x864 — 44% more pixels than 1280x720 for the same price.** The documented workflow is generate large, downscale locally.

**High tier is klein-only.** SDXL and dreamshaper are trained at ~1024 and degrade above it (duplicated structures, geometry drift, edge artifacts), so the UI warns. **CHANGED 2026-09-06: the three SD models now own a `SIZE_TABLE_OVERRIDES` entry so their DEFAULT no longer exceeds that limit** — Standard 16:9 is **1024x576**, not 1536x864. Previously the shipped default produced the artifacts and the program merely warned about a setting the user had never chosen. High still reaches past the limit on purpose, and still warns; the tier dropdown is the opt-in. A global "allow unsafe resolutions" toggle was rejected — the correct value depends on the selected model, so it would only ever be right for a subset. FLUX.2 klein is natively specified to 4 MP and handles it — verified by side-by-side test at seed 4242: no duplication, no drift, no artifacts. The cost is time, not money: 16.1s vs 9.8s per image, **64% slower**, which matters more than the $2.29-vs-$1.72 price on an overnight batch.

**klein's hard ceiling is 1920, below the tabled High sizes**, so `SIZES_KLEIN_HIGH` substitutes legal sizes automatically (16:9 → 1792x1008, etc.). Without it, 16:9 High would be servable by no model at all — SD renders it badly and klein rejects it outright. 1:1 deliberately keeps 1536x1536, because the largest legal square is 16 tiles against 9 and would genuinely cost more.

**klein-9b bills per megapixel**, not per tile — the one model where a bigger tier genuinely costs more.

### Pollinations

Keyless and working. **Exactly ONE request per IP is queued** — `"Queue full for IP: ...: 1 requests already queued (max: 1)"` — so any concurrency above 1 produces only 429s that burn each job's retry budget. **An API key does NOT lift this**; it raises quota and shortens the inter-request gap (15s → 1s) only. `max_concurrency` is 1 in both modes. Throughput is ~15-45s per image regardless, so it will never suit a large batch.

Beware cached responses when probing this: a repeated prompt+seed returns in under a second and can make a concurrent burst look successful.

**Pollinations also CLAMPS silently to ~0.59 MP, and that was a correctness bug, not a cosmetic one.** Measured 2026-09-05 with cache-defeating prompts on both models: anything above **589,824 px** is scaled down with the aspect ratio preserved, returned as **HTTP 200 with no error and no warning**. 1536x864 came back as 1024x576; 1024x1024 as 768x768. `max_dimension=2048` on both specs was wrong by ~3.5x and is now 1024, and `SIZES_POLLINATIONS` (a `SIZE_TABLE_OVERRIDES` entry, computed against the cap then verified live) means the program only ever requests sizes the service will actually deliver — 16:9 Standard is **1024x576**, not the 1536x864 the shared table gives.

The second half of the bug was the record: `GenerationResult` is built from the REQUESTED size, so a clamped image was written into its sidecar at the size that was asked for. The sidecar now carries **`size_mismatch`** stating outright whether the provider resized the image — rather than leaving `width`/`height` and `actual_dimensions` to be compared by a reader who never does — and the engine logs a warning when they differ.

**This is the same failure SHAPE as the black-image content filter**: HTTP 200, no error, wrong result, and a batch that reports 100% success. Standing rule — **trust the bytes, not the response.** No auto-cropping was added: ratios are honoured, so cropping would discard pixels to fix a problem that does not exist.

### Auth

**Endpoint:** `https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/{MODEL_NAME}`, `Authorization: Bearer {API_TOKEN}`.

**A READ-ONLY token is sufficient** — the dashboard's **"Read all resources"** template, verified against both the free JSON path and the paid multipart path. This is what `guide.md` recommends: easier to explain and harmless if leaked. The program only reads; `ai/run` is a POST but it is *inference*, creating no resource and changing no setting.

> **Gotcha:** validate with `/accounts/{id}/tokens/verify`, **not** `/user/tokens/verify` — the latter 401s on a perfectly valid account token. `verify` returns only `{id, status}`, so token grants cannot be checked programmatically.

Two secrets are required, not one: **account ID and API token**.

### Prompt length is per-model, and truncation is silent

Every model drops whatever runs past its text encoder's limit with **no error and no sign in the image**. The budgets differ by roughly 7x: the SD models use CLIP (77 tokens, ~300 characters), klein uses a 512-token encoder (~2000 characters). This is the measured reason long descriptive prompts pay off on klein and are wasted on SD — the SD models are never shown the detail.

**Positive and negative prompts have separate budgets** — CFG encodes them in separate passes, so a heavy negative costs the scene description nothing. This is why negative presets are **stackable layers** (checkboxes, composed with duplicates dropped) rather than alternatives: stacking is cheap, so the only question is whether a layer is relevant. Terms are left out for being inert, never for being expensive.

**But stacking is only free against the *positive* budget, not the negative's own.** One built-in layer is ~283 characters, so on SD roughly **one layer fits** — two typical layers already overflow and the tail is silently dropped. The GUI's existing counter grades the composed text against the model's limits and already covers this; the practical consequence is that **layer order matters on SD**, since layers compose in list order. Dedup saves tens of characters, not hundreds (only 12 terms overlap across all 20 layers), and must never be relied on to fit a stack inside a budget.

Style presets stay **flat strings** — no core/extended split, no metadata. Both were considered and cut: the user already controls prompt length, and a split would break plain copy-paste out of the program.

**Preset names carry the ordering.** Built-ins are named `NN GROUP - NAME` (`01 MAIN - DIGITAL ART`), because the dropdown is ordered by a plain `sorted()` on the keys — the name *is* the sort key. Two digits, so it survives past nine groups. User presets sort above all built-ins, enforced by `_preset_names()` partitioning on membership in `BUILTIN_PRESETS` rather than trusting the `*` prefix the Save As dialog suggests. `*Painterly` and `*Comic` (the two originals) ship as **seeded user presets**, not built-ins — they demonstrate the convention at the top of the list. Full scheme and roster: [docs/preset-naming-scheme.md](docs/preset-naming-scheme.md).

**Style presets are style ONLY — no subject matter.** A style block containing "ancient ruins" puts ruins in every image of the batch, and it is easy to miss when reading a preset rather than running it. The deliberate exceptions are groups `06 COOL` and `07 BEAUTY`, where imposing the framing *is* the product: a batch usually has one idea behind it, so the preset does the heavy lifting and the prompt file carries only the varying part. Every other group binds strictly.

Presets carry **no attention-weighting syntax** (`(term:1.2)`, `((term))`), **no embedding filenames** (`verybadimagenegative_v1.3`) and **no Pony tag conventions** (`score_6`, `source_pony`). All three are inert on this lineup — the APIs encode them as literal text — and the source material was full of them.

Limits live in `ModelSpec.prompt_soft_limit` / `prompt_hard_limit` and drive soft ok/near/over counters in the GUI. **Nothing truncates a prompt** — characters are a proxy for tokens, keyword lists tokenize worse than prose, and cutting a user's text would repeat the API's own fault one layer earlier. See `docs/findings.md`.

### Licensing

Cloudflare treats prompts and outputs as your Customer Content — you own the images and may use them commercially. But Cloudflare neither trains nor licenses the models, so each carries its own:

- `flux-2-klein-4b` — **Apache 2.0**, no restrictions. The safest paid choice.
- `flux-2-klein-9b` — FLUX **Non-Commercial**, which restricts *serving the model*, not the outputs. Generating via Cloudflare's hosted endpoint and using the images commercially is fine.
- SD-family — SD/OpenRAIL-style, commercial output use permitted.

The program is a client calling a hosted API and never redistributes weights, so none of these constrain the tool itself.

## Cloudflare AI Gateway models (added from 2026-09-05)

A second class of Cloudflare model, reached through the **AI Gateway**. Same endpoint, same token, same account — but different in four ways that each broke an assumption baked into the original five:

| | Native (the original 5) | Gateway |
|---|---|---|
| **Addressing** | model id in the **URL path** | model id in the **request body** at bare `/ai/run` |
| **Billing** | per 512x512 **tile** | **flat per image** (or per resolution tier) |
| **Paid from** | daily free **neuron allowance** | **prepaid credit** — no free quota at all |
| **Validation errors** | code **5006** | code **7003**; `402` = no credit |

Consequences worth knowing before touching this code:

- **`ModelSpec.bills_per_tile` gates every tile readout.** A tile count beside a flat-priced model is a meaningless number that implies the "generate large, downscale locally" headroom these models do not have. Suppressed in the GUI, `cli estimate` and `cli dry-run`.
- **`free_images_per_day` returns `None` for two different reasons** — a free model, or a paid gateway model with no neuron allowance. They must not print the same text. The original code assumed only the first and said "free model — no neuron cost" for a paid model; fixed, and now three distinct branches.
- **`result.image` carries several incompatible shapes at the same field path, and it is nested deeper than the docs say.** klein returns **bare base64**; krea, flux-2-pro and — **measured 2026-09-06** — **p-image** all return a **presigned URL** needing a second GET. (The docs said p-image returned a `data:` URI; it does not. That handling stays, since a data URI decoded as bare base64 yields *garbage, not an error*.) The live envelope is **`{"result": {"state": ..., "result": {"image": ...}}}`** — both fields sit *inside* `result`, so `_extract_image` **walks the chain** rather than assuming a depth. Reading a fixed depth returned `None` on a valid, already-billed response and the retries that followed **bought four copies of one image**. Detection is driven by the content, never by the declared encoding — which is the only reason the wrong p-image spec cost nothing.
- **A retry on a PAID model is a new charge, not a recovery.** The image is generated and billed before the response arrives, so `PAID_MAX_ATTEMPTS = 1` — one try, no retry — and an unreadable 200 fails **permanently** there while staying transient on a free model. **429s are exempt**: they are refused before generating, so they cost nothing and must still back off normally. The presigned-URL *fetch* also stays transient, being the one case where retrying recovers something already paid for. Free lane is 3 attempts.
- **The presigned fetch must never carry the `Authorization` header** — the URL is already signed, and forwarding the token to that host would leak the credential. And every fetch failure is **transient**: the image was generated and billed before the URL was handed over, so retrying is the only way to recover something already paid for.
- **Gateway responses carry a `state` field** the native models lack. Only `"Completed"` is documented; anything else is treated as transient rather than assumed successful.
- **`SIZE_TABLE_OVERRIDES` lets a model own its whole size table**, not just substitute at High. p-image needs this: it caps at 1440 *and* requires multiples of 16, so its best 16:9 is **1280x720 — smaller than the program's Standard 1536x864**. Recraft needs it too, for a different reason: its sizes are an opaque published enum rather than anything computable.
- **Recraft is the ONE model whose bad request is not free, and that is the main thing to get right about it.** Every other gateway model's field list was verified at zero cost precisely because the gateway rejects a malformed body *before* charging. Recraft's gateway type-checks only that `size` is a **string** and defers the value check to Recraft, so a bad size gets past, is **billed**, and then fails at generation time. `size` is therefore validated client-side by `recraft_size_string()` — the only legal source of the value — and `validate_size()` routes enum models through it as well, so the GUI readout and `cli dry-run` refuse a bad size too. A min/max check is **not** sufficient: an enum model's legal sizes are a *set*, and `1024x768` sits inside Recraft's 768–1344 bounds while still being illegal.
- **A `size_enum` model MUST own a `SIZE_TABLE_OVERRIDES` entry.** Without one, `size_for()` falls back to the shared `SIZES` table and yields 1536x864 at Standard 16:9 — not a legal Recraft size. This actually happened while adding the second model of the pair. It matters here and nowhere else because a shared fallback is safe only where a wrong answer is rejected cheaply, and on this family it is **billed and then refused**. Pinned by `test_every_size_enum_model_owns_a_size_table`.
- **The resolution tier is a REAL price lever on exactly one family, and the price machinery must follow it.** Every other gateway model is flat per image, so `_flat_per_image()` covers them; nano-banana bills `$67 / $101 / $151` per 1000 at 1K / 2K / 4K, where a 4K image costs 2.3x a 1K one. `_per_resolution()` recovers the tier from the pixel size and drives the GUI readout, `cli estimate` and `cli dry-run` alike. An unrecognised size falls back to the **dearest** price, never the cheapest: if the estimate has to be wrong it must not be wrong in the direction that surprises the user with a bill.
- **`nano-banana-2-lite` is PINNED TO 1K, and that is a recorded decision.** Cloudflare's schema declares `1K|2K|4K`, but OpenRouter, fal.ai and a published pricing breakdown all say Lite renders 1K only — and Google publishes **no 2K or 4K rate for Lite**. The unpriceability is what settles it: this program's contract is that a batch can be quoted before it runs, so an unpriceable resolution is not one to send. `nano_banana_resolution()` looks the value up per model rather than deriving it from the tier name, because the two models in the family do not agree. Do not "fix" this to the full ladder without real published prices.
- **Key a user-facing explanation on the FACT it asserts, not on a field that happens to correlate.** Two strings keyed on `size_style` have now been wrong for a second model: the "locked to 1K" disabled-tier reason (fixed when Recraft arrived) and the `~ estimated` size readout (fixed when nano-banana arrived, which speaks krea's exact size vocabulary but has *published* dimensions). The second is now keyed on `ModelSpec.sizes_published`, which asks the real question. **Check these by launching the GUI, not by reading the code.** **MEASURED 2026-09-06: `sizes_published` is itself now known to overpromise** — both nano-banana models return 1376x768 rather than Google's published 1344x768, converging on the same size the "estimated" krea pair returns. The flag still correctly describes *where the number came from*, which is what the readout claims, so it stays; but a published size is a request, not a promise, and only the decoded bytes settle it.
- **Ask whether a default is UNKNOWN, not just whether it is non-neutral.** nano-banana's `output_format` has no published default anywhere — weaker ground than flux-2-pro's documented `jpeg`. Sent explicitly all the same: an unknown default cannot be assumed neutral. It is also the only family where the program *asks* for a format, which makes the magic-byte sniff matter more rather than less.
- **Grounding is NOT exposed on nano-banana-2, and the reason is billing rather than scope.** `google_search` and `image_search` are Google Search grounding — the model searches before generating to ground the image in real-world fact. They are **billed separately at $14 per 1000 search queries** after 5000 free per *month*, and Google's docs state plainly that one prompt may trigger several billable queries. Through a pass-through gateway, against an allowance the program cannot see, that is unpriceable by construction, and it would break the cost estimate on the most expensive model in the lineup. **This is a cost decision and is revisitable** if the per-query charge ever becomes visible to the client — unlike the reference-image skips, which are permanent. (`image_search` is *also* img2img-shaped, so it is doubly excluded.)
- **A model's safe-size ceiling is per-model, and a warning that cries wolf is worse than no warning.** The shared `max_safe_dimension` of 1024px encodes SD's degradation above its training size. nano-banana-2 renders 5376x3072 natively, so firing that warning there would be flatly wrong — and would teach users to ignore it on the SD models where it is real. Set per model; pinned by a test that also asserts the SD warning survives.
- **The over-budget warning became the FIVE-BAND cost scale** (see the table near the top of this file). Every paid model used to get the identical line, at $15 and at $151 alike, phrased in a project-internal budget vocabulary the user had never heard of. The dearest band now leads with the **batch total** and the image count rather than the per-1000 rate — "$151 per 1000" reads as abstract where "this batch of 500 costs $75.50" does not. GUI, `cli estimate` and `cli dry-run` all follow it.
- **A seed that was never sent must not be recorded.** Recraft accepts no `seed` field, so reproducibility is impossible there by any means — a stronger statement than "the control is greyed out", and the GUI says it in those terms. `_finish` records `seed=None` whenever `supports_seed` is False; writing the engine's unused generated number into the sidecar would promise a reproducibility that does not exist. nano-banana is also seedless and got the same treatment (2026-09-05), verified rather than re-implemented.

**The x16 rule binds harder than the pixel cap.** p-image's 16:9 is 1280x720, not 1440x810, because 810 is not a multiple of 16. A first draft of that table had it wrong; a three-line check caught it. **Compute these tables, never eyeball them.**

**The field lists were verified at zero cost** and must not be re-derived: the gateway validates a request *before* charging, so a malformed request returns 400 naming every legal field, and a well-formed one returns 402 — proof the shape is right without generating anything.

### Prompt expansion, and the reference-image fields

### The content filter is adjustable on exactly two models

A refused prompt on the native lineup returns HTTP 200 and a black frame, which the program marks `BLOCKED` permanently. Until 2026-09-05 the user had no way to *respond* to a refusal they thought was spurious. Two gateway models expose a lever, and they disagree about how:

| Model | Field | Type | "Loosen it" |
|---|---|---|---|
| `pruna/p-image` | `disable_safety_checker` | boolean | `true` |
| `black-forest-labs/flux-2-pro-preview` | `safety_tolerance` | integer 0–5 | **`5`** |

**`safety_tolerance` runs 0 = STRICTEST to 5 = MOST PERMISSIVE** (API default 2). The direction reads backwards from what the name suggests, and inverting it makes the filter maximally aggressive while looking like the model simply being difficult. Confirmed from Cloudflare's published schema; **doc-derived, not measured**, and pinned by `SAFETY_TOLERANCE_*` constants plus a test that exists only to stop a later edit flipping it.

Both are driven by **one** program setting (`default` / `permissive` / `off`), mapped per model by `filter_value_for()` in `core/models.py`, so nothing outside that file knows which field a model speaks. The `default` mode **sends nothing at all** rather than pinning the documented `2`, so the program follows the provider if that default ever moves.

**The program defaults to `permissive` on both models** — the loosest setting each one offers. An earlier draft defaulted to `default` on the reasoning that loosening a filter should be a knowing decision; that was reversed the same day, and the argument against it is worth keeping. This is a **batch** tool: a one-off generator can shrug off a spurious refusal because the user just reruns it, whereas here a false flag costs a slot in an overnight run of hundreds that the user only discovers the next morning. On the native lineup a refusal is invisible at request time (HTTP 200 and a black frame), these two models are the only lever against that, and shipping the lever set to "off" hands the user the annoyance without the remedy. The failure mode is also real rather than hypothetical: **Cloudflare runs a vision check over the OUTPUT image**, so ordinary prompts get flagged on the strength of a frame the user never asked for and cannot inspect — exactly the class of false positive this setting exists for.

It does **not** disable moderation and is not a route around any provider's policies: it asks for the loosest setting the model itself publishes (5 of 5 on flux-2-pro's own scale), the provider still enforces its own limits, and a genuinely refused prompt is still refused. `default` and the stricter end stay one dropdown away.

**Ask what a field's default actually IS before assuming that omitting it is neutral.** This lineup has now produced the same lesson three times: krea's `creativity` defaults to prompt expansion *on*, flux-2-pro's `output_format` defaults to `jpeg`, and **Recraft's `size` defaults to `1024x1024` — a square**, so silence there would quietly render an entire 16:9 batch as 1:1 crops. All three are sent explicitly.

**`output_format` on flux-2-pro defaults to `jpeg`, which is not neutral**, so it is sent explicitly — the same lesson `creativity` taught. The wire spelling is derived by `wire_output_format()`, never written by hand: this model says `jpeg` and nano-banana says `jpg` for the same format. Magic bytes are sniffed regardless; a requested format is a weaker claim than a declared one, and CLAUDE.md's standing rule is that declared ones lie.

**Reference-image inputs — PARTIALLY REVERSED 2026-09-19, approved by the user.** The blanket skip below stood on two premises: that these fields are for single-image *editing*, and that they need a hosted URL. **Both are false for part of the lineup**, measured against the live API. A single global style-reference image is now planned for the four models that accept a **local file** — both klein models (multipart binary), both nano-banana models (base64, measured working) and flux-2-pro (base64, documented). **krea, recraft and p-image remain permanently excluded**: krea explicitly refuses base64 (`Must be an HTTP(S) URL`) so it would need public hosting, recraft has no `controls.image` at all (only `colors`/`background_color`), and p-image has no reference field whatsoever. The banned-fields test must be **narrowed to those models, never deleted**, or it silently stops guarding them. Multi-image, per-image strength and moodboards stay out — this is a batch style lever, not an editor. Full spec: [docs/reference-image-plan.md](docs/reference-image-plan.md); measurements in [docs/findings.md](docs/findings.md).

**Prompt expansion IS exposed, and defaults differently from the API.** Krea rewrites the prompt before generating unless told not to — its `creativity` field defaults to `"low"`, which is expansion **on**. The program sends `creativity` **always**, because staying silent would mean silently accepting whatever krea chooses. **CHANGED 2026-09-06: the default is now `"medium"`, matching krea's own documented default** (the API default is `medium`, not `low` as an earlier note here said). The original `"raw"` rested on a misreading — extra units in one image were attributed to expansion, but the sidecar showed `creativity: raw` was sent and the prompt went through untouched. Krea's docs also state a *detailed* prompt is polished rather than restructured, so the style-suffix drift that motivated `raw` does not bite at the ~660-character prompts this program sends. Shipping `raw` meant paying krea prices while turning off the thing that makes it krea. Not `high`: that takes liberty with style and mood, which a batch wants held constant.

This matters more here than in a one-off generator: the text sent is **prompt + style suffix**, and expansion rewrites the concatenated whole. It can reword the style addon as readily as the subject — and the style suffix is precisely the part meant to stay identical across every image in a batch, so letting it drift defeats the point of having one. Exposed as a control rather than forced off, since expansion genuinely helps a short or sparse prompt.

The other three krea dials (`intensity`, `complexity`, `movement`) are **not** sent, and that is not a limitation: every one defaults to the neutral value `0`, so omitting them is byte-for-byte equivalent to sending them. `creativity` is the exception only because its default is not neutral.

## Tech stack

Follows the Reactorcore house standard in `old wip/!standard python RC/` (local only, not in the repo) — read those before changing GUI or packaging:

- `standard python program by RC.md` — folder structure, build process, brand constants
- `ttkbootstrap_gui_guidelines.txt` — layout rules, required patterns, pitfalls
- `ttkbootstrap_labelframe_fix.md` — **always apply**
- `ttkbootstrap_custom_theme.md` — custom theme injection pattern
- `gui (example)/` — working GUI from a shipped program

**Environment:** Python **3.13.1** at `C:\Python313`. Installed: `ttkbootstrap 1.20.2`, `pyinstaller 6.19.0`, `httpx 0.28.1`, `requests 2.32.4`, `pillow 10.4.0`. Nothing needs installing.

ttkbootstrap is exactly 1.20.2 — the version with the `LabelFrame(padding=)` breakage. Use `_tk_ttk.LabelFrame` throughout; the codebase already does.

**Theme:** a custom teal/cyan theme (`gui/theme.py`), Segoe UI, injected **before** `ttk.Window()` — after is too late.

**Packaging:** PyInstaller `--onedir` via `build_release.bat`, released on itch.io under Reactorcore branding.

## Release

`build_release.bat` produces `dist/Batch AI Image Generator/` ready to zip. It compiles with PyInstaller, copies the docs, assets, promo images, example files and the source (the CLI is a shipped feature, and publishing the source is what lets a cautious user verify where their API token goes), strips `__pycache__` at every depth, and **aborts if `credentials.json` or `config.json` appear in the output**.

**Always test the built exe from a directory other than the project folder.** `config.json` and `credentials.json` sit beside the program, so a build tested in the dev folder will silently pick up real keys — that is the most likely way a token leaks into a public zip.

Runtime dependencies that must stay beside the exe: **`guide.md`** (the Help button opens it), **`recipes.md`** (the Helpers tab is parsed from it) and **`assets/icon.ico`** (the window icon).

**`promo.md` is DEV-ONLY and must never ship** (decided 2026-09-05). It is store copy, the marketing plan and the pricing strategy — none of a customer's business. The copy line was removed from `build_release.bat`; **`changelog.md` took its place** in the same block.

**Pricing: the program is PAID at $8 on itch.io**, and that is settled rather than provisional. `promo.md` records the reasoning: a paywall filters abuse of the free external tiers this program depends on, and "someone could build this in a weekend" undersells the tooling and design knowhow required. The distinction that must survive into every piece of copy is **the tool costs $8; the generation need not cost anything** — three models bill nothing and Pollinations needs no account. Never write copy that reads as "this software is free". **The promo images were re-rendered 2026-09-05** to drop a "Free" tag that read as a claim about the software; they now say **13 MODELS** and **"13 models — free and paid"**. `make_promo_images.py` regenerates them and **lives in the repo deliberately** — the first version was written to a scratch folder and lost, so a one-word text change meant rewriting the whole generator. Its copy is in constants at the top; the two rendering traps it guards against (measure every glyph, and draw the bullet rather than typing U+25B8) are documented in its docstring.

**klein bills NEURONS, not prepaid credit, and the two models differ by ~10x.** MEASURED 2026-09-06 at 1536x864: klein 4B bills **131.88 neurons/image (~75 free/day)**, klein 9B **1411.93 (~7 free/day)** — 10.7x, not the ~2x the parameter counts suggest. This **supersedes** the 2026-09-04 figure of 4.61 neurons/tile, which produced a wrong 361/day for 4B; today's query returns `totalTiles = 0` for klein, so **neurons-per-IMAGE is the reliable reading and per-tile is inference on top of it.** Both models now carry measured rates. Their labels say "free daily, then …" rather than "paid": calling a model free-for-most-batches "paid" pushed users toward genuinely dearer options. **Anything stating a price outside `core/models.py` should derive it from there** — a hand-typed collage label got both klein figures wrong at once.

## Scope — closed, and these were decisions

Do not "fix" these by adding them back. Each was considered and deliberately cut.

- **The PROVIDER lineup is FINAL, and as of 2026-09-05 so is the MODEL lineup — all eight gateway models ship.** Cloudflare plus Pollinations remain the only two providers. What is being added (from 2026-09-05) is more *Cloudflare* models via its **AI Gateway**, which is the same endpoint, token and account — not a new provider and not a new credential. See [docs/gateway-models-todo.md](docs/gateway-models-todo.md) for the phased plan and per-model quirks. **fal.ai, Together and Replicate are still dropped, not deferred** — fal doesn't publish per-model pricing for its wider catalogue, so a cost estimator can't be built against it, and the genuinely better generators are priced far above what is comfortable for batch work. For one-off high-quality images the answer is a free arena site, not another paid integration. **Do not add providers.**
- **No in-app prompt builder.** Template/wildcard expansion was brainstormed and cut as too niche for a general-purpose tool. It became a separate project, **Omni Prompt Builder**, which will ship curated wildcard `.txt` lists generating the prompt files this program consumes. `docs/prompt-builder-ideas.md` is input to *that* project, not a backlog for this one.
- **No live quota readout.** The API can't support one (see above). Client-side estimates only, labelled as estimates.
- **No unified-billing setting — BLOCKED UPSTREAM, not cut.** Routing native models through AI Gateway credit (`cf-aig-gateway-id`) is specified in [docs/unified-billing-todo.md](docs/unified-billing-todo.md) and deliberately unbuilt: **MEASURED 2026-09-09**, klein requires multipart and the gateway path rejects multipart, so the feature reaches only the three JSON models — and makes those three *paid*, because "free" is a property of the neuron path rather than of the model. `ModelSpec.is_free` therefore stops describing reality the moment unified billing is on, which is why `_attempt_budget()` branching on it would hand a **billed** model the free lane's 3 attempts. Re-test with `python tools/probe_unified_billing.py` before building anything (free, prints STILL BROKEN / FIXED; last run 2026-09-12, still broken).
- **No credential encryption.** Encrypting a local key with a local key solves nothing.

## Working agreements

### Measure, do not assume

Two bugs in this project came from writing down a plausible number instead of testing one: the Pollinations concurrency cap (guessed 4-with-key, actually 1) and a reserved label height (guessed 3 lines, actually 4). Both reached the user as visible faults.

**Where a limit, size or capability matters, probe it** — with inputs that cannot be served from a cache. When a measurement contradicts the documentation, the measurement wins and the doc gets corrected with a note saying what it superseded.

### NEVER run a paid generation without explicit permission (2026-09-19)

**Hard rule, no exceptions, no judgement calls.** Do not send a request that generates a billable image on any paid model — gateway or native — unless the user has given an explicit go-ahead **for that specific test, in that specific message**.

When a probe reaches the point where only a real generation can answer the question: **stop and ask.** Do not proceed because the amount is small, because the test seems conclusive, because the user approved the *investigation*, or because a prior message sounded permissive. Approval to look into something is never approval to spend. A general "sure, try it" covers only the free steps; the billable step needs its own yes.

**And when asking, ask for the PROMPT too.** These models bill a **flat fee per image** — a 64x64 throwaway costs exactly what a real 4K image costs — so a generation spent on `"a red cube on a white table"` is money burned for nothing. If the user is paying for an image, they get to choose what it is, so the test doubles as a real result. Ask for the prompt, and the size/model if it matters, then run it once.

This was written after a reference-image probe on `nano-banana-2-lite` spent ~$0.034 on a junk prompt. The user's approval had been "sure why not, seems like if you can do it for free" — **the free-ness was the condition**, and the billable step should have stopped and asked. The cost was trivial; the precedent is not, and on `nano-banana-2` at $151/1000 the same mistake is 4x dearer per image.

**What is still free and needs no permission:** the gateway validates a body BEFORE forwarding it, so malformed and well-shaped-but-unusable requests are rejected at no cost. That is how the entire gateway field list was verified, and it is the technique to reach for first — see `tools/probe_reference_image.py`, which establishes encodings using unreachable URLs and deliberately corrupt payloads. Free models (the three SD, both Pollinations) are also unrestricted; klein's daily neuron allowance is not a blank cheque but is low-stakes, so prefer klein over a prepaid-credit model when a real image genuinely is required.

### The single custom prompt override (2026-09-09)

A tickbox on the Prompts tab sends **one typed prompt** instead of the prompt file, for trying an idea before it is worth writing a `.txt` for. Off by default. The tick **and** the text both persist across restarts — retyping the prompt is the chore the feature removes.

**It is MATERIALISED as a real single-line .txt, and that is the whole design.** `prompt_file` is not merely an input: its path keys `find_batch()` for resume, its stem seeds `build_filename()`, and it is recorded in every sidecar as `source_file`. A sentinel path would make two different one-offs collide on one batch row and one filename. `materialize_one_off()` writes to `<output_dir>/.oneoff/<stem>.txt` — inside the output folder for the same reason `.batchgen.db` is, since a resume must find the same path it ran under. **`core/engine.py` was not touched at all**, and it should stay that way: do not add a one-off code path to the engine.

**Disambiguate on CONTENT, not on existence.** An identical prompt keeps its path, so re-running a one-off resumes instead of paying twice; a different prompt that sanitizes to the same stem gets `unique_path`. Stem collisions are real, not theoretical — `sanitize_fragment` keeps words from *both* ends, so "a misty forest of tall pines at dawn" and "...of dark spruces at dawn" both stem to `misty_dawn`. The test uses that exact pair, because an earlier draft used prompts that stemmed differently and **passed with the guard deleted**.

**The text lives in `single_custom.txt` beside the program, NOT in `config.json`** — only the flag is config. The box is free-form and users paste anything into it, which is a poor fit for a JSON string field. It must never ship: `build_release.bat` aborts on it alongside `credentials.json` and `config.json`, and it is gitignored with `.oneoff/`.

**Saving on keystroke alone is not enough.** A right-click paste fires no `KeyRelease` — and pasting is exactly how a long prompt arrives — so `<<Paste>>` and `<FocusOut>` are bound too, plus a flush in `_on_close` for text typed and never blurred.

**A one-off pins the count to 1, which silently poisoned `prompt_limit`.** `_set_limit()` persists `None` whenever `n >= total`, which always holds at a total of 1, so it would have erased a cap the user had set on their real prompt file. Guarded on the override flag. Found by tracing the path, not by hitting it.

The prompt-file entry is **greyed out, never hidden** (per the rule below), and the banner states the **consequence** — "generating 1 image from the text below. Your prompt file is ignored." — not the mode's name.

**AMENDED 2026-09-09, both on user feedback.** The one-off text box is **editable even while the override is off**: disabling it bought nothing, because a `tk.Text` does not visibly grey out, so the only effect was a box that silently refused typing — and drafting the next idea before arming the override is reasonable. And the banner **always says something**, including a green "Disabled — using the selected prompt file" in the off state. An empty label left a hole in the layout until the box was ticked, and stating the off case is what makes the on case read as a change rather than as noise. Four states now: off (green), on (amber), on-but-empty (red), and the prompt-file row's own greying. Preview, character counter, Generate slider and the Provider tab's batch cost all follow the override; check these by launching the GUI. CLI parity is `--prompt "text"`, with the prompt-file argument now `nargs="?"`.

### The style reference image (2026-09-19, BUILT)

One global reference image, applied to every prompt in the batch, on the **five** models that accept a local file — both klein (multipart binary `input_image_0`), both nano-banana (`image_input`, base64 data URI) and flux-2-pro (`input_images`, base64, **doc-derived and still unconfirmed with a real image**). Full plan: [docs/reference-image-plan.md](docs/reference-image-plan.md); measurements in [docs/findings.md](docs/findings.md).

**krea, Recraft and p-image are excluded by MEASUREMENT, not preference**, and that is recorded in `REFERENCE_IMAGE_EXCLUSIONS` in `core/models.py` rather than in a doc — krea refuses a `data:` URI outright (`Must be an HTTP(S) URL`) and would need the user's art hosted publicly, Recraft's `controls` holds only `colors`/`background_color`, and p-image has no such field at all. **The banned-fields test was NARROWED to those three, never deleted**, or it silently stops guarding them.

**`core/reference.py` owns the ENTIRE decision layer, and the GUI owns none of it.** The status label, `cli dry-run` and the engine all render the same `PreparedReference`; none of them decides anything. A label that says "will be upscaled to 1024x1024" while the engine sends something else is the failure that structure exists to prevent.

**`reference_field is None` is the single gate.** `supports_reference_image()` is to this feature what `cost_band()` is to pricing — no model list is written in the GUI, the CLI or the engine, and `reference_models_sentence()` builds the user-facing "use one of these instead" text from the registry so a model added later appears without anyone updating a string.

**The 64px floor is UNDOCUMENTED, binds PER SIDE, and is the whole reason the client-side check exists.** Measured: 63x63 rejected, 64x64 accepted, **64x48 rejected**. The refusal is a generic HTTP 400 `AiError: Invalid input` (8001) naming neither the field nor the size, so an unchecked 16x16 sprite fails every line of the batch unexplainably. The documented "smaller than 512x512" maximum is simply **false** — 4096x4096 returns 200 — but the program caps at 2048 anyway, because accepted is not recommended.

**Upscaling is NEAREST by default and that is load-bearing.** An image is upscaled only because it is below the floor, which means it is tiny, which means it is almost certainly pixel art — and smooth resampling blurs the hard edges that ARE the style being referenced. The upscale is an **integer factor**, or a fractional scale reintroduces exactly the blur NEAREST was chosen to avoid. Downscaling snaps each side to a **multiple of 16** (a 1280x1280 sheet lands on 1024x1024, not the 1025x1025 that rounding sqrt(1.05 MP) gave before 2026-10-15), and uses LANCZOS for photos but **keeps NEAREST for detected pixel art even at a fractional factor** — decided 2026-10-15: uneven columns are acceptable for a style reference, smooth blur is not, so do not "fix" it to integer-only downscaling. **No padding, no stretching** — the x16 snap moves the ratio by about 1% at most — because anything outside 3:7–7:3 is rejected at step 0, so the ratio guard owns shape and the resize owns size.

**Reject outside 3:7–7:3; WARN on a mismatch with the output ratio.** These are different questions and must not be conflated. The window is about the model being unable to use the image at all (a 12:1 animation strip); a 1:1 sprite guiding a 16:9 batch is perfectly reasonable, because the reference carries *style* and the output ratio carries *composition*. Every message names the actual numbers and a remedy.

**Identity is a CONTENT hash of the prepared bytes, in BOTH gates.** The filename hash *and* `find_batch()` — the plan specified only the first, which is exactly half of the fix the style-suffix bug already taught, and CLAUDE.md's own rule is that fixing one leaves the symptom. A path would let a different sprite swapped in under the same filename resume the old batch and generate nothing. The resampler mode is deliberately **not** a separate hash part: it changes the bytes, so it is covered. Adding the column needed the project's first schema **migration** (`JobStore._migrate()`), since `CREATE TABLE IF NOT EXISTS` never touches an existing table.

**Backward compatibility was VERIFIED, not assumed.** The hash part is **omitted entirely** when there is no reference rather than appended as `None` — the parts are joined with a separator, so a trailing `None` appends an empty field and changes the digest, which would have renamed every pre-existing image and re-billed every paid batch on the next run. The plan asserted the opposite; a two-line check settled it.

**The resampler is a three-state dropdown, not a checkbox**, because auto-detection is measured to be reliable and a checkbox would make every user answer a question the program can usually answer itself. Two signals — colour count and a nearest half-scale round trip — and **the colour count carries the veto**, contradicting the plan: a smooth gradient passes the round trip at 0.004 while holding ~196k colours, and nearest is wrong for it. See findings.md for that and for the 0–255 vs 0–1 unit bug in the first implementation.

**No engine branch, and this stays that way.** The reference is prepared ONCE before the run and passed down like the style suffix; `_UNPREPARED` is a sentinel distinct from a prepared `None`, so a referenceless batch does not re-check on every job. A reference set on a model that cannot take one is **dropped with a log line**, not raised — the model and the reference are chosen in two different dropdowns, so the combination is reachable by ordinary use. An unusable **file** does raise, and is validated in the GUI *before* the paid-confirmation dialog, since the only other place it would surface is inside a worker thread after the user has already agreed to spend.

**Influence is a SENTENCE, not a strength, and that is the only option (2026-10-15).** No model taking a local reference has a strength field, so the Influence dropdown appends a sentence naming the reference in the model's own words — `ModelSpec.reference_prompt_name`, `"image 0"` on klein, `"the reference image"` elsewhere. **The five levels and their wording (None / Subtle / Medium / Heavy / Exact — "No influence from {ref}." … "Exact style as {ref}.") are the USER'S choice**, replacing a measured Off/Style/Strong set, and were deliberately left untested; they live only in `INFLUENCE_TEMPLATES` in `core/reference.py` and are pinned by a test. **There is no "off": None sends a sentence too**, and is the default. Applied in `load_lines()`, so it lives in `final` and therefore in the request, sidecar, job row and filename hash; `prepare()` folds it into the stored suffix so `find_batch()` sees it too — **both gates again**. Gated on a reference actually being sent, never on the dropdown alone. Do not turn it into a slider.

### The Helpers tab, and recipes.md as a runtime input (2026-09-13)

A 4th tab, **Helpers** — a bonus section of small conveniences, not part of the batch workflow. It currently holds one thing: the LLM prompt recipes. Text links to four assistant sites, then a copy-to-clipboard button per prompt block. That is the whole feature; there is no round trip back into the program (no "save the reply as a .txt"), by decision — the user has Notepad open anyway.

**`recipes.md` is now PARSED AT RUNTIME, so its format is load-bearing.** This is the fact that matters for future edits: the file is no longer just shipped prose. `core/recipes.py` reads it with the same path ladder the Help button walks for `guide.md`, and the tab is built from what it finds. There is deliberately **no second copy of the prompt text in Python** — same reasoning as `core/models.py` owning every price. Edit the doc, press **Reload**, see the change.

**Two markers carry the contract, and they were chosen over shape-matching.** `<links>...</links>` wraps the site list (one `Name - URL` per line, split on the LAST separator so a dashed name survives, and any of `- – —` accepted because nobody types an em dash on purpose). `<recipe name="...">` wraps each copyable block. The first draft matched on *shape* — any bullet containing a URL, the heading nearest a fence — and that silently captures prose added later: the "Recovering from a bad batch" section is already a bullet list, so a link added there would have turned up in the GUI for no visible reason. **A marker matches intent; a shape matches accidents.**

**The fences stay INSIDE the `<recipe>` tag** rather than being replaced by it. They are what makes the block render as a copyable code box for anyone reading `recipes.md` as a document, which is still its primary job. The tag adds a name the parser can trust; it does not take over the rendering.

**Placeholders are single tokens** (`YOUR_TEXT`, `YOUR_PROMPT`, `DESCRIBE_THE_LOOK_YOU_WANT`), not `[BRACKETED PHRASES]`, because a double-click selects one token and cannot select a bracketed phrase. Changed in the doc itself rather than transformed at copy time, so the clipboard is byte-identical to the file.

**Captions are the ONE thing not parsed**, and that is deliberate: the prose around each block is explanatory paragraphs, not caption-shaped. `CAPTIONS` in `gui/tabs/helpers.py` is keyed by recipe name with a blank fallback, so a recipe added to the doc still gets a working button, just without a caption — the drift risk is cosmetic, never on the prompt text. A test asserts every captioned name still exists, since a rename would silently drop its caption.

**Missing and unparseable are different states with opposite fixes**, so they print different text and the "Open recipes.md" button disables only for the first. A broken file must degrade to an empty tab that explains itself, never to a program that will not start — `load()` catches rather than raises.

**Links sit ABOVE the recipes**, matching the document, because that is the order of use: open the assistant first so it loads while you fetch the prompt.

**No in-app AI, and this is settled.** Running these prompts through Workers AI was considered and cut. Not mainly the neuron cost: they are *judgement* tasks ("style only, no subject matter", "distil every visual element"), which small instruct models fail quietly — producing plausible output that breaks the one rule that matters, while spending the image quota to do it. The external assistants are better at this and free.

Not mentioned in `promo.md` by decision — it is a workflow convenience, not a headline feature.

### Image identity: the filename IS the key (2026-09-13)

Two user-reported symptoms — "a changed style suffix generates nothing" and "the db file stays locked until I close the program" — plus a third found on the way. Full write-up in [docs/filenames-and-regenerate-plan.md](docs/filenames-and-regenerate-plan.md).

**The style suffix is part of the image, so it is part of the image's identity.** It was in neither gate: `find_batch()` stored `style_suffix` from the start but never compared it, and `build_filename()` used `original_prompt`, which is the bare line *without* the suffix. Two independent gates, one missing input — so a rerun reattached to a finished batch, found the old file on disk, and skipped, silently. Both now include it. **Fixing only one leaves the symptom**, which is the thing to remember if either is ever refactored.

**The filename now carries a derived hash of every image-affecting setting** (final prompt, model, size, negative, guidance, steps, expansion, filter), so "I changed something" regenerates by construction rather than by anyone remembering to update an identity check. **Derived, never random**: `existing_output()` rebuilds the name to find an image, so a random component would break crash-resume and overwrite protection for every batch and silently re-bill a paid batch on any rerun. **Collisions are the feature** — two runs colliding means "same image". **The seed is deliberately excluded**, or a random-seed batch could never resume.

**Filename slugs keep the words that VARY across the batch, not the words at the ends.** MEASURED against the shipped `test_prompts.txt`: `_squeeze` takes from both ends, but a batch's boilerplate sits at *both* ends ("Distant low angle background of a …" / "… weather."), so all four of those lines named themselves `distant_low_angle_*_weather` and the subject never appeared at any budget; at a 20-char budget all four collapsed to the identical `distant_low_weather`. Position was the wrong signal — repetition is the right one, and the engine has already loaded every line before it names anything, so it can be measured. Now `field_day_cloudy` / `forest_dawn_rainy` / `desert_dusk_clear`. The corpus must be the **unlimited** prompt list (`naming_corpus()`, not `load_lines()`), or a 5-of-100 test run and the later full run would disagree about what counts as boilerplate and name the same line two different things.

**The style slug comes from the suffix TEXT, never a preset name** — a preset can be edited without being re-saved, and the filename would then assert a style the image does not have. A slug of what was actually sent cannot lie. **No model field**, deliberately: an abbreviation table would be a second place a model's identity is written, against `core/models.py` being the single source of truth.

**`Overwrite` never did what everyone believed, including two docs.** It is checked in `_generate_one` **after** a job is claimed, and `claim_next()` never hands out a `done` row — so on a finished batch that check is reached for no job at all. It governs only the on-disk check. `recipes.md` and `findings.md` both asserted it "regenerates everything"; both corrected. **Regenerate All** (`store.requeue_finished()`, `cli.py regenerate`) is the real action, and it implies overwrite for its run — requeueing alone would just be skipped again by the on-disk check. It leaves `blocked` alone (same text, same refusal) and leaves `failed` to Retry Failed, so the two actions stay separate and differently priced.

**Regenerate covers the CURRENT RUN, not the prompt file, and the button is named for that.** `limit` is applied in `load_lines()`, so `prepare()` never creates rows past it — a 5-of-100 run has 5 job rows and `requeue_finished()` finds 5. The first label was **Regenerate All**, and "All" promised a scope the button does not have; it is now **Regenerate**, with the count stated beside it. Pinned by `test_regenerate_respects_the_generate_slider`, which exists because if limiting ever moved later (to the claim, say) a 5-of-100 Regenerate would quietly become 100 images — a 20x bill on a paid model.

**Documenting a misleading label is not fixing it.** The `Overwrite` finding was written into `findings.md` and `recipes.md` last session, and the very next day the user ticked the box, pressed Start on a finished batch, got "0 pending" and no images, and reported it as a bug. The checkbox still said "Overwrite images that already exist", which reads as *regenerate everything*. It now says **"Replace files instead of saving alongside them (only affects images being generated now)"**, the tooltip points at Regenerate, and the "nothing left to do" summary names Regenerate and states outright that Overwrite does not do this. **Where a doc has to explain that a control does not do what it says, change the control's words.**

The behaviour itself is pinned, not changed: `test_overwrite_does_not_redo_a_finished_batch` asserts a ticked Overwrite regenerates **nothing**. Making it re-queue finished work would silently re-bill a whole paid batch whenever the box happened to be ticked — which is exactly why Regenerate is separate and confirmed.

**A disabled control still has to say why it is disabled.** Regenerate was enabled on a fresh Run tab, where pressing it built the batch, requeued zero jobs and ran normally — Start wearing the wrong label. It is now gated on `done + skipped > 0` (exactly what `requeue_finished()` acts on) with an on-screen reason beside it — "run a batch first" / "redo the N image(s) from this run" — never a tooltip alone, per the negative-prompt group's rule.

**`secondary.TButton` paints itself `bg_surface`, the same colour as the frame it sits in**, and its `active` colour is the one it already has — so a standalone one reads as floating text with no hover feedback. Tolerable inside a bordered frame (Clear Log), not for a control on its own; hence `quiet.TButton`. **Found by looking at a screenshot, not the code** — the styles are named for intent and this one's appearance does not follow from its name.

**A status line that grows changes the layout below it.** `progress.current` was cut at 100 characters, which clipped mid-sentence on nearly every real prompt. MEASURED at the 900px minimum width: the label reserves two lines (27px empty, 50px at two) and **160 characters is the most that fits** — 240 spilled to a third line and made every panel below it jump on each image, the exact failure `reserve_lines` exists to prevent. Widening a label means measuring it at the minimum window size, not at the default one.

**A leaked `JobStore` was holding the database open.** [gui/app.py](gui/app.py) built a whole `BatchEngine` just to count prompt lines and dropped it without `close()` — no `with`, unlike `dry_run()` twenty lines below. It fired on **every Start press**, including ones cancelled at the paid-confirmation dialog, and WAL sidecars only clear on a clean close. The general rule: `BatchEngine(...)` opens a SQLite connection, so it is **always** `with`, even when only reading.

### The UI sanity pass (2026-09-05)

Phases 1-6 of [docs/ui-sanity-pass-plan.md](docs/ui-sanity-pass-plan.md) are complete. That file holds the detail; the durable rules it produced:

- **A "don't let it jump" guard must ask WHAT CAUSED the change.** `reserve_lines` in `gui/scroll.py` was a one-way ratchet — right for status text that changes on its own, wrong for text driven by an explicit user choice, where holding the tallest model's height leaves permanent dead space under every shorter one. Hence `sticky_height`, False on the seven labels that re-render on model selection.
- **Hiding a control the user might want reads as the app losing settings; hiding a whole feature the model CANNOT USE is honest.** The negative-prompt group collapses on the 10 models that ignore it — 431px of dead checkboxes — but the group frame and the reason stay on screen. The explanation must never disappear; only the controls fold.
- **A disabled empty box is indistinguishable from an unfilled one.** Disabled numeric controls now show the value actually in use (klein's fixed `4` steps) or `n/a`. The placeholder must never be persisted — both vars have config-writing traces, so `n/a` would have been saved as the user's step count.
- **Track a combobox selection by INDEX, never by reading the label back.** Tier labels are per-model now, so a reverse lookup on visible text would silently reset the user's tier the moment the list was rebuilt.
- **Compute label widths, don't eyeball them.** Tier labels were measured across every model x tier x ratio (longest 69 chars against a 70-wide box); the first draft was 83 chars against a 56-wide box. Pinned by tests.

### Where notes go

| What you have | Where it goes |
|---|---|
| A box that is now done | Tick it in `TODO.md`. One line, no essay. |
| A durable measured fact — a price, an API quirk, a library pitfall | **`docs/findings.md`** |
| "Here is what this session did and found" | **`docs/session-log.md`** |
| A confirmed architectural decision and its rationale | This file |

Keep `TODO.md` a checklist. It previously grew to 200+ lines of session write-ups and became expensive to load every session.

### Docs

**No manual line wrapping in markdown.** One continuous line per paragraph, let the editor soft-wrap. Hard wraps break copy-paste and provide no parsing benefit. This applies to every markdown file here, released or internal.

### General

- Keep the tool general-purpose. No consumer of its output gets to shape it.
- Prompt quality is the actual cost lever. Validate on free endpoints before any paid batch.
- Follow the Reactorcore standards for every GUI and packaging decision — header, footer attribution, `_apply_icon` on every window, right-click context menus, no drag-and-drop, tooltips.
- Run `python tests/test_engine.py` (105/105, offline) after touching `core/`.

## Prompt lessons

### The "blurry" prompt lesson

An early attempt used `"Blurry distant aerial photography of a [forest]"` on FLUX schnell and came back genuinely blurry, while a weaker SD1.5 model had ignored the word. That is strong prompt adherence doing its job — a prompt-design problem, not a model problem. Words like "blurry" must be replaced with what is actually wanted: soft focus, atmospheric haze, depth of field, painterly softness.
