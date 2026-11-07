# Promotion Plan — Batch AI Image Generator

Everything needed to launch this: where to post, why there, and ready-to-paste copy for each place.

> **One caveat up front.** I could not open Reddit from the machine this was written on — reddit.com, the JSON API and old.reddit are all blocked here, and web searches only returned generic third-party "Reddit self-promotion rules" articles rather than the actual sidebars. The subreddit recommendations below are based on what those communities are generally known for, and each one carries a note about its known posture. **Check each subreddit's sidebar and rules yourself before posting** — that verification step is genuinely still owed, and posting blind is how a launch turns into a ban.

---

## The strategy

### What is actually being sold here

Not "an AI image generator" — there are thousands, and most of them are prettier than this one. What this program has is a much narrower and much sharper pitch: **it does a thousand of them unattended, and tells you what the run costs before you press go.**

Everything about the marketing should lean on that. The people who want this are the ones who have already hit the wall where a web UI stops being viable: someone generating a texture set, a card game's art, a hundred game backgrounds, a batch of blog headers. They are not looking for a model. They are looking for the thing that runs the model a thousand times while they sleep.

The three hooks, in order of strength:

1. **It's built for batches that actually finish.** Crash resume, retry logic, per-image metadata, cost known in advance. The unglamorous parts nobody puts in a demo video and everybody needs at image 400. This is the lead, because it is the thing nothing else does well.
2. **Running it can cost nothing.** Three Stable Diffusion models on Cloudflare that bill nothing — measured, not promised — plus a keyless provider needing no account at all, and twelve paid models above them for when quality matters. **Say "the generation is free", never "the program is free".** The program is $8.
3. **It catches the black-image trap.** Content-filtered prompts come back as `200 OK` with an all-black frame and no error at all. Tools that don't check report perfect success and hand you a folder of black rectangles. This one decodes every image. That detail is *the* credibility line — it's specific, it's verifiable, and it signals that the author actually ran big batches instead of shipping a demo.

### Positioning against the obvious question

Someone will ask "why not just use ComfyUI / A1111 / Fooocus?" The answer is honest and short: those are local generators that need a real GPU. This is a cloud batch runner for people who don't have one — a laptop with 4 GB of VRAM can drive this perfectly well, because the generation happens elsewhere. It's a different tool for a different constraint, not a competitor. Say that plainly rather than dodging it; the honesty reads well and it pre-empts the top comment.

### The business model — SETTLED: paid at $8

**This is decided, not a recommendation.** The program sells on itch.io at **$8**, and it already has paying customers. An earlier draft of this file argued for free-with-a-tip-jar; that argument lost, and the reasoning that beat it is recorded here so it does not get relitigated.

**Why paid:**

- **A paywall filters abuse of somebody else's service.** This drives free and cheap tiers on external APIs that can be withdrawn if enough people hammer them. A price is a remarkably effective filter against the people who would ruin that for everyone, and protecting the free lane is worth more than the marginal reach a $0 price would buy.
- **"Someone could build this in a weekend" undersells the required knowhow.** That claim assumes the reader already has the tooling, the API knowledge and the design judgement. Nobody else has shipped a batch AI image generator this approachable to a layperson. The measured knowledge inside it — the tile-optimal size tables, the black-image detector, the read-only-token finding, the Pollinations cap — is the product, and it was expensive to acquire.
- **Eight dollars is not a barrier to the people who want this.** Anyone generating hundreds of images has already decided the problem is worth solving. $8 filters tyre-kickers, not customers.

**What stays free regardless, and must be said clearly in every piece of copy:** the *generation* is free. Three Cloudflare models bill nothing, Pollinations needs no account, and the paid models are opt-in. The distinction to keep sharp is **the tool costs $8; running it need not cost anything more.** Never write copy that reads as "this software is free" — that was the flaw in the first version of this file and it is the flaw in the current promo images.

**The source still ships with the download**, and that is unchanged by the price. It is what answers "why should I paste an API token into a stranger's exe", which is the single biggest conversion barrier here. A customer who wants to read `utils/credentials.py` and confirm where their token goes can do so.

