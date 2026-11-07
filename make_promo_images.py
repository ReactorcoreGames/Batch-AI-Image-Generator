"""Generate the itch.io store images from the master art.

Produces promo/thumbnail_630x500.jpg (the cover image on the store card) and
promo/cover_1280x720.jpg (the page banner), composited over
assets/icon og (2).jpg in the app's own teal/cyan palette.

    python make_promo_images.py

This script is IN THE REPO deliberately. The first version lived in a scratch
folder and was lost, which meant a one-word text change (removing a misleading
"FREE" badge after the program went paid) turned into rewriting the whole
generator. Editing the TEXT constants below is now the whole job.

Two rendering traps were hit the first time and are guarded against here:

  * Hardcoded x-offsets made the thumbnail's title lines overlap at some font
    sizes. Everything is measured with fit_font() / draw.textbbox() instead --
    never assume a glyph's width.
  * The bullet glyph U+25B8 rendered as tofu boxes in Segoe UI Semibold, so
    bullets are DRAWN as polygons rather than typed.

JPG is written rather than PNG: 72 KB vs 280 KB for the thumbnail at no
visible quality cost.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
MASTER = ROOT / "assets" / "icon og (2).jpg"
OUT_DIR = ROOT / "promo"

# The app's own palette, from gui/theme.py. Kept as literals rather than
# imported so this script never drags the GUI stack in.
TEXT_PRIMARY = "#E8F6F6"
ACCENT_SOFT = "#7FE3EC"
ACCENT_MID = "#31C6D4"
TEXT_SECONDARY = "#A9CFCE"
BG_BASE = "#0D2E2D"

FONT_BLACK = "C:/Windows/Fonts/seguibl.ttf"      # Segoe UI Black
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"      # Segoe UI Bold
FONT_SEMIBOLD = "C:/Windows/Fonts/seguisb.ttf"   # Segoe UI Semibold

# --- The copy. THIS is the part you edit. -----------------------------------
#
# The program is PAID at $8. Never write anything here that reads as "this
# software is free" -- the badge said FREE for exactly that reason and had to
# come out. The generation being free is a true and much better hook, but it
# has to name what is free.

THUMB_TITLE = ["BATCH AI", "IMAGE", "GENERATOR"]
THUMB_TAGLINE = "Prompts in. Images out."
THUMB_BADGE = "13 MODELS"

COVER_TITLE = ["BATCH AI IMAGE", "GENERATOR"]
COVER_SUBTITLE = ["A text file of prompts goes in.", "A folder of images comes out."]
# (text, colour) -- the accent colour is the emphasis, so use it sparingly.
COVER_BULLETS = [
    ("Runs unattended \u00b7 resumes after a crash", TEXT_PRIMARY),
    ("Cost shown before you spend it", TEXT_PRIMARY),
    ("13 models \u2014 free and paid", ACCENT_SOFT),
    ("No GPU needed", ACCENT_MID),
]
COVER_FOOTER = "Made by Reactorcore  \u00b7  reactorcore.itch.io"


def fit_font(path: str, text: str, max_width: int, start: int, floor: int = 12):
    """Largest size at or below `start` whose rendering fits `max_width`.

    Measure, never assume. The first version of this script positioned title
    lines with hardcoded offsets and they overlapped.
    """
    size = start
    while size > floor:
        font = ImageFont.truetype(path, size)
        if font.getbbox(text)[2] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(path, floor)


def shadowed_text(img, xy, text, font, fill, blur=6, passes=3, offset=(0, 3)):
    """Draw text over a soft multi-pass shadow so it holds over busy art."""
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.text((xy[0] + offset[0], xy[1] + offset[1]), text, font=font,
            fill=(0, 0, 0, 210))
    for _ in range(passes):
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(shadow)
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill)


def scrim(img, box, opacity=150, feather=90):
    """A soft dark panel behind text, so contrast never depends on the art."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(box, fill=(5, 20, 20, opacity))
    layer = layer.filter(ImageFilter.GaussianBlur(feather))
    img.alpha_composite(layer)


def cover_art(size):
    """The master art, cropped to fill `size` without distortion."""
    src = Image.open(MASTER).convert("RGBA")
    tw, th = size
    scale = max(tw / src.width, th / src.height)
    new = (int(src.width * scale + 1), int(src.height * scale + 1))
    src = src.resize(new, Image.LANCZOS)
    left = (src.width - tw) // 2
    top = (src.height - th) // 2
    return src.crop((left, top, left + tw, top + th))


def draw_bullet(draw, x, y, h, colour):
    """A triangular bullet, DRAWN not typed.

    U+25B8 renders as a tofu box in Segoe UI Semibold. Learned the hard way.
    """
    draw.polygon([(x, y), (x, y + h), (x + h * 0.72, y + h / 2)], fill=colour)


