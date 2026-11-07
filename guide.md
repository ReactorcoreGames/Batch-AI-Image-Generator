# Batch AI Image Generator — User Guide

A text file of prompts goes in, a folder of images comes out.

---

## TL;DR / Quickstart

1. Run `Batch AI Image Generator.exe`.
2. Go to the **Provider** tab. Pick **Pollinations — no key needed** if you want to try it immediately with zero setup, or **Cloudflare Workers AI** (free, faster, needs two free values pasted in — see [Getting your Cloudflare keys](#getting-your-cloudflare-keys)).
3. Go to the **Prompts & Style** tab. Click **Choose Prompt File…** and pick a `.txt` file with one prompt per line. Click **Choose Output Folder…** and pick where the images should land.
4. Optionally pick a **Style Preset** — that text gets appended to every single prompt, so you don't have to repeat your style wording on every line.
5. Go to the **Run** tab. Click **Dry Run** first — it shows how many images you'll get and what they'd cost, without contacting anything. Then click **Start Batch**.

**The default setup costs nothing to run.** SDXL Lightning at the Standard tier was measured generating images at zero cost, so you can run a full batch on it without spending anything — the paid models are all opt-in and clearly marked. You can also close the program mid-batch and restart it later; finished images are skipped rather than regenerated.

---

## What this program is for

You have a list of image ideas — one hundred, one thousand — and you want all of them rendered without babysitting a web page. This tool takes that list as a plain `.txt` file, appends a shared style description to each line, sends them to a cloud image API, and downloads every result into a folder with a `.json` metadata file beside it.

It is built for unattended batches: it survives crashes, retries the failures that are worth retrying, refuses to retry the ones that aren't, keeps well inside free-tier rate limits by default, and tells you the cost before you spend it.

## Requirements

- Windows 10 or 11.
- An internet connection.
- Nothing else. Python is not required — the release is a compiled program.

## What's in the package

| File / folder | What it is |
|---|---|
| `Batch AI Image Generator.exe` | The program. Double-click it. |
| `_internal/` | Program libraries. Don't move or delete it — the exe needs it. |
| `guide.md` | This file. The **Help** button in the program opens it. |
| `1 first time setup tutorial.html` | **Start here.** Six steps you open one at a time, with a screenshot of each tab and a checklist that remembers your progress — install, keys, first batch, nothing about money. Opens in any browser, works offline. |
| `2 advanced usage tutorial.html` | The long version: the paid models, how the billing works, loading credit with screenshots, and the traps that cost money. Read it before picking any model with a `$` marker. |
| `prompting.md` | How to write prompts that work — length limits, structure, common traps. |
| `recipes.md` | Copy-paste prompts for building style presets and turning writing into images. |
| `readme.md` | Short overview and licence info. |
| `changelog.md` | What changed in each release, and what to watch out for. |
| `assets/icon.ico` | The window icon. Keep it beside the exe. |
| `cli.py`, `core/`, `gui/`, `utils/` | The source, for the command-line front end and for anyone who wants to read or modify it. |
| `test_prompts.txt`, `test_style_prompt_addon.txt` | Tiny example files so you can see the expected format. |
| `promo/` | Screenshots and cover art. |

`guide.md` and `assets/icon.ico` must stay next to the exe: the Help button and the window icon both look for them there at runtime.

---

## Writing prompt files

A prompt file is a plain `.txt` file with **one prompt per line**. Blank lines are skipped. That's the whole format.

```
a quiet forest clearing at dawn, mist between the trunks
a coastal fishing village under heavy grey rain
a desert highway at noon, heat shimmer over the asphalt
```

Three lines means three images. Write it in Notepad, or export it from a spreadsheet — anything that produces plain text works.

### The style suffix

Rather than repeating your art direction on every line, you write it once in the **Style Suffix** box and the program appends it to every prompt before sending. So the first line above actually gets sent as:

> a quiet forest clearing at dawn, mist between the trunks, soft painterly 2D digital illustration, broad expressive brushwork, atmospheric perspective, …

Dozens of style presets ship with the program, grouped and numbered in the dropdown (`01 Main`, `02 Photo`, `03 Style`, and on through named-artist references in `09 Artist`) so related styles sort together — your own saved presets always sort above them. You can edit the text freely and click **Save As Preset…** to keep your own. The **Preview** panel shows exactly what will be sent, so there is never any guessing.

Prompt wording matters more than the model does. A note from testing: the word "blurry" produces genuinely blurry images on the stronger models, because they follow instructions well. If you want atmosphere, say *soft focus*, *atmospheric haze*, or *depth of field* — say what you want, not what it vaguely resembles.

For how to write a good one — what to put first, how long it can be, and the traps — see **`prompting.md`**, and **`recipes.md`** for a copy-paste prompt that gets an LLM to build one for you.

### Trying a style on a few images first

Under the preview on the **Prompts** tab there is a **Generate** slider. Loading a prompt file always sets it to the maximum — every prompt — and dragging it down runs only the first N.

This is for style testing. Rather than building a second prompt file with five lines in it, load your real hundred-line file, pull the slider down to 5, and look at what comes out. The prompts past the cut stay visible in the preview, struck through, so you can see exactly where the line falls.

It always takes prompts from the **top** of the file, and that is deliberate. Images are matched to prompts by line number, so when you are happy with the style and slide back up to **All**, the images your test run already made are reused instead of being generated a second time. A five-image test costs five images, not five plus a hundred.

The cost figures on the Provider tab follow the slider, so the batch total shown is always for the run you are about to make.

### One image from a single typed prompt

Sometimes you have an idea and you just want to see it once, and writing a `.txt` file for one line is a chore. At the bottom of the **Files** box on the Prompts tab there is a tickbox: **Single custom prompt**. Tick it, type a prompt into the box underneath, and the next run generates exactly one image from that text and ignores your prompt file entirely.

A coloured line under the tickbox always tells you which one is in use — green while your prompt file is running, amber while the override is on. While it is on the prompt file row is greyed out. Untick it and everything goes straight back to your prompt file — it is never modified, and neither is your Generate slider setting.

The text box stays editable either way, so you can draft the next thing you want to try without arming the override first.

Everything else still applies. The style suffix is appended just as it is to a file prompt, and the model, size, negative prompt, guidance and seed are all the ones on the Provider tab. The only difference is where the prompt comes from and that there is exactly one of it.

The tickbox and the text both survive a restart, so the prompt you were last playing with is still there when you come back. The text is kept in a `single_custom.txt` beside the program.

Behind the scenes it is written into your output folder as an ordinary one-line prompt file, which means the image is named and recorded exactly like any other. Running the same one-off text twice picks up where it left off rather than generating a second copy, and two different one-off prompts stay separate even when they would produce similar file names.

### Where the images go

Each image is saved as `promptfile-linenumber-key_words--style_words-code.jpg` (or `.png`) — for example `landscapes-004-desert_dusk_clear--soft_painterly_bloom-a3f9c2.jpg`. Reading left to right: which file and line it came from, what the prompt was about, what style was applied, and a short code standing for every other setting.

Two details worth knowing:

- **The words are the ones that make this prompt different from the others in the batch.** If every line starts "Distant low angle background of a…", those shared words are dropped and the name keeps what actually varies — the subject, the time of day, the weather.
- **The double dash separates prompt from style**, so a folder is easy to scan even when every image shares one style.

The code at the end changes whenever anything about the image changes — the prompt, the style suffix, the model, the size, the negative prompt, and so on. That is what lets you re-run with a different style and get new files instead of the program deciding the work is already done.

Beside each image is a `.json` sidecar recording the original prompt, the final prompt with the style suffix, the model, the seed, the size, the timestamp and the estimated cost. If you ever want to reproduce an image, everything you need is in that file.

---

### Negative prompts and their presets

A negative prompt lists what you want kept **out** of every image. On the **Provider** tab, the **Negative preset** dropdown loads a saved one into the box, and works exactly like the style presets — Save As Preset, Delete Preset, same buttons in the same order.

**Universal Clean-up** is the built-in general-purpose set: watermarks, text, signatures, logos, quality floors and framing faults. It deliberately contains no anatomy terms (no "extra fingers", no "bad hands"). Those are dead weight on landscape and background work, and every word you spend costs room in a tight budget — see below.

Negative prompts are a **Stable Diffusion feature**, and only three models here accept one: SDXL Lightning, SDXL Base and DreamShaper. On the other ten the whole negative prompt group folds away with a line saying why — the FLUX klein models take a guidance value instead, and most of the AI Gateway models take neither. Your text and your layer choices are kept, so switching to one of those models and back leaves everything as you had it.

### How long can a prompt be?

Under the style editor, and under the negative prompt box, is a character counter. It turns amber as you approach the model's comfortable length and red past it.

It matters because **the model truncates silently**. Past its limit, the end of your prompt is simply dropped — no error, no warning, and nothing in the picture to tell you that your carefully written style suffix never actually arrived.

The limit depends on which model you picked, and the difference is large:

| Model | Comfortable length |
|---|---|
| SDXL Lightning, SDXL Base, DreamShaper | **~300 characters** |
| Pollinations DreamShaper | ~300 characters |
| P-Image, both Krea, both Recraft, both Nano Banana | ~800 characters |
| Pollinations FLUX.1 Schnell | ~1000 characters |
| FLUX.2 klein 4B / 9B, FLUX.2 pro Preview | **~2000 characters** |

So a long, richly detailed prompt is worth writing for the FLUX models and largely wasted on the Stable Diffusion models — they are not ignoring your detail, they are never shown it. The counter measures your **longest prompt plus the style suffix**, because that combination is what actually gets sent, and it re-grades itself when you change model.

**`prompting.md`** covers what to do about it — chiefly that the style suffix is the part you lose, since it is appended last.

These are advice, not limits. Nothing in the program cuts your text — some prompts tokenize better than the estimate suggests, and the counter would rather warn you early than trim something you meant to keep.

## Choosing a provider

### Pollinations — zero setup

Pick this to start generating within ten seconds of opening the program. No account, no key, no configuration. Two models: **FLUX.1 Schnell** and **DreamShaper 8 LCM**.

The catch is throughput. Pollinations allows **exactly one request at a time per IP address** — this was measured, not guessed, and an API key does not change it. In practice you get roughly one image every 15 to 45 seconds. That is fine for a handful of images and unusable for a batch of five hundred. The program clamps concurrency to 1 automatically so you don't spend your retry budget on rejections.

If you have a Pollinations API key you can paste it in; it raises your quota and shortens the gap between requests, but it does not lift the one-at-a-time limit.

**Pollinations images are capped at about 1024x576.** This was measured: ask for anything larger and the service quietly scales it down to fit, reporting success with no error and no warning. The program now only ever asks for sizes it will actually deliver, so the sizes offered here are smaller than on Cloudflare — 1024x576 for 16:9, 768x768 for square. That cap is the real reason Pollinations is a zero-setup lane rather than a main one.

### Cloudflare Workers AI — the main provider

Faster, higher quality, and still free for the default models. It needs two values pasted into the program once, and it gives you **thirteen models**.

They come in two groups, and the difference matters because they are paid for in completely different ways.

#### The five original models — free daily allowance

Cloudflare gives every account **10,000 free neurons per day** — neurons are Cloudflare's own name for their compute credit — resetting at midnight UTC. These five models draw on that allowance, and three of them were measured not to touch it at all.

| Model | Cost per 1000 images | Notes |
|---|---|---|
| **SDXL Lightning** | **Free** | The default. Fastest — roughly 2–3 seconds per image. |
| **SDXL Base 1.0** | **Free** | Slower, because it takes more refinement passes. Sometimes more detailed. |
| **DreamShaper 8 LCM** | **Free** | Fast, and leans more photographic than the two SDXL models. |
| **FLUX.2 klein 4B** | $1.72 | The best quality here for the money, by a distance — and free for roughly the first 75 images a day. |
| **FLUX.2 klein 9B** | ~$15–19 | Slower and roughly ten times klein 4B's price for a modest gain. Free for only about 7 images a day. |

The three Stable Diffusion models were **measured at zero cost** — fifteen test images across all three billed nothing at all. They aren't "free tier until you hit a cap"; on Cloudflare's pricing they simply don't bill.

klein 4B costs **$1.72 per 1000 images at the Standard tier** — under a fifth of a cent each. In practice a small batch often costs nothing: unlike the three free models it genuinely consumes the daily allowance, and it was measured billing about 132 neurons per 1536x864 image, which works out at roughly **75 free images a day** at that size before the price applies at all. **klein 9B is far hungrier — about 1412 neurons an image, or roughly 7 a day free.** That is more than ten times klein 4B per image, not the two times its name suggests, which is the main reason 4B is usually the better buy. Both figures were measured directly against Cloudflare's usage API; the Cost Calculator on the Provider tab shows the estimate for your chosen size.

#### The eight AI Gateway models — prepaid credit

These are also Cloudflare models, reached through its **AI Gateway**, and they use the same account and the same API token. What is different is the money: they are **not covered by the free daily allowance at all**. They are paid for out of a prepaid credit balance you top up in advance, and each one charges a flat price per image regardless of size — except Nano Banana 2, which is the one model where a bigger size genuinely costs more.

**You must load credit before any of these will run.** See [Loading AI Gateway credit](#loading-ai-gateway-credit) below.

| Model | Cost per 1000 images | Notes |
|---|---|---|
| **P-Image** | $5.00 | Very fast, and it automatically expands your prompt with extra detail. Its largest 16:9 image is 1280x720. |
| **Krea 2 Medium Turbo** | $15.00 | The strongest here at anime, painting and illustration rather than photorealism, and the best of the expensive models for the money. One fixed size. |
| **Krea 2 Medium** | $30.00 | Double Turbo's price for a slight gain. Worth it when every image in a batch must look consistent; otherwise pick Turbo. |
| **FLUX.2 pro Preview** | $30.00 | Pick this for its adjustable content filter, not its pictures — Krea Turbo looks better for half the price. |
| **Recraft V4.1 Utility** | $35.00 | A solid all-rounder and the better of the two Recrafts. 16:9 is 1344x768. No seed, and the only family that bills a rejected request — see below. |
| **Recraft V4.1** | $35.00 | Same price and sizes as Utility, slightly weaker overall. Pick it for art direction, composition and readable text in the image. No seed. |
| **Nano Banana 2 Lite** | $34.00 | Google's model, and the best quality for the money of the expensive options. 16:9 is 1344x768. No seed. |
| **Nano Banana 2** | $67 / $101 / $151 | The best quality available here and by far the dearest — **the price depends on the size tier you pick.** Suits a few special images, not a whole batch. No seed. |

### Reading the cost markers

Each model in the dropdown carries a marker showing roughly what it costs, so you can judge a model without doing arithmetic:

| Marker | Band | Cost per 1000 images |
|---|---|---|
| *(none)* | **FREE** | Nothing |
| `$` | **LOW COST** | Up to $5 |
| `$$` | **MEDIUM COST** | $5 to $20 |
| `$$$` | **HIGH COST** | $20 to $50 |
| `$$$$` | **EXTREME COST** | Over $50 |

The marker is a browsing aid graded at a fixed reference size. The Cost Calculator is the real number, and it grades whatever size you have actually chosen — which matters on Nano Banana 2, where changing the tier can move the model between bands.

### When a failure costs money

Most failures cost you nothing. A rejected request is normally refused before anything is generated, and Cloudflare does not bill for it — that is how this program's model settings were verified without spending anything. There are three exceptions worth knowing about, because in each one you are charged for something you cannot use.

| Situation | Charged? | What the program does about it |
|---|---|---|
| **A malformed request** — a size or setting a model won't accept | **No**, on twelve of the thirteen models. Refused before generating. | Nothing needed. |
| **A malformed request on either Recraft model** | **YES.** Recraft is the one model family that accepts the request, bills it, and *then* fails. | The program only ever sends sizes from Recraft's own published list, and checks them before the batch starts. You should not be able to trigger this. |
| **A blocked prompt** (the content filter refuses it) | **Assume yes, on any paid model.** The request is well formed, so the image is generated and billed before it comes back blank. Not measured directly, but the request reports success, which suggests it ran. | Marked as blocked and never retried, so you pay at most once rather than repeatedly. |
| **A download that fails after the image was made** | **Yes** — it was generated and billed before the transfer failed. | Retried, because the image is already paid for and retrying is the only way to get it. |

**The practical advice is the same in every case: use Dry Run.** It lists the whole batch, validates every setting against the model you picked, and costs nothing, because it makes no API calls at all. It is specifically designed to catch the mistakes that would otherwise be expensive.

**The blocked-prompt row is the one that can actually cost you real money, and it is the only one the program cannot prevent.** The other three are either impossible to trigger or worth retrying; a refusal is a well-formed request that gets generated, billed, and handed back as a black frame. Cloudflare also runs a check over the finished **image**, not just your text, so a perfectly ordinary prompt can be flagged on the strength of a frame you never see — and military, weapon and combat subjects draw more of these than most.

On a batch this compounds. Five hundred prompts sharing one style suffix that trips the filter means five hundred billed refusals, and because each is marked blocked rather than failed, the run finishes and reports itself as clean. Three habits make this a non-problem:

- **Test new prompt wording on a free model first.** SDXL Lightning uses the same content filter and costs nothing to be refused by.
- **Use the Generate slider** to run the first five images of a batch before committing the other 495.
- **On P-Image and FLUX.2 pro Preview, try the content filter setting** before rewriting anything — those two are the only models here that let you ask for a more permissive setting.

If prompts are being refused in numbers, fix the wording rather than re-running the batch. See [Failed vs. blocked](#failed-vs-blocked) below for what a refusal looks like.

### What each model can't do

Not every model accepts every control. Nothing is hidden when you pick one — the controls that don't apply switch themselves off and say why — but it is worth knowing before you plan a batch around a feature.

| | Models |
|---|---|
| **Accept a negative prompt** | SDXL Lightning, SDXL Base, DreamShaper only. Everything else takes a guidance value or nothing. |
| **Accept a seed** (so two runs can match) | Everything **except** both Recraft models and both Nano Banana models. |
| **Have a working size tier** | Everything **except** both Krea models, both Recraft models and Nano Banana 2 Lite, which each render at one fixed size. |
| **Change price with the tier** | Both klein models and Nano Banana 2. Everywhere else the tier changes pixels, not money. |

If reproducibility matters to you — regenerating an image later, or making variations of one that came out well — the seed row is the important one. On a model that accepts no seed there is no way to make two runs match, by any means.

### Guidance and Steps — what the defaults are and why

The **Guidance** and **Steps** boxes on the Provider tab are optional. Leave them empty and the program sends each model the value it was measured to want; you only need this table if you're curious what "empty" actually means, or if you want to experiment.

| Model | Guidance (CFG) | Steps |
|---|---|---|
| SDXL Lightning | 8 | 8 — try 20 if 8 looks a little sharp/crunchy for your taste |
| SDXL Base 1.0 | 8 | 20 — this model wants its full step budget |
| DreamShaper 8 LCM | 1 | 8 (minimum — fewer steps produces warped, duplicated subjects) |
| FLUX.2 klein 4B / 9B | 1 (per Black Forest Labs' own guidance-distilled model card) | fixed at 4, not adjustable |

These aren't guesses — they came out of a same-prompt, same-seed comparison across every combination for each model, keeping whichever setting actually looked best rather than just "didn't break." Guidance controls how strictly an image follows your prompt: too low and Stable Diffusion output can look soft or smeary; too high and it gets harsh, oversaturated, or (on DreamShaper specifically) badly broken. Steps is how many refinement passes the model runs — DreamShaper's distilled sampler needs at least 8 to avoid warped results, while SDXL Base wants its full 20 to look its best.

If you type a value into either box yourself, that overrides the automatic one for every image in the batch.

**Eight of the thirteen models accept neither setting.** All eight AI Gateway models take no guidance value, and only the Stable Diffusion models take a step count. When you select one of those, the boxes switch off and show the value actually being used, or `n/a` where there is no such setting — and anything you had typed is kept, ready for the next model that does accept it.

### The content filter setting

Two models let you adjust how strict their content filter is: **P-Image** and **FLUX.2 pro Preview**. Nothing else here offers the option.

This exists because of a genuinely annoying failure mode. When a content filter refuses a prompt you do not get an error — you get a completely black image and a report of success (see [Failed vs. blocked](#failed-vs-blocked) below). In a batch of five hundred run overnight, a wrongly refused prompt is a slot you lose and only discover the next morning. On these two models the setting gives you something to do about it other than rewriting a prompt that was fine.

It is set to the **permissive** end by default, which asks each model for the loosest setting it itself publishes. It does not switch moderation off, it is not a way around anybody's policies, and the provider still applies its own limits — a genuinely refused prompt is still refused. Stricter settings are one dropdown away if you prefer them.

### Prompt expansion

The two Krea models expand your prompt before generating, filling in lighting, colour and composition detail of their own. This is not a quirk to switch off — it is what Krea is built around, and a large part of what you are paying for when you choose it.

How much it changes depends on how much you wrote. A short prompt gets expanded a great deal, which is where the feature earns its keep. A long, detailed prompt like the ones this program is usually fed gets *polished* rather than rewritten: the model makes its own choices about light and composition, but your specifics survive.

The program sends **Moderate** by default, which is Krea's own default. In our testing that was the difference between a muddled scene and a clean one on an identical prompt, so it is worth leaving alone unless you have a reason not to.

Set it to **Off** when you want your words used verbatim — for instance when a style suffix must stay identical across a batch and you would rather have that than the model's polish. **Heavy** takes real liberty with style and mood: good for exploring from a short prompt, risky across a batch where consistency is the point.

---

## Getting your Cloudflare keys

You need **two values, not one**. Both are free and take about three minutes.

**1. Your Account ID**

Log in at [dash.cloudflare.com](https://dash.cloudflare.com). The account ID is a 32-character hex string visible in the URL of your dashboard, and on the right-hand side of most account pages. Copy it.

**2. Your API Token**

Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens) → **Create Token** → use the **"Read all resources"** template → **Continue to summary** → **Create Token**. Copy the token immediately; Cloudflare only shows it once.

**Use the "Read all resources" template, not the Workers AI one.** A read-only token is enough for everything this program does — that was tested directly against the five free-allowance models, not assumed.

For the eight AI Gateway models, Cloudflare's own documentation is inconsistent about what is needed. Its [REST API page](https://developers.cloudflare.com/ai-gateway/usage/rest-api/), which documents the exact endpoint this program calls, says an **Account → Workers AI → Read** token is sufficient. Its [Get Started page](https://developers.cloudflare.com/ai-gateway/get-started/) additionally asks for **AI Gateway Read and Edit** — but that page is written around creating and managing a gateway by hand, which this program never does. The "Read all resources" template covers every read permission in both lists, so it is the safe choice either way.

If a gateway model ever fails with a permissions error rather than a credit error, the fix is to add **AI Gateway → Edit** to your token. The program reports those two failures differently, so you will be able to tell which one you have hit. The program only ever reads: it verifies your token, then asks the AI endpoint to generate an image. Generating an image is a `POST`, but it is *inference* — it creates no resource and changes no setting on your account. A read-only token means that if the token ever leaks, nobody can alter anything you own with it.

**3. Paste them in**

Open the **Provider** tab, paste both values into the **API Keys** box, and click **Save Keys**. Then click **Check Credentials** to confirm they work.

They're saved to `credentials.json` next to the program, restricted to your Windows user account. **No environment variables, no restart, no system configuration.** The keys are never written to `config.json`, never stored in the job database, and never included in any image metadata.

If you already use environment variables (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `POLLINATIONS_API_KEY`), those still work and take priority over the saved file. That's there for scripted setups; you don't need it.

> **Before sharing this folder with anyone, delete `credentials.json` and `config.json`.** They sit beside the exe and they contain your keys.

---

## Loading AI Gateway credit

**Only needed for the eight AI Gateway models.** If you are using the free models or Pollinations, skip this entirely — you never need to enter a payment method at all.

The eight AI Gateway models are not covered by Cloudflare's free daily allowance. They draw on a **prepaid credit balance** that you top up in advance, and until there is credit on the account they will not run: the request comes back refused and the program reports the batch as out of quota rather than retrying it.

**Three things to know before you start, because they surprise people:**

- **You must add a credit or debit card.** PayPal appears as an option but is **not** accepted for this — Cloudflare requires a card as the primary payment method, and a PayPal-only account will be turned away after you have already gone through the motions.
- **The minimum top-up is $10.** Not $5, and not an arbitrary amount — the field accepts **$10 to $50**.
- **There is a 5% purchase fee** on top. $10 of credit costs **$10.50**; $100 costs $105. That is Cloudflare's fee, not this program's.

**Do it in this order.** Going straight to the credits page first is what makes this confusing, because it sends you away to add a card and then back again:

1. **Set up your payment method first** — go to [dash.cloudflare.com](https://dash.cloudflare.com) → **Billing** (in the left sidebar, or the account menu) and add your credit or debit card.
2. **Then go to the AI Gateway credits page** — **AI** → **AI Gateway** → **Credits**, or use the **Check credits** link beside the model dropdown in the program, which takes you straight there whenever a gateway model is selected.
3. **Click Manage / Top-up credits** and enter an amount between $10 and $50.
4. Optionally set up auto top-up, which recharges automatically when the balance falls below a threshold you choose. Leave this off unless you want it — it is a standing charge on your card.

Credit does not expire, so the minimum $10 is a one-off that will last a long time at these prices: at $5 per 1000 images on P-Image, $10 is 2000 images.

**If you would rather follow screenshots**, the `promo/!cloudflare info/` folder in this download has a picture of each step, for both the API token and the prepaid credit setup.

*The card requirement, the $10–50 range and the 5% fee were all confirmed on a real account on 2026-09-06. The auto top-up detail is from Cloudflare's documentation.*

---

## Size, quality and cost

Cloudflare bills the five original models per 512×512 tile, which means their cost moves **in steps, not smoothly**. Any size inside the same tile count costs exactly the same. This has a pleasant consequence: the obvious sizes are wasteful. At the Standard tier, 16:9 gives you **1536×864 — 44% more pixels than 1280×720 for exactly the same price.** Every size the program offers is the largest exact-ratio size that still fits its tile bracket, so you're never leaving pixels on the table.

There are five aspect ratios (16:9, 3:2, 1:1, 2:3, 9:16) and three size tiers — **Draft**, **Standard** and **High**. Standard is the default and what most batches should use; Draft is for while you are still working out your prompts.

**What the tier does depends entirely on which model you picked**, so rather than describing it in the abstract the dropdown now tells you: each option shows the exact size it will produce, and on the models where the tier changes the bill, the price too. The big size figure under the two dropdowns is always the size you are actually going to get.

Three things are worth knowing in advance:

- **On most models the tier changes size only, not price.** All eight AI Gateway models except Nano Banana 2 charge a flat price per image, so Draft costs exactly what High costs. Picking a smaller size to save money there saves nothing.
- **On Nano Banana 2 the tier is a price control.** $67 per 1000 images at Draft, $101 at Standard, $151 at High — a High batch costs more than twice a Draft one. The dropdown shows this as you choose.
- **Five models have no tier at all.** Both Krea models, both Recraft models and Nano Banana 2 Lite each render at one fixed size, so the control switches itself off and says why.

**High tier is only sensible on the FLUX.2 klein models.** The Stable Diffusion models are trained around 1024px and fall apart above it: duplicated structures, drifting geometry, ugly edges. **Their Draft and Standard sizes are now capped to stay inside that limit** — Standard 16:9 is 1024x576 on those three, rather than the 1536x864 the larger models use — so the default never asks for something they cannot render well. High still offers the big sizes if you want them, and warns you when you pick one. The warning is set per model, so it does not fire on models like Nano Banana 2 that render large sizes natively and perfectly well.

A useful workflow on the tile-priced models: generate at Standard and batch-downscale afterwards in a tool like XnConvert. A downscaled 1536×864 beats a natively generated 1280×720, and costs the same. That trick only applies where cost moves in tile steps — on a flat-priced model there is no spare headroom to exploit, which is why the program only shows a tile count where it is genuinely a billing fact.

The **Cost Calculator** on the Provider tab updates live as you change model, ratio and tier, so the price of a decision is visible at the moment you make it.

### About "images remaining today"

This applies only to the five original Cloudflare models, which draw on the free daily allowance. The three free Stable Diffusion models genuinely bill zero neurons, so there is no daily cap to show for them. For the klein models, the program shows an **estimate** built from a measured neuron rate (checked directly against Cloudflare's own usage figures), not a guess — but it is still labelled an estimate, since it assumes that rate holds at every size the same way the dollar price does. For your exact, live usage, check Cloudflare's own dashboard; the Provider tab has a link straight to it.

The eight AI Gateway models have **no free daily allowance at all**, so there is no "remaining today" figure for them — what you have is whatever prepaid credit is on the account. The same link becomes **Check credits** when one of those models is selected.

---

## Using a reference image

The style suffix describes a look in words. A **reference image** shows the model one directly — and some looks are much easier to show than to describe. Drop in a sprite, a painting, a photo or a piece of concept art, and every prompt in the batch is generated to match its look.

Find it in **Style Reference Image** on the Provider tab. Tick the box, choose a file, and a small preview appears beside a line telling you exactly what will be sent.

**It works on five models:** FLUX.2 klein 4B, FLUX.2 klein 9B, FLUX.2 pro Preview, Nano Banana 2 Lite and Nano Banana 2. The others accept no such thing at all — that is a limit of those models, not of this program — and when one of them is selected the control greys out and says so rather than quietly ignoring your image. **klein 4B is the one to start with:** it is free for roughly the first 75 images a day.

Things worth knowing:

- **PNG, JPEG and WebP all work.** So does any size and almost any shape.
- **No particular size is needed.** The program resizes your image to about 1 megapixel, which is what these models are happiest with. Anything bigger is scaled down; anything smaller than 64 pixels on a side is scaled up, because the models reject images below that outright.
- **Pixel art is scaled up with nearest-neighbour**, which keeps the hard pixel edges crisp instead of blurring them into mush. A 16×16 sprite becomes a clean 1024×1024. The program works out which kind of image you gave it automatically; if it guesses wrong, the **Resizing** dropdown lets you say.
- **It never touches your file.** All the resizing happens on a copy in memory.
- **Very long, thin images are refused.** A sprite animation strip laid out in a row is too far from square for these models to use. Crop out a single frame, or tile the strip into a grid — a varied grid is a better style reference anyway.
- **Your reference does not have to match your output shape.** A square sprite guiding a 16:9 batch is perfectly normal: the reference carries the *style*, the aspect ratio you chose carries the *framing*. The program mentions the difference and carries on.

**The Influence dropdown** adds a short sentence to the end of every prompt, so you do not have to type it into each line: **None** — *"No influence from image 0."*, **Subtle** — *"Subtle influences from image 0."*, **Medium** — *"Medium influence from image 0."*, **Heavy** — *"Heavy influence from image 0."*, **Exact** — *"Exact style as image 0."* On Nano Banana and FLUX.2 pro the wording says *"the reference image"* instead, since only klein is documented to number its inputs. Every level, None included, adds its sentence whenever a reference image is in use. It shows in the Prompts tab preview and counts towards the prompt length.

Set your expectations for it, though: **the reference image does most of the work on its own**, and no model offers a real "strength" setting — this is wording, not a weight.

You can also write it yourself, anywhere in a prompt: on the klein models the reference is **image 0** — for example *"a mountain village at dusk, in the style of image 0"*. If you do, leave Influence off or the two sentences may compete — None still adds its own.

Changing the reference image counts as changing the picture, so a re-run generates fresh images rather than skipping the ones already on disk. Swapping in a different file under the same filename works too — the program looks at the picture, not the name.

On the command line: `--reference-image PATH`, plus `--reference-resample auto|nearest|lanczos` if you want to overrule the automatic choice, and `--reference-influence none|subtle|medium|heavy|exact` for the sentence above. `dry-run` shows exactly what would be sent, including the resize, before anything is spent.

---

## Running a batch

The **Run** tab has five buttons.

**Dry Run** lists every job it would create, the filenames it would write, and the total estimated cost — with **zero API calls**. Given that a mistyped setting could mean an unwanted bill, run this first. Every time.

**Start Batch** begins generating. You get live counts of finished, failed, blocked and in-flight jobs, elapsed time, running cost estimate, the prompt currently being worked on, and a log.

**Pause** stops new images from starting; requests already in the air are allowed to finish. **Resume** picks back up. **Cancel** stops the batch and keeps everything finished so far.

**Retry Failed** re-queues jobs that failed for temporary reasons. It deliberately does *not* retry blocked ones — see below.

**Regenerate**, below the log, generates the images from your last run again, replacing what is already in the folder. Use it when *nothing* changed and you want another attempt — a different random seed, or results that just were not good. It covers whatever your current settings would generate, so if the Generate slider is set to 5 of 100, it redoes those 5. You do **not** need it after changing the style suffix, model or size: those change the file names, so a normal Start generates them anyway. On a paid model those images are charged again, so it asks for confirmation first. It stays greyed out until you have run a batch, since until then there is nothing to redo.

### Resuming, and not wasting work

Batch state lives in a small SQLite database in your output folder. Close the program, reboot, come back tomorrow — point it at the same prompt file and output folder and press Start, and it skips everything already finished and carries on. Finished images are never regenerated by accident.

One thing worth knowing, because the name misleads: the **Replace files** checkbox on the Provider tab (previously called "Overwrite") does *not* redo finished images. It only decides what happens when an image being generated *right now* would land on a filename that already exists — off, it saves alongside as `..._2`; on, it replaces. Ticking it and pressing Start on a completed batch does nothing at all, because there is nothing left to run. **Regenerate**, on the Run tab, is the control that redoes finished work.

### The log file

Everything shown in the Run tab's log is also appended to `log.txt` in your output folder, alongside the images and the database, so you can look up what happened after closing the program. It is never cleared or rotated automatically — delete it yourself if it grows too large.

### Failed vs. blocked

Two different things, treated differently:

**Failed** means something went wrong that might not go wrong again — a timeout, a network blip, a rate limit. These are retried automatically with exponential backoff, and **Retry Failed** will have another go.

**Blocked** means the provider's content filter refused the prompt. This is worth understanding because the failure mode is sneaky: a filtered prompt comes back as `HTTP 200 OK` with a **completely black image** and no error of any kind. A tool that didn't check would report a flawless 100% success rate and hand you a folder of black rectangles. This program decodes every image it receives and rejects any single flat colour as a **permanent** failure, so blocked prompts are never retried — retrying wouldn't help. Rewrite the prompt instead.

On a paid model you should assume a blocked prompt still costs you, since the request reported success (see [When a failure costs money](#when-a-failure-costs-money)). That is why they are never retried, and why it is worth testing new prompt wording on one of the free models before committing a large paid batch to it.

### Being a good citizen

Concurrency defaults to 2 with a deliberate one-second gap between requests, and `HTTP 429` is honoured with proper backoff. These free tiers are a courtesy, not an entitlement, and hammering them is how they stop being free for everyone. You can raise the concurrency, but please have a reason.

---

## The command line

`cli.py` is a fully supported second front end onto the same engine — not a test harness. If you want to run batches from a scheduled task, a script, or a machine with no display, use it. It needs Python 3.13 with `httpx` and `pillow` installed.

```
python cli.py models                                              list models, prices and sizes
python cli.py check                                               verify credentials work
python cli.py estimate --model klein4b --ratio 16:9 --count 500   what would 500 images cost?
python cli.py dry-run prompts.txt -o out --style style.txt        job list, zero API calls
python cli.py run     prompts.txt -o out --style style.txt        generate
python cli.py run     prompts.txt -o out --limit 5                 only the first 5 prompts
python cli.py run     --prompt "a lighthouse in a storm" -o out   one image, no prompt file
python cli.py resume  prompts.txt -o out                          continue where it stopped
python cli.py retry-failed prompts.txt -o out                     another go at the failures
python cli.py status  -o out                                      what happened in past batches
```

Useful flags on `run`: `--model`, `--ratio`, `--tier`, `--seed`, `--concurrency`, `--delay`, `--format`, `--overwrite`, `--limit N` (the command-line equivalent of the Generate slider — only the first N prompts, for trying a style before committing to the whole file), and `--prompt "some text"` (the equivalent of the Single custom prompt tickbox — generates one image from the text you give it, and takes the place of the prompt file argument). Run `python cli.py run --help` for the full list. It reads the same `credentials.json` the GUI writes, so if you've set the keys up once in the interface the CLI already works.

---

## Image licensing

You own what you generate and can use it commercially. Cloudflare treats your prompts and outputs as your content.

One honest note: **FLUX.2 klein 9B** carries a FLUX Non-Commercial licence. That licence restricts *serving the model* — running it as a service yourself — not the images it produces. Generating through Cloudflare's hosted endpoint and using the results commercially is fine. Every other model here permits commercial use of outputs without qualification: Apache 2.0 for klein 4B, OpenRAIL-style for the Stable Diffusion family, and for the eight AI Gateway models the same Customer Content terms that cover the rest of Cloudflare — the images are yours.

This program is a client that calls a hosted API. It never downloads, redistributes or runs the models themselves, so none of those licences place any obligation on you for using it.

---

## Troubleshooting

**"Check Credentials" fails.** Confirm you copied the account ID and not the zone ID — the account ID is on your dashboard's account page. Re-create the token if you pasted it after navigating away, since Cloudflare shows it only once.

**Everything comes back blocked.** Your prompts are tripping the content filter. Rewrite the wording; retrying identical text will produce the same refusal.

**Images look duplicated or the geometry is warped.** You're on the High tier with a Stable Diffusion model — Draft and Standard are capped to sizes those models handle properly, so High is the only tier that can do this. Drop back to Standard, or switch to klein 4B, which renders the large sizes natively and is free for the first several dozen images a day.

**The batch seems frozen on Pollinations.** It isn't — that's the one-request-per-IP limit, which works out around 15 to 45 seconds per image. For anything sizeable, use Cloudflare.

**A paid model fails immediately with an out-of-quota or payment error.** You have selected one of the eight AI Gateway models and the account has no prepaid credit on it. Those eight are not covered by the free daily allowance — see [Loading AI Gateway credit](#loading-ai-gateway-credit). The **Check credits** link beside the model dropdown goes straight to the right page.

**A paid model's images come out smaller than I expected.** Several of the AI Gateway models render at their own fixed sizes rather than the program's tiers — P-Image tops out at 1280x720 for 16:9, and the Recraft and Nano Banana Lite models at 1344x768. The large size figure under the dropdowns always shows what you will actually get, before you start.

**The seed setting is greyed out.** Both Recraft models and both Nano Banana models accept no seed at all. That is a limit of those models rather than of this program, and it means two runs of the same prompt cannot be made to match on them. Pick a different model if reproducibility matters.

**A batch restarted and did nothing.** It found everything already finished and skipped it, which is correct. If you changed the style suffix, model or size, that is *not* what happened — those change the file names, so the new versions generate on a normal Start. If nothing changed and you want the images made again anyway, use **Regenerate All**.

**The Help button says the guide is missing.** `guide.md` needs to be in the same folder as the exe. Restore it from the zip.

---

### DreamShaper used to give black or bright green images — fixed

Older versions of this program left DreamShaper 8 LCM's guidance value unset, which meant it ran with a setting meant for other Stable Diffusion models. On an LCM model like this one that produced an occasional all-black frame (reported as a content block, since that's exactly what one looks like) or an image with its blue channel crushed into a lurid green-and-black mess — most often on green outdoor scenes, though it was never really about the scene.

The program now sends DreamShaper the guidance value it actually needs automatically; you don't need to do anything. If you're on an old build and still seeing this, update, or switch to SDXL Lightning in the meantime — the same prompts render correctly there.

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
