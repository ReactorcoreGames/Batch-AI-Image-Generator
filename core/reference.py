"""Style reference image — the whole decision layer, in one place.

A single global reference image applied to every prompt in a batch, on the
models that can accept a LOCAL file. Read docs/reference-image-plan.md for the
measurements; the short version is that the "reference fields are a permanent
skip" ruling was PARTIALLY REVERSED on 2026-09-19, because both premises
behind it (editing-only, hosted-URL-only) proved false for part of the lineup.

*** EVERY VERDICT LIVES HERE, NOT IN THE GUI. ***
The GUI status label, `cli dry-run` and the engine all consume the same
`PreparedReference` rather than each computing their own answer. A label that
says "will be upscaled to 1024x1024" while the engine sends something else is
exactly the failure this structure exists to prevent.

Nothing here touches the network, and nothing here modifies the user's file:
`prepare()` reads it and returns bytes in memory.

The numbers, all MEASURED 2026-09-19 on flux-2-klein-4b against the live API:

  * There is NO 512x512 maximum, whatever Cloudflare's changelog says.
    640x480, 1024x1024, 2048x2048 and 4096x4096 all returned HTTP 200.
  * There IS an undocumented 64px minimum, PER SIDE. Bisected exactly: 63x63
    rejected, 64x64 accepted; 64x48 rejected, so it binds on each dimension
    rather than on the total or the longest edge.
  * Rejection is a generic HTTP 400 `AiError: Invalid input` (code 8001)
    naming neither the field nor the size -- which is precisely why the check
    has to happen here, before the request leaves.
  * PNG, JPEG and WebP are all accepted. No square requirement.
  * Reference size does NOT affect generation latency (4.2-4.9s across
    512/1024/2048/4096px refs at a fixed 1536x864 output), so an oversized
    reference costs upload bandwidth and nothing else.
"""

from __future__ import annotations

import hashlib
import io as _io
from dataclasses import dataclass, field
from pathlib import Path

# The ~1 MP target. NO VENDOR PUBLISHES ONE -- checked across Cloudflare, BFL,
# fal.ai, Replicate and the FLUX.2 model cards. The community has, and it is
# traceable to code: ComfyUI's PREFERED_KONTEXT_RESOLUTIONS (nodes_flux.py,
# adopted by InvokeAI and others) is 17 sizes, every one of them within 2.8%
# of ~1.05 MP, every one a multiple of 16, and spanning exactly 3:7 to 7:3.
# That one table supplies the target, the divisibility convention AND the
# aspect window below. Independently corroborated: the standard ComfyUI FLUX.2
# reference workflow scales inputs to 1 megapixel via ImageScaleToTotalPixels.
#
# COMMUNITY-DERIVED and CROSS-FAMILY (FLUX.1 Kontext guidance applied to
# FLUX.2 and nano-banana). A good default, not a law -- do not present it to
# the user as official.
TARGET_PIXELS = 1_050_000

# The hard floor, measured (see the module docstring). Per side.
MIN_DIMENSION = 64

# NOT the documented ceiling, and not the measured one either: 4096x4096 was
# accepted. This is the program's own cap, because ACCEPTED IS NOT
# RECOMMENDED -- the same lesson the SDXL training-size guidance taught.
# black-forest-labs/flux2 issue #42 reports >4000px inputs producing output
# "heavily blurred or degrad[ing] into noise-like artifacts", unfixed by
# raising steps and with no maintainer reply; and the latency measurement
# found no benefit whatsoever above ~1 MP. So: never send 4096.
MAX_DIMENSION = 2048

# 3:7 .. 7:3, exactly the span of PREFERED_KONTEXT_RESOLUTIONS, and separately
# corroborated by the repeated "Flux supports aspect ratios from 3:7 to 7:3".
MIN_ASPECT = 3 / 7          # 0.4286
MAX_ASPECT = 7 / 3          # 2.3333

# How close two ratios must be before the program stops mentioning the
# difference. A 1024x1024 reference against a 1:1 output should read as fine
# rather than being pedantically flagged over rounding.
RATIO_TOLERANCE = 0.10

