# Recipes

Things to copy, paste and get on with. For the craft, see `prompting.md`; for operating the program, see `guide.md`.

The prompts below are for an **LLM assistant** — not for the image generator. They produce text you then paste into this program. Any of these will do:

<links>
Claude - https://claude.ai
ChatGPT - https://chatgpt.com
Gemini - https://gemini.google.com
Perplexity - https://www.perplexity.ai
</links>

Replace the `YOUR_TEXT`-style placeholder in each (double-click selects the whole thing), and paste the whole block.

> **This file is read by the program.** The **Helpers** tab shows the links above and a copy button for each prompt below, parsed straight out of this file — so editing here changes the tab, and you can add your own. The `<links>` and `<recipe>` tags are what the program looks for: edit freely inside them, but leave the tags themselves in place. Hit **Reload** on the Helpers tab to see your changes without restarting.

## Build a style preset with an LLM

The result goes in the style suffix box on the Prompts tab.

<recipe name="Style preset">
```
I want a reusable image-generation style prompt: a block of style keywords I can append to any subject to give it a consistent look.

Here is an example of the FORMAT I want, not the substance:

oil-painting, oil on board, Syd Mead, John Berkey, unique presentation, childhood nostalgia, colorful background, surreal elements, retro design, cartoonish style, bright colors, strange texture

Requirements:

1. It must describe ONLY the look - medium, technique, colour, lighting, mood, texture. No subject matter, no specific objects, no scene.
2. It must work for ANY subject: a tundra outpost, a bustling city, a subway tunnel, a dock, a building interior, a spaceship compartment.
3. Put the most important, most style-defining words FIRST. Anything optional goes last - the tail may be cut off before it reaches the model.
4. Comma-separated keywords and short phrases, one line, under 600 characters.
5. Reply with the prompt only. No commentary, no explanation, no quote marks.

The look I want:

DESCRIBE_THE_LOOK_YOU_WANT
```
</recipe>

Two things in there earn their place. **"No subject matter"** is what keeps the preset reusable — an LLM will happily slip "ancient ruins" into a style block and then every image you generate has ruins in it. **Front-loading** matters because on Stable Diffusion the tail genuinely gets cut off, so the words that define the style have to be at the start.

## Turn writing into an image

For when you have a piece of text — a scene, a chapter, a description — and want a picture of it.

**Vignette** — depict the scene literally:

<recipe name="Vignette">
```
Suggest a suitable text vignette for an image that fits the context of the text below. Describe it in detail yet concisely, use no more than 600 characters, and keep the result as a single paragraph.

The text:

YOUR_TEXT
```
</recipe>

**Visual metaphor** — depict what it *means*:

<recipe name="Visual metaphor">
```
Suggest a suitable visual metaphor that fits the context of the text below. Describe it in detail yet concisely, use no more than 600 characters, and keep the result as a single paragraph.

The text:

YOUR_TEXT
```
</recipe>

**Mood board** — several angles on one subject, for a whole batch:

<recipe name="Mood board">
```
Give me 8 distinct image prompts based on the text below. Vary the shot type, the time of day, and the emotional register between them.

Output rules: one prompt per line, no numbering, no commentary, no blank lines. I am pasting this straight into a batch image generator that reads one prompt per line. Keep each prompt under 300 characters.

The text:

YOUR_TEXT
```
</recipe>

That last one produces a prompt file directly: save the reply as a `.txt` and point the program at it.

## Condense a wordy prompt

For when you have flowing prose and need it to fit Stable Diffusion's ~300 characters.

<recipe name="Condense a prompt">
```
Rewrite the prompt below as a condensed cloud of keywords and short phrases, all on one line, comma-separated. Distil every element relevant to a visual image and drop filler words that don't describe anything. Put the most important elements first.

Then add a few describers suited to the image type:

- 3D render: material and lighting quality, compositing, aesthetic
- photo: lens, exposure, depth of field, other photographic terms
- digital painting: perspective, shading, aesthetic

Reply with the rewritten prompt only.

The prompt:

YOUR_PROMPT
```
</recipe>

## Getting a bigger image for free

Cost is charged per 512x512 tile, so every size inside the same tile count costs exactly the same. The sizes in the dropdown are already the largest that fit each tier — at Standard, 16:9 gives you **1536x864, which is 44% more pixels than 1280x720 for the same price**.

Generate large, then downscale locally if you need something smaller. Downscaling is free and looks better than generating small.

## When to run a big batch

Free tiers are shared, so an overnight or early-morning batch will probably go more smoothly than one at a busy hour. Weekends and early in the week are likely quieter than midweek.

**This is folklore, not measurement.** We haven't tested it, and the advice originally came from an LLM. Treat it as a mild preference, not a rule — if a batch is going fine at 2pm on a Wednesday, nothing is wrong.

What *is* measured: the program's default concurrency of 2 with a one-second delay is deliberate, and raising it risks rate limits rather than finishing sooner. Pollinations is capped at one request at a time no matter what you do.

## Recovering from a bad batch

- **Lots of blocked images?** The content filter rejected those prompts. Blocked is permanent — retrying identical text gets the same refusal. Reword them.

- **SDXL/Lightning results suck?** Switch to Flux 2 Klein 4B or one of the prepaid models. Stable Diffusion (SD/SDXL) models have limitations in what subjects they can handle - usually any drawn, anime, comic or painted styles are weaker on SD models, while they're slightly better at photo/realism images of people/portraits and close-ups. Anything else needs a better model.

- **Lots of failed images?** Usually network or rate limits. Hit **Retry Failed**; it re-queues those and leaves blocked ones alone.

- **Wrong style on everything?** Fix the style suffix and press **Start** again. That is all — the suffix is part of each image's filename, so a changed style means new filenames, and the new versions generate alongside the old ones. The same goes for changing the model or the size.

- **Want the same thing again, with but a different reroll?** That is what **Regenerate** is for — a different random seed reroll, or results that simply were not good. It replaces the images already in the folder and, on a paid model, charges for them again, so it asks first. It covers what your current settings would generate, so a 5-of-100 slider setting redoes those 5. You only need it when *nothing* changed; a different style, model or size regenerates on a normal Start.
