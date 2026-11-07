# Session log

What each build session actually did, and — more usefully — what it *found*. Written up here rather than in [TODO.md](../TODO.md) so that file stays a short, scannable list of work still to do.

**Read this when:** you are about to change something and want to know whether it was already tried, measured, or deliberately decided against. Durable technical facts (prices, model behaviour, API quirks) live in [findings.md](findings.md); this file is the chronological record.

Sessions are listed newest last, matching the order they happened.

---

## Session 2 results (2026-08-31) — provider layer + batch engine, no GUI

Shipped: `core/models.py` (registry + calculator), `core/providers/` (base ABC, cloudflare, pollinations), `core/imagecheck.py`, `core/db.py`, `core/prompts.py`, `core/engine.py`, `cli.py`, `tests/test_engine.py`. Phases 2 and 3 are complete.

**Verified against the live API** (free SD lane, $0): all 6 test prompts generated in 10s at 768x432 via `cli.py run`; resume, on-disk overwrite protection and `status` all confirmed; the paid `klein4b` multipart + base64 path verified with one Draft image at $0.00057, exactly the published $0.57/1000. Offline suite is 10/10 — it covers the retry taxonomy (block never retried, 429 retried, attempts capped, crash refunds the attempt) because provoking those live would mean abusing a shared free tier.

**Finding 1 — the High tier was unreachable as tabled.** 16:9 High is 2048x1152, but klein's hard ceiling is 1920 and the SD models degrade above ~1024, so *no* model could serve it. `SIZES_KLEIN_HIGH` now substitutes the largest exact-ratio, multiple-of-16 sizes inside klein's range (16:9 → 1792x1008, 8 tiles, $2.29/1000). 1:1 deliberately stays at the tabled 1536x1536: the largest legal square is 1920x1920 at 16 tiles vs 9, so it would cost more rather than being free headroom.

**Finding 2 — the content filter did not fire on a re-test.** Both spike prompts that previously returned identical all-black frames came back as real, varied images (54KB/60KB, full 0-255 range, different MD5s). Cloudflare's filtering is evidently inconsistent between runs. The `is_blank()` guard stays in regardless — it costs nothing and the black frames *were* measured once. Do not conclude from this that the filter is gone.

**High tier: KEEP — decided 2026-08-31 by side-by-side test.** Questioned as maybe-expensive and rarely-used. Tested klein-4b at 16:9 High (1792x1008) against Standard (1536x864) on the same prompt and seed 4242: High showed **no duplicated structures, no geometry drift, no edge artifacts** — FLUX.2's native 4 MP specification holds up. At **$2.29/1000 vs $1.72** it is +33% cost for +21% pixels, still under half the $5 ceiling, and it suits the documented generate-large-then-downscale workflow. klein-9b remains the genuinely expensive one, and it is already opt-in-only. **The real cost is time, not money: 16.1s vs 9.8s per image (64% slower)** — the GUI should say so where the tier is chosen, since that dominates a large overnight batch. Reference images in `out/tiercheck/`.

**Note for Session 3:** `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` are set as *user* env vars, so a shell started before they were set will not see them. Tests here read them via `[Environment]::GetEnvironmentVariable(...,'User')`. The GUI should report missing credentials clearly rather than assuming a stale shell is a missing key.

## Session 3 results (2026-08-31) — the GUI

Shipped: `main.py`, `gui/theme.py`, `gui/app.py`, `gui/scroll.py`, `gui/tabs/{prompts,provider,run}.py`, `utils/config.py`. **`core/` was not modified** — the engine suite is still 10/10, unchanged before and after.

**Verified live on the free SD lane:** a full 6-image batch through the GUI's own Start path (7s, correct `.jpg` extensions from magic-byte sniffing, 6 sidecars); a no-op resume; and a genuine partial resume — 2 images deleted and their rows released, re-run regenerated exactly those 2 and reported "2 image(s) generated. 6 of 6 done in total". Every model x ratio x tier combination was driven through the calculator without error.

**Finding 1 — the SD degradation warning overfired on the default settings.** `max_safe_dimension=1024` is one threshold covering very different outcomes. At High (2048px) SD really does fall apart, but at Standard (1536x864) it does not: lightning at 1536x864 produced a coherent scene with no duplicated structures, no geometry drift and no edge artifacts (kept in `out/sizecheck/`, alongside the Draft render — which is actually the *weaker* image). Showing identical alarming text for both would train users to ignore it, so the GUI grades the message: past 1.75x the safe limit it is a warning, below that a calm note. **The registry value was left alone** — it correctly gates the High tier, and this is a presentation decision.

**Finding 2 — "credentials missing" was the wrong diagnosis.** The engine reports missing credentials whenever the env vars are absent from the process, but the common real cause is that they exist at the *user* level and the program was started before they were set. Reporting that as "missing" sends someone off to mint a second API key. The GUI now checks the user-level value and, when it finds one, says the variable is set but not visible and that reopening the program fixes it.

**Finding 3 — every tab needed to scroll.** At the 900x640 minimum, the Provider tab's Politeness section was entirely off-screen, the Run tab's log was squeezed to a single line, and the Prompts tab's style editor was a sliver with its help text clipped mid-sentence. All three now use `gui/scroll.py`, whose scrollbar appears only when content actually overflows, and whose wheel binding is scoped to the hovered canvas so it never hijacks the log or preview widgets. Fixed `wraplength` values had the same class of bug — `autowrap()` rebinds them to the real container width.

**Theme note:** do **not** call `style.configure("TScrollbar", ...)`. ttkbootstrap intercepts it and re-runs `element_create()` on already-registered image elements, raising `Duplicate element Horizontal.TScrollbar.thumb` at startup. Scrollbars pick up the injected palette on their own.

## Session 3b (2026-08-31) — feedback round after first hands-on use

Fixes from the first real run-through. Most were layout or discoverability; two were genuine defects.

- [x] **Tooltips ran off the right edge of the screen.** ttkbootstrap's `ToolTip` places itself at `pointer + (25, 10)` with no bounds check whatsoever. `gui/tooltip.py` subclasses it and clamps to the display, flipping to the other side of the cursor when there is no room. Use `tip(widget, "text")` everywhere, never `ToolTip` directly.
- [x] **API keys are now entered in the GUI.** This was the big one: "set a Windows environment variable, then restart" is not a usable setup step, and the restart advice did not even work reliably. Keys go in an **API Keys** section on the Provider tab and save to `credentials.json` (gitignored, next to the exe, `icacls`-restricted). **Real environment variables still take priority**, so existing setups are unaffected, and keys still never touch `config.json` or the job database — which is what the original "env vars only" rule was actually protecting against. Saving publishes straight into `os.environ`, so it takes effect with no restart. Each field shows where its value comes from: *saved* / *using environment variable* / *set in Windows, needs restart* / *not set*.
- [x] **Check Credentials made the whole tab scrunch.** It ran a network call plus a PowerShell shell-out on the main thread, and forced the "Checking…" text through with `update_idletasks()` mid-relayout. Now runs on a worker thread and marshals back via `root.after`.
- [x] **Sections jerked when status text appeared.** Labels that appear, change length and vanish were resizing their frames. `reserve_lines()` holds their height. Measured stable across all 6 model x tier combinations and during a credential check.
- [x] **Style suffix box** now has a scrollbar and a drag handle to resize it (3–20 lines).
- [x] **Style preset dropdown** widened from 28 to 42 characters.
- [x] **Header is one row** — title, vertical divider, subtitle, and a **Help** button that opens `guide.md` (and says plainly that it does not exist yet, since it is written during the release phase).
- [x] **Negative prompt is a multi-line box** with a scrollbar, not a single-line Entry.
- [x] **Guidance and Steps tooltips give real ranges** — guidance 1–20 (7–8 typical, 1–2 for distilled models), steps 1–20 (Lightning ~8, LCM 4–8, SDXL Base ~20, klein fixed at 4).
- [x] **Output format selector** (`core/imagecheck.convert_image`). Providers offer no format parameter and lie about what they send, so this is a **local re-encode after download**: Keep original (default) / PNG / JPEG / WebP. The tooltip is explicit that converting a JPEG to PNG recovers nothing. Sidecar records `format`, `provider_format` and `converted_from`. Verified live — a WebP batch produced `.webp` files with `provider_format=jpg`.
- [x] **Filenames cut from ~76 to ~52 characters.** Windows still enforces a 260-character limit on the full path in many applications, and the old names spent 60 characters on the prompt including filler words. Stopwords are dropped, and words are now taken from **both ends** of the prompt — plain head-truncation kept only the boilerplate opening that every prompt in a batch shares, so `...field at day. Cloudy` and `...forest at dawn. Rainy` produced near-identical names. Covered by a new test; suite is **11/11**.

**Engine changes this round** (the two defects the GUI exposed, fixed in `core/` with tests rather than worked around in the UI): `core/prompts.py` filename shortening, and `core/engine.py` + `core/imagecheck.py` for the format conversion.

## Session 3c (2026-08-31) — format visibility, credential simplification, Pollinations modes

- [x] **The delivered image format is now visible before you generate.** Added `output_format` to `ModelSpec`, measured live rather than taken from docs: **lightning JPEG** (declares `image/png`, sends JPEG), **sdxl-base PNG**, **dreamshaper PNG**, **klein 4b/9b JPEG**, **Pollinations JPEG**. The model dropdown reads "SDXL Lightning (free, fastest) — JPEG", and a line under the format picker states what will be saved. There was previously no way to know this: the content-type header is wrong for several models.
- [x] **WebP dropped.** Poorly supported by viewers and editors, so its normal fate is being converted again — and a JPEG→WebP→JPEG round trip measured up to **36/255 channel drift**. Offering a format whose usual outcome is a lossy re-encode was unhelpful. Formats are now Keep original / PNG / JPEG.
- [x] **The converter warns when a conversion is pointless.** JPEG→PNG is flagged: measured **max channel difference 0** (pixel-identical) in a file **8.2x larger**. PNG→JPEG is flagged as permanently lossy. "Keep original" stays the default.
- [x] **Environment variables demoted to a compatibility path.** `credentials.json` is now the primary, documented route: entered in the GUI, saved next to the program, `icacls`-restricted to the current user, gitignored. Env vars are still read and still take priority so existing setups and CI keep working, but nothing in the UI tells a first-time user to go and configure one, and the "restart the program" advice is gone. Each field shows *saved* / *from environment variable* / *not set yet*, with a **Get key ↗** link to the page where the key is created.
- [x] **Pollinations split into two dropdown modes** — "no key needed" and "with API key" — because the two behave very differently. Choosing the keyed mode without a saved key is refused up front rather than silently falling back to the throttled path.

