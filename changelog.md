# Changelog

## v2.2 — show the model the look you want

### Added

- **Style reference image — show the model a picture instead of describing it.** New **Style Reference Image** box on the Provider tab. Tick it, pick a PNG, JPEG or WebP, and that image is sent along with every prompt in the batch so the results follow its look. Some styles are far easier to show than to put into words — a sprite sheet, a painting, a piece of concept art. The style suffix and the reference work together: the suffix carries the words, the image carries the look. A small preview shows exactly what will be sent, and a line beside it says what was done to it.
  - **Works on five models:** FLUX.2 klein 4B, FLUX.2 klein 9B, FLUX.2 pro Preview, Nano Banana 2 Lite and Nano Banana 2. The other models have no way to accept an image, so on those the box greys out and tells you which models to switch to, rather than quietly ignoring your picture. **klein 4B is the one to start with** — it is free for roughly the first 75 images a day.
  - **Any size, almost any shape.** The program resizes your image to about 1 megapixel, which is what these models handle best. Images under 64 pixels a side are enlarged, because the models refuse anything smaller, and that refusal would otherwise fail every image in the batch with an unhelpful error.
  - **Pixel art stays crisp.** Sprites are resized with hard pixel edges instead of being blurred, and the program detects which kind of image you gave it. If it guesses wrong, the **Resizing** dropdown lets you choose.
  - **Very long, thin images are refused up front**, such as an animation strip laid out in one row, with a message saying how to fix it. Your reference does not need to match your output shape — a square sprite guiding a widescreen batch is perfectly normal.
  - **Your file is never modified.** All resizing happens on a copy in memory.
  - **Changing the reference counts as changing the picture**, so a re-run makes fresh images instead of skipping the ones already on disk. That holds even if you swap a different image in under the same filename, because the program looks at the picture, not the name.

- **An Influence dropdown for the reference image.** No model offers a "strength" setting for a reference, so the only way to steer it is with words in the prompt — and typing that into every line is tedious. The dropdown adds a short sentence to the end of every prompt for you: **None** ("No influence from image 0."), **Subtle**, **Medium**, **Heavy** or **Exact** ("Exact style as image 0."). On Nano Banana and FLUX.2 pro the wording says "the reference image" instead. The sentence shows in the Prompts tab preview and counts towards the prompt length, so what you see is still exactly what gets sent. Expect a nudge rather than a dial: the reference image itself does most of the work.

- **On the command line:** `--reference-image PATH`, `--reference-resample auto|nearest|lanczos` and `--reference-influence none|subtle|medium|heavy|exact`. `dry-run` shows the resize and the added sentence before anything is spent.

### Fixed

- **`cli.py dry-run` could crash when its output was saved to a file or piped into another command on Windows**, partway through the report, on the arrow and dash characters in the reference and cost lines. Output now always goes out as UTF-8.

## v2.1 — helpers, one-off prompts, and images that know what made them

### Added

- **A new Helpers tab, with the prompt recipes built in.** The program ships with `recipes.md`, a set of prompts you paste into a chat assistant — Claude, ChatGPT, Gemini or Perplexity — to help you write better image prompts: build a reusable style block, turn a piece of writing into an image prompt, get eight varied prompts for a whole batch, or squeeze a long prompt down to fit Stable Diffusion's limit. Until now, using one meant opening the file, finding the right block, and carefully selecting it with the mouse without clipping the edges — and clipping the edges is easy to do and hard to notice. Now there is a button for each one that puts it on the clipboard exactly, plus links that open the assistant sites, and a short note next to each button saying what it does and what to do with the answer. **The tab is built from `recipes.md` itself, so you can edit that file — change the wording, add your own prompts, add or remove links — and press Reload to see your changes straight away.** The file explains the two markers it uses, so you know what to leave alone.

- **Single custom prompt — try one image without writing a file for it.** New tickbox at the bottom of the Files box on the Prompts tab. Tick it, type a prompt, and the next run makes exactly one image from that text instead of reading your prompt file. It is for the moment when you have an idea, want to see it once, and writing a `.txt` for a single line feels like a chore. Your prompt file is left completely alone and one untick puts everything back. The tickbox and the text both survive a restart, so whatever you were last playing with is still there tomorrow. The preview, the character counter and the cost estimate all follow it, so what you see is still exactly what will be sent. Re-running the same one-off prompt resumes rather than generating it again, so it cannot quietly cost you twice. On the command line the same thing is `--prompt "your text"` in place of the prompt file.

