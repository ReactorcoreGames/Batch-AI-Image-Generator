# Video plan — trailer + walkthrough

Preliminary shot plans for two YouTube videos. **Both are on hold until after the Cloudflare model deprecation on 2026-11-20** ([changelog](https://developers.cloudflare.com/changelog/post/2026-11-05-planned-model-deprecations/)) and the v2.3 update that follows it, because the deprecation removes the three free Stable Diffusion models, including the program's current default. Anything recorded before v2.3 ships would show a model list, a default and a "free" pitch that no longer exist.

Dev-only, like `promo.md`. The YouTube title, description and tags live in [promo.md](../promo.md) and need the same post-v2.3 rewrite (see the checklist at the bottom).

Shots marked **⚠** depend on something the deprecation changes. Re-check each one against v2.3 before recording.

---

## What changes on 2026-11-20

| Removed | Was |
|---|---|
| `stable-diffusion-xl-lightning` | **The default model.** Free. |
| `stable-diffusion-xl-base-1.0` | Free. |
| `dreamshaper-8-lcm` | Free. |

Cloudflare suggests `flux-2-klein-9b` as the replacement for all three, but klein 9B gets only ~7 free images a day; **klein 4B (~75 free/day) is the likelier new default**, and that is a v2.3 decision rather than something this plan should assume. Once the three are gone, free generation means **klein 4B's daily allowance plus the two Pollinations models**, and the lineup drops from 13 models to 10. The videos should pitch "free to start, cheap to scale" rather than "free forever", which was the old angle.

---

## Before recording (both videos)

- [ ] v2.3 is released, and the recording uses the released exe rather than running from source.
- [ ] Record from a **clean copy of the release folder** with a throwaway `config.json`, so no personal presets, paths or one-off prompt text show up.
- [ ] Credentials: the Account ID field shows in plain text. Either blur it in editing, as the existing `promo/BAIG screenshot (2).png` does, or temporarily paste in a dummy value for the shots where keys are visible. The token and Pollinations key fields are masked unless "Show keys" is ticked, so never tick it on camera.
- [ ] Window at 1920x1080, maximised, with the Windows taskbar hidden or tidy. Use 125% display scaling or zoom in during editing so the 14px UI text survives YouTube compression.
- [ ] A **pre-generated output folder** of good-looking images for the time-lapse and the final montage. A fresh batch on camera is fine for the walkthrough, but the trailer needs the best results available.
- [ ] A prompt file that makes a visually varied batch, with mixed subjects, so the folder-filling shot reads as "lots of different things" rather than 40 near-identical forests.
- [ ] Decide whether any shot uses a paid model. If it does, generate those images deliberately beforehand; the recording itself never needs to spend money.

---

## Video 1 — Trailer (~60–75 s)

**Purpose:** the itch page video and the first thing a YouTube search hit sees. No voice-over; music plus large on-screen captions. Every shot answers "what does it do for me?", never "how does it work?".

**Hook:** the folder filling up. Open on the payoff, then explain it.

| # | Time | On screen | Caption | Notes |
|---|---|---|---|---|
| 1 | 0–5 s | Explorer window, thumbnail view, a folder filling with images in fast time-lapse | **A text file of prompts goes in.** | Cold open on the payoff. Speed it up enough that the images pop in rhythmically, ideally on the beat. |
| 2 | 5–8 s | Cut to a `.txt` in Notepad, one prompt per line, scrolling | **A folder of images comes out.** | Short, readable lines. Let the viewer see that it's just text. |
| 3 | 8–14 s | Prompts tab: pick a style preset from the dropdown, and the preview shows prompt + suffix | **One style for the whole batch** | Open the dropdown long enough to show how long the preset list is. |
| 4 | 14–20 s | Provider tab: change models, cost calculator updates | **Free to start. Cheap to scale.** ⚠ | Show the cost bands. After v2.3, start on the new free default, then switch to a paid model so the number visibly changes. |
| 5 | 20–26 s | Reference image box: pick a pixel-art sprite, preview appears | **Show it the look you want** | The v2.2 headline feature. Pixel art reads best because the crisp upscale is visible. |
| 6 | 26–32 s | Run tab: Dry Run output, then Start | **See the cost before you spend a cent** | Pause on the dry-run total. |
| 7 | 32–40 s | Run tab progress + log scrolling, time-lapsed | **Walk away. It runs unattended.** | |
| 8 | 40–46 s | Close the program mid-batch, reopen it, Start again, and it carries on | **Crash? Reboot? It picks up where it left off.** | One of the strongest selling points, and it's quick to show. |
| 9 | 46–52 s | Open a `.json` sidecar beside an image | **Every image remembers how it was made** | Zoom in on prompt / model / seed. |
| 10 | 52–65 s | Fast montage of the best outputs, full screen, varied styles | **No GPU needed.** | Music peak. Make sure the images come from models still in the lineup. ⚠ |
| 11 | 65–75 s | End card: program name, icon, "$8 on itch.io", link | **Batch AI Image Generator — reactorcore.itch.io** | Static card, 5+ s, so YouTube end-screen elements can sit over it. |

**Optional extra shot**, if there's room: the black-image detection — a refused prompt shows as BLOCKED in the log instead of being saved as a black square. It's the most technically impressive feature, but it takes words to explain, so it probably belongs in the walkthrough.

---

## Video 2 — Walkthrough (~8–12 min)

**Purpose:** the "how do I actually use this" video that gets found by search for years. Voice-over or captions, at the pace of a first-time user. Chapters double as YouTube timestamps, so keep one chapter per heading below.

| # | Chapter | Shows | Notes |
|---|---|---|---|
| 1 | **What it is** (0:30) | Folder-filling payoff shot (reuse the trailer's), then one sentence: text file in, folder out | Mention it runs on a weak PC because the generation happens in the cloud. |
| 2 | **Download and first launch** (0:45) | Unzip, the `!START HERE.png`, the two tutorial HTML pages, double-click the exe | Point out the `_internal` folder must stay beside the exe. |
| 3 | **Getting the Cloudflare keys** (1:30) | Cloudflare dashboard: Account ID, then Create Token → "Read all resources" | Reuse the flow from `promo/!cloudflare info/`. **Blur the Account ID and the token on screen.** Explain why a read-only token is enough. |
| 4 | **Saving keys and checking them** (0:30) | Provider tab → paste → Save Keys → Check Credentials | "Show keys" stays off. Mention `credentials.json` stays on the user's PC and the source is included for verification. |
| 5 | **Picking a model** (1:30) ⚠ | Model dropdown, cost bands (FREE / $ / $$ / $$$ / $$$$), the per-model description line | Rewrite after v2.3: the new free default, klein 4B's daily allowance, Pollinations as the keyless option, and when a paid model is worth it. |
| 6 | **Size and quality tier** (0:45) ⚠ | Aspect ratio, tier dropdown, pixel readout | The "44% more pixels for the same price" tile story is about per-tile billing. Check it still applies to whatever replaces the SD models as the default before claiming it. |
| 7 | **Writing a prompt file** (1:00) | Notepad, one prompt per line, `example_prompts.txt` | Show the prompt-length counter going over on a long prompt. ⚠ The SD 77-token limit leaves with the SD models, so the counter story may now be klein's 512 tokens instead. |
| 8 | **Style suffix and presets** (1:00) | Preset dropdown, editing the suffix, Save As, the preview pane | Explain that the suffix is what keeps a batch consistent. |
| 9 | **Negative prompts** (0:30) ⚠ | Stacked negative layers | Only the models that accept a negative prompt show this group. Check which ones still do after the SD models go; it may end up being a short aside or cut entirely. |
| 10 | **Single custom prompt** (0:30) | Tick the box, type one idea, run once | "Try an idea before writing a file for it." |
| 11 | **Style reference image** (1:30) | Pick an image, preview, Resizing dropdown, Influence dropdown | Use a pixel-art sprite and a painting so both resizing modes show. Note which models accept a reference. |
| 12 | **Dry run, then Start** (1:00) | Run tab: Dry Run output, the paid-confirmation dialog if on a paid model, Start | Linger on the dry-run cost. |
| 13 | **While it runs** (1:00) | Pause / Resume / Cancel, progress, log | |
| 14 | **When things go wrong** (1:00) | Close mid-batch and resume; a BLOCKED refused prompt; Retry Failed | The black-image story: the provider says "success" and sends a black square, and the program catches it. |
| 15 | **Redoing images** (0:45) | Regenerate vs. changing a setting (filenames carry a settings code, so a change makes fresh images) | Make clear Overwrite does *not* regenerate a finished batch. |
| 16 | **The output folder** (0:45) | Images, `.json` sidecars, the hidden `.batchgen.db` | |
| 17 | **Helpers tab** (0:45) | Copy a recipe, paste it into a chat assistant | Quick bonus mention. |
| 18 | **Command line, briefly** (0:30) | `cli.py dry-run` and `cli.py run` in a terminal | For automation-minded viewers. Keep it short. |
| 19 | **Wrap-up** (0:20) | End card, same as the trailer's | |

Running total is about 15 min at the listed lengths. Trim chapters 9, 17 and 18 first if it needs to come down toward 10.

---

## After 2026-11-20: update checklist

- [ ] Re-check every ⚠ shot against the v2.3 build and rewrite or drop it.
- [ ] Rewrite the YouTube description in `promo.md`: the "three Stable Diffusion models bill nothing" paragraph, "Thirteen models", the chapter timestamps (replace them with the trailer's or walkthrough's real ones), and the tag list (`stable diffusion`).
- [ ] Decide whether the trailer and the walkthrough get separate titles, descriptions and tag sets in `promo.md`. Currently there is one block, written for a single two-minute video.
- [ ] Link the trailer from the itch page and the walkthrough from `guide.md` / the setup tutorial pages.
