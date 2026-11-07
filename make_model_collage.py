"""Build the model-comparison collage from a set of already-generated images.

    python make_model_collage.py

Writes promo/model_comparison.jpg -- every model in the lineup rendering the
SAME prompt, each tile labelled with the model, its price band and the size it
actually delivered, with the shared prompt printed underneath.

The comparison is only honest if every tile ran the identical prompt, so the
script REFUSES to build if the sidecars disagree. That check is the whole point
of reading `final_prompt` from the .json rather than passing the text in: a
collage captioned "here is one prompt across 13 models" that quietly used two
prompts would be worse than no collage.

Sizes are read from the DECODED IMAGE, never from the requested size in the
sidecar. Four models in this lineup silently return something other than what
was asked for (see docs/findings.md), and a label claiming the requested size
would be repeating exactly the mistake the program's own size_mismatch flag
exists to catch.

Rendering traps inherited from make_promo_images.py, which apply here too:

  * Measure every glyph with textbbox() -- never hardcode an offset. The tile
    labels are per-model strings of very different lengths.
  * Tiles are letterboxed into a fixed cell rather than stretched, because the
    delivered aspect ratios genuinely differ (1280x720 vs 1536x864 vs 1024x576)
    and stretching them would misrepresent the very thing being compared.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core import models as M

ROOT = Path(__file__).parent
OUT = ROOT / "promo" / "model_comparison.jpg"

# The app's palette, from gui/theme.py. Literals rather than an import so this
# script never drags the GUI stack in -- same reasoning as make_promo_images.py.
TEXT_PRIMARY = "#E8F6F6"
ACCENT_SOFT = "#7FE3EC"
ACCENT_MID = "#31C6D4"
TEXT_SECONDARY = "#A9CFCE"
BG_BASE = "#0D2E2D"
TILE_BG = "#0A2423"

FONT_BLACK = "C:/Windows/Fonts/seguibl.ttf"
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_SEMIBOLD = "C:/Windows/Fonts/seguisb.ttf"
FONT_REGULAR = "C:/Windows/Fonts/segoeui.ttf"

TITLE = "15 MODELS, ONE PROMPT"
SUBTITLE = "Every model in Batch AI Image Generator rendering the same prompt"
FOOTER = "Made by Reactorcore  \u00b7  reactorcore.itch.io"

# The fairness disclaimer. This is NOT boilerplate -- without it the chart is
# actively misleading, and an earlier draft of it was.
#
# The prompt below is ~660 characters. The three SD models encode text with
# CLIP, which stops at 77 tokens (~300 characters), so they were shown LESS
# THAN HALF of it and then judged on the result. The bigger models read all of
# it. A reader comparing the tiles without knowing that concludes the SD
# models are bad, when what they are is BADLY BRIEFED -- they do considerably
# better on the short, focused prompts they were built for.
DISCLAIMER_HEAD = "READ THIS BEFORE JUDGING THE MODELS"
DISCLAIMER = [
    "One long, detailed prompt — about 660 characters — which suits the larger models and handicaps the smaller ones.",
    "The three SD models read text with CLIP, which stops around 300 characters, so they never saw half of this prompt.",
    "A four-subject scene is also the hardest thing to ask of a small model. Give these one subject and a short prompt and they do markedly better.",
    "Krea runs with its prompt-expansion feature ON — that is what the model is built around, and a fair part of why it does well here.",
    "This is a snapshot of ONE prompt, not a ranking. The free and cheap models are often the right choice; try them before paying.",
]

# (folder, display name, price label). Order is cheapest-first within each
# group so the collage reads as a price ladder rather than an arbitrary grid.
# (folder, display name, model key). The price label is DERIVED from the
# registry rather than typed here -- a hand-written one was wrong on its first
# outing: both klein models were labelled "FREE ~300/day" when 9B actually gets
# about SIX images a day, because it costs ~10x more per image and burns the
# same daily neuron allowance that much faster. The program already knew the
# real number; the collage was the only place repeating a guess.
TILES = [
    ("out/collage/lightning",        "SDXL Lightning",       "lightning"),
    ("out/collage/sdxl",             "SDXL Base 1.0",        "sdxl"),
    ("out/collage/dreamshaper",      "DreamShaper 8 LCM",    "dreamshaper"),
    ("out/collage/poll-dreamshaper", "Pollinations DS",      "poll-dreamshaper"),
    ("out/collage/poll-flux",        "Pollinations Flux",    "poll-flux"),
    ("out/collage/klein4b",          "FLUX.2 Klein 4B",      "klein4b"),
    ("out/collage/klein9b",          "FLUX.2 Klein 9B",      "klein9b"),
    ("out/collage/p-image",          "P-Image",              "p-image"),
    ("out/paidtest/krea-turbo",      "Krea 2 Turbo",         "krea-turbo"),
    ("out/paidtest/krea-medium",     "Krea 2 Medium",        "krea-medium"),
    ("out/paidtest/flux2pro",        "FLUX.2 Pro",           "flux2pro"),
    ("out/paidtest/nano-lite",       "Nano Banana 2 Lite",   "nano-banana-2-lite"),
    ("out/paidtest/recraft-u",       "Recraft V4.1 Utility", "recraft-utility"),
    ("out/paidtest/recraft-41",      "Recraft V4.1",         "recraft-v41"),
    ("out/paidtest/nano-2",          "Nano Banana 2",        "nano-banana-2"),
]

COLS = 5
CELL_W, CELL_H = 460, 259          # 16:9 image area per tile
LABEL_H = 54                       # name + price strip under each image
GAP = 14
MARGIN = 40


def price_label(model_key: str) -> tuple[str, str]:
    """(label, colour) for a model's cost, straight from the registry.

    Three genuinely different billing lanes, and flattening them misleads:

      * FREE            -- bills nothing, ever.
      * FREE ~N/day     -- bills Cloudflare NEURONS against a free daily
                           allowance, so a small batch costs nothing and a
                           large one starts charging partway through. N is the
                           MEASURED allowance and differs enormously between
                           the two klein models (~361 vs ~6), which is exactly
                           why it is read rather than typed.
      * $X / 1000       -- prepaid credit, charged from the first image.
    """
    spec = M.get_model(model_key)
    if spec.is_free:
        return "FREE", TEXT_SECONDARY
    w, h = M.size_for("16:9", "standard", model_key)
    est = M.estimate(model_key, w, h, 1)
    if est.free_images_per_day:
        return f"FREE ~{est.free_images_per_day}/day", ACCENT_MID
    return f"${est.cost_per_1000:,.0f} / 1000", ACCENT_SOFT


def load(folder: str):
    """Return (image, model_name, delivered_size, prompt) for one tile."""
    d = ROOT / folder
    sidecars = sorted(d.glob("*.json"))
    if not sidecars:
        raise SystemExit(f"no sidecar .json in {folder} — generate it first")
    meta = json.loads(sidecars[0].read_text(encoding="utf-8"))
    img_path = d / meta["image_file"]
    if not img_path.exists():
        raise SystemExit(f"sidecar names a missing image: {img_path}")
    im = Image.open(img_path).convert("RGB")
    # The DECODED size, not the requested one -- four models in this lineup
    # return something else and say nothing about it.
    return im, meta["model"], f"{im.size[0]}x{im.size[1]}", meta["final_prompt"]


def letterbox(im: Image.Image, w: int, h: int) -> Image.Image:
    """Fit into w x h preserving aspect, padded rather than stretched.

    The delivered ratios genuinely differ across this lineup, so stretching
    would distort the exact thing the collage is comparing.
    """
    canvas = Image.new("RGB", (w, h), TILE_BG)
    scale = min(w / im.width, h / im.height)
    new = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                    Image.LANCZOS)
    canvas.paste(new, ((w - new.width) // 2, (h - new.height) // 2))
    return canvas


def main() -> int:
    tiles, prompts = [], set()
    for folder, name, model_key in TILES:
        im, _model, size, prompt = load(folder)
        prompts.add(prompt.strip())
        price, colour = price_label(model_key)
        tiles.append(
            (letterbox(im, CELL_W, CELL_H), name, price, size, colour))

    # An honest comparison requires one prompt. Refuse rather than mislead.
    if len(prompts) != 1:
        raise SystemExit(
            f"the tiles used {len(prompts)} different prompts; a comparison "
            "collage is only meaningful if every model ran the same one"
        )
    prompt = prompts.pop()

    rows = (len(tiles) + COLS - 1) // COLS
    grid_w = COLS * CELL_W + (COLS - 1) * GAP
    grid_h = rows * (CELL_H + LABEL_H) + (rows - 1) * GAP

    title_font = ImageFont.truetype(FONT_BLACK, 52)
    sub_font = ImageFont.truetype(FONT_SEMIBOLD, 26)
    name_font = ImageFont.truetype(FONT_BOLD, 25)
    meta_font = ImageFont.truetype(FONT_SEMIBOLD, 20)
    prompt_head_font = ImageFont.truetype(FONT_BOLD, 23)
    prompt_font = ImageFont.truetype(FONT_REGULAR, 21)
    foot_font = ImageFont.truetype(FONT_SEMIBOLD, 21)

    # Wrap the prompt to the grid width by MEASURING it, not by guessing a
    # character count -- the same rule the promo script learned the hard way.
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    wrap_at = 40
    while wrap_at < 400:
        lines = textwrap.wrap(prompt, wrap_at)
        if any(probe.textbbox((0, 0), ln, font=prompt_font)[2] > grid_w - 60
               for ln in lines):
            wrap_at -= 2
            break
        wrap_at += 2
    prompt_lines = textwrap.wrap(prompt, max(20, wrap_at))

    line_h = 30
    head_h = 150
    prompt_box_h = 34 + len(prompt_lines) * line_h + 30
    foot_h = 56
    W = grid_w + MARGIN * 2
    disc_box_h = 34 + len(DISCLAIMER) * line_h + 24
    H = (head_h + grid_h + 26 + prompt_box_h + 16 + disc_box_h
         + foot_h + MARGIN)

    canvas = Image.new("RGB", (W, H), BG_BASE)
    d = ImageDraw.Draw(canvas)

    d.text((MARGIN, 34), TITLE, font=title_font, fill=TEXT_PRIMARY)
    d.text((MARGIN, 98), SUBTITLE, font=sub_font, fill=TEXT_SECONDARY)

    y = head_h
    for i, (im, name, price, size, colour) in enumerate(tiles):
        col, row = i % COLS, i // COLS
        x = MARGIN + col * (CELL_W + GAP)
        ty = y + row * (CELL_H + LABEL_H + GAP)
        canvas.paste(im, (x, ty))
        d.rectangle([x, ty + CELL_H, x + CELL_W, ty + CELL_H + LABEL_H], fill=TILE_BG)
        d.text((x + 12, ty + CELL_H + 6), name, font=name_font, fill=TEXT_PRIMARY)
        # Price right-aligned: measured, never offset by guess.
        pw = d.textbbox((0, 0), price, font=meta_font)[2]
        d.text((x + CELL_W - 12 - pw, ty + CELL_H + 8), price,
               font=meta_font, fill=colour)
        d.text((x + 12, ty + CELL_H + 30), size, font=meta_font, fill=ACCENT_MID)

    py = y + grid_h + 26
    d.rectangle([MARGIN, py, W - MARGIN, py + prompt_box_h], fill=TILE_BG)
    d.text((MARGIN + 20, py + 12), "THE PROMPT", font=prompt_head_font, fill=ACCENT_SOFT)
    for i, ln in enumerate(prompt_lines):
        d.text((MARGIN + 20, py + 44 + i * line_h), ln,
               font=prompt_font, fill=TEXT_SECONDARY)

    dy = py + prompt_box_h + 16
    d.rectangle([MARGIN, dy, W - MARGIN, dy + disc_box_h], fill=TILE_BG)
    d.text((MARGIN + 20, dy + 12), DISCLAIMER_HEAD,
           font=prompt_head_font, fill=ACCENT_MID)
    for i, ln in enumerate(DISCLAIMER):
        d.text((MARGIN + 20, dy + 46 + i * line_h), ln,
               font=prompt_font, fill=TEXT_SECONDARY)

    fw = d.textbbox((0, 0), FOOTER, font=foot_font)[2]
    d.text(((W - fw) // 2, H - 40), FOOTER, font=foot_font, fill=TEXT_SECONDARY)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, quality=92, optimize=True)
    print(f"wrote {OUT}  ({W}x{H}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