- **18 new style presets, in the Photo and Asset groups.** The style dropdown has grown considerably — the Photo group is now nineteen entries and Asset eleven. There are now a total of awesome 110 style presets to choose from!
  - **Photo gained thirteen**, arranged so that neighbouring letters are genuinely different choices rather than shades of one another. *Professional* and *Candid* got remade to be about skill/intent. There are two plain opposites — *Soft Feel* and *Hard Feel* — then *Cinematic*, *Extreme*, and pairs that let you pick a surface and a world: *Glossy-Shiny* against *Gritty-Dirty* and *Grunge-Rough*, *Utopian-Hightech* against *Dystopian-Bleak*, plus *Dreamy-Surreal*, *Noir-Gothic*, *Horror-Terror*, *Nuclear-Fire* and *Long Exposure*. They are treatments rather than subjects, so any prompt file can be run through any of them.
  - **Asset gained five**, and these are the ones to reach for when the image has a job to do rather than a look to have: *Silhouette*, *Seamless Texture*, *App Icon*, *Promotional Cover* and *Advertisement Poster*. The first three deliberately describe **structure only** — framing, background, how readable the shape is — and name no style, medium or subject at all, so you can stack your own look on top. They also assume no particular shape of image, because the size control is where you choose that.

- **A Regenerate button, for redoing images you have already made.** Previously there was no supported way to say "make these again" — you had to delete the files by hand. Regenerate redoes the images from the run you just did, after a confirmation that tells you how many and what it will cost. It leaves refused prompts alone, since the same text gets the same refusal, and leaves failed ones to the existing Retry Failed button, so the two actions stay separate and separately priced. It covers the images in the current run rather than your whole prompt file — if you generated the first 5 of 100, Regenerate does those 5, and the count is stated next to the button. When there is nothing to regenerate yet, the button is switched off with a line saying why rather than leaving you to guess.

### Changed

- **Image filenames now carry a short code derived from the settings that made the image.** The prompt, the model, the size, the negative prompt, the style suffix and the rest all feed into it. This is what makes "I changed something, so make it again" work by itself, rather than depending on the program remembering to check each setting individually. Two runs producing the same code means the settings really were identical. The seed is deliberately left out, so a batch with random seeds can still be resumed after a crash.

- **Filenames now pick the words that actually differ between your prompts.** They used to take words from the start and end of each line, which is exactly where batch prompts tend to be identical — four prompts beginning "Distant low angle background of a…" and ending "…weather" all named themselves the same thing, and the part that varied never appeared at all. They now name themselves from the words that vary across the batch: `field_day_cloudy`, `forest_dawn_rainy`, `desert_dusk_clear`.

- **The "Overwrite" checkbox now says what it actually does.** It read "Overwrite images that already exist", which sounds like "regenerate everything" — and it never did that. It only governs whether a newly generated image replaces an existing file or saves alongside it; on a finished batch it does nothing at all, because there is nothing left to generate. It now reads **"Replace files instead of saving alongside them (only affects images being generated now)"**, and points at Regenerate, which is the button that does the thing people were expecting. The behaviour has not changed — making the checkbox re-generate finished work would silently re-bill an entire paid batch whenever it happened to be ticked.

### Fixed

- **Changing your style suffix and re-running produced nothing.** The style suffix is part of the image, but it was not part of how the program decided whether an image already existed — so it would find the old file, decide the work was done, and skip silently. Change the suffix now and the images are regenerated, as you would expect.

- **The database file stayed locked until you closed the program.** Pressing Start opened a connection to the batch database that was never closed, including when you cancelled at the confirmation dialog, which left the working files beside it sitting there until the program exited.

- **The status line no longer clips mid-sentence, and no longer shifts the panels below it.** It was cut at 100 characters, which landed in the middle of nearly every real prompt. It now shows 160 — measured as the most that fits on two lines at the program's smallest window size, so the panels underneath stay put instead of jumping on every image.

---

## v2.0 — the big model update

### Added