**Finding — keyless Pollinations was fighting the app's own defaults.** Measured from a real user run: keyless Pollinations queues **exactly one request per IP** and rejects the rest with `"Queue full for IP: ...: 1 requests already queued (max: 1)"`. With the default concurrency of 2, the second worker could never succeed — it only produced 429s that burned each job's retry budget, and jobs failed outright. Providers now declare `max_concurrency` (`Provider.max_concurrency`, 0 = no limit) and the engine clamps to it with a log line. **Verified: the same 2-image batch that previously exhausted all 4 attempts on line 1 and failed now completes 2/2 with zero 429s.** Keyless throughput is still genuinely slow (~46s for the second image) — that is the service, not the app.

## Session 3d (2026-08-31) — second feedback round

- [x] **Keyed Pollinations was still hitting 429s — my earlier `max_concurrency = 4 if has_key` was an unverified guess.** Probed directly: the queue limit is **per IP ADDRESS and a key does not lift it**. Six *serial* requests with a key and no delay at all succeeded 6/6, while overlapping pairs kept returning 429 whether the key was sent as a Bearer header or a `token` query parameter. An earlier probe appeared to show 2/2 succeeding only because a repeated prompt+seed is served from cache in under a second instead of being generated — which is exactly why this needed measuring with unique prompts. `max_concurrency` is now **1 for both modes**; a key raises quota and shortens the inter-request gap (15s → 1s), not concurrency. **Verified: a 4-image keyed batch now runs 4/4 with zero 429s** (was erroring on nearly every line).
- [x] **The two Pollinations modes were not actually distinct.** With a key saved, "no key needed" still sent it, because the provider read `POLLINATIONS_API_KEY` from the environment. `PollinationsProvider(api_key="")` now means "deliberately send no key" while `None` still means "use what is configured" — `or` conflated the two — and the GUI passes an explicit provider for keyless mode.
- [x] **Mouse wheel no longer changes dropdown values.** Tk lets the wheel cycle a Combobox/Spinbox whenever the pointer is over it, which inside a scrolling tab silently changed settings while scrolling past. Applied centrally by walking the widget tree after build (`_block_wheel_on_value_widgets`) so a control added later cannot reintroduce it. Verified 10/10 widgets bound.
- [x] **Image Size section no longer shifts.** Every column is pinned to a minimum width and `size_label` has a fixed width, so a longer size readout or a different ratio cannot push the dropdowns sideways. The remaining 12px height jump was the klein High-tier warning wrapping to **four** lines where only three were reserved. **Verified stable across all 45 model × ratio × tier combinations** — combobox positions and frame height are now constant.
- [x] **Tooltip flicker fixed.** The old approach let the base class place the window and then corrected it, so one frame was drawn at the wrong position. `show_tip` is now overridden to build the window hidden, measure it, compute the final in-bounds position, and only then deiconify. `move_tip` is a deliberate no-op — the tooltip no longer chases the cursor, which removes the flicker entirely and is easier to read.

**Lesson worth keeping:** two of these (the Pollinations cap, the reserved line count) were cases where I wrote down a plausible number instead of measuring one. Where a limit or a size matters, probe it — and probe it with inputs that cannot be served from a cache.


## Session 3e (2026-08-31) — CLI/GUI parity audit, layout pass, prompt-builder brainstorm

No new features. An audit session: check the CLI still matches the GUI after three rounds of GUI-only fixes, sanity-check the GUI layout, and sketch the in-app prompt builder.

**CLI had drifted behind the GUI in four ways, all now closed.** The GUI gained options across sessions 3b–3d that were never mirrored:

- `--format` / `--jpeg-quality` — the GUI's "Save images as" selector had no CLI equivalent, so `BatchConfig.output_format` was reachable from only one front end.
- `--style-text` — the GUI keeps the style suffix inline in `config.json`, the CLI could only read it from a file. A GUI user had no way to reproduce their own run from the command line.
- `--no-key` — the GUI's "Pollinations — no key needed" mode passes `PollinationsProvider(api_key="")` explicitly, so it means it even when a key is saved. The CLI had no way to exercise the keyless lane deliberately once a key existed.
- `apply_to_environment()` at startup — the CLI still read credentials from the environment only, so keys saved through the GUI were invisible to it. This made `cli.py check` report missing credentials on a machine where the GUI worked fine.

**Bug found while auditing: the dry run named files `.png` unconditionally.** `engine.dry_run()` hardcoded the extension, which contradicts the project's own measured rule that the extension must come from sniffed magic bytes and never be assumed. It now derives the real extension — a chosen `output_format` wins, otherwise the model's measured `output_format`. Verified: lightning → `.jpg`, sdxl → `.png`, `--format jpg` → `.jpg`. Worth noting the dry run is meant to be the cheap sanity check before spending money, so listing filenames the batch would never write undermined the one job it has.

**`reserve_lines()` reworked into a high-water mark.** The fixed reservation from session 3d fixed the jumping but cost roughly 150px of permanent blank space on the Provider tab, which is what the user noticed. Details and the `<Configure>`-doesn't-fire-on-clear subtlety are in [docs/findings.md](findings.md). All eleven call sites benefit without changes; measured empty → 0, grown → 96, shorter → 96 (no jump), cleared → 0.

**GUI now opens maximized** (`state("zoomed")`, with the X11 spelling as a fallback and neither fatal). The 1100x800 geometry stays as the restore-down size. Verified: state `zoomed`, 1920x991.

**Stale docstrings corrected** where the code had moved on: `utils/config.py` and `cli.py` still said credentials were environment-only; `core/providers/pollinations.py` still called the key's effects "unverified" after session 3d measured them; the Cloudflare token help text still recommended the Workers AI template rather than the verified-sufficient "Read all resources".

**Prompt builder brainstorm** written to [docs/prompt-builder-ideas.md](prompt-builder-ideas.md) — nothing agreed, open questions listed at the end for the next session.

`python tests/test_engine.py` still 11/11.

---

## Session 5 — Release prep (2026-08-31)

Worked through all three phases of `RC prompt to make releases easier.md`. The program itself was not touched: no code changes, no feature work, scope stayed closed.

**Phase 1 — materials.** Wrote `guide.md`, `readme.md` and `promo.md`, and generated the two store images into `promo/` alongside the user's three screenshots.

The guide leads with free-by-default, since that is the actual headline: three measured-zero-cost SD models, a keyless Pollinations lane, and a $1.72/1000 paid upgrade well inside the $5 ceiling. It tells users to create the Cloudflare token from the **"Read all resources"** template rather than the Workers AI one, explains that two secrets are needed (account ID *and* token) and that both are entered in the GUI with no env vars or restart, documents the CLI as a supported second front end, and is explicit that "images remaining today" is a client-side estimate rather than a measured figure — because the API reports 0 neurons even for models that bill. One honest line covers the klein-9b FLUX Non-Commercial licence restricting *serving the model* rather than the outputs.

The 630x500 thumbnail and 1280x720 cover were composited with Pillow over `assets/icon og (2).jpg`, using the app's own teal/cyan palette from `gui/theme.py` and Segoe UI Black with a multi-pass Gaussian shadow so the text holds over busy art. Two rendering bugs were caught by looking at the output rather than trusting the code: the thumbnail's title lines overlapped (hardcoded x-offsets, replaced with a `fit_font` measure-and-shrink helper), and the cover's `▸` bullet glyph rendered as tofu boxes in Segoe UI Semibold (replaced with drawn polygons). JPG ships and PNG was discarded — 72 KB vs 280 KB for the thumbnail at no visible quality cost.

`promo.md` recommends **free and open source with a tip jar** rather than paid, on the reasoning that the value ceiling is low (someone could rebuild the core in a weekend) but the trust ceiling is high, a paywall kills the exact communities where this lands best, and open source is what answers "why should I paste an API token into a stranger's exe."

**Phase 2 — build.** `build_release.bat` produces `dist/Batch AI Image Generator/`. It ships the source as well as the exe, since `cli.py` is a documented feature and publishing the source is what makes the credential handling verifiable.

Two build-script bugs found by testing rather than reading:

- **The .bat needed CRLF line endings.** Written with LF, `cmd.exe` reported `'build_release.bat' is not recognized as an internal or external command` even with the file plainly present in the working directory — a misleading error that looks like a path problem.
- **Nested `__pycache__` survived the first cleanup.** `for /d /r` only walks directories that exist when the loop starts, so `core/providers/__pycache__` and `gui/tabs/__pycache__` shipped. Replaced with `for /f` over `dir /s /b /ad`, which collects the paths first. Verified by rebuild.

The script also **aborts if `credentials.json` or `config.json` appear in the release folder**, since those live beside the program and are the most likely way a token leaks into a public zip.

**Phase 3 — cleanup.** Moved to `old wip/`: both session plans, the original spec draft, `spike/`, the parked CoW objectName bug report, the two loose Advance Wars style JPGs (duplicates of files in `style images inspo/`), and `out/` renamed to `out (test batches)`. Kept `docs/findings.md`, `docs/session-log.md`, `tests/`, `assets/` and `original reason for this program/` — the mods are the next phase and depend on that last one. Extended `.gitignore` for `dist/`, `build/`, `*.spec`, `old wip/` and editor folders, and corrected its stale header claiming credentials live in env vars.

`CLAUDE.md` rewritten for post-release maintenance: development narrative dropped, architecture and measured provider facts kept, the closed-scope decisions stated explicitly as decisions so they don't get "fixed" back in.

