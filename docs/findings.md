# Measured findings

Facts established by **running something and looking at the result**, not by reading documentation. Several of these contradict the docs, and two of them contradict earlier guesses of my own — that is exactly why they are written down.

**Read this before changing provider code, pricing, or anything size-related.** [session-log.md](session-log.md) has the chronological story; this file is the reference.

Every entry says how it was measured, so it can be re-checked if a provider changes.

---

---

## Pollinations silently CLAMPS to ~0.59 MP (measured 2026-09-05)

**This is a measured fact that contradicts what the program assumed, and it cost real image quality until it was found.** Both Pollinations models were specced with `max_dimension=2048`. The true limit is a **pixel budget of ~589,824 px (0.5625 MP)**, and anything above it is silently scaled down.

Probed with cache-defeating unique prompts on both `flux` and `dreamshaper`, so it is a platform cap rather than a model quirk:

| Requested | Returned | |
|---|---|---|
| 768x432 (16:9) | 768x432 | honoured |
| 512x512 (1:1) | 512x512 | honoured |
| 432x768 (9:16) | 432x768 | honoured |
| 1024x576 (0.59 MP) | 1024x576 | honoured |
| 1152x648 (0.75 MP) | **1024x576** | clamped |
| 1280x720 (0.92 MP) | **1024x576** | clamped |
| 1536x864 (1.33 MP) | **1024x576** | clamped |
| 1024x1024 (1.05 MP) | **768x768** | clamped |
| 1024x1536 (1.57 MP) | **627x940** | clamped |

**Aspect ratio is preserved; the image is simply scaled to fit the budget. It returns HTTP 200 with no error and no warning.**

This investigation started from a different hypothesis — that FLUX.1 schnell on Pollinations only supports 1:1. **That is false.** Non-square ratios are honoured exactly. The premise behind a proposed auto-crop feature did not hold, and the feature was dropped: cropping would have discarded pixels to fix a problem that does not exist.

### Why this mattered more than a wrong number

`GenerationResult` is built from the **requested** width and height, so at the program's Standard tier the user asked for 1536x864, received 1024x576, and the sidecar JSON recorded 1536x864. A batch reported 100% success while every file was smaller than its own metadata claimed.

**This is the same failure shape as the black-image content filter** — HTTP 200, no error field, wrong result — and it is the second instance of the project's standing rule: *trust the bytes, not the response.*

### The fix

- `SIZES_POLLINATIONS` gives both models their own size table, **computed** against the measured cap (largest exact-ratio, multiple-of-8 size fitting the budget), then **verified against the live API**: 1024x576, 936x624, 768x768 and 576x1024 were each requested and each returned at exactly the requested size. At 16:9 the Standard size is **1024x576**.
- `max_dimension` corrected from 2048 to 1024 on both specs. Note the per-side value alone cannot express this limit — it is an *area* budget, which is why the size table is the real fix.
- The sidecar now records **`size_mismatch`**, and the engine **logs a warning**, whenever the delivered size differs from the requested one. Two similar keys sitting side by side (`width`/`height` vs `actual_dimensions`) left the comparison to a reader who never makes it.

Pinned by `test_pollinations_never_asks_for_a_size_it_will_not_get` and `test_pollinations_ratios_are_exact`.

---

## Cloudflare AI Gateway access: what a user must actually do (doc-derived 2026-09-05)

**DOC-DERIVED, not measured** — no prepaid credit was available to spend. Sourced from Cloudflare's own documentation; a measured contradiction beats it, as always.

- **The program's endpoint is correct.** `POST /accounts/{id}/ai/run` with the model id in the body. No gateway id belongs in the URL path.
- **Gateway routing uses the `cf-aig-gateway-id` HTTP header**, not the path. For **third-party models it is optional**: requests route through the account's default gateway, and *"if the gateway does not exist, AI Gateway creates it on the first authenticated request."* **So the program sending no such header is correct for the gateway models** — do not "fix" this by adding one. **SUPERSEDED IN PART, MEASURED 2026-09-09**: the same sentence was written as though it settled the matter for the *native* five as well, and there it is wrong — the header is **mandatory** to route a Workers AI model through a gateway, and omitting it is why native models keep billing neurons while credit sits unspent. See "Unified billing reaches the JSON models and not klein" below.
- **Token permission is Account → Workers AI → Read**, required for all `/accounts/{id}/ai/*` endpoints including third-party models. The **"Read all resources"** template includes it, so `guide.md`'s existing advice stands. Note the read-only-token finding was *measured* on the native models and is *inferred* for gateway ones.
- **Credits must be loaded before any gateway model runs**: Cloudflare dashboard → AI Gateway → **Credits Available** → *Manage* → *Top-up credits*. Auto top-up with a threshold is available.
- **There is a 5% fee on credit purchases** — $100 of credit costs $105.
- Without credit the API returns **HTTP 402**, already mapped to a fatal `QuotaExhausted`.

