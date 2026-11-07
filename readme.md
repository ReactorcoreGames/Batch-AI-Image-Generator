# Batch AI Image Generator

**A text file of prompts goes in, a folder of images comes out.**

Write your image ideas one per line in a `.txt` file. Point this program at it. Come back to a folder of finished images, each with its full generation details saved beside it. It's built for large unattended runs — it survives crashes, resumes where it stopped, retries what's worth retrying, and tells you what a batch costs before you spend anything.

**Thirteen models, and the ones it starts on cost nothing to run.** Three Stable Diffusion models on Cloudflare Workers AI were measured generating images at zero cost, and the Pollinations provider needs no account at all — not a trial, not a credit balance that runs out on Tuesday. From there the lineup runs up through FLUX.2 klein 4B at **$1.72 per 1000 images** to Google's Nano Banana 2, and every model is marked with what it costs before you pick it.

![Batch AI Image Generator](promo/BAIG%20screenshot%20(1).png)

## What it does

- **Batch generation from a plain text file** — one prompt per line, blank lines skipped.
- **A shared style suffix** appended to every prompt, so you write your art direction once instead of a thousand times. Painterly and Comic presets included; save your own.
- **Thirteen models across two providers.** Cloudflare Workers AI — five on its free daily allowance, eight more through its AI Gateway — and Pollinations, keyless and zero-setup. All the Cloudflare models share one account and one API token.
- **A live cost calculator, and a cost band on every model.** FREE, LOW, MEDIUM, HIGH or EXTREME, readable straight off the dropdown — then change the model, ratio or size tier and watch the real number for your batch update as you decide.
- **Dry run mode** — the full job list and total cost with zero API calls.
- **Crash-resumable.** Job state lives in SQLite next to your output. Close it, reboot, come back tomorrow: finished images are skipped, not regenerated.
- **Sidecar metadata** — a `.json` beside every image with the original prompt, the final prompt, model, seed, size, timestamp and cost estimate.
- **Black-image detection.** Content-filtered prompts come back from the API as `200 OK` with an all-black frame and no error. Every image is checked and flat-colour results are marked as permanent failures rather than being silently saved as successes.
- **Tile-optimal sizes.** On the models that bill per tile, cost moves in steps — so at the Standard tier 16:9 gives you 1536×864, 44% more pixels than 1280×720 for exactly the same price.
- **Per-model honesty about the controls.** Five models render at one fixed size, four accept no seed, ten ignore negative prompts. The interface says so on the model that has the limit, rather than offering a control that quietly does nothing.
- **Polite by default.** Low concurrency, a deliberate gap between requests, proper `HTTP 429` backoff.
- **A command-line front end** (`cli.py`) onto the same engine, for scripts and scheduled tasks.

## Requirements

- Windows 10 or 11
- An internet connection
- No Python needed — the release is compiled

## Getting started

1. Unzip and run `Batch AI Image Generator.exe`.
2. On the **Provider** tab, pick **Pollinations** to generate immediately with no setup, or paste in a free Cloudflare account ID and API token for the faster main lane. The eight AI Gateway models additionally need prepaid credit loaded on your Cloudflare account; the free models and Pollinations need no payment method at all.
3. On the **Prompts & Style** tab, choose your `.txt` prompt file and an output folder.
4. On the **Run** tab, click **Dry Run** to see the cost, then **Start Batch**.

If you would rather be walked through it, open **`1 first time setup tutorial.html`** in the download — six steps with a screenshot of each tab and a checklist to tick off, covering nothing that costs money. **`2 advanced usage tutorial.html`** is the companion for the paid models: what they cost, how the billing works, and how to load credit. Both work offline in any browser.

Full instructions, including how to get the Cloudflare keys, are in **[guide.md](guide.md)** — the **Help** button in the program opens it. What changed in each release is in **[changelog.md](changelog.md)**.

## Licence

**The program** is free to use and free to redistribute unmodified. Please don't repackage it as your own.

**The images you generate are yours.** Cloudflare treats prompts and outputs as your content, and you may use them commercially.

One honest caveat worth knowing rather than worrying about: FLUX.2 klein 9B carries a FLUX Non-Commercial licence, which restricts *serving the model* — hosting it as a service yourself — and not the images it produces. Generating through Cloudflare's hosted endpoint and using the results commercially is fine. Every other model here permits commercial output use without qualification. This program is a client calling a hosted API; it never downloads or runs the models themselves.

## A note on your API keys

Keys are entered in the program and saved to `credentials.json` beside the exe, restricted to your Windows user. They are never written to `config.json`, never stored in the job database, and never included in image metadata. **If you share this folder with anyone, delete `credentials.json` and `config.json` first.**

The guide recommends creating your Cloudflare token from the **"Read all resources"** template. That is genuinely sufficient — the program only reads and generates, never modifies your account — and it means a leaked token can't be used to change anything you own.

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