**Verification.** `python tests/test_engine.py` 11/11. The packaged exe was copied to `C:\trash\cleantest1\` and launched from there — it runs, `IsZoomed` confirms genuinely maximized, the theme and all three tabs render, the window icon loads, and it started with **empty credential fields**, confirming it picks up nothing from the dev folder. It wrote a fresh defaults-only `config.json`. `guide.md` and `assets/icon.ico` are both present beside the exe for the Help button and window icon. The shipped `cli.py` was run from the release folder and reports the documented prices (klein4b $1.72/1000, SD models free).

**One thing not verified, and flagged in `promo.md` itself:** Reddit was unreachable from this machine — reddit.com, its JSON API and old.reddit all blocked, and web searches returned only generic third-party "self-promotion rules" articles. The subreddit recommendations are based on general knowledge of those communities, each carries a note on its known posture, and the file says plainly at the top that the sidebars still need checking before posting.

---

## Session 7 — Test-run slider, negative presets, prompt length counters (2026-09-02)

Three post-release GUI features, all driven by the same idea: make the expensive or invisible thing visible before it costs anything.

**The Generate slider.** A `ttk.Scale` under the preview on the Prompts tab caps a run at the first N prompts, so a style can be tried on 5 of 100 without maintaining a second prompt file. It defaults to the maximum every time a file is loaded — a file you just chose should generate in full unless you say otherwise.

Two decisions worth keeping:

- **It takes a prefix, not a sample.** Resume identifies a job by line number, so the first N of a capped run and the first N of a later full run are the same jobs. Verified end-to-end: after a `limit=2` run over a 4-prompt file, the uncapped run made exactly **two** API calls, for prompts 3 and 4. A random sample would have made a test run cost extra on every subsequent full run.
- **`limit` is applied in `BatchEngine.load_lines()`** — the single point where prompts enter the engine — so the job planner, the cost estimate and the dry run cannot disagree about how many images a run makes. `_prompt_count()` on the Provider tab honours it too, otherwise the calculator would quote a 100-image price for a 5-image test.
- **"All" stores `None`, not the number.** A stored `100` would silently cap a prompt file that had since grown to 120.

Prompts past the cut stay in the preview, struck through in a new low-contrast `text_muted` palette entry, rather than being hidden — seeing where the cut falls is the point of a preview. `cli.py` gets `--limit N` (as `dest="prompt_limit"`, since `status` already had its own `--limit`).

**Negative presets.** Same shape as the style presets, deliberately: same dropdown, same Save As / Delete buttons in the same order, same restore-the-built-ins-if-emptied behaviour. One built-in for now, **Universal Clean-up**, plus a "None" entry. It carries no anatomy terms — they are dead weight on landscape and background work, and every wasted word costs real room against a 77-token budget. The larger pile in `WIP todo styles etc/negatives.txt` is explicitly a **later brainstorm**; shipping a half-sorted version of it would be harder to correct than shipping nothing.

**Prompt length counters.** Soft character counters under the style editor and the negative prompt box, grading ok / near / over.

The measurement that shaped this: **the encoders truncate silently** — no error, no warning, nothing in the image — and the budget differs by roughly 7x across the lineup (CLIP's 77 tokens ≈ 300 characters on the SD models, versus FLUX.2's 512 ≈ 2000 on klein). A single number in the GUI would have been wrong for half the models, so the limits live in `ModelSpec` as `prompt_soft_limit` / `prompt_hard_limit` and the label re-grades when the model changes. Full write-up in `docs/findings.md`.

The counter measures the **longest prompt in the file plus the style suffix**, not the suffix alone: that combination is what is actually sent, and measuring the suffix by itself would read comfortably short right up to the moment the model truncated it. The longest line rather than the average, because the longest is the one that decides whether anything is lost at all.

Nothing truncates. The counters are advice — some prompts tokenize far better than a character estimate suggests, and silently cutting a user's text would be the same fault as the API's, committed one layer earlier.

**Verification.** `tests/test_engine.py` extended to **14/14** with three new cases: the limit takes the first N and a full run reuses them (asserted on API calls, since the reused jobs are already `DONE` in the reattached batch and so are never counted as skips), an absent or oversized limit means everything, and length advice grades per-model without mutating the text. A GUI smoke test built the real app against a throwaway config and drove every new widget — slider defaults to max on load, caps the dry run at 5, "All" restores; the negative preset loads and updates its counter; and the same 390-character prompt graded `danger` on SDXL Lightning and fine on klein-4b, which is the per-model behaviour working.

Two bugs the tests caught rather than review: the `_prompt_count` rewrite dropped the local `core.prompts` import without the module-level one landing (a `NameError` reached only by loading a preset), and the first version of the reuse test asserted on `skipped`, which is always 0 on that path — the reuse is real, the counter was simply the wrong thing to measure.

---

## Session 8 — Stackable negative layers, shipped docs (2026-09-02)

A design session first, then the code. The decisions and their reasoning are in `docs/preset-and-docs-plan.md`; this is what was built.

**The measurement that reframed everything.** Positive and negative prompts have **separate** token budgets — CFG encodes them in separate passes. A heavy negative costs the scene description nothing. That invalidated a comment shipped the session before ("every wasted token costs real room"), and more importantly it changed the design: if stacking negatives is cheap, the only question is relevance, which is what made layers worth building.

**Negative presets became stackable layers.** Checkboxes replace the single-select dropdown; ticking joins the layers into the box, deduplicated case-insensitively with first-occurrence-wins so ordering survives. `compose_negative()` and `split_terms()` live in `core/prompts.py` — pure and testable rather than buried in the GUI.

Decisions worth keeping:

- **Ticking REPLACES the box.** A merge would make it impossible to untick a layer and actually be rid of its terms. Hand edits survive until the next tick, and that trade is stated in the tooltip.
- **Delete requires exactly one ticked layer.** With checkboxes there is no "selected" item; guessing which of three to delete would be worse than asking.
- **The empty `"None"` preset was dropped** and is migrated away on load. It existed so the dropdown could mean "no negative prompt"; with checkboxes that is just nothing ticked, and an empty layer is a confusing no-op.
- **A composed set cannot be saved as a named preset** — rejected as presets-containing-presets for no gain, since re-ticking is trivial.

`Human Anatomy` was added as a second built-in so stacking is demonstrable out of the box. Style presets were deliberately **not** changed: no core/extended split, no metadata — both rejected as complexity the user already controls, and the split would have broken plain copy-paste.

**Two shipped documents**, `prompting.md` (craft: length limits, structure, the say-what-you-want lesson) and `recipes.md` (cookbook: LLM prompts for building style presets, text-to-image vignette/metaphor, batch timing). Split by *when they are read* rather than by topic. `guide.md` keeps everything it had and gains pointers; migrating content out would risk someone missing it. Batch-timing advice ships **explicitly flagged as folklore** — it is unmeasured LLM-sourced guidance and says so rather than presenting a confident table.

**A wrong claim caught by checking it.** The first draft of the recovery section in `recipes.md` said that deleting images and re-running would regenerate them. It does not: the database still marks those jobs done, so **zero** API calls happen. Both the images and `.batchgen.db` must go. Plausible, consistent with a reasonable reading of the code, and false — written up in `docs/findings.md`.

**Verification.** Offline suite **15/15**, with a new case covering layer composition (order preserved, deduplicated, nothing lost, degenerate inputs clean). The GUI smoke test now drives the layers: one layer, two stacked and deduplicated, unticking actually removing that layer's terms, and hand edits surviving. A **two-process restart test** confirms ticked layers and hand-edited text both come back — two `ttk.Window()`s cannot coexist in one process, since ttkbootstrap's global Style holds the destroyed root, so the legs run as separate processes.

Not done, by decision: the Cloudflare truncation probe (next), and the preset content pass over `positives.txt` / `negatives.txt` / the `art styles ___.md` files (its own session — enough material there to need the context).

## Session 8b — the truncation probe, and a DreamShaper defect (2026-09-02)

**Truncation: confirmed.** Cloudflare's SD models really do cut long prompts. A 715-character woodland prompt with "a giant yellow rubber duck" at the front renders a duck dominating the frame; the identical words with that clause moved to the end render no duck at all, on both Lightning and SDXL Base. Same seed, same steps. The ~300-character guidance already shipped is correct and now measured rather than inferred.

**The first probe was badly designed and proved nothing**, which is the more useful lesson. It compared a *short* front-loaded prompt against a *long* buried one -- two variables at once -- and sent no step count, which broke DreamShaper into abstract garbage. Round 2 fixed both: identical words in both cases with only the position differing, and each model given its own `default_steps`. **The control that matters is the same prompt reordered, not a different prompt.**

**What the probe could not do, and why we stopped.** It shows truncation happens; it cannot show WHERE the cut falls. The API returns image bytes only -- no token count, no truncation flag, no echo of the parsed prompt. Finding the boundary behaviourally (bisecting on whether the duck rendered) was started and then abandoned as a bad idea: SD models take enough creative liberty run-to-run that one "gone" reading does not reliably reproduce, so the result would have been false precision. The boundary is instead taken from the architecture, which is documented: DreamShaper 8 LCM is fine-tuned from SD 1.5, which uses CLIP ViT-L/14, which is 77 tokens. Sources recorded in findings.

**An unrelated defect found by accident.** DreamShaper 8 LCM returns a 1223-byte pure-black frame for "a red squirrel on a mossy tree stump in a woodland clearing" -- a completely innocuous prompt that Lightning renders perfectly with identical parameters. Nearby rewordings return images with the blue channel crushed to 0-31, giving lurid green-and-black output with the composition intact.

Ruled out: step count (4-20 all fine), seed, and prompt length (a 500-character red-barn prompt is fine). It tracks the *content* -- green woodland scenes break it.

**The program's behaviour here is correct and must not be changed.** `is_blank()` requires a genuinely uniform frame, and the model really is returning flat black, so reporting a content block is the right call from the information available. Only the explanation is misleading. Documented in `models.py`'s `price_note` (so it surfaces in the model dropdown), `guide.md` troubleshooting, and `recipes.md`.

**Docs reworked to instruction.** `prompting.md` gained the full building-blocks reference -- shot sizes, camera angles, composition, lighting, medium, emphasis modifiers -- laid out vertically as in the source doc, each entry annotated with what it *does* to the viewer rather than just what it is. Camera *movement* terms were deliberately dropped, with a note saying why: they describe motion over time and mean nothing to a still image. `recipes.md` switched its copy-paste prompts from `>` quote blocks to fenced code blocks (quote blocks copy badly out of a plain-text editor) and gained links to Claude, ChatGPT, Gemini and Perplexity.

---

## 2026-09-03 — Preset content: a naming scheme, 55 styles, 20 negative layers

The preset *system* was already built and tested; this session was content plus the naming scheme that had to be agreed before any content could be written. Deciding categories after writing forty presets means renaming forty presets, so the scheme was gated as its own phase and written to [preset-naming-scheme.md](preset-naming-scheme.md) before a single preset body was drafted.

### The source material, and how much of it survived

Four files in `WIP todo styles etc/`, heterogeneous on purpose.

**`art styles rcg.md` (116 lines)** — the curated one, and the backbone. Written to the right spec already (NAME + style-only body). Most entries lifted with light trimming. Cuts: `PREMIUM PRODUCT SHOT MAX` (it is `MIN` with every instruction restated in synonyms), the elaborate `FUTURISTIC HUMAN HABITAT` (same content, twice the words), and the trailing "THINGS I GENERALLY NEED" / "SPECIAL SIGNATURE" blocks, which are personal branding notes rather than presets.

**`art styles beauty.md` (36 lines)** — nine entries at 700–1250 characters each, i.e. **over SD's entire ~300-character budget by up to 4x**. Flagged before the session started, and the fix was trimming to 390–450 rather than dropping them. Living-photographer names were removed **from this group only**, purely to buy back length; artist names are kept everywhere else because they are a legitimate and effective prompting technique.

**`positives.txt` (274 lines)** — mostly process archaeology. Lines 203–275 are five iterations of a *prompt for asking an LLM to write style prompts* (that is a `recipes.md` topic, already covered); lines 57–120 are a 60-title game list with no prompts attached. Genuinely salvageable: the Planetary Annihilation design-doc extract (the best entry in the file — the developers' own words, concrete and unusual), the de-branded XCOM description, Astroneer, and Mario Galaxy. The artist list on line 4 became the whole of `09 ARTIST`.

**`negatives.txt` (182 lines)** — rebuilt from scratch rather than salvaged, at the user's direction. It is **the same ~40 terms shuffled into eight different orders** (lines 4, 10, 22, 28, 31, 34 and 45 are all permutations of one anatomy-plus-quality pile), collected from scattered folders as a word cloud to pick ideas from. The vocabulary was kept; the structure is new.

### What was deliberately not carried over, and why it would have been inert

Three categories of term in the source do **nothing** on this provider lineup, and shipping them would have looked like function while being noise:

- **Embedding filenames** — `verybadimagenegative_v1.3`, `ng_deepnegative_v1_75t`, `DeepNegative`, `fastnegative-xl`. These are textual-inversion files that only do anything when the embedding is installed locally. On a hosted API they encode as the literal words.
- **Pony Diffusion tag conventions** — `score_6`, `score_5`, `source_pony`, `source_furry`. Meaningless on SDXL, DreamShaper and FLUX.
- **Attention-weighting syntax** — `(ugly face:0.8)`, `((monochrome))`, `[term]`, `::`. **The Cloudflare and Pollinations APIs do not parse these**; the parentheses and numbers are encoded as text, wasting budget and mildly corrupting the term. The bare terms were kept, the wrapping stripped.

Also cut: the ~110-entry positive-framing list at lines 59–179. Its useful half is what `Quality Floor` and `Clean Background` already express as negatives; the rest ("captivating visual flow", "emotional depth") is inert affirmation. Its one real contribution — the clutter and background terms — became `Clean Background`.

### The naming scheme

`NN GROUP - NAME`, ten groups from `00 NONE` through `09 ARTIST`, ordered by how often you would reach for something blind rather than by quality.

**Two digits, not one.** The dropdown is ordered by a plain `sorted()` on the preset names — that is the entire ordering mechanism, so **the name is the sort order**. A single digit breaks at ten groups, where `10 X` sorts between `01 X` and `02 X`. Two digits costs one character and never breaks.

**The number exists to decouple sort position from group name.** Alphabetical group names would sort `ARTIST, ASSET, BEAUTY, COOL, GAMES, MAIN…` — alphabetical order has nothing to do with usefulness, and the generalists a new user wants would be scattered through the middle.

**One gap caught during review:** the first draft had `01 MAIN - PHOTO PRO` alongside `02 PHOTO - PROFESSIONAL` — the same preset in two places. Dropped. The same preset under two names makes a user wonder how they differ, and "they don't" is the worst possible answer in a dropdown.

### User presets sort above the built-ins, by mechanism rather than convention

Agreed that a user's own presets belong at the top, marked with a leading `*`. `*` is ASCII 42 and digits start at 48, so a plain sort already does this — but only for names that actually carry the asterisk, and a name typed without one would land somewhere in the middle of the built-ins. So `_preset_names()` now **partitions on membership in `BUILTIN_PRESETS`** and returns non-built-ins first, making it true regardless of the name. The Save As dialog pre-fills `*` (or `*` plus the current built-in's full name when saving a tweak), so the asterisk is the visible cue for a rule already enforced underneath.

**The two original presets are seeded as `*Painterly` and `*Comic`** rather than kept as built-ins — a user decision, and a good one: they double as a worked example of the convention sitting right there at the top of the dropdown on first run. They live in `SEEDED_USER_PRESETS` and are merged by `default_style_presets()`, deliberately *not* in `BUILTIN_PRESETS`, or the top-sort would push them down.

### Migration, which needed more care than expected

Three paths, all tested against real config files:

1. **Upgrading from the shipped version** — `Painterly`/`Comic` are renamed in place to `*Painterly`/`*Comic`, and the rename follows through to `last_preset` so a returning user's selection is not left dangling.
2. **The superseded negative layers** — `Universal Clean-up` and `Human Anatomy` are dropped **only if byte-identical to what shipped**. An edited copy is the user's work and survives untouched. Verified both ways.
3. **Fresh install** — 55 built-ins plus the 2 seeded, selection defaults to `01 MAIN - DIGITAL ART`.

A stale ticked layer (`negative_layers` naming a preset that no longer exists) was already handled by an existing filter at the end of `load_config`; confirmed rather than re-implemented.

### Verification

`15/15` offline tests pass. Every one of the 55 style presets measured at **300–500 characters** — the tightened range agreed for this roster, deliberately above SD's ~300 budget and far below FLUX's ~2000, so the front of each preset is what SD sees and the tail is what klein gets. Nothing was padded to reach the range.

The **style-only rule** was checked by scanning every preset body for concrete subject nouns. Every hit was a substring false positive — "car" inside *cartoony*, "man" inside *manicure* and *manga*. The only genuine `human` occurrences are in `06 COOL`, which is the documented exception.

The GUI was launched headlessly and the real widgets inspected: 57 dropdown entries in the right order, fresh install selecting `01 MAIN - DIGITAL ART`, and an upgraded config correctly showing `*Painterly`.

### The finding that came out of testing

Measuring composed negative stacks turned up something that qualifies the design basis and is now in [findings.md](findings.md): **"stacking is nearly free" is true against the positive budget but not against the negative's own.** One layer is ~283 characters, so on SD *roughly one layer fits* — two typical layers already overflow, and the excess is silently dropped exactly as it is in a positive prompt.

This changes no code (the existing `refresh_negative_hint()` already grades the composed text against the selected model's limits, so the warning was already correct) and argues for no smaller layers (a layer trimmed to fit two-at-a-time on SD would be worse on klein, where seven fit). But it does make **layer order a quality lever on SD**, since layers compose in list order and the tail is what gets cut.

Deduplication was also measured: only **12 terms** overlap across all 20 layers, so dedup saves tens of characters, not hundreds. Its job is correctness — not repeating a term, which on SD is unintended emphasis — rather than compression, and it must not be relied on to keep a stack inside a budget.

### Left open

`08 GAMES` ships with four entries and is deliberately unfinished. A game preset earns its slot by capturing camera and rendering nuance the generic styles cannot — isometric versus side-on versus top-down, FOV and lens, pixel art versus HD sprites versus low-poly — and that needs per-title research rather than improvisation. The 60-title list in `positives.txt` is a wishlist to be trimmed by hand first. Super Metroid's *dark atmospheric* pixel mood was identified as a genuine gap and noted in `TODO.md`.

---

## 2026-09-05 — Gateway models, phase 1: shared groundwork + `pruna/p-image`

First of the eight Cloudflare **AI Gateway** models. Explicitly **no live testing** — no prepaid credit was available to spend, so everything was written against documentation plus the field lists already verified at zero cost via the API's own 400 rejections.

### Why p-image first

It is the architectural pathfinder rather than merely the cheapest. Every gateway model needs the same three pieces of machinery that did not exist (body-addressed calls, flat per-image pricing, a per-family size vocabulary), and p-image is the smallest model that forces all three. It is also the only one that can express size **both** as an enum and as pixels, so it exercises both paths of the new size abstraction. And it sits *exactly on* the old $5/1000 ceiling, so it needed no amendment of its own — the `$$`/`$$$` tiers could be built without any model yet depending on them.

### Built

- `ModelSpec.call_style` (`native`/`gateway`) — the model id moves from the URL path into the request body. `_gateway_payload()` builds it.
- `ModelSpec.size_style` + `SIZE_TABLE_OVERRIDES` — a model can now own its **whole** size table, not merely substitute at High as klein does.
- `_flat_per_image()` + `ModelSpec.bills_per_tile` — flat per-image pricing, with tile counts suppressed everywhere they would mislead (GUI readout, `cli estimate`, `cli dry-run`).
- `cost_tier_marker()` — the `$`/`$$`/`$$$` dropdown markers, **derived** rather than stored so they cannot drift from `price_fn`, and computed at a fixed reference size so they never flicker as the tier changes.
- Error taxonomy: **7003** as a named `PermanentError`; **402** as `QuotaExhausted` (fatal, never retried).
- 8 new offline tests. **26/26 pass.**

### Three things this session got wrong first, and caught

1. **`SIZES_PIMAGE` was eyeballed and illegal.** The obvious 16:9 at a 1440 cap is 1440x810 — but 810 is not a multiple of 16. The largest legal 16:9 is **1280x720**. A three-line computation caught it before it became a permanent 400 on every 16:9 job. *The x16 rule binds harder than the pixel cap.*
2. **The data-URI trap.** Gateway models return `data:image/jpeg;base64,...` at `result.image`; klein returns **bare base64 at the same field path**. Verified locally that `b64decode()` does **not** raise on the data-URI form — it returns garbage silently, which would have failed the decode check as *transient* and retried every job of a paid batch. The strip is driven by content, never by declared encoding.
3. **"free model — no neuron cost" was printed for a paid model.** `free_images_per_day` returns `None` for two unrelated reasons, and the CLI's old `else` assumed only one of them. Now three branches.

Also corrected: the wishlist doc said P-Image returns a **download URL** and warned an extra-GET mechanic would be needed. Cloudflare's own model pages show base64 — confirmed on two Pruna models. **There is no extra-GET mechanic to build.**

### Scope decision recorded

The **$5/1000 hard ceiling is amended, deliberately.** It now governs the `$` tier and the *default* model choice rather than the whole lineup; `$$`/`$$$` are opt-in, marked, and still warn. Written into CLAUDE.md and `BUDGET_CEILING_PER_1000` so a later session does not revert it.

### Left open on purpose

`disable_safety_checker` is **not** wired up — it is never sent, so the provider default applies. Deferred to the same session as flux-2-pro's `safety_tolerance` so both filter controls get one consistent GUI treatment rather than two ad-hoc ones.

**Nothing here has touched the live API.** Every unverified assumption is listed in the table at the bottom of [gateway-models-todo.md](gateway-models-todo.md). Next: `krea/krea-2-medium-turbo`.

---

## 2026-09-05 (cont.) — Gateway models, phase 2: the krea pair

Continued in the same session as p-image, because the groundwork built there is exactly what krea needed and the context was still hot. Still **no live testing** — no prepaid credit to spend.

### What krea added that p-image did not

- **The presigned-URL response shape.** `result.image` is a URL, so the bytes need a **second HTTP GET**. This is the extra-GET mechanic the wishlist doc predicted for p-image — wrong family, right prediction. `_PresignedURL` (a `str` subclass, so it can never be mistaken for image bytes downstream) marks it, and `_fetch_presigned()` performs the fetch at the call site, which has the client.
- **A model with NO tier ladder.** `has_tier_ladder()` plus `_fixed_size_table()`; the tier dropdown is **disabled** with an explanation rather than left doing nothing silently.

### Two security/correctness calls in the fetch

- **No `Authorization` header on the presigned GET.** The URL is already signed, and forwarding the Cloudflare token to a third-party host would leak the credential. Tested — the token must not appear in the outgoing headers.
- **Fetch failures are TRANSIENT.** The image was generated and *billed* before the URL was handed over, so a failed fetch means a paid image was lost; retrying is the only way to get it back. Non-HTTPS URLs are refused outright rather than downgraded.

### Worse than the wishlist said

krea "cannot serve the High tier" understates it: locked to `1K`, it cannot serve **Standard** either (~1328x752 vs 1536x864). And Krea does not publish what 1K resolves to per ratio. Handled structurally rather than by guessing — the pixels are **never sent** (the model takes a ratio enum), so a wrong estimate cannot break a request; it is shown with a `~` and "estimated", and the true size is sniffed into the sidecar metadata on the first real run.

### Style dials: researched, then deliberately declined

All four now have documented ranges (`KREA_STYLE_DIALS`). **Every default is the neutral value**, so omitting them is equivalent to sending them. Left out because a global per-run dial is already what the style-suffix file does, in plain text. Noted that `creativity: "raw"` (disables prompt expansion) is the one worth exposing if that is ever revisited.

### One bug caught in existing code

The param note printed **"has a fixed step count of None"** for both gateway families — the old text assumed `steps_settable=False` always meant a *known* fixed count (klein's 4). Gateway models take no steps parameter at all, which is a different thing. Now two branches.

**32/32 offline tests pass** (6 new). Next: `black-forest-labs/flux-2-pro-preview`.

---

## 2026-09-05 (cont.) — prompt expansion exposed; img2img fields skipped permanently

A follow-up to the krea work, from a user question about the four style dials.

**`creativity` was wrong to leave unset.** The first pass treated all four krea dials as equivalent and omitted them all, reasoning that every default was neutral. That is true of `intensity`/`complexity`/`movement` (all default 0) but **not** of `creativity`, which defaults to `"low"` — prompt expansion **ON**. Omitting it meant silently accepting prompt rewriting.

Now sent **always**, defaulting to `"raw"` (off) — deliberately diverging from the API default. The reasoning is specific to this program: the text sent is *prompt + style suffix*, and expansion rewrites the concatenated whole, so it can reword the **style addon** as readily as the subject. That is the worse failure, because the style suffix is the one part meant to stay identical across an entire batch.

Exposed rather than hardcoded, since expansion helps short or sparse prompts. GUI dropdown (labelled "Off — use my prompt exactly" rather than the API's opaque `raw`), a `--prompt-expansion` CLI flag, and an inline note in the parameter summary so the setting is visible **without** hovering a tooltip.

**Reference-image fields confirmed as a PERMANENT skip:** `styles`, `image_style_references`, `moodboards`, `image_input`, `input_images`. All img2img-shaped; this program is txt2img. A test now asserts none are ever sent.

New `ModelSpec.supports_prompt_expansion` gates it, so callers pass the setting unconditionally and the spec decides whether it reaches the wire. `prompt_expansion` added to `BatchConfig` and the `Provider.generate` interface (Pollinations accepts and ignores it).

Also fixed while here: the parameter note said **"has a fixed step count of None"** for gateway models — the old text assumed `steps_settable=False` implied a *known* count (klein's 4), but gateway models take no steps parameter at all.

**35/35 offline tests pass** (3 new). Next: `black-forest-labs/flux-2-pro-preview`.


---

## 2026-09-05 — Gateway model 4: `black-forest-labs/flux-2-pro-preview`, and the content-filter controls

Fourth gateway family. Also the session where the **content filter finally became something a user can touch**, which was the actual reason this model was on the list — its Elo (1207) is *below* the cheaper Krea Turbo, so it was never bought for quality.

**No live testing**, as with every gateway model so far: no prepaid credit, and the neuron allowance is still blocked. Everything here is documentation-derived and coded defensively, with the unverified parts flagged in the tracking doc rather than quietly assumed.

### What the research settled

Three things were genuinely open going in, and Cloudflare's published schema closed all three (two of them read twice, independently, in agreement):

- **Response shape** — `result.image` is declared `format: uri`, i.e. a **presigned URL**. That is krea's shape, so `json_url` and the existing presigned-fetch path were reused unchanged. Worth noting that the lineup now carries **three incompatible encodings at the one `result.image` path** (bare base64 / data URI / URL), which is exactly why `_extract_image` sniffs content rather than trusting the declared encoding.
- **`safety_tolerance` direction** — 0 is strictest, 5 most permissive, default 2. The source doc's read was right. Pinned by constants and by a test whose only job is to stop a later edit inverting it.
- **`output_format` default** — `jpeg`, which is **not neutral**. Sent explicitly for the same reason `creativity` is: a field whose default is not the neutral choice is worth stating.

### What needed no work at all

flux-2-pro takes true pixels, minimum 64, **no multiple-of-16 rule**, no upper bound found. Every size in the program's shared `SIZES` table clears both constraints — checked, not eyeballed — so it is the **first gateway model with no size override and a fully working Draft/Standard/High ladder**. p-image needed its own whole table; krea has no ladder at all.

### The content-filter controls

Built as **one** setting for **two** models that disagree about how to express it — p-image's `disable_safety_checker` is a boolean, flux-2-pro's `safety_tolerance` is an integer 0–5. Three modes (`default` / `permissive` / `off`), mapped per-model by `filter_value_for()` so nothing outside `core/models.py` knows which field a model speaks.

p-image's field had been deliberately left unwired since it shipped, precisely so both could get one consistent treatment. That is now done: GUI dropdown (enabled on exactly those two models, disabled elsewhere with an inline note explaining that a refused prompt comes back as a black frame), a `--content-filter` CLI flag, `BatchConfig.content_filter`, and the setting recorded in the sidecar metadata.

The `default` mode **sends nothing at all** rather than pinning the documented value — the opposite call from `creativity`, and for a reason worth keeping straight: a filter's provider default *is* the neutral choice, whereas krea's expansion default is not.

**Reversed within the session: the program now DEFAULTS to `permissive`.** The first draft started on `default`, arguing that loosening a filter should be a knowing decision. That is the right call for a one-off generator and the wrong one here — a batch tool pays for a spurious refusal with a slot in an overnight run of hundreds, discovered the next morning, not with a rerun. The user also confirmed the failure mode is a live annoyance rather than a hypothetical: **Cloudflare runs a vision check over the OUTPUT image**, so ordinary prompts get flagged on the strength of a frame nobody asked for and nobody can inspect. Shipping the only lever in the lineup set to "off" would hand the user the annoyance without the remedy. It still does not disable moderation — it asks for the loosest setting each model itself publishes, and the provider's own limits are unchanged.

### Fixed while in there

A **pre-existing grid collision** in the Generation Settings frame: the prompt-expansion combobox and the random-seed checkbox were both gridded at `row=4, column=0`. Adding the filter control meant laying that region out properly, so the seed block moved to row 6 and the parameter note to row 7.

### Blocked prerequisite, left open

The checklist wanted the flagged Advance Wars prompt re-run on klein 4B at a fixed seed *before* this model was built, to learn whether the 3030 output-flag reproduces or was an unlucky roll. That is gated on the neuron allowance clearing and still cannot be done. **Built anyway** — the model and the filter controls are worth having either way; only the *urgency* depended on that test. The box stays ticked open.

**41/41 offline tests pass** (6 new, covering the pixel-exact size mapping, flat $30/1000 pricing, the safety_tolerance direction, the send-nothing default, the two-field mapping, and the jpeg/jpg wire spelling). GUI verified to build and the control verified to enable on exactly the two models that have it. Next: `recraft/recraftv4-1-utility`.


---

## 2026-09-05 — Gateway model 5: `recraft/recraftv4-1-utility`

Fifth of the eight gateway models, and the one the phased plan flagged as awkward. No live calls; documentation and cross-checked online sources only, as with every model since p-image.

### What made it different from the previous four

Recraft is the first model in the lineup whose **bad request is not free**. Every field list in this project was verified at zero cost by leaning on the gateway rejecting a malformed body before charging — 400 naming the legal fields, 402 when the shape was right. Recraft's gateway type-checks only that `size` is a *string* and hands the value check to Recraft, so a bad size gets past, is billed, and fails at generation time.

That single asymmetry drove most of the work. `size` is validated client-side against the published enum by `recraft_size_string()`, which is the only legal source of the value, and `ModelSpec.validate_size()` routes enum models through it too — so the GUI readout and `cli dry-run` refuse a bad size as well, not just the provider at request time. **That second part turned out to matter**: `1024x768` sits inside Recraft's 768–1344 bounds and is a multiple of 16, and the min/max check waved it straight through. Confirmed fixed against the CLI.

This also implemented `size_style="size_enum"`, the fifth size vocabulary — declared in the `SizeStyle` Literal since the p-image session but raising `PermanentError` until now.

### Findings worth keeping (all in findings.md)

- **Recraft's own default for `size` is `1024x1024`, a square.** Silence would have rendered a whole 16:9 batch as 1:1 crops. Third time this lineup has produced "check what the default actually is before assuming omission is neutral" — after krea's `creativity` and flux-2-pro's `output_format`. That question is now worth asking of every remaining model as a matter of course.
- **The ratio labels are nominal.** Recraft's "16:9" is 1344x768 = 1.75, not 1.778 — krea's `_ratio_key_for()` tolerance of 0.02 would not have matched it, which is why the enum is looked up by ratio key instead.
- **Response is a presigned URL** with `state: "Completed"`, i.e. the krea/flux-2-pro shape. Read on the utility page, independently on the `recraftv4-1` page, and cross-checked against a third-party listing of the same response. Reuses `json_url` and the existing fetch unchanged.
- **No seed at all.** Beyond disabling the GUI controls, `_finish` now records `seed=None` whenever `supports_seed` is False — recording the engine's unused generated seed in the sidecar would have promised a reproducibility that does not exist. nano-banana will need the same.

### Two pieces of existing text that were quietly wrong for a second model

Both found by actually launching the GUI and switching models rather than by reading the code:

- The tier-disabled warning said "it is locked to 1K resolution" — krea's reason, and a plausible-sounding lie about Recraft. Now branches on `size_style`.
- The "~ estimated" size readout keyed on "has no tier ladder", which caught Recraft too. Krea's sizes are genuine guesses; Recraft's are published exact values sent verbatim, so marking them estimated was the mirror-image dishonesty. Now keyed on `size_style == "aspect_ratio_resolution"`.

A build-order bug also surfaced only by running it: `_on_seed_mode()` fires during `_build_generation`, before the model dropdown exists, and reached `_current_spec()` on a missing attribute. Guarded.

### Deliberately not done

`style` / `substyle` / `controls` all left unset — optional, and `style`'s enum is unconfirmed for the gateway path (Recraft's *native* docs give `realistic_image` as the default, but that is a different API surface). Unlike `size`, a missing style cannot produce a wrong-shaped image, so silence is safe. `controls.image` is reference-image shaped and joined the banned-fields test.

**48/48 offline tests pass** (7 new: the validated size enum, the local refusal of an illegal size, `size` always being sent against the square default, no-seed/no-tier-ladder, the flat $35/`$$`/presigned-URL shape, 16:9 being smaller than Standard, and seedless models recording no seed). GUI verified by launching it and reading back the widget states on four models. Next: `recraft/recraftv4-1` — the same field list and the same size enum, so it should be nearly free.

---

## 2026-09-05 — Gateway model 6: `recraft/recraftv4-1` (same session as Utility)

Continued straight on from Utility rather than starting fresh, because the second model of the pair is the same field list, the same size enum and the same response shape — the risk the one-family-per-session rule guards against was not present, and everything it depends on was already loaded and verified.

Confirmed independently rather than inherited: fetched the `recraftv4-1` model page and checked its field list (`prompt`, `size`, `style`, `substyle`, `controls`, `image`; no seed, no width/height, no `aspect_ratio`) and its response example against Utility's. Identical, including the presigned URL and `state: "Completed"`. The pair now shares one `_RECRAFT_COMMON` dict, mirroring the krea pair.

**Adding it caught a real bug**, which is the argument for having done it deliberately rather than as a copy-paste. The new model needed its own `SIZE_TABLE_OVERRIDES` entry; without one `size_for()` fell back to the shared `SIZES` table and produced 1536x864 at Standard 16:9 — not a legal Recraft size. On any other gateway model that is a free rejection; on this family it is **billed and then refused**. Now pinned by `test_every_size_enum_model_owns_a_size_table`, which checks every enum model owns a table *and* that every ratio×tier it yields passes `validate_size`. The test was verified to fail when the override is removed rather than assumed to work.

All five Recraft tests were widened to loop over both models, on the principle that a quirk holding for one of an identical pair must hold for the other.

Labelling was the only real content decision. Elo 1198 against Utility's 1218 for the same money, so the dropdown tooltip and `price_note` both say plainly that V4.1 is **not** the upgrade: same price, same fixed sizes, lower score, and the reason to pick it is its art direction. Verified by launching the GUI and reading back the widget states — both models disable the seed controls and the tier dropdown identically.

**49/49 offline tests pass.** Next: `google/nano-banana-2-lite`. Note the seedless GUI path built for Recraft applies to it directly — setting `supports_seed=False` is the whole of that work.

## 2026-09-05 — Gateway model 7: `google/nano-banana-2-lite`

Billed as the risky one, and it was — but not for the reason the plan predicted. The brief was that this is the one family where the Draft/Standard/High dropdown maps onto a real price ladder (1K/2K/4K), and that the whole job was wiring the tier through to both the request and the estimate carefully enough that the cost readout could not quietly quote one number while the request sent another.

That is true of `nano-banana-2`. It turned out **not** to be true of Lite, and finding that out was the session.

### The conflict

Cloudflare's own model page declares `resolution` as an enum of `1K, 2K, 4K` — read directly, twice. But three independent sources say the Lite model renders 1K and nothing else: OpenRouter ("Outputs are generated at 1K resolution across 14 aspect ratios"), fal.ai ("Output images are generated at a fixed 1K"), and a pricing breakdown noting that Google publishes a 1K per-image rate for Lite and **no 2K or 4K rate at all**, unlike the models above it.

So the gateway schema accepts a value the model may not honour, priced at a rate nobody publishes. The rendering question is genuinely open; the pricing question is not, and that is what decided it. **This program's contract is that it can tell you what a batch costs before you run it.** Sending 2K on Lite would be a request whose price cannot be estimated from anything at all — worse than a smaller image, and exactly the kind of silent wrongness the "measure, do not assume" rule exists to prevent. Lite is pinned to 1K, the pin lives in one data structure, and unpinning it is a one-line change the moment real prices exist.

The per-resolution price machinery was built anyway, because `nano-banana-2` needs it and shipping it untested until the $151/1000 model arrives would be the wrong order to find a bug in. `_per_resolution()` recovers the tier from the pixel size and is tested against a full 1K/2K/4K ladder at nano-banana-2's real published prices. An unrecognised size falls back to the **dearest** price rather than the cheapest — if the estimate has to be wrong, it must not be wrong in the direction that surprises someone with a bill.

### The bug the brief predicted, and it was there

The brief said two GUI strings keyed on `size_style` had now been wrong for a second model twice, and to check them by launching the GUI rather than reading the code. Both were wrong again, in the same way, and launching the GUI is what showed it.

nano-banana speaks krea's exact size vocabulary — `aspect_ratio` plus a `resolution` word, no width/height field — so it fell straight into krea's branches. But Google **publishes** the pixel dimensions where Krea does not, so the `~1344 x 768 (~1.03 MP, estimated)` readout would have called a documented number a guess, and the disabled-tier reason would have said "locked to 1K" about a model whose API declares 2K and 4K and which this program pins by choice. Both are plausible-sounding lies of exactly the kind the Recraft session fixed one instance of.

The estimated-size readout is now keyed on a new `ModelSpec.sizes_published` rather than on the size vocabulary. That is the generalisable fix: **key a user-facing explanation on the fact it asserts, not on whatever field happens to correlate with it today.** No size vocabulary can answer "is this number published or invented?", so the flag asks it directly. Krea is the only model in the lineup where it is False. The disabled-tier reason now has three branches, and the nano-banana one says plainly that the pin is the program's decision.

### A latent bug found on the way

`_ratio_key_for` — the helper that recovers a ratio NAME from the pixel size everything upstream carries — was looking up `SIZES_KREA` specifically. Harmless while krea was the only caller. But nano-banana's nominal 16:9 is 1344x768 (1.750) against krea's estimated 1328x752 (1.766), so it would have been answering one model's request from another model's size table. Now matched against the program's own five ratios with a tolerance wide enough for the ~1.6% drift these nominal labels carry, and 1:1 still cannot collide with 3:2.

### The rest went as predicted

The seedless path Recraft built applied unchanged — `supports_seed=False` was genuinely the whole of that work, and it was verified rather than re-implemented: a seed passed in is dropped, `_finish` records None, the GUI disables all three controls. Both assertions were checked to **fail** when the flag is flipped, rather than assumed to work.

`output_format` is spelled `jpg` here and `jpeg` on flux-2-pro, which is precisely what `wire_output_format()` exists for. The wrinkle is that the default is **unknown** rather than merely non-neutral — neither Cloudflare nor Google publishes one, which is weaker ground than flux-2-pro's documented `jpeg`. Sent explicitly all the same, on the reasoning that an unknown default cannot be assumed neutral. That question has now paid off four times on this lineup. Worth noting too that this is the only family where the program asks for a format at all, and a requested format is a weaker claim than a declared one — so the magic-byte sniff matters more here, not less.

Response shape resolved from the docs at no cost and cross-checked against the sibling model's page: a presigned URL, `state: "Completed"`, reusing `json_url` unchanged. That is now three incompatible shapes across seven models at the identical `result.image` path.

`image_input` is a permanent skip and joined the banned-fields test. It is Lite's entire optional surface, so nothing else was left unexposed. The model has no content-filter lever, which is worth knowing before reaching for it on prompts that flux-2-pro exists to rescue.

**56/56 offline tests pass** (49 before): seven new, two extended. Next and last: `google/nano-banana-2`.

## 2026-09-05 — Gateway model 8: `google/nano-banana-2`. The lineup is COMPLETE.

The last model, and the one the phased order deliberately saved for last: highest quality (Elo 1320), highest price ($67/$101/$151 per 1000), and the only model in the program where the quality tier changes the bill.

It was also the cheapest of the eight to add, which was the whole point of building the per-resolution machinery during the Lite session rather than now. `NANO_BANANA_TIER_RESOLUTION` gained a three-line entry, `SIZE_TABLE_OVERRIDES` gained one line derived from it, and `has_tier_ladder()` started returning True on its own. `_per_resolution()` was already under test against this exact ladder at these exact prices.

### The tier mapping, and a good question from the user

Draft/Standard/High map onto 1K/2K/4K. The user's instinct was to give the model its own dropdown with a fourth "Ultra" rung, on the reasoning that Standard should mean something near 1024px and 1K sitting at Draft reads oddly. The pushback that landed: the tier names are a **program-wide vocabulary** meaning a quality intent rather than an absolute pixel promise — klein's Draft is 768x432, Recraft's Standard is 1344x768 — and a fourth option existing for one model in fourteen would be dead on every other one. The size readout always shows real pixels, so nothing is inferred from the word. Agreed and implemented that way. The oddness is real but it is the cheaper cost.

### The two unknown fields turned out not to be what they looked like

`google_search` and `image_search` were on the list as "research before exposing", and the obvious guess is that they are img2img-shaped like every other skip here. Only `image_search` is. Both are **Google Search grounding**: the model searches before generating, to ground the image in real-world fact.

The disqualifying fact is billing. Grounding is charged separately at **$14 per 1000 search queries** after 5000 free per month, and Google's docs are explicit that one prompt may trigger *several* billable queries. Through a pass-through gateway, against a monthly allowance the program cannot see, that is unpriceable by construction — it would make the cost estimate silently wrong by an unbounded amount on the most expensive model in the lineup, which is precisely the failure the whole gateway effort has been structured to avoid.

Recorded as a **cost** decision rather than an architectural one, with the rates stored alongside the field names. The img2img skips are permanent; this one is revisitable if the per-query charge ever becomes visible to the client.

### Two things fixed that were not on the list

**4K needed a per-model safe ceiling.** 5376x3072 is five times anything else in the lineup, and the shared 1024px `max_safe_dimension` would have fired the SD degradation warning on a model natively specified to 4K. Wrong, and actively harmful — a warning that cries wolf where it does not apply teaches users to ignore it where it does. Pinned by a test that also asserts the SD warning still fires.

**The cost-tier marker was pricing models at sizes they cannot serve.** The marker uses a fixed 1536x864 reference so it cannot flicker; that is not a nano-banana size, so it was landing on `_per_resolution`'s unknown-size fallback and quoting the dearest tier. Right answer, wrong route. No marker in the lineup changed, but relying on a fallback to be correct by accident is how the next model in a straddling band gets mislabelled, so override models are now marked at their own Standard size.

### The over-budget warning got a second band

The user asked directly whether the GUI is loud enough here, and it was not. Every paid model got the identical line — the same sentence at $15 and at $151, which is how a warning gets tuned out — and the $5 ceiling is the wrong reference for a model over the *tolerance*. The `$$$` band now leads with the **batch total** rather than the per-1000 rate, and names the image count. GUI, `cli estimate` and `cli dry-run` all updated; verified by launching the GUI and reading the widgets back, and by running both CLI paths.

**61/61 offline tests pass** (56 before). All eight gateway models ship. Remaining: the `guide.md` / `readme.md` / `promo.md` documentation pass with a sanity check, deferred to its own session by decision, then the exe build. Still blocked on the neuron allowance: the per-family black-image content check, and the flagged Advance Wars prompt at a fixed seed.

---

## Session (2026-09-05) — UI/UX sanity pass over the 13-model lineup

**Context:** the GUI was written for five Cloudflare-native models. Eight AI Gateway models were added afterwards and broke assumptions baked into the labels, tooltips and layout. This pass fixed the presentation; **no models or providers were added.** Phases 1-4 of [ui-sanity-pass-plan.md](ui-sanity-pass-plan.md) are complete; Phase 5 (the `guide.md` / `readme.md` / `promo.md` rewrite) was deliberately deferred to a fresh session, and that file is written to be picked up cold.

Tests: **49/49 → 73/73**, all offline. GUI launched and every model walked after each phase.

**Finding 1 — Pollinations silently clamps to ~0.59 MP.** The investigation started from the hypothesis that FLUX.1 schnell only supports 1:1; that is false, ratios are honoured exactly. The real bug is an area cap: 1536x864 was requested, 1024x576 delivered, and 1536x864 recorded in the sidecar. Full measurements and the fix in [findings.md](findings.md). A proposed auto-crop feature was dropped once the premise turned out not to hold.

**Finding 2 — a screen-bounds clamp inverts when the content is bigger than the screen.** The model tooltip had grown to 2958 characters (984px tall against 816px usable) and the positioning arithmetic pushed its top off-screen, so the last paragraphs were unreachable with nothing to indicate they existed. The deeper fault was **growth by accretion** — each new model appended its own paragraph — so per-model prose moved out of the tooltip into a label under the dropdown, which is bounded because it describes one model.

**Finding 3 — the Guidance box was never disabled at all.** Built as a local `g`, so no code could reach it; it stayed editable on the eight models that accept no guidance while the note two lines below said otherwise.

**Decision — cost bands replaced "over budget".** The old label read *"exceeds the $5.00 ceiling for this project"*: it described this project's internal budget policy, which a user has never heard of, and it was binary, so $5.01 and $151 got the identical sentence. Now FREE (Neurons) / LOW / MEDIUM / HIGH / EXTREME at $5 / $20 / $50, inclusive bounds. **This was written in five separate places** — Provider tab, Run tab log, two CLI commands, and the paid-generation confirmation dialog — each with its own wording; all now render `COST_BAND_LABELS`, with a test that scans the source so a sixth cannot appear. The marker gained a fourth level (`$$$$`), so `$$$` now means HIGH rather than "the most expensive".

**Decision — the tier dropdown is built per model.** `TIER_LABELS` was one hardcoded sentence per tier ("High — biggest; klein models only, and ~64% slower"), wrong or irrelevant for most of the lineup and actively dangerous on nano-banana-2, where it described a size while the control changed the price by up to 2.3x. `tier_description()` derives labels from the registry. Two things fell out of doing it properly: **klein also has a price lever** (it bills per tile, so its ladder is $0.57/$1.72/$2.29 — previously invisible), and **"Draft — cheapest" is a falsehood on flat-priced models**, where it pushed users toward fewer pixels for a saving that does not exist.

**Decision — model notes are written for a layperson.** All 15 were rewritten. They had been dev shorthand: they referenced the internal "$5/1000 ceiling", quoted raw Elo numbers, and said "per 1000" with no noun. Comparisons are now relative to things visible in the app. A test bans the specific dead vocabulary. **The neuron allowance is now front-loaded on all five native models** — previously the free models said "Cloudflare charges nothing" without saying why, and only klein-4B mentioned the daily allowance, so nothing explained why a paid model can cost nothing for the first few hundred images. This **reversed a rule from earlier the same session**: "neurons" had been banned as jargon, which was wrong — it is Cloudflare's own published term and the allowance cannot be explained without it.

**Decision — Generation Settings split into two groups**, and the negative-prompt group collapses on the 10 models that ignore it (431px of dead checkboxes otherwise). The group frame and an explanation stay visible; only the controls fold. This amends the session's own "never hide controls" rule: hiding a control the user might want reads as lost settings, but a whole feature the model *cannot use* is better stated once than shown as twenty dead checkboxes.

**Gateway access requirements were researched** (doc-derived, no credit available to spend) and are in [findings.md](findings.md). The short version: the program's endpoint and its omission of the `cf-aig-gateway-id` header are both correct; what was missing was any mention of the **prepaid credit prerequisite**, now surfaced beside the model dropdown rather than only in a note below the fold, and the **5% purchase fee**.

---

## Session 2026-09-09 — the single custom prompt override

**Feature.** A tickbox at the bottom of the Prompts tab's Files frame sends **one typed prompt** instead of the prompt file. Motivation was the user's, and it is the same argument the existing "Generate: first N" slider already makes, taken one step further: the slider avoids maintaining a second prompt file, this avoids maintaining one at all when the question is only "does this idea work?".

**The design decision that matters: it is MATERIALISED as a real single-line .txt, not threaded through the engine as a special case.** `prompt_file` is not merely an input — its path keys `find_batch()` for resume, its stem seeds `build_filename()`, and it is written into every sidecar as `source_file`. The obvious alternative, a sentinel path like `"(one-off)"`, was rejected on the spot: every one-off sharing an output folder would collide on one batch row and one filename, so image #2 would land via `unique_path` next to a job row whose line 1 held a *different* prompt. Writing a real file means resume, naming, batch identity and metadata all keep working **with zero engine changes**. `core/engine.py` was not touched at all.

`materialize_one_off()` writes to `<output_dir>/.oneoff/<stem>.txt` — inside the output folder rather than the system temp, for the same reason `.batchgen.db` lives there: a resume has to find the same path it ran under, and temp gets swept.

**Same prompt resumes, different prompts do not collide.** The path is disambiguated on **content**, not on existence: an identical prompt keeps its path (so re-running a one-off costs nothing), while a different prompt that sanitizes to the same stem gets `unique_path`. This is a real case, not a theoretical one — `sanitize_fragment` keeps words from *both* ends, so "a misty forest of tall pines at dawn" and "a misty forest of dark spruces at dawn" both stem to `misty_dawn`. The test uses that exact pair; an earlier draft used three prompts that stemmed differently and **passed even with the guard deleted**, which was caught by deliberately breaking the guard and checking the suite went red.

**A bug found by tracing rather than by hitting it.** `_set_limit()` persists `prompt_limit` as `None` whenever `n >= total`. A one-off pins total to 1, so that always holds — and it would have silently erased a cap the user had set on their real prompt file. Now guarded on the override flag.

**Persistence: the flag is in config.json, the TEXT is not.** `single_custom.txt` sits beside the program like `config.json` does. The box is free-form and the user may paste anything into it, so it does not belong wedged into a JSON string field — the user made this call and it is the right one. Saved on keystroke, **plus `<<Paste>>` and `<FocusOut>`** (a right-click paste fires no `KeyRelease`, which is exactly how a long prompt arrives) **plus a flush in `_on_close`** for text typed and never blurred.

**Both persist across restart, by decision.** Retyping the prompt is the chore the feature exists to remove. The earlier assumption — that the tick should reset to off each launch so the app never silently ignores a prompt file — was overruled: it is the user's switch to leave where they like, and the banner plus the greyed-out file row make the state impossible to miss.

**GUI rules followed.** The prompt-file entry and its button are **greyed out, never hidden** (a vanishing control reads as lost settings; hiding is for a feature the model cannot use). The banner states the **consequence** — "generating 1 image from the text below. Your prompt file is ignored." — not the mode's name, on the same reasoning that turned "$151 per 1000" into "this batch of 500 costs $75.50". A third banner state covers ticked-but-empty, which is cheaper than a dialog at Start.

**Everything downstream follows the override**, verified by launching the GUI rather than by reading the code: the preview (it is titled "exactly what will be sent" — leaving it listing file prompts would be the same shape of lie as a sidecar recording a size the provider never delivered), the character counter, the Generate slider, and the Provider tab's batch cost.

**CLI parity:** `--prompt "text"` in place of the prompt-file argument, which is now `nargs="?"`. Giving neither produces a message naming both ways of supplying a prompt.

**Verified live** on `poll-flux` (the Cloudflare free allowance was exhausted at the time): one real image, correct sidecar, a re-run resuming in 0s with no HTTP request, and a second distinct prompt creating its own batch. 80/80 offline tests pass, two of them new.

**Amended the same day, on user feedback — two GUI corrections.** The one-off text box is now **editable even while the override is off**. Disabling it was reflex rather than reasoning: a `tk.Text` does not visibly grey out the way a ttk widget does, so the disable had no visual signal at all and its only effect was a box that silently refused typing. Drafting the next idea before arming the override is a normal thing to want. And the banner **always renders text**, with a green "Disabled — using the selected prompt file" in the off state; an empty label left a hole in the layout that looked like a bug until the box was ticked, and stating the off case explicitly is what makes the on case read as a change rather than as noise. Four states: off (green), on (amber), on-but-empty (red), plus the prompt-file row's greying.

The general lesson, and it is the one already written down for disabled numeric controls: **a disabled empty box is indistinguishable from an unfilled one.** The same reasoning applies to a label reserved but left blank, and to a `tk.Text` disabled with no visual change to show for it.

---

## Session (2026-09-13) — the Helpers tab, and recipes.md becomes a runtime input

Shipped a 4th tab, **Helpers**: text links to four LLM assistant sites, then a copy-to-clipboard button per prompt block, everything parsed out of `recipes.md` at load. New `core/recipes.py` (parser, no Tk, offline-testable) and `gui/tabs/helpers.py`. 84/84 offline tests pass, four of them new.

**The idea started as "put the recipes behind buttons" and the real value turned out to be different from the stated one.** The pitch was saving alt-tabs. What the buttons actually remove is a class of *error*: copying a fenced block out of rendered markdown by hand means selecting it without clipping the fence or missing the last line, and a button cannot get that wrong. Worth noting because the weaker justification (convenience) would not on its own have earned a tab.

**No in-app AI, and the reason is stronger than the neuron cost.** The original plan was to run these prompts through Workers AI inside the program. Cut — but not mainly for quota. Every one of these prompts is a *judgement* task: "style only, no subject matter", "distil every element relevant to a visual image". Small instruct models fail those quietly, producing plausible-looking output that breaks the single rule that makes the recipe work, while spending the image allowance to do it. A feature that produces bad style presets and charges you for the privilege is worse than no feature.

**Finding — a marker matches intent; a shape matches accidents.** The first design parsed by shape: any bullet containing a URL became a link, and a fenced block was labelled by the nearest preceding heading (with a bold lead-in as a tiebreak, since "Turn writing into an image" holds three blocks under one heading). Both were wrong for the same reason. `recipes.md`'s "Recovering from a bad batch" section is already a bullet list, so a link added there later would have appeared in the GUI for no reason a user could see; and a heuristic with a tiebreak rule breaks the moment someone reformats a paragraph. Replaced with explicit `<links>` and `<recipe name="...">` markers. The parser now matches what the author *meant*, so unrelated edits to the document cannot trip it.

**The fences stay inside the `<recipe>` tag rather than being replaced by it.** Tempting to drop them — the tag alone would be easier to parse. But the fences are what make the block render as a copyable code box for someone reading `recipes.md` as a document, which is still its primary job. The tag adds a name the parser can trust; it does not take over the rendering. Unknown HTML tags render as nothing in a markdown viewer, so the document looks unchanged.

**Placeholders went from `[BRACKETED PHRASES]` to single tokens** (`YOUR_TEXT`, `DESCRIBE_THE_LOOK_YOU_WANT`) on user feedback, because a double-click selects one token and cannot select a bracketed phrase. Considered doing this as a copy-time transform to keep the brackets in the doc; rejected as convolution. Editing the document means the clipboard is byte-identical to the file, which is one fewer thing that can disagree.

**Captions are the one thing deliberately NOT parsed.** The prose around each block is explanatory paragraphs, not caption-shaped, so `CAPTIONS` is a small table keyed by recipe name with a blank fallback. A recipe added to the doc still gets a working button, just without a caption — so the drift risk is cosmetic and never touches the prompt text. A test asserts every captioned name still exists in the file, since a rename would otherwise silently drop its caption.

**Missing and unparseable are different states with opposite fixes**, so they say different things and the "Open recipes.md" button disables only for the first. A user editing this file in Notepad can now break the tab, so `load()` catches rather than raises: a broken document must degrade to an empty tab that explains itself, never to a program that will not start. An early draft of the header also reported "(0 links, 0 prompts)" in the unparseable case, which reads as a bland statistic where it should defer to the panel explaining the actual problem.

**Caught by looking rather than by reading: the link labels had dark rectangles behind them.** They sat in a bare `ttk.Frame`, which is `bg_base`, inside a LabelFrame, which is `bg_surface`. Invisible in the code, obvious in a screenshot — the standing rule about checking the GUI by launching it earned its place again.

**Links sit above the recipes**, matching the document, on the user's reasoning that it is the order of use: open the assistant first so it loads while you fetch the prompt. An earlier draft had them as a footnote at the bottom.

Not mentioned in `promo.md` by decision — a workflow convenience, not a headline feature.

---

## Style reference image — BUILT (2026-09-19)

Implemented [reference-image-plan.md](reference-image-plan.md) end to end: `core/models.py` capability fields, `core/reference.py` (the whole decision layer), the klein multipart path, the gateway base64 path, identity/resume, the Provider-tab GUI group, CLI parity and a `guide.md` section. Suite is **102/102 offline**, thirteen of them new. **No paid generation was run** — every check is synthetic Pillow images through mocked transports, per the standing rule.

**The plan was right about the measurements and wrong about three mechanics**, all three caught by tests rather than by reading. Written up in [findings.md](findings.md); the short version:

1. **Appending `None` to the filename hash is not backward compatible.** The parts are joined with a separator, so a trailing `None` appends an empty field and changes the digest — which would have renamed every image in every pre-existing batch, so each would have looked unfinished, resumed and regenerated. On a paid model that is a full re-bill from a filename change nobody asked for. The part is **omitted** rather than passed as `None`.
2. **The plan stopped at the filename and never mentioned `find_batch()`.** That is exactly half of the fix the style-suffix bug already taught this project, and CLAUDE.md's own rule is that fixing one gate leaves the symptom. The reference hash is now a `batches` column too — which needed the project's **first schema migration**, since `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists and every `.batchgen.db` on disk would have raised on the first query naming the new column. Verified against a hand-built legacy database: an old batch reads `''` and reattaches unchanged.
3. **"Follow the round-trip diff when the signals disagree" is wrong in one direction.** Right for JPEG'd pixel art; wrong for a smooth gradient, which survives the round trip at 0.004 (no detail to lose) while holding ~196,000 colours. The **colour count** carries the veto. There was also a unit bug in the first implementation — Pillow's `ImageStat` is 0–255 while the plan's thresholds are 0–1, making the cutoff ~25x too strict.

