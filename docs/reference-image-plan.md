# Style reference image — implementation plan

**Status:** approved, unbuilt. Investigated and measured 2026-09-19; written for a fresh session to implement.

**Feature in one line:** one global reference image, applied to every prompt in the batch, on the four models that can accept a local file — a style lever the style-suffix text cannot reach.

This is a **deliberate partial reversal** of the "img2img fields are a permanent skip" ruling in CLAUDE.md and `docs/findings.md`. The reversal was approved by the user on 2026-09-19 after measurement showed the two premises behind that ruling were false for part of the lineup. Read [findings.md](findings.md) § "The img2img fields — PARTIALLY REVERSED" before starting; every number below comes from there.

## What was measured, and what it rules in and out

Four models can take a **local file**. Everything else in the lineup cannot, and that is settled by measurement rather than preference:

| Model | Band | Field | Encoding | Ships in this feature |
|---|---|---|---|---|
| `flux-2-klein-4b` | `$` (free daily) | `input_image_0..3` | multipart **binary** | **Yes — the primary target** |
| `flux-2-klein-9b` | `$$` | `input_image_0..3` | multipart **binary** | **Yes** |
| `nano-banana-2-lite` | `$$$` | `image_input[]` | **base64 data URI** (measured 200/Completed) | Yes |
| `nano-banana-2` | `$$$$` | `image_input[]` | base64 data URI (same family, same schema) | Yes |
| `flux-2-pro-preview` | `$$$` | `input_images[]` | `data:` base64 **documented, NOT measured** | Yes, but see caveat |
| krea Turbo / Medium | `$$` | `image_style_references[].url` | **https URL only — refuses base64** | **No — impossible** |
| recraft Utility / V4.1 | `$$$` | top-level `image` | uri | **No** |
| `p-image` | `$` | *no such field* | — | **No** |
| 3 SD models, both Pollinations | free | none | — | **No** |

**krea is the painful exclusion.** Its field is literally described as *"Reference images to drive the visual style (up to 10)"* with a per-image `strength` — the best-fitting field in the lineup. It is unreachable: a `data:` URI returns `Validation error at image_style_references[0].url: Must be an HTTP(S) URL`, and a real URL is genuinely fetched. Serving the user's file would require hosting it publicly (a tunnel or file host = new dependency, new credential, user's art published to a third party). **Cut by decision. Do not revisit without a hosting story the user has asked for.**

**flux-2-pro caveat:** its base64 support is documented by Cloudflare ("each entry is an HTTPS URL or a `data:image/...;base64,...` URI", max 8) but was **not** confirmed with a real image, because confirming costs a paid generation. Ship it, but the first real use should be watched. Better: confirm it with the user's permission and a real prompt (see the rule below).

**`controls.image` does not exist on recraft** — the schema's `controls` holds only `colors` and `background_color`. The old note was wrong about the shape; the conclusion (not sent) is unchanged.

## The hard numbers

Measured on `flux-2-klein-4b` against the live API, and these contradict the vendor docs:

- **There is NO 512x512 maximum.** Cloudflare's changelog and blog both say *"all input images must be smaller than 512x512"*. False: 640x480, 1024x1024, 2048x2048 and **4096x4096 all returned HTTP 200**.
- **There IS an undocumented 64px minimum, per side.** Bisected exactly: 63x63 rejected, **64x64 accepted**; 56/60/62 rejected. **`64x48` is rejected** — the floor applies to *each* dimension, not the total or longest edge. Third-party FLUX.2 docs independently state "resolutions from 64x64", corroborating it.
- Rejection is HTTP 400, `AiError: Invalid input`, code **8001** — a generic message naming neither the field nor the size. **The program must validate client-side** or the user gets an unexplainable failure.
- **No square requirement.** 320x180 and 512x64 accepted.
- **PNG, JPEG and WebP all accepted**, as ordinary multipart parts with filename + content-type.
- **Reference size does not affect generation latency.** At a fixed 1536x864 output: 512px ref 4.7s, 1024px 4.6s, 2048px 4.2s, 4096px 4.9s — flat within noise. Oversized refs cost **upload bandwidth only** (2.5 / 7.6 / 25.5 / 89.5 KB as PNG).

### The recommended size

**No VENDOR publishes one** — checked across Cloudflare, BFL, fal.ai, Replicate and the FLUX.2 model cards. But the **community has**, and it is traceable to code:

**`PREFERED_KONTEXT_RESOLUTIONS`** (ComfyUI `nodes_flux.py`, adopted by InvokeAI and others) — 17 sizes whose properties, analysed, give the whole spec:

| Property | Value |
|---|---|
| Megapixels | **1.035–1.062 MP** — every entry within 2.8% of ~1.05 MP |
| Divisibility | **all multiples of 16** |
| Aspect range | **exactly 3:7 to 7:3** (0.429–2.333) |

That independently confirms the ~1 MP target **and supplies the aspect-ratio guard**. Corroborated by the separately-repeated "Flux supports aspect ratios from 3:7 to 7:3". Caveat: this is FLUX.1 **Kontext** guidance applied to FLUX.2 / nano-banana — same family, same reference-conditioning mechanism, and the ~1 MP figure independently matches the ComfyUI FLUX.2 workflow default, but it is **community-derived and cross-family**. A good default, not a law; do not present it as official.

Supporting evidence for the same target:

- **~1 MP is the ecosystem convention** — the standard ComfyUI FLUX.2 reference workflow scales inputs to 1 megapixel via `ImageScaleToTotalPixels`.
- **Above ~4000px is measurably bad** — `black-forest-labs/flux2` issue #42 reports editing with >4000px inputs returns output "heavily blurred or degrade[s] into noise-like artifacts", unfixed by raising steps. Open, no maintainer reply. **Accepted ≠ recommended**, the same lesson the SDXL-Lightning guidance probe taught.
- Some providers **bill input megapixels** (fal: "1 MP input + 1 MP output"). Not Cloudflare's klein, so it does not affect this program's cost — but it shows inputs are real pixel data, not thumbnails.

**Target: ~1 MP. Floor: 64px per side. Ceiling: 2048px per side. Aspect window: 3:7 to 7:3.** Never send 4096 even though it is accepted.

**What ~1 MP means per ratio** — computed, multiples of 16. Note 16:9 is **1360x768, not 1280x720**: the intuitive number is 0.92 MP and wastes ~12% of the budget, the same trap the `SIZES` tile-packing table exists to avoid.

| Ratio | ~1 MP target |
|---|---|
| 1:1 | **1024x1024** |
| 16:9 | **1360x768** |
| 4:3 | 1184x880 |
| 3:2 | 1248x832 |
| 9:16 | 768x1360 |

## The resize ladder

One function, `prepare_reference()`, owns this. It writes a **temporary copy** and never touches the user's file.

```
0. REJECT outright if ratio is outside 3:7 .. 7:3      (see below -- do not silently fix)
1. if either side < 64:       UPSCALE by INTEGER factor toward ~1 MP   -> NEAREST
2. elif pixels > ~1.05 MP:    DOWNSCALE to ~1 MP, cap 2048/side        -> LANCZOS
3. else:                      leave alone, copy as-is
```

**Integer upscale, aiming at the ~1 MP ballpark.** For a 16x16 sprite the candidates are 32x (512x512) and 64x (1024x1024); pick the largest integer factor that does not overshoot ~1.05 MP. This keeps pixel edges exact — a fractional scale reintroduces precisely the blur NEAREST was chosen to avoid. Where the integer factor cannot land near 1 MP (e.g. a 300x300 input: 3x = 810x810, 4x = 1.44 MP overshoots), take the largest non-overshooting factor and leave it; do **not** follow with a fractional correction.

**The resampler choice is load-bearing and must be pixel-art aware.**

- **Upscaling defaults to NEAREST** (overridable — see the resampler control in the GUI section). A sprite is upscaled because it is *below* the floor, which means it is tiny, which means it is almost certainly pixel art. Smooth resampling blurs the hard pixel edges that are the entire style being referenced — it hands the model a mush of the thing the user wanted. The project already knows this: CLAUDE.md records the 72 xBRZ-upscaled sprites.
- **The aspect ratio is NEVER altered.** No padding, no stretching, no letterboxing — an integer upscale preserves the ratio for free, and anything outside the 3:7–7:3 window is rejected at step 0 rather than reshaped. This keeps the two guards from fighting: the ratio check owns shape, the resize owns size.
- **Downscaling is LANCZOS**, the normal high-quality path, since anything over 1 MP is a photo, render or large artwork.
- **Never upscale past ~1.05 MP**, and clamp before checking so the branches cannot fight.