**Where the free-tool arguments still bite, and what to do about them:** the communities most allergic to a paid link are exactly the ones this lands hardest in. The answer is not to drop the price but to **lead with the problem and the findings, not the product**. A post about the tile-pricing step function or the `200 OK` black-image behaviour is welcome anywhere; a post about a paid Windows tool is not. Give away the knowledge freely and let the tool be the footnote — see the copypastas below, which are written that way deliberately.

**Revisit the price** only with evidence: if sales stall at a price point people mention explicitly, or if a genuinely expensive feature with an ongoing cost behind it ever ships.

### Where the traffic actually comes from

The release doc's instinct is right: prioritise **persistent, searchable places people browse on purpose** over feeds that scroll away in six hours.

**Persistent (most of the long-term value):**
- **itch.io** — indexed, browsable by tag, and the single canonical download link. Everything else points here.
- **GitHub** — searched directly for "batch image generation", picked up by topic pages, and it's where the credibility of the code lives.
- **A well-tagged YouTube video** — a two-minute screen recording will be found by "batch AI image generation" searches for years. This is the highest-effort item and probably the highest return.
- **alternativeto.net** — people land there specifically looking for a tool that does one thing. Free entry, permanent listing.

**Burst (spikes, then gone — but the spike seeds the persistent stuff):**
- Reddit posts. Big day-one number, near-zero tail.
- Discord servers.

Do the persistent listings *first*, so that when a Reddit post does spike, everyone who follows the link finds a finished page rather than a placeholder.

### Timing and sequence

1. Publish the itch page and the GitHub repo. Both complete, both with screenshots.
2. Record and upload the YouTube video. Link it from the itch page.
3. Post to the AI-tool subreddits — the most receptive audience, and the one that will find real bugs.
4. Wait a few days, absorb the feedback, ship a fix if one is needed.
5. Then post to the gamedev-adjacent places, where "I used this to generate 200 game backgrounds" is a far stronger post than "I made a tool."

That last point is worth taking seriously: **the strongest post you can make about this program is not about this program.** It's a showcase of a batch of images you actually generated with it, with the tool mentioned as how you did it. Once the Commander Wars backgrounds exist, that's the post.

### Practical rules for every post

- Lead with the problem, not the feature list. "I kept losing hours babysitting a browser tab to generate 200 images" beats any description of the software.
- Say the price and the free-generation part explicitly and early, in that order. Burying an $8 price and having a reader discover it at the download link is how you lose them; leading with it and immediately saying the generation itself costs nothing is how you keep them.
- Never post a bare link. Every platform's rules and every platform's audience punish it.
- Reply to every comment for the first 48 hours. Engagement decides whether the post lives.
- Be upfront that it's Windows-only. Getting corrected on that in the comments is worse than saying it yourself.

---

# Copypastas

## itch.io

**Name of project**

```
Batch AI Image Generator
```

**Subtitle (100 characters max)**

```
A text file of prompts goes in, a folder of images comes out. Unattended, resumable, cost-aware.
```

*(99 characters.)*

**Long description (markdown)**