**Two things were found by LOOKING at the GUI rather than reading it**, which is what CLAUDE.md says to do for these strings. `autowrap()` measures the *container*, so the status label sharing a row with the 96px preview thumbnail was given a wraplength ~100px wider than its actual space and ran off the right edge — it now has its own full-width row. And three facts run together on one line read as a wall, so each is on its own line and `reserve_lines` went from 3 to 4.

**One hole the plan did not cover:** an unusable reference would only have raised inside a worker thread, *after* the user clicked through the paid-confirmation dialog. It is now prepared at the same pre-flight point that counts the prompt lines, with its own dialog — the fix for a bad reference is different from the fix for a bad prompt file.

The **flux-2-pro base64 path remains doc-derived and unconfirmed**, exactly as the plan flagged. Confirming it costs a paid generation, so it needs the user's explicit permission and a real prompt.

## Reference influence dropdown (2026-10-15)

User asked for a control over how strongly the reference applies, as a dropdown that slips "influenced by image 0" onto every prompt instead of typing it. Confirmed no model in the feature has a strength field, so the dropdown writes the sentence. Built in `core/reference.py` (`INFLUENCE_*`, `influence_phrase()`, `with_influence()`), `ModelSpec.reference_prompt_name`, the engine's `load_lines()`/`prepare()`, the Provider tab (new Influence row; the old constant `REFERENCE_PROMPT_HINT` became the model-aware `reference_hint()`, since "image 0" is klein-only), the Prompts tab preview and counter, and `--reference-influence` in the CLI. Three tests added (105/105).

Tested on klein-4b with the user's own prompt and sprite-sheet reference, 9 images of an approved 12: four levels were drafted, "subtle" proved indistinguishable from no sentence and was cut, leaving Off / Style / Strong. Results in findings.md. The preview refresh is called from the reference event handlers rather than from `refresh_reference()`, because that runs inside `recalculate()` and the preview calls back into `recalculate()` via the prompt-count slider.