A 16x16 sprite therefore becomes a crisp 1024x1024 NEAREST upscale (64x) — legal, ~1 MP, and still recognisably pixel art.

### The aspect-ratio guard — reject, do not "fix"

Anything outside **3:7 – 7:3** is refused with an explanation rather than corrected. Checked against real sprite shapes:

| Input | Ratio | Verdict |
|---|---|---|
| 16x16 / 32x32 / 64x64 sprite | 1.00 | OK |
| 16x32, 32x48 character | 0.50 / 0.67 | OK |
| **256x256 sprite SHEET** | 1.00 | **OK** |
| 128x32 four-frame strip | 4.0 | **Reject** |
| 256x32 eight-frame strip | 8.0 | **Reject** |
| 384x32 twelve-frame strip | 12.0 | **Reject** |

**Single sprites and square-ish sheets pass; horizontal animation strips fail** — and a strip is exactly what a user might plausibly drag in. Neither automatic fix is acceptable: stretching distorts every frame, and padding a 12:1 strip to 7:3 wastes most of the canvas and shrinks the sprite content toward illegibility. So **reject with the remedy stated**: crop a single frame, or tile the strip into a grid. A grid is also the better style reference — a row of near-identical frames teaches the model less than a varied square sheet.

The message must name the actual numbers ("384x32 is 12:1; the widest usable is about 7:3"), never just "unsupported aspect ratio".

## Architecture

### Provider layer

The interface is `prompt + size -> image bytes` and stays essentially that; the reference is an optional extra threaded through, not a new abstraction.