```markdown
# Batch AI Image Generator
*A text file of prompts goes in, a folder of images comes out.*

This is a downloadable windows program to mass-create AI images using free or low-cost AI image generators hosted by [Cloudflare.com](http://cloudflare.com/) or [Pollinations.ai](http://pollinations.ai/).

A text file of prompts goes in, a folder of images comes out.

Write your image ideas one per line in a `.txt` file. Point this program at it. Come back to a folder of finished images, each with its full generation details saved beside it.

You have a list of image ideas — one hundred, one thousand — and you want all of them rendered without babysitting a web page. This tool takes that list as a plain \`.txt\` file, appends a shared style description to each line, sends them to a cloud image API, and downloads every result into a folder with a \`.json\` metadata file beside it.

This program will essentially save you hours of time and manual labor, especially on tasks that are mundane like backgrounds, textures, sprites, etc.

**Prompting skills are still necessary for good results**, so if you want to learn how to prompt like a pro or want ready prompts by the thousands, check out my text generators too:

[https://itch.io/c/5887279/text-generators](https://itch.io/c/5887279/text-generators)  

It comes loaded with both Free (with Daily limits that reset automatically) and Prepaid high quality models from the best that 2026 offers. It survives crashes, resumes where it stopped, retries what's worth retrying, and tells you exactly what a batch costs before you spend anything.

## Thirteen models, and the ones it starts on cost nothing to run

* **Three Stable Diffusion models on Cloudflare Workers AI that bill nothing** — Dreamshaper 8, SDXL, SD Lightning. Good general purpose models for simpler prompts.
* **A keyless provider (Pollinations)** that needs no account at all — you can be generating within ten seconds of opening the program (albeit slower and lower quality, but its free.)
* Two high quality free models with daily limits: 'FLUX 2 Klein 4B' with ~75 free images per day and 'FLUX 2 Klein 9B' with ~7 free images per day but at very high quality. Additional uses beyond the daily limit costs '$1.72 per 1000 images' for Flux 2 Klein 4B, the most affordable and best quality tradeoff that is available today in 2026 without needing your own GPU.
* **Plus nine more prepaid models with massively boosted quality**, like P-Image, Krea, Recraft v4.1, Flux 2 Pro Preview, and Nano Banana 2/Lite. Every model carries a cost badge — FREE, LOW, MEDIUM, HIGH, EXTREME — so you always know which end of the scale you are on before you press start. You will also be warned before using Prepaid models to be as safe as possible with your prepaid credits you got on Cloudflare's AI Gateway service.

## Features

* **Batch from a plain text file** — reads one prompt per line, blank lines skipped. Notepad and copypasta is all you need to make your prompt lists, no matter how short or long you make them.
* **An optional shared style suffix** appended to every prompt, so you write your art direction once instead of a thousand times. You can either select on of the 90+ pre-included and curated styles I've written for you or you can make your own or edit the existing ones easily!
* **Thirteen models across two providers**, with a **live cost calculator** that updates as you change model, aspect ratio and size tier — and a cost band on every entry in the list.
* **Dry run mode** — the complete job list and total cost with zero API calls. Know before you spend.
* **Crash-resumable.** Job state lives in a SQLite database beside your output. Close it, reboot, come back tomorrow — finished images are skipped, not regenerated.
* **Sidecar metadata** — a `.json` beside every image with the original prompt, the final prompt, model, seed, size, timestamp and cost estimate. Reproducing any image is trivial.
* **Black-image detection.** This one matters more than it sounds: content-filtered prompts come back from the API as `200 OK` with an all-black frame and no error field. A tool that doesn't check reports a flawless 100% success rate and hands you a folder of black rectangles. This one decodes every image and marks flat-colour results as permanent failures.
* **Tile-optimal sizes.** On the models that bill per tile, cost moves in steps rather than smoothly — so at the Standard tier, 16:9 gives you 1536x864, which is **44% more pixels than 1280x720 for exactly the same price**. Every size offered is the largest one that fits its price bracket.
* **Honest about what each model can't do.** Five render at one fixed size, four accept no seed, ten ignore negative prompts. The program says so on the model that has the limit, instead of showing you a control that quietly does nothing.
* **Polite by default** — low concurrency, a deliberate gap between requests, proper 429 backoff. Free tiers are a courtesy and this doesn't abuse them.
* **A command-line front end** onto the same engine, for scheduled tasks and headless machines.
* **Complete suite of tutorials** - so even a layperson can learn to use the program, despite Cloudflare making it difficult with their confusing UI. *shakes fist*
* **Useful bonus materials** - such as curated AI LLM prompts you can use to help create your AI image prompts from an inspiration text, create new style presets or learn the secrets of how to prompt images like a pro - all included!
* **The images you generate are yours**, commercial use included.

## Requirements

Windows 10 or 11, and an internet connection. A potato computer will work fine, the actual image gen happens in the cloud, so this makes mass image generation possible for the rest of us.

You will need a [cloudflare.com](http://cloudflare.com/) account and a optionally a [pollinations.ai](http://pollinations.ai/) account to access their services. This involves creating an API token/key, which is very easy even for a layperson - I've included tutorials to help you every step of the way.

Worth noting that the provided image models are censored and sanitized, so you may likely only create SFW content. Anything related to gore, erotic or banned imagery may return as a useless black square.

There may also be a risk if you try to abuse its rules that you will get banned by the providers, so please use their services respectfully and responsibly.

## Your API keys/tokens are safe

Entered in the program, saved to a file beside it that's restricted to your Windows user. Never written to the config, never stored in the job database, never embedded in image metadata. The guide walks you through creating a Cloudflare token from the **"Read all resources"** template — read-only is genuinely sufficient for everything here, including the paid models, so a leaked token can't be used to change anything you own.

The full source is included in the download, so you can see exactly where your API token goes.

## Feedback and Suggestions are welcome

If you love the batch feature of the program, but wished it supported another AI model that is provided via a known API service, feel free to leave a message in the comments and I might add it if its feasible.

Do note that the best image models are often expensive and can cost a lot even for a handful of images, so make sure you actually would be able to afford using it once its implemented.

I personally try to focus on low-cost solutions that provide the best amount of value for batch operations, but if you have money to burn on those services, I can include them too.

This program itself is a one-time payment only so I only get what you initially paid for and you keep it forever. Any other costs will be rendered by API service providers if you choose to exceed their free plan limits and you deliberately enable billing by usage yourself.

---

## Check out everything else I do: 🚀

Home/Links: [https://linktr.ee/reactorcore](https://linktr.ee/reactorcore)

Releases: [https://reactorcore.itch.io](https://reactorcore.itch.io/)

Blog: [https://www.patreon.com/ReactorcoreGames](https://www.patreon.com/ReactorcoreGames)

Discord: [https://discord.gg/UdRavGhj47](https://discord.gg/UdRavGhj47)

Catalog: [https://reactorcoregames.github.io/](https://reactorcoregames.github.io/)
```

