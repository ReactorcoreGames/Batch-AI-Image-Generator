"""Model capability registry — pure data and pure functions, no I/O.

Everything else in the app reads from here. Nothing about a model's dimensions,
encoding, or price is hardcoded anywhere else.

All values are the measured/verified ones from CLAUDE.md and spike/SPIKE_RESULTS.md.
Where the two disagreed, the measurement won.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

RequestEncoding = Literal["json", "multipart"]
# json_data_uri is the Pruna/gateway shape and is NOT interchangeable with
# json_base64 despite sharing the result.image field path: gateway models
# return a full `data:image/jpeg;base64,...` URI where klein returns bare
# base64. Decoding one as the other yields garbage, not an error.
# json_url is the krea shape: result.image is a PRESIGNED URL, not image data
# at all, so fetching it costs a second HTTP request. This is the extra-GET
# mechanic the wishlist doc predicted for p-image -- it was wrong about which
# family needed it, but right that one would.
ResponseEncoding = Literal["raw", "json_base64", "json_data_uri", "json_url"]

# How the model is addressed. Native models put the model id in the URL path;
# gateway models put it in the request BODY at the bare /ai/run endpoint.
# Verified 2026-09-04 against the live API at zero cost.
CallStyle = Literal["native", "gateway"]

# How a model expresses the size it wants. The native five take exact pixels;
# every gateway family speaks something different, and the tile-optimal SIZES
# table is meaningless for the ones that do not take pixels at all.
SizeStyle = Literal["pixels", "aspect_ratio", "aspect_ratio_resolution", "size_enum"]

TILE = 512  # Cloudflare bills per 512x512 tile.


# ---------------------------------------------------------------------------
# Size table — verbatim from CLAUDE.md. Every entry is exact-ratio,
# a multiple of 16, and the LARGEST size that still fits its tile count.
# Do not recompute these naively: 1280x720 wastes 44% of the tile budget
# that 1536x864 uses for exactly the same price.
# ---------------------------------------------------------------------------

Tier = Literal["draft", "standard", "high"]
TIERS: tuple[Tier, ...] = ("draft", "standard", "high")
RATIOS: tuple[str, ...] = ("16:9", "3:2", "1:1", "2:3", "9:16")

# What a tier MEANS, independent of any model. The tier names are a
# program-wide vocabulary describing an INTENT, not an absolute pixel promise:
# klein's Draft is 768x432 while Recraft's Standard is 1344x768, and on
# nano-banana-2 the tier moves the price rather than only the size. The
# per-model specifics are appended by tier_description(); these stay generic
# precisely so they remain true for every model.
# Two sets, because "cheapest" is a LIE on a flat-priced model. Most of the
# gateway lineup charges the same for every size, so a Draft image there costs
# exactly what a High one does -- telling the user otherwise would push them
# toward a smaller image for a saving that does not exist.
TIER_INTENT_PRICED: dict[Tier, str] = {
    "draft":    "Draft — smallest and cheapest",
    "standard": "Standard — the normal choice",
    "high":     "High — largest, and costs the most",
}
TIER_INTENT_FLAT: dict[Tier, str] = {
    "draft":    "Draft — smallest",
    "standard": "Standard — the normal choice",
    "high":     "High — largest, at the same price",
}
# A free model has no price to be flat, so "at the same price" is a strange
# thing to tell someone paying nothing. Size and speed are the only trade
# there, which is what these say.
TIER_INTENT_FREE: dict[Tier, str] = {
    "draft":    "Draft — smallest and fastest",
    "standard": "Standard — the normal choice",
    "high":     "High — largest and slowest",
}

SIZES: dict[str, dict[Tier, tuple[int, int]]] = {
    "16:9": {"draft": (768, 432),  "standard": (1536, 864),  "high": (2048, 1152)},
    "3:2":  {"draft": (768, 512),  "standard": (1536, 1024), "high": (2016, 1344)},
    "1:1":  {"draft": (512, 512),  "standard": (1024, 1024), "high": (1536, 1536)},
    "2:3":  {"draft": (512, 768),  "standard": (1024, 1536), "high": (1344, 2016)},
    "9:16": {"draft": (432, 768),  "standard": (864, 1536),  "high": (1152, 2048)},
}

# The High tier as tabled tops out at 2048, but klein's hard ceiling is 1920 --
# and klein is the ONLY family that handles High properly (SD degrades above
# ~1024). Taken literally the High tier would therefore be reachable by no model
# at all: 16:9 High is 2048x1152, which SD renders badly and klein rejects
# outright. These are the largest exact-ratio, multiple-of-16 sizes inside
# klein's 256-1920 range, substituted automatically for klein at High.
#
# 1:1 stays at the tabled 1536x1536: klein accepts it, and the largest legal
# square (1920x1920) is 16 tiles against 9, so it would cost noticeably more
# rather than being the free headroom every other High entry is.
SIZES_KLEIN_HIGH: dict[str, tuple[int, int]] = {
    "16:9": (1792, 1008),   # 8 tiles
    "3:2":  (1920, 1280),   # 12 tiles
    "1:1":  (1536, 1536),   # 9 tiles (tabled size; klein accepts it)
    "2:3":  (1280, 1920),   # 12 tiles
    "9:16": (1008, 1792),   # 8 tiles
}


# p-image's custom path caps at 1440 -- lower than klein's 1920 and well below
# the tabled High sizes. These are the largest exact-ratio, multiple-of-16
# sizes inside its 256-1440 range. Note 1:1 CANNOT keep the tabled 1536x1536
# here (klein could): 1440x1440 is the largest legal square.
#
# Standard 16:9 (1536x864) is ALSO over the cap, so p-image substitutes at
# Standard too, not just at High -- the only model in the lineup that does.
# COMPUTED, not eyeballed: the x16 rule bites harder than the 1440 cap does.
# 16:9 tops out at 1280x720 -- NOT 1440x810, because 810 is not a multiple of
# 16. Checking this cost nothing and caught a wrong table; do the same for any
# model added later. (Verify with: largest k where 16k and 9k are both <=1440
# and both %16==0.)
#
# Consequence worth knowing: p-image's best 16:9 is 1280x720, SMALLER than the
# program's Standard 16:9 of 1536x864. The "generate large, downscale locally"
# workflow does not apply here, and the UI says so.
SIZES_PIMAGE: dict[str, dict[Tier, tuple[int, int]]] = {
    "16:9": {"draft": (768, 432),  "standard": (1280, 720),  "high": (1280, 720)},
    "3:2":  {"draft": (768, 512),  "standard": (1440, 960),  "high": (1440, 960)},
    "1:1":  {"draft": (512, 512),  "standard": (1024, 1024), "high": (1440, 1440)},
    "2:3":  {"draft": (512, 768),  "standard": (960, 1440),  "high": (960, 1440)},
    "9:16": {"draft": (432, 768),  "standard": (720, 1280),  "high": (720, 1280)},
}

# krea is locked to resolution="1K" -- the validator accepts no other value --
# so it has ONE size per ratio and no tier ladder at all. Draft, Standard and
# High are therefore identical for every ratio, and the GUI says so rather
# than leaving a dropdown that silently does nothing.
#
# UNVERIFIED, and deliberately so: Krea does not publish the pixel dimensions
# "1K" resolves to at each ratio, and it could not be probed without spending.
# These are ~1 megapixel at the exact ratio, rounded to multiples of 16, which
# is the standard reading of "1K" -- but they are an ESTIMATE used only for the
# size readout and the megapixel figure.
#
# This is safe to be wrong about, by design: the program does NOT send
# width/height to krea (it cannot -- the model rejects them), so a wrong guess
# here cannot produce a bad request. It only affects a displayed number, and
# the TRUE dimensions are sniffed from the returned image into
# GenerationResult.actual_dimensions and written to the sidecar metadata. The
# first real run therefore self-corrects the record even though the estimate
# stays. Replace these with the measured values when someone runs one.
SIZES_KREA: dict[str, tuple[int, int]] = {
    "16:9": (1328, 752),    # 0.999 MP
    "3:2":  (1232, 816),    # 1.005 MP
    "1:1":  (1024, 1024),   # 1.049 MP -- the near-universal square "1K"
    "2:3":  (816, 1232),
    "9:16": (752, 1328),
}

# Recraft speaks a fifth size vocabulary: an opaque ENUM of "WxH" strings.
# Not aspect_ratio (which it rejects outright), and not width/height either --
# the string itself is the parameter, and the model has exactly ONE size per
# ratio at standard resolution, so there is no tier ladder here at all.
#
# *** THE ASYMMETRY THAT MAKES THIS FAMILY DANGEROUS ***
# The gateway only type-checks that `size` is a STRING and defers VALUE
# validation to Recraft itself. Every other gateway model rejects a bad
# request for free, before billing (that is how the whole field list was
# verified at zero cost). This one does not: a bad `size` value gets past the
# gateway and fails at GENERATION time, AFTER the image has been charged for.
# So the value is validated CLIENT-SIDE against this table before the request
# is ever sent -- see recraft_size_string(), which is the only place a `size`
# string may come from.
#
# Full published table (Recraft's own appendix), cross-checked 2026-09-05
# against two independent third-party API references that list the identical
# 14 entries. Only the five the program offers are wired up; the rest are
# recorded so a future ratio addition does not have to re-derive them.
#
#   1:1   1024x1024      5:4   1152x896      2:1   1536x768
#   3:2   1280x832       4:5   896x1152      1:2   768x1536
#   2:3   832x1280       6:10  832x1344      4:3   1216x896
#   16:9  1344x768       14:10 1280x896      3:4   896x1216
#   9:16  768x1344       10:14 896x1280
#
# Note the ratio LABELS are nominal, not exact: Recraft's "16:9" is 1344x768,
# which is 1.75, not 1.778. That is why the enum string is looked up by ratio
# KEY here rather than recovered by matching a numeric ratio the way krea's is.
#
# Note also that 16:9 is 1344x768 -- SMALLER than the program's Standard 16:9
# of 1536x864, for $35/1000 rather than $0-$1.72. The UI says so plainly; a
# user picking Recraft gets fewer pixels for considerably more money, and that
# is a fact about the model, not a bug to hide.
# Pollinations silently CLAMPS anything above ~589,824 px (0.5625 MP) down to
# that budget, preserving the aspect ratio, and returns HTTP 200 with NO error
# and no warning. MEASURED 2026-09-05 with cache-defeating unique prompts, on
# BOTH models, so it is a platform cap rather than a model quirk:
#
#     requested            returned
#     1024x576  (0.59 MP)  1024x576   honoured
#     1152x648  (0.75 MP)  1024x576   clamped
#     1280x720  (0.92 MP)  1024x576   clamped
#     1536x864  (1.33 MP)  1024x576   clamped
#     1024x1024 (1.05 MP)  768x768    clamped
#     1024x1536 (1.57 MP)  627x940    clamped
#
# Before this table the program asked for the shared Standard 1536x864 and
# silently received 1024x576 -- while recording 1536x864 in the sidecar JSON,
# because GenerationResult is built from the REQUESTED size. That is the same
# failure shape as the black-image content filter: HTTP 200, no error, wrong
# result. The old max_dimension of 2048 was wrong by roughly 3.5x.
#
# COMPUTED, not eyeballed (CLAUDE.md's standing rule), then VERIFIED against
# the live API: 1024x576, 936x624, 768x768 and 576x1024 were each requested
# and each came back at exactly the requested size. Every entry is the largest
# exact-ratio, multiple-of-8 size fitting its budget; Standard and High are
# both the cap, since there is nothing above it to reach for.
SIZES_POLLINATIONS: dict[str, dict[Tier, tuple[int, int]]] = {
    "16:9": {"draft": (512, 288),  "standard": (1024, 576), "high": (1024, 576)},
    "3:2":  {"draft": (456, 304),  "standard": (936, 624),  "high": (936, 624)},
    "1:1":  {"draft": (384, 384),  "standard": (768, 768),  "high": (768, 768)},
    "2:3":  {"draft": (304, 456),  "standard": (624, 936),  "high": (624, 936)},
    "9:16": {"draft": (288, 512),  "standard": (576, 1024), "high": (576, 1024)},
}

# The measured pixel budget itself, so the cap is stated once and the table
# can be checked against it by a test rather than trusted.
POLLINATIONS_MAX_PIXELS = 1024 * 576      # 589,824

# The three SD-family models degrade above roughly their ~1024px training
# size: duplicated structures, geometry drift, edge artifacts. That was always
# known -- it is what `max_safe_dimension` encodes -- but until 2026-09-06 the
# program still ASKED for 1536x864 at the default tier and merely warned about
# the result. So the shipped default produced the artifacts, and the warning
# fired on a setting the user never chose.
#
# A 13-model comparison collage made the cost obvious: the SD tiles were
# visibly the worst of the lineup, and a large part of that was the program
# handing them a size they were never trained for. The user's call was that
# reliable output at the designed size beats more pixels around a broken
# image, which is the same conclusion the Pollinations table reached from a
# different direction -- ask for what the model can actually serve.
#
# STANDARD is therefore capped at the training size. HIGH deliberately keeps
# the shared large sizes, so the ability to push past the limit still exists
# for anyone who wants it and accepts the artifacts -- the tier dropdown is
# the opt-in, and size_warnings() still fires there. DRAFT is unchanged; it
# was already well inside the safe range.
#
# COMPUTED, never eyeballed (CLAUDE.md's standing rule): each Standard entry
# is the largest exact-ratio, multiple-of-16 size with both dimensions <=1024.
# 1:1 stays 1024x1024 because that IS the training size, not despite it.
SD_MAX_SAFE_PIXELS_DIM = 1024

SIZES_SD: dict[str, dict[Tier, tuple[int, int]]] = {
    "16:9": {"draft": (768, 432), "standard": (1024, 576),  "high": (2048, 1152)},
    "3:2":  {"draft": (768, 512), "standard": (1008, 672),  "high": (2016, 1344)},
    "1:1":  {"draft": (512, 512), "standard": (1024, 1024), "high": (1536, 1536)},
    "2:3":  {"draft": (512, 768), "standard": (672, 1008),  "high": (1344, 2016)},
    "9:16": {"draft": (432, 768), "standard": (576, 1024),  "high": (1152, 2048)},
}

SIZES_RECRAFT: dict[str, tuple[int, int]] = {
    "16:9": (1344, 768),
    "3:2":  (1280, 832),
    "1:1":  (1024, 1024),
    "2:3":  (832, 1280),
    "9:16": (768, 1344),
}

# Every legal `size` value, as the strings Recraft accepts. The five above
# plus the nine ratios the program does not offer. A value not in this set is
# refused locally rather than paid for.
RECRAFT_SIZE_ENUM: frozenset[str] = frozenset({
    "1024x1024", "1280x832", "832x1280", "1344x768", "768x1344",
    "1536x768", "768x1536", "1152x896", "896x1152", "832x1344",
    "1280x896", "896x1280", "1216x896", "896x1216",
})

# Recraft's own API default for `size` is "1024x1024" -- a SQUARE, and
# therefore NOT a neutral default: omitting the field would silently give
# every image in a 16:9 batch a 1:1 crop. `size` is consequently sent ALWAYS,
# the same call made for krea's `creativity` and flux-2-pro's `output_format`.
RECRAFT_DEFAULT_SIZE = "1024x1024"


def recraft_size_string(width: int, height: int) -> str:
    """The `size` enum string for a pixel size, validated against the table.

    THE ONLY legal source of a Recraft `size` value. Raises ValueError for
    anything not in the published enum, because Recraft's value validation
    happens AFTER billing -- an unchecked bad value costs real money and
    returns nothing. Every other gateway model fails validation for free;
    this one does not, so the check has to live here.
    """
    s = f"{width}x{height}"
    if s not in RECRAFT_SIZE_ENUM:
        raise ValueError(
            f"{s} is not one of Recraft's accepted sizes. Recraft validates "
            f"`size` AFTER billing, so an unrecognised value would be charged "
            f"for and then fail. Legal values: "
            + ", ".join(sorted(RECRAFT_SIZE_ENUM))
        )
    return s


# Google's nano-banana family speaks krea's vocabulary -- aspect_ratio plus a
# resolution tier -- but with a REAL ladder behind it: `1K|2K|4K`, and on the
# full nano-banana-2 the PRICE CHANGES WITH THE TIER. It is the only family in
# the whole lineup where the Draft/Standard/High dropdown maps onto something
# that costs different money, which makes it the highest risk of a subtly
# wrong cost estimate anywhere in this program.
#
# The pixel dimensions ARE published, unlike krea's. Google documents the
# exact output size for each ratio at each tier, and every tier is an exact
# 2x of the one below it. Cross-checked 2026-09-05 against two independent
# sources listing the identical table. Still DOC-DERIVED rather than measured,
# and still never SENT -- the model takes the ratio enum and the resolution
# word, never pixels -- so these drive the displayed size and nothing else.
#
#   ratio   1K          2K          4K
#   1:1     1024x1024   2048x2048   4096x4096
#   16:9    1344x768    2688x1536   5376x3072
#   9:16    768x1344    1536x2688   3072x5376
#   3:2     1248x832    2496x1664   4992x3328
#   2:3     832x1248    1664x2496   3328x4992
#   4:3     1184x864    (not offered by this program)
#   5:4     1152x896    (not offered by this program)
#   21:9    1536x672    (not offered by this program)
#
# Note the ratio labels are NOMINAL, as on Recraft: "16:9" is 1344x768, which
# is 1.75 rather than 1.778. The enum string is therefore looked up by ratio
# KEY, never recovered by matching a numeric ratio.
NANO_BANANA_RESOLUTIONS: tuple[str, ...] = ("1K", "2K", "4K")

SIZES_NANO_BANANA: dict[str, dict[str, tuple[int, int]]] = {
    "16:9": {"1K": (1344, 768),  "2K": (2688, 1536), "4K": (5376, 3072)},
    "3:2":  {"1K": (1248, 832),  "2K": (2496, 1664), "4K": (4992, 3328)},
    "1:1":  {"1K": (1024, 1024), "2K": (2048, 2048), "4K": (4096, 4096)},
    "2:3":  {"1K": (832, 1248),  "2K": (1664, 2496), "4K": (3328, 4992)},
    "9:16": {"1K": (768, 1344),  "2K": (1536, 2688), "4K": (3072, 5376)},
}

# Which resolution word each program tier asks for. Kept as data rather than
# inlined so the two nano-banana models can differ: LITE IS PINNED TO 1K.
#
# *** THE CONFLICT, AND WHY LITE IS PINNED ***
# Cloudflare's gateway schema for nano-banana-2-lite DECLARES the full
# `1K|2K|4K` enum -- read directly off the model page 2026-09-05. But three
# independent sources say the Lite model renders 1K and nothing else
# (OpenRouter: "Outputs are generated at 1K resolution across 14 aspect
# ratios"; fal.ai: "Output images are generated at a fixed 1K (1024x1024px)";
# and a pricing breakdown noting that Google publishes a 1K per-image rate for
# Lite and NO 2K or 4K rate, unlike the models above it).
#
# So the schema accepts a value the model may not honour, and for which NO
# PRICE IS PUBLISHED. That second half is what decides it: this program's
# whole contract is that it can tell you what a batch will cost before you run
# it, and sending 2K on Lite would be a request whose price cannot be
# estimated from anything. Pinning to 1K means the quoted cost is the real one.
# UNVERIFIED by design -- it is in the Unverified table and needs one paid
# call to settle. If Lite turns out to honour 2K/4K and Google publishes the
# rates, replace this entry with the full ladder and nothing else changes.
NANO_BANANA_TIER_RESOLUTION: dict[str, dict[Tier, str]] = {
    "nano-banana-2-lite": {"draft": "1K", "standard": "1K", "high": "1K"},
    # The full model is the ONE place in the program where the tier dropdown
    # changes the bill: $67 / $101 / $151 per 1000. Mapped straight onto the
    # ladder rather than given a bespoke fourth "Ultra" tier -- the tier names
    # are a program-wide vocabulary meaning a quality INTENT, not an absolute
    # pixel promise (klein's Draft is 768x432, Recraft's Standard is 1344x768),
    # and a fourth option existing for one model in fourteen would be dead on
    # every other one. The size readout always shows the real pixels, so
    # nothing has to be inferred from the word.
    "nano-banana-2": {"draft": "1K", "standard": "2K", "high": "4K"},
}


# nano-banana-2's two extra fields, and why NEITHER is sent.
#
# RESEARCHED 2026-09-05 rather than assumed, and the answer is not "they are
# img2img-shaped" (only one of them is). They are Google Search grounding:
#
#   google_search   the model runs Google Search before generating, to ground
#                   the image in real-world fact -- live weather, current
#                   events, a real stock chart, a real landmark.
#   image_search    the model retrieves real web IMAGES via Google Image
#                   Search and uses them as visual context.
#
# *** THE REASON THEY ARE SKIPPED IS BILLING, NOT SCOPE ***
# Grounding is charged SEPARATELY from image generation: $14 per 1000 search
# queries after 5000 free per month, and Google's own docs are explicit that
# "a customer-submitted request to Gemini may result in one or more queries to
# Google Search. You will be charged for each individual search query
# performed." So a single image can trigger an unknown number of billable
# queries, on a monthly free allowance the program cannot see, through a
# Cloudflare gateway that passes the charge through.
#
# That is unpriceable by construction, and this program's contract is that it
# can quote a batch before it runs. Enabling grounding would make the cost
# estimate silently wrong by an unbounded amount on the single most expensive
# model in the lineup -- the exact failure the whole gateway effort has been
# structured to avoid. `image_search` is ALSO reference-image shaped and would
# be a permanent skip on those grounds anyway; `google_search` is skipped
# purely on cost visibility.
#
# This is a COST decision, so it is revisitable in a way the img2img skips are
# not: if the per-query charge ever becomes visible to the client, grounding
# is genuinely useful for a factual subject and could be exposed as an opt-in
# with a loud warning. It is not a permanent architectural exclusion.
NANO_BANANA_GROUNDING_FIELDS: tuple[str, ...] = ("google_search", "image_search")
NANO_BANANA_GROUNDING_USD_PER_1000_QUERIES = 14.00
NANO_BANANA_GROUNDING_FREE_QUERIES_PER_MONTH = 5000


def _nano_banana_size_table(
    tier_resolution: dict[Tier, str]
) -> dict[str, dict[Tier, tuple[int, int]]]:
    """Expand a tier->resolution mapping into the program's size table shape."""
    return {
        ratio: {t: SIZES_NANO_BANANA[ratio][tier_resolution[t]] for t in TIERS}
        for ratio in SIZES_NANO_BANANA
    }


