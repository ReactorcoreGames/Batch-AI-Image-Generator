# In-app prompt builder — tentative design notes

> **CUT 2026-08-31 — this feature will NOT be built into this program.** The argument against it below won: it is too niche and too specific to belong in a general-purpose batch tool. The need is real, but it becomes its own project — **Omni Prompt Builder**, a dedicated tool shipping a large curated array of wildcard `.txt` lists, aimed at producing exactly the prompt files this program consumes. This document is kept as input to that project, not as a plan for this one. Nothing here should be implemented in the batch generator.

**Status: brainstorm, nothing agreed.** Written 2026-08-31 to explore the TODO line "In-app prompt template expansion (`[biome]` × `[time]` combinatorics) so the `.txt` can be generated rather than hand-written." Everything here is a proposal to argue with, not a plan to build.

## The problem it solves

The tool's input is a `.txt` file, one prompt per line. That is a good input format and should not change. But the way that file actually gets *written*, for this project's own use case, is combinatorial: the mod brief in `original reason for this program/CoW Desired Background for mods.md` is a matrix of location × season × weather × time-of-day. Writing that by hand means typing the same sentence dozens of times with three words swapped, and every edit to the sentence means retyping all of them.

Concretely: 8 biomes × 4 times of day is 32 lines that differ by two words. Add weather (say 4) and it is 128. Nobody hand-maintains that, so in practice you either write a throwaway Python script or you quietly shrink your ambitions to what you are willing to type. Both are bad outcomes for a tool that is otherwise aimed at laypeople.

**The honest counter-argument, worth taking seriously before building anything:** this is a niche need. A user generating twenty unrelated illustrations gains nothing, and a fourth tab is a permanent cost paid by every user for a feature some fraction will ever open. That argues for the builder being clearly optional and self-explanatory rather than a step in the main flow — not for skipping it, but for where it sits and how loudly it announces itself.

## Core concept

One template line with named slots, plus a list of values for each slot. The builder produces the cross product.

```
Template:  Distant low angle background of a [biome] at [time]. [weather] weather.

[biome]    field, forest, desert, wasteland
[time]     dawn, day, dusk, night
[weather]  Clear, Cloudy, Rainy, Thunderstorm
```

→ 64 lines, previewed live, written to a `.txt` the rest of the program already understands.

That last point is the important design constraint: **the builder's only output is a normal prompt file.** It does not become a new input path into the engine, it does not get its own job type, and nothing downstream needs to know it exists. It is a text-file authoring aid that happens to live in the same window. This keeps the blast radius near zero and means the feature can be cut or reworked later without touching the engine.

## What the slot syntax should be

Candidate syntaxes, and why `[name]` is probably right:

| Syntax | For | Against |
|---|---|---|
| `[biome]` | Reads naturally; already the syntax used informally in the TODO and the mod brief | Square brackets do appear in real prompts occasionally (weighting syntax in some UIs) |
| `{biome}` | Familiar to anyone who has seen Python format strings | Same collision risk, and less familiar to laypeople |
| `<biome>` | Very unlikely to collide | Reads as markup/code, less friendly |
| `%biome%` | No collision at all | Ugly, reads as a batch file |

**Recommendation: `[name]`,** with an escape hatch (`[[` for a literal bracket) documented but not made prominent. The collision risk is theoretical for this program's providers, and readability wins for the target audience. Slot names should be case-insensitive and tolerate spaces (`[time of day]`).

## Layout sketch

A fourth tab, **Build Prompts**, sitting *before* Prompts in the notebook order — it produces the file the Prompts tab consumes, so left-to-right matches the workflow.

```
┌─ Template ─────────────────────────────────────────────────────────┐
│ Distant low angle background of a [biome] at [time]. [weather]     │
│ weather.                                                            │
│                                                    [Insert slot ▾]  │
│ Slots found: biome, time, weather                                   │
└─────────────────────────────────────────────────────────────────────┘
┌─ Slot values ──────────────────────────────────────────────────────┐
│  biome     │ field, forest, desert, wasteland          │ 4 values   │
│  time      │ dawn, day, dusk, night                    │ 4 values   │
│  weather   │ Clear, Cloudy, Rainy, Thunderstorm        │ 4 values   │
│                                          [+ Add slot] [Load set ▾]  │
└─────────────────────────────────────────────────────────────────────┘
┌─ Result ───────────────────────────────────────────────────────────┐
│ 64 prompts.  Estimated: free (SDXL Lightning, 1536x864)             │
│  1  Distant low angle background of a field at dawn. Clear weather. │
│  2  Distant low angle background of a field at dawn. Cloudy...      │
│  ...                                                                │
│              [Save as .txt…]  [Save and use as my prompt file]      │
└─────────────────────────────────────────────────────────────────────┘
```

Slots are discovered from the template automatically rather than declared separately — you type `[biome]` and a row for it appears. Declaring a slot in two places is exactly the kind of bookkeeping a layperson shouldn't have to do, and it can't get out of sync if there's only one source.