**Tags (10, comma separated)**

```
ai, image-generation, batch, automation, tool, utility, stable-diffusion, flux, gamedev, windows
```

**Suggested itch settings**

- Kind of project: **Tool**
- Release status: **Released**
- Pricing: **Paid**, **$8** — settled, see the business model section above. Not name-your-own-price, not $0.
- Platform: **Windows**
- Upload the 630x500 thumbnail as the cover image, the 1280x720 as the page banner, and all three screenshots to the gallery

> **The promo images need re-rendering before the next upload.** The current cover and thumbnail in `promo/` carry a **"Free"** tag, written when the program was going to be free. It now reads as a claim that the software costs nothing, which is exactly the confusion to avoid. Replace that tag with something that sells the real hook — the batch capability, the 13-model lineup, or "free & paid models" — rather than the price of the program. Text only; the artwork itself is fine.

---

## GitHub

**Description blurb (the top-right info box)**

```
Batch AI image generation from a plain text file — unattended, crash-resumable, with cost known before you spend it. 13 models across Cloudflare Workers AI and Pollinations, three of them free to run. Windows GUI and CLI.
```

**Topics (10, one per line)**

```
ai
image-generation
batch-processing
stable-diffusion
flux
cloudflare-workers-ai
pollinations
python
ttkbootstrap
gui
```

---

## YouTube

A video is very worth making here. Two minutes, screen recording, no face, no talking head needed — the whole product demo is *watching a folder fill up with images*, which is inherently satisfying footage. Show the dry run first (the cost number is the hook), then start the batch, then time-lapse the folder filling, then open a sidecar `.json`. Close on the price: $8 for the tool, nothing for the generation on the default models.

**Title**

```
Generate 1000 AI Images From a Text File — Unattended, Resumable, No GPU Needed (Windows Tool)
```

**Description**

```
A text file of prompts goes in, a folder of images comes out.

I kept losing evenings babysitting a browser tab to generate large sets of images, so I built the thing that does it unattended. Write one prompt per line in a .txt file, point this at it, and come back to a finished folder — with every image's prompt, model, seed and cost saved beside it.

The tool is $8. The generation is free on the models it starts with: three Stable Diffusion models on Cloudflare Workers AI bill nothing at all (measured, not assumed), and the Pollinations provider needs no account whatsoever. Above those sit ten paid models, from $1.72 per 1000 images up to Google's Nano Banana 2, each marked with its cost band so you always know which end of the scale you are on.

WHAT IT DOES
0:00 The problem with generating images one at a time
0:15 Prompt file + style suffix
0:35 Picking a model, and the live cost calculator
0:55 Dry run — see the cost before spending anything
1:10 Running the batch
1:30 Crash resume, retries, and the black-image problem
1:50 Where to get it

FEATURES
- Batch generation from a plain .txt file, one prompt per line
- A shared style suffix appended to every prompt
- Thirteen models across two providers, three of them free to run
- Live cost calculator and a zero-API-call dry run
- Crash-resumable — close it, reboot, carry on tomorrow
- JSON metadata sidecar beside every image
- Detects content-filtered black images instead of saving them as successes
- Tile-optimal sizes: 44% more pixels for the same price
- Command-line front end included

Doesn't need a good GPU — it drives cloud APIs, so it runs fine on a laptop. That was the whole reason I wrote it.

Windows 10/11. $8, one-time.

DOWNLOAD
https://reactorcore.itch.io/

---

Check out everything else I do:

Home/Links: https://linktr.ee/reactorcore
Releases: https://reactorcore.itch.io
Blog: https://www.patreon.com/ReactorcoreGames
Discord: https://discord.gg/UdRavGhj47
Catalog: https://reactorcoregames.github.io/

-Reactorcore
```