- **Eight new models, taking the lineup from five to thirteen.** All of them are Cloudflare models reached through its AI Gateway, so they use the same account and the same API token you already pasted in — there is no second account to make and no second key to manage.
  - **P-Image** — very fast, and it automatically expands your prompt with extra detail. The cheapest of the new arrivals.
  - **Krea 2 Medium Turbo** and **Krea 2 Medium** — the strongest models here for anime, painting and illustration rather than photorealism. Turbo is the better buy; the full Medium is for when every image in a batch needs to look consistent with the others.
  - **FLUX.2 pro Preview** — chosen for its adjustable content filter rather than its pictures. Worth it if good prompts keep coming back refused.
  - **Recraft V4.1 Utility** and **Recraft V4.1** — solid all-rounders. Utility is the better of the two overall; the plain V4.1 is the one to pick for art direction, composition and readable text inside the image.
  - **Nano Banana 2 Lite** and **Nano Banana 2** — Google's models. Lite is the best quality for the money among the expensive options. The full Nano Banana 2 is the best-looking model available here and by far the most expensive, so it suits a handful of special images rather than a whole batch.
- **An adjustable content filter**, on the two models that offer one (P-Image and FLUX.2 pro Preview). If a perfectly ordinary prompt keeps being refused, you can now ask for a more permissive setting instead of just rewriting it and hoping. It does not switch moderation off, and the provider still applies its own limits — it asks for the loosest setting the model itself publishes. It is set to the permissive end by default, because in an overnight batch a wrongly refused prompt is a wasted slot you do not find out about until morning.
- **Control over prompt expansion.** The two Krea models expand your prompt before generating, filling in lighting, colour and composition detail of their own. This is not a quirk — it is what Krea is built around, and in our own side-by-side it was the difference between a muddled scene and a clean one on an identical prompt. It now defaults to **Moderate**, matching Krea's own default, and can be turned down to *Off* when you want your words used verbatim, or up to *Heavy* when you are exploring from a short prompt.
- **A first-time setup page**, as `1 first time setup tutorial.html` in the download. Six steps you open one at a time — install, the two free Cloudflare values, a prompt file, press Start — with a screenshot of each tab and a tick-off checklist beside them that remembers how far you got. There is **nothing on it about money**, because none of it costs any: it is meant to be blitzed through in a couple of minutes by someone who just wants to see images come out.
- **An advanced usage page**, as `2 advanced usage tutorial.html`, for when you want more than that. A sticky index down the side, sections that fold away, the three genuinely different ways a model is paid for, and a walk-through of loading AI Gateway credit **in the order that actually works** — card first, then the credits page, because doing it the other way round bounces you between pages. The Cloudflare setup screenshots that were already in the download are now shown inline, click to enlarge. **Both pages open in any browser and need no internet connection**, and every price on them is read out of the program's own model list, so they cannot drift from what it charges.
- **A direct link to your AI Gateway credit balance**, next to the model list, so you can check what you have left without hunting through the dashboard.
- **A prepaid credit notice.** The eight new models are paid for from a credit balance you top up in advance, not from Cloudflare's free daily allowance. The program now tells you that as soon as you select one of them, rather than letting you configure an entire batch and discover it at the moment you press Start. Worth knowing before you top up: Cloudflare requires a credit or debit card (PayPal is offered but not accepted for this), the minimum top-up is $10, and there is a 5% fee — so the smallest purchase costs $10.50. The guide walks through the setup in the order that actually works, and the download includes screenshots of each step.

### Changed

