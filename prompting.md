# Writing prompts that work

A short reference. For how to *operate* the program, see `guide.md`; for ready-made prompts to copy, see `recipes.md`.

## The one rule that matters most

**Subject in the prompt, treatment in the style suffix, and order both by how much you'd miss them.**

Your prompt file describes *what* the picture is of. The style suffix describes *how* it looks, and gets appended to every line. Keeping them separate is what lets you re-run a hundred prompts in a different style by editing one box.

Put the important words first. Image models weight the opening of a prompt more heavily than the end — so the further down a detail sits, the more likely it is to be quietly ignored.

## How long is too long

Every model has a length limit, and **it truncates silently** — no error, nothing missing from the picture to tell you. The counters under the style editor and the negative prompt box tell you where you stand.

| Model | Comfortable length |
|---|---|
| SDXL Lightning, SDXL Base, DreamShaper | **~300 characters** |
| FLUX.2 klein 4B / 9B | **~2000 characters** |
| Pollinations FLUX.1 Schnell | ~1000 characters |

This is measured, not theory. The same 715-character prompt was sent twice with only one clause moved: *"a giant yellow rubber duck"* at the front produced a duck dominating the frame; the same words with the duck clause at the **end** produced no duck at all, on both SDXL Lightning and SDXL Base.

**On the Stable Diffusion models, your style suffix is the part that gets eaten.** It is appended last, so it truncates first. Write a long scene description plus a rich style suffix on SDXL and you lose the style — the opposite of what you'd expect. Either keep the total under ~300, or use a klein model.

The negative prompt has its **own separate budget** and does not compete with any of this. A long negative costs your scene description nothing.

## Building blocks

Pick what you need and ignore the rest — two or three of these beats a wall of adjectives. The parenthesised notes are what each choice *does* to the viewer, which is usually the thing you're actually choosing between.

### Prompt structure

Roughly most to least important, which is also the order to write them in:

```
SHOT TYPE

SUBJECT / DESCRIPTION

VIEW / PERSPECTIVE       (corrections on top of the shot type)

ART MEDIUM
STYLE / ARTIST

COLOUR
LIGHTING                 (flat, or cinematic)

QUALITY / RESOLUTION
```

Anything you want *absent* goes in the negative prompt, not here.

### Shot sizes

```
Extreme close-up         (a detail, an eye, a texture — abstract, intense)
Big close-up             (face fills the frame)
Close-up                 (head and shoulders — emotion, intimacy)
Medium close-up          (chest up — the conversational default)
Medium                   (waist up — gesture plus expression)
Medium wide / long       (full body, some surroundings)
Wide / long              (subject and setting share the frame)
Extreme wide / long      (subject tiny in a vast space — scale, isolation)

Establishing shot        (introduces a place; the opening shot of a scene)
Point of view (POV)      (first person — puts the viewer inside the frame)

Two shot                 (two subjects, equal weight)
Over the shoulder        (two subjects, emphasis on the far one)
Reverse shot             (the same pair from the other side)
```

Wide and extreme wide are the workhorses for backgrounds and landscapes. Close-ups are for when a single subject carries the image.

### Camera angles

```
Eye level, neutral angle (relatable, honest, unremarkable — a safe default)

Low angle                (looking UP at the subject — power, threat, grandeur)
High angle               (looking DOWN at it — smallness, vulnerability)

Bird's eye view          (from far above — distant awe, a whole landscape)
  also: aerial view, overview, view from a high position
Worm's eye view          (from the ground looking up — close, local awe)
  also: floor angle, view from a low position

Dutch angle              (frame tilted — unease, disorientation, dread)
  also: canted angle, tilted angle
```

Angle is the cheapest way to change the *feeling* of an otherwise identical scene. If a batch of landscapes looks flat, this is usually the missing ingredient.

Camera *movement* terms — pan, tilt, track, pedestal, crab — are deliberately not listed. They describe motion over time and mean nothing to a still image; a model will either ignore them or waste attention on them.

### Composition

```
Rule of thirds           (subject off-centre — natural, unforced)
Symmetry                 (centred and balanced — formal, still, imposing)
L-shape                  (a foreground edge framing the subject — depth)
Leading lines            (roads, rivers, fences pulling the eye inward)
Follow the action        (framed as though tracking movement)
Framing                  (shooting through a doorway, branches, an arch)
Atmospheric perspective  (distance fading to haze — depth, scale)
```

### Lighting

```
Flat lighting            (even, shadowless — clear but undramatic)
Cinematic lighting       (directional, high contrast, deliberate)
Golden hour              (low warm sun — flattering, nostalgic)
Blue hour / twilight     (cool, quiet, melancholy)
Overcast / diffuse       (soft, even, unromantic — good for detail)
Backlit / rim light      (subject outlined in light — separation, drama)
Volumetric light         (visible shafts and god rays through air)
Low-key                  (mostly shadow — tension, mystery)
High-key                 (mostly bright — airy, clean, optimistic)
```

### Medium and style

```
Oil painting, oil on board, gouache, watercolour, ink and wash
Digital illustration, digital painting, concept art, matte painting
Cel-shaded, comic book art, graphic novel, storyboard sketch
3D render, isometric render, clay render
Photograph, film photography, polaroid, long exposure
```

Naming a medium does more work than almost anything else in a prompt. "Oil painting" and "3D render" of the same subject are barely related images.

### Emphasis modifiers

Support varies by model — the Stable Diffusion models here understand them, and the FLUX klein models largely ignore them in favour of plain description.

```
(word)          increase attention
[word]          reduce attention
word :: word    split into separate concepts
                ("hot :: dog" reads differently from "hotdog")
```

Don't lean on these. Clear wording and good ordering beat weighting syntax on every model in this program.

## Say what you want, not what you don't

An early test here used the word *"blurry"* to get a soft, distant background. FLUX obliged and returned a genuinely blurry, useless image. An older, weaker model had ignored the word entirely, which is why the problem only appeared after upgrading.

That's strong prompt adherence working correctly. The better the model, the more literally it takes you.

So: **soft focus · atmospheric haze · depth of field · painterly softness · distant and hazy** — not "blurry". Same for "dark" (try *low-key lighting*, *deep shadows*) and "simple" (try *minimal*, *uncluttered composition*).

Things you want *absent* belong in the negative prompt, not phrased as a negative in the main prompt.

## Negative prompts

A comma-separated list of what to keep out. Stable Diffusion only — the FLUX klein models ignore it and use guidance instead.

They're built from **layers** on the Provider tab: tick a quality floor, an anatomy fixer, a no-text layer, and they join together with duplicates removed. Because the budget is separate, stack whatever is genuinely useful.

Only stack what's *relevant*. Anatomy terms do nothing for an empty landscape — they aren't expensive, just useless there.

## Practical habits

- **Test on 5 before running 100.** The Generate slider on the Prompts tab caps a run; a later full run reuses what the test already made.
- **Validate on the free models.** Prompt wording is the real cost lever, and Lightning is free.
- **Fix the seed when comparing wording.** Otherwise you're comparing noise.
- **Generate large, downscale locally.** At Standard, 16:9 is 1536x864 for the same price as 1280x720.