**Tags (comma separated)**

```
ai image generation, batch image generation, stable diffusion, flux, cloudflare workers ai, nano banana, ai art tool, automation, batch processing, text to image, ai tools, no gpu, windows app, pollinations, gamedev tools
```

---

## Reddit

**Read this first.** As noted at the top, I could not reach Reddit to verify any of these sidebars — check each one yourself before posting. The general shape of the rules across all of them is consistent, though, and worth respecting regardless: no bare links, no posting the same thing to five subreddits in one hour, participate before and after you post, and expect that the ones with self-promotion day restrictions will enforce them.

Space these out over a week or more. Posting all five on launch day is the single fastest way to get flagged as a spammer across all of them at once.

### Option 1 — r/StableDiffusion

The largest and most receptive audience for this. **Known posture:** generally welcoming of free and open tools and hostile to anything that reads as an ad for a paid product — which this now is, so handle it carefully. **The post below is written to survive that:** it leads with the findings, gives away the genuinely useful knowledge in the body, and mentions the tool once at the end. Do not put the price or the link in the title, and do not put the link in the body — answer with it when someone asks. Being source-available is what keeps this postable at all. Verify their current stance on self-promotion in the sidebar; it has tightened at times.

**Title**

```
Cloudflare bills image generation per 512x512 tile, so the cost is a step function — and the obvious resolutions waste it. What I learned building an unattended batch generator
```

**Post**

```
I don't have the GPU for good local generation (4 GB of VRAM on a laptop), so I've been using cloud APIs — and generating anything more than a handful of images meant sitting there feeding prompts into a web form one at a time. So I wrote the thing that does it while I sleep.

You write one prompt per line in a .txt file, set a style suffix that gets appended to every line, and it generates the lot into a folder with a JSON sidecar beside each image recording the prompt, model, seed, size and cost.

The parts I actually care about, which are the boring ones:

**It resumes.** Job state is in a SQLite database in the output folder. Close it, reboot, come back the next day — finished images are skipped, not regenerated. I lost a 300-image run to a crash once and built this specifically so that couldn't happen again.

**It knows the cost before you spend it.** Dry run mode gives you the full job list and total cost with zero API calls.

**It catches the black-image thing.** This one surprised me and is the reason I'm posting rather than just using it quietly. When Cloudflare's content filter refuses a prompt, it doesn't return an error — it returns `HTTP 200 OK` with a byte-identical all-black image and no error field anywhere in the response. If you don't decode and check every image, your batch reports a flawless 100% success rate and hands you a folder of black rectangles. So it checks every one, and treats flat-colour output as a permanent failure that never gets retried.

**The generation itself can be free.** The three Stable Diffusion models on Cloudflare Workers AI billed literally zero neurons across all my testing — that's measured, not me reading a pricing page. There's also a keyless Pollinations provider if you don't want to make an account at all. The cheapest paid step up (FLUX.2 klein 4B) is $1.72 per 1000 images, and Cloudflare's free daily allowance covers roughly the first 300 of those a day.

One thing I worked out that might be useful even if you never touch the tool: **Cloudflare bills per 512x512 tile, so the cost is a step function.** Any size inside the same tile count costs identically — which means the obvious resolutions are wasteful. At the same price as 1280x720, you can have 1536x864. That's 44% more pixels for nothing. Generate large, downscale locally.

Windows, source included, $8 on itch. Not a ComfyUI replacement — it drives cloud APIs, so it's for people who don't have the GPU rather than people who do. Happy to just answer questions about the Cloudflare side if that's the more useful part.

Happy to answer anything about the Cloudflare side, the pricing tables were a genuine research project.
```