# Pixel-art auto-detection thresholds. MEASURED 2026-09-19 on synthetic cases,
# and the separation is wide rather than marginal:
#
#     input                        distinct colours   half-scale round trip
#     32x32 pixel art                             4                  0.000
#     pixel art upscaled 16x                      4                  0.000
#     pixel art saved as JPEG q85                22                  0.041
#     512x512 photo gradient                 97,537                  0.529
#
# Two cheap signals: the distinct COLOUR COUNT, and whether the image survives
# a nearest half-downscale/upscale ROUND TRIP unchanged (true only of an image
# built from uniform blocks). Even pixel art mangled through JPEG stays
# clearly on the pixel-art side, which is the case naive detection breaks on.
#
# NEITHER SIGNAL ALONE IS SUFFICIENT, and the plan's suggestion to follow the
# round trip when they disagree turned out to be wrong in one direction --
# found by testing rather than by reading. A smooth gradient passes the round
# trip with 0.004 (it has no detail to lose, so halving and doubling changes
# nothing) while holding ~196,000 colours, and nearest is flatly wrong for it.
# So the COLOUR COUNT carries the veto: see detect_pixel_art().
PIXEL_ART_MAX_COLOURS = 256
PIXEL_ART_MAX_ROUND_TRIP = 0.10

# The resampler modes the user can pick. Three states rather than a checkbox:
# auto-detection is measured to be reliable, so a checkbox would make every
# user answer a question the program can usually answer itself -- but the
# manual options stay, because detection CAN be wrong and the user knows
# their own file.
RESAMPLE_MODES: tuple[str, ...] = ("auto", "nearest", "lanczos")
DEFAULT_RESAMPLE = "auto"
RESAMPLE_LABELS: dict[str, str] = {
    "auto": "Auto (detect pixel art)",
    "nearest": "Pixel art (nearest)",
    "lanczos": "Photo (lanczos)",
}

# Formats confirmed accepted as a reference part. Sniffed on the way in by
# Pillow rather than trusted from the extension.
ACCEPTED_FORMATS: tuple[str, ...] = ("png", "jpeg", "webp")

# What a prepared reference is encoded AS when it is sent. Everything is
# re-encoded to PNG: it is lossless (so a nearest upscale is not immediately
# undone by JPEG ringing on the hard edges it exists to preserve), it is
# accepted by every model in the feature, and it makes the content hash a
# function of the PIXELS rather than of the source file's compression.
WIRE_FORMAT = "png"
WIRE_CONTENT_TYPE = "image/png"
WIRE_FILENAME = "reference.png"


class ReferenceError(ValueError):
    """The chosen file cannot be used, with a message the user can act on.

    The message always names the ACTUAL NUMBERS and the remedy. "Unsupported
    aspect ratio" tells a user nothing; "384x32 is 12:1 — the widest usable is
    about 7:3. Crop one frame, or tile the strip into a grid" tells them what
    to do next.
    """


@dataclass
class PreparedReference:
    """Everything the GUI, the CLI and the provider need, computed once.

    `data` is what actually goes on the wire, so `content_hash` is taken over
    it rather than over the source file -- see hash_part().
    """

    path: Path
    data: bytes
    width: int                  # the size being SENT
    height: int
    source_width: int
    source_height: int
    source_format: str
    resampler: str              # "nearest" | "lanczos" | "" (unchanged)
    resampler_reason: str       # why that one, in the user's words
    transform: str              # "none" | "upscale" | "downscale"
    scale_factor: float
    detected_pixel_art: bool | None   # None when detection was not consulted
    warnings: list[str] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        """A hash of the BYTES BEING SENT, never of the path.

        The path would be the same failure shape as the style-suffix bug this
        program has already fixed once: swap a different sprite in under the
        same filename and a path-keyed identity would reattach to the finished
        batch, find the old files on disk and generate nothing, silently.

        Hashing the prepared bytes also covers the resampler choice for free
        -- it changes the bytes -- which is why the mode is deliberately NOT a
        separate hash part.
        """
        return hashlib.blake2b(self.data, digest_size=8).hexdigest()

    @property
    def size_text(self) -> str:
        return f"{self.width}x{self.height}"

    @property
    def source_size_text(self) -> str:
        return f"{self.source_width}x{self.source_height}"

    def describe(self) -> str:
        """One line stating the TRANSFORMATION, not just the file.

        The transformation is the surprising part: a user who drags in a
        16x16 sprite needs to know it is being sent at 1024x1024.
        """
        if self.transform == "none":
            return (f"{self.source_size_text} {self.source_format.upper()}. "
                    f"Sent as-is — already a usable size.")
        verb = "upscaled" if self.transform == "upscale" else "downscaled"
        factor = ""
        if self.transform == "upscale" and float(self.scale_factor).is_integer():
            factor = f" {int(self.scale_factor)}x"
        return (f"{self.source_size_text} → {verb}{factor} to {self.size_text} "
                f"({self.resampler}, {self.resampler_reason}). "
                f"Sent at {self.size_text}.")


