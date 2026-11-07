# Preset naming scheme and roster

Agreed 2026-09-03, before any preset content was written. This file is the **contract the content is written against**: it fixes the naming scheme, the group list, the full roster of built-in style presets and negative layers, and the rules every preset body must obey. Deciding categories after writing forty presets means renaming forty presets, which is why this exists as its own gate.

The measured facts these rules rest on live in [findings.md](findings.md); the preset system's shape (flat strings, no metadata, stackable negative layers) was settled in `preset-and-docs-plan.md` and is not relitigated here.

---

## The naming scheme

Every built-in style preset is named:

```
NN GROUP - NAME
```

- **`NN`** — a two-digit number code. Its only job is **sort order**: the most versatile, most reachable-for presets get low numbers and land near the top of the dropdown; specialised ones sink. It is not a rating of quality, it is a rating of *how often you'd reach for it blind*.
- **`GROUP`** — the family. All entries sharing a number share a group, and vice versa. Upper case.
- **`NAME`** — what the preset actually is.

Separator is space-hyphen-space. `NN GROUP` is written in Title Case — e.g. `01 Main - Digital Art` — matching the rest of the dropdown rather than shouting in upper case; the structure (number, group, name) is still visible at a glance in a list of forty-plus.

> **Superseded 2026-09-03:** the roster originally shipped as `NN GROUP - NAME` in full upper case (e.g. `01 MAIN - DIGITAL ART`). Renamed to Title Case because all-caps read as shouting for no reason — the numbering alone carries the sort-order structure. `load_config()` migrates a returning user's saved config and `last_preset` from the old names automatically.

### Why two digits

The dropdown is ordered by plain `sorted()` on the preset names — see `_preset_names()` in [prompts.py](../gui/tabs/prompts.py). That is the entire ordering mechanism; there is no separate sort key, so **the name is the sort order**. A single digit sorts correctly only while there are nine or fewer groups. At ten, `10 X` sorts between `01 X` and `02 X` and the scheme silently breaks. Two digits costs one character and never breaks, so the roster ships as `00`…`09` with room to grow.

### Why a number at all, rather than just letters

Alphabetical group names would sort `ARTIST, ASSET, BEAUTY, COOL, GAMES, MAIN, PHOTO, SPECIAL, STYLE` — alphabetical order has nothing to do with usefulness, and the generalists a new user wants would be scattered through the middle. The number decouples **sort position** from **group name**, so groups can be renamed or reordered later without either fighting the other.

**The order in this document is the official order.** The built-in roster is not alphabetised within its groups; it is arranged deliberately, and the numbering exists to preserve that arrangement through a plain sort.

### User presets sort above the built-ins

The built-ins are the official set and occupy `00`–`09`. **A user's own presets belong at the top of the list, above all of them**, marked with a leading asterisk:

```
*MY THING
*03 STYLE - RETRO TWEAKED
```

`*` is ASCII 42 and digits start at 48, so a plain `sorted()` already places asterisked names above `00 NONE - BLANK`. The convention costs nothing and works today.

**Proposed, needs a decision before anyone writes code:** make this a mechanism rather than a convention. As it stands a user who saves without the asterisk lands wherever their name falls alphabetically — quite possibly buried between two built-in groups, which is the one outcome the scheme exists to prevent. Two small changes fix it:

1. `_preset_names()` partitions on membership in `BUILTIN_PRESETS` and returns non-built-ins first, so a user preset is on top regardless of what it is called. Roughly three lines.
2. The Save-As-Preset dialog pre-fills the entry with `*` (or with the current preset's prefix when saving a tweak of a built-in, e.g. `*03 STYLE - `), so the asterisk is the visible cue for a rule that is already true underneath.

Doing both makes "your presets are at the top" a fact rather than a hope. Neither is required for the content in this document to ship.

### The scheme is self-teaching

A user who opens the dropdown sees forty-five names that all look the same, and the shape is obvious without being explained: number, group, name. The intended effect is that a user saving their own preset follows the pattern because that is what everything else looks like — not because a rule told them to. The Save-As prefill above is what turns "obvious" into "already done for you".

One line of hint text beside the preset controls would reinforce it further: *"Built-ins are named `NN GROUP - NAME` so the list stays sorted. Yours go on top."* Also proposed rather than built.

### Rules for the numbers

- **Nothing is enforced in code.** A user preset named `zzz my thing` works fine. The scheme is a convention the built-ins demonstrate, not a validator.
- **`00` is reserved** for `00 NONE - BLANK`, the empty style suffix. It sorts first among the built-ins, which is where "no style" belongs.
- **`10`+ is free** for a user who wants a whole group of their own rather than an asterisk.

---

## The groups

| NN | Group | What lives here |
|---|---|---|
| `00` | NONE | The blank suffix. One entry. |
| `01` | MAIN | The versatile generalists. Reach for one of these when you have no strong opinion. Every entry is unique to this group. |
| `02` | PHOTO | Photographic treatments, split by what the camera is doing. |
| `03` | STYLE | Art media and rendering styles — the "what is this drawn with" group. |
| `04` | SPECIAL | Distinctive visual effects and treatments. Strong flavour, narrower use. |
| `05` | ASSET | Presets whose job is producing a *usable file* — sprites, stickers, product shots. Framing and background are part of the style here, on purpose. |
| `06` | COOL | Concept-forging presets. These take an arbitrary subject and push it hard toward a specific fantasy. |
| `07` | BEAUTY | Portrait, glamour and macro-beauty treatments. |
| `08` | GAMES | Styles that reproduce a specific game's look, including its camera and rendering conventions. |
| `09` | ARTIST | Named-artist style references. |

### `01 MAIN` contains no duplicates

An earlier draft had `01 MAIN - PHOTO PRO` alongside `02 PHOTO - PROFESSIONAL`. **Dropped.** The same preset under two names makes a user stop and wonder how they differ, and the answer "they don't" is the worst possible answer in a dropdown. MAIN therefore means *the versatile generalists that live nowhere else*, and anything with a natural home in a specific group lives only there.

### `06 COOL` and `07 BEAUTY` assume a subject, deliberately

Most presets here are style-only in the strict sense. `06 COOL` and `07 BEAUTY` are not: `06 COOL - COMBAT ROBOT` will turn whatever you prompt into a mecha, and `07 BEAUTY - PRETTY EYES` frames an extreme close-up of an eye.

**This is a batch-tool feature rather than a compromise.** A batch run usually has one idea behind it. A preset that does the heavy lifting of *how this is framed and rendered* lets the prompt file carry only the varying part — a colour, a vehicle type, an environment, a mood word — and every image in the run comes back consistent. The group name is the warning label: a user who picks something from `06` or `07` for an unrelated batch has been told what kind of thing it is.

The strict style-only rule still binds every other group. See rule 3 below.

---

## Rules every preset body must obey

1. **300–500 characters.** This is the working range for the whole roster, tighter than the 100–1000 the earlier plan allowed. It sits deliberately *above* SD's ~300-character budget and far below FLUX's ~2000: the front of the preset is what SD sees, the rest is what klein gets. Presets shorter than 300 are fine when the style genuinely needs no more; **nothing is padded to hit a number.**
2. **Front-load the load-bearing clause.** The first ~300 characters must be a complete, recognisable style on their own, because on SD that is all that arrives. Everything after is spice in descending order. CLIP also weights earlier tokens more heavily *within* the limit, so this is a quality lever, not only a truncation defence.
3. **Style only — no subject matter.** A style block containing "ancient ruins" puts ruins in every image of the batch. This is the failure mode most likely to slip past a reading and only show up in a hundred generated files. **Exception:** `06 COOL` and `07 BEAUTY`, where the subject framing *is* the product — and only within those groups.
4. **No attention-weighting syntax.** `(term:1.2)`, `((term))`, `[term]` and `::` are A1111/ComfyUI conventions. **The Cloudflare and Pollinations APIs do not parse them** — the parentheses and numbers are encoded as literal text, wasting tokens and mildly corrupting the term. The source material uses these heavily; they are stripped.
5. **No embedding names or tag-set conventions.** `verybadimagenegative_v1.3`, `ng_deepnegative_v1_75t`, `DeepNegative` and `fastnegative-xl` are textual-inversion *filenames* that only do anything if that embedding is installed locally. `score_6`, `source_pony` and `source_furry` are Pony Diffusion tag conventions. On this lineup all of them are inert noise.
6. **Phrase every preset in POSITIVES.** Say what the image should have, never what it should lack. "no vignette", "nothing touching the frame edge" and "no focal point" all put their own nouns in front of the model, which is the opposite of the intent — that is what the negative-prompt layers are for. Added 2026-09-14, when the first draft of the `05 ASSET` structural presets was written in negatives throughout.
7. **Never bake an aspect ratio or an orientation into a preset.** "wide landscape composition" and "vertical portrait composition" fight the size control, which is where the user actually picks the ratio — a preset that assumes 16:9 is wrong the moment someone runs it at 1:1. Same for reserving empty space for text: several models render text perfectly well, and the user can ask for it in the prompt. Added 2026-09-14 for the same draft.
8. **Artist names are kept.** They are a legitimate and effective SD prompting technique, and are generally used several at a time, which blends the references past the point of reproducing any one artist's work. `09 ARTIST` is built entirely on this. The one place they are *removed* is `07 BEAUTY`, purely to buy back length — those entries were 700–1250 characters and had to lose something.

---

## Style preset roster

Sorted exactly as it will appear in the dropdown.

| Name | Source | Notes |
|---|---|---|
| `00 None - Blank` | new | Empty string. |
| `01 Main - Digital Art` | rcg `DIGIART` | |
| `01 Main - Digital Painting` | original program preset (`Painterly`) | Promoted from a seeded user preset to an official built-in 2026-09-03. |
| `01 Main - Digital Comic` | original program preset (`Comic`) | Promoted from a seeded user preset to an official built-in 2026-09-03. |
| `01 Main - Digital Anime 90s` | new | Added 2026-09-03 — cel-animation, painted-background, VHS-era OVA look. |
| `01 Main - 3D High Poly` | rcg `3D` | |
| `01 Main - 3D Low Poly` | new | Counterpart to the above; faceted, flat-shaded, game-asset-era 3D. |
| `01 Main - Frazetta Oil Paint` | rcg `FRANKZ` | |
| `02 Photo - A - Intentional Pro` | rewritten 2026-09-14 | Was `02 Photo - Professional`. Rewritten from a studio-bound description to a *skill level* that works in any setting, at any hour, on any subject. |
| `02 Photo - B - Candid Amateur` | rewritten 2026-09-14 | Rewritten for the same reason — the old body assumed an indoor phone snap. |
| `02 Photo - C - Soft Feel` | new 2026-09-14 | Mood dial, step 1. Gentle, cozy, low contrast. |
| `02 Photo - D - Hard Feel` | new 2026-09-14 | Mood dial, step 2. Decisive contrast, defined shadows. |
| `02 Photo - E - Cinematic` | new 2026-09-14 | Mood dial, step 3. The graded-film look. |
| `02 Photo - F - Extreme` | new 2026-09-14 | Mood dial, step 4. The deliberate "too much" option. |
| `02 Photo - G - Glossy-Shiny` | new 2026-09-14 | Surface aesthetic. Paired opposite of `H`. |
| `02 Photo - H - Gritty-Dirty` | new 2026-09-14 | *Soiled* — grime and dust. Distinct from `I`, which is *damaged*. |
| `02 Photo - I - Grunge-Rough` | new 2026-09-14 | *Damaged* — chipped, corroded, abraded. |
| `02 Photo - J - Dystopian-Bleak` | new 2026-09-14 | World aesthetic. Paired opposite of `K`. |
| `02 Photo - K - Utopian-Hightech` | new 2026-09-14 | |
| `02 Photo - L - Dreamy-Surreal` | new 2026-09-14 | |
| `02 Photo - M - Noir-Gothic` | new 2026-09-14 | |
| `02 Photo - N - Horror-Terror` | new 2026-09-14 | Strictly a *mood* — atmosphere and light only, no gore nouns, per rule 3. |
| `02 Photo - O - Nuclear-Fire` | new 2026-09-14 | |
| `02 Photo - P - Long Exposure` | new 2026-09-14 | |
| `02 Photo - Q - Rad Fisheye` | rcg lens line 1 | Expanded from a bare lens spec into a real style. Body unchanged; re-lettered only. |
| `02 Photo - R - Macro Closeup` | rcg lens line 4 | As above. |
| `02 Photo - S - Tilt Shift` | new | Miniature-faking; the one photo style with a strong signature look. |
| `03 Style - Sketch` | rcg `SKETCH` | |
| `03 Style - Drawing` | rcg `DRAWING` | |
| `03 Style - Graphite Watercolor` | rcg `GRAPHITEWATERCOLOR` | |
| `03 Style - Retro` | rcg `RETRO` | Retro-futurist core kept; "gooey mess / strange texture / pop culture reference" cut as vague-to-harmful. |
| `03 Style - Vector` | rcg `VECTOR` | |
| `03 Style - Popart` | rcg `POPART` | Trimmed; the source repeats one instruction ~6 ways across 28 terms. |
| `03 Style - Pixel Front View` | rcg | |
| `03 Style - Pixel Side View` | rcg | |
| `04 Special - Ghostly` | rcg `GHOSTLY` | |
| `04 Special - Whitespace` | rcg `WHITESPACE` | |
| `04 Special - Splash` | rcg `SPLASH` | |
| `04 Special - Glitch` | rcg `GLITCH` | The img2img workflow note in the source is dropped; the program has no img2img. |
| `05 Asset - Premium Product Shot` | rcg `MIN` | `MAX` cut — it is `MIN` with every instruction restated in synonyms. |
| `05 Asset - Sticker` | rcg `STICKER` | |
| `05 Asset - Silhouette` | new 2026-09-14 | Structure-only. See the note below. |
| `05 Asset - Seamless Texture` | new 2026-09-14 | Structure-only. |
| `05 Asset - App Icon` | new 2026-09-14 | Structure-only. Deliberately says nothing about margins or the frame edge — it should fill the canvas. |
| `05 Asset - Promotional Cover` | new 2026-09-14 | Opens with its own name, then the *feel*, the way `Premium Product Shot` does. |
| `05 Asset - Advertisement Poster` | new 2026-09-14 | As above. |
| `05 Asset - Pixel Front View Single Object` | new, mirroring the side-view entry | |
| `05 Asset - Pixel Front View Spritesheet` | rcg | |
| `05 Asset - Pixel Side View Single Object` | rcg | |
| `05 Asset - Pixel Side View Spritesheet` | rcg | |
| `06 Cool - Futuristic Human World` | rcg `HABITAT (simpler)` | Elaborate version cut; it says the same in twice the words. |
| `06 Cool - Combat Robot` | rewritten from scratch | Source was a bare subject list. Rewritten as a *transformation*: takes any subject and forges it into a mecha. |
| `06 Cool - Mega Vehicle` | rewritten from scratch | Was `EPIC FRONTAL VEHICLE`. Same treatment — a megamachine / fortress-vehicle forge. |
| `06 Cool - Homo Mugen` | rewritten from scratch | Both source variants cut. See the brief below. |
| `07 Beauty - Pretty Eyes` | beauty `HYPNOTIC GAZE` | |
| `07 Beauty - Pretty Lips` | beauty `CAPTIVATING LIPS` | |
| `07 Beauty - Pretty Hand` | beauty `ENCHANTING HAND` | |
| `07 Beauty - Pretty Ear` | beauty `ADORNED EAR` | |
| `07 Beauty - Entrancing Portrait` | beauty | |
| `07 Beauty - Latex Beauty` | beauty + positives line 8 | The only beauty entry that was too *short*; absorbs the stray latex/lipgloss/nail fragment. |
| `07 Beauty - Mirror Selfie Room` | beauty | |
| `07 Beauty - Mirror Selfie Phone` | beauty | Differs from Room by one clause in the source. Kept as two because the phone glimpse genuinely changes the composition. |
| `08 Games - ASTRONEER (Action/3D)` | positives | Genre/graphics-style suffix added 2026-09-03 so the dropdown carries what kind of game it is at a glance. |
| `08 Games - Planetary Annihilation (Strategy/3D)` | positives | Best entry in `positives.txt` — the developers' own design doc. The stray "trees" is removed. |
| `08 Games - Super Mario Galaxy (Platformer/3D)` | positives | |
| `08 Games - XCOM 2 (Tactics/3D)` | positives, de-branded | Subject nouns (aliens, cybernetics, weaponry) stripped; palette, lighting and mood kept. |
| `08 Games - Homeworld 1 (Strategy/3D)` | expansion, 2026-09-03 | Deliberately crude low-poly. Paired with Homeworld 2 as a before/after — same lineage, opposed render fidelity. |
| `08 Games - Homeworld 2 (Strategy/3D)` | expansion, 2026-09-03 | Sleek high-poly counterpart to Homeworld 1. |
| `08 Games - Super Mario World (Platformer/2D Sprite)` | expansion, 2026-09-03 | 16-bit SNES sprite era, Mode-7-adjacent parallax. |
| `08 Games - Donkey Kong Country (Platformer/2D Sprite)` | expansion, 2026-09-03 | Pre-rendered CGI sprites downsampled to 16-bit — a distinct rendering technique from Mario World's hand-drawn sprites. |
| `08 Games - Super Metroid (Action/2D Sprite)` | expansion, 2026-09-03 | Dark, desaturated, atmospheric — the gap flagged at the 08 GAMES session that cut it the first time. |
| `08 Games - Metroid Fusion (Action/2D Sprite)` | expansion, 2026-09-03 | GBA-era, cooler and higher-contrast than Super Metroid — paired as a deliberately distinct counterpart. |
| `08 Games - Warning Forever (Shmup/2D)` | expansion, 2026-09-03 | Neon wireframe over flat color fills. Paired with Battleships Forever. |
| `08 Games - Battleships Forever (Shmup/2D)` | expansion, 2026-09-03 | Same wireframe lineage as Warning Forever, but textured fills inside the outline — the one differing clause. |
| `08 Games - DEFCON (Strategy/2D Vector)` | expansion, 2026-09-03 | Neon vector line art on black; nothing else in the roster covers this render technique. |
| `08 Games - Portal (Puzzle/3D)` | expansion, 2026-09-03 | Sterile test-chamber material language. |
| `08 Games - Tribes Ascend (FPS/3D)` | expansion, 2026-09-03 | Blocky angular low-poly-leaning hard-surface design. |
| `08 Games - Battletech (Tactics/3D)` | expansion, 2026-09-03 | Chunky mass-conveying mech silhouettes. |
| `08 Games - C&C Allies (RTS/Isometric 2D)` | expansion, 2026-09-03 | Faction-rebranded from Red Alert 2; body text is palette/design-language only, no faction nouns. |
| `08 Games - C&C Yuri (RTS/Isometric 2D)` | expansion, 2026-09-03 | Faction-rebranded from Yuri's Revenge. |
| `08 Games - C&C GDI (RTS/Isometric 2D)` | expansion, 2026-09-03 | Faction-rebranded from Tiberian Sun, desolate GDI-leaning. |
| `08 Games - Halo Covenant (RTS/3D)` | expansion, 2026-09-03 | Faction-rebranded from Halo Wars 2. |
| `08 Games - Red Faction EDF (Action/3D)` | expansion, 2026-09-03 | Faction-rebranded from Red Faction Guerrilla. |
| `08 Games - Systems Alliance (Action RPG/3D)` | expansion, 2026-09-03 | Faction-rebranded from Mass Effect 1. |
| `08 Games - USG Ishimura (Horror/3D)` | expansion, 2026-09-03 | Faction/setting-rebranded from Dead Space (original). |
| `08 Games - Overwatch (Hero Shooter/3D)` | expansion, 2026-09-03 | Re-included with a fresh angle (clean painterly hero-render, not generalist digital art) after being cut in the original session for overlapping `01 Main - Digital Art`. |
| `08 Games - Celeste (Platformer/2D Sprite)` | expansion, 2026-09-03 | Re-included with a fresh angle (gradient-sky atmosphere, emotional warmth) after being cut in the original session for overlapping the pixel presets. |
| `08 Games - Terraria (Adventure/2D Sprite)` | expansion, 2026-09-03 | |
| `08 Games - Kingdom Rush (Strategy/Isometric 2D)` | expansion, 2026-09-03 | |
| `08 Games - Slime Rancher (Adventure/3D)` | expansion, 2026-09-03 | |
| `08 Games - Rollercoaster Tycoon 2 (Simulation/Isometric 2D)` | expansion, 2026-09-03 | |
| `08 Games - Super Smash Bros Melee (Fighting/3D)` | expansion, 2026-09-03 | GameCube-era stylish menu energy plus glossy 3D render. |
| `08 Games - Master of Orion 2016 (4X Strategy/2D Painted)` | expansion, 2026-09-03 | Painterly illustrative sci-fi concept-art style. |
| `08 Games - Stars in Shadow (4X Strategy/2D Sprite)` | expansion, 2026-09-03 | Cozy painterly pixel-adjacent, small-scale charm rather than epic grandeur. |
| `08 Games - Einhander (Shmup/3D)` | expansion, 2026-09-03 | PS1-era low-poly grim industrial shmup. |
| `08 Games - Deus Ex Human Revolution (Action RPG/3D)` | expansion, 2026-09-03 | Black-and-gold renaissance-cyberpunk palette. |
| `08 Games - Team Fortress 2 (Action/3D)` | expansion, 2026-09-03 | Exaggerated comic-proportioned painterly 3D. |
| `08 Games - Daemon X Machina (Action/3D)` | expansion, 2026-09-03 | Stark black/red/neon-orange mecha design language. |
| `08 Games - Synthetik 2 (Action/Top-Down 3D)` | expansion, 2026-09-03 | Contemporary military-industrial robotics. |
| `09 Artist - ...` | positives line 4 | Several entries; see below. |

### The `06 COOL - HOMO MUGEN` brief

The source's two variants are cut entirely — both are dense with subject-specific words ("cellular regeneration", "hermaphroditic biology", "amorphous", "gentle mutation") that read as body horror to a diffusion model. The concept being written to instead:

> An evolved, genetically enhanced human that keeps the recognisable human form, but with unlimited cosmetic biomodding and no downsides. Exotic and beautiful skin, hair, features and accessories. **Not** mutants, **not** horror — the "mugen" is *infinite fantasy* in what beauty could be if biology were fully customisable.

Written to steer toward striking rather than unsettling. Terms suggesting deformation, dissolution or loss of human structure are deliberately excluded, and the `Anti-Horror` negative layer stacks well with it.

### `09 ARTIST`

Built from the artist list in `positives.txt` line 4, which pairs each name with the look it is being reached for. Each entry names **one primary artist plus one or two stylistic companions**, which is how artist prompting is meant to work — several references blended past the point of reproducing any single body of work.

Named in the roster as `09 Artist - Full Name (Title of Their Most Popular Work)`, e.g. `09 Artist - Tsutomu Nihei (Blame!)`. A bare surname told a browsing user nothing; the full name plus a recognisable credit gives them something to picture before they read the body text. Where an artist has no single iconic piece, the parenthetical names their best-known body of work instead (e.g. `(Ender's Game Covers)`, `(Warhammer 40K Fan Art)`) rather than guessing at a specific title.

### What `08 GAMES` gets now, and what it does not

Four entries shipped in the original session, from what `positives.txt` already contained in usable form. **Expanded 2026-09-03** to 37 entries after a dedicated per-title research pass — the group is no longer deliberately small.

The filter applied to every candidate title, then and now: a game preset earns its slot by capturing **camera and rendering nuance the generic styles cannot** — isometric or side-on or top-down, FOV and lens, pixel art versus HD sprites versus low-poly models. "General art style" or "I like this game" was not sufficient on its own; several popular titles were evaluated and rejected because they didn't clear that bar (Bomberman Hero, Starcraft 2 confirmed-cut again, Planetary Annihilation TITANS as a duplicate of the existing Planetary Annihilation entry, several under-researched titles left for a future pass — Antichamber, HYPERNOVA: Escape from Hadea, Taur).

**Faction-themed entries are rebranded to the faction, not the parent title**, and their bodies stay strictly style-only per rule 3 — palette, material language and design vocabulary, never a faction or franchise proper noun in the body text itself (the heading carries the real-world reference point; the same pattern the original XCOM 2 entry already used). This produced `C&C Allies` / `C&C Yuri` / `C&C GDI` as three separate isometric-RTS entries rather than one generic Command & Conquer preset, because the three factions carry genuinely different palettes and design languages within the same camera convention.

**Overwatch and Celeste were re-included**, reversing the original session's cuts, once a sharper angle was found for each: Overwatch as the clean painterly hero-shooter render (distinct from the generalist `01 Main - Digital Art`), Celeste for its gradient-sky atmosphere and emotional warmth (distinct from the existing pixel presets, which don't carry that mood). Super Metroid, flagged as a genuine gap at the time, is now filled — paired deliberately against Metroid Fusion's cooler, tighter, higher-contrast GBA look so the two don't collapse into one generic "Metroid pixel art."