def nano_banana_resolution(model_key: str, tier: Tier) -> str:
    """The `resolution` word to send for a program tier on a nano-banana model.

    THE ONLY legal source of the value. It is looked up rather than derived
    from the tier name because the two models in the family do not agree:
    Lite is pinned to 1K at every tier (see NANO_BANANA_TIER_RESOLUTION).
    """
    try:
        return NANO_BANANA_TIER_RESOLUTION[model_key][tier]
    except KeyError:
        raise ValueError(
            f"{model_key!r} has no nano-banana resolution mapping for tier "
            f"{tier!r}"
        ) from None


def _per_resolution(prices: dict[str, float]) -> Callable[[int, int], float]:
    """Price per image, keyed by which resolution tier the size belongs to.

    The nano-banana family is the ONE place where a bigger tier genuinely
    costs more money on a gateway model, so `_flat_per_image` is wrong here
    and quoting a single number would understate a 4K batch by up to ~2.3x.

    price_fn only ever receives pixels, so the tier is recovered from the
    size -- which is exact and unambiguous, because every entry in
    SIZES_NANO_BANANA is distinct. An unrecognised size falls back to the
    HIGHEST published price rather than the lowest: if the estimate has to be
    wrong, it must be wrong in the direction that does not surprise the user
    with a bill.
    """
    by_size: dict[tuple[int, int], float] = {}
    for per_res in SIZES_NANO_BANANA.values():
        for res, wh in per_res.items():
            if res in prices:
                by_size[wh] = prices[res]
    worst = max(prices.values())

    def f(width: int, height: int) -> float:
        return by_size.get((width, height), worst)
    return f


# Models whose size table is wholly their own rather than a High-tier
# substitution on the shared one. Keyed by ModelSpec.key.
def _fixed_size_table(
    sizes: dict[str, tuple[int, int]]
) -> dict[str, dict[Tier, tuple[int, int]]]:
    """Expand one-size-per-ratio into the tier shape the rest of the app uses.

    For a model with no tier ladder every tier maps to the same size. Building
    it this way keeps size_for() total -- callers never have to special-case
    "this model has no tiers" -- while has_tier_ladder() lets the UI explain
    why the dropdown does nothing.
    """
    return {r: {t: wh for t in TIERS} for r, wh in sizes.items()}


SIZE_TABLE_OVERRIDES: dict[str, dict[str, dict[Tier, tuple[int, int]]]] = {
    "p-image": SIZES_PIMAGE,
    "krea-turbo": _fixed_size_table(SIZES_KREA),
    "krea-medium": _fixed_size_table(SIZES_KREA),
    "recraft-utility": _fixed_size_table(SIZES_RECRAFT),
    "recraft-v41": _fixed_size_table(SIZES_RECRAFT),
    # Built from the tier->resolution mapping, so if Lite is ever unpinned
    # from 1K the table follows automatically rather than being re-entered.
    "nano-banana-2-lite": _nano_banana_size_table(
        NANO_BANANA_TIER_RESOLUTION["nano-banana-2-lite"]),
    "nano-banana-2": _nano_banana_size_table(
        NANO_BANANA_TIER_RESOLUTION["nano-banana-2"]),
    # Both Pollinations models share the platform's pixel cap.
    "poll-dreamshaper": SIZES_POLLINATIONS,
    "poll-flux": SIZES_POLLINATIONS,
    # The three SD models share their ~1024px training size. Standard is
    # capped to it; High still reaches past it on purpose. See SIZES_SD.
    "lightning": SIZES_SD,
    "sdxl": SIZES_SD,
    "dreamshaper": SIZES_SD,
}