def hash_part(prepared: "PreparedReference | None") -> str | None:
    """The reference's contribution to the image identity hash.

    None when no reference is in use, which is what keeps every batch made
    before this feature resuming exactly as it did: the parts are joined with
    a separator and None renders as empty, so appending this at the END of the
    list leaves an unchanged run's digest unchanged.
    """
    return prepared.content_hash if prepared is not None else None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _round_trip_diff(im) -> float:
    """Mean per-channel difference after a nearest half-down/up round trip.

    NORMALISED TO 0..1, which is the scale the measured thresholds are on.
    Pillow's ImageStat returns a 0..255 mean, and leaving it there made the
    threshold ~25x stricter than intended -- pixel art saved as JPEG scored
    6.01 against a 0.10 cutoff and was classified as a photo, the exact case
    the two-signal design exists to get right. Caught by a test, which is why
    the division is spelled out rather than folded into the constant.

    0.0 means every 2x2 block was uniform, i.e. the image is built from flat
    blocks -- pixel art, or a nearest-upscaled sprite. A photo scores ~0.5.
    Deliberately cheap: one downscale, one upscale, one difference.
    """
    from PIL import Image, ImageChops, ImageStat

    w, h = im.size
    if w < 2 or h < 2:
        return 0.0
    rgb = im.convert("RGB")
    small = rgb.resize((max(1, w // 2), max(1, h // 2)), Image.NEAREST)
    back = small.resize((w, h), Image.NEAREST)
    diff = ImageChops.difference(rgb, back)
    return sum(ImageStat.Stat(diff).mean) / 3.0 / 255.0


def detect_pixel_art(im) -> tuple[bool, str]:
    """(is_pixel_art, human-readable reason).

    Two signals, and they disagree only on the awkward middle ground. Where
    they do, FOLLOW THE ROUND TRIP: mis-applying LANCZOS to a sprite is the
    visible failure -- it blurs the hard edges that are the entire style being
    referenced -- while treating a photo as pixel art costs a slightly harder
    resize nobody will notice at 1 MP.
    """
    colours = im.convert("RGB").getcolors(maxcolors=PIXEL_ART_MAX_COLOURS)
    few_colours = colours is not None
    diff = _round_trip_diff(im)
    blocky = diff < PIXEL_ART_MAX_ROUND_TRIP

    if blocky and few_colours:
        return True, f"detected pixel art — {len(colours)} colours, flat blocks"
    if few_colours:
        # Few colours but real edge detail: pixel art that has been through
        # JPEG, where the ringing around every hard edge pushes the round
        # trip up while the palette stays tiny. This is the case naive
        # detection breaks on, and the colour count is what rescues it.
        return True, f"detected pixel art — {len(colours)} colours"
    if blocky:
        # Blocky but tens of thousands of colours: a smooth gradient, a soft
        # render, an out-of-focus photo. It survives a half-scale round trip
        # because it has no detail to lose, NOT because it is built from
        # blocks -- and nearest would be the wrong choice for it.
        #
        # Which is why the colour count gets the veto here rather than the
        # round trip: a flat gradient and a sprite look identical to the
        # round trip alone, and only the palette tells them apart.
        return False, "smooth gradient — treated as artwork"
    return False, f"detected photo or artwork — {diff:.2f} edge detail"


# ---------------------------------------------------------------------------
# The resize ladder
# ---------------------------------------------------------------------------

def _best_integer_upscale(w: int, h: int) -> int:
    """The largest integer factor that does not overshoot the ~1 MP target.

    INTEGER, and that is load-bearing. An image is upscaled here because it is
    BELOW the 64px floor, which means it is tiny, which means it is almost
    certainly pixel art -- and a fractional scale reintroduces exactly the
    blur NEAREST was chosen to avoid, by landing sample points between source
    pixels. A 16x16 sprite therefore becomes a crisp 1024x1024 at 64x.

    Where no integer factor lands near the target (a 300x300 input: 3x is
    0.81 MP, 4x overshoots at 1.44 MP), take the largest non-overshooting
    factor and STOP. Do not follow it with a fractional correction -- that
    trades away the exact pixel edges to gain a few percent of a target that
    is itself a community convention rather than a rule.
    """
    factor = 1
    while True:
        nxt = factor + 1
        if (w * nxt) * (h * nxt) > TARGET_PIXELS:
            break
        if w * nxt > MAX_DIMENSION or h * nxt > MAX_DIMENSION:
            break
        factor = nxt
    # The floor still has to be cleared even if clearing it overshoots the
    # target: an image below 64px on a side is rejected outright by the API,
    # so a too-small result is not a compromise, it is a failure.
    while w * factor < MIN_DIMENSION or h * factor < MIN_DIMENSION:
        factor += 1
    return factor


def _downscale_size(w: int, h: int) -> tuple[int, int]:
    """Fit to ~1 MP and to the 2048/side cap, each side a multiple of 16.

    MULTIPLES OF 16, per the plan's computed table: a 1280x1280 sheet lands on
    1024x1024, not the 1025x1025 that rounding sqrt(1.05 MP) gives. Each side
    snaps to its NEAREST multiple, so the ratio moves by at most ~1% (4:3 ->
    1184x880); a side snapped up past the target is taken back down a step.

    No padding, no stretching, no letterboxing -- anything outside the
    3:7..7:3 window was already rejected at step 0, so the two guards never
    fight: the ratio check owns shape, and this owns size.
    """
    scale = (TARGET_PIXELS / (w * h)) ** 0.5
    scale = min(scale, MAX_DIMENSION / w, MAX_DIMENSION / h)
    nw = max(MIN_DIMENSION, round(w * scale / 16) * 16)
    nh = max(MIN_DIMENSION, round(h * scale / 16) * 16)
    # Snapping both sides up can overshoot the target; shed 16 from whichever
    # side gained the most. MIN_DIMENSION and MAX_DIMENSION are both multiples
    # of 16, so neither clamp can break the rule.
    while nw * nh > TARGET_PIXELS:
        if nw / (w * scale) >= nh / (h * scale) and nw > MIN_DIMENSION:
            nw -= 16
        elif nh > MIN_DIMENSION:
            nh -= 16
        else:
            break
    return nw, nh


def check_aspect(width: int, height: int) -> None:
    """Raise ReferenceError if the shape is outside 3:7 .. 7:3.

    REJECT, DO NOT "FIX". Neither automatic correction is acceptable:
    stretching distorts every frame of a sprite strip, and padding a 12:1
    strip out to 7:3 wastes most of the canvas and shrinks the actual sprite
    content toward illegibility. So the program refuses and states the remedy
    -- which is also the better style reference, because a row of
    near-identical animation frames teaches the model less than a varied grid.

    Single sprites and square-ish sheets pass (16x16, 16x32, even a 256x256
    sheet); horizontal animation strips fail -- and a strip is exactly what a
    user might plausibly drag in.
    """
    if width <= 0 or height <= 0:
        raise ReferenceError("that image has no pixels")
    ratio = width / height
    if MIN_ASPECT <= ratio <= MAX_ASPECT:
        return
    if ratio > MAX_ASPECT:
        shape = f"{ratio:.3g}:1"
        limit = "about 7:3 (2.33:1)"
        fix = ("Crop one frame out of it, or tile the strip into a grid — a "
               "varied square sheet is a better style reference than a row of "
               "near-identical frames anyway.")
    else:
        shape = f"1:{1 / ratio:.3g}"
        limit = "about 3:7 (1:2.33)"
        fix = ("Crop it, or tile it into a grid — a squarer image is both "
               "usable and a better style reference.")
    raise ReferenceError(
        f"{width}x{height} is {shape} — too far from square to use. The "
        f"widest usable shape is {limit}. {fix}")


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def prepare(path: str | Path, resample: str = DEFAULT_RESAMPLE,
            output_size: tuple[int, int] | None = None) -> PreparedReference:
    """Read, validate and resize a reference image. Never touches the source.

    `output_size` is optional and affects ONLY the advisory ratio note -- a
    reference whose shape differs from the batch's output shape is fine, and
    the model simply re-frames. That is a WARNING, never a refusal; only the
    3:7..7:3 window is a hard stop, because that is about the model being
    unable to use the image at all.

    Raises ReferenceError with an actionable message for anything unusable:
    a missing file, an unreadable one, or a shape outside the window.
    """
    from PIL import Image, UnidentifiedImageError

    if resample not in RESAMPLE_MODES:
        raise ReferenceError(
            f"unknown resampler {resample!r}; expected one of "
            + ", ".join(RESAMPLE_MODES))

    p = Path(path)
    if not p.exists():
        raise ReferenceError(f"file not found: {p}")
    if not p.is_file():
        raise ReferenceError(f"not a file: {p}")

    try:
        with Image.open(p) as opened:
            source_format = (opened.format or "").lower()
            mode = "RGBA" if "A" in opened.getbands() else "RGB"
            im = opened.convert(mode)
    except UnidentifiedImageError as e:
        raise ReferenceError(
            f"not a readable image: {p.name}. PNG, JPEG and WebP all work."
        ) from e
    except OSError as e:
        raise ReferenceError(f"could not read {p.name}: {e}") from e

    sw, sh = im.size
    check_aspect(sw, sh)

    detected: bool | None = None
    if resample == "auto":
        detected, reason = detect_pixel_art(im)
    else:
        reason = "your choice"

    warnings: list[str] = []
    resampler = ""
    transform = "none"
    scale_factor = 1.0
    out = im

    if sw < MIN_DIMENSION or sh < MIN_DIMENSION:
        # Step 1: below the floor. UPSCALE by an INTEGER factor.
        #
        # The default here is NEAREST, and the reasoning is the whole point of
        # the ladder: an image is in this branch because it is smaller than
        # 64px on a side, which means it is tiny, which means it is almost
        # certainly pixel art. Smooth resampling would blur the hard pixel
        # edges that ARE the style being referenced, handing the model a mush
        # of the thing the user wanted.
        factor = _best_integer_upscale(sw, sh)
        scale_factor = float(factor)
        transform = "upscale"
        use_nearest = detected if resample == "auto" else (resample == "nearest")
        resampler = "nearest" if use_nearest else "lanczos"
        out = im.resize((sw * factor, sh * factor), _pil_filter(resampler))
        warnings.append(
            f"{sw}x{sh} is below the {MIN_DIMENSION}px minimum these models "
            f"accept, so it is enlarged {factor}x to "
            f"{sw * factor}x{sh * factor} before it is sent.")
    elif sw * sh > TARGET_PIXELS or sw > MAX_DIMENSION or sh > MAX_DIMENSION:
        # Step 2: above the target. DOWNSCALE -- LANCZOS by default, since
        # anything over 1 MP is a photo, a render or a large artwork.
        nw, nh = _downscale_size(sw, sh)
        transform = "downscale"
        scale_factor = nw / sw if sw else 1.0
        use_nearest = detected if resample == "auto" else (resample == "nearest")
        resampler = "nearest" if use_nearest else "lanczos"
        out = im.resize((nw, nh), _pil_filter(resampler))
    else:
        # Step 3: already in the window. Leave the pixels exactly alone.
        #
        # The DETECTION reason is discarded here on purpose: nothing was
        # resampled, so naming a resampler would describe a decision that was
        # never acted on. The status label says "sent as-is" and that is the
        # whole truth of this branch.
        reason = "no resizing needed"

    buf = _io.BytesIO()
    # Re-encoded to PNG rather than passed through: lossless, so a nearest
    # upscale is not immediately undone by JPEG ringing on the very edges it
    # was chosen to preserve, and the content hash then describes the pixels
    # rather than the source file's compression settings.
    out.save(buf, format="PNG")
    data = buf.getvalue()

    prepared = PreparedReference(
        path=p,
        data=data,
        width=out.size[0],
        height=out.size[1],
        source_width=sw,
        source_height=sh,
        source_format=source_format or "image",
        resampler=resampler,
        resampler_reason=reason,
        transform=transform,
        scale_factor=scale_factor,
        detected_pixel_art=detected,
        warnings=warnings,
    )

    if output_size:
        note = ratio_note(prepared, *output_size)
        if note:
            prepared.warnings.append(note)
    return prepared


def _pil_filter(name: str):
    from PIL import Image
    return Image.NEAREST if name == "nearest" else Image.LANCZOS


def ratio_note(prepared: PreparedReference, out_w: int, out_h: int) -> str:
    """The advisory note when the reference's shape differs from the output's.

    A WARNING, never a refusal, and it states the CONSEQUENCE rather than the
    verdict. "Aspect ratio mismatch" is a verdict; "your reference is 1:1 but
    you are generating 16:9, so the model will re-frame the composition" tells
    the user what will actually happen -- and wanting that is perfectly
    reasonable, because the reference carries STYLE while the output ratio
    carries COMPOSITION.
    """
    if out_h <= 0 or prepared.height <= 0:
        return ""
    ref = prepared.width / prepared.height
    out = out_w / out_h
    if abs(ref - out) <= RATIO_TOLERANCE * max(ref, out):
        return ""
    return (
        f"Your reference is {_ratio_words(prepared.width, prepared.height)} "
        f"but you are generating {_ratio_words(out_w, out_h)} — the model will "
        f"re-frame the composition. The style still transfers.")


def _ratio_words(w: int, h: int) -> str:
    """A ratio as a human would say it, matching a named one where close."""
    if h <= 0:
        return f"{w}x{h}"
    r = w / h
    for name, value in (("1:1", 1.0), ("16:9", 16 / 9), ("3:2", 1.5),
                        ("4:3", 4 / 3), ("2:3", 2 / 3), ("9:16", 9 / 16),
                        ("3:4", 0.75)):
        if abs(r - value) <= 0.03 * value:
            return name
    return f"{r:.2f}:1" if r >= 1 else f"1:{1 / r:.2f}"


# ---------------------------------------------------------------------------
# Influence: a sentence added to the end of every prompt (added 2026-10-15)
#
# NO MODEL IN THE FEATURE EXPOSES A STRENGTH FIELD. klein's whole field list
# is prompt, width, height, guidance, seed and input_image_0..3; nano-banana
# and flux-2-pro have nothing either. The one per-image `strength` in the
# lineup is krea's, and krea cannot take a local file at all. So the prompt
# text is the only lever there is, and this setting writes that text for the
# user instead of making them type "in the style of image 0" every time.
#
# These are WORDS, not weights. A level is a request the model may follow
# loosely, and nothing here should be presented to the user as a percentage
# or a dial.
#
# Off by default, so every batch that existed before this setting keeps its
# final prompt -- and therefore its filename hash and its batch identity --
# byte for byte.
# ---------------------------------------------------------------------------

# The five levels and their exact wording were CHOSEN BY THE USER 2026-10-15,
# replacing a measured Off/Style/Strong set, on the reasoning that short plain
# sentences beat long specific ones. Untested by decision. The earlier
# measurement (findings.md) still stands as background: the reference alone
# does most of the work, and wording nudges rather than grades.
#
# There is no "off" any more: every level, None included, sends a sentence
# whenever a reference is in use. "none" is the default because it is the
# least directive -- but it is NOT "prompt unchanged".
INFLUENCE_MODES: tuple[str, ...] = ("none", "subtle", "medium", "heavy",
                                    "exact")
DEFAULT_INFLUENCE = "none"
INFLUENCE_LABELS: dict[str, str] = {
    "none": "None",
    "subtle": "Subtle",
    "medium": "Medium",
    "heavy": "Heavy",
    "exact": "Exact",
}

# `{ref}` is the model's own name for the reference -- ModelSpec's
# reference_prompt_name, "image 0" on klein. Edit the wording HERE; nothing
# else holds a copy of it.
INFLUENCE_TEMPLATES: dict[str, str] = {
    "none": "No influence from {ref}.",
    "subtle": "Subtle influences from {ref}.",
    "medium": "Medium influence from {ref}.",
    "heavy": "Heavy influence from {ref}.",
    "exact": "Exact style as {ref}.",
}


def influence_phrase(mode: str | None, spec) -> str:
    """The sentence this mode adds for this model, or "".

    "" for an unknown mode, and for a model with no reference field
    -- a phrase naming "image 0" sent to a model that was never given one
    would point the model at nothing.
    """
    template = INFLUENCE_TEMPLATES.get(mode or "")
    if template is None or spec.reference_field is None:
        return ""
    return template.format(ref=spec.reference_prompt_name)


def with_influence(text: str, phrase: str) -> str:
    """`text` with the influence phrase appended, or `text` unchanged.

    Never edits the user's text: it only chooses a joiner. A prompt that ends
    mid-sentence gets a full stop so the phrase does not run on into it; one
    that already ends in punctuation (including a keyword list's comma) is
    joined with a plain space. That makes the added part exactly
    `result[len(text):]`, which is what the GUI preview relies on to colour it.
    """
    if not phrase:
        return text
    stripped = text.rstrip()
    if not stripped:
        return phrase
    joiner = " " if stripped[-1] in ".!?,;:" else ". "
    return stripped + joiner + phrase