---

## Negative layer roster

Each layer covers **one** concern. They compose with case-insensitive de-duplication on comma-separated terms, first occurrence winning, so overlap between layers is expected and harmless.

**Stacking is nearly free** — classifier-free guidance encodes the negative prompt in its own pass with its own full token budget, so a heavy negative costs the scene description nothing. Terms are therefore left out for being **inert**, never for being expensive. Anatomy fixes do nothing for an empty landscape; that is the only reason to leave them off.

**Several layers deliberately contradict each other.** `Photoreal Guard` and `Anti-Photo` are opposites; so are `Quality Floor` and `Ruin Quality`, and `Colour Discipline` and `Deep Fried`. This is correct — they are layers, you tick one.

| Layer | Concern |
|---|---|
| `Quality Floor (Photo)` | Generic photographic quality: bad exposure, poor composition, muddy light. |
| `Quality Floor (Art)` | The 2D-art equivalent: amateur drawing, wonky linework, flat lifeless rendering. |
| `Ruin Quality (Photo)` | **Inverted.** Deliberately produces a badly-taken photo. |
| `Ruin Quality (Art)` | **Inverted.** Deliberately produces a poorly-drawn image. |
| `Deep Fried` | **Inverted.** Deliberate corruption — colour, contrast and lighting wrecked. Opposite of `Colour Discipline`. |
| `Text & Markings` | Watermarks, signatures, logos, captions, letterforms, subtitles, UI and HUD. |
| `Framing` | Cropped, out of frame, cut off, tiling, seams, borders, matting. |
| `Anatomy (General)` | Overall body structure and proportion. |
| `Anatomy (Hands)` | Split out because hands fail independently of everything else and are the most common visible defect. |
| `Anatomy (Arms & Limbs)` | Extra, missing and disconnected limbs. |
| `Anatomy (Pose)` | Impossible, broken and stiff posing. |
| `Anatomy (Skin)` | Blemishes, plastic and waxy skin, texture failures. |
| `Faces & Eyes` | Survives every other fix; deformed iris and pupils, asymmetry, misaligned gaze. |
| `Anti-Horror` | Beyond anatomy — stops a merely-wrong result becoming a genuine freak show. |
| `Extra People` | Multiple subjects, duplicates, clones, crowds. Orthogonal to anatomy. |
| `Photoreal Guard` | You asked for a photo and got a 3D render: plastic skin, CGI, uncanny. |
| `Anti-Photo` | You asked for illustration and it drifted to stock photography. |
| `Clean Background` | Clutter, busy backgrounds, stray objects, debris. |
| `Colour Discipline` | Oversaturation, blown highlights, washed-out and muddy colour, banding. |
| `Sprite / Cutout` | Background, ground plane, cast shadows and perspective — the things that make a cut-out asset unusable. |