Sources: [REST API](https://developers.cloudflare.com/ai-gateway/usage/rest-api/), [Unified Billing](https://developers.cloudflare.com/ai-gateway/features/unified-billing/), [default gateway changelog](https://developers.cloudflare.com/changelog/2026-03-02-default-gateway).

---

## Unified billing reaches the JSON models and not klein — MEASURED 2026-09-09

Prompted by a live account that had exhausted its daily neurons while holding unspent AI Gateway credit: the paid gateway models kept working and `flux-2-klein-4b` did not. Every claim below was measured against that account, and **two of them contradict Cloudflare's documentation**, which by this project's standing rule means the documentation is the thing that is wrong.

**Unified billing is an ACCOUNT setting, and no header will substitute for it.** The gateway carries `workers_ai_billing_mode`, readable at `GET /accounts/{id}/ai-gateway/gateways/default`. It ships as `"postpaid"` — the free-neuron path. While it read `postpaid`, a correctly-formed request carrying `cf-aig-gateway-id: default` on a JSON model *still* returned `429` / `4006` neuron exhaustion. The header routes; it does not pay. Flipping the dashboard setting to **Unified billing** (`"unified"`) is what moves the money, and it is the user's action, not the program's. **Read the field rather than asking the user whether they set it** — it is one unauthenticated-cost GET and it distinguishes "not configured" from "genuinely broken", which no error message on the request path does.

**The three "free" SD models are NOT free under unified billing.** `sdxl-lightning` returned `429`/`4006` on exhausted neurons, and after the mode flip — nothing else changed — the identical request returned `200` and a real 1024x576 image. That image was billed to credit. So "free" is a property of the **neuron path**, not of the model, and `ModelSpec.is_free` silently stops describing reality the moment unified billing is on. This is the finding that decides the shape of any future setting: there is no free lane to exempt, and the retry cap at `core/engine.py:514` branches on `is_free`, so under unified billing it would grant a **billed** model the free lane's 3 attempts and buy up to three copies of one image. That is the exact failure that bought four copies of a p-image generation on 2026-09-06.

**klein cannot be gateway-routed at all, because its two requirements contradict each other.** The FLUX.2 klein models require `multipart/form-data`. The gateway path refuses it:

| Request | Result |
|---|---|
| multipart, no header | `200` — image (billed to neurons) |
| multipart, `+ cf-aig-gateway-id` | `500` / **7000** `Invalid request body` |
| multipart via explicit boundary, `+ header` | `500` / **7000** — same |
| JSON, `+ header`, model in path | `400` / **5006** `required properties at '/' are 'multipart'` |
| JSON, `+ header`, bare `/ai/run`, `{model, input}` | `400` / **5006** — same |
| multipart, `+ header`, bare `/ai/run` | `400` / **6003** `Request body is not valid json` |
| **`sdxl-lightning` JSON, `+ header`** | **`200` — image, billed to credit** |

The model demands multipart; the gateway accepts only JSON. No body satisfies both. The Lightning row is the control that makes this conclusive — same account, token, gateway and header — so the failure is the **request encoding**, not the configuration. Cloudflare's REST API page says under "Specify a gateway" that *"Workers AI requests always require this header"*, unqualified, and that is not true of the multipart models.

**RE-TESTED 2026-09-12: unchanged.** Same `7000` on multipart, same `5006` on JSON, control still passing, account still `unified` — so this is a standing upstream limitation rather than a transient glitch. Re-check with `python tools/probe_unified_billing.py`.

**The irony worth remembering: klein-4b is both the best per-dollar model in the lineup and the one model unified billing cannot reach.** Reported 2026-09-09 to the Cloudflare community forum, Discord and `cloudflare/cloudflare-docs`; drafts kept at [cloudflare-klein-gateway-bug-report.md](cloudflare-klein-gateway-bug-report.md) and [cloudflare-docs-issue.md](cloudflare-docs-issue.md). Until it changes, a "use my credit" setting can only ever cover the three JSON models — and would make those three cost money — which is why the feature is **specified but not built**: [unified-billing-todo.md](unified-billing-todo.md).

**`7000` responses carry no `requestId`**, only a `cf-ray`, unlike the `5006`s. Worth knowing when reporting one.

---

## GUI pitfalls found in the 2026-09-05 UI pass

Three bugs whose causes generalise beyond this program.

### A screen-bounds clamp breaks when the thing being clamped is bigger than the screen

`gui/tooltip.py` positioned tooltips with `y = max(_MARGIN, min(y, screen_h - tip_h - _MARGIN))`. That is correct **only while the tooltip fits**: once `tip_h` exceeds the screen height the inner term goes negative, `max` selects `_MARGIN`, and the window is placed with its top at the margin and its bottom far off-screen — no scrollbar, no indication anything is missing.

Measured: the model dropdown's tooltip had grown to 2958 characters, which at the default wraplength is **984px tall against 816px of usable screen**. The same expression also ignored the taskbar entirely.

Fixed by handling the too-tall case explicitly rather than arithmetically, plus `_fit_vertically()`, which **widens** an oversized tooltip (trading height for width the screen has spare) instead of clipping it. **The deeper fault was growth by accretion** — every model added appended its own paragraph — so per-model prose moved out of the tooltip entirely and into a label under the dropdown.

### A "don't let it jump" guard must ask what caused the change

`reserve_lines()` held a high-water mark that only ever grew. Right for status text that changes on its own (a credential check, a batch result), where an unprompted resize reads as the section jumping. **Wrong for text driven by an explicit user choice**: selecting a model with a 3-line note and returning to a 1-line one left two blank lines that never closed. Now takes `sticky_height=False` for user-driven labels.

### A widget kept in a local variable cannot be managed later

The Guidance entry was built as a local `g`, so nothing could ever disable it. On the eight models that accept no guidance it stayed fully editable while the note two lines below said the opposite. Now `self.guidance_entry`.

**Related trap:** the Steps and Guidance vars have `trace_add` handlers that write straight to config, so displaying a placeholder such as `n/a` in a disabled box would have **persisted it as the user's setting** and sent it to the next model that does accept one. Guarded by a `_placeholding` flag.

---

## Cloudflare AI Gateway models

### MEASURED 2026-09-06 — the first live gateway calls, and two doc-derived facts were WRONG

**This section supersedes the doc-derived entries below it wherever they disagree.** Until this date every gateway fact was read from Cloudflare's published model pages, because no prepaid credit existed to spend. $10 of credit was loaded and the eight paths were finally run. Per the standing rule, **the measurement wins**.

**The token question is settled: a "Read all resources" token IS sufficient.** No `AI Gateway → Edit` grant was needed. The gateway lane authenticates with exactly the same token as the native five, and the Get Started page's Read+Edit advice applies to creating gateways by hand, which this program never does.

**Prepaid credit works as documented.** No provisioning step, no separate gateway setup — the credit simply becomes spendable at bare `/ai/run`.

#### 1. The response nests ONE LEVEL DEEPER than the documentation implied

This is the expensive one. The live shape is:

```json
{"result": {"state": "Completed", "result": {"image": "https://..."}}}
```

Both `state` and `image` sit **inside** `result`, not beside it. Every doc-derived example — and the code written from it — had `state` at the top level and the image at `result.image`. Reading that fixed depth returns `None` **on a perfectly valid, fully generated, already-billed response**.

**What it cost: 4 billed images for 1 wanted picture.** `None` was raised as a transient error, the engine retried on its normal budget, and each retry generated and billed a fresh image. ~$0.02 instead of $0.005. The image existed and was paid for every single time; the program simply could not see it.

`_extract_image` now **walks the `result` chain** instead of assuming a depth, checking `state` at every level. Both the nested and the flat shape parse, so a future change of depth cannot cost money again. Pinned by `test_gateway_image_is_found_however_deeply_it_is_nested`.

#### 2. p-image returns a PRESIGNED URL, not a `data:` URI

The entry below records — from Cloudflare's own model pages, read twice and "confirmed family-wide" — that p-image returns `data:image/jpeg;base64,...`. **It does not.** It returns a presigned R2 URL needing a second GET, exactly like krea and flux-2-pro. Measured directly; the sidecar of the first successful image still records `response_encoding: json_data_uri` from the registry while the fetch log shows a plain `GET` to `ai-gateway-outputs...r2.cloudflarestorage.com`.

**This cost nothing, and the reason is worth keeping.** `_extract_image` dispatches on the **content** (`startswith("http")`) rather than the declared `response_encoding`, so the wrong spec was simply never consulted. The defensive choice made a wrong doc a non-event. The `json_data_uri` handling stays regardless — it is cheap, and the data-URI shape may still be real on other models in the family.

**The general lesson, now measured twice over:** three families disagree at one field path, the documentation was wrong about which family does what, and only content-sniffing survived contact with the live API.

#### 3. A retry on a paid model is a NEW CHARGE, not a recovery

The retry budget was designed on the free lane, where trying again costs nothing and often works. On a prepaid model that reasoning inverts: the image was generated and billed **before** the response reached the program, so a retry does not recover the thing already paid for — it buys another one.

Two changes, both the user's call:

- **`PAID_MAX_ATTEMPTS = 1`.** A paid model gets one try and no retry. **Rate limits are exempt** — a 429 is refused *before* generating, so it is never billed, and capping it would fail jobs that cost nothing to recover. The free default dropped from 4 attempts to **3**.
- **An unreadable 200 on a paid model is now PERMANENT**, not transient. If the program cannot read the response, that is a fault to surface, not one to pay for repeatedly. On a free model the identical fault stays transient, because there it genuinely is free to retry.

**Deliberately NOT applied to the presigned-URL fetch.** There the image is already paid for and a retry re-downloads it rather than regenerating it — the one place where retrying is how you recover money already spent.


#### 4. FOUR of the eight silently RESIZE — and three of them are models whose sizes were called "published"

All eight requested sizes were accepted, but four came back different, at **HTTP 200 with no error**:

| Model | Asked | Delivered | Registry said |
|---|---|---|---|
| krea-turbo | 1328x752 | **1376x768** | estimated |
| krea-medium | 1328x752 | **1376x768** | estimated |
| nano-banana-2-lite | 1344x768 | **1376x768** | **published** |
| nano-banana-2 | 1344x768 | **1376x768** | **published** |
| p-image, flux2pro, both Recraft | — | **exact** | — |

The krea pair being approximate was expected — the registry already flagged their sizes as estimated. **The nano-banana pair is the correction**: CLAUDE.md and the registry treat Google's published dimensions as authoritative (`sizes_published=True`, which is what drives the `~ estimated` GUI readout), and they are not. Both families converge on the same **1376x768**, suggesting a shared gateway-side normalisation rather than four independent model quirks.

**Nothing was lost, and that is because of the Pollinations lesson.** `size_mismatch` and `actual_dimensions` are computed from the decoded bytes, so every sidecar records what actually arrived and the engine logged a warning on each. This is the third time the same failure shape has appeared — Pollinations' silent clamp, the content filter's black frame, and now this — and each time the answer was the same: **trust the bytes, not the response.**

The delivered size is *larger* than requested and keeps the ratio, so no image is degraded and no crop is warranted. The practical consequence is only that a size readout for these four is a request, not a promise.

#### 5. Recraft delivers WEBP, not the PNG its registry entry declares

Both Recraft models returned **WebP** where `output_format` says `png`. The magic-byte sniff caught it and both files were written `.webp` with contents matching, so this cost nothing — but it is a fourth independent confirmation that **the declared format lies across this lineup**. Recorded rather than "fixed" in the registry, since the sniff is the authority by design and `output_format` is documentation of intent.

#### 6. The presigned URL is not always a Cloudflare R2 URL

Three distinct hosts appeared, all fetched correctly by the same `json_url` path:

| Model | Host |
|---|---|
| p-image, both nano-banana, both Recraft | `ai-gateway-outputs...r2.cloudflarestorage.com` |
| krea pair | `gen.krea.ai` |
| flux2pro | `delivery.eu2.bfl.ai` |

The provider's own CDN is handed straight through. This makes the **"never send `Authorization` on the presigned fetch"** rule materially more important than it looked when the assumption was that the URL always pointed at Cloudflare's own storage: the token would otherwise have been forwarded to Krea's and Black Forest Labs' infrastructure. The rule was already correct; the measurement raises its stakes.

#### 7. Everything else the plan set out to test, confirmed

- **The `size` enum was accepted on both Recraft models** — no billed rejection. `recraft_size_string()` produced legal values and the client-side validation earned its keep by never being exercised.
- **`safety_tolerance: 5` accepted** on flux2pro; **`output_format: jpeg`** honoured (its `jpg`-spelling twin worked on nano-banana).
- **Seed handling is correct on all eight**: recorded where supported, `null` on all four seedless models (both Recraft, both nano-banana). No invented seed was ever written.
- **No black frames.** The safe prompt wording passed the filter on every model — and so did the *original* "warzone" wording on the free lane, so that vocabulary is not automatically refused. **The blocked-prompt billing question therefore remains unsettled**, since no refusal occurred to measure. The guide's "assume yes" stands as an inference.
- **Costs matched the estimator to the cent**: $0.251 for eight images, exactly as quoted.

#### 8. The SD degradation warning fired on the program's own DEFAULT — and pointed at a paid fix

Raised by the user after seeing it during this session's free runs, and it was a real usability fault rather than noise.

`max_safe_dimension` is 1024 on the three SD models, but the shipped default is **standard + 16:9 = 1536x864**. So a new user's very first free batch, on settings they never touched, printed a WARNING about duplicated structures and geometry drift — and the old text ended *"Use a klein model for this tier"*, which is a **paid** model. A free-lane user was being alarmed about a default and pointed at a bill.

**The fact is true and stays** — those models are trained near 1024px and genuinely drift above it, and suppressing it would leave users blaming their prompts for duplicated turrets. What was wrong was the framing. The text now states the trade-off, says outright that it is not a fault, and names the **free** remedy (drop a tier) before the paid one.

The general rule: **a warning about a default the program itself chose is a design problem, not a warning.** Either the default is wrong, or the message needs to read as a trade-off. Here the default is right — 1536x864 is 44% more pixels for the same money and usually worth it — so the message changed.

#### 9. Krea's poor composition is NOT prompt expansion — a correction

Stated during this session that krea "still twisted the prompt despite `creativity: raw`". **That was wrong and is corrected here.** The sidecar records `prompt_expansion: raw` and `original_prompt == final_prompt`; `creativity` is sent on every krea request, and there is no evidence the service rewrote anything.

What was actually observed was extra units appearing in the output on a singular prompt — the model's own compositional habit on a busy scene, not prompt expansion. A mechanism was inferred from a symptom. The honest statement is: **both krea models compose poorly on this prompt, cause unknown**, while p-image, flux2pro, Recraft and nano-banana honoured the singular wording.

Worth keeping because the failure mode is seductive: `creativity` exists, expansion would explain the symptom, and the explanation was reached without checking the field that records it.


#### 10. The SD models now get their OWN size table — asking for what they can render

Follow-on from #8, decided the same day after the comparison collage made the cost visible: the SD tiles were the worst in the lineup, and a large part of that was the program handing them 1536x864 when they are trained near 1024.

Rewording the warning (#8) fixed the message, not the problem. **The three SD models now own a `SIZE_TABLE_OVERRIDES` entry**, exactly like Pollinations, and Standard is capped at the training size: 16:9 → **1024x576**, 3:2 → 1008x672, 1:1 → 1024x1024, 2:3 → 672x1008, 9:16 → 576x1024. Computed, not eyeballed — each is the largest exact-ratio multiple-of-16 size with both dimensions ≤1024.

**High deliberately still exceeds it.** The ability to push past the limit stays, as an opt-in through the tier dropdown, and `size_warnings()` still fires there. A global "allow unsafe resolutions" checkbox was considered and rejected: the right value depends on which model is selected — harmless on klein and every gateway model, harmful on SD — so a global toggle would be a setting that is only ever correct for a subset, and the honest default would ship it off and unused.

**The general rule this and #8 share: if the program itself chose the setting, a warning about it is a design problem.** Either fix the default or reword the message. Here both were wrong, so both changed.

Cost note: Standard drops from 6 tiles to 4, so it is also cheaper — but it is genuinely less output, and anyone downscaling 1536x864 to 1080p loses headroom. That is the accepted trade, not an incidental win.

#### 11. Krea's expansion default moved from `raw` to `medium` — matching the vendor

Two things overturned the original `raw` default, and the first is a lesson about evidence rather than about krea.

**The evidence for `raw` was bad.** It was chosen partly because krea's output on a singular-subject prompt contained extra units, read at the time as expansion rewriting the text. The sidecar disproves it: `creativity: raw` was sent and `original_prompt == final_prompt`. Nothing was rewritten. A mechanism had been inferred from a symptom that merely correlated with it — the same failure shape as keying a UI string on `size_style`, one entry above.

**The documentation says the concern does not apply at our prompt lengths.** Krea's own docs and Runware's guide agree the API default is **`medium`** — not `low`, as a comment in `core/models.py` had claimed — and that a *detailed* prompt is polished rather than restructured: expansion makes lighting, colour and composition choices instead of rewriting the subject. Wholesale rewriting is what a five-word prompt gets, not a 660-character one. The style-suffix drift that motivated `raw` is a real risk on short prompts and largely not one here.

So the program now sends `medium`. Shipping `raw` meant paying krea prices while switching off the thing that makes krea worth choosing. **Not `high`**: that level takes deliberate liberty with style and mood, which a batch wants held constant across images. `KREA_API_DEFAULT_EXPANSION` records the vendor's default separately from the program's, so the two ideas stay distinct even while they agree.

#### 12. A disabled combobox that still shows a value reads as clickable

Reported by the user: selecting a model that does not support prompt expansion or filter control leaves those dropdowns greyed but still displaying a setting, so they look clickable and do nothing.

Same lesson the disabled numeric boxes already taught during the UI sanity pass — **a disabled control must show something honest rather than a leftover value** — simply not applied to the comboboxes. They now display the reason ("not supported by this model" / "not adjustable on this model") in place of a stale mode.

The placeholder is display-only and cannot be persisted: both readback helpers match on the visible label and fall through to the program default when nothing matches, and config is only written from the user's own `<<ComboboxSelected>>`, which a disabled combo cannot fire. Verified by launching the GUI and switching models, not by reading the code — per the standing rule for this class of string.


#### 13. klein's neuron cost RE-MEASURED — and the earlier 4.61/tile figure was wrong

Prompted by the user disbelieving a "6 free images/day" figure for klein 9B ("it's only twice as big as the 4B"). The doubt was right that the number was untrustworthy; the measurement went the other way.

Measured 2026-09-06 via the same `aiInferenceAdaptiveGroups` GraphQL query, one image each at 1536x864:

| Model | Neurons/image | Free images/day (10,000 allowance) | Program used to claim |
|---|---|---|---|
| klein 4B | **131.88** | **~75** | 361 |
| klein 9B | **1411.93** | **~7** | 6 |

**The 9B estimate was right by accident and the 4B estimate was wrong.** 9B had no measured rate and fell back to deriving the allowance from its $ price — the same derivation that was undercounting 4B badly — and happened to land near the truth. 4B's stored 4.613 neurons/tile produced 361/day against a measured 75.

**9B costs 10.7x more neurons per image than 4B, not the ~2x its parameter count suggests.** That is the substantive finding, and it is why 4B is the better buy by a wider margin than the names imply.

This **contradicts the 2026-09-04 reading** of ~4.61/tile recorded above. Both used the same query, so the difference is real rather than methodological — most likely the earlier figure divided by a tile count that did not match what was billed. Today's query returns `totalTiles = 0` for klein, so a per-tile rate can only be inferred from image count and requested size. **The durable lesson: neurons-per-IMAGE is what the API reports reliably; per-tile is inference layered on top of it.** The newer figure also sits closer to Cloudflare's published 26.05/tile than the old one did, which is weak corroboration.

Both models now carry a measured rate, and their labels and price notes say "free daily, then …" rather than a flat "paid" — for a small batch these are free, and calling them paid drove users toward genuinely more expensive models.

#### 14. Krea's prompt expansion is the model, not a setting — confirmed by side-by-side

Following #11, both krea models were re-run on the identical prompt with `creativity: medium` instead of `raw`. The difference is not subtle: at `raw` both produced muddled scenes with extra, incorrect units (the very output that was misdiagnosed as expansion *causing* the problem); at `medium` both produced exactly one of each requested unit, correctly coloured and placed.

So the original `raw` default was not merely unnecessary — **it was actively producing the bad output it was chosen to prevent.** Worth stating plainly, because the reasoning behind `raw` was sound in the abstract and still wrong in fact. The sidecar confirms `original_prompt == final_prompt` in both runs, so the improvement comes from the model's own conditioning, not from text being rewritten.

#### 15. Pollinations is genuinely weak at multi-subject scenes, prompt length aside

Tested rather than assumed, after the collage showed both Pollinations models producing poor results and the working theory was that the 660-character prompt had unfairly handicapped them.

A deliberately short 190-character prompt with the same four subjects still produced a single subject and ignored most of the brief — though it did honour the watercolour style, which the long prompt had not. FLUX.1 Schnell uses a T5 encoder with a far larger budget than CLIP, so truncation never explained its result in the first place.

**Conclusion: the "they were just mis-briefed" defence holds for the three SD models and does NOT fully hold for Pollinations.** Their weakness on a four-subject composition is real. The comparison collage's disclaimer says this in the honest form — a multi-subject scene is the hardest thing to ask of a small model, and these do markedly better on one subject — rather than implying every weak tile is purely an artefact of prompt length.

#### 16. A price label typed by hand goes stale; derive it

The collage originally carried hand-typed price strings, and its first version labelled BOTH klein models "FREE ~300/day" — wrong for 4B (75) and badly wrong for 9B (7). The registry already knew the right answer for each.

The labels are now computed by `price_label()` from `is_free`, `free_images_per_day` and `cost_per_1000`, which also makes the three genuinely different billing lanes visible: free, free-then-paid on the neuron allowance, and prepaid credit from image one. **Anything a doc or promo asset states about price should be read out of `core/models.py`, never retyped beside it** — that file is the single source of truth precisely so a second copy cannot drift.


#### 17. The klein neuron rate CHANGED between 2026-09-03 and 2026-09-06 — Cloudflare corrected an under-billing

The 4.76x jump in #13 was not a measurement error, and this is the explanation. Investigated after the user pointed out that a real 108-image batch had used only ~2,990 of 10,000 neurons — which is the 361/day the program used to claim.

**The old batch is on disk and rules out every confound.** All 108 sidecars: `model=klein4b`, requested *and* delivered `1536x864`, identical settings, file dates 2026-09-03. Byte-identical conditions to today's test. So:

| Date | Neurons/image | Implied free images/day |
|---|---|---|
| 2026-09-03 (108-image batch) | **~27.7** | 361 |
| 2026-09-06 (3 images, two readings) | **131.88** | 75 |

**The decisive check is against Cloudflare's PUBLISHED rate**, which the docs give as 26.05 neurons per output 512x512 tile for klein 4B, and 1363.64 per first MP + 181.82 per subsequent MP for 9B. At 1536x864 (6 tiles, 1.327 MP):

| Model | Published prediction | Measured today | Agreement |
|---|---|---|---|
| klein 4B | 156.30 | 131.88 | within 16% |
| klein 9B | 1423.11 | 1411.93 | **within 0.8%** |

**Today's billing matches the published price sheet; September 3rd's did not — it was running at roughly 1/5.6 of the documented rate.** The conclusion is that Cloudflare was **under-billing image models and has corrected it**, not that they raised prices. No changelog entry, no community reports found for either reading.

**This retires the 2026-09-04 finding above**, which recorded ~4.61 neurons/tile as authoritative precisely *because* it contradicted Cloudflare's published 26.05 by 5.7x. That finding's own reasoning — "where a measurement contradicts the documentation, the measurement wins" — is a good rule that failed here, and the failure mode is worth naming: **a measurement beats documentation about how a system BEHAVES, but a billing rate is a published commitment, and a measurement 5.7x cheaper than the price sheet is more likely a bug in your favour than a discount.** A measured value far off a published one in the *cheap* direction should be treated as provisional and re-checked, not banked.

**Practical consequence, and it is a customer-facing one:** any statement of "~361 free images/day on klein 4B" is now wrong and should be corrected to ~75. The figure was published in good faith from a real measurement; it is simply no longer true.

**Nothing about the dollar pricing changed.** klein 4B is still $1.72/1000 — that always came from the published price, not from the neuron reading, and it stays correct. Only the free-daily-allowance estimate moved.

### The `result.image` field carries two incompatible shapes — confirmed 2026-09-05

> **PARTLY SUPERSEDED 2026-09-06 by the measured section above.** The claim that p-image returns a `data:` URI is **wrong** — it returns a presigned URL. The nesting shown below is also one level too shallow. The reasoning about content-sniffing beating declared encodings held up and is why the wrong shape cost nothing.

**Provenance, stated plainly:** this entry is from **Cloudflare's published model pages**, not from a live call — no prepaid credit was available to spend. It is recorded here anyway because it directly contradicts an assumption the program was about to be built on. Everything below is doc-derived until a paid call confirms it, and the "verified at zero cost" field lists it builds on came from the API's own 400 rejections.

The native klein models return **bare base64** at `result.image`. The Pruna/gateway models return a full **data URI** at the **same field path**:

```json
{"state": "Completed", "result": {"image": "data:image/jpeg;base64,..."}}
```

Confirmed identical on `pruna/p-image` and `pruna/p-image-edit`, so it is family-wide rather than a doc typo.

**Why this matters more than it looks — VERIFIED LOCALLY:** `base64.b64decode()` does not raise on the data-URI form. Checked directly: decoding `data:image/jpeg;base64,<8-byte PNG header>` returned **23 bytes of garbage** with no exception. It skips the non-alphabet prefix characters and returns **decoded garbage**, which then fails the image-decode check as a *transient* error and gets retried — burning the retry budget on every job of a paid batch, with a misleading error. The prefix strip is therefore driven by **the content** (`startswith("data:")`), never by the declared `response_encoding`, since the two shapes are indistinguishable by field name.

**This also corrects the wishlist doc**, which said P-Image returns a *download URL* and warned an extra-GET mechanic would be needed. It does not, and there is none to build.

### Gateway models are billed from prepaid credit, not the neuron allowance

A different billing lane from the native five, with three consequences the original code got wrong:

- **`free_images_per_day` is `None` for two unrelated reasons** — a free model, or a paid gateway model with no allowance to draw on. The CLI's old `else` branch printed *"free model — no neuron cost"* for **any** `None`, which was flatly wrong for a $5/1000 model. Now three branches.
- **`402 Insufficient balance` is a real, reachable state** and is fatal for the batch — mapped to `QuotaExhausted`, never retried, so it cannot burn a job's retry budget against a wall.
- **Tile counts are meaningless here.** Gateway models bill flat per image, so the "generate large, downscale locally" headroom does not exist. `bills_per_tile` suppresses the readout rather than showing a number that implies it.

### The multiple-of-16 rule binds harder than the pixel cap — computed 2026-09-05

p-image accepts 256–1440 and requires multiples of 16. The obvious 16:9 size at that cap is **1440x810** — and it is **illegal**, because 810 is not a multiple of 16. The largest legal exact-ratio 16:9 is **1280x720**.

A first draft of `SIZES_PIMAGE` had 1440x810 in it. A three-line check caught it before it could become a permanent 400 on every 16:9 job.

**Compute these tables, never eyeball them:**

```python
best = max((rw*k, rh*k) for k in range(1, 2000)
           if rw*k <= CAP and rh*k <= CAP and (rw*k) % 16 == 0 and (rh*k) % 16 == 0)
```

Consequence: p-image's best 16:9 is **smaller** than the program's Standard 16:9 (1536x864), and Standard and High resolve to the same size for 4 of 5 ratios. The GUI states this explicitly, because a tier dropdown that silently does nothing reads as a bug.

---

### krea returns a presigned URL — the extra-GET mechanic is real, just not where predicted — 2026-09-05

Doc-derived (Cloudflare's model pages for both krea models), not from a live call.

`result.image` on `krea/krea-2-medium` and `krea/krea-2-medium-turbo` is a **presigned URL**, not image data:

```json
{"state": "Completed",
 "result": {"image": "https://examples.aig.cloudflare.com/krea/krea-2-medium/default.png"},
 "gatewayMetadata": {"keySource": "..."}}
```

So the same `result.image` path now carries **three** mutually incompatible shapes across the lineup — bare base64 (klein), a data URI (p-image), and a URL (krea). Detection is by content, never by declared encoding.

The wishlist doc predicted this mechanic for **p-image** and was wrong about the family, but right that one model would need it. Two consequences worth writing down:

- **The fetch must NOT carry the `Authorization` header.** The URL is already signed; forwarding the Cloudflare token to whatever host the signature points at would leak the credential to a third party. There is a test asserting the token never appears in the outgoing headers.
- **Every fetch failure is TRANSIENT, not permanent.** The image was generated and **billed** before the URL was handed over, so a failed fetch means a paid image was lost. Retrying is the only way to recover it, and marking it permanent would throw away something the user already paid for.

### krea cannot render at the program's Standard size, let alone High

`resolution` accepts **`1K` and nothing else** — the validator rejects every other value, and width/height are not accepted at all.

The wishlist doc noted krea "cannot serve the High tier". It is worse than that: **1K at 16:9 is roughly 1328x752, below the program's Standard 1536x864 too.** So the quality tier does nothing whatsoever for these two models, and `has_tier_ladder()` now disables the dropdown and says why — a control that silently does nothing reads as a bug rather than a model limitation.

**Krea does not publish what "1K" resolves to per ratio**, and it could not be probed without spending. `SIZES_KREA` holds ~1 MP exact-ratio estimates. This is safe to be wrong about *by construction*: the program never sends those pixels (the model takes a ratio enum), so a bad guess cannot produce a bad request — it only affects a displayed number, which is shown with a `~` and the word "estimated". The true size is sniffed from the returned image into `actual_dimensions` and written to the sidecar metadata, so the first real run records the fact even though the estimate stays.

### krea's four style dials all default to neutral — 2026-09-05

`creativity` (`raw|low|medium|high`, default `low`), and `intensity`/`complexity`/`movement` (integers -100..100, default 0). Recorded in `KREA_STYLE_DIALS`.

**Three of the four defaults are the neutral value**, so omitting `intensity`, `complexity` and `movement` is byte-for-byte equivalent to sending them — nothing is skipped by leaving them out, and they stay out.

**`creativity` is the exception, and it is now exposed** (superseding the first version of this entry, which left all four unset). Its default is **`"low"` — expansion ON**, not neutral. So a caller who says nothing gets prompts silently rewritten before generation, with no indication in the output that it happened.

The program therefore sends `creativity` **always**, defaulting to **`"raw"` (off)** — deliberately not the API's default. Rationale, which is specific to this program rather than general:

- The text sent is **prompt + style suffix**, and expansion rewrites the **concatenated whole**. It can reword the style addon as readily as the subject.
- That is the worse of the two failures: the style suffix is the part meant to stay **identical across every image in a batch**. Silently varying it defeats the entire point of having one.
- A user seeing images that do not match their prompt has no way to discover why — there is no error, and nothing in the metadata says the text was changed.

Exposed as a control (GUI dropdown + `--prompt-expansion`) rather than hardcoded off, because expansion genuinely helps a short or sparse prompt. The GUI states inline which way it is set, so it is visible without hovering a tooltip.

### The img2img fields — PARTIALLY REVERSED 2026-09-19

**The blanket "permanent skip" below was reversed for ONE narrow case: a single global style-reference image.** The original ruling stood on two premises — that these fields are for single-image *editing*, and that they need a hosted URL. Measured against the live API, both are false for part of the lineup. The reversal is deliberate and user-approved; the *rest* of the ruling stands, and the banned-fields test must be narrowed rather than deleted, or it silently stops guarding krea and recraft too.

**What the field actually is, per model — MEASURED 2026-09-19 against the live gateway:**

| Model | Field | Encoding accepted | Local file? |
|---|---|---|---|
| klein 4b / 9b | `input_image_0..3` | **multipart binary** | **Yes, direct** |
| nano-banana-2 / Lite | `image_input[]` | **https URL *and* base64** (both confirmed) | **Yes, base64** |
| flux-2-pro | `input_images[]` | https URL or `data:` base64 (documented) | Yes |
| krea x2 | `image_style_references[].url` | **https URL ONLY** | **No** |
| recraft x2 | top-level `image` | uri | No |
| p-image | *none — no such field* | — | No |

**krea explicitly refuses base64**, and that is a measured refusal rather than an inference: a `data:` URI returns `Validation error at image_style_references[0].url: Must be an HTTP(S) URL`, while a real https URL is genuinely fetched (an unreachable host returns `failed to fetch`). So krea's reference feature is unreachable for a desktop tool without hosting the user's art on a public URL. Not worth a new external dependency. Note this is the model whose field is *described* as "Reference images to drive the visual style (up to 10)" with a per-image `strength` — the best-fitting field in the lineup, and the one that cannot be used.

**`controls.image` does not exist on recraft.** The schema's `controls` object contains only `colors` and `background_color`. There is a separate top-level `image` field instead. The earlier note here was wrong about the shape; the practical conclusion (not sent) is unchanged.

**p-image has no reference field at all** — ten properties, none of them an image. It does expose `lora_weights` (HuggingFace URLs), a different and much heavier route to style consistency.

### klein's reference images: the documented 512x512 cap is WRONG, and there is an undocumented MINIMUM

MEASURED 2026-09-19 on `flux-2-klein-4b`, and this contradicts Cloudflare's own changelog and blog post, which both state *"up to 4 512x512 images"* and *"all input images must be smaller than 512x512"*.

- **There is no 512px maximum.** 640x480, 1024x1024, 2048x2048 and **4096x4096 all returned HTTP 200.** Nothing was rejected for being too large. The program should still downscale, but for *upload size and speed*, not because the API demands it.
- **There IS a hard minimum of 64px on EACH side, undocumented anywhere.** Bisected exactly: 63x63 rejected, 64x64 accepted. 56, 60, 62 all rejected. `64x48` is **rejected** — so the floor applies per-dimension, not to the total or the longest edge.
- Rejection is HTTP 400 `AiError: Invalid input`, code **8001** — a generic message that names neither the field nor the size, so the program must validate this client-side or the user gets an unexplainable failure.
- **No square requirement.** 320x180 and even 512x64 were accepted.
- **PNG, JPEG and WebP all accepted**, passed as ordinary multipart file parts with a filename and content-type.

**The 64px floor is the finding that matters for the sprite use case**, because it is exactly the range retro sprites live in: a 16x16 or 32x32 sprite — the whole motivating case — is **rejected outright**. It must be upscaled to at least 64px before sending, and for pixel art that upscale must be **NEAREST**, or the resampler blurs away the hard pixel edges that are the entire style being referenced. This is the one place the program must not use its usual smooth resampling.

### Two things the reference-image PLAN got wrong, found while building it (2026-09-19)

Both were caught by tests rather than by reading, and both are the same shape: a number written down plausibly instead of measured.

**1. Appending `None` to the filename hash is NOT backward compatible.** The plan said to append the reference hash at the end of `image_hash_parts()` and "pass `None` when no reference is used, so every existing batch keeps its current filenames". It does not: `_hash_tag()` joins the parts with ``, so a trailing `None` renders as an empty FIELD and the digest changes. Every image in every batch made before the feature would have been renamed, so each batch would have looked unfinished, resumed, and regenerated — **a full re-bill on a paid model, caused by a filename change nobody asked for.** The part is therefore **omitted entirely** rather than appended as `None`, and `test_hash_parts_are_unchanged_when_no_reference_is_set` pins it. Verified with a three-line check, exactly as the p-image size table was.

**2. "Follow the round-trip diff when the two signals disagree" is wrong in one direction.** The plan's pixel-art detector uses a colour count and a nearest half-scale round trip, and says to trust the round trip on a disagreement because mis-applying LANCZOS to a sprite is the visible failure. That is right for JPEG'd pixel art (few colours, high diff) and **wrong for a smooth gradient**: a gradient survives the round trip at 0.004 — it has no fine detail to lose, so halving and doubling changes nothing — while holding ~196,000 colours, and nearest is flatly the wrong resampler for it. **The COLOUR COUNT carries the veto**, not the round trip. Measured on synthetic cases, and both directions are pinned by a test.

There was also a **unit bug** in the first implementation of the same detector: Pillow's `ImageStat` returns a 0–255 mean while the plan's measured thresholds (0.000 / 0.041 / 0.529) are on a 0–1 scale, making the cutoff ~25x too strict — JPEG'd pixel art scored 6.01 against a 0.10 threshold and was classified as a photo. `_round_trip_diff()` now divides by 255 explicitly, with the reason spelled out rather than folded into the constant.

**And one thing the plan omitted entirely: `find_batch()`.** The plan put the reference into the filename hash and stopped there. That is exactly half of the fix the style-suffix bug already taught this program — CLAUDE.md records it as *"fixing only one leaves the symptom"* — so the reference hash is now a column on `batches` and part of the batch identity too. That needed the first real schema MIGRATION in the project: `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so a new column in `SCHEMA` reaches a fresh database and no other, and every `.batchgen.db` already on disk would have raised on the first query naming it. `JobStore._migrate()` adds it with a `DEFAULT ''`, so a pre-existing batch reads back `''` and reattaches exactly as it always did — verified against a hand-built legacy database.

### The RECOMMENDED reference resolution is ~1 MP — and no vendor publishes one

Researched 2026-09-19 across Cloudflare, Black Forest Labs, fal.ai, Replicate and the FLUX.2 model cards. **None of them states a recommended input resolution for reference images.** That absence is itself the finding: anyone waiting for an official number will not get one, so the target below is reasoned from the surrounding evidence rather than quoted.

What IS established:

- **~1 MP is the ecosystem convention.** The standard ComfyUI FLUX.2 reference workflow scales inputs with `ImageScaleToTotalPixels` to **1 megapixel**, which is the closest thing to a de-facto community default.
- **Above ~4000px is measurably BAD.** `black-forest-labs/flux2` issue #42 reports that editing with inputs wider or taller than 4000px returns output that is "heavily blurred or degrade[s] into noise-like artifacts", and raising steps from 4 to 20 does not fix it. Open, no maintainer reply. So the API accepting 4096x4096 (measured above) does **not** mean 4096 is a good idea — accepted and recommended are different bars, the same lesson the SDXL-Lightning guidance probe taught.
- **Input megapixels are BILLED on some providers.** fal prices editing on input MP as well as output ("1 MP input + 1 MP output"). Cloudflare's klein bills per image rather than per input MP, so this does not affect *this* program's cost — but it shows inputs are treated as real pixel data, not thumbnails, and it is a reason not to send 4096px casually.
- **Reference size does NOT affect generation latency.** MEASURED on klein-4b at a fixed output of 1536x864: 512px ref 4.7s, 1024px 4.6s, 2048px 4.2s, 4096px 4.9s — flat within noise. Oversized references cost **upload bandwidth only** (2.5KB / 7.6KB / 25.5KB / 89.5KB as PNG). So the argument for downscaling is quality and upload time, never generation time.
- **The floor is corroborated.** Third-party FLUX.2 klein documentation independently states the model supports "resolutions from 64x64", matching the 64px minimum measured here exactly.

**Conclusion for this program: target ~1 MP, clamp to the 64px floor, never exceed 2048px on a side.** Upscale anything under 64px (NEAREST for pixel art), downscale anything over ~1 MP (LANCZOS for photos/art), and leave everything between alone. Do not send 4096px even though it is accepted.

### CORRECTION 2026-09-19: practitioner guidance DOES exist — the FLUX preferred-resolution list

The "no vendor publishes one" note above stands for the **vendors**, but it was too quick a conclusion overall: the community established this and it is traceable to code. Found on a second look, prompted by the user asking whether independent testers had published anything.

**`PREFERED_KONTEXT_RESOLUTIONS`** — a constant in ComfyUI's `nodes_flux.py`, adopted downstream (e.g. InvokeAI issue #8374 requesting it). 17 entries, and analysing them shows the list is not arbitrary:

| Property | Value |
|---|---|
| Megapixels | **1.035 – 1.062 MP** — every entry within 2.8% of ~1.05 MP |
| Divisibility | **all 17 are multiples of 16** (only 1024x1024 is a multiple of 64) |
| Aspect range | **0.429 to 2.333 — exactly 3:7 to 7:3** |

```
(672,1568) (688,1504) (720,1456) (752,1392) (800,1328) (832,1248) (880,1184)
(944,1104) (1024,1024) (1104,944) (1184,880) (1248,832) (1328,800) (1392,752)
(1456,720) (1504,688) (1568,672)
```

**This independently confirms the ~1 MP target reasoned above, and it adds the piece that reasoning could not supply: a hard aspect-ratio window.** The endpoints are exact — 3/7 = 0.4286 and 7/3 = 2.333 — so the list *is* the ratio guard, not merely a size table. Corroborated separately by the widely-repeated "Flux supports aspect ratios from 3:7 to 7:3".

Also community-established, weaker but consistent: **inputs should be at least 1024px on the short side**, **pre-resize rather than letting a node handle mismatched sizes** (more predictable results), and divisibility avoids compression artifacts.

**Caveat on provenance:** this is FLUX.1 **Kontext** guidance, and the program's models are FLUX.2 klein, nano-banana and flux-2-pro. It is the same architectural family and the same reference-conditioning mechanism, and the ~1 MP figure matches the ComfyUI FLUX.2 workflow default independently — but it is **community-derived and cross-family**, not a vendor statement about these exact models. Treat it as a good default, not a hard law, and do not claim it is official.

**What ~1 MP means per ratio** (computed, multiples of 16 — do not eyeball these):

| Ratio | ~1 MP size | MP |
|---|---|---|
| 1:1 | **1024x1024** | 1.05 |
| 16:9 | **1360x768** | 1.04 |
| 4:3 | 1184x880 | 1.04 |
| 3:2 | 1248x832 | 1.04 |
| 9:16 | 768x1360 | 1.04 |

Note 16:9 is **1360x768, not 1280x720** — the intuitive "nice" number is 0.92 MP and leaves ~12% of the budget unused, the same trap the SIZES tile-packing table exists to avoid.

### The 3:7–7:3 window rejects animation STRIPS, and that is the useful case to catch

Checked against real sprite shapes, because this decides what the program must refuse:

| Input | Ratio | Verdict |
|---|---|---|
| 16x16, 32x32, 64x64 sprite | 1.000 | OK |
| 16x32, 32x48 character | 0.50 / 0.67 | OK |
| **256x256 sprite SHEET** | 1.000 | **OK** |
| 128x32 four-frame strip | 4.0 | **Reject** |
| 256x32 eight-frame strip | 8.0 | **Reject** |
| 384x32 twelve-frame strip | 12.0 | **Reject** |

So **single sprites and square-ish sheets pass; horizontal animation strips fail**, and a strip is exactly the kind of file a user would plausibly drag in. Stretching one to fit would distort every frame; padding a 12:1 strip to 7:3 wastes most of the canvas on blank space and shrinks the actual sprite content toward illegibility. **Rejecting with an explanation is the honest answer** — tell the user to crop a single frame or tile the strip into a grid, which is also better style-reference input than a row of near-identical frames.

---

### There is no reference STRENGTH field anywhere, and prompt wording is a nudge, not a dial (2026-10-15)

**No model that takes a local reference exposes a strength or weight.** klein's full field list is `prompt`, `width`, `height`, `guidance`, `seed`, `input_image_0..3`; nano-banana and flux-2-pro have nothing either. The only per-image `strength` in the lineup is krea's `image_style_references[].strength`, and krea refuses a local file (see above). So the Influence dropdown writes a sentence into the prompt — the only lever there is.

**MEASURED on klein-4b, 9 images, 2 seeds (4242, 777), 1:1 Standard 1024x1024**, one long pixel-art sprite-sheet prompt and a 1280x1280 AW2-style sprite-sheet reference (sent at 1024x1024, nearest):

| Condition | Result |
|---|---|
| No reference | Generic grey/tan tanks, 4x3 grid instead of the requested 4x4 |
| Reference, no sentence | Transformed: the reference's orange-red palette, helmeted crews, a proper 4x4 grid |
| + "Loosely inspired by the art style of image 0." | **Indistinguishable from no sentence** on both seeds — near-identical layouts. Cut. |
| + "In the art style of image 0." | Visible variation, no consistent direction vs. no sentence |
| + "Closely match the art style, colour palette and rendering of image 0." | Most visible change on both seeds (chunkier, closer hue) — and on seed 4242 it **overrode "Flat pure chroma green background" and rendered on WHITE** |

Conclusions: **the reference alone does nearly all of the work**; a sentence is a nudge on top. Two levels survive because each produced a visible change, but they do **not** form a reliable ladder. Asking to match the reference's *colours* competes with colour instructions in the prompt, which is why the GUI and guide warn about Strong specifically. One prompt and one reference — a small sample, enough to cut the level that did nothing and not enough to claim a ranking.

**SUPERSEDED the same day by user decision:** the shipped levels are None / Subtle / Medium / Heavy / Exact with the user's own short wording, untested. The measurement above stays as background, not as the spec.

"image 0" is klein's documented index convention (Cloudflare's own example). nano-banana and flux-2-pro are given "the reference image" instead — **untested**, chosen because neither documents an index convention.

## Cloudflare Workers AI

### API token needs READ ONLY — verified 2026-08-31

**The program never writes anything to Cloudflare.** It calls exactly two endpoints:

| Endpoint | Method | Used for |
|---|---|---|
| `/accounts/{id}/tokens/verify` | GET | the Check Credentials button |
| `/accounts/{id}/ai/run/{model}` | POST | every image |

`ai/run` is a POST, but it is *inference*, not configuration — it creates no resource and changes no account setting. **Tested directly with a "Read all resources" token: both the free JSON path (SDXL Lightning) and the paid multipart path (FLUX.2 klein 4B) returned HTTP 200 and real image bytes.**

This **supersedes** the earlier claim in CLAUDE.md that the token needs *Workers AI — Edit*. That was taken from Cloudflare's own dashboard template description and never tested. A read-only token is sufficient, and it is what `guide.md` should recommend: it is both easier to explain and less dangerous if leaked.

> **Gotcha:** validate with `/accounts/{id}/tokens/verify`, **not** `/user/tokens/verify` — the latter returns 401 for a perfectly valid account token. Also note `verify` returns only `{id, status}`; it does not list the token's permissions, so there is no way to check grants programmatically.

### The free models really are free — measured 2026-08-30

15 images across `stable-diffusion-xl-lightning`, `stable-diffusion-xl-base-1.0` and `dreamshaper-8-lcm` billed **0 neurons**, with step counts recorded correctly (so telemetry was working, it simply charged nothing).

**But `totalNeurons` cannot back a quota UI.** In the same test `flux-2-klein-4b` — which definitively bills at $1.72/1000 — *also* reported 0 neurons. A billed model reading zero means the field is not a dependable meter. **Spend is tracked client-side** from the model and tile count; "images remaining today" can only ever be an estimate.

### Delivered image format per model — measured 2026-08-31

The `content-type` header **lies**. Measured by sniffing magic bytes on live generations:

| Model | Declares | Actually returns |
|---|---|---|
| `stable-diffusion-xl-lightning` | `image/png` | **JPEG** |
| `stable-diffusion-xl-base-1.0` | `image/png` | PNG |
| `dreamshaper-8-lcm` | `image/png` | PNG |
| `flux-2-klein-4b` / `9b` | — | JPEG |
| Pollinations (both models) | — | JPEG |

Recorded as `ModelSpec.output_format` and shown in the GUI's model dropdown. **Never hardcode `.png`; always sniff.**

### Response encoding differs per family — measured 2026-08-30

- **SD family** (lightning, sdxl-base, dreamshaper) → raw image bytes in the HTTP body
- **klein models** → base64 inside a JSON envelope at `result.image`

### Content filter returns HTTP 200 + a black image — measured 2026-08-30

A blocked prompt comes back `200 OK` with a byte-identical all-black frame. No error field, no distinct status code. Without a check, a batch would save hundreds of black images and report 100% success.

`imagecheck.is_blank()` rejects flat-colour output as a **permanent** failure (never retried — the prompt is the problem). Validated with zero false positives.

**The filter is erratic.** On a later re-test, both prompts that previously returned black frames came back as real varied images; conversely it once fired on "a simple blue circle on a white background". Do not conclude from a clean run that it is gone.

### High tier is klein-only, and the tabled sizes were unreachable

SD models are trained at ~1024 and degrade above it. klein's hard ceiling is 1920, so the tabled 16:9 High size (2048x1152) was servable by *no* model — SD renders it badly, klein rejects it outright. `SIZES_KLEIN_HIGH` substitutes the largest exact-ratio, multiple-of-16 sizes inside klein's range (16:9 High → **1792x1008**, 8 tiles, $2.29/1000).

**High tier confirmed worth keeping** (2026-08-31, side-by-side at seed 4242): no duplicated structures, no geometry drift, no edge artifacts. **Its real cost is time, not money — 16.1s vs 9.8s per image, 64% slower**, which matters more than the price on an overnight batch.

### SD at Standard is fine — measured 2026-08-31

`max_safe_dimension=1024` is one threshold covering very different outcomes. At High (2048px) SD genuinely falls apart, but at Standard (1536x864) SDXL Lightning produced a coherent scene with no duplicated structures or geometry drift. Reference images in `out/sizecheck/` — the *Draft* render is actually the weaker image.

The GUI therefore **grades** the warning: past 1.75x the safe limit it is a warning, below that a calm note. The registry value was left alone; this is a presentation decision.

---

## Pollinations

### An API key does NOT lift the concurrency limit — measured 2026-08-31

**This corrects an earlier guess of mine (`max_concurrency = 4 if has_key`), which caused real 429 errors in use.**

The queue limit is **per IP address** and a key does not raise it:

```
"Queue full for IP: ...: 1 requests already queued (max: 1)"
```

| Test | Result |
|---|---|
| 6 **serial** keyed requests, unique prompts, no delay | **6/6 succeeded** |
| Overlapping pairs, Bearer header | 429 |
| Overlapping pairs, `token` query param | 429 |

A key raises **quota** and shortens the inter-request gap (15s → 1s). It does **not** allow two requests at once. `max_concurrency` is 1 in both modes.

> **Beware the cache when probing this.** A repeated prompt+seed is served in under a second instead of being generated, which made an early concurrent burst read as 2/2 successful. Probe with **unique prompts** or the measurement is meaningless.

Verified after the fix: a 4-image keyed batch runs **4/4 with zero 429s**. Throughput is genuinely slow regardless (~45s per generated image).

---

## Local image handling

### Converting JPEG → PNG recovers nothing — measured 2026-08-31

On a real generated image:

| | Result |
|---|---|
| Max channel difference after JPEG → PNG | **0** (pixel-identical) |
| File size | 44,773 → 367,377 bytes (**8.2x larger**) |

PNG faithfully stores whatever it is given; handing it a decoded JPEG stores the JPEG's *losses* losslessly. Choose a format for what you need to do with the files, never for quality.

### WebP was dropped

A JPEG → WebP → JPEG round trip measured up to **36/255 channel drift**. Since WebP is poorly supported by viewers and editors, its normal fate is being converted back — i.e. a lossy re-encode for no benefit. Formats offered are Keep original / PNG / JPEG.

### Pillow is not optional

`is_blank()` (the content-filter guard), `decodes()` and `dimensions()` all need it. The format converter added **zero** new dependencies — Pillow was already mandatory.

---

## Windows / filesystem

### Filenames must stay short

The classic `MAX_PATH` limit is 260 characters for the **whole path**, and output folders can be deeply nested. Names were ~76 characters and are now ~52.

**Words are taken from both ends of the prompt.** Plain head-truncation kept only the boilerplate opening that every prompt in a batch shares, so `...field at day. Cloudy` and `...forest at dawn. Rainy` produced near-identical names. Covered by a test.

### Environment variables set with `setx` are invisible to a running process

Windows only passes environment variables to processes started *afterwards*. This is why the original "set an env var, then restart" credential flow did not reliably work, and why keys are now entered in the GUI and saved to `credentials.json`.

---

## GUI / ttkbootstrap 1.20.2

### `style.configure("TScrollbar", ...)` crashes at startup

ttkbootstrap intercepts it and re-runs `element_create()` on already-registered image elements:

```
_tkinter.TclError: Duplicate element Horizontal.TScrollbar.thumb
```

Scrollbars pick up the injected theme palette on their own. Do not style them.

### `ttk.LabelFrame(padding=)` crashes

Known issue at this version — use `_tk_ttk.LabelFrame` (stdlib) everywhere. See `!standard python RC/ttkbootstrap_labelframe_fix.md`.

### The stock ToolTip renders off-screen and flickers

`ttkbootstrap.widgets.tooltip.ToolTip` places itself at `pointer + (25, 10)` with **no bounds check**, and re-positions on every motion event. Correcting the position *after* the base class placed the window drew one frame in the wrong spot — the visible flicker.

`gui/tooltip.py` overrides `show_tip` to build the window hidden, measure it, compute the final in-bounds position, then show it. `move_tip` is a deliberate no-op.

### The mouse wheel changes Combobox/Spinbox values

Tk cycles these controls whenever the pointer is over them, so inside a scrolling tab, scrolling past a dropdown silently changes a setting. Blocked centrally by walking the widget tree after build, so a control added later cannot reintroduce it.

### Labels that appear and change length make sections jump

Any label whose text appears, changes length, or vanishes resizes its frame. Use `reserve_lines()`, and **measure the longest case** — reserving 3 lines where the text wrapped to 4 left a 12px jump. Fixed `wraplength` values clip on a narrower window; `autowrap()` rebinds them to the real container width.

**Revised 2026-08-31: `reserve_lines()` is now a high-water mark, not a fixed reservation.** Holding the height unconditionally traded one visible fault for another — the Provider tab has several labels that are empty most of the time (`size_warning`, `budget_label`, `param_note`, `provider_note`, `creds_label`), and together they held roughly 150px of permanent blank space between real controls. The row now grows to fit whatever text is set, never shrinks while text is present (so a shorter replacement message still cannot cause a jump), and collapses to zero when the label is empty. The `lines` argument is now the ceiling rather than the reservation.

**The subtlety that made the first attempt wrong:** `<Configure>` does not fire when a label's text is merely *cleared*, so an emptied label kept its old height forever — the exact dead space the change was meant to remove. `reserve_lines()` therefore also wraps the label's own `configure`/`config` and re-checks on idle, which catches every text change. Verified: empty → 0, long text → 96, shorter text → 96 (no jump), cleared → 0.

Likewise, pin grid columns to a `minsize` and give changing readouts a fixed `width`, or selecting a different value shifts the controls sideways.

## Prompt length: the encoder truncates silently, and the budget is per-model

Added 2026-09-02, with the soft character counters.

Every model here drops whatever runs past its text encoder's token limit. There is **no error, no warning, and nothing in the image** to show that the tail of a prompt never arrived — which is exactly why the counters exist. A user who appends a long style suffix to an already-long prompt can lose the suffix entirely and never find out.

The budgets are genuinely different per model family, so a single number in the UI would be wrong for half the lineup:

| Family | Encoder | Token limit | ~Characters |
|---|---|---|---|
| SD (lightning, sdxl, dreamshaper) | CLIP ViT-L | **77** incl. start/end, so ~75 usable | **~300** |
| FLUX.2 klein (4b, 9b) | Qwen3/T5, `max_length=512` | **512** | **~2000** |
| Pollinations FLUX.1 schnell | T5 | ~256 | ~1000 |

This is the measured basis for "long descriptive prompts pay off on klein and are largely wasted on SD" — the SD models are not ignoring your detail out of weakness, they are never being shown it.

**Characters are a proxy, not the unit.** A token is roughly 4 characters of ordinary English, but a comma-separated keyword list — which is precisely what a negative prompt is — tokenizes considerably worse, so it overflows earlier than its character count suggests. `CHARS_PER_TOKEN = 4.0` in `core/prompts.py` therefore errs on the safe side, and the counters are labelled as advice throughout.

**Nothing in the program truncates a prompt.** The limits live in `ModelSpec.prompt_soft_limit` / `prompt_hard_limit` and drive a three-level label (ok / near / over) and nothing else. Enforcing them would be worse than the problem: some prompts tokenize far better than the estimate, and silently cutting a user's text is the same fault as the API's, committed one layer earlier.

Sources: CLIP's 77-token context is the documented Stable Diffusion limit; FLUX.2's text encoder tokenizes at `max_length=512`.

## Positive and negative prompts have SEPARATE token budgets

Established 2026-09-02.

They do not compete. Classifier-free guidance runs the model twice per step — once conditioned on the positive prompt, once on the negative — and each pass gets its own text encoding with the full token budget. A 300-character positive prompt costs the negative prompt nothing. The API mirrors this: `prompt` and `negative_prompt` are separate fields in the request body.

**Consequence for preset design:** a heavy universal negative is nearly free. Terms are left out of a negative for being **inert** — anatomy fixes do nothing for an empty landscape — never for being expensive. An earlier comment in `utils/config.py` claimed "every wasted token costs real room against CLIP's 77-token budget"; that was **wrong** and has been corrected.

This is why `negative_presets` became stackable layers rather than alternatives: if stacking is cheap, the only question left is whether a layer is *relevant*.

**Ordering still matters, and not only at the limit.** CLIP weights earlier tokens more heavily even within the 77, so front-loading is a quality lever, not just a truncation defence. The user-facing form of this: *subject in the prompt, treatment in the style suffix, and order both by how much you'd miss them* — and, counterintuitively, **on SD the style suffix is what gets eaten**, because it is appended last.

**Still unverified:** whether Cloudflare's *hosted* endpoint truncates at exactly 77 tokens or does something more generous. Local SD architecture is not proof about someone else's deployment. The probe is specified in `docs/preset-and-docs-plan.md` and is the next thing to run.

## Deleting generated images does NOT make them regenerate

Measured 2026-09-02, while fact-checking `recipes.md` — the first draft of that section asserted the opposite and was wrong.

Resume consults **two** sources, and either one alone will skip a job:

1. `.batchgen.db` records the job as `done`, so it is never claimed off the queue.
2. `_generate_one` checks the disk for an existing output before calling the API.

So deleting the image files alone changes nothing — the database still says done, and **zero API calls are made**. Deleting `.batchgen.db` alone also changes nothing, because the files are then found on disk and skipped (this is what `test_overwrite_protection` covers).

**To regenerate a subset you must delete both** the image files and `.batchgen.db`. Verified: with both removed, a 4-prompt batch missing 2 images regenerated exactly those 2 and skipped the rest.

Worth remembering as a doc-writing lesson too: the claim was plausible, matched a reasonable mental model of the code, and was still false. Cheap to check, so check.

**AMENDED 2026-09-13, and the last sentence was itself wrong.** It read "`Overwrite` regenerates everything, at full cost." It does not, and never did: `overwrite` is checked in `_generate_one` **after** a job is claimed, and a `done` row is never handed out by `claim_next()` — so on a finished batch that check is reached for no job at all and nothing is generated. The flag only ever governed **source 2**, the on-disk check. The same doc-writing lesson applies one level down: a plausible claim about code the author had read, still false.

Both sources are also now keyed on the **style suffix**, which neither knew about before — `find_batch()` compares it (it was stored from the start but never read), and it is in the filename plus the derived hash. A changed style, model or size therefore produces a new filename and regenerates on a normal Start, which is what `recipes.md` had been working around by telling users to delete two things. **Regenerate All** (`cli.py regenerate`) is the deliberate "nothing changed, do it again anyway" action, and is the thing `Overwrite` was wrongly believed to be.

## PROBE: Cloudflare's SD models DO truncate long prompts — confirmed

Measured 2026-09-02. This settles the open question left by the prompt-length work.

**Method.** One 715-character woodland scene, and a distinctive element — *"a giant yellow rubber duck sitting in the middle of the clearing"* — placed either at the **front** or at the **end** of the otherwise identical prompt. Same seed (4242), same step count (each model's own `default_steps`), same size. The only variable is position. Detection by saturated-yellow pixel fraction, then confirmed by eye.

| Model | Duck at front | Duck at end | Verdict |
|---|---|---|---|
| SDXL Lightning | 0.117 | 0.028 | **truncated** |
| SDXL Base 1.0 | 0.152 | 0.023 | **truncated** |
| DreamShaper 8 LCM | — | — | inconclusive, see below |

Visually unambiguous: at the front, a large yellow rubber duck dominates the frame. Moved to the end of the *same 715 characters*, it is **completely absent** — not small, not faint, not there at all. The rest of the scene is nearly identical, which is exactly what truncation looks like and what a "too crowded" prompt would not.

The images are kept in `docs/probe images/` — compare `sdxl__front.png` against `sdxl__buried.png`.

**So the ~300-character guidance is right**, and the residual yellow (~0.02) in the truncated images is foliage and sunlight, not a duck.

### What this probe did NOT establish

**Where the cut falls.** The probe shows that content past a certain depth is dropped; it cannot say at which word. The API returns image bytes and nothing else — no token count, no truncation flag, no echo of the parsed prompt — so there is no way to read the boundary out of a response.

Finding it behaviourally was considered and **rejected**: it would mean bisecting on whether a model chose to render one object, and SD models take enough creative liberty run-to-run that a single "gone" reading does not reliably reproduce. That produces false precision, not a measurement.

The boundary is instead known from the architecture, which is documented and deterministic:

| Model | Base | Text encoder | Limit |
|---|---|---|---|
| DreamShaper 8 LCM | fine-tuned from `runwayml/stable-diffusion-v1-5` | CLIP ViT-L/14 | **77 tokens** |
| SDXL Lightning, SDXL Base | SDXL | CLIP ViT-L + bigG | **77 tokens** |
| FLUX.2 klein 4b / 9b | — | Qwen3/T5, `max_length=512` | **512 tokens** |

Sources: the [DreamShaper 8 LCM model card](https://huggingface.co/Lykon/dreamshaper-8-lcm) states it is fine-tuned from SD 1.5; the [SD 1.5 card](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5) states it "uses a fixed, pretrained text encoder (CLIP ViT-L/14)"; CLIP's 77-token context is the documented limit, and diffusers truncates past it by default ([issue #2136](https://github.com/huggingface/diffusers/issues/2136), [SDXL discussion](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/discussions/60)); FLUX.2's encoder tokenizes at `max_length=512` ([text encoders](https://deepwiki.com/black-forest-labs/flux2/3.2-text-encoders)).

**So: the architecture says 77 tokens, the probe confirms Cloudflare's hosted deployment does not quietly extend it, and the ~4-chars-per-token conversion gives the ~300 characters the UI advises.** The character figure stays labelled an estimate, because tokenization varies with wording — a comma-separated keyword list overflows sooner than prose.

**Why the first attempt failed, worth remembering.** Round 1 used a red umbrella and compared a *short* front-loaded prompt against a long buried one — two variables at once, so it proved nothing. It also sent no step count, which broke DreamShaper. Round 2 fixed both: same words in both cases, only position differing, and each model given its own default steps. **The control that matters is the same prompt reordered, not a different prompt.**

## DreamShaper 8 LCM returns black frames and colour-broken images on woodland scenes

Found 2026-09-02 while running the truncation probe. Unrelated to truncation, and worse.

`@cf/lykon/dreamshaper-8-lcm` fails on ordinary green outdoor scenes:

- `"a red squirrel on a mossy tree stump in a woodland clearing"` → HTTP 200 with a **1223-byte pure-black frame** (all channels 0,0). Identical parameters on SDXL Lightning render the scene perfectly.
- Slight rewordings return an image whose **blue channel is crushed** (B-max 0–31), producing radioactive green-and-black output with the composition intact but the colour destroyed.

**Not** step count, **not** seed, **not** prompt length — a 500-character red-barn-and-blue-lake prompt renders fine at every step count from 4 to 20. It tracks the *content*: heavily green woodland scenes break it.

**Consequence for the program: this is indistinguishable from a content block, and is correctly reported as one.** `is_blank()` requires a genuinely uniform frame (`lo == hi` on every channel), which is the right test — the model really is returning a flat black image. So the detector is not at fault and must not be weakened. But the *message* ("the content filter refused this prompt") is misleading here, because nothing was refused.

Practical advice: **if DreamShaper returns blocked images or lurid green ones on landscape work, switch model rather than rewriting the prompt.** Lightning handles the same prompts. This is a defect in a third-party hosted model, not something the program can fix.

### PROBE Phase 1: the trigger is green CONTENT, not prompt wording — confirmed 2026-09-04

Full plan and rationale in `dreamshaper-quality-probe.md` (archived locally in `old wip/`) — started to find a general, mechanism-based warning to replace the over-specific "forest background" one removed 2026-09-03, and to settle a separate hypothesis (forcing SD to 1:1 and cropping) that this probe's sample review already showed was not the real problem.

**Method.** Four prompts, all sharing a squirrel subject, at fixed Standard 16:9 (1536x864), `default_steps=8`, seed 4242 — only the content varies:

| Label | Prompt content | Result |
|---|---|---|
| A — known trigger | plain woodland clearing | **Broken.** Radioactive green/yellow blob, no recognisable subject, blue channel crushed to 0–35. |
| B — autumn foliage, explicit "no green" | same scene, told to avoid green | **Still broken where green appears.** The model rendered green undergrowth anyway (ignored the negative instruction), and blue crushed specifically in that region — the orange/yellow sky area stayed intact. |
| C — desert, no green anywhere | sandy dune, no foliage | **Clean.** Normal full-range image, identifiable squirrel, no crush. |
| D — same woodland scene, much more specific wording | named tree species, ferns, bluebells, dappled light | **Still broken**, same severity as A. Extra specificity did not help at all. |

**Conclusion: the trigger is saturated green content actually present in the rendered scene, not vagueness or wording of the prompt.** D disproves "the model is filling in a generic blob because the prompt is vague" — a highly specific woodland prompt broke exactly the same way as a plain one. B disproves "just tell it not to be green" — the crush is regional: it fires wherever green ends up in the composition and leaves the rest of the frame alone, so even a prompt actively steering away from green can't fully escape it once the model puts any green into the image. C is the clean negative control: zero green content, zero bug, completely normal render.

This rules out Phase-1-adjacent theories cheaply: it is not a truncation/length effect (all four prompts are well under the ~300-char SD budget), not a "the model got confused" vagueness effect, and not fixed by rewording alone. It also confirms the bug is **regional/compositional**, not a whole-frame binary switch — B's mixed result (fine sky, broken foliage) is the clearest evidence of that.

### PROBE Phase 2/2b: size and aspect ratio do NOT explain or fix it — confirmed 2026-09-04

Phase 2 (single seed) first looked like tier mattered — Draft avoided the crush that hit Standard. That did not survive a 3-seed re-run. **Phase 2b ran the same 4 prompts x 4 sizes (Draft/Standard x 16:9/1:1) x 3 seeds — 48 generations — and got a 9–12/12 failure rate at every single size and ratio tested.** Draft did not avoid the bug; it just converted some of the green-content failures into pure-black content-filter blocks instead of the blue crush (the two failure modes were colliding, not one replacing the other). Even the best-looking cell (`standard_1x1`) still failed 9/12, with the 3 green-woodland prompts crushing 9/9 regardless of shape. **Conclusion: size/aspect ratio is not the lever. The single seed that looked clean in Phase 1 was luck, not a real result.** This also finally puts the original "force SD to 1:1 and crop" hypothesis to rest — even 1:1 was never safe.

### PROBE Phase 3: guidance (CFG) was the actual root cause — confirmed 2026-09-04

`@cf/lykon/dreamshaper-8-lcm` is an **LCM (latent consistency model) distilled sampler**. LCM models are documented to want very low guidance (~1–2) and to misbehave — oversaturation, blown highlights, colour breakup — at normal SDXL-style guidance (~7–8). The program's provider code (`core/providers/cloudflare.py`) has **never set `guidance` explicitly** — it is only sent if a caller supplies one — so every generation in Phase 1 and Phase 2/2b rode Cloudflare's server-side default, which is almost certainly tuned for the two non-LCM SD models, not this one.

**Method.** On the worst confirmed cell (`standard_16x9`, 1536x864, the known-trigger prompt), a full grid of `num_steps × guidance` — steps `[4, 8, 12, 20]` × guidance `[1, 3, 5, 8]`, 16 generations, single seed:

```
guidance\steps    4        8       12       20
     1.0        OK       OK       OK       OK
     3.0        CRUSH    OK       OK       OK
     5.0        BLOCK    OK       OK       OK
     8.0        OK       BLOCK    OK       OK
```

**13 of 16 combos came back clean**, against a 3/12 success rate for this exact cell in Phase 2b (which used no explicit guidance). `guidance=1` was clean across every step count tested, and produced the best-looking DreamShaper output seen in the entire investigation — fully photorealistic, correctly coloured, no crush, no posterization. By contrast `guidance=8, steps=20` — closer to what a non-LCM SDXL default would be — was technically "OK" by the blue-channel heuristic but visually oversaturated/posterized on inspection, so even the surviving high-guidance cells are not actually good; low guidance is not just "less likely to fully break," it is **also the better-looking output**.

**Verification.** `guidance=1, steps=8` re-run across all 3 Phase-2b seeds on both the known-trigger prompt and the desert control (6 generations): **6/6 OK**, confirmed by eye — the exact cell that failed 3/3 times in Phase 2b at the old (unset/default) guidance now succeeds 3/3 times at guidance=1, and the control holds 3/3 as well.

**This is the real fix, and it long precedes the aspect-ratio question that started this investigation.** Scripts: `old wip/spike/dreamshaper_probe_phase3.py`, images in `old wip/spike/out/phase3/`.

**Applied 2026-09-04.** `ModelSpec` gained a `default_guidance: float | None` field (mirroring the existing `default_steps` pattern), set to `1.0` for `dreamshaper`. `core/providers/cloudflare.py`'s `generate()` now falls back to `model.default_guidance` whenever the caller doesn't supply an explicit guidance, in both the JSON and multipart request paths — previously guidance was skipped entirely if unset, with no fallback at all. `default_steps=8` for dreamshaper is also now documented as a deliberate floor: the same Phase 3 grid showed `steps=4` produces duplicated/warped subjects (a 3-headed squirrel cluster) even at the correct `guidance=1`, so the low end of the settable range is genuinely bad independent of CFG. 15/15 offline tests still pass.

### PROBE: Lightning and SDXL-base do NOT share the same guidance gap — measured 2026-09-04

Before assuming the fix generalises, the same steps x guidance grid (on the same `standard_16x9` cell, same known-trigger and desert-control prompts) was run against both remaining free SD models. **Neither needed a `default_guidance` override, but for opposite reasons, and one of them showed the fix would have actively hurt it.**

**SDXL Lightning** — also a distilled/fast model (8-step default), so its guidance sensitivity was not safe to assume away. Result: **10/10 OK** across guidance `[1, 3, 5, 8]` x steps `[8, 20]`, plus both desert-control values. Visually confirmed clean at every combination tested, including `guidance=8`/`steps=20` where DreamShaper had shown oversaturation. **Conclusion: Lightning is robust across the full range tested — no override needed, Cloudflare's own default is fine.**

**SDXL Base 1.0** — the standard, non-distilled SDXL (`default_steps=20`). Result: **10/10 "OK" by the automated blue-channel check**, but visual inspection told a different story from the pass rate: `guidance=1` (the value that fixed DreamShaper) produced **badly degraded, smeary output with melted textures and no real edges**, at both `steps=8` and even at the model's own full `steps=20`. `guidance=3–8` at `steps=20` were all genuinely clean and sharp. **Conclusion: SDXL-base wants the OPPOSITE of DreamShaper's fix** — it needs its full step budget and normal-to-moderate guidance, not a low one. Applying DreamShaper's `guidance=1` fix universally would have quietly broken this model. `default_steps=20` was already correct and needed no change; no `default_guidance` override was added, since Cloudflare's own default already sits in the working 3–8 range.

**This validates measuring each model individually rather than generalising a fix.** The three free SD models have three different correct guidance stories: DreamShaper (LCM) needs an explicit low override, Lightning is guidance-agnostic across the tested range, and SDXL-base needs to be left alone at a moderate-to-normal value it already gets by default. Scripts: `old wip/spike/lightning_sdxl_guidance_probe.py`, images in `old wip/spike/out/guidance_sanity/{lightning,sdxl}/`.

### Consolidated recommendation table — 2026-09-04

The upshot of the whole guidance/steps investigation, in one place:

| Model | Best guidance (measured) | Best steps (measured) | `ModelSpec` default | Code change needed? |
|---|---|---|---|---|
| DreamShaper 8 LCM | **~1** — 3+ risks a broken, colour-crushed image | **8–20** — 4 produces a duplicated/warped subject even at guidance=1, so 8 is a floor, not just a default | `default_guidance=1.0`, `default_steps=8` | **Yes — applied 2026-09-04** |
| SDXL Lightning | **~8** — corrected 2026-09-04. All values 1-8 passed the automated check, but closer visual comparison showed guidance=1 is over-sharpened/crunchy (wiry, harsh fur texture) while guidance=8 (`control_steps8_g8.jpg`) is clean and naturally lit — the best Lightning result in the whole probe. Do not treat "all technically OK" as "no preference"; look at the actual images. | **8** — its native distilled default; 20 works and gives a softer/more-detailed look, worth suggesting to a user who finds 8 steps too crunchy-looking | `default_guidance=8.0`, `default_steps=8` | **Yes — applied 2026-09-04** |
| SDXL Base 1.0 | **3–8** — a normal-to-moderate value; guidance=1 badly smears texture even at 20 steps | **20** — its own full, non-distilled step budget | no `default_guidance` (unset, and Cloudflare's own default already lands in the working 3-8 range), `default_steps=20` | No — already correct |

**Lesson from the Lightning correction:** the automated blue-channel/washout heuristic said 10/10 OK for Lightning across the whole grid, and an early pass through this table used that to mean "no preference, any guidance is fine." That was wrong — "not broken" and "best-looking" are different bars, and only a side-by-side visual comparison caught that guidance=1 was noticeably worse than guidance=8 despite both passing the automated check. Don't average across a grid's "OK" cells and call it a verdict; look at the actual images before writing a recommendation.

GUI tooltips for the Guidance and Steps fields (`gui/tabs/provider.py`) were rewritten 2026-09-04 (and corrected again same day for Lightning) to match this table. "Leave empty for the model's own default" is accurate now that both DreamShaper's and Lightning's correct values are applied automatically via `default_guidance` — it was **not** accurate before this session's fix, since leaving it empty rode Cloudflare's un-tuned default for both.

### klein 4B / 9B — guidance fixed from the official model card, not a local probe

Checked 2026-09-04, prompted by the same pattern showing up in a third place: klein had `default_guidance` unset too, same as DreamShaper had before its fix. Unlike DreamShaper, klein had already produced 108 real prompts with excellent results, so this was worth checking against official documentation before spending API calls or touching anything working.

**Black Forest Labs' own README for `FLUX.2-klein-4B`** (the distilled model Cloudflare hosts as `@cf/black-forest-labs/flux-2-klein-4b` — distinct from the separate, non-distilled "klein Base" line) gives its official example code as `guidance_scale=1.0, num_inference_steps=4`. This is a guidance-distilled model by design, the same category as DreamShaper's LCM sampler, and BFL's own usage example pins guidance at exactly 1.0 — matching the `steps` fixed-at-4 behaviour this program already enforces (`steps_settable=False`).

**Applied without a local probe**, on the strength of the primary source: `default_guidance=1.0` set on both `klein4b` and `klein9b` (`klein9b` is the same step-distilled-to-4 family, not the separate klein-Base line). 15/15 tests still pass. This makes the already-good behaviour explicit and guaranteed rather than incidental — the 108 prior prompts were most likely already close to this value via Cloudflare's own default, so no regression is expected, only a guarantee that it stays correct if Cloudflare's default ever changes.

Sources: [black-forest-labs/FLUX.2-klein-4B README](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/blob/main/README.md) (official example: `guidance_scale=1.0, num_inference_steps=4`); [Cloudflare's flux-2-klein-4b changelog](https://developers.cloudflare.com/changelog/post/2026-01-15-flux-2-klein-4b-workers-ai/) confirms `guidance` is optional with no stated default on Cloudflare's side, and `steps` fixed at 4.

**Confirming probe run 2026-09-04** (6 generations at `standard_16x9`, guidance `[1, 3, 5, 8]` on the trigger prompt plus a desert control at guidance 1 and 8 — cost roughly 6 cents but was effectively free against the user's daily neuron allowance). **Result: 6/6 clean, and unlike DreamShaper/SDXL-base/Lightning, no visible quality difference was found across the whole tested range** — guidance=1, 3, 5 and 8 all produced excellent, artifact-free images (two different but equally strong aesthetic treatments — illustrated at 1/8, photorealistic at 3/5 — rather than one being visibly better or worse). This means klein's `default_guidance=1.0` is correctly sourced from the official model card and is a safe, defensible choice, but — unlike the other three models — the local evidence doesn't actually distinguish it as superior to the alternatives tested; it's "confirmed harmless and doc-recommended," not "confirmed best by measurement." Images in `old wip/spike/out/klein_guidance/`, script `old wip/spike/klein4b_guidance_probe.py`.

### klein4b's "free images per day" was undercounting by ~5.7x — measured 2026-09-04

Found while investigating the guidance question above, from an offhand user observation: 108 real klein4b images (all Standard 16:9, all identical settings) used only a small fraction of the 10,000/day free neuron allowance and reset clean the next day — which didn't square with the GUI's own displayed estimate of 63 free images/day at that size.

**Root cause: the GUI derives "free images per day" from the $1.72/1000 published price**, which implicitly assumes Cloudflare's stated per-tile neuron rate (26.05 neurons/output tile, per their pricing page) is what's actually billed. It measurably is not.

**Measured directly via Cloudflare's GraphQL usage API** (`aiInferenceAdaptiveGroups`, the same query used in the original spike) — two independent readings a week apart:

| Source | Images | Total neurons | Neurons/image (6 tiles) | Neurons/tile |
|---|---|---|---|---|
| User's real production batch | 108 | ~2,990 (dashboard, approximate) | ~27.7 | ~4.61 |
| Fresh confirming query, same day as this investigation | 6 (the guidance probe above) | 166.07 (exact, via GraphQL) | 27.68 | 4.613 |

The two agree to within 0.1%. **The actual rate is ~4.61 neurons/tile, not 26.05** — about 5.7x less than Cloudflare's own published per-model pricing page states. At Standard 16:9 (6 tiles), that's **~361 free images/day, not the 63 the GUI showed.**

**This also revisits an earlier finding.** The 2026-08-30 note above ("`totalNeurons` cannot back a quota UI... flux-2-klein-4b also reported 0 neurons") was real at the time, but was about the free SD-family models' correct 0-neuron billing — the original spike's `neurons` command only ever tested the three SD models, never klein. A fresh GraphQL query today shows the free SD models still correctly reading 0, while klein4b reads a real, stable, nonzero number (166.07, confirmed identical on a second query minutes later) — so klein's neuron telemetry works and can be trusted now, whatever the state was in earlier testing.

**Applied:** `ModelSpec` gained `measured_neurons_per_tile: float | None`, set to `4.613` for `klein4b` only (not `klein9b`, which bills per-megapixel via a different formula — its own neuron rate hasn't been measured yet). `Estimate.free_images_per_day` now uses this measured rate when present, falling back to the old $-derived formula otherwise. The $ pricing itself (`$1.72/1000`) is unaffected and still correct against Cloudflare's published price — only the free-daily-allowance estimate changed. 15/15 tests pass.

**GUI copy also updated** (`gui/tabs/provider.py`): the model dropdown tooltip, the cost calculator's note, and the "Check usage" link tooltip all previously implied Cloudflare's neuron count "can't be trusted" for any paid model and led with the $ price as the only signal — which, per direct user feedback, made klein feel like a real cost decision when for most users on the free plan it functions as another free model. All three now state the measured free-images-per-day figure plainly, and the "can't be trusted" language is now scoped to what it actually applies to (the always-0-billing SD models having no cap to measure, not klein's telemetry being broken).

**Caveat, stated in the code comment:** this is one production batch plus one confirming probe, both at the same size/tier (Standard 16:9, 6 tiles). The per-tile rate is assumed to scale linearly with tile count, matching how the $ price itself is modelled, but that scaling has not been independently confirmed at a different size. If Cloudflare's real pricing has a per-request minimum or non-linear component, the free-image estimate at very different sizes could still be off — flagged here so a future session knows this wasn't re-verified across sizes, only trusted to scale the same way the price does.

## Negative layers stack cheaply against the POSITIVE budget, not against their own

Measured 2026-09-03, while writing the built-in negative layers.

"Stacking is nearly free" is true and remains the design basis — the negative prompt is encoded in its own CFG pass and costs the scene description nothing. **But it is not free of its own budget**, and the built-in layers are large enough that this bites immediately on SD:

| Layers ticked | Composed length |
|---|---|
| 1 | ~283 chars |
| 2 | ~554 chars |
| 3 | ~742 chars |
| 5 | ~1067 chars |
| all 20 | 4327 chars |

**Against SD's ~300-character budget, roughly ONE layer fits.** Two typical layers (`Text & Markings` + `Framing` = 409 chars) already overflow, and everything past the cut is silently dropped exactly as it is in a positive prompt. On klein (~2000 chars) about seven layers fit; on Pollinations FLUX.1 schnell (~1000) about three.

Consequences, none of which change the layer design:

- **The GUI already handles this correctly.** `refresh_negative_hint()` grades the composed text against the selected model's own `prompt_soft_limit` / `prompt_hard_limit`, so a user who over-ticks on SD gets the same ok/near/over warning the positive prompt gets. No code change was needed; the counter was already measuring the right string.
- **Layer ORDER is the lever on SD.** Layers compose in list order and the tail is what gets cut, so the first ticked layer is the one that actually runs. This is the negative-prompt form of the same front-loading rule the style suffix follows.
- **It does not argue for smaller layers.** A layer trimmed to fit two-at-a-time on SD would be worse on klein, where seven fit comfortably, and the whole point of splitting concerns is that a user ticks only the relevant ones. One well-chosen layer on SD is the correct outcome, not a degraded one.

### Deduplication is real but small

Across the 20 built-in layers only **12 terms** appear in more than one layer — `blown highlights` and `washed out` (Quality Floor ∩ Colour Discipline), `3d render` and `cgi` (Photoreal Guard ∩ Anti-Photo), `plastic skin` (Anatomy (Skin) ∩ Photoreal Guard), and similar. Dedup therefore saves tens of characters, not hundreds, and **must not be relied on to keep a stack inside a budget**. Its job is correctness — not repeating a term, which on SD is mild unintended emphasis — rather than compression.

A stack of nine anatomy-and-quality layers deduplicated to exactly its raw length, because those particular layers happen not to collide. The overlap sits between layers that address adjacent concerns, which is precisely where a user is most likely to tick both.

## Error 4006: a 429 that must NOT be retried

Cloudflare returns HTTP 429 for two genuinely different conditions, and they must be classified differently or a batch quietly burns its whole retry budget against a wall that will not move.

**Verbatim body (measured 2026-09-05):**

```json
{"code":4006,"message":"AiError: AiError: you have used up your daily free allocation of 10,000 neurons, please upgrade to Cloudflare's Workers Paid plan if you would like to continue usage."}
```

This is the **daily free 10,000-neuron allowance spent**, not a transient rate limit. Measured in a real run: two jobs died burning their full retry budget (`attempts=3`) against this, then landed in `pending` with no useful signal — the run just produced noise. It affects **every model on the account, including the free SD ones**, since the allowance is account-wide, not per-model.

Cloudflare's docs say the allowance resets at 00:00 UTC. **Measured false**: the block was still active 7 hours past that reset time, with the GraphQL usage counter reading 0 neurons used at the same moment — the enforcer's internal state disagrees with the metric that is supposed to describe it. This is a known upstream inconsistency, not a one-off. **Consequence: the true block duration is not predictable, and must never be waited out in-process** (no in-process retry loop, no computed sleep-until-reset). The only correct response is to stop the batch cleanly and let the user try again later.

**Applied:** `QuotaExhausted(PermanentError)` in `core/providers/base.py`, raised by `core/providers/cloudflare.py` when a 429 body parses with `errors[0].code == 4006` (a 429 that fails to parse, or parses without that code, still falls through to the existing `RateLimited` path unchanged). The engine (`core/engine.py`) catches it at the worker level as a **batch-level stop**: the job that surfaced it is `release()`d back to `pending` (never marked `failed` — it was never given a fair attempt), the remaining jobs are left untouched in `pending`, and the run aborts immediately rather than attempting them. The existing resume path (`retry-failed` is not even needed — the jobs were never marked failed) picks the batch back up unchanged whenever the user tries again. Surfaced in the GUI run tab and the CLI as an expected free-tier condition, not an error.


## FLUX.2 [pro] Preview: three things that were settled from the schema, not a call

Added 2026-09-05. **Everything in this section is DOC-DERIVED, not measured** — no live call has been made against `black-forest-labs/flux-2-pro-preview`, because gateway models bill from prepaid credit and none is available. Each fact below was read from Cloudflare's published model schema, and two of the three were read twice independently and agreed. They are recorded here because they were genuinely uncertain going in and are now settled well enough to code against — but a measured contradiction beats them, as always.

### 1. `result.image` is a presigned URL — the THIRD shape at that one field path

Cloudflare's schema declares it `"string" format: uri`. So the lineup now has **three mutually incompatible encodings living at the identical `result.image` path**:

| Family | `result.image` holds |
|---|---|
| klein 4B / 9B | **bare base64** |
| p-image | ~~a `data:image/jpeg;base64,...` URI~~ — **MEASURED 2026-09-06: a presigned URL**, same as krea |
| krea x2, **flux-2-pro** | a **presigned URL** needing a second GET |

flux-2-pro reuses krea's `json_url` path unchanged, including the two rules that matter there: the presigned fetch **must not carry the `Authorization` header** (the URL is already signed; forwarding the token leaks it to a third-party host), and **every fetch failure is transient** (the image was generated and billed before the URL was handed over, so retrying is the only way to recover something already paid for).

The practical lesson is the general one: **the shape is never inferred from the field name.** `_extract_image` sniffs the content — `data:` prefix, `http(s)://` prefix, else bare base64 — rather than trusting the spec's declared encoding, precisely because three families disagree at one path.

### 2. `safety_tolerance` runs 0 = STRICTEST to 5 = MOST PERMISSIVE

Integer, range 0–5, **API default 2**. The direction reads backwards from what a dial named "tolerance" suggests, and **inverting it is the expensive mistake**: sending `0` for a "permissive" setting makes the filter *maximally aggressive*, and the symptom — more prompts refused — looks like the model being difficult rather than like a configuration bug. Cloudflare's schema states it plainly ("0 is the strictest, 5 the most permissive"), and Black Forest Labs' own convention agrees.

Pinned by `SAFETY_TOLERANCE_MIN` / `_MAX` / `_API_DEFAULT` in `core/models.py` and by a test that exists solely to stop a later edit silently flipping it.

**Still worth one paid check on first use**, since this is the entire reason the model is in the lineup: generate one prompt that reliably trips the native klein filter, at `5` and at `0`, and confirm `5` is the one that passes. ~$0.06.

### 3. `output_format` defaults to `jpeg` — a non-neutral default, so it is sent explicitly

Enum `jpeg | png | webp`, **defaulting to `jpeg`**. That is not a neutral default: left alone the model silently picks a lossy format for a batch the user may want lossless. This is the same lesson krea's `creativity` taught — **a field whose default is not the neutral choice is worth stating rather than inheriting** — so the program sends it always.

**The spelling is a real trap, not a cosmetic one.** flux-2-pro accepts `jpeg`; nano-banana (still to be added) accepts `jpg`. Same format, two vocabularies. `ModelSpec.output_format` keeps the program's own internal spelling (`"jpg"`), because it also drives the dropdown and the file-extension logic that every model shares; the wire value is derived by `wire_output_format()` from a per-family vocabulary table. Writing the string out by hand at each call site is exactly how that ships as a bug.

Sniffing magic bytes remains mandatory regardless. Asking for a format is not evidence of receiving one — CLAUDE.md's standing rule is that the declared content-type lies (lightning declares `image/png` and sends JPEG), and a requested format is a weaker claim than a declared one.

### And one thing that needed no special handling at all

flux-2-pro takes **true `width`/`height`, minimum 64, with no multiple-of-16 rule** (`1537` was accepted in the zero-cost field probe; no upper bound was found — 50000 passed validation). It is the only model on the gateway wishlist with pixel-exact control, so **the program's shared `SIZES` table maps onto it directly** with no `SIZE_TABLE_OVERRIDES` entry and a full working Draft/Standard/High ladder — the first gateway model for which that is true. p-image needed its own whole table and krea has no ladder at all.

Checked rather than assumed: every size in `SIZES` is ≥ 64 in both dimensions, so nothing needs substituting.

## The content filter is adjustable on exactly two models, and they disagree about how

CLAUDE.md records that a refused prompt on the native lineup returns **HTTP 200 and a byte-identical black frame** — no error, no distinct status. The program detects that and marks the job `BLOCKED`, permanently, because retrying identical text produces the same refusal. What it could not do until now is give the user any way to *respond* to a refusal they believe is spurious.

Two gateway models expose a lever, and they express it completely differently:

| Model | Field | Type | "Loosen it" means |
|---|---|---|---|
| `pruna/p-image` | `disable_safety_checker` | **boolean** | `true` |
| `black-forest-labs/flux-2-pro-preview` | `safety_tolerance` | **integer 0–5** | `5` |

Both are driven by **one** program-level setting with three modes (`default` / `permissive` / `off`), mapped per-model by `filter_value_for()` in `core/models.py`. The GUI dropdown and the `--content-filter` flag never have to know which field a given model speaks; the spec's `content_filter_field` decides, and models that name no field are never sent either one however the caller asks.

p-image's field has no middle setting because it is a boolean — `permissive` and `off` genuinely mean the same single thing there. That is stated rather than papered over with an invented third value.

**"Provider default" is expressed by sending NOTHING**, not by sending the documented default value. This is deliberately the opposite call from krea's `creativity`, and the reasoning is worth keeping straight:

- `creativity` **is** sent always, because its API default (`low`) is **not** neutral — silence means accepting a prompt rewrite the user never asked for.
- A content filter's provider default **is** the neutral choice: it is what the user gets on every other model in the lineup. Pinning today's documented value (`2`) would freeze the program to a number the user never chose and stop it following the provider if that default ever moves.

**The program defaults to `permissive` on both models** — the loosest setting each one offers. An earlier draft defaulted to `default` on the reasoning that loosening a filter should be a knowing decision; that was reversed the same day, and the argument against it is worth keeping. This is a **batch** tool: a one-off generator can shrug off a spurious refusal because the user just reruns it, whereas here a false flag costs a slot in an overnight run of hundreds that the user only discovers the next morning. On the native lineup a refusal is invisible at request time (HTTP 200 and a black frame), these two models are the only lever against that, and shipping the lever set to "off" hands the user the annoyance without the remedy. The failure mode is also real rather than hypothetical: **Cloudflare runs a vision check over the OUTPUT image**, so ordinary prompts get flagged on the strength of a frame the user never asked for and cannot inspect — exactly the class of false positive this setting exists for.

It does **not** disable moderation and is not a route around any provider's policies: it asks for the loosest setting the model itself publishes (5 of 5 on flux-2-pro's own scale), the provider still enforces its own limits, and a genuinely refused prompt is still refused. `default` and the stricter end stay one dropdown away.

`p-image`'s `disable_safety_checker` had been deliberately left unwired since it shipped, specifically so both controls could get one consistent treatment rather than two ad-hoc ones. That is what this is.


## Recraft V4.1 Utility: the one gateway model whose bad request is NOT free

Everything else about the gateway lineup was verified at zero cost by exploiting the same property: the gateway validates a request **before** charging, so a malformed body returns 400 naming every legal field and a well-formed one returns 402 Insufficient balance. That is how eight models' field lists were established without spending anything.

**Recraft breaks that property, and it is the single most important fact about this family.** The gateway type-checks only that `size` is a **string** and defers the *value* check to Recraft itself. A bad size therefore gets past the gateway, is **billed**, and then fails at generation time. There is no free rejection to lean on.

The response is to validate `size` client-side before the request leaves. `recraft_size_string()` in `core/models.py` is the only legal source of a `size` value, and `ModelSpec.validate_size()` routes enum models through it as well — which matters, because the GUI size readout and `cli dry-run` both read `validate_size` and would otherwise green-light a size the provider would charge for and refuse.

**A min/max check is not sufficient here, and that is easy to miss.** An enum model's legal sizes are a *set*, not a range. `1024x768` sits comfortably inside Recraft's 768–1344 bounds, is a multiple of 16 in both dimensions, and is still not an accepted value. Verified: `cli dry-run --model recraft-utility --width 1024 --height 768` now reports it as an error rather than costing money to discover.

### `size` is a fifth size vocabulary, and its API default is a square

Recraft uses `size`, an opaque enum of `WxH` strings. Not `aspect_ratio` — which it **rejects outright** — and not `width`/`height` either. This is the fifth distinct size vocabulary in the lineup (pixels · aspect_ratio · aspect_ratio+resolution · size enum · nano-banana's ladder still to come).

The published table, cross-checked 2026-09-05 against Cloudflare's model page and two independent third-party API references that list the identical 14 entries:

| Ratio | Size | | Ratio | Size |
|---|---|---|---|---|
| **1:1** | `1024x1024` | | 5:4 | `1152x896` |
| **3:2** | `1280x832` | | 4:5 | `896x1152` |
| **2:3** | `832x1280` | | 6:10 | `832x1344` |
| **16:9** | `1344x768` | | 14:10 | `1280x896` |
| **9:16** | `768x1344` | | 10:14 | `896x1280` |
| 2:1 | `1536x768` | | 4:3 | `1216x896` |
| 1:2 | `768x1536` | | 3:4 | `896x1216` |

All five of the program's ratios are covered (bolded).

**Recraft's own default for `size` is `1024x1024` — a SQUARE.** That makes silence non-neutral in the worst way: omitting the field would quietly render an entire 16:9 batch as 1:1 crops. `size` is consequently sent **always**, which is the third time this lineup has produced the same lesson (krea's `creativity` defaults to expansion-on, flux-2-pro's `output_format` defaults to `jpeg`). **Ask what a field's default actually is before deciding that omitting it is neutral.**

**The ratio labels are nominal, not exact.** Recraft's "16:9" is 1344x768, which is 1.75, not 1.778. That is why the enum string is looked up by ratio *key* rather than recovered by matching a numeric ratio the way krea's `_ratio_key_for()` does — krea's 0.02 tolerance would not have matched it.

**16:9 is 1344x768, smaller than the program's Standard 1536x864** — fewer pixels for $35/1000 against $0–$1.72. There is one fixed size per ratio and no tier ladder at all, so `has_tier_ladder()` returns False and the tier dropdown disables. The reason shown had to be made model-specific: the existing text said "locked to 1K resolution", which is krea's reason and would have been a plausible-sounding lie about Recraft.

Related: the "~ estimated" size readout is now keyed on `size_style == "aspect_ratio_resolution"` rather than on "has no tier ladder". Krea's sizes are genuine guesses (it does not publish what 1K resolves to); Recraft's are published exact values that go on the wire verbatim, and marking those "estimated" would be the mirror-image dishonesty.

### No seed at all — and a seed must not be recorded where none was sent

Recraft exposes no `seed` field. **Reproducibility is impossible on this model by any means**, which is a stronger statement than "the seed box is greyed out" and is worth saying in those terms to anyone using a fixed seed to compare prompt wordings. The GUI disables the checkbox, the label and the entry, following the precedent set by krea's tier dropdown and the content-filter combo.

The subtler half: the engine generates a seed for every job regardless of model, and the provider drops it. Writing that unused number into the image's sidecar `.json` would promise a reproducibility that does not exist — someone re-running with that seed would get a different image and have no way to know why. `_finish` now records `seed=None` whenever `supports_seed` is False. **nano-banana needs this same treatment; it is also seedless.**

### Response shape: presigned URL, the same as krea and flux-2-pro

DOC-DERIVED, not measured. Read on Cloudflare's `recraftv4-1-utility` page, independently on the `recraftv4-1` page, and cross-checked against a third-party listing of the same response:

```json
{"gatewayMetadata": {...}, "result": {"image": "https://pub-....r2.dev/.../simple-generation.png"}, "state": "Completed"}
```

`result.image` is an **https presigned URL**, reusing `json_url` and the existing presigned fetch unchanged, and the envelope carries the gateway `state` field. That is now **four** models at three incompatible shapes on the identical `result.image` path — klein's bare base64, p-image's data URI, and krea/flux-2-pro/recraft's URL — which remains the reason the shape is sniffed from content and never inferred from the field name.

### What is deliberately not sent

`style`, `substyle` and `controls` are all optional and all left unset. `controls.image` is reference-image shaped and is a permanent skip like every other img2img field in the lineup; the banned-fields test was extended to cover `controls` and `image` on this model. `style`'s enum values are unconfirmed for the gateway path — Recraft's own API docs name `realistic_image` as the default with `digital_illustration` among the alternatives, but that is the *native* Recraft API and the gateway's behaviour when the field is omitted was not confirmed, so it stays in the Unverified table. Unlike `size`, a missing style cannot produce a wrong-*shaped* image, so silence is the safe call there.

### The pair, and the billed-size bug that adding the second one exposed

`recraft/recraftv4-1` ships alongside Utility. The field list is **confirmed identical** on both Cloudflare model pages — `prompt`, `size`, `style`, `substyle`, `controls`, `image`; no seed, no width/height, no `aspect_ratio` — and so is the presigned-URL response, so the pair shares one `_RECRAFT_COMMON` dict the way the krea pair does. They are **not** a cheap/expensive pair: identical $35/1000, identical fixed sizes, and V4.1 scores **lower** (Elo 1198 against Utility's 1218). V4.1 earns its place on character — art-directed tuning, high aesthetics, strong composition, accurate text rendering — and nothing in the UI presents it as an upgrade.

Adding it exposed a genuine bug worth recording, because it is the exact failure mode this family's asymmetry makes expensive. **A `size_enum` model needs its own `SIZE_TABLE_OVERRIDES` entry.** Without one, `size_for()` falls back to the shared `SIZES` table and returns 1536x864 at Standard 16:9 — which is not a legal Recraft size. On any other gateway model that request is rejected for free. On this family it is **billed and then refused**.

It is now pinned by `test_every_size_enum_model_owns_a_size_table`, which asserts both that every enum model owns a table and that every ratio×tier it produces passes `validate_size`. The test was verified to fail when the override is removed, rather than assumed to work.

**The generalisable lesson:** a shared fallback is safe only where a wrong answer is *rejected* cheaply. Recraft is the first model here where falling back silently produces a plausible-looking value that costs money to discover is wrong, so the fallback has to be closed off by assertion rather than left as a default.


## `google/nano-banana-2-lite` — added 2026-09-05

Google's model, reached through the AI Gateway. Elo 1290 — the strongest score per dollar on the paid lineup, above both Krea models and above both Recraft models while costing slightly less than either Recraft. **Everything below is doc-derived or from published third-party sources; nothing here was measured against the live API**, by the standing no-spend rule.

### The headline: the resolution tier is a real price lever, and Lite is pinned anyway

This is the one family in the whole lineup where the Draft/Standard/High dropdown maps onto something that costs different money. Cloudflare's schema exposes `resolution: 1K|2K|4K`, and on the full `nano-banana-2` the published prices are **$67 / $101 / $151 per 1000** — a 4K image costs 2.3x a 1K one. Every other gateway model is flat per image, so `_flat_per_image()` is right for them and would be wrong here.

**But `nano-banana-2-lite` is PINNED TO 1K by this program, and that is a decision rather than an oversight.** There is a genuine conflict in the sources:

| Source | Says |
|---|---|
| Cloudflare's own model page | `resolution` enum is `1K, 2K, 4K` — read directly, 2026-09-05 |
| OpenRouter | "Outputs are generated at 1K resolution across 14 aspect ratios" |
| fal.ai | "Output images are generated at a fixed 1K (1024x1024px)" |
| Pricing breakdown | Google publishes a 1K per-image rate for Lite and **no 2K or 4K rate**, unlike the models above it |

So the gateway schema accepts a value the model may not honour, and for which **no price is published anywhere**. The second half is what decides it. This program's contract is that it can tell you what a batch will cost before you run it; sending 2K on Lite would be a request whose price cannot be estimated from anything. Pinning to 1K means the quoted number is the real one.

The consequence in the UI is that `has_tier_ladder()` returns False for Lite and the tier dropdown disables — but **the reason text must not say "locked to 1K"**, because that is krea's reason and it would be a plausible-sounding lie here. The API declares 2K and 4K; it is this program that declines to send them, and the GUI says so in those words.

This is in the Unverified table. One paid call settles it. If Lite turns out to honour 2K/4K *and* Google publishes the rates, replace the one entry in `NANO_BANANA_TIER_RESOLUTION` with the full ladder and everything else — size table, price, tier dropdown, cost readout — follows automatically.

**The per-resolution price machinery was built and tested anyway**, on a full 1K/2K/4K ladder, because `nano-banana-2` needs it and Lite cannot exercise it. `_per_resolution()` recovers the tier from the pixel size (every entry in `SIZES_NANO_BANANA` is distinct, so the recovery is exact) and **falls back to the DEAREST price for an unrecognised size, never the cheapest** — if the estimate has to be wrong, it must not be wrong in the direction that surprises the user with a bill.

### Sizes ARE published, unlike krea's — and that broke a UI string keyed on the wrong thing

nano-banana speaks krea's exact size vocabulary (`size_style="aspect_ratio_resolution"` — an aspect_ratio enum plus a resolution word, no width/height field at all). But Google publishes the pixel dimensions where Krea does not. Cross-checked 2026-09-05 against two independent sources listing the identical table:

| Ratio | 1K | 2K | 4K |
|---|---|---|---|
| 16:9 | 1344x768 | 2688x1536 | 5376x3072 |
| 3:2 | 1248x832 | 2496x1664 | 4992x3328 |
| 1:1 | 1024x1024 | 2048x2048 | 4096x4096 |
| 2:3 | 832x1248 | 1664x2496 | 3328x4992 |
| 9:16 | 768x1344 | 1536x2688 | 3072x5376 |

Every tier is an exact 2x of the one below, which is asserted rather than trusted. The ratio labels are **nominal**, as on Recraft: "16:9" is 1344x768, which is 1.750 rather than 1.778. So the enum string is looked up by ratio KEY, never recovered by matching a numeric ratio.

**The UI bug this exposed is the generalisable part.** The size readout marks krea's dimensions `~1328 x 752 (~1.00 MP, estimated)` because they are a guess. That branch was keyed on `size_style == "aspect_ratio_resolution"` — correct while krea was the only model using that style, and wrong the instant a second model shared it, since it would have called Google's published numbers a guess. **The honest question is "is this number published or invented?", which no size vocabulary can answer**, so it is now asked directly via `ModelSpec.sizes_published`. Krea is the only model in the lineup where it is False.

This is the same class of mistake as printing krea's "locked to 1K" for Recraft, and it is now the **second** time a string keyed on `size_style` turned out to be keyed on the wrong thing. The lesson: key a user-facing explanation on the *fact it asserts*, not on whatever field happens to correlate with it today.

### `output_format` is `jpg` here and `jpeg` on flux-2-pro

Same format, different spelling, and writing either one out by hand at a call site is exactly how that bug ships. Derived by `wire_output_format()` from the per-family vocabulary table; magic bytes are sniffed regardless.

**The default is UNKNOWN, not merely non-neutral.** Cloudflare states the enum (`jpg|png`) but publishes no default, and Google does not either. This differs from flux-2-pro, where the non-neutral `jpeg` default was documented and had to be countered — here there is simply nothing to reason from. It is sent explicitly for that reason: **an unknown default cannot be assumed neutral.** That question has now paid off four times on this lineup (krea's `creativity`, flux-2-pro's `output_format`, Recraft's square `size` default, and this).

Note also that this is the only family where the program *asks* for a format. A requested format is a weaker claim than a declared one, and CLAUDE.md's standing rule is that declared ones lie — so the sniff matters more here, not less.

### No seed, and the seedless path held

`supports_seed=False` was the whole of the work, as intended. The path Recraft built — GUI disables the checkbox, label and entry; `_param_note` says reproducibility is impossible rather than just greying a box; `_finish` records `seed=None` — applied unchanged. Verified rather than re-implemented: a seed passed into `_gateway_payload` is dropped, and `_finish` records None. Both are pinned, and both were checked to fail when `supports_seed` is flipped.

### Response shape: presigned URL — the fourth model at that shape

DOC-DERIVED. Read on Cloudflare's `nano-banana-2-lite` page and cross-checked against the sibling `nano-banana-2` page, which declares the identical envelope:

```json
{"gatewayMetadata": {"keySource": "..."}, "result": {"image": "https://examples.aig.cloudflare.com/google/nano-banana-2-lite/concept-sketch.jpg"}, "state": "Completed"}
```

`result.image` is an **https presigned URL**, reusing `json_url` and the existing presigned fetch unchanged, and the envelope carries the gateway `state` field. The running tally at the identical `result.image` field path is now **klein's bare base64, p-image's data URI, and a presigned URL on krea x2, flux-2-pro, recraft x2 and nano-banana** — three incompatible shapes across seven models, which is why the shape is sniffed from content and never inferred from the field name.

### `_ratio_key_for` was matching against one model's sizes for another model's request

Worth recording because it was silent. The helper that recovers the ratio NAME from a pixel size — needed by every enum-based model, since everything upstream carries pixels — was looking up `SIZES_KREA` specifically. That was harmless while krea was the only caller, but nano-banana's nominal 16:9 is 1344x768 (1.750) against krea's estimated 1328x752 (1.766), so the lookup would have been comparing one model's sizes against another model's request. It now matches against the program's own five ratios with a tolerance wide enough to cover the ~1.6% drift these nominal labels carry, and 1:1 still cannot collide with 3:2 in either direction.

### What is deliberately not sent

`image_input` (array, maxItems 3) is reference-image shaped and is a **permanent skip** like every other img2img field in the lineup. The banned-fields test covers it. That is the model's entire optional surface on Lite — there are no style dials, no filter lever, no steps, no guidance and no negative prompt, so nothing else was left on the table.

**No content-filter control.** Unlike p-image and flux-2-pro, this model exposes no lever, so a refused prompt has whatever remedy Google's own policy allows and the program's black-frame check is the only backstop. Worth knowing before picking it for prompts that were being refused elsewhere — that is flux-2-pro's job, not this model's.


## `google/nano-banana-2` — added 2026-09-05. The lineup is now COMPLETE.

Elo 1320, the highest quality available here, and by a wide margin the most expensive: **$67 / $101 / $151 per 1000** at 1K / 2K / 4K. Over the $50/1000 tolerance at every tier, so the `$$$` marker is fixed and safe — the one thing the source doc flagged as needing a re-check if a cheaper resolution ever appears. Doc-derived throughout; nothing measured against the live API.

### The only model in the program where the quality tier changes the bill

Worth stating plainly because it inverts an assumption that holds everywhere else. On the native five, tiers are **free** — Cloudflare bills per 512x512 tile, so any size inside the same tile count costs the same, which is the whole basis of the "generate large, downscale locally" advice. On every other gateway model the price is **flat per image**, so the tier changes pixels and nothing else. Here a High batch costs **2.25x** a Draft one.

The machinery was built during the Lite session and needed no changes: `NANO_BANANA_TIER_RESOLUTION` gained one three-line entry, `SIZE_TABLE_OVERRIDES` one line derived from it, and `has_tier_ladder()` began returning True on its own. `_per_resolution()` was already tested against this exact ladder at these exact prices. That was the point of building it then rather than now.

**Draft/Standard/High map to 1K/2K/4K rather than getting a bespoke fourth "Ultra" tier.** The tier names are a program-wide vocabulary meaning a quality *intent*, not an absolute pixel promise — klein's Draft is 768x432, Recraft's Standard is 1344x768, and the native Standard is 1536x864. A fourth option existing for one model out of fourteen would be dead on every other one, or would make the dropdown change length as the model changes. The size readout always shows real pixels, so nothing has to be inferred from the word. 1K sitting at Draft does read oddly against the program's usual ~1024px Standard; that is the cost of a consistent vocabulary and it is the cheaper cost.

### `google_search` and `image_search` are NOT sent — and the reason is billing, not scope

These are the two fields Lite does not have, and the obvious guess is that they are img2img-shaped like every other skip in this lineup. **Only one of them is.** Researched rather than assumed:

- **`google_search`** — the model runs Google Search before generating, to ground the image in real-world fact: live weather, current events, a real stock chart, a real landmark.
- **`image_search`** — the model retrieves real web images via Google Image Search and uses them as visual context. This one *is* also reference-image shaped.

**The disqualifying fact is that grounding is billed separately: $14 per 1000 search queries after 5000 free per month.** Google's own pricing documentation is explicit that "a customer-submitted request to Gemini may result in one or more queries to Google Search. You will be charged for each individual search query performed." So a single image can trigger an unknown number of billable queries, drawn against a *monthly* allowance the program cannot see, through a Cloudflare gateway that passes the charge through.

That is unpriceable by construction. This program's contract is that it can quote a batch before it runs, and enabling grounding would make the estimate silently wrong by an unbounded amount **on the single most expensive model in the lineup** — the exact failure mode the whole gateway effort has been structured to avoid.

**This is a COST decision and is revisitable in a way the img2img skips are not.** The reference-image fields are a permanent architectural exclusion: this is a txt2img program. Grounding is genuinely useful for a factual subject and is excluded only because its cost is invisible. If the per-query charge ever becomes visible to the client, it could be exposed as an opt-in with a loud warning. Recorded in `NANO_BANANA_GROUNDING_FIELDS` with the rates alongside, so the reasoning survives the decision.

### 4K needed a per-model safe ceiling, not a warning

At High the 16:9 size is **5376x3072 — 16.5 megapixels**, five times the largest size anything else in the lineup renders. The shared `max_safe_dimension` of 1024px exists because SD models degrade above their training size (duplicated structures, geometry drift), and left at the default it would have fired that warning here. That would be flatly wrong on a model natively specified to 4K, and worse than useless: a warning that cries wolf on a model built for the size teaches users to ignore it on the SD models where it is real. Set to the model's true ceiling, pinned by a test that also asserts the SD warning still fires.

### The cost-tier marker was pricing models at sizes they cannot serve

Found while adding this model, and fixed even though nothing moved. `cost_tier_marker()` prices every model at a **fixed reference size** (1536x864) so the marker cannot flicker as the user changes tier. But 1536x864 is not a nano-banana size, so pricing the marker there landed on `_per_resolution`'s unknown-size fallback and quoted the **dearest** tier.

That fallback is correct for a cost *estimate* — never understate a bill — and wrong for a browsing *marker*, which should describe the ordinary case. It happened to produce the right answer here, since nano-banana-2 is `$$$` at every tier. **Relying on a fallback to be right by accident is how the next model in a straddling price band gets mislabelled**, so a model that owns a size table is now marked at its own Standard size via `COST_TIER_REFERENCE_RATIO_TIER`. No marker in the lineup changed; a test pins that every override model is priced at a size it can actually serve.

### The over-budget warning now has two bands

Until this model, every paid model got the identical red line: `OVER BUDGET — $X per 1000 exceeds the $5.00 ceiling`. The same sentence at $15 and at $151 is a warning users learn to skip past, and the $5 ceiling is the wrong reference point for a model that is over the *tolerance* — a different and much larger statement.

The `$$$` band now leads with **the total for this batch** rather than the per-1000 rate, because that is the number that actually lands on the card: "$151 per 1000" reads as abstract where "this batch of 500 costs $75.50" does not. It also names the image count, so a small total is visibly small because the batch is small rather than because the model is cheap. Applied in the GUI, `cli estimate` and `cli dry-run` alike; the `$$` band keeps the original wording plus the batch total appended.


## Cloudflare AI Gateway prepaid credit — measured on a real account (2026-09-06)

Setting up prepaid credit for the eight gateway models, recorded because every one of these contradicts or adds to what the documentation implies, and all three surprised the user mid-purchase.

- **A credit or debit card is REQUIRED.** PayPal is presented as a payment option and is then **not accepted** for credit top-up — the flow lets you get most of the way there before turning you away. A card has to be set as the primary payment method first.
- **The minimum top-up is $10, and the field accepts $10-50.** The plan written the day before assumed $5 was possible; it is not.
- **The 5% purchase fee is real and confirmed:** $10 of credit cost **$10.50**. The dashboard balance shows the $10, not what was paid.
- **The dashboard journey is genuinely bad first time.** Going to the AI Gateway credits page first sends you off to add a payment method and then back again. The order that works: **Billing → add card → AI Gateway → Credits → top up.** `guide.md` now documents that order, and a first-time setup page is on the TODO.

### The API token permission question is OPEN, and Cloudflare's own docs disagree

- [REST API page](https://developers.cloudflare.com/ai-gateway/usage/rest-api/) — *"Authenticate with a Cloudflare API token that has the Account > Workers AI > Read permission"* for `/accounts/{id}/ai/*`. This documents **the exact endpoint this program calls**.
- [Get Started page](https://developers.cloudflare.com/ai-gateway/get-started/) — asks for **`AI Gateway - Read`, `AI Gateway - Edit`, and `Workers AI - Read`**. That page is written around **creating and managing a gateway by hand**, which this program never does.

The `Edit` grant is plausibly needed only for gateway creation — and the default gateway is auto-created on first authenticated request, which is the case that might need it. **The "Read all resources" template covers every READ permission in both lists**, so it remains the recommendation. Unresolved until the first live paid call: a permission failure returns **401/403** (and is free, rejected before generating), which the program reports distinctly from the **402** credit failure, so the error itself will say which.

### `build_release.bat` was not shipping the screenshots — fixed

`xcopy /q /y "promo\*"` **without `/e` copies only top-level files**, so `promo\!cloudflare info\` never reached the release: 5 files copied instead of 11. Found while verifying that a new `guide.md` pointer to that folder would actually resolve for a customer. Fixed by adding `/e`, verified 11 files. **A doc pointer to a shipped path is worth testing against the build, not the source tree.**

---

## `recipes.md` is parsed at runtime, so its FORMAT is load-bearing (2026-09-13)

The **Helpers** tab is built from `recipes.md` at load — links and copy buttons both. The document is the single source; there is no copy of the prompt text in Python, for the same reason `core/models.py` owns every price. `core/recipes.py` does the parsing, with the same path ladder the Help button walks for `guide.md`.

**The consequence to remember: editing this document can break a GUI tab**, and nothing else in the program would notice. `test_shipped_recipes_doc_actually_parses` exists for exactly that, and it also asserts that every recipe named in the GUI's `CAPTIONS` table still exists in the file — a rename would otherwise silently drop its caption.

**Two markers carry the contract:**

| Marker | Holds | Rule |
|---|---|---|
| `<links> … </links>` | one `Name - URL` per line | split on the **LAST** separator, so a name containing a dash survives; `-`, `–` and `—` all accepted |
| `<recipe name="…">` | a fenced block | the fence stays **inside** the tag |

**Markers rather than shape-matching, and this is the durable lesson.** The first design matched on shape: any bullet with a URL became a link, and a fenced block took its name from the nearest preceding heading. Both quietly capture prose added later — the "Recovering from a bad batch" section is already a bullet list, so a link added there would have turned up in the GUI for no visible reason, and the heading rule needed a tiebreak (three blocks share one heading under "Turn writing into an image") that any reformatting would break. **A marker matches intent; a shape matches accidents.**

**The fences are NOT redundant with the tags.** They are what makes each block render as a copyable code box for someone reading `recipes.md` as a document, which is still its primary job. Unknown HTML tags render as nothing in a markdown viewer, so the tags cost the document nothing while giving the parser a name it can trust.

**Placeholders are single tokens** (`YOUR_TEXT`, `YOUR_PROMPT`, `DESCRIBE_THE_LOOK_YOU_WANT`) rather than `[BRACKETED PHRASES]`, because a double-click selects one token and cannot select a phrase. Done in the document rather than as a copy-time substitution, so the clipboard is byte-identical to the file.

**Parsing must never raise.** A user can edit this file in Notepad and break it, so `load()` catches and returns empty. "Missing" and "found but unparseable" are kept as **distinct** states because they have opposite fixes — restore the file, versus restore the markers — and the GUI prints different text for each.

**GUI pitfall found here, and it is the recurring one:** the link labels sat in a bare `ttk.Frame`, which is `bg_base`, inside a LabelFrame, which is `bg_surface` — dark rectangles behind each link. Invisible when reading the code, obvious in a screenshot. Any frame nested inside a LabelFrame needs `style="Surface.TFrame"`.