**Values are comma-separated in a single field, not a list widget.** A one-line entry you can paste into is far less work than an add/remove/reorder list, and comma-separated is how people already write these. The cost is that a value containing a comma needs an escape; that is rare enough to document rather than design around.

## Features worth having

**Live count and cost, prominently.** This is the feature most likely to prevent an expensive mistake. Combinatorics grow alarmingly fast: four slots of four values is 256 images. On the free lane that is an afternoon; on klein-9b it is real money. The count belongs next to the template where it updates as you type, and it should turn a warning colour past some threshold (500? 1000?) — with the existing cost calculator's numbers, not a second implementation of pricing.

**A hard guard rail at some ceiling.** Nothing good happens if someone accidentally produces 50,000 lines. Refuse to expand past a limit and say why, rather than freezing the UI building a list nobody wanted.

**Saved slot sets.** The biome/time/weather lists for the Commander Wars mods are worth keeping between sessions, and they are exactly the kind of thing you tweak repeatedly. This should reuse the existing style-preset mechanism in `utils/config.py` — same storage shape, same save/delete UI idiom — rather than inventing a second preset system.

**Ship the mod matrix as a built-in set.** The location × season × weather × time-of-day matrix from the mod brief is already written down. Having it present as a starting example makes the feature self-teaching: open the tab, see something real, edit it. This is the same reasoning behind shipping Painterly and Comic as built-in style presets.

**Skip-combination support, eventually.** Some combinations are nonsense — "desert at rainy weather" or a snow biome in summer. Options, roughly in order of increasing cost: (a) ignore it, let the user delete lines from the saved `.txt`; (b) an exclusion list of `slot=value + slot=value` pairs to drop; (c) conditional slots. **(a) is almost certainly right for v1** — the output is a text file, editing it is easy, and (b) is a surprising amount of UI for a problem that may not bite.

**Random sampling instead of the full product.** "Give me 30 random combinations out of the 256" is genuinely useful for exploring a style cheaply before committing. Cheap to implement (shuffle, take N), and it pairs well with the Draft tier as the intended iterate-then-commit workflow. Worth considering for v1 precisely because it makes the expensive-batch mistake less likely.

## Things to deliberately NOT do

- **Don't make it the required path to a prompt file.** Hand-written `.txt` files must stay first-class. Most users will never open this tab.
- **Don't invent a mini-language.** No conditionals, no arithmetic, no nesting slots inside slots. The moment this needs documentation longer than a paragraph it has failed its audience. If someone needs that power they can write a script and produce a `.txt`.
- **Don't merge it with the style suffix.** The suffix is appended to every line and already has its own editor and presets. Slots vary *per line*. Keeping them separate keeps both explainable.
- **Don't have it write directly into the engine.** Save a file, then point the Prompts tab at it. One artifact, visible on disk, editable by hand afterwards.
- **Don't auto-overwrite the user's existing prompt file.** "Save and use" should default to a new filename and confirm before replacing anything.

## Layperson-friendliness notes

The concept "template with slots" is not obvious to someone who has never programmed, so the tab has to teach it in the first three seconds. Things that would help:

- Prefill with a working example on first open, not an empty box. Seeing a filled-in template and its 64 results explains the feature better than any label.
- The word "slot" may be jargon. "Word list", "variable", "placeholder" — worth deciding. **"Placeholder"** is probably the most broadly understood.
- Show the *first few results* live, not just a count. The connection between "I typed `[biome]`" and "these lines came out" needs to be visible.
- Colour the placeholders in the template box so `[biome]` is visibly a special thing, not literal text someone expects in their image.
- The failure mode to design against: someone types `[biome]` and never fills in values, then generates 1 image containing the literal text "[biome]". Either refuse to save with empty placeholders, or substitute nothing and warn loudly.

## Open questions for the next session

1. Is this a fourth tab, or a dialog launched from a button on the Prompts tab? A dialog keeps the main window simpler and matches "most users never need this"; a tab is more discoverable and has room for the live preview. **Leaning tab**, but the discoverability argument cuts both ways given the niche audience.
2. Does the ordering of the cross product matter? Iterating biome-slowest groups all four times of day for one biome together, which is likely what you want when reviewing output side by side. Probably yes, and probably worth making the leftmost placeholder the slowest-varying.
3. Should the built-in mod matrix ship in the released tool at all, or is it Commander-Wars-specific clutter in a general-purpose program? (CLAUDE.md is explicit that the tool must stay general-purpose.) A neutral example may serve better, with the mod matrix kept as a loadable file in the project folder.
4. Does the CLI get an equivalent? A `python cli.py expand template.txt --slot biome=field,forest ...` would keep the two front ends in parity, and is cheap since the expansion logic would live in `core/`. Probably yes — the expansion belongs in `core/prompts.py` regardless, so both front ends can reach it.