- **klein (multipart):** append one more form field to the existing `files=` dict in [cloudflare.py:232-244](../core/providers/cloudflare.py#L232-L244) — `input_image_0: (filename, bytes, content_type)`. This is the whole change for the primary target. Verified working by curl example and by direct measurement.
- **gateway base64 models:** `_gateway_payload()` gains a branch keyed on a new `ModelSpec` field (below), emitting `image_input: ["data:image/png;base64,..."]` for nano-banana or `input_images: [...]` for flux-2-pro.
- **Only ONE image is ever sent**, always at index 0. No multi-reference, no per-image strength. That is a scope decision, not a limitation of the API — multi-image and weights are single-image *editing* features, and this is a batch style lever.

### `core/models.py` — the single source of truth

Nothing about a model's reference capability may be written anywhere else. Add to `ModelSpec`:

- `reference_field: str | None` — `"input_image_0"`, `"image_input"`, `"input_images"`, or `None`. **`None` is the gate for the whole feature** on that model.
- `reference_encoding: str | None` — `"multipart"` or `"base64"`.
- `reference_min_dimension: int = 64` and `reference_max_dimension: int = 2048` — per-model, following the precedent set by `max_safe_dimension` (CLAUDE.md: *"a model's safe-size ceiling is per-model"*).

A helper `supports_reference_image(key) -> bool` keeps every GUI/CLI/engine check derived rather than hardcoded, exactly as `cost_band()` does for pricing.

### Image identity — the part that must not be got wrong

**The reference image is image-affecting, so it enters the filename hash.** `image_hash_parts()` in [prompts.py:305-340](../core/prompts.py#L305-L340) gains one element.

**It must be a content hash of the file BYTES, never the path.** Swapping a different sprite in under the same filename would otherwise resume the old batch and generate nothing — the identical failure shape as the style-suffix bug already fixed once. Hash the *prepared* bytes (post-resize), since that is what is actually sent.

Append it **at the end** of the parts list, and pass `None` when no reference is used, so every existing batch keeps its current filenames and resume still works across the upgrade.

`core/engine.py` should need no new code path — the reference is prepared once before the run and passed down, the way the style suffix is. **Do not add a reference-specific branch to the engine**, per the precedent set by the one-off prompt override.

### Config and persistence

- Path goes in `config.json` (a path is a short, well-behaved string — unlike the one-off prompt text, which needed its own file).
- Persist the **enabled flag and the path** separately, so unticking does not lose the selection.
- Persist the **resampler mode** (`auto` / `nearest` / `lanczos`). Default `auto`.
- **Validate on load**: a path that no longer exists must degrade to a clear "file missing" state, never a crash or a silent skip.

## GUI — a new Provider tab section

A **"Style reference"** group, following the negative-prompt group's established pattern:

- **Browse button + path entry + Clear.** Right-click context menu, per house standard.
- **A small preview thumbnail** — the user must see *which* image is armed. This is the cheapest possible guard against "wrong sprite for 200 images".
- **A live readout of what will actually be sent**: `32x32 → upscaled to 1024x1024 (nearest)`, or `3000x2000 → downscaled to 1224x816`. State the transformation, not just the file, because the transformation is the surprising part.
- **Enabled per-model, and when disabled the reason stays on screen.** CLAUDE.md's rule: *"Hiding a control the user might want reads as the app losing settings; hiding a whole feature the model CANNOT USE is honest"* — and *"a disabled control still has to say why it is disabled"*. Say which models support it: *"Not available on this model — use FLUX.2 klein, nano-banana or flux-2-pro."*
- **Warn on the 64px floor before the run**, with the fix stated: the program will upscale automatically, but the user should know their 16x16 sprite is being scaled to 1024.
- Follow `sticky_height=False` on any label that re-renders on model selection.
- **Check it by launching the GUI, not by reading the code** — CLAUDE.md names this explicitly for per-model explanatory strings, which have now been wrong twice.

### The status label — four states, and it always says something

Modelled directly on the one-off prompt banner, which established the pattern and the reason for it (CLAUDE.md: *"the banner always says something… stating the off case is what makes the on case read as a change rather than as noise"*). The four `*.TLabel` styles already exist in `gui/theme.py` — `success` / `warning` / `danger` / `info`.

**It must state the CONSEQUENCE, not the verdict.** "Aspect ratio mismatch" is a verdict; "your reference is 1:1 but you are generating 16:9 — expect the composition to be re-framed" is a consequence. Same rule that renamed the Overwrite checkbox.

| State | Style | Says |
|---|---|---|
| No file selected | `info` / muted | *"No reference image — the style suffix alone drives the look."* |
| **All good** | `success` | *"1024x1024 PNG. Sent as-is — already the right size and close to your 1:1 output."* |
| Will be resized | `info` | *"32x32 → upscaled 32x to 1024x1024 (nearest, pixel-art safe). Sent at 1024x1024."* |
| Ratio differs from output | `warning` | *"Reference is 1:1, output is 16:9 — the model will re-frame the composition. Style still transfers."* |
| Outside 3:7–7:3 | `danger` | *"384x32 is 12:1 — too wide to use. Crop one frame, or tile the strip into a grid."* |
| Missing / unreadable | `danger` | *"File not found"* / *"Not a readable image"* — different text, different fixes. |

**Ratio mismatch is a WARNING, never a rejection.** A 1:1 sprite reference for a 16:9 batch is a perfectly reasonable thing to want — the reference carries *style*, and the output ratio carries *composition*. Only the 3:7–7:3 window is a hard refusal, because that is about the model being unable to use the image at all. Do not conflate the two.

Use a tolerance of roughly ±10% before calling ratios "close enough", so 1024x1024 against a 1:1 output reads as OK rather than pedantically flagging rounding.

Every one of these is computed on selection and on model/ratio change — the label re-renders, so `sticky_height=False`.

### The resampler control — three states, not a checkbox

The user asked for a checkbox (integer/nearest vs fractional/lanczos). **Make it a three-state dropdown — `Auto` / `Pixel art (nearest)` / `Photo (lanczos)` — defaulting to `Auto`,** because auto-detection is measured to be reliable and a checkbox would make every user answer a question the program can usually answer itself.

Measured 2026-09-19 on synthetic cases, and the separation is wide:

| Input | Distinct colours | Half-scale nearest round-trip diff |
|---|---|---|
| 32x32 pixel art | **4** | **0.000** |
| Pixel art upscaled 16x | **4** | **0.000** |
| Pixel art saved as JPEG q85 | 22 | 0.041 |
| 512x512 photo gradient | **97,537** | **0.529** |

Two signals, both cheap: **distinct colour count** and whether the image **survives a nearest half-downscale/upscale round trip unchanged** (true only when the image is built from uniform blocks). Pixel art scores 4 colours / 0.000 diff; a photo scores ~97k / 0.529. Even pixel art mangled through JPEG stays clearly on the pixel-art side, which is the case that would otherwise break naive detection.

Suggested thresholds, to be re-checked against real files: colours < 256 **or** round-trip diff < 0.10 → pixel art. Prefer over-detecting photos as photos: mis-applying LANCZOS to a sprite is the visible failure, so when the two signals disagree, follow the round-trip diff.

**The manual options exist because auto-detection can be wrong and the user knows their file.** Keep them; just do not make them mandatory.

**The status label must state which resampler was used and why**, e.g. *"detected pixel art — upscaled with nearest"*. Without that, `Auto` is a black box and the user cannot tell whether to override it. When the user picks manually, say that instead: *"nearest (your choice)"*.

Note the resampler choice **does not enter the filename hash directly** — it changes the prepared bytes, and the hash is taken over those bytes, so it is covered automatically. Do not add it as a separate hash part.

### Prompt integration

klein can address references **by index in the prompt text** — Cloudflare's own example: *"take the subject of image 1 and style it like image 0"*. With one image it is always `image 0`.

Worth surfacing as a hint near the control, because it is genuinely useful and completely undiscoverable. It pairs with style presets exactly as the user intended: the preset carries the words, the reference carries the look.

## CLI parity

`--reference-image PATH` and `--reference-resample {auto,nearest,lanczos}`, matching the `--prompt` precedent. `cli dry-run` must show the prepared size, the chosen resampler and the transformation, since dry-run is where a user checks before paying. A ratio outside the window must fail there too, with the same message the GUI shows.

## Tests

- **Narrow `test_reference_image_fields_are_never_sent`, do NOT delete it.** It must keep asserting the banned fields on the models that cannot serve them — krea, recraft, p-image — or it silently stops guarding them. Rename to reflect the narrower promise.
- New: one image is sent at index 0 and never more than one.
- New: the 64px floor is enforced client-side per dimension (64x48 must be rejected/corrected before sending, not sent).
- New: upscale uses NEAREST, downscale uses LANCZOS.
- New: the ratio guard rejects outside 3:7–7:3 and accepts at the exact endpoints (672x1568 and 1568x672 must PASS — off-by-one here silently refuses legal input).
- New: pixel-art auto-detection classifies a 4-colour block image as pixel art and a smooth gradient as photo; a manual override always wins over `auto`.
- New: ratio mismatch against the output ratio is a WARNING state, never a refusal.
- New: the hash changes when the reference bytes change, and is **stable across path changes with identical bytes**.
- New: hash parts are unchanged when no reference is set (backward-compatible resume).
- Existing suite is 84/84 offline — keep it offline; use synthetic Pillow images, no network.

## guide.md

A short section stating: what it does, which models support it, the 64px floor and automatic upscale, the ~1 MP target, that PNG/JPEG/WebP all work, that no square or specific ratio is required, and that pixel art is upscaled with nearest-neighbour to preserve hard edges. Plus the `image 0` prompt-reference tip.

Keep it plain — this ships to laypeople.

## Do not do

- **Do not add krea, recraft or p-image.** Measured impossible (or absent), not merely awkward.
- **Do not add multi-image, per-image strength, or moodboards.** One global reference, by decision.
- **Do not add a hosting/tunnel/upload service.** This was the specific idea considered and cut.
- **Do not send 4096px references** even though the API accepts them.
- **Do not put the reference path in the filename** — only the content hash.
- **Do not run a paid generation to test any of this** without explicit per-test permission and a user-supplied prompt. See the rule now in CLAUDE.md. klein is on the free daily neuron allowance and is the correct place to test.

## Suggested order

1. `core/models.py` capability fields + `supports_reference_image()`.
2. `prepare_reference()` — ratio guard, resize ladder, pixel-art detection + tests (pure Pillow, offline, no API). **The whole decision layer lives here, not in the GUI**, so the CLI and the status label consume the same verdict rather than each computing their own. Have it return a small result object (prepared bytes, final size, transformation description, resampler used, warning state) — the label and `dry-run` then just render it.
3. klein multipart path — the primary target, cheapest to verify on the free allowance.
4. Hash integration + resume tests.
5. GUI section — status label and resampler dropdown.
6. Gateway base64 path (nano-banana, flux-2-pro).
7. CLI, guide.md, narrowed banned-fields test.

Steps 1–4 deliver the entire motivating use case on a `$`-band model with a mostly-free daily allowance. Everything after is breadth.
