# Filenames, resume identity, and Regenerate — plan (2026-09-13)

Started from two user-reported symptoms and grew into a naming revamp, because the symptoms turned out to share one root cause: **nothing that identifies a generated image accounts for the style suffix.**

## The reported symptoms

1. "A single-prompt override gets skipped if the prompt is identical to a previous run, even when I changed the style suffix." — Correct.
2. "Overwrite existing files doesn't get me around it." — Correct.
3. "The .batchgen.db file stays locked until I close the program." — Correct, and it is a plain resource leak.

## Root causes, as found in the code

**A. Batch identity ignores the style suffix.** `find_batch()` ([core/db.py:220](../core/db.py#L220)) keys on `source_file + output_dir + model + width + height`. The suffix is *stored* on the batch row by `create_batch()` but never *compared*. Change the suffix, keep the prompt, and `prepare()` reattaches to a batch whose jobs are all `done`. Nothing runs.

**B. The filename ignores the style suffix.** `build_filename()` ([core/prompts.py:249](../core/prompts.py#L249)) uses `source_file + line_no + original_prompt`, and `original_prompt` is the bare line *without* the suffix. So even with A fixed, `existing_output()` globs the same prefix, finds the old image, and marks the job `SKIPPED` ([core/engine.py:424](../core/engine.py#L424)).

Two independent gates, same missing input. Both must be fixed or the symptom survives.

**C. The one-off override concentrates the problem.** `materialize_one_off()` ([core/prompts.py:355](../core/prompts.py#L355)) names its materialised `.txt` from the prompt text alone, so an identical prompt yields an identical `source_file` — hence the same batch *and* the same filename. The "disambiguate on CONTENT" guard there considers only the prompt, never the suffix. This is exactly the reported case.

**D. Overwrite is a file-level flag only.** It is honoured at [engine.py:424](../core/engine.py#L424) and [engine.py:580](../core/engine.py#L580), but **no database code consults it**. A `done` job is never handed out by `claim_next()`, so the overwrite check is code that job never reaches. `recipes.md:122` currently claims ticking Overwrite "regenerates everything" — **that line is wrong** and must be corrected.

**E. The db lock is a leaked JobStore.** [gui/app.py:511](../gui/app.py#L511) constructs a whole `BatchEngine` just to count prompt lines and discards it without `close()` — no `with`, unlike `dry_run()` twenty lines below which does it correctly. The constructor opens a live `sqlite3` connection ([engine.py:153](../core/engine.py#L153)). WAL mode leaves `-wal`/`-shm` sidecars that only clear on a clean close. It fires on **every Start press**, including ones cancelled at the paid-confirmation dialog.

## The naming revamp

### Why the old scheme fails, measured

Tested against the shipped `test_prompts.txt`. The first four lines differ in exactly the words that matter (field/forest/desert/wasteland, day/dawn/dusk/night, cloudy/rainy/clear/thunderstorm). At the shipped 32-char budget:

```
distant_low_angle_cloudy_weather
distant_low_angle_rainy_weather
distant_low_angle_clear_weather
distant_low_thunderstorm_weather
```

**The subject never appears at any budget.** `_squeeze()` keeps words from both ends, but a batch's shared boilerplate sits at *both* ends (`Distant low angle background of a ...` / `... weather.`) while the variation sits in the middle. At a 20-char budget all four collapse to the identical `distant_low_weather`.

### The fix: pick words that VARY across the batch

The engine loads every prompt line before naming anything, so it can **measure** which words repeat instead of guessing by position. Keep words appearing in at most half the lines; drop the rest as boilerplate. Same corpus, same budget:

```
field_day_cloudy
forest_dawn_rainy
desert_dusk_clear
wasteland_night_thunderstorm
```

Distinguishable, and shorter. Verified to degrade correctly on four batch shapes: a single line (no corpus — falls back to the current stopword+squeeze path), four lines with no shared boilerplate (unchanged, nothing to strip), a heavy shared preamble (above), and the two-line stem-collision pair from `test_engine.py` (`tall_pines` / `dark_spruces`, which the current code deliberately collides).

This must stay deterministic — the docstring at [prompts.py:186](../core/prompts.py#L186) is a hard requirement, since resume rebuilds the name to find the image. Determinism now depends on the *corpus*, so the corpus must be the full unlimited prompt list, never the `limit`-truncated one, or a limited run and a full run would name the same line differently.

### The structure

```
source(10)-NNN-prompt(20)--suffix(20)-hash(6).ext
```

Example: `paid_test_-001-epic_montage_warzone--soft_painterly_bloom-a3f9c2.jpg`

- **Double dash before the suffix.** Single dashes everywhere else read as one continuous phrase, so prompt and style blur together. `--` is the only divider that survives slugging (every other separator is a legal slug character or gets eaten by `_UNSAFE`).
- **No model field.** Deliberately omitted: an abbreviation table would be a second place a model's identity is written, and `core/models.py` is the single source of truth. The folder-per-model workflow in `out/collage/` already covers comparisons, better than a filename field would.
- **Style suffix as a slug, not a preset name.** A preset *name* can lie — the user may edit a preset's text without re-saving it, leaving a filename that asserts a style it does not have. A slug of the real text cannot lie, and it handles custom un-preset suffixes for free.

### The hash

`blake2b(key, digest_size=4).hexdigest()[:6]` over everything that changes the image: final prompt (which already contains the suffix), model key, width, height, negative prompt, guidance, steps, prompt-expansion mode, content-filter mode.

**Derived, never random.** A random tag was considered and rejected: it makes `build_filename()` unrebuildable, which breaks `existing_output()`, which breaks crash-resume and overwrite protection for *every* batch — and it silently re-bills an entire paid batch on any rerun, since nothing is ever recognised. Collisions are the feature: two files colliding means "same image", which is what resume is for.

**The seed is excluded from the key** (decided). Including it would mean a random-seed rerun always writes a new file and resume never skips. Excluding it keeps resume meaningful and gives Regenerate a clear, separate job.

The hash subsumes fix A: a changed suffix changes the filename, so resume regenerates by construction. `find_batch()` is still fixed, because the DB and the disk must agree on what "the same batch" means.

### Budget

60 was a thrown-out figure, not a constraint. Slugs at 20/20 give ~66 characters with the extension. The real constraint is Windows MAX_PATH (260 for the whole path, inside a user-chosen and possibly deep output folder), and ~66 is comfortable. Word-boundary truncation is already handled by `_squeeze`. Tune the two slug budgets against real prompt/suffix pairs rather than by eye.

## Overwrite vs Regenerate

Settled: **leave Overwrite alone** as file-level protection, and add a **Regenerate** button that resets `done` jobs to `pending`.

Once the hash covers every image-affecting parameter, "I changed something" regenerates automatically. The only case left is "I changed nothing and want another roll anyway" — a different random seed, or the first result was simply ugly. That is a genuinely different intent from "don't protect files on disk" and deserves its own control rather than overloading a checkbox.

It is also a spend action on paid models, so it gets the same confirmation `_confirm_paid()` already applies to a fresh batch.

## Work items

1. **Close the leaked JobStore** — wrap [gui/app.py:511](../gui/app.py#L511) in `with`. One line, pure bug.
2. **Style suffix in `find_batch()`** — add it to the WHERE clause. Column already exists.
3. **Corpus-aware prompt slugs** — new keep-what-varies pass, falling back to today's behaviour on a single-line corpus.
4. **New filename structure + derived hash** — including the `--` divider.
5. **Regenerate button** — GUI + `store` method + CLI parity, with paid confirmation.
6. **Docs** — correct the wrong `recipes.md:122` claim; update `guide.md`, `findings.md`, `CLAUDE.md`.

## Migration

The scheme changes every filename, so existing images stop being recognised by resume and would be regenerated. Everything under `out/` is disposable test data. **Confirm before running anything against a real batch folder**, and no generation runs without explicit permission.