*Weave the link in as a plain line at the very end, after you've answered the first couple of comments — or put it in a top-level comment on your own post, which reads better than a link in the body on most subreddits.*

### Option 2 — r/gamedev

**Known posture:** strict about self-promotion, and typically restricts it to a designated weekly thread. Almost certainly you should post this in their **Feedback Friday / Marketing Monday** style thread rather than as a standalone submission — check which. Angle it at the workflow problem, not the tool.

**Title**

```
Generating game background art in bulk on a laptop with no GPU — the batch pipeline I ended up building
```

**Post**

```
I needed a large set of background images for a game mod — every biome, at several times of day, in a couple of weather states. That's a combinatorial problem: it's not ten images, it's a few hundred, and generating them one at a time through a web UI was going to take a week of evenings.

My laptop has 4 GB of VRAM, so local generation was off the table. What I ended up building is a batch runner over cloud image APIs: a .txt file with one prompt per line goes in, a folder of images comes out, with a shared style suffix appended to every prompt so the whole set stays visually consistent.

The things that turned out to matter for gamedev-scale batches specifically:

- **Consistency across the set.** One style suffix applied to every prompt does more for a coherent-looking set than fiddling with individual prompts does.
- **Resumability.** A 300-image run will get interrupted. It skips what's finished and carries on.
- **Metadata beside every image.** A JSON sidecar with the prompt and seed, so when one image out of two hundred is exactly right, you can regenerate variations of it instead of trying to remember what you typed.
- **Aspect ratio control.** 16:9 natively, rather than generating square and cropping.
- **Cost that's known in advance.** Dry run gives you the total before any API call happens, and the models it starts on bill nothing at all.

It's $8 on itch, Windows, source included in the download.

Mostly interested in whether other people are hitting the same combinatorial wall on art assets, and what you've done about it — the "I need 40 variations of the same thing" problem feels underserved compared to the "I need one great image" problem that everything is optimised for.
```

### Option 3 — r/aiArt or r/AIAssisted

**Known posture:** more permissive about tool posts than the technical subs, but heavily image-driven — a post without pictures will sink regardless of how good the tool is. **Save this one until you have a genuinely good set of generated images to show**, and lead with the images.

**Title**

```
Generated this whole set overnight from a text file — 40 variations, one style, zero babysitting
```

**Post**

```
[Lead with a grid of the actual generated images.]

These were all generated in one unattended run from a .txt file with one prompt per line, plus a single shared style description appended to every one of them. That shared suffix is what keeps a set like this looking like it belongs together — the per-image prompt only describes the subject, and the style is written once.

The generation cost nothing — I'm using the Stable Diffusion models on Cloudflare Workers AI, which don't bill anything, through a batch tool I wrote because doing this through a web interface one image at a time was making me want to stop doing it at all.

Happy to share the tool or the style suffix text if either is useful to anyone.
```

*Let someone ask for the link in the comments and reply with it. On image-first subreddits that converts far better than putting it in the body, and it stays on the right side of the rules.*

### Option 4 — r/software or r/freesoftware

**Known posture:** r/software tolerates release posts if they're substantive, but is notably cooler on paid ones — check whether they require a [PAID] tag, and use it if so. **Skip r/freesoftware entirely**: it cares specifically about the licence, and a paid closed-price tool is not what that community is for. Posting there would be a waste at best and a ban at worst. Write plainly, lead with the constraint that produced it.

**Title**

```
Batch AI Image Generator — takes a .txt file of prompts, generates the lot unattended (Windows, $8, source included)
```

**Post**