def make_thumbnail():
    W, H = 630, 500
    img = cover_art((W, H))
    scrim(img, (0, int(H * 0.42), W, H), opacity=165, feather=70)

    d = ImageDraw.Draw(img)
    margin = 30

    # Badge, top left. Names WHAT there are 13 of -- a bare number, or worse a
    # bare "FREE", makes a claim about the program itself.
    badge_font = ImageFont.truetype(FONT_BLACK, 30)
    bb = d.textbbox((0, 0), THUMB_BADGE, font=badge_font)
    pad_x, pad_y = 18, 12
    bw = bb[2] - bb[0] + pad_x * 2
    bh = bb[3] - bb[1] + pad_y * 2
    badge = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(badge).rectangle(
        (margin, margin, margin + bw, margin + bh), fill=(13, 46, 45, 235)
    )
    img.alpha_composite(badge)
    d = ImageDraw.Draw(img)
    d.text((margin + pad_x - bb[0], margin + pad_y - bb[1]), THUMB_BADGE,
           font=badge_font, fill=ACCENT_MID)

    # Title block, bottom left. Middle line accented.
    avail = W - margin * 2
    fonts = [fit_font(FONT_BLACK, line, avail, 76) for line in THUMB_TITLE]
    heights = [f.getbbox(line)[3] - f.getbbox(line)[1]
               for f, line in zip(fonts, THUMB_TITLE)]
    gap = 12
    tag_font = ImageFont.truetype(FONT_SEMIBOLD, 24)
    tag_h = tag_font.getbbox(THUMB_TAGLINE)[3] - tag_font.getbbox(THUMB_TAGLINE)[1]

    # Lay the block out from the bottom up: tagline, then a rule above it,
    # then the title. Each spacing is a named constant so a longer title
    # cannot silently collide with the tagline the way it did on the first
    # render -- the whole block moves up instead.
    rule_h = 6
    tag_to_rule = 20        # tagline baseline area up to the rule
    rule_to_title = 22      # rule up to the title's last line
    block_h = sum(heights) + gap * (len(THUMB_TITLE) - 1)

    tag_top = H - margin - tag_h
    rule_y = tag_top - tag_to_rule - rule_h
    y = rule_y - rule_to_title - block_h

    for i, (line, font, h) in enumerate(zip(THUMB_TITLE, fonts, heights)):
        colour = ACCENT_SOFT if i == 1 else TEXT_PRIMARY
        shadowed_text(img, (margin, y - font.getbbox(line)[1]), line, font, colour)
        y += h + gap

    ImageDraw.Draw(img).rectangle(
        (margin, rule_y, margin + 96, rule_y + rule_h), fill=ACCENT_MID
    )

    shadowed_text(img, (margin, tag_top - tag_font.getbbox(THUMB_TAGLINE)[1]),
                  THUMB_TAGLINE, tag_font, TEXT_PRIMARY, blur=4)

    out = OUT_DIR / "thumbnail_630x500.jpg"
    img.convert("RGB").save(out, quality=92, optimize=True)
    return out


def make_cover():
    W, H = 1280, 720
    img = cover_art((W, H))
    scrim(img, (0, 0, int(W * 0.62), H), opacity=155, feather=110)

    margin = 64
    avail = int(W * 0.55)

    # Title
    fonts = [fit_font(FONT_BLACK, line, avail, 84) for line in COVER_TITLE]
    y = 110
    for i, (line, font) in enumerate(zip(COVER_TITLE, fonts)):
        colour = ACCENT_SOFT if i == len(COVER_TITLE) - 1 else TEXT_PRIMARY
        bbox = font.getbbox(line)
        shadowed_text(img, (margin, y - bbox[1]), line, font, colour, blur=8)
        y += bbox[3] - bbox[1] + 14

    ImageDraw.Draw(img).rectangle((margin, y + 4, margin + 155, y + 12),
                                  fill=ACCENT_MID)
    y += 52

    # Subtitle
    sub_font = ImageFont.truetype(FONT_BOLD, 34)
    for line in COVER_SUBTITLE:
        bbox = sub_font.getbbox(line)
        shadowed_text(img, (margin, y - bbox[1]), line, sub_font, TEXT_PRIMARY, blur=5)
        y += bbox[3] - bbox[1] + 14
    y += 30

    # Bullets
    bullet_font = ImageFont.truetype(FONT_SEMIBOLD, 30)
    for text, colour in COVER_BULLETS:
        bbox = bullet_font.getbbox(text)
        h = bbox[3] - bbox[1]
        draw_bullet(ImageDraw.Draw(img), margin, y + 4, h * 0.68, ACCENT_MID)
        shadowed_text(img, (margin + 34, y - bbox[1]), text, bullet_font,
                      colour, blur=4)
        y += h + 22

    # Footer
    foot_font = ImageFont.truetype(FONT_SEMIBOLD, 24)
    fb = foot_font.getbbox(COVER_FOOTER)
    shadowed_text(img, (margin, H - margin + 10 - fb[3]), COVER_FOOTER,
                  foot_font, TEXT_SECONDARY, blur=4)

    out = OUT_DIR / "cover_1280x720.jpg"
    img.convert("RGB").save(out, quality=92, optimize=True)
    return out


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    for path in (make_thumbnail(), make_cover()):
        size = Image.open(path).size
        print(f"wrote {path.name}  {size[0]}x{size[1]}  "
              f"{path.stat().st_size // 1024} KB")