- **A five-level cost scale replaces the old over-budget warning.** Every model now sits in a band you can read straight off the list: **FREE**, **LOW COST**, **MEDIUM COST**, **HIGH COST** and **EXTREME COST**, marked in the dropdown with nothing, `$`, `$$`, `$$$` or `$$$$`. The old warning was a single sentence that appeared identically on a model costing $6 per 1000 images and one costing $151, and it explained itself in terms of a budget limit that meant something to me and nothing to you. The new bands are just money, and the most expensive band leads with what **your** batch costs rather than an abstract rate.
- **The size and quality tier options are now different for each model, and honest about what they do.** Previously the three tiers always claimed to run from "smallest and cheapest" to "biggest", which was wrong for most of the new models: on a flat-priced model, Draft costs exactly what High costs, so choosing Draft to save money saved nothing. Each option now shows the actual size it produces, and on the models where the tier genuinely changes the bill it shows the price too — Nano Banana 2 costs $67 per 1000 images at Draft and $151 at High, and the dropdown now says so at the moment you choose. Five of the thirteen models render at one fixed size only; on those the control is switched off with an explanation instead of pretending to do something.
- **Every model description rewritten in plain language.** The old ones were written for me and leaked in jargon — internal budget vocabulary, benchmark scores you cannot act on, and prices quoted per 1000 without ever saying per 1000 *what*. Each model now says what it is good at, what it costs per 1000 images, and what it cannot do, in that order.
- **The free models now explain why they are free.** All five original Cloudflare models draw on the same free daily allowance of 10,000 neurons — Cloudflare's compute credit, reset at midnight UTC. Three of them were measured using none of it at all; the two FLUX.2 klein models genuinely use it up, which is why klein 4B is free for roughly the first 75 images each day and klein 9B for only about 7 — 9B costs over ten times more per image, not the twice its name suggests. All of that was previously impossible to work out from the interface.
- **The Generation Settings panel is reorganised** into two clearly labelled groups — *Negative prompt* and *Model parameters* — instead of one wide grid with controls stranded at opposite ends of half-empty rows. On the models that ignore negative prompts entirely, that whole group now folds away, with a line saying why. Nothing is lost: your text, your layer choices and your settings all survive switching models and switching back.
- **The image size is now displayed as a headline figure**, large and directly under the two dropdowns that produce it, rather than as one more line of small text. It is the answer to "what am I actually getting", so it now looks like an answer.
- **The tile count is only shown where it means something.** It is a billing fact on the Cloudflare models that charge by tile, and a meaningless number everywhere else — on a flat-priced model it implied there was spare headroom to fill, and there is not.
- **The model list shows all thirteen models at once**, without scrolling.
- **The quality tier control is now labelled "Size / quality tier"**, because selecting a resolution is what it actually does.
- **FLUX.2 klein 9B is no longer flagged "OVER BUDGET".** It is described as what it is: slower and considerably pricier than klein 4B for a modest gain.

### Fixed

- **Pollinations images were arriving smaller than you asked for, and were being recorded at the wrong size.** This is the one worth reading properly, because it affects images you may already have generated. Pollinations silently caps images at about 1024x576 and quietly scales anything larger down to fit — it reports success, with no error and no warning. The program was asking for 1536x864 at the Standard tier, receiving 1024x576, and then writing "1536x864" into the details file saved beside the image. **Any Pollinations image generated with an earlier version has a details file that overstates its size.** The images themselves are fine, and their real dimensions are readable from the image file. The program now asks only for sizes Pollinations will actually deliver, records the size the file really has, and warns in the log if a provider ever resizes an image behind its back.
- **Long model descriptions were being cut off at the bottom of the screen** when hovering over the model list. The pop-up is now sized so it fits, and the model information that had grown too long to hover over at all has moved into the panel below the dropdown, where it stays on screen and updates as you choose.
- **The Guidance box accepted input on models that ignore it.** Eight of the thirteen models have no use for a guidance value, and the box stayed editable on all of them while the note two lines below correctly said it was unavailable. It is now properly switched off — and the boxes that are switched off show the value actually being used, or "n/a", instead of sitting empty and grey, which was indistinguishable from not having been filled in yet.
- **Panels no longer leave blank gaps after switching models.** Choosing a model with a long description and then going back to one with a short description used to leave two dead lines behind that never closed up.
- **The usage link now points at the right dashboard.** It always went to the Workers AI usage page, which shows nothing at all for the eight new models — those bill from credit, on a different page. It now goes to whichever page is relevant to the model you have selected.

### Removed

- **The licence line under the model list.** It sat under every model telling you something you had already assumed: you own the images you generate and can use them commercially. The one genuine caveat — FLUX.2 klein 9B's licence, which restricts running the model as a service yourself and not the pictures it makes — is still written up in the guide, where anyone actually looking for it will find it.
- **The store and marketing notes no longer ship in the download.** They were only ever of interest to me.

---

## v1.0 — first release

The original release: batch generation from a plain text file, a shared style suffix appended to every prompt, five Cloudflare models plus keyless Pollinations, a live cost calculator, dry run with no API calls, crash-resumable batches, details saved beside every image, detection of the content filter's all-black responses, and a command-line front end onto the same engine.

---

## Contact

mailto:reactorcoregames@gmail.com

---

Check out everything else I do: ✨🚀

https://linktr.ee/reactorcore

https://reactorcore.itch.io/

-Reactorcore

---

My other links:
Home/Links: https://linktr.ee/reactorcore
Releases: https://reactorcore.itch.io
Blog: https://www.patreon.com/ReactorcoreGames
Discord: https://discord.gg/UdRavGhj47
Catalog: https://reactorcoregames.github.io/

---

Made by Reactorcore — https://linktr.ee/reactorcore