Negative layers keep plain descriptive names rather than the `NN GROUP - NAME` scheme. They are a checkbox list of a manageable size, not a dropdown of forty-five, and grouping them by number would add ceremony without adding navigation.

### What was cut from `negatives.txt`, and why

The source file is roughly **the same forty terms shuffled into eight different orders** (lines 4, 10, 22, 28, 31, 34 and 45 are all permutations of one anatomy-plus-quality pile). It was collected from scattered folders as a **word cloud to pick ideas from**, never as a design, and it is treated that way: the vocabulary is kept, the structure is rebuilt from scratch.

Specifically dropped:

- **Embedding filenames and tag conventions** — see rule 5 above. Inert on every model in this lineup.
- **Attention-weighting syntax** — see rule 4. The bare terms are kept, the `(term:0.8)` wrapping is not.
- **Line 14** (`glowing, fuzzy, face, detailed background, photo`) — a project-specific negative. `face` and `photo` as blanket negatives are actively dangerous defaults.
- **Lines 50–52** (`cel shading, toon shading, bright colors`) — a legitimate "no cartoon" idea, but filed under universal negatives where it would wreck every stylized batch. Its territory is covered by `Anti-Photo`'s inverse rather than shipped as a universal.
- **Lines 59–179, the positive-framing list** — ~110 entries converting negatives into positive phrasing ("captivating visual flow", "inspiring composition", "emotional depth"). **Considered and cut.** The genuinely useful half is already what `Quality Floor` and `Clean Background` express as negatives, and the rest is inert affirmation. Its one real contribution — the clutter and background-simplicity terms — became `Clean Background`.
- **`((high quality, masterpiece, masterwork))`** from `positives.txt` — SD1.5-era booru weighting, near-inert on SDXL, meaningless on FLUX, and the weight syntax is unparsed here.

### The existing two layers are superseded

`Universal Clean-up` and `Human Anatomy` currently ship in `utils/config.py`. `Universal Clean-up` splits into `Text & Markings`, `Framing` and `Quality Floor (Photo)` — a real improvement, because those are three separate concerns a user will want independently. `Human Anatomy` becomes the five `Anatomy (...)` layers plus `Faces & Eyes`.

---

## Not this session

- The ~20 vague/interpretable prompts (`WIP todo styles etc/!TODO.md`).
- The Commander Wars mod prompt files.
- The "4th tab with LLM assist" idea.
- The three GUI reinforcements proposed above — top-sorting for user presets, Save-As prefill, and hint text — which need their own decision.
- A handful of `08 GAMES` titles considered and left out for now due to insufficient reference confidence: Antichamber, HYPERNOVA: Escape from Hadea, Taur.