# The program's five ratios expressed as the aspect_ratio enum strings the
# gateway models accept. Every one of the five is directly representable on
# p-image, krea and nano-banana, so no ratio is lost by switching vocabulary.
# (Those models also accept ratios the program does not offer -- 4:3, 21:9,
# 2.35:1 -- which are deliberately not exposed; the ratio list is a program-
# level choice, not a per-model one.)
RATIO_TO_ENUM: dict[str, str] = {
    "16:9": "16:9",
    "3:2":  "3:2",
    "1:1":  "1:1",
    "2:3":  "2:3",
    "9:16": "9:16",
}


def size_for(ratio: str, tier: Tier, model_key: str | None = None) -> tuple[int, int]:
    """Look up the tile-optimal size for a ratio + tier.

    When `model_key` names a model whose max dimension is below the tabled
    High-tier size, the klein-safe High size is substituted.
    """
    if model_key is not None:
        override = SIZE_TABLE_OVERRIDES.get(model_key)
        if override is not None:
            try:
                return override[ratio][tier]
            except KeyError:
                raise ValueError(
                    f"unknown ratio/tier: {ratio!r}/{tier!r}"
                ) from None
    try:
        w, h = SIZES[ratio][tier]
    except KeyError:
        raise ValueError(f"unknown ratio/tier: {ratio!r}/{tier!r}") from None
    if tier == "high" and model_key is not None:
        m = get_model(model_key)
        if max(w, h) > m.max_dimension and ratio in SIZES_KLEIN_HIGH:
            return SIZES_KLEIN_HIGH[ratio]
    return w, h


def has_tier_ladder(model_key: str) -> bool:
    """Does changing the quality tier actually change anything for this model?

    False for krea, which is locked to resolution="1K" and so serves one size
    per ratio. The UI needs this to explain a tier dropdown that would
    otherwise appear broken.
    """
    override = SIZE_TABLE_OVERRIDES.get(model_key)
    if override is None:
        return True
    for per_tier in override.values():
        distinct = {per_tier[t] for t in TIERS if t in per_tier}
        if len(distinct) > 1:
            return True
    return False


def tier_changes_price(model_key: str) -> bool:
    """Does moving the quality tier change what this model COSTS?

    True for nano-banana-2 alone, and deliberately COMPUTED from the price
    function rather than by naming that model: the day a second model bills by
    resolution, the UI follows without an edit here. Every other model in the
    lineup is either free, flat per image, or tile-priced at sizes the ratio
    already fixes -- so the tier moves pixels, not money.

    The UI needs this because a control that silently triples a bill must not
    look like the one that merely picks a size.
    """
    spec = get_model(model_key)
    if spec.is_free:
        return False
    prices = set()
    for ratio in RATIOS:
        for tier in TIERS:
            try:
                w, h = size_for(ratio, tier, model_key)
            except ValueError:
                continue
            prices.add(round(spec.cost_per_1000(w, h), 6))
    return len(prices) > 1


def tier_description(model_key: str, tier: Tier, ratio: str | None = None) -> str:
    """One line describing what a tier means FOR THIS MODEL.

    The dropdown used to carry a single hardcoded sentence per tier, written
    when the lineup was five Cloudflare-native models: "High -- biggest; klein
    models only, and ~64% slower". That is now wrong or irrelevant for most of
    the lineup, and on nano-banana-2 it is actively dangerous -- it describes a
    size while the control is silently changing the price by up to 2.3x.

    Three shapes, in order of how much the user needs to be told:
      * the tier changes the PRICE  -> lead with the price, it is the headline
      * the tier changes the SIZE   -> show the size it resolves to
      * the tier does NOTHING       -> say so; the dropdown is disabled anyway
    """
    spec = get_model(model_key)
    priced = tier_changes_price(model_key)
    if spec.is_free:
        caption = TIER_INTENT_FREE[tier]
    else:
        caption = (TIER_INTENT_PRICED if priced else TIER_INTENT_FLAT)[tier]
    if not has_tier_ladder(model_key):
        return caption
    try:
        # Defaulted here rather than in the signature: DEFAULT_RATIO is defined
        # further down this module, so a default argument would be evaluated
        # at import time and fail.
        w, h = size_for(ratio or DEFAULT_RATIO, tier, model_key)
    except ValueError:
        return caption
    if not priced:
        return f"{caption} — {w}x{h}"
    # Enough decimal places to keep two tiers from displaying as one number.
    # klein-4b runs $1.15/$2.30 across the ladder, which rounds to "$1"/"$2"
    # at zero places -- a difference the user can see but not size up, and on
    # klein-9b two tiers rounded to the SAME figure. Never let a price control
    # print two different prices identically.
    price = spec.cost_per_1000(w, h)
    money = f"${price:,.0f}" if price >= 10 else f"${price:,.2f}"
    return f"{caption} — {w}x{h}, {money} per 1000 images"