```
A small Windows utility I wrote for myself and cleaned up enough to share.

**The problem it solves:** generating more than a handful of AI images means either a good GPU and a local setup, or feeding prompts into a web form one at a time. I have neither the GPU nor the patience, and I needed a few hundred images.

**What it does:** reads a .txt file with one prompt per line, appends a shared style suffix to each, generates them all through a cloud API, and writes the images into a folder with a JSON sidecar beside each one recording the prompt, model, seed and cost.

**What makes it worth using rather than scripting yourself:**

- Crash-resumable — SQLite job state, skips what's already finished
- Retry logic that distinguishes temporary failures from permanent ones
- Detects the content filter's black-image responses (the API returns 200 OK with a black frame and no error, so a naive tool reports total success and saves black rectangles)
- Live cost calculator and a dry-run mode with zero API calls
- Rate limiting on by default, because the free tiers are a courtesy

**Cost:** $8 for the tool. The generation is a separate matter and can be free — three of the thirteen models bill nothing at all, and one provider needs no account. The cheapest paid model is $1.72 per 1000 images; the dearest is $151, and every one is labelled with its cost band in the interface.

Windows 10/11, no Python install needed, source is published. Written in Python with ttkbootstrap.
```

### Option 5 — r/Frugal_Jerk-style angle: r/selfhosted or r/DataHoarder

Weaker fits and worth considering only if the first four go well. **r/selfhosted** is a stretch — this calls a cloud API rather than hosting anything, and that community will correctly point that out, so only post there if you frame it explicitly as "not self-hosted, but the option for people whose hardware can't self-host this." Honestly, probably skip it. **A better fifth option is a comment rather than a post**: when someone in any of the above subs asks "how do I generate a lot of images without a GPU," answer the question properly and mention the tool at the end. That's the highest-conversion, lowest-risk promotion there is, and it's why lurking for a few weeks after launch is worth more than a fifth launch post.

---

## Three more places worth the effort

### 1. alternativeto.net

Free, permanent, and specifically browsed by people trying to find a tool that does one particular thing. List it as an alternative to Midjourney, Stable Diffusion WebUI (AUTOMATIC1111) and Fooocus, with the distinguishing note that it's a *batch runner over cloud APIs* rather than a local generator. Low effort, indefinite tail.

**Suggested short description:**

```
Batch AI image generation from a plain text file — one prompt per line, generated unattended into a folder with metadata. Crash-resumable, with cost estimated before you spend, across 13 models of which three are free to run. Drives cloud APIs, so it needs no GPU. Windows, GUI and CLI.
```

### 2. Hacker News (Show HN)

Worth one shot. The audience appreciates exactly the things that are hard to show in a screenshot — the resume semantics, the retry taxonomy, the black-image discovery, the reverse-engineered pricing. It also lives in the search index permanently.

**Title:**

```
Show HN: Batch AI image generation from a text file, with the cost known before you run it
```

Lead the comment with the technical findings rather than the feature list — the tile-based step-function pricing and the `200 OK` black-image behaviour are the genuinely interesting parts and are what would get discussed. Post on a weekday morning US time, and be present in the thread.

### 3. The itch.io community forums and relevant Discords

itch has its own "Release Announcements" board, and it converts because everyone reading it is already on itch. Their rule is explicit and worth honouring: **don't just dump a link.** Write a real post about what it does and why.

For Discords: your own server first, then any gamedev or AI-art servers you're already a member of, in their designated showcase channels. **Only servers you already participate in** — joining a server to post a link is transparent and gets you removed.

---

## To anyone reading this: please share it

If this program is useful to you, the single most valuable thing you can do is tell someone else about it. Post it where people with the same problem are looking, mention it when someone asks how to generate images in bulk without a GPU, or just leave a comment on the itch page — visible activity is what makes a page findable by anyone else.

What I can offer is straightforward: **if you send real traffic my way, I'll return the favour.** If you have a project of your own, email me and I'll share it across my channels — itch, Patreon, Discord, catalog. If you find a bug, report it and you get credited in the release notes. If you write something using this — a tutorial, a video, a showcase of images you generated — send me the link and I'll feature it on the project page.

For my paid projects the arrangement is different and worth stating plainly here so it's on the record: if you bring paying customers, contact me at the address below with some proof of the impact and **I will share the earnings with you** — genuinely, and by more than a token amount. If you turn out to have been pivotal in bringing in those customers, that share can go past 50% of the revenue, after the platform's cut and other deductions come out. I'm not a company with a legal department and an affiliate programme; I'm one person with a laptop trying to earn enough to make rent, so we'd work it out directly and fairly between us.

Either way — thank you for reading this far. It genuinely matters.

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