def tile_count(width: int, height: int) -> int:
    """Number of 512x512 tiles billed for a given size.

    Cost is a step function: any size inside the same tile count costs
    identically. Partial tiles round up.
    """
    return -(-width // TILE) * -(-height // TILE)


def megapixels(width: int, height: int) -> float:
    return (width * height) / 1_000_000.0


# ---------------------------------------------------------------------------
# Pricing formulas. Two shapes, and they are genuinely different:
#   * tile-flat   — price scales with tile count (klein-4b)
#   * per-MP      — price scales with megapixels (klein-9b only)
#   * free        — the three SD-family models, measured at 0 neurons
# ---------------------------------------------------------------------------

def _free(width: int, height: int) -> float:
    return 0.0


def _tile_flat(per_tile_usd: float) -> Callable[[int, int], float]:
    def f(width: int, height: int) -> float:
        return tile_count(width, height) * per_tile_usd
    return f


def _flat_per_image(per_image_usd: float) -> Callable[[int, int], float]:
    """Gateway models bill a FLAT price per image, regardless of size.

    This is the shape that breaks the tile model: Cloudflare's native models
    bill per 512x512 tile, so "generate large, downscale locally" is free
    headroom. On a gateway model it buys nothing -- the price is identical at
    every size, so the only reason to pick a size is the size you want.

    Anywhere a tile count is shown next to one of these it is meaningless and
    must be suppressed rather than displayed as a number. See
    ModelSpec.bills_per_tile.
    """
    def f(width: int, height: int) -> float:
        return per_image_usd
    return f


def _per_megapixel(base_usd: float, per_mp_usd: float) -> Callable[[int, int], float]:
    """klein-9b bills per megapixel with a first-MP premium: the published
    tier prices are $15.00 / $17.00 / $19.00 per 1000 at Draft / Standard / High
    (16:9), i.e. ~1.5c flat plus a per-MP component."""
    def f(width: int, height: int) -> float:
        return base_usd + per_mp_usd * megapixels(width, height)
    return f


@dataclass(frozen=True)
class ModelSpec:
    key: str                       # short name used by the CLI/config
    id: str                        # Cloudflare model id
    label: str
    provider: str = "cloudflare"

    request_encoding: RequestEncoding = "json"
    response_encoding: ResponseEncoding = "raw"

    # Native = model id in the URL path. Gateway = model id in the request
    # body at the bare /ai/run endpoint. See CallStyle.
    call_style: CallStyle = "native"

    # How this model wants its size expressed. "pixels" is the native five and
    # flux-2-pro; the other gateway families each speak their own vocabulary
    # and cannot be sent width/height at all.
    size_style: SizeStyle = "pixels"

    # Whether the 512x512 tile count is a meaningful billing unit for this
    # model. False for every gateway model -- they bill flat per image (or per
    # resolution tier), so a tile count next to one is a meaningless number and
    # the UI must suppress it rather than show it.
    bills_per_tile: bool = True

    # Does this model rewrite the prompt before generating, and expose a
    # control for it? True only for krea today. Drives the GUI control and
    # the warning that the user's text may not be what gets rendered.
    supports_prompt_expansion: bool = False

    # The name of this model's content-filter field, or "" for the models
    # that expose no lever at all (which is most of them -- the native
    # Cloudflare models pointedly do not offer one). Only two values exist:
    # "safety_tolerance" (flux-2-pro, an integer 0-5) and
    # "disable_safety_checker" (p-image, a boolean). See CONTENT_FILTER_MODES.
    content_filter_field: str = ""

    # Which spelling this model's `output_format` field uses, or "" for the
    # models that do not accept the field at all. "jpeg" is flux-2-pro's
    # vocabulary; "jpg" is nano-banana's. See wire_output_format() -- the
    # difference is a real, easy-to-ship bug, not a cosmetic one.
    output_format_vocab: str = ""

    # Are the pixel dimensions this model renders at PUBLISHED, or are they
    # the program's own estimate? False only for krea, which takes a
    # `resolution` word and does not say what it resolves to -- so the size
    # readout marks its numbers "~ estimated" rather than presenting a guess
    # as fact.
    #
    # This is deliberately NOT derived from size_style. The estimated-size
    # readout was originally keyed on `size_style == "aspect_ratio_resolution"`
    # because krea was the only model using it; nano-banana then arrived
    # speaking the identical vocabulary with dimensions Google publishes
    # exactly, and the readout would have called them a guess. The honest
    # question is "is this number measured/published or invented?", which no
    # size vocabulary can answer, so it is asked directly.
    sizes_published: bool = True

    # Aspect ratios this model can actually serve, as program ratio keys.
    # Empty means "all five". Set where a model's enum omits one of ours.
    supported_ratios: tuple[str, ...] = ()

    # Cost tier marker shown in the model dropdown: "" (free), "$", "$$", "$$$".
    # NOT stored -- derived at a FIXED reference size by cost_tier_marker() so
    # it cannot drift out of sync with price_fn, and cannot flicker as the user
    # changes tier. A browsing aid; the cost estimator remains the real number.

    # The image format the provider actually DELIVERS -- measured, not what it
    # claims in the content-type header, which lies (lightning declares
    # image/png and sends JPEG). Shown in the UI so the format is visible
    # before generating, and used to grey out pointless conversions.
    output_format: str = "jpg"

    min_dimension: int = 256
    max_dimension: int = 2048
    multiple_of_16: bool = False

    steps_settable: bool = True
    default_steps: int | None = None
    max_steps: int | None = None

    supports_negative_prompt: bool = True
    supports_guidance: bool = True
    supports_seed: bool = True

    # Guidance (CFG) the provider sends when the caller doesn't specify one.
    # MEASURED 2026-09-04: the provider previously left this unset entirely,
    # which meant every model rode Cloudflare's own server-side default.
    # For dreamshaper-8-lcm (an LCM distilled sampler) that default is far
    # too high -- a steps x guidance grid found guidance=1 fixed 13/16
    # combos on a cell that failed 3/12 with guidance unset, and guidance=1
    # was also the best-LOOKING output, not just the least-broken. See
    # docs/findings.md and docs/dreamshaper-quality-probe.md.
    default_guidance: float | None = None

    # SD models are trained at ~1024 and degrade above it (duplicated
    # structures, geometry drift). This gates the High tier.
    max_safe_dimension: int = 1024

    # Prompt length budget, in CHARACTERS, for the soft counters in the GUI.
    #
    # The real unit is tokens, not characters, and no exact conversion exists:
    # a token is roughly 4 characters of ordinary English but a comma-separated
    # keyword salad tokenizes far worse than prose. These are therefore
    # deliberately SOFT numbers -- advice, never enforcement. Nothing truncates
    # a prompt on this side; the model does its own truncating, silently, and
    # the point of the counter is that the user finds out before it does.
    #
    #   SD family  -- CLIP ViT-L caps at 77 tokens including start/end, so ~75
    #                 usable, ~300 characters. Anything past it is DROPPED with
    #                 no error. Measured against the published CLIP limit.
    #   klein      -- FLUX.2's encoder tokenizes at max_length=512, so roughly
    #                 2000 characters. This is why long descriptive prompts pay
    #                 off on klein and are wasted on SD.
    prompt_soft_limit: int = 300
    prompt_hard_limit: int = 380

    price_fn: Callable[[int, int], float] = field(default=_free, repr=False)
    price_note: str = ""
    is_free: bool = True
    licence: str = ""

    # Neurons actually billed per 512x512 OUTPUT tile, if measured directly
    # via Cloudflare's GraphQL usage API. None means "not measured, fall
    # back to deriving it from the $ price" -- see Estimate.free_images_per_day.
    #
    # MEASURED 2026-09-04 for klein4b: Cloudflare's own pricing page states
    # 26.05 neurons/output tile, but two independent real measurements
    # (a 108-image production batch, and a fresh 6-image check) both landed
    # at ~4.61 neurons/tile -- about 5.7x less. Deriving "free images per
    # day" from the $1.72/1000 price (which assumes the published rate)
    # undercounted by the same 5.7x: 63/day shown vs ~361/day measured.
    # The dashboard's per-model neuron reading, once dismissed as unusable
    # for image models (see the price-verification note in this file, dated
    # 2026-08-30 -- that finding was about the 0-neuron SD models, and never
    # actually tested klein), was re-checked directly via GraphQL and reads
    # a real, consistent, nonzero number for klein4b today.
    measured_neurons_per_tile: float | None = None

    # ---- style reference image (added 2026-09-19) ------------------------
    #
    # A PARTIAL reversal of the "reference-image fields are a permanent skip"
    # ruling. The old ruling rested on two premises -- that these fields are
    # for single-image EDITING, and that they need a publicly hosted URL --
    # and MEASURED 2026-09-19 both are false for part of the lineup. Four
    # models take a LOCAL file; krea/recraft/p-image genuinely cannot and
    # stay excluded by measurement rather than by preference.
    #
    # `reference_field is None` is THE GATE for the whole feature on a model.
    # Nothing outside this file may decide whether a model can take one --
    # ask supports_reference_image(), exactly as pricing asks cost_band().
    #
    #   "input_image_0"  klein, multipart binary part
    #   "image_input"    nano-banana, list of `data:` base64 URIs
    #   "input_images"   flux-2-pro, list of `data:` base64 URIs (DOC-DERIVED)
    reference_field: str | None = None

    # "multipart" (a real file part) or "base64" (a data: URI in a JSON list).
    # Not derivable from request_encoding: flux-2-pro and nano-banana are both
    # JSON gateway models and both want base64, while klein is the multipart
    # one -- but a future JSON model could want a URL, so it is stated.
    reference_encoding: str | None = None

    # What the PROMPT calls the reference, for the influence phrase (see
    # core/reference.py). Per model because the families disagree: klein
    # addresses inputs by index -- Cloudflare's own example is "style it like
    # image 0" -- while the others are steered in plain language and have no
    # documented index convention. Only meaningful with a reference_field.
    reference_prompt_name: str = "the reference image"

    # MEASURED 2026-09-19 on klein-4b, and both numbers contradict the docs.
    #
    # The floor is UNDOCUMENTED and real: bisected exactly, 63x63 rejected and
    # 64x64 accepted, and it applies to EACH SIDE -- 64x48 is refused. The
    # rejection is a generic HTTP 400 "AiError: Invalid input" (code 8001)
    # naming neither the field nor the size, so a user who sends a 32x32
    # sprite gets an unexplainable failure unless the program checks first.
    #
    # The ceiling is NOT the documented one. Cloudflare's changelog and blog
    # both say "all input images must be smaller than 512x512"; 640x480,
    # 1024x1024, 2048x2048 and even 4096x4096 all returned HTTP 200. 2048 is
    # the program's own cap, chosen because accepted is not the same as
    # recommended -- flux2 issue #42 reports >4000px inputs degrading into
    # noise-like artifacts, and latency measurements showed no benefit at all
    # above ~1 MP (512/1024/2048/4096px refs all took 4.2-4.9s).
    #
    # Per-model, following the precedent max_safe_dimension set: a shared
    # constant would be a second place a model's limits are written.
    reference_min_dimension: int = 64
    reference_max_dimension: int = 2048

    @property
    def short_name(self) -> str:
        """The model name WITHOUT its parenthetical descriptor.

        `label` is written for the dropdown, where the parenthetical is the
        useful part ("(free daily, then cheap)"). Dropped into the middle of a
        sentence it reads badly -- "FLUX.2 klein 9B (free daily, then 10x 4B)
        has a fixed step count of 4" was reported as awkward, and it is.
        Sentences use this; the dropdown keeps the full label.
        """
        name = self.label.split(" (", 1)[0].strip()
        return name or self.label

    # ---- derived helpers -------------------------------------------------

    def cost_per_image(self, width: int, height: int) -> float:
        return self.price_fn(width, height)

    def cost_per_1000(self, width: int, height: int) -> float:
        return self.cost_per_image(width, height) * 1000.0

    def validate_size(self, width: int, height: int) -> list[str]:
        """Return a list of hard errors ('' if the size is usable)."""
        errs: list[str] = []
        # An enum model's legal sizes are a SET, not a range, so a
        # min/max/multiple-of check is not sufficient: 1024x768 sits happily
        # inside Recraft's 768-1344 bounds and is still not an accepted value.
        # This matters more here than anywhere else in the lineup, because
        # Recraft is the one model that BILLS a bad size before rejecting it
        # (the gateway type-checks only that `size` is a string and defers the
        # value check downstream). Catching it in validate_size means the GUI
        # readout and `cli dry-run` both refuse it too, rather than only the
        # provider at request time.
        if self.size_style == "size_enum":
            try:
                recraft_size_string(width, height)
            except ValueError as e:
                errs.append(str(e))
            return errs
        for name, v in (("width", width), ("height", height)):
            if v < self.min_dimension or v > self.max_dimension:
                errs.append(
                    f"{name} {v} outside {self.id}'s range "
                    f"{self.min_dimension}-{self.max_dimension}"
                )
            if self.multiple_of_16 and v % 16:
                errs.append(f"{name} {v} is not a multiple of 16 (required by {self.id})")
        return errs

    def size_warnings(self, width: int, height: int) -> list[str]:
        """Non-fatal quality notes — e.g. the SD training-size degradation.

        REWORDED 2026-09-06 after a user asked why the program warns about a
        setting they never chose. On the three free SD models this fires at
        the DEFAULT tier and DEFAULT ratio (standard 16:9 = 1536x864), so a
        new user's very first free batch produced an alarm about the shipped
        configuration -- and the old text then told them to "use a klein
        model", which is PAID. A free-lane user was being warned about a
        default and pointed at a bill.

        The fact is real and stays: these models are trained near 1024px and
        genuinely drift above it. What changed is the framing. It now names
        the FREE remedy (drop a tier) before the paid one, and reads as a
        trade-off rather than a fault, because nothing is actually wrong --
        the larger size is often still the one worth having.

        Kept rather than suppressed: it is the honest reason a free 16:9 batch
        sometimes shows duplicated turrets, and a user who does not know that
        will blame their prompt.
        """
        warns: list[str] = []
        if max(width, height) > self.max_safe_dimension:
            longest = max(width, height)
            warns.append(
                f"{width}x{height} is above this model's ~{self.max_safe_dimension}px "
                f"training size, so it may duplicate structures or drift "
                f"geometrically at {longest}px. That is a known trade-off of the "
                f"free models rather than a fault — the extra size is often still "
                f"worth it. For cleaner geometry drop to a smaller tier (free), or "
                f"use a klein/gateway model, which handle this size natively (paid)."
            )
        return warns


# ---------------------------------------------------------------------------
# The 5 in-scope Cloudflare models. Scope is locked; do not add without a
# decision — a model with unpublished pricing cannot back the cost estimator.
# ---------------------------------------------------------------------------

CLOUDFLARE_MODELS: list[ModelSpec] = [
    ModelSpec(
        key="lightning",
        output_format="jpg",  # measured 2026-08-31: declares PNG, sends JPEG
        id="@cf/bytedance/stable-diffusion-xl-lightning",
        label="SDXL Lightning (free, fastest)",
        request_encoding="json",
        response_encoding="raw",       # measured: raw bytes, and it's JPEG
        min_dimension=256, max_dimension=2048,
        steps_settable=True, default_steps=8, max_steps=20,
        # MEASURED 2026-09-04: Lightning stayed technically OK across
        # guidance 1-8 and steps 8/20 (10/10 by the automated check), but on
        # closer visual comparison guidance=1 is over-sharpened/crunchy --
        # wiry over-defined fur, harsh HDR-ish edges -- while guidance=8
        # (control_steps8_g8.jpg) is clean and naturally lit, the best
        # Lightning result seen in the whole probe. See docs/findings.md and
        # old wip/spike/out/guidance_sanity/lightning/.
        default_guidance=8.0,
        supports_negative_prompt=True,
        max_safe_dimension=1024,
        price_fn=_free, is_free=True,
        price_note="FREE. Runs on Cloudflare's free daily allowance of 10,000 "
                   "neurons (their compute credit, reset at 00:00 UTC) — and in "
                   "testing this model consumed none of it at all, across every "
                   "request measured. The fastest model here and the one to start "
                   "with.",
        licence="SD/OpenRAIL-style; commercial output use permitted.",
    ),
    ModelSpec(
        key="sdxl",
        output_format="png",  # measured 2026-08-31: genuine PNG
        id="@cf/stabilityai/stable-diffusion-xl-base-1.0",
        label="SDXL Base 1.0 (free, slower)",
        request_encoding="json",
        response_encoding="raw",
        min_dimension=256, max_dimension=2048,
        steps_settable=True, default_steps=20, max_steps=20,
        # MEASURED 2026-09-04: the OPPOSITE lesson from dreamshaper -- this
        # is a non-distilled model that wants its full step budget and
        # normal-to-moderate guidance. guidance=1 badly degraded output
        # (textures melted, no real edges) even at steps=20; guidance=3-8
        # at steps=20 were all clean. No override needed: default_steps=20
        # is already correct and Cloudflare's own guidance default was fine
        # in every test. See docs/findings.md and
        # old wip/spike/out/guidance_sanity/sdxl/.
        supports_negative_prompt=True,
        max_safe_dimension=1024,
        price_fn=_free, is_free=True,
        price_note="FREE. Runs on Cloudflare's free daily allowance of 10,000 "
                   "neurons (their compute credit, reset at 00:00 UTC) — and in "
                   "testing this model consumed none of it at all. Slower than "
                   "SDXL Lightning because it takes more refinement passes.",
        licence="SD/OpenRAIL-style; commercial output use permitted.",
    ),
    ModelSpec(
        key="dreamshaper",
        output_format="png",  # measured 2026-08-31: genuine PNG
        id="@cf/lykon/dreamshaper-8-lcm",
        label="DreamShaper 8 LCM (free, photoreal-leaning)",
        request_encoding="json",
        response_encoding="raw",
        min_dimension=256, max_dimension=2048,
        steps_settable=True, default_steps=8, max_steps=20,
        # MEASURED 2026-09-04: default_steps=8 is a deliberate floor, not
        # just a speed default -- steps=4 produced duplicated/warped subjects
        # (a 3-headed squirrel cluster) even at guidance=1. 8-20 all looked
        # clean; there was no reason found to prefer higher than 8 by default.
        default_guidance=1.0,  # MEASURED 2026-09-04: LCM model, needs low CFG.
                                # See ModelSpec.default_guidance docstring.
        supports_negative_prompt=True,
        max_safe_dimension=1024,
        price_fn=_free, is_free=True,
        # SUPERSEDED 2026-09-04 (see docs/findings.md, "PROBE Phase 3"): the
        # 2026-09-02 note here blamed prompt content ("not steps... it
        # tracks the content") and called it an uncontrollable third-party
        # defect. That was wrong. The real cause was a missing guidance
        # value -- this is an LCM model, and it was riding Cloudflare's
        # default meant for non-LCM SDXL. With default_guidance=1.0 above,
        # a 48-generation, 3-seed sweep across every size/ratio that
        # previously failed 9-12/12 times came back clean. Content and size
        # only ever changed how often the wrong CFG happened to visibly
        # break; they were never the actual mechanism.
        price_note="FREE. Runs on Cloudflare's free daily allowance of 10,000 "
                   "neurons (their compute credit, reset at 00:00 UTC) — and in "
                   "testing this model consumed none of it at all. Leans more "
                   "photographic than the two SDXL models.",
        licence="SD/OpenRAIL-style; commercial output use permitted.",
    ),
    ModelSpec(
        key="klein4b",
        output_format="jpg",  # measured: returns JPEG
        id="@cf/black-forest-labs/flux-2-klein-4b",
        label="FLUX.2 klein 4B (free daily, then cheap)",
        request_encoding="multipart",
        response_encoding="json_base64",   # measured: base64 at result.image
        min_dimension=256, max_dimension=1920,
        multiple_of_16=True,
        steps_settable=False, default_steps=4, max_steps=4,
        # MEASURED (from source) 2026-09-04: Black Forest Labs' own README
        # for this exact model (FLUX.2-klein-4B, the distilled/guidance-
        # distilled variant Cloudflare hosts as flux-2-klein-4b -- NOT the
        # separate "klein Base" line, which is trained without guidance
        # distillation) gives its official example as guidance_scale=1.0,
        # num_inference_steps=4. Confirmed with a local probe the same day:
        # 6 generations across guidance 1-8 at Standard 16:9 were all clean,
        # with no visible quality difference across the range -- so 1.0 is
        # a safe, doc-backed choice, though the range as a whole is robust.
        default_guidance=1.0,
        supports_negative_prompt=False,    # klein takes guidance, not negative
        max_safe_dimension=2048,           # natively specified to 4 MP
        prompt_soft_limit=2000, prompt_hard_limit=2400,   # ~512-token encoder
        price_fn=_tile_flat(1.72 / 6 / 1000),   # $1.72/1000 at 6 tiles
        # RE-MEASURED 2026-09-06 via the same GraphQL query: one 1536x864
        # image billed 131.88 neurons = ~21.98 per output tile, giving ~75
        # free images/day rather than the ~361 the old 4.613 rate implied.
        #
        # This CONTRADICTS the 2026-09-04 reading of ~4.61/tile, and the newer
        # number is the one used. Both were taken the same way, so the
        # difference is real rather than methodological -- most likely the
        # earlier figure divided by a tile count that did not match what was
        # actually billed (today's query returns totalTiles = 0 for klein, so
        # a per-tile rate can only be derived from the image count and the
        # requested size). The honest reading is that neurons-per-IMAGE is
        # what the API reports reliably; per-tile is inference on top of it.
        #
        # RESOLVED 2026-09-06 (same day): the rate genuinely CHANGED. The old
        # 108-image batch is on disk, all klein4b at 1536x864, dated 09-03 --
        # identical conditions, ~27.7 neurons/image. Today's 131.88 matches
        # Cloudflare's PUBLISHED 26.05/tile (156.30 predicted for 6 tiles)
        # within 16%, and klein9b matches its published rate within 0.8%.
        # September 3rd was running at ~1/5.6 of the documented price, so
        # Cloudflare was under-billing image models and has corrected it.
        #
        # WARNING TO FUTURE SESSIONS: this number has moved once and can move
        # again. It is an estimate of a free allowance, not a contract. The
        # $ price ($1.72/1000) comes from the published price sheet and did
        # NOT change. If a re-measurement disagrees with the published rate in
        # the CHEAP direction, suspect a billing bug rather than banking it --
        # that is exactly how the old 4.613 figure got recorded as fact.
        # Style reference image. MEASURED 2026-09-19 against the live API:
        # one more multipart part, `input_image_0`, carrying the raw file
        # bytes with a filename and content-type. PNG, JPEG and WebP all
        # accepted; no square requirement (320x180 and 512x64 both passed);
        # and reference size does NOT affect generation latency, so an
        # oversized reference costs upload bandwidth and nothing else.
        #
        # klein can also address the reference BY INDEX in the prompt text --
        # Cloudflare's own example is "take the subject of image 1 and style
        # it like image 0". With one image it is always `image 0`.
        reference_field="input_image_0",
        reference_encoding="multipart",
        reference_prompt_name="image 0",
        measured_neurons_per_tile=21.98,
        is_free=False,
        price_note="Free for roughly the first 75 images each day, then about "
                   "$1.72 per 1000 images — by far the cheapest paid model here. "
                   "It draws on Cloudflare's free daily "
                   "allowance of 10,000 neurons (their compute credit, reset at "
                   "00:00 UTC), and unlike the three free models it genuinely uses "
                   "them up — so a typical batch costs nothing and a large one "
                   "starts charging partway through. The best quality here for the "
                   "money.",
        licence="Apache 2.0 — no restrictions. Safest paid choice.",
    ),
    ModelSpec(
        key="klein9b",
        output_format="jpg",  # measured: returns JPEG
        id="@cf/black-forest-labs/flux-2-klein-9b",
        # "OVER BUDGET" was this project's internal budget vocabulary, which
        # the cost bands replaced. The dropdown already carries a $$ marker
        # and the note says the price, so the label describes the MODEL.
        label="FLUX.2 klein 9B (free daily, then 10x 4B)",
        request_encoding="multipart",
        response_encoding="json_base64",
        min_dimension=256, max_dimension=1920,
        multiple_of_16=True,
        steps_settable=False, default_steps=4, max_steps=4,
        # Same distilled family as klein4b (step-distilled to 4 inference
        # steps) -- see the default_guidance comment on klein4b above.
        default_guidance=1.0,
        supports_negative_prompt=False,
        max_safe_dimension=2048,
        prompt_soft_limit=2000, prompt_hard_limit=2400,   # ~512-token encoder
        # Fits the published $15.00 / $17.00 / $19.00 per-1000 tier prices
        # for 16:9 draft (0.332 MP) / standard (1.327 MP) / high (2.359 MP).
        price_fn=_per_megapixel(0.01432, 0.001973),
        # MEASURED 2026-09-06, the first direct reading for this model: one
        # 1536x864 image billed 1411.93 neurons = ~235.3 per output tile, or
        # about 7 free images a day. That is 10.7x klein4b's neuron cost per
        # image, NOT the ~2x its parameter count suggests -- the user's own
        # instinct was that 9B could not be as expensive as the old estimate
        # implied, and the measurement went the other way: 9B really is that
        # much dearer, while the 4B figure was the one that was wrong.
        #
        # Until now this model had NO measured rate and fell back to deriving
        # the allowance from its $ price, which happened to give 6/day -- close
        # to the truth by luck rather than by method, since that same
        # derivation was undercounting klein4b badly.
        # Same FLUX.2 family, same multipart shape as klein 4B above.
        reference_field="input_image_0",
        reference_encoding="multipart",
        reference_prompt_name="image 0",
        measured_neurons_per_tile=235.32,
        is_free=False,
        price_note="Free for roughly the first 7 images each day — it draws on "
                   "the same 10,000-neuron daily allowance as the other "
                   "Cloudflare models but burns through it about ten times "
                   "faster than klein 4B — then costs roughly $15-19 per 1000 "
                   "images. That is about ten times klein 4B's price for a "
                   "modest quality gain, so 4B is usually the better buy. One "
                   "of the few models where a bigger image genuinely costs more.",
        licence="FLUX Non-Commercial — restricts SERVING the model, not the "
                "outputs. Generating via Cloudflare's hosted endpoint and using "
                "the images commercially is fine.",
    ),
]

# ---------------------------------------------------------------------------
# Cloudflare AI GATEWAY models. Same endpoint, same token, same account as the
# native models above -- but addressed differently (model id in the BODY, not
# the URL path) and billed differently (flat per image, not per tile).
#
# Field lists were verified against the live API at ZERO COST: the gateway
# validates a request before charging, so a malformed request returns 400
# naming every legal field, and a well-formed one returns 402 Insufficient
# balance -- which is itself proof the model id and request shape are correct.
# See docs/gateway-models-todo.md. Do not re-derive them.
# ---------------------------------------------------------------------------

# Shared by both krea models -- the field lists are confirmed identical, so
# the only differences between the pair are price, speed and label.
_KREA_COMMON = dict(
    provider="cloudflare",
    call_style="gateway",
    request_encoding="json",
    # result.image is a PRESIGNED URL, not image data: fetching it costs a
    # second HTTP request. Confirmed on both krea models 2026-09-05.
    response_encoding="json_url",
    output_format="png",   # the doc example is a .png URL; sniffed regardless

    size_style="aspect_ratio_resolution",
    bills_per_tile=False,
    # Locked to resolution="1K"; width/height are not accepted at all. The
    # min/max here describe the sizes SIZES_KREA produces, not a range the
    # caller may choose from -- nothing is sent to the model.
    min_dimension=752, max_dimension=1328,
    max_safe_dimension=1328,   # it only ever renders at its own one size

    # The ONLY model in the lineup whose displayed size is an estimate. Krea
    # publishes no pixel dimensions for "1K"; SIZES_KREA is a ~1 MP guess and
    # the GUI marks it as one. See sizes_published.
    sizes_published=False,

    steps_settable=False, default_steps=None, max_steps=None,
    supports_negative_prompt=False,
    supports_guidance=False,
    supports_seed=True,

    # UNVERIFIED -- Krea publishes no prompt limit. Set to a middle ground.
    # Note `creativity` defaults to "medium", which is a PROMPT EXPANSION mode:
    # the model may rewrite the prompt before generating, so an exact budget
    # is less meaningful here than on a model that takes the text verbatim.
    prompt_soft_limit=800, prompt_hard_limit=1000,
    supports_prompt_expansion=True,
)

# Krea's four style dials, documented 2026-09-05.
#
#   creativity  "raw" | "low" | "medium" (default) | "high"  -- prompt expansion
#   intensity   integer, -100..100, default 0     NOT SENT
#   complexity  integer, -100..100, default 0     NOT SENT
#   movement    integer, -100..100, default 0     NOT SENT
#
# The three sliders are NOT sent, and that is not a limitation: every one of
# them defaults to the NEUTRAL value (0), so omitting them is byte-for-byte
# equivalent to sending the defaults. Nothing is being missed. They stay out
# because a single global dial applied to every prompt in a batch is already
# what the style-suffix file does, in plain text the user can read and edit.
#
# `creativity` IS exposed -- see PROMPT_EXPANSION_MODES below. It is the only
# one of the four that changes what the model does with the TEXT rather than
# how it renders, and its default is not neutral.
KREA_STYLE_DIALS = {
    "creativity": ("raw", "low", "medium", "high"),
    "intensity": (-100, 100, 0),
    "complexity": (-100, 100, 0),
    "movement": (-100, 100, 0),
}

# Prompt expansion: the model rewrites the prompt before generating.
#
# EXPOSED, unlike the other three dials, because its default is NOT neutral --
# krea ships with "medium", meaning expansion is ON unless the caller turns it
# off. A user who does not know that sees images that do not match the prompt
# they wrote and has no way to find out why. (Exposing it is still right; what
# changed in 2026-09-06 is which value the program SENDS by default.)
#
# It matters more in this program than in a one-off generator. The text sent
# is `prompt + style suffix`, and expansion operates on the CONCATENATED
# result -- so it can rewrite the style addon as readily as the subject. That
# is the worse failure of the two: the style suffix is the part specifically
# meant to stay constant across every image in a batch, and silently varying
# it defeats the point of having one.
#
# Not forced for the user either way. Expansion genuinely helps a short or
# sparse prompt, and this is a general-purpose tool -- so it is a visible
# choice with an honest tooltip rather than a decision made on their behalf.
#
# CHANGED 2026-09-06: the default was "raw" (expansion OFF), on the reasoning
# above that expansion could reword the style suffix. Two things overturned it.
#
# First, the evidence for "raw" was bad. It was set partly because krea's
# output on a singular-subject prompt contained extra units, which was read as
# expansion rewriting the text. The sidecar disproves that: `creativity: raw`
# was sent and `original_prompt == final_prompt`. Krea composed that scene
# poorly for reasons unknown; nothing was rewritten. A mechanism had been
# inferred from a symptom.
#
# Second, the vendor documentation says the concern does not apply to prompts
# of the length this program sends. Krea's own docs and Runware's guide both
# state the API default is "medium" (NOT "low", as an earlier note here said),
# and that for a DETAILED prompt expansion "polishes and enhances rather than
# restructuring your specific details" -- it makes lighting, colour and
# composition choices instead of rewriting the subject. Wholesale rewriting is
# what happens to a five-word prompt, not a 600-character one.
#
# So the program now matches the vendor default. "medium" is what the model is
# tuned for and is the reason to pick krea at all; shipping "raw" meant paying
# krea prices while turning off the thing that makes it krea.
#
# Deliberately NOT "high": that level takes liberty with style, mood and
# aesthetics, which is exactly what a BATCH needs held constant across images.
PROMPT_EXPANSION_MODES: tuple[str, ...] = ("raw", "low", "medium", "high")
# The API's own default, per Krea's documentation. Named so the two ideas stay
# distinct: what the provider does when told nothing, versus what this program
# chooses to send. They agree today; they have not always.
KREA_API_DEFAULT_EXPANSION = "medium"
DEFAULT_PROMPT_EXPANSION = "medium"


# ---------------------------------------------------------------------------
# Content-filter control.
#
# Two models in the lineup expose a lever on their own content filter, and
# they express it completely differently:
#
#   p-image      `disable_safety_checker` -- a BOOLEAN (checker on/off)
#   flux-2-pro   `safety_tolerance`       -- an INTEGER 0-5
#
# Rather than bolting a separate control onto each, both are driven by one
# program-level setting with three modes. The per-model mapping lives in
# ModelSpec.content_filter_field / _filter_value_for(), so the GUI and CLI
# never have to know which field a given model speaks.
#
# WHY THIS MATTERS: CLAUDE.md records that Cloudflare's native models return
# HTTP 200 and a byte-identical BLACK IMAGE for a refused prompt -- no error,
# no distinct status. A user hitting spurious blocks on the native lineup has
# no lever at all. These two models are the only lever that exists.
CONTENT_FILTER_MODES: tuple[str, ...] = ("default", "permissive", "off")

# DECIDED 2026-09-05: the program defaults to the MOST PERMISSIVE setting on
# the two models that offer one -- NOT to the provider's own default.
#
# This reverses an earlier draft that defaulted to "default" on the reasoning
# that loosening a filter should be a knowing decision. That reasoning was
# wrong for THIS tool, and the argument against it is worth keeping:
#
#   * This is a BATCH generator. A one-off generator can shrug off a spurious
#     refusal -- the user reruns it. Here a false flag costs a slot in an
#     overnight run of hundreds, and the user finds out the next morning.
#   * On the native lineup a refusal is INVISIBLE at request time: HTTP 200
#     and a black frame (see CLAUDE.md). These two models are the only lever
#     that exists against that, and shipping the lever set to "off" gives the
#     user the annoyance without the remedy.
#   * The failure mode is already REAL, not hypothetical. Cloudflare runs a
#     vision check over the OUTPUT image, so ordinary prompts get flagged on
#     the strength of a frame the user never asked for and cannot inspect --
#     that is precisely the class of false positive this setting exists for.
#
# What it is NOT: this does not disable moderation, and it is not a route
# around any provider's policies. It asks for the loosest setting the model
# itself offers, which is 5 of 5 on flux-2-pro's own published scale. The
# provider still enforces its own limits, and a genuinely refused prompt is
# still refused. "default" and the stricter end remain one dropdown away.
DEFAULT_CONTENT_FILTER = "permissive"

# flux-2-pro's `safety_tolerance` scale, per Cloudflare's published schema for
# black-forest-labs/flux-2-pro-preview (fetched 2026-09-05) and Black Forest
# Labs' own convention:
#
#     0 = STRICTEST ............ 5 = MOST PERMISSIVE     (API default: 2)
#
# *** THE DIRECTION IS THE WHOLE POINT. ***
# It reads backwards from every other "tolerance" dial one might expect, and
# getting it inverted would make the filter MAXIMALLY AGGRESSIVE -- the exact
# opposite of the intent, and it would look like the model was simply refusing
# more prompts rather than like a configuration bug. Two independent reads of
# Cloudflare's schema page agree on the direction, but it is DOC-DERIVED, NOT
# MEASURED: no live call has been made against this model. Verify empirically
# on first paid use (one prompt that reliably trips the native klein filter,
# generated at 5 and at 0 -- ~$0.06 total) and record the result in
# docs/findings.md. See the Unverified table in docs/gateway-models-todo.md.
SAFETY_TOLERANCE_MIN = 0        # strictest
SAFETY_TOLERANCE_MAX = 5        # most permissive
SAFETY_TOLERANCE_API_DEFAULT = 2

# What each program mode means on each field. "default" is expressed by
# sending NOTHING at all rather than by sending the documented default value:
# if the provider ever moves its default, the program follows it rather than
# pinning an old number the user never chose. Note that "default" is no longer
# the PROGRAM's default -- see DEFAULT_CONTENT_FILTER -- it is the mode a user
# picks to hand the decision back to the provider.
#
# There is no middle setting for p-image because its field is a boolean --
# "permissive" and "off" both mean the same single thing there, which is
# honest rather than a limitation invented to fill the table.
_FILTER_VALUES: dict[str, dict[str, object]] = {
    "safety_tolerance": {
        "permissive": SAFETY_TOLERANCE_MAX,   # 5 == most permissive. Not 0.
        "off": SAFETY_TOLERANCE_MAX,          # 5 is as far off as it goes
    },
    "disable_safety_checker": {
        "permissive": True,
        "off": True,
    },
}


# The output_format wire vocabulary, per family. THE SPELLING DIFFERS AND
# THAT IS THE WHOLE POINT OF THIS TABLE:
#
#   flux-2-pro    accepts  jpeg | png | webp     <- "jpeg"
#   nano-banana   accepts  jpg  | png            <- "jpg"
#
# ModelSpec.output_format stores the program's own internal spelling ("jpg"),
# because it also drives the format shown in the dropdown and the file
# extension logic, which are shared across every model. Writing the wire value
# out by hand at each call site is exactly how the jpeg/jpg bug gets shipped,
# so it is derived here instead, keyed by the field's own vocabulary.
_OUTPUT_FORMAT_WIRE: dict[str, dict[str, str]] = {
    "jpeg": {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"},
    "jpg":  {"jpg": "jpg",  "jpeg": "jpg",  "png": "png"},
}


def wire_output_format(model: "ModelSpec") -> str | None:
    """The string to send in this model's `output_format` field, or None.

    None for every model that does not accept the field, which is most of
    them -- the format is then whatever the provider sends, and sniffed from
    the magic bytes as always.
    """
    vocab = _OUTPUT_FORMAT_WIRE.get(model.output_format_vocab)
    if vocab is None:
        return None
    return vocab.get(model.output_format)


def filter_value_for(model: "ModelSpec", mode: str | None) -> tuple[str, object] | None:
    """(field_name, value) to send for a content-filter mode, or None.

    None means "send nothing", which covers three cases that must not be
    conflated: the model exposes no filter control at all, the mode is
    "default" (inherit the provider's own), or the mode is unknown.
    """
    field_name = model.content_filter_field
    if not field_name:
        return None
    m = mode or DEFAULT_CONTENT_FILTER
    if m not in CONTENT_FILTER_MODES:
        raise ValueError(
            f"unknown content filter mode {m!r}; expected one of "
            + ", ".join(CONTENT_FILTER_MODES)
        )
    values = _FILTER_VALUES.get(field_name, {})
    if m not in values:
        return None
    return field_name, values[m]

# Shared by both Recraft models -- the field list was confirmed IDENTICAL on
# both Cloudflare model pages (prompt, size, style, substyle, controls, image;
# no seed, no width/height, no aspect_ratio), so the pair differs only in id,
# label and the character of the model. Same $35/1000 price, same size enum,
# same presigned-URL response.
_RECRAFT_COMMON = dict(
    provider="cloudflare",
    call_style="gateway",
    request_encoding="json",
    # CONFIRMED 2026-09-05 from Cloudflare's own model pages for
    # recraftv4-1-utility and recraftv4-1, read independently, plus a
    # third-party listing of the same response: result.image is an
    # `https://...` PRESIGNED URL, the krea/flux-2-pro shape, and the
    # envelope carries the gateway `state` field. NOT the bare base64
    # klein returns and NOT the data URI p-image returns -- all three
    # incompatible shapes still live at the identical field path, which
    # is why _extract_image sniffs the content rather than trusting it.
    # DOC-DERIVED, not measured.
    response_encoding="json_url",
    output_format="png",   # the doc example URL ends .png; sniffed anyway

    # The fifth size vocabulary in the lineup, and the only opaque one.
    # See SIZES_RECRAFT and recraft_size_string() for why the value must
    # be validated locally before the request.
    size_style="size_enum",
    bills_per_tile=False,
    # These describe the sizes SIZES_RECRAFT produces, not a range the
    # caller may pick from -- nothing but the enum string is ever sent.
    min_dimension=768, max_dimension=1344,
    max_safe_dimension=1344,   # it only ever renders at its own fixed sizes

    # No steps, no guidance, no negative prompt -- and NO SEED. Recraft
    # exposes no seed field at all, so runs are NOT reproducible on either
    # model in the pair. The GUI disables the seed controls and says why;
    # there is no way to make two runs of the same prompt match here.
    steps_settable=False, default_steps=None, max_steps=None,
    supports_negative_prompt=False,
    supports_guidance=False,
    supports_seed=False,

    # UNVERIFIED. Recraft publishes no prompt limit and it could not be
    # probed without spending. Set to the same middle ground as p-image
    # and krea. Nothing truncates on this side, as everywhere else.
    prompt_soft_limit=800, prompt_hard_limit=1000,

    price_fn=_flat_per_image(35.00 / 1000),
    is_free=False,
    licence="Recraft-hosted via Cloudflare; outputs are your Customer Content.",
)

CLOUDFLARE_GATEWAY_MODELS: list[ModelSpec] = [
    ModelSpec(
        key="p-image",
        id="pruna/p-image",
        label="P-Image (paid, ultra-fast, prompt-enhanced)",
        provider="cloudflare",
        call_style="gateway",
        request_encoding="json",
        # NOT json_base64, despite the identical result.image field path:
        # this returns a full `data:image/jpeg;base64,...` URI where klein
        # returns bare base64. Confirmed 2026-09-05 on Cloudflare's own model
        # pages for both p-image and p-image-edit, so it is family-wide.
        response_encoding="json_data_uri",
        output_format="jpg",   # data URI declares image/jpeg; sniffed anyway

        size_style="aspect_ratio",
        bills_per_tile=False,
        # A filter opt-out the native Cloudflare models do not offer. A
        # BOOLEAN here where flux-2-pro takes an integer 0-5; both are driven
        # by the one CONTENT_FILTER_MODES setting. Verified as a legal field
        # by the live 400-rejection field list (2026-09-04); its behaviour is
        # unverified, since exercising it costs a paid call.
        content_filter_field="disable_safety_checker",
        # The custom path's real limits. 1440 is the cap, but the x16 rule is
        # the binding constraint at 16:9 -- see SIZES_PIMAGE.
        min_dimension=256, max_dimension=1440,
        multiple_of_16=True,
        max_safe_dimension=1440,   # no degradation reported below its own cap

        # No steps, no guidance, no negative prompt -- none are accepted.
        steps_settable=False, default_steps=None, max_steps=None,
        supports_negative_prompt=False,
        supports_guidance=False,
        supports_seed=True,

        # UNVERIFIED. Cloudflare publishes no prompt limit for this model and
        # it could not be probed without spending. Set to the SD/CLIP-ish
        # middle ground deliberately: the model does its own automatic prompt
        # ENHANCEMENT, which means a short prompt is expanded server-side and
        # a long one may be treated quite differently from either the 77-token
        # CLIP models or klein's 512-token encoder. Treat these numbers as
        # advice only -- as everywhere else, nothing truncates a prompt here.
        prompt_soft_limit=800, prompt_hard_limit=1000,

        price_fn=_flat_per_image(5.00 / 1000),
        is_free=False,
        price_note="$5.00 per 1000 images, whatever size you pick — so the smaller "
                   "Draft size saves you nothing here. Very fast, and it rewrites "
                   "your prompt automatically to add detail. Its largest 16:9 "
                   "image is 1280x720, smaller than most other models manage.",
        licence="Pruna-hosted via Cloudflare; outputs are your Customer Content.",
    ),
    ModelSpec(
        key="krea-turbo",
        id="krea/krea-2-medium-turbo",
        label="Krea 2 Medium Turbo (paid, illustration)",
        price_fn=_flat_per_image(15.00 / 1000),
        is_free=False,
        price_note="$15.00 per 1000 images, whatever size you pick. Leans to "
                   "anime, painting and illustration rather than photorealism. "
                   "It expands your prompt before generating — adding lighting, "
                   "colour and composition detail — which is what Krea is built "
                   "around and is on by default; set Prompt expansion to Off if "
                   "you want your words used verbatim. It renders at one fixed "
                   "size, so the quality tier does nothing.",
        licence="Krea-hosted via Cloudflare; outputs are your Customer Content.",
        **_KREA_COMMON,
    ),
    ModelSpec(
        key="krea-medium",
        id="krea/krea-2-medium",
        label="Krea 2 Medium (paid, most consistent)",
        price_fn=_flat_per_image(30.00 / 1000),
        is_free=False,
        price_note="$30.00 per 1000 images — double its Turbo sibling for only a "
                   "slight quality gain. Worth it when you need every image in a "
                   "batch to look consistent with the others; otherwise pick "
                   "Turbo. Expands your prompt by default, the same as Turbo. "
                   "Same fixed size, so the quality tier does nothing.",
        licence="Krea-hosted via Cloudflare; outputs are your Customer Content.",
        **_KREA_COMMON,
    ),
    ModelSpec(
        key="flux2pro",
        id="black-forest-labs/flux-2-pro-preview",
        label="FLUX.2 pro Preview (paid, tunable content filter)",
        provider="cloudflare",
        call_style="gateway",
        request_encoding="json",
        # CONFIRMED 2026-09-05 from Cloudflare's published schema for this
        # model, read twice independently: result.image is declared
        # `"string" format: uri` -- a PRESIGNED URL, the same shape as krea
        # and NOT the data URI p-image returns or the bare base64 klein does.
        # Three incompatible shapes now live at the identical field path, so
        # the shape is never assumed from the field name; _extract_image also
        # sniffs the content. DOC-DERIVED, not measured.
        response_encoding="json_url",
        # `output_format` DEFAULTS TO "jpeg" on this model -- a non-neutral
        # default, so it is sent EXPLICITLY rather than inherited (the same
        # lesson krea's `creativity` taught: a field whose default is not the
        # neutral choice is worth stating). This value drives what is sent AND
        # what the dropdown reports. Note the spelling is "jpeg" on this
        # model and "jpg" on nano-banana -- the wire value is derived by
        # wire_output_format(), never by writing the string out by hand.
        output_format="jpg",
        output_format_vocab="jpeg",

        # The ONLY wishlist model with pixel-exact control: true width/height,
        # minimum 64, and NO multiple-of-16 rule (1537 was accepted in the
        # zero-cost field probe). No upper bound was found -- 50000 passed
        # validation, so any real bound is enforced later or is very high.
        # The program's shared SIZES table therefore maps onto it directly
        # with no override: every tabled size is >= 64 and needs no rounding.
        size_style="pixels",
        bills_per_tile=False,
        min_dimension=64,
        # 2048 is the largest size the program's own table asks for, not a
        # limit the model imposes. Kept at the table's ceiling deliberately:
        # validate_size() should not wave through a size the program cannot
        # produce anyway, and no real bound is known to put here instead.
        max_dimension=2048,
        multiple_of_16=False,
        max_safe_dimension=2048,   # FLUX.2 family is specified to 4 MP

        # The reason this model is in the lineup at all. Integer 0-5, where
        # 5 is the MOST PERMISSIVE -- see the SAFETY_TOLERANCE_* constants,
        # and read the direction warning there before changing anything.
        content_filter_field="safety_tolerance",

        # No steps, no guidance, no negative prompt -- none are accepted.
        steps_settable=False, default_steps=None, max_steps=None,
        supports_negative_prompt=False,
        supports_guidance=False,
        supports_seed=True,

        # Same 512-token FLUX.2 text encoder family as klein, so klein's
        # measured budget is the right analogy here -- unlike p-image and
        # krea, where prompt enhancement made every analogy weak. Still
        # UNVERIFIED for this specific model; nothing truncates either way.
        prompt_soft_limit=2000, prompt_hard_limit=2400,

        # Style reference image. DOC-DERIVED, NOT MEASURED: Cloudflare's
        # schema says each entry of `input_images` is "an HTTPS URL or a
        # data:image/...;base64,... URI" (max 8). Confirming it would have
        # cost a paid generation, which needs the user's explicit per-test
        # permission -- so this ships on the documentation and the first real
        # use is worth watching. The program sends exactly one, at index 0.
        reference_field="input_images",
        reference_encoding="base64",
        price_fn=_flat_per_image(30.00 / 1000),
        is_free=False,
        price_note="$30.00 per 1000 images, whatever size you pick. Its "
                   "distinguishing feature is the adjustable content filter, so "
                   "reach for it when good prompts keep coming back refused. "
                   "Follows a detailed prompt closely, and takes the largest "
                   "16:9 image of any paid model here.",
        licence="FLUX.2 [pro] served via Cloudflare; outputs are your Customer "
                "Content. The weights are not redistributed by this program.",
    ),

    ModelSpec(
        key="recraft-utility",
        id="recraft/recraftv4-1-utility",
        label="Recraft V4.1 Utility (paid, general-purpose)",
        price_note="$35.00 per 1000 images. A solid all-rounder, and the better of "
                   "the two Recraft models. Two catches: its 16:9 image is "
                   "1344x768, smaller than most other models manage, and it "
                   "accepts no seed, so you cannot make two runs match.",
        **_RECRAFT_COMMON,
    ),
    ModelSpec(
        key="recraft-v41",
        id="recraft/recraftv4-1",
        label="Recraft V4.1 (paid, art-directed)",
        # NOT the upgrade to Utility, and the label must never imply it is.
        # Identical price, identical size enum, identical everything on the
        # wire -- and a LOWER Elo (1198 against Utility's 1218). It earns its
        # place on CHARACTER, not score: art-directed tuning for high
        # aesthetics, strong composition, accurate text rendering and refined
        # design taste. Ships as a pair with Utility by decision; do not
        # "optimise" the pair down to one.
        price_note="$35.00 per 1000 images — the same price and the same sizes as "
                   "Recraft Utility, but slightly weaker overall. It is not an "
                   "upgrade: pick it for art direction, strong composition and "
                   "readable text in the image. It accepts no seed, so you cannot "
                   "make two runs match.",
        **_RECRAFT_COMMON,
    ),
    ModelSpec(
        key="nano-banana-2-lite",
        id="google/nano-banana-2-lite",
        label="Nano Banana 2 Lite (paid, Google, high quality)",
        provider="cloudflare",
        call_style="gateway",
        request_encoding="json",
        # CONFIRMED 2026-09-05 from Cloudflare's own model page, read twice,
        # and cross-checked against the sibling nano-banana-2 page which
        # declares the identical envelope: result.image is an
        # `https://...` PRESIGNED URL (the doc example ends `.jpg`), and the
        # response carries the gateway `state` field plus `gatewayMetadata`.
        # The krea / flux-2-pro / Recraft shape, so it reuses `json_url` and
        # the existing presigned fetch unchanged -- FOUR of the seven gateway
        # models now return a URL at the same field path where klein returns
        # bare base64 and p-image returns a data URI. DOC-DERIVED, not
        # measured.
        response_encoding="json_url",
        # The doc example URL ends .jpg. Magic bytes are sniffed regardless --
        # and here the program also ASKS for a format, which is a weaker claim
        # than a declared one, so the sniff matters more rather than less.
        output_format="jpg",
        # `jpg`, NOT `jpeg`. flux-2-pro spells the same format the other way,
        # and writing either out by hand at a call site is how that bug ships.
        # See wire_output_format() and _OUTPUT_FORMAT_WIRE.
        #
        # Cloudflare's schema states the enum (`jpg|png`) but NO default, and
        # Google does not publish one either -- so unlike flux-2-pro, where
        # the non-neutral `jpeg` default was documented and had to be
        # countered, here the default is simply UNKNOWN. Sent explicitly for
        # exactly that reason: an unknown default cannot be assumed neutral.
        output_format_vocab="jpg",

        # krea's vocabulary -- aspect_ratio enum plus a resolution word, and
        # no width/height field at all -- but with a real ladder behind the
        # resolution. See NANO_BANANA_TIER_RESOLUTION for why THIS model is
        # nonetheless pinned to 1K.
        size_style="aspect_ratio_resolution",
        bills_per_tile=False,
        # These describe the sizes the 1K table produces, not a range the
        # caller may pick from -- nothing but the ratio and resolution words
        # are ever sent.
        min_dimension=768, max_dimension=1344,
        max_safe_dimension=1344,   # it only ever renders at its own 1K sizes

        # No steps, no guidance, no negative prompt -- and NO SEED. The field
        # list has none, so runs are NOT reproducible on this model by any
        # means. supports_seed=False is the whole of the work: the GUI
        # disables the seed checkbox, label and entry, _param_note says
        # reproducibility is impossible, and _finish records seed=None so the
        # engine's unused number never reaches the sidecar.
        steps_settable=False, default_steps=None, max_steps=None,
        supports_negative_prompt=False,
        supports_guidance=False,
        supports_seed=False,

        # UNVERIFIED. Neither Cloudflare nor Google publishes a prompt length
        # limit for this model, and it could not be probed without spending.
        # Set to the same middle ground as p-image, krea and Recraft. Nothing
        # truncates on this side, as everywhere else in the program.
        prompt_soft_limit=800, prompt_hard_limit=1000,

        # PER-RESOLUTION pricing, not flat -- the only family in the lineup
        # where the tier changes the bill. Lite is pinned to 1K so today only
        # the 1K rate can ever be quoted, but the mechanism is real and the
        # sibling nano-banana-2 needs all three.
        #
        # $0.034 per 1K image, from Cloudflare's AI Gateway announcement
        # ("Nano Banana 2 Lite generates 1K images at $0.034 each") and
        # independently at $0.0336 standard-tier from a pricing breakdown --
        # agreeing with the ~$34/1000 in the source wishlist doc. Google
        # publishes NO 2K or 4K rate for Lite, which is half the reason the
        # model is pinned to 1K.
        # Style reference image. MEASURED 2026-09-19 on this model: a list
        # of `data:image/...;base64,...` URIs at `image_input`, which came
        # back HTTP 200 / state "Completed". The program sends exactly one.
        reference_field="image_input",
        reference_encoding="base64",
        price_fn=_per_resolution({"1K": 34.00 / 1000}),
        price_note="$34.00 per 1000 images. Google's model, and the best value "
                   "of the dearer options in our own side-by-side — close to full "
                   "Nano Banana 2 for half the price. Two catches: its 16:9 image is "
                   "1344x768, smaller than most other models manage, and it "
                   "accepts no seed, so you cannot make two runs match.",
        is_free=False,
        licence="Google model hosted via Cloudflare; outputs are your "
                "Customer Content.",
    ),
    ModelSpec(
        key="nano-banana-2",
        id="google/nano-banana-2",
        label="Nano Banana 2 (paid, Google, HIGHEST quality)",
        provider="cloudflare",
        call_style="gateway",
        request_encoding="json",
        # Same envelope as Lite -- read on this model's own page and
        # cross-checked against Lite's. Presigned URL at result.image, with
        # `state` and `gatewayMetadata`. DOC-DERIVED, not measured.
        response_encoding="json_url",
        output_format="jpg",
        output_format_vocab="jpg",

        # THE model with a real tier ladder. See NANO_BANANA_TIER_RESOLUTION.
        size_style="aspect_ratio_resolution",
        bills_per_tile=False,
        # 4K at 21:9 would be 6144 wide, but the program does not offer 21:9;
        # across the five ratios it does offer, the largest dimension is
        # 5376 (16:9 and 9:16 at 4K). These describe what the size table
        # produces -- nothing but the ratio and resolution words is ever sent.
        min_dimension=768, max_dimension=5376,
        # Natively specified to 4K, so the shared 1024px degradation threshold
        # would be flatly wrong here: it would warn about duplicated
        # structures and geometry drift on a model built to render this size.
        # Set to its true ceiling so size_warnings() stays silent, the same
        # call already made for every model that owns its own size table.
        max_safe_dimension=5376,

        steps_settable=False, default_steps=None, max_steps=None,
        supports_negative_prompt=False,
        supports_guidance=False,
        # Seedless, exactly like Lite. Reproducibility is impossible.
        supports_seed=False,

        # UNVERIFIED, as with every model in this family.
        prompt_soft_limit=800, prompt_hard_limit=1000,

        # THE ONLY MODEL IN THE PROGRAM WHERE THE TIER CHANGES THE BILL.
        # $67 / $101 / $151 per 1000 at 1K / 2K / 4K -- a High-tier batch
        # costs 2.25x a Draft one, where on every other model in the lineup
        # the tier is free or fixed. Over the $50/1000 tolerance at EVERY
        # tier, so the $$$ marker is fixed and safe.
        # Same family, same schema as Lite above (measured there).
        reference_field="image_input",
        reference_encoding="base64",
        price_fn=_per_resolution({
            "1K": 67.00 / 1000,
            "2K": 101.00 / 1000,
            "4K": 151.00 / 1000,
        }),
        price_note="THE MOST EXPENSIVE MODEL HERE — and the only one where the "
                   "quality tier changes what you pay: $67 per 1000 images at "
                   "Draft, $101 at Standard, $151 at High. A batch of 500 at High "
                   "costs about $75. It is the best quality available here, but it "
                   "is roughly 40 times the price of klein 4B, so treat it as a "
                   "model for a few special images rather than for a whole batch. "
                   "Check the batch total before you start. It accepts no seed, so "
                   "you cannot make two runs match.",
        is_free=False,
        licence="Google model hosted via Cloudflare; outputs are your "
                "Customer Content.",
    ),
]


POLLINATIONS_MODELS: list[ModelSpec] = [
    ModelSpec(
        key="poll-dreamshaper",
        output_format="jpg",  # measured: returns JPEG
        id="dreamshaper",
        label="DreamShaper 8 LCM",
        provider="pollinations",
        request_encoding="json",     # unused — pollinations is a GET URL
        response_encoding="raw",
        # MEASURED: the service clamps above ~0.59 MP regardless of the per-
        # side value, so max_dimension alone cannot express the limit -- the
        # size table does. 1024 is the largest side any tabled size uses.
        min_dimension=256, max_dimension=1024,
        steps_settable=False,
        supports_negative_prompt=False,
        supports_guidance=False,
        max_safe_dimension=1024,
        price_fn=_free, is_free=True,
        price_note="Free, and needs no key at all. Slow — about one image every 15 "
                   "seconds, and only one at a time — so it suits a handful of "
                   "images rather than a large batch. Images are capped at about "
                   "1024x576.",
    ),
    ModelSpec(
        key="poll-flux",
        output_format="jpg",  # measured: returns JPEG
        id="flux",
        label="FLUX.1 Schnell",
        provider="pollinations",
        request_encoding="json",
        response_encoding="raw",
        # Same measured 0.59 MP platform cap as the other Pollinations model.
        min_dimension=256, max_dimension=1024,
        steps_settable=False,
        supports_negative_prompt=False,
        supports_guidance=False,
        max_safe_dimension=1024,
        prompt_soft_limit=1000, prompt_hard_limit=1200,   # T5, ~256 tokens
        price_fn=_free, is_free=True,
        price_note="Free, and needs no key at all. Slow — about one image every 15 "
                   "seconds, and only one at a time — so it suits a handful of "
                   "images rather than a large batch. Images are capped at about "
                   "1024x576.",
    ),
]

ALL_MODELS: list[ModelSpec] = (
    CLOUDFLARE_MODELS + CLOUDFLARE_GATEWAY_MODELS + POLLINATIONS_MODELS
)
_BY_KEY = {m.key: m for m in ALL_MODELS}
_BY_ID = {m.id: m for m in ALL_MODELS}

DEFAULT_MODEL = "lightning"     # free, fastest, measured 1.6-3.0s
DEFAULT_RATIO = "16:9"
DEFAULT_TIER: Tier = "standard"


def get_model(key: str) -> ModelSpec:
    """Look up by short key or by full Cloudflare model id."""
    if key in _BY_KEY:
        return _BY_KEY[key]
    if key in _BY_ID:
        return _BY_ID[key]
    raise KeyError(
        f"unknown model {key!r}. Known: {', '.join(sorted(_BY_KEY))}"
    )


def models_for_provider(provider: str) -> list[ModelSpec]:
    return [m for m in ALL_MODELS if m.provider == provider]


# ---------------------------------------------------------------------------
# Style reference image — capability lookup and the recorded exclusions.
# ---------------------------------------------------------------------------

# Why the other models are NOT in the feature. Recorded here rather than in a
# doc because each one is a MEASUREMENT, and a future session looking at the
# krea schema will see the best-fitting field in the whole lineup and assume
# it was an oversight. It was not.
#
#   krea (both)     `image_style_references[].url` -- literally described as
#                   "Reference images to drive the visual style (up to 10)",
#                   with a per-image `strength`. UNREACHABLE: a data: URI is
#                   refused with `Validation error at
#                   image_style_references[0].url: Must be an HTTP(S) URL`,
#                   and a real URL is genuinely fetched. Serving the user's
#                   own file would mean hosting it publicly -- a tunnel or
#                   file host, i.e. a new dependency, a new credential and
#                   the user's art published to a third party. Cut by
#                   decision; do not revisit without a hosting story the user
#                   has asked for.
#   recraft (both)  no reference field exists. `controls` holds only `colors`
#                   and `background_color` -- the old note claiming a
#                   `controls.image` was wrong about the SHAPE, though right
#                   about the conclusion.
#   p-image         no reference field of any kind.
#   SD / Pollinations   txt2img only.
REFERENCE_IMAGE_EXCLUSIONS: dict[str, str] = {
    "krea-turbo": "krea accepts only an HTTP(S) URL, never a local file",
    "krea-medium": "krea accepts only an HTTP(S) URL, never a local file",
    "recraft-utility": "Recraft has no reference-image field at all",
    "recraft-v41": "Recraft has no reference-image field at all",
    "p-image": "p-image has no reference-image field at all",
}


def supports_reference_image(model_key: str) -> bool:
    """Can this model take a style reference image?

    The ONE question every GUI, CLI and engine check must ask. Derived from
    the spec rather than from a hardcoded model list, exactly as cost_band()
    is for pricing -- a list written anywhere else is a second source of
    truth that will drift the moment a model is added.
    """
    return get_model(model_key).reference_field is not None


def models_supporting_reference_image() -> list[ModelSpec]:
    """Every model that can take one, in registry order.

    Used for the GUI/CLI "use one of these instead" message, so the list the
    user is shown is always the real one.
    """
    return [m for m in ALL_MODELS if m.reference_field is not None]


def reference_models_sentence() -> str:
    """"FLUX.2 klein 4B, FLUX.2 klein 9B, ... or Nano Banana 2" — for prose.

    Built from the registry so a model added later appears in the message
    without anyone remembering to update a hand-written string.
    """
    names = [m.short_name for m in models_supporting_reference_image()]
    if not names:
        return "no model in this lineup"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


# ---------------------------------------------------------------------------
# Cost estimation — the calculator the CLI and (later) the GUI both read.
# ---------------------------------------------------------------------------

# AMENDED 2026-09-05 (gateway model expansion). This ceiling was originally an
# absolute scope limit: nothing pricier than $5/1000 was in scope at all. It
# now governs the `$` tier and the DEFAULT model choice, while `$$`/`$$$`
# models are opt-in, clearly marked in the dropdown, and still trigger the
# over-budget warning. This is a recorded decision, not an oversight -- see
# CLAUDE.md and docs/gateway-models-todo.md. Do not "fix" it back.
BUDGET_CEILING_PER_1000 = 5.00

# Cost tier thresholds, per 1000 images. DECIDED -- see the source doc.
COST_TIER_TOLERANCE_PER_1000 = 50.00   # $5/100, the user's stated tolerance

# ---------------------------------------------------------------------------
# COST BANDS -- the one vocabulary the whole app uses to describe price.
#
# REPLACED the "OVER BUDGET ... exceeds the $5.00 ceiling for this project"
# wording on 2026-09-05. Two things were wrong with it:
#
#   1. It described THIS PROJECT'S internal budget policy, which the user has
#      never heard of and cannot act on. "Over budget" against whose budget?
#   2. It was binary. Everything from $5.01 to $151 got the identical
#      sentence, so the label could not tell a mild overshoot from a model
#      that costs thirty times as much.
#
# The bands below say what a model COSTS, on a scale, in the same words
# everywhere -- dropdown marker, model note, cost calculator, CLI. The
# thresholds are the user's, stated 2026-09-05.
#
# Each band's upper bound is INCLUSIVE, so a model sitting exactly on a round
# number lands in the cheaper band (p-image at exactly $5.00 is LOW COST).
# That was a deliberate choice: a boundary that punishes a model for being
# exactly on it reads as a bug to anyone who checks the arithmetic.
# ---------------------------------------------------------------------------

CostBand = Literal["free", "low", "medium", "high", "extreme"]

# (band, inclusive upper bound per 1000 images). Ordered cheapest first;
# `cost_band()` walks it and takes the first match, so the bounds are the only
# place a threshold is written down.
COST_BAND_LIMITS: tuple[tuple[CostBand, float], ...] = (
    ("low",     5.00),
    ("medium",  20.00),
    ("high",    50.00),
    # "extreme" is whatever is left; it has no upper bound by definition.
)

COST_BAND_LABELS: dict[CostBand, str] = {
    "free":    "FREE (Neurons)",
    "low":     "LOW COST",
    "medium":  "MEDIUM COST",
    "high":    "HIGH COST",
    "extreme": "EXTREME COST",
}

# Short markers for the model dropdown, where the full band name would not
# fit. Same bands, same thresholds -- derived from cost_band() so the two can
# never disagree, which is exactly how the old marker and the old over-budget
# warning came to describe different things.
COST_BAND_MARKERS: dict[CostBand, str] = {
    "free":    "",
    "low":     "$",
    "medium":  "$$",
    "high":    "$$$",
    "extreme": "$$$$",
}

# Which ttk style each band uses, so severity looks the same everywhere.
COST_BAND_STYLES: dict[CostBand, str] = {
    "free":    "success.TLabel",
    "low":     "secondary.TLabel",
    "medium":  "secondary.TLabel",
    "high":    "warning.TLabel",
    "extreme": "danger.TLabel",
}


def cost_band_for_price(per_1000: float) -> CostBand:
    """Which cost band a per-1000-images price falls in.

    Split out from cost_band() so a PRICE can be graded directly -- the cost
    calculator grades the user's actual selected size, which is not always the
    reference size the dropdown marker uses.
    """
    if per_1000 <= 0:
        return "free"
    for band, upper in COST_BAND_LIMITS:
        if per_1000 <= upper:
            return band
    return "extreme"


def cost_band(model_key: str) -> CostBand:
    """The cost band for a model, at the fixed reference size.

    Always computed at COST_TIER_REFERENCE_SIZE, never at the user's current
    size, so a browsing marker does not flicker as the tier changes. The cost
    calculator grades the real selected size via cost_band_for_price().
    """
    m = get_model(model_key)
    if m.is_free:
        return "free"
    # Flat-priced models ignore the size argument entirely; tile-priced ones
    # need a real reference size, which is why one is used for both.
    #
    # But a model that owns its own size table may not be able to SERVE the
    # shared reference size, and on a per-resolution model that matters: the
    # shared 1536x864 is not a nano-banana size, so pricing the marker at it
    # would land on _per_resolution's unknown-size fallback and quote the
    # DEAREST tier. That fallback is right for a cost estimate (never
    # understate a bill) and wrong for a browsing marker, which should
    # describe the model's ordinary case.
    override = SIZE_TABLE_OVERRIDES.get(model_key)
    if override is not None:
        ref_ratio, _ = COST_TIER_REFERENCE_RATIO_TIER
        w, h = size_for(ref_ratio, "standard", model_key)
    else:
        w, h = COST_TIER_REFERENCE_SIZE
    return cost_band_for_price(m.cost_per_1000(w, h))


def cost_band_label(model_key: str) -> str:
    """The band name shown to the user, e.g. 'MEDIUM COST'."""
    return COST_BAND_LABELS[cost_band(model_key)]


# The size every cost-tier marker is computed at. FIXED deliberately: deriving
# the marker from the user's current selection would make it flicker as they
# change tier, and it is a browsing aid rather than a live quote.
COST_TIER_REFERENCE_SIZE = SIZES["16:9"]["standard"]   # 1536x864

# The same reference point expressed as ratio + tier, for models that own
# their own size table and so may not be able to serve the shared pixel size.
COST_TIER_REFERENCE_RATIO_TIER = ("16:9", "standard")


def cost_tier_marker(model_key: str) -> str:
    """The short cost marker for the model dropdown: '', '$'..'$$$$'.

    A thin view over cost_band(), NOT a parallel calculation. The marker and
    the band name used to be computed separately and could describe different
    things; deriving one from the other makes that impossible.
    """
    return COST_BAND_MARKERS[cost_band(model_key)]


FREE_NEURONS_PER_DAY = 10_000
NEURON_USD = 0.011 / 1000        # $0.011 per 1000 neurons


@dataclass(frozen=True)
class Estimate:
    model: str
    width: int
    height: int
    tiles: int
    megapixels: float
    count: int
    cost_per_image: float
    total_cost: float
    is_free: bool
    over_budget: bool
    warnings: list[str]
    errors: list[str]
    measured_neurons_per_tile: float | None = None

    # False for gateway models, which bill flat per image. The `tiles` field
    # is still populated (it is a pure geometric fact) but is NOT a billing
    # unit for these, and the UI must not present it as one.
    bills_per_tile: bool = True

    # Relative-cost marker for the dropdown: "", "$", "$$", "$$$".
    cost_tier: str = ""

    @property
    def cost_per_1000(self) -> float:
        return self.cost_per_image * 1000.0

    @property
    def free_images_per_day(self) -> int | None:
        """Estimated images/day on the free neuron allowance.

        None for free models (no cap applies).

        Uses ModelSpec.measured_neurons_per_tile when available -- a real
        rate read from Cloudflare's GraphQL usage API, not derived from the
        $ price. For klein4b that measured rate (~4.61 neurons/tile) is
        ~5.7x cheaper than deriving it from the published $1.72/1000 price,
        which assumes Cloudflare's stated 26.05 neurons/tile is what's
        actually billed -- it measurably isn't. See the ModelSpec docstring
        and docs/findings.md.

        Falls back to deriving it from the $ price for any model without a
        measured rate -- still labelled an estimate throughout the UI,
        since that derivation assumes the published per-tile rate holds.
        """
        if self.is_free or self.cost_per_image <= 0:
            return None
        # Gateway models are not billed in neurons at all -- they draw on
        # prepaid credit, not the daily free neuron allowance -- so "free
        # images per day" is not a meaningful number for them. Saying nothing
        # is correct here; deriving one from the $ price would invent a free
        # allowance that does not exist.
        if not self.bills_per_tile:
            return None
        if self.measured_neurons_per_tile is not None and self.tiles > 0:
            neurons_per_image = self.measured_neurons_per_tile * self.tiles
            return int(FREE_NEURONS_PER_DAY / neurons_per_image)
        return int((FREE_NEURONS_PER_DAY * NEURON_USD) / self.cost_per_image)


def estimate(model_key: str, width: int, height: int, count: int = 1) -> Estimate:
    m = get_model(model_key)
    per = m.cost_per_image(width, height)
    return Estimate(
        model=m.key,
        width=width,
        height=height,
        tiles=tile_count(width, height),
        megapixels=round(megapixels(width, height), 3),
        count=count,
        cost_per_image=per,
        total_cost=per * count,
        is_free=m.is_free,
        over_budget=(per * 1000.0) > BUDGET_CEILING_PER_1000,
        warnings=m.size_warnings(width, height),
        errors=m.validate_size(width, height),
        measured_neurons_per_tile=m.measured_neurons_per_tile,
        bills_per_tile=m.bills_per_tile,
        cost_tier=cost_tier_marker(m.key),
    )


def resolve_size(model_key: str, ratio: str, tier: Tier) -> tuple[int, int]:
    """Tile-optimal size for a model + ratio + tier, validated against the
    model's real constraints. Raises ValueError on a hard constraint break."""
    w, h = size_for(ratio, tier, model_key)
    m = get_model(model_key)
    errs = m.validate_size(w, h)
    if errs:
        raise ValueError(
            f"{ratio} at '{tier}' tier is {w}x{h}, which {m.key} cannot do: "
            + "; ".join(errs)
        )
    return w, h
