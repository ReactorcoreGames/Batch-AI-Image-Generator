"""config.json persistence.

Loaded on startup with defaults filled in, saved on every change. Deliberately
forgiving: a missing or malformed file falls back to defaults rather than
stopping the app.

CREDENTIALS ARE NEVER STORED HERE. API keys live in credentials.json (or the
environment) — see utils/credentials.py. Nothing in DEFAULT_CONFIG is a secret.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from core import models as M
from core import reference as R
from core.engine import (
    DEFAULT_CONCURRENCY,
    DEFAULT_DELAY,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
)

# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------
#
# NAMING SCHEME -- "NN GROUP - NAME". Documented in full in
# docs/preset-naming-scheme.md; the short version is that the dropdown is
# ordered by a plain sorted() on these keys, so THE NAME IS THE SORT ORDER.
# The two-digit number exists to decouple sort position from group name, and
# to keep working past nine groups (a single digit puts "10 X" between "01 X"
# and "02 X"). User presets get a leading "*" and sort above all of these --
# both by convention and, in _preset_names(), by mechanism.
#
# HOW THE BODIES ARE WRITTEN, and why:
#
#  * 300-500 characters. Above SD's ~300-character budget and far below
#    FLUX's ~2000, so the front of a preset is what SD sees and the tail is
#    what klein gets. Nothing is padded to reach the range.
#  * The load-bearing clause goes FIRST. On SD the tail is silently dropped,
#    and CLIP weights earlier tokens more heavily even within the limit.
#  * STYLE ONLY -- no subject matter. A style block containing "ancient
#    ruins" puts ruins in every image of the batch. The deliberate exceptions
#    are groups 06 COOL and 07 BEAUTY, where the subject framing IS the
#    product; see docs/preset-naming-scheme.md.
#  * No "(term:1.2)" / "((term))" weighting syntax -- the Cloudflare and
#    Pollinations APIs do not parse it, so it encodes as literal text.
#  * No embedding filenames ("verybadimagenegative_v1.3") or Pony tag
#    conventions ("score_6", "source_pony"); both are inert on this lineup.
BUILTIN_PRESETS: dict[str, str] = {
    "00 None - Blank": "",

    # -- 01 MAIN: the versatile generalists ------------------------------
    "01 Main - Digital Art": (
        "digital illustration, painterly rendering, bold confident strokes, clean "
        "linework and hard edges, chunky exaggerated proportions, vibrant saturated "
        "colors, strong contrast, expressive lighting, dynamic shading, hand-drawn "
        "feel, highly detailed, appealing and stylish, comic-book and anime "
        "influence, rich color depth, crisp focal detail, confident silhouette"
    ),
    "01 Main - Digital Painting": (
        "soft painterly 2D digital illustration, stylized animated game-background art, "
        "broad expressive brushwork, softly blended edges, atmospheric perspective, "
        "impressionistic environmental detail, rich saturated colors, warm/cool color "
        "contrast, diffuse cinematic lighting, subtle paper-and-paint texture, gentle "
        "haze and bloom, slightly softened focus"
    ),
    "01 Main - Digital Comic": (
        "bold hand-drawn 2D cartoon illustration, dynamic comic-book game art, strong "
        "expressive ink outlines, simplified graphic shapes, vibrant saturated colors, "
        "flat-to-painterly color fills, rough traditional drawing texture, subtle "
        "watercolor and colored-pencil feel, energetic perspective, exaggerated forms, "
        "crisp focal details with softer painted backgrounds, lively action-oriented "
        "composition"
    ),
    "01 Main - Digital Anime 90s": (
        "1990s anime screenshot, cel animation, classic anime film grain, painted "
        "background art, soft airbrushed shading, muted retro color palette, warm "
        "analog film tones, hand-inked linework, subtle chromatic softness, VHS-era "
        "cel look, nostalgic OVA aesthetic, glossy highlight dots on the eyes, gentle "
        "vignette, slightly desaturated shadows, classic character design proportions"
    ),
    "01 Main - 3D High Poly": (
        "high resolution 3D render, polished stylized CG, clean lines, exaggerated "
        "proportions, saturated colors, well defined shapes, hard edges, high "
        "definition materials, shiny reflections, expressive light play, atmospheric "
        "effects, subsurface and specular detail, ultra detailed surfacing, subjects "
        "rendered with higher saturation and contrast than the softer painterly "
        "background, cinematic depth"
    ),
    "01 Main - 3D Low Poly": (
        "low poly 3D render, faceted geometry, flat shaded surfaces, visible polygon "
        "edges, simplified blocky forms, limited flat color palette, clean untextured "
        "materials, soft ambient occlusion, gentle gradient lighting, crisp silhouette, "
        "deliberately minimal detail, stylized geometric abstraction, tidy readable "
        "shapes, indie game asset look, soft shadows, uncluttered composition"
    ),
    "01 Main - Frazetta Oil Paint": (
        "Frank Frazetta, epic fantasy realism, oil on board, bold intense composition, "
        "dramatic chiaroscuro lighting, deep shadows, rich earthy tones, strong "
        "contrast, expressive visible brushstrokes, heavy impasto, rugged textured "
        "surfaces, muscular heroic forms, raw primal energy, dynamic pose, atmospheric "
        "haze, dark moody backdrop, larger-than-life scale, timeless mythic ambiance, "
        "vivid painted detail"
    ),

    # -- 02 PHOTO: photographer skill, mood intensity, surface aesthetic --
    # Lettered A..S because the dropdown is ordered by a plain sorted() on the
    # names -- the letter IS the sort key, exactly as NN is for the groups.
    # A/B are skill level, C-F a mood-intensity dial, G-P surface and world
    # aesthetics, Q-S the three lens-driven keepers.
    "02 Photo - A - Intentional Pro": (
        "deliberate professional photography, every choice considered, expert command "
        "of available light, precise exposure, confident intentional composition, "
        "purposeful focal point, sharp where it matters, controlled tonal range, clean "
        "color accuracy, refined framing, skilled handling of any environment or hour, "
        "assured technical execution, polished professional finish, the work of an "
        "experienced photographer"
    ),
    "02 Photo - B - Candid Amateur": (
        "candid amateur snapshot, casual phone camera photo, unposed spontaneous "
        "moment, whatever light was available, mixed color temperature, slightly "
        "off-kilter framing, mild motion blur, visible sensor noise, flat unedited "
        "colors, imperfect exposure, everyday casual realism, gentle lens softness, "
        "authentic and uncurated, ordinary and unstaged, the honest look of a quick "
        "personal photo"
    ),
    "02 Photo - C - Soft Feel": (
        "soft gentle photography, tender low contrast, smooth luminous falloff, warm "
        "inviting tones, delicate diffused light, cozy and comforting atmosphere, "
        "gentle highlights, airy pastel color, calm and reassuring mood, muted "
        "harmonious palette, feathered soft edges, quiet intimacy, welcoming warmth "
        "throughout, relaxed and unhurried, an image that feels kind and safe"
    ),
    "02 Photo - D - Hard Feel": (
        "hard decisive photography, strong assertive contrast, crisp defined shadow "
        "edges, punchy tonal separation, bold directional light, vivid saturated color, "
        "sharp clarity, dramatic tonal weight, confident graphic impact, deep rich "
        "blacks, bright forceful highlights, striking and forceful, uncompromising "
        "visual strength, an image with bite and presence"
    ),
    "02 Photo - E - Cinematic": (
        "cinematic film still, color graded palette, filmic contrast curve, motivated "
        "atmospheric lighting, anamorphic lens character, subtle halation and bloom, "
        "shallow cinematic depth of field, teal and amber tonality, gentle film grain, "
        "widescreen visual language, deliberate mood and narrative weight, professional "
        "cinematography, a single frame lifted from a feature film"
    ),
    "02 Photo - F - Extreme": (
        "extreme maximalist photography, contrast pushed to the limit, crushed inky "
        "blacks, blazing blown highlights, hyper-saturated color, aggressive clarity "
        "and micro-contrast, overwhelming visual intensity, brutal tonal extremes, "
        "searing luminance, relentless and excessive, sensory overload, dialed far past "
        "tasteful, unapologetically over the top, maximum impact"
    ),
    "02 Photo - G - Glossy-Shiny": (
        "glossy polished photography, immaculate reflective surfaces, wet-look sheen, "
        "crisp specular highlights, mirror-bright finish, rich enhanced color, flawless "
        "smooth materials, liquid gleam, high-gloss lacquered surfaces, pristine and "
        "spotless, luminous surface reflections, slick and sleek, buffed to perfection, "
        "everything gleaming and showroom fresh"
    ),
    "02 Photo - H - Gritty-Dirty": (
        "gritty dirty photography, grime and dust on every surface, smudged and "
        "stained, soiled worn materials, desaturated muted color, caked filth in the "
        "crevices, greasy residue, dusty haze, tired dulled surfaces, lived-in and "
        "unwashed, real-world squalor, honest unglamorous texture, heavy with "
        "accumulated dirt, unclean and authentic"
    ),
    "02 Photo - I - Grunge-Rough": (
        "grunge rough photography, chipped and scratched surfaces, corroded rusted "
        "metal, cracked peeling material, coarse abrasive texture, heavy physical "
        "damage, battered and beaten, raw unfinished edges, flaking decay, pitted and "
        "gouged, harsh industrial wear, brutal material erosion, aggressively textured, "
        "weathered by force and time"
    ),
    "02 Photo - J - Dystopian-Bleak": (
        "dystopian bleak photography, cold desaturated palette, oppressive heavy "
        "atmosphere, sickly grey-green cast, crushing sense of decline, dim joyless "
        "light, thick polluted air, hopeless muted tones, brutal cold shadows, "
        "crumbling ruined world, suffocating gloom, desolate and abandoned, grim "
        "unrelenting mood, a future that went badly wrong"
    ),
    "02 Photo - K - Utopian-Hightech": (
        "utopian high-tech photography, gleaming seamless surfaces, brilliant clean "
        "luminance, immaculate white and chrome, glowing accent light, precision "
        "engineered perfection, weightless elegance, optimistic radiant atmosphere, "
        "flawless smooth forms, advanced and effortless, harmonious calm order, bright "
        "hopeful future, everything working beautifully"
    ),
    "02 Photo - L - Dreamy-Surreal": (
        "dreamy surreal photography, soft glowing haze, ethereal bloom, unreal shifted "
        "colors, floating weightless quality, gauzy diffusion, iridescent pastel light, "
        "gentle impossibility, hypnotic otherworldly calm, melting soft edges, luminous "
        "fog, half-remembered vision, blurred boundary between real and imagined, "
        "drifting and hallucinatory"
    ),
    "02 Photo - M - Noir-Gothic": (
        "noir gothic photography, deep engulfing shadow, ornate brooding darkness, "
        "dramatic single-source light, heavy chiaroscuro, desaturated near-monochrome, "
        "elegant decayed grandeur, moody atmospheric haze, stark pools of illumination, "
        "velvet blacks, solemn ceremonial weight, beautiful and severe, shadowed "
        "romantic melancholy"
    ),
    "02 Photo - N - Horror-Terror": (
        "horror photography, dread-soaked atmosphere, sickly jaundiced light, "
        "oppressive crawling shadow, cold clammy tones, wrongness in the air, harsh "
        "unnatural illumination, suffocating darkness at the edges, unsettling tonal "
        "dissonance, clammy damp surfaces, mounting sense of threat, nauseous color "
        "cast, something deeply wrong, terrifying and inescapable"
    ),
    "02 Photo - O - Nuclear-Fire": (
        "nuclear fire photography, blazing incandescent glow, molten ember light, "
        "scorched blackened surfaces, searing orange and white heat, thick roiling "
        "smoke, glowing cinders in the air, blistering radiant intensity, heat-warped "
        "shimmering air, raging inferno illumination, burnt charred tones, apocalyptic "
        "firelight, everything ablaze"
    ),
    "02 Photo - P - Long Exposure": (
        "long exposure photograph, flowing motion streaks, luminous light trails, silky "
        "smoothed movement, static elements rendered razor sharp, time compressed into "
        "a single frame, glowing traced paths of light, blurred drifting motion against "
        "solid anchors, extended shutter, elegant sweeping trails, stillness and motion "
        "together, tripod-steady clarity"
    ),
    "02 Photo - Q - Rad Fisheye": (
        "16mm fisheye lens photograph, extreme barrel distortion, curved bent horizon, "
        "ultra wide field of view, exaggerated perspective, enlarged looming foreground "
        "subject, rapidly receding background, vignetted circular edges, dynamic low "
        "angle, action sports photography energy, deep focus, bold saturated color, "
        "high contrast, dramatic sense of speed and scale, punchy and kinetic"
    ),
    "02 Photo - R - Macro Closeup": (
        "50mm macro lens photograph, extreme close-up, ultra fine surface texture, "
        "razor thin depth of field, creamy bokeh falloff, focus stacking clarity, "
        "exaggerated microscopic detail, soft diffused studio lighting, delicate "
        "specular highlights, visible grain and fibre, crystalline sharpness at the "
        "focal plane, soft focus edges, intimate scale, high resolution, pristine detail"
    ),
    "02 Photo - S - Tilt Shift": (
        "tilt-shift photograph, miniature faking effect, narrow band of sharp focus, "
        "strong blur above and below, high vantage point looking down, oversaturated "
        "toy-like colors, boosted contrast, crisp small-scale detail, everything "
        "appearing as a scale model diorama, bright even daylight, clean shadows, "
        "playful and precise, selective plane of focus, shallow apparent depth"
    ),

    # -- 03 STYLE: art media and rendering -------------------------------
    "03 Style - Sketch": (
        "color pencil sketch, airbrushed illustration, anime influence, centered "
        "subject, faded and blurred edges, partially drawn elements, selective "
        "rendering of key details, deliberate incompleteness, soft textures, muted "
        "color palette, light tooth of paper showing, loose confident linework, "
        "conceptual rather than literal, unfinished margins, quiet and considered"
    ),
    "03 Style - Drawing": (
        "color pencil drawing, centered subject, softly blurred and faded edges, "
        "selective rendering of key details, deliberate incompleteness, muted earthy "
        "color palette, textured strokes, layered transparencies, ethereal dreamlike "
        "quality, conceptual rather than literal, leaves room for interpretation, "
        "evokes a mood, sense of ambiguity, visible paper texture, gentle tonal shifts"
    ),
    "03 Style - Graphite Watercolor": (
        "graphite sketch on white background, watercolor accents and washes, centered "
        "subject, softly defined edges, selective rendering of key details, limited "
        "earthy palette, textured mixed media, bleeding pigment edges, visible pencil "
        "hatching, ethereal quality, conceptual rather than literal, sparse and "
        "incomplete, generous white space, delicate and restrained"
    ),
    "03 Style - Retro": (
        "retro-futurist oil painting, oil on board, Syd Mead, John Berkey, Hajime "
        "Sorayama, airbrushed chrome and gloss, optimistic mid-century science fiction, "
        "bold saturated color, colorful gradient background, dramatic rim lighting, "
        "smooth reflective surfaces, clean visionary design, vintage magazine "
        "illustration, nostalgic warmth, confident graphic composition, glossy finish"
    ),
    "03 Style - Vector": (
        "wireframe vector illustration, see-through neon glow lines, 3D wireframe "
        "construction, color-coded layers, precise linework, high-tech blueprint "
        "aesthetic, dark background, luminous edges, depth-indicating grid, crisp clean "
        "lines, intricate technical detail, minimal shading, soft neon gradients, "
        "hologram transparency, chromatic aberration, layered dimensionality, cyber "
        "schematic"
    ),
    "03 Style - Popart": (
        "pop art, high contrast, bold color blocking, duotone, posterized flat tones, "
        "halftone patterns, stencil and street art influence, rough expressive "
        "brushstrokes, paint splash and drip effects, gritty distressed texture, "
        "weathered urban surfaces, dramatic hard shadows, graphic and raw, aggressive "
        "brushwork, layered composition, spray paint aesthetic"
    ),
    "03 Style - Pixel Front View": (
        "32-bit pixel art illustration, vivid saturated colors, sharp crispy edges, "
        "exaggerated cartoony proportions, playful and vibrant, stylized simplicity, "
        "detailed pixel clusters, compact readable forms, charming low-res textures, "
        "bright highlights, limited palette, clean dithering, soft outlines, front view "
        "perspective, symmetrical framing, dynamic and colorful"
    ),
    "03 Style - Pixel Side View": (
        "32-bit pixel art illustration, vivid saturated colors, sharp crispy edges, "
        "exaggerated cartoony proportions, playful and vibrant, stylized simplicity, "
        "detailed pixel clusters, compact readable forms, charming low-res textures, "
        "bright highlights, limited palette, clean dithering, soft outlines, side view "
        "perspective, clean profile silhouette, dynamic and colorful"
    ),

    # -- 04 SPECIAL: strong flavour, narrower use ------------------------
    "04 Special - Ghostly": (
        "ghostly translucent forms, liquid foggy reflective materials, surreal and "
        "dreamlike, luminescent inner glow, soft radiance, weightless drift, phantom "
        "outlines, echoing shapes, holographic shimmer, flickering opacity, muted "
        "pastels, cool desaturated tones, ambient flow, delicate and serene, celestial "
        "astral atmosphere, otherworldly presence, retrofuturist haze, hypnotic calm"
    ),
    "04 Special - Whitespace": (
        "sharp precise lines on a light background, high-contrast wireframe, minimal "
        "shading, clean and abstract, fine line detail, layered transparency, "
        "structural depth, digital blueprint aesthetic, monochrome with subtle color "
        "accents, generous white space, sleek and futuristic, analytical technical "
        "schematic, soft shadows, angular structure, polished and modern, sophisticated"
    ),
    "04 Special - Splash": (
        "vibrant explosion of color, fluid dynamics, liquid textures, glass-like shards, "
        "solid forms made of flowing fluid, bursting outward motion, translucent "
        "reflective surfaces, glossy radiant highlights, juicy and vivid, molten "
        "textures, kinetic energy, surreal yet coherent, rich color contrast, "
        "high-definition splatters, layered depth, organic yet structured, striking"
    ),
    "04 Special - Glitch": (
        "digital distortion glitch effect, pixelated and corrupted imagery, datamosh "
        "artifacts, chromatic aberration, scanlines and visual static, vibrant neon "
        "colors, jagged fragmented edges, torn displaced blocks, unexpected "
        "juxtapositions, chaotic and unpredictable, lo-fi digital decay, experimental "
        "and avant-garde, unsettling yet compelling, signal noise, RGB channel split"
    ),

    # -- 05 ASSET: the output is meant to be a usable file ---------------
    "05 Asset - Premium Product Shot": (
        "commercial product photography, studio lighting, pure white seamless backdrop, "
        "perfect subject isolation, controlled reflections, professional soft shadows, "
        "clean centered composition, sharp focus throughout, photorealistic, precise "
        "color accuracy, premium retouching, perfect exposure, e-commerce standard, "
        "high-end advertising quality, crystal clear, pristine detail"
    ),
    "05 Asset - Sticker": (
        "vector illustration sticker art, isolated on a flat black background, centered "
        "subject, bold thick outlines, vibrant anime-inspired colors, cartoon "
        "exaggeration, strong contrast, painterly yet clean, expressive lighting, "
        "dynamic shading, chunky proportions, crisp lines, hard edges, die-cut border, "
        "eye-catching and stylish, highly detailed, hand-drawn feel"
    ),
    # These five describe STRUCTURE only -- framing, background, shape
    # legibility -- and deliberately name no style, medium or subject, so any
    # prompt can be run through them. They also assume no aspect ratio: the
    # user picks that with the size control, and baking "wide" or "vertical"
    # into the body would fight it.
    "05 Asset - Silhouette": (
        "silhouette image, subject rendered as a single solid filled shape, one flat "
        "contrasting background color, bold unmistakable outline, clean readable "
        "contour, strong graphic shape language, complete subject shape visible, crisp "
        "hard edges, maximum shape clarity, instantly recognizable by outline alone, "
        "stark two-tone separation, centered and legible"
    ),
    "05 Asset - Seamless Texture": (
        "seamless tileable texture, flat-on perpendicular overhead view, pattern "
        "filling the entire frame edge to edge, perfectly uniform even lighting across "
        "the whole surface, consistent scale throughout, continuous repeating pattern "
        "running past all four edges, flat orthographic projection, evenly distributed "
        "detail, uniform brightness corner to corner, repeats invisibly when tiled"
    ),
    "05 Asset - App Icon": (
        "app icon design, single bold centered element, strong instantly readable "
        "silhouette, simple clean background, large simplified forms, high shape "
        "clarity at small sizes, confident graphic weight, clear figure-to-ground "
        "separation, filling the canvas boldly, minimal essential detail, immediately "
        "recognizable at a glance, iconic and distilled"
    ),
    "05 Asset - Promotional Cover": (
        "promotional cover art, striking eye-catching presentation, bold confident "
        "composition, strong central visual hook, rich vibrant color, dramatic "
        "appealing lighting, polished commercial finish, high production value, dynamic "
        "energy, professional marketing quality, inviting and memorable, designed to "
        "make someone stop and look, premium promotional appeal"
    ),
    "05 Asset - Advertisement Poster": (
        "advertisement poster, bold commercial impact, arresting hero presentation, "
        "high contrast and clarity, saturated punchy color, dramatic advertising "
        "lighting, glossy professional finish, strong visual hierarchy, clean "
        "uncluttered staging, confident graphic presence, persuasive and aspirational, "
        "premium print advertising quality, designed to sell at a glance"
    ),
    "05 Asset - Pixel Front View Single Object": (
        "32-bit pixel art, single centered object, pure flat green background, vivid "
        "saturated colors, sharp crispy edges, exaggerated cartoony proportions, "
        "stylized simplicity, detailed pixel clusters, compact readable form, charming "
        "low-res textures, bright highlights, soft outlines, limited palette, front "
        "view perspective, isolated with no scenery, clean cut-out silhouette"
    ),
    "05 Asset - Pixel Front View Spritesheet": (
        "32-bit pixel art spritesheet, organized grid layout, animation-ready frames, "
        "pure flat green background, vivid saturated colors, sharp crispy edges, "
        "exaggerated cartoony proportions, stylized simplicity, detailed pixel clusters, "
        "compact forms, charming low-res textures, bright highlights, soft outlines, "
        "consistent scale across frames, front view perspective, evenly spaced cells"
    ),
    "05 Asset - Pixel Side View Single Object": (
        "32-bit pixel art, single centered object, pure flat green background, vivid "
        "saturated colors, sharp crispy edges, exaggerated cartoony proportions, "
        "stylized simplicity, detailed pixel clusters, compact readable form, charming "
        "low-res textures, bright highlights, soft outlines, limited palette, side view "
        "perspective, clean profile silhouette, isolated with no scenery"
    ),
    "05 Asset - Pixel Side View Spritesheet": (
        "32-bit pixel art spritesheet, organized grid layout, animation-ready frames, "
        "pure flat green background, vivid saturated colors, sharp crispy edges, "
        "exaggerated cartoony proportions, stylized simplicity, detailed pixel clusters, "
        "compact forms, charming low-res textures, bright highlights, soft outlines, "
        "consistent scale across frames, side view perspective, evenly spaced cells"
    ),

    # -- 06 COOL: concept forges. These DO impose subject matter, and that
    # is the point -- the prompt file carries the varying part (a color, a
    # purpose, an environment) and the preset does the heavy lifting.
    "06 Cool - Futuristic Human World": (
        "optimistic near-future human environment, color-coded standardized yet stylish "
        "design, sleek lines and rounded edges, abundant natural light, prefabricated "
        "modular construction with bespoke touches, warm inviting palette with subtle "
        "accent colors, clean and organized, greenery integrated throughout, advanced "
        "materials, dynamic lighting, safe and sustainable, lived-in and thriving, "
        "futuristic yet grounded, functional elegance"
    ),
    "06 Cool - Combat Robot": (
        "reimagined as a towering armored combat mecha, hard-surface mechanical design, "
        "layered armor plating with panel lines, powerful articulated limbs and heavy "
        "actuators, glowing energy accents, battle-worn scratched paint, aggressive "
        "purposeful stance, industrial military engineering, dramatic low angle, rim "
        "lighting, volumetric haze, high contrast shadows, imposing scale, gleaming "
        "metal and matte composite surfaces, concept art rendering"
    ),
    "06 Cool - Mega Vehicle": (
        "reimagined as a colossal fortress vehicle, megastructure machine, dramatic "
        "front-view composition, symmetrical framing, low-angle heroic perspective, "
        "immense sense of scale, heavy armored plating, exposed mechanical greebling, "
        "volumetric fog, atmospheric depth, high contrast shadows, rim lighting, "
        "gleaming weathered surfaces, telephoto compression, Chris Foss, Syd Mead, "
        "Peter Elson, dark moody background, industrial concept art"
    ),
    "06 Cool - Homo Mugen": (
        "an elegantly bioengineered human of a far-future age, unmistakably human and "
        "strikingly beautiful, flawless luminous skin with subtle iridescent sheen, "
        "impossible hair colors with soft inner glow, refined graceful features, "
        "delicate bioluminescent markings, elegant grown-not-worn adornments, serene "
        "confident poise, ageless vitality, soft rim light, gentle chromatic gradients, "
        "high fashion styling, radiant and healthy, sophisticated and alluring"
    ),

    # -- 07 BEAUTY: portrait, glamour and macro treatments. Like 06, these
    # impose framing on purpose. Living-photographer names were removed from
    # this group only, to buy back length -- the sources ran 700-1250 chars.
    "07 Beauty - Pretty Eyes": (
        "extreme close-up beauty macro of an eye, ultra-detailed iris, crystalline "
        "clarity, bright catch lights, long feathered eyelashes, dramatic eye makeup "
        "and artistic liner, intense compelling gaze, luminous highlights, glassy wet "
        "surface, razor sharp focus, studio ring lighting, colored gradient light, soft "
        "bokeh background, symmetrical center-framed composition, dramatic contrast, "
        "professional beauty photography, micro detail"
    ),
    "07 Beauty - Pretty Lips": (
        "beauty macro photography of lips, perfect lip definition, glossy dewy finish, "
        "subtle parting, ultra-detailed natural lip texture, professional makeup "
        "artistry, volumetric highlights catching the gloss, studio beauty lighting, "
        "soft gradient shadows, rich color saturation, flawless skin rendering, perfect "
        "cupid's bow, plush dimensional depth, extreme close-up, soft focus edges, "
        "editorial cosmetics campaign quality"
    ),
    "07 Beauty - Pretty Hand": (
        "professional beauty macro of a hand, ultra-detailed manicure, glossy nail "
        "finish, elegant graceful finger positioning, delicate bone structure, smooth "
        "moisturized porcelain skin, studio ring lighting, soft dimensional shadows, "
        "crystal clear macro focus, clean studio backdrop, gradient reflections, "
        "shallow depth of field, subtle skin veining, elegant wrist angle, luxury "
        "fashion aesthetic, salon-perfect finish"
    ),
    "07 Beauty - Pretty Ear": (
        "extreme macro photography of an ear with fine jewelry, luxury metallic "
        "reflections, gem facet sparkle, delicate anatomical detail, translucent "
        "backlit skin, fine vellus hair, professional product lighting, focus stacked "
        "clarity, soft gradient background, dimensional shadows, glossy mirror-like "
        "metal surfaces, porcelain skin texture, elegant composition, shallow depth of "
        "field, ethereal glow, jewelry campaign quality"
    ),
    "07 Beauty - Entrancing Portrait": (
        "ethereal beauty portrait, direct intense gaze, professional beauty lighting, "
        "alternative editorial makeup, otherworldly atmosphere, volumetric fog, "
        "dramatic depth, haunting elegance, razor sharp focus on the face, cinematic "
        "color grading, dark mystical mood, atmospheric rim lighting, crystalline skin "
        "texture, high fashion editorial, hypnotic center-focused composition, "
        "dimensional shadows, dark glamour, premium retouching, magnetic presence"
    ),
    "07 Beauty - Latex Beauty": (
        "glossy latex fashion beauty shot, slick smooth reflective surfaces, patterned "
        "dark indigo and black latex outfit, hypnotic dark purple vignette, purple glow "
        "and exotic mist, creamy pink lipgloss, long feathered eyelashes, long almond "
        "shaped nails with french tips, wet specular highlights, dramatic studio "
        "lighting, high contrast, editorial fashion photography, sleek and alluring, "
        "rich saturated color"
    ),
    "07 Beauty - Mirror Selfie Room": (
        "mirror selfie composition, full-body reflection, authentic candid moment, "
        "natural indoor lighting, genuine relaxed expression, comfortable casual pose, "
        "mirror frame visible, everyday lived-in room, softly blurred background, "
        "natural color grading, real mirror reflections, unposed authenticity, "
        "lifestyle blogging aesthetic, gentle depth of field, contemporary casual "
        "style, natural shadows"
    ),
    "07 Beauty - Mirror Selfie Phone": (
        "mirror selfie composition, smartphone held up and visible in the reflection, "
        "full-body mirror shot, authentic candid moment, natural indoor lighting, "
        "genuine expression, comfortable casual pose, mirror frame visible, everyday "
        "location, softly blurred background, natural color grading, influencer "
        "lifestyle photo, unposed authenticity, gentle depth of field, contemporary "
        "casual style, natural shadows"
    ),

    # -- 08 GAMES: deliberately small. A game preset earns its slot by
    # capturing camera and rendering nuance the generic styles cannot, and
    # that needs per-title research. See docs/preset-naming-scheme.md.
    "08 Games - ASTRONEER (Action/3D)": (
        "soft pastel color palette, clean minimalist stylized 3D render, smooth "
        "untextured surfaces, rounded friendly geometric forms, gentle gradient skies, "
        "low poly shapes with soft edges, whimsical and optimistic, bright even "
        "lighting, approachable silhouettes, muted candy tones, weightless airy "
        "atmosphere, uncluttered composition, playful sense of wonder and discovery, "
        "soft ambient occlusion"
    ),
    "08 Games - Planetary Annihilation (Strategy/3D)": (
        "deliberately polygonal and faceted stylized 3D, straight lines and 90 and 45 "
        "degree angles, blocky hard-edged shapes, uniform flat colors on decals and "
        "textures, simple edge wear emphasizing polygon facets, exaggerated proportions, "
        "highly readable silhouettes, saturated high-contrast foreground against a "
        "desaturated low-contrast watercolor painterly background, distant orbital "
        "vantage, clean and legible at small scale"
    ),
    "08 Games - Super Mario Galaxy (Platformer/3D)": (
        "whimsical bright saturated color palette, smooth polished cartoon 3D render, "
        "clean rounded shapes, playful exaggerated proportions, radiant magical glow "
        "effects, sparkling particle highlights, dynamic wide-angle perspective, "
        "buoyant weightless composition, joyful and family-friendly, imaginative "
        "fantastical design, soft rim lighting, cheerful warm tones, immaculate "
        "readable silhouettes"
    ),
    "08 Games - XCOM 2 (Tactics/3D)": (
        "muted desaturated palette, earthy grounded tones, gritty realistic textures, "
        "somber tense atmosphere, occasional pops of vibrant high-contrast light, "
        "subdued strategic lighting, deep dramatic shadows, isometric elevated "
        "three-quarter camera angle, detailed grounded environments, cinematic color "
        "grading, near-future military austerity, weathered surfaces, suspenseful and "
        "oppressive mood, stylized realism"
    ),
    "08 Games - Homeworld 1 (Strategy/3D)": (
        "deliberately crude low poly 3D models, sparse flat-shaded surfaces, simple "
        "untextured or coarsely patterned panels, blocky angular silhouettes with "
        "visible facets, distant strategic space-combat vantage, small readable shapes "
        "against a vast dark starfield, minimal geometric detail per hull, utilitarian "
        "industrial greebling kept sparse, muted metallic palette, faint engine glow "
        "points, wide empty black backdrop, late-1990s real-time-strategy render "
        "fidelity, functional rather than ornate design language"
    ),
    "08 Games - Homeworld 2 (Strategy/3D)": (
        "sleek high poly 3D models, refined dense surface detailing, layered plating "
        "with fine seams and greeble work, smooth curved hull transitions alongside "
        "sharp angular accents, distant strategic space-combat vantage, small readable "
        "shapes against a vast dark starfield, richer specular highlights on polished "
        "metal, subtle textured panel variation, cooler high-tech metallic palette, "
        "brighter engine glow trails, wide empty black backdrop, evolved early-2000s "
        "real-time-strategy render fidelity, ornate refined design language"
    ),
    "08 Games - Super Mario World (Platformer/2D Sprite)": (
        "16-bit SNES sprite era, chunky bright cartoon character sprites with thick "
        "black outlines, saturated primary color palette, painterly parallax "
        "background layers with soft gradient skies, layered scrolling depth "
        "suggesting Mode 7 pseudo-3D, tile-based side-view level composition, bold "
        "simple shading with minimal dithering, cheerful whimsical tone, crisp pixel "
        "edges at low resolution, friendly rounded character silhouettes, warm "
        "inviting lighting, classic early-1990s console platformer rendering"
    ),
    "08 Games - Donkey Kong Country (Platformer/2D Sprite)": (
        "pre-rendered CGI sprites downsampled to a limited 16-bit palette, glossy "
        "rendered specular lighting baked flatly into static sprite frames, "
        "early-1990s Silicon Graphics workstation render look, soft airbrushed "
        "shading with visible color banding, chunky rounded character forms with a "
        "plasticky sheen, dense jungle parallax background layers, warm earthy "
        "palette accented by saturated highlights, slight aliasing at sprite edges, "
        "side-view tile-based level composition, moody atmospheric depth behind "
        "bright foreground sprites"
    ),
    "08 Games - Super Metroid (Action/2D Sprite)": (
        "dark moody 16-bit pixel art, oppressive isolated atmosphere, sparse "
        "desaturated palette of cold blues and greys with rare pockets of alien "
        "color, heavy use of shadow and negative space, sprawling side-view "
        "tile-based environments, sense of dread and quiet tension, minimal ambient "
        "detail emphasizing emptiness, muted lighting with occasional eerie glow "
        "accents, grainy low-resolution texture, deliberate pacing conveyed through "
        "stillness, early-1990s console pixel rendering, haunting subdued mood"
    ),
    "08 Games - Metroid Fusion (Action/2D Sprite)": (
        "tight claustrophobic sprite scale on a Game Boy Advance era palette, cooler "
        "sterile blue-grey and green color scheme, higher-contrast graphic pixel art "
        "with cleaner harder edges than earlier 16-bit work, cramped corridor-driven "
        "side-view tile composition, clinical antiseptic lighting, sharper silhouette "
        "readability at small sprite size, sparse but crisp background detailing, "
        "tense sanitized industrial mood, early-2000s handheld console pixel "
        "rendering, restrained saturation with punchy accent highlights"
    ),
    "08 Games - Warning Forever (Shmup/2D)": (
        "top-down 2D vector-inspired composition, bold glowing neon wireframe "
        "outlines over flat solid color fills, angular geometric mechanical "
        "silhouettes built from interlocking shapes, soft particle bloom and glow "
        "effects around edges, dark black background making colors pop, "
        "early-2000s independent shoot-em-up rendering, retro anime "
        "science-fiction influence, minimal flat shading, high-contrast graphic "
        "clarity, clean thin outline weight, sparse background clutter, energetic "
        "kinetic composition"
    ),
    "08 Games - Battleships Forever (Shmup/2D)": (
        "top-down 2D vector-inspired composition, bold glowing neon wireframe "
        "outlines containing textured detailed fills rather than flat color, "
        "angular geometric mechanical silhouettes with visible internal paneling "
        "and surface detail within each wireframe segment, soft particle bloom and "
        "glow effects around edges, dark black background making colors pop, "
        "early-2000s independent space-combat rendering, retro anime "
        "science-fiction influence, layered shading within outlined shapes, "
        "high-contrast graphic clarity, sparse background clutter"
    ),
    "08 Games - DEFCON (Strategy/2D Vector)": (
        "minimalist neon vector line art, thin glowing outline geography on a stark "
        "black background, high-contrast glow-on-black rendering, monochrome or "
        "duotone color scheme with a single dominant neon hue, sparse abstract "
        "composition, cold detached military-strategic tone, clean thin line weight "
        "throughout, subtle scan-line or radar-sweep texture, wide top-down map "
        "perspective, austere uncluttered layout, muted ambient glow bloom, "
        "early-2000s minimalist strategy interface aesthetic"
    ),
    "08 Games - Portal (Puzzle/3D)": (
        "sterile clinical environment design, clean white paneling accented with "
        "bold orange and blue geometric trim, exposed technical infrastructure and "
        "utilitarian piping visible behind smooth surfaces, cool even fluorescent "
        "lighting with minimal warm tones, sparse minimalist industrial-scientific "
        "composition, sharp clean geometric architecture, high-key even exposure, "
        "subtle ambient occlusion in paneled seams, calm sterile mood, glossy "
        "reflective floor surfaces, restrained color palette dominated by white and "
        "grey"
    ),
    "08 Games - Tribes Ascend (FPS/3D)": (
        "blocky angular futuristic hardware design leaning toward low poly "
        "hard-surface geometry, faceted armor plating with sharp geometric "
        "transitions, cool metallic palette accented by bright team-color "
        "highlights, dynamic high-speed aerial motion blur, wide open sky-and-terrain "
        "vistas suggesting vertical traversal, glossy specular highlights on smooth "
        "panel surfaces, sci-fi athletic design language, crisp clean edge "
        "definition, dramatic sweeping camera angle, energetic kinetic composition, "
        "early-2010s stylized realism"
    ),
    "08 Games - Battletech (Tactics/3D)": (
        "chunky heavy mechanical silhouettes with immense implied mass, thick "
        "layered armor plating and visible rivets and seams, industrial "
        "giant-machine weight conveyed through blocky proportions, muted military "
        "palette of olive, rust and gunmetal grey, weathered scratched surface "
        "detailing, low dramatic camera angle emphasizing scale, overcast diffused "
        "lighting, grounded battlefield atmosphere, dense mechanical greeble detail "
        "at joints, somber restrained color grading, tabletop-miniature-inspired "
        "hard-surface rendering"
    ),
    "08 Games - C&C Allies (RTS/Isometric 2D)": (
        "isometric real-time-strategy camera angle, clean blue and silver high-tech "
        "color scheme, retro-futurist 1950s-tinged military design language, "
        "polished streamlined hardware surfacing, crisp readable unit silhouettes "
        "against a bright green terrain palette, orderly disciplined composition, "
        "glossy specular highlights on smooth metal, bold primary accent lighting, "
        "saturated cheerful strategic-map color grading, tidy grid-aligned scene "
        "layout, nostalgic alternate-history atomic-age aesthetic"
    ),
    "08 Games - C&C Yuri (RTS/Isometric 2D)": (
        "isometric real-time-strategy camera angle, organic and mechanical forms "
        "fused into unsettling bio-technological hybrids, dominant purple and "
        "magenta color scheme with sickly bioluminescent accents, pulsing energy "
        "glow embedded in fleshy-metallic surfacing, alien psychic unease conveyed "
        "through asymmetric organic curves, dim moody ambient lighting with "
        "saturated glow highlights, unsettling dreamlike strategic-map color "
        "grading, grid-aligned scene layout, hypnotic surreal atmosphere, glossy "
        "wet-looking organic textures"
    ),
    "08 Games - C&C GDI (RTS/Isometric 2D)": (
        "isometric real-time-strategy camera angle, desolate ashen wasteland "
        "terrain, industrial-military high-tech hardware surfacing against a "
        "devastated backdrop, desaturated grey and brown palette pierced by toxic "
        "green glow accents, cracked scorched ground textures, hazy polluted "
        "atmospheric lighting, grim war-torn strategic-map color grading, "
        "grid-aligned scene layout, oppressive apocalyptic mood, weathered "
        "rust-streaked surfaces, sparse skeletal vegetation, harsh contrast between "
        "ruin and glowing hazard"
    ),
    "08 Games - Halo Covenant (RTS/3D)": (
        "organic-curved biomechanical design language in dominant purple and gold, "
        "ornate alien surfacing with intricate ceremonial detailing, glowing "
        "energy-shield accents rippling across smooth hull curves, dramatic "
        "void-black backdrop, reverent quasi-religious grandeur in composition, "
        "warm gold rim lighting against cool purple ambient tones, sweeping "
        "cinematic camera angle, polished glossy alien material finish, soft "
        "volumetric energy glow, ornamental symmetry, epic strategic-scale framing"
    ),
    "08 Games - Red Faction EDF (Action/3D)": (
        "dusty red-toned planetary industrial palette, utilitarian brutalist "
        "architecture with exposed rebar and raw concrete, oppressive authoritarian "
        "occupier design language, weathered corrugated metal structures, hazy "
        "ochre atmospheric lighting, sun-bleached washed-out color grading, harsh "
        "midday shadow contrast, gritty sandblasted surface texture, sprawling "
        "open-world dusty vista, grounded destructible-environment aesthetic, grim "
        "utilitarian mood, sparse vegetation against red rock terrain"
    ),
    "08 Games - Systems Alliance (Action RPG/3D)": (
        "sleek near-future military hardware design, dark hull surfacing accented "
        "with cool blue emissive trim, holographic user-interface glow elements "
        "floating over grounded plausible-future spacecraft geometry, restrained "
        "realistic proportions with functional greeble detailing, moody low-key "
        "lighting punctuated by blue accent glow, brushed metal and matte composite "
        "material language, dramatic three-quarter hero-shot camera angle, soft "
        "volumetric haze, grounded cinematic color grading, understated elegant "
        "surface design"
    ),
    "08 Games - USG Ishimura (Horror/3D)": (
        "industrial derelict spacecraft interior, heavy rusted machinery streaked "
        "with grime and corrosion, claustrophobic corridor composition with low "
        "ceilings and exposed conduits, dim flickering emergency lighting in "
        "sickly red and amber tones, oppressive survival-horror atmosphere, deep "
        "pooling shadows concealing detail, worn scratched metal surfaces, sparks "
        "and steam venting from damaged pipework, tense dread-laden mood, tight "
        "framing amplifying isolation, cold sterile-turned-decayed material palette"
    ),
    "08 Games - Overwatch (Hero Shooter/3D)": (
        "stylized painterly-yet-clean 3D character render, semi-realistic "
        "proportions balanced with graphic silhouette readability, saturated but "
        "tasteful color palette, soft cel-adjacent shading with smooth gradient "
        "falloff, crisp bright rim lighting separating subject from background, "
        "glossy clean material finish on hard-surface elements, confident dynamic "
        "three-quarter pose framing, punchy high-key studio lighting, polished "
        "animated-film-adjacent render quality, bold flat accent colors, energetic "
        "heroic composition, sharp graphic clarity"
    ),
    "08 Games - Celeste (Platformer/2D Sprite)": (
        "moody atmospheric pixel art with soft painterly gradient sky backdrops, "
        "high color-contrast silhouettes against a limited but expressive sprite "
        "palette, emotionally warm tone conveyed through gentle color transitions, "
        "small crisp character sprites with clean readable outlines, layered "
        "parallax mountain and cloud backdrops, gentle glow around light sources, "
        "wistful reflective mood, side-view platforming composition, dusk-and-dawn "
        "hued lighting, tender intimate scale despite pixel simplicity"
    ),
    "08 Games - Terraria (Adventure/2D Sprite)": (
        "dense detailed 2D sprite tile art, layered parallax backgrounds spanning "
        "underground caverns to open sky, saturated adventure-fantasy color "
        "palette shifting by depth and biome, painterly hand-placed pixel "
        "detailing, side-view world composition with rich environmental texture, "
        "warm inviting surface-layer lighting deepening to cool moody tones "
        "underground, whimsical exploratory mood, crisp tile-based block "
        "silhouettes, dense foliage and mineral texture variation, nostalgic "
        "sandbox-adventure rendering"
    ),
    "08 Games - Kingdom Rush (Strategy/Isometric 2D)": (
        "richly detailed 2D diorama illustration, warm painterly fantasy art "
        "style, hybrid top-down and isometric camera angle, chunky readable unit "
        "and structure silhouettes set against lush painted terrain, dense foliage "
        "and terrain texture rendered with soft painterly brushwork, warm "
        "golden-hour ambient lighting, saturated inviting color palette, whimsical "
        "storybook mood, layered depth through overlapping terrain elements, clean "
        "bold outlines on foreground objects, cozy adventurous atmosphere"
    ),
    "08 Games - Slime Rancher (Adventure/3D)": (
        "vibrant candy-bright cartoon 3D render, glossy rounded bouncy forms with "
        "soft toy-like material shading, saturated pastel-to-vivid color palette, "
        "cheerful pastoral science-fiction-farm atmosphere, smooth clean surface "
        "finish with gentle specular highlights, bouncy squash-and-stretch implied "
        "motion, bright even outdoor lighting, whimsical sunny composition, "
        "rounded friendly silhouettes free of harsh angles, playful saturated "
        "sky-and-field backdrop, wholesome inviting mood, polished family-friendly "
        "render quality"
    ),
    "08 Games - Rollercoaster Tycoon 2 (Simulation/Isometric 2D)": (
        "bright cheerful isometric 2D pre-rendered sprite art, dense colorful "
        "diorama-style scene composition, saturated primary-color palette, "
        "nostalgic late-1990s simulation-game rendering, crisp clean sprite edges "
        "with flat even lighting, tidy grid-aligned layout, cheerful sunny daytime "
        "atmosphere, charming miniature-scale detailing, warm inviting color "
        "grading, orderly readable top-down-leaning perspective, wholesome "
        "bustling-world mood, polished period-accurate render fidelity"
    ),
    "08 Games - Super Smash Bros Melee (Fighting/3D)": (
        "stylish high-energy 3D character render, slightly glossy plastic-adjacent "
        "material shading, dynamic dramatic camera angles with strong "
        "foreshortening, bold saturated color palette and punchy graphic contrast, "
        "polished early-2000s console render fidelity, crisp specular highlights "
        "on smooth surfaces, confident heroic action-pose framing, vibrant stage "
        "lighting with rim-light accents, energetic celebratory composition, clean "
        "readable silhouettes, exaggerated dynamic motion lines, bright optimistic "
        "mood"
    ),
    "08 Games - Master of Orion 2016 (4X Strategy/2D Painted)": (
        "painterly illustrative science-fiction concept art, rich detailed digital "
        "painting technique applied to character and vessel portraiture, warm "
        "dramatic directional lighting sculpting form, high production-value "
        "strategy-game illustration style, confident brushwork with soft edge "
        "blending, deep atmospheric background falloff, regal composed portrait "
        "framing, saturated warm highlights against cool shadow tones, polished "
        "finished-concept-art rendering, epic grandiose mood, refined painterly "
        "texture throughout"
    ),
    "08 Games - Stars in Shadow (4X Strategy/2D Sprite)": (
        "cozy warm painterly pixel-adjacent science-fiction illustration, soft "
        "rounded friendly silhouettes rendered with gentle painterly shading over "
        "a pixel-informed structure, inviting saturated pastel-leaning palette, "
        "small-scale intimate technological charm rather than epic grandeur, warm "
        "ambient glow lighting, tender handcrafted texture, storybook-adjacent "
        "composition, endearing rounded forms free of harsh edges, gentle "
        "soft-focus background falloff, comforting nostalgic mood, approachable "
        "friendly rendering"
    ),
    "08 Games - Einhander (Shmup/3D)": (
        "grim monochrome-leaning industrial polygon render, PS1-era low-poly "
        "rendering fidelity with visible faceted geometry and minimal texture "
        "filtering, angular gunmetal-gray mechanical surfacing, stark "
        "high-contrast side-view camera composition, cold oppressive "
        "sci-fi-military atmosphere, harsh directional lighting with crushed "
        "shadow detail, sparse desaturated palette accented by rare warning-light "
        "color, vertex-jitter-adjacent geometric imprecision, bleak claustrophobic "
        "mood, austere mechanical silhouettes"
    ),
    "08 Games - Deus Ex Human Revolution (Action RPG/3D)": (
        "distinctive black and gold color palette, chiaroscuro dramatic lighting "
        "with deep velvety shadows and warm metallic highlights, ornate "
        "augmented-technology surfacing rendered against dark environments, "
        "painterly noir-tech atmosphere, renaissance-inspired decorative motifs "
        "applied to hard-surface detailing, moody low-key exposure, rich warm rim "
        "lighting tracing gilded edges, composed dramatic portrait or "
        "three-quarter framing, restrained saturated accent color, elegant "
        "brooding mood, polished cinematic render quality"
    ),
    "08 Games - Team Fortress 2 (Action/3D)": (
        "exaggerated comic-proportioned painterly 3D render, warm painted texture "
        "work layered over stylized cartoon anatomy, bold primary-color palette "
        "split into cohesive team-color schemes, early-1900s illustration "
        "influence adapted to a modern 3D render, expressive readable silhouettes "
        "with confident graphic shapes, soft painterly rim lighting, dynamic "
        "action-pose framing, punchy high-contrast comic shading, playful "
        "energetic mood, glossy varnished material finish, warm nostalgic color "
        "grading"
    ),
    "08 Games - Daemon X Machina (Action/3D)": (
        "stark black and red mechanical surfacing accented by bright orange neon "
        "glow trim, clean white technical paneling contrasting against dark heavy "
        "plating, high-contrast industrial-futuristic hard-surface design "
        "language, dramatic hard directional lighting with crisp specular "
        "highlights, angular aggressive silhouette geometry, glowing emissive "
        "seams tracing joint lines, moody dark backdrop making neon accents pop, "
        "polished modern mecha-render fidelity, tense combative mood, sharp "
        "graphic clarity"
    ),
    "08 Games - Synthetik 2 (Action/Top-Down 3D)": (
        "gritty contemporary military-industrial robotics rendering, worn matte "
        "metal surfacing mixed with glowing tactical-tech accent lighting, "
        "top-down or three-quarter action-camera framing, desaturated tactical "
        "color palette with punchy emissive highlights, scuffed battle-worn "
        "material detailing, harsh functional lighting emphasizing mechanical "
        "form, dense modern hard-surface greeble detail, tense high-stakes combat "
        "atmosphere, crisp readable silhouettes at a slight overhead angle, cold "
        "utilitarian mood"
    ),

    # -- 09 ARTIST: named-artist references, blended two or three at a time
    # so no single body of work is being reproduced.
    "09 Artist - Tsutomu Nihei (Blame!)": (
        "Tsutomu Nihei, stark black and white ink, dense crosshatching, brutalist "
        "megastructure architecture, oppressive vertical scale, extreme perspective, "
        "claustrophobic industrial silence, heavy shadow and blown-out highlights, "
        "intricate mechanical detail, cold and inhuman geometry, manga linework, "
        "vanishing points into darkness, monochrome, isolated figures dwarfed by "
        "structure"
    ),
    "09 Artist - Neil Blevins (Pixar Concept Art)": (
        "Neil Blevins, hard-surface science fiction concept art, industrial functional "
        "machinery, meticulous surface paneling and greebling, cool desaturated "
        "metallic palette, believable engineering, dramatic volumetric lighting, dust "
        "and atmospheric scatter, 3D concept render, weathered practical surfaces, "
        "grounded plausible technology, precise detail, cinematic depth"
    ),
    "09 Artist - Maciej Kuciara (Blade Runner 2049)": (
        "Maciej Kuciara, cinematic near-future concept art, photoreal digital painting, "
        "gritty grounded realism, desaturated cool palette, dramatic overcast light, "
        "atmospheric haze and particulate, hard-surface military hardware, film-still "
        "framing, subtle lens artifacts, weathered practical detail, tense oppressive "
        "mood, high dynamic range"
    ),
    "09 Artist - Christopher Balaskas (Beneath Ceaseless Skies Covers)": (
        "Christopher Balaskas, luminous retro-futurist vista, vast open landscape with "
        "monumental architecture, glowing sky gradients, warm sunset and cool shadow "
        "contrast, clean geometric structures, soft atmospheric perspective, small "
        "figures for scale, serene optimistic science fiction, painterly digital "
        "rendering, radiant light bloom, spacious composition"
    ),
    "09 Artist - Yusuke Murata (One-Punch Man)": (
        "Yusuke Murata, dynamic manga illustration, immaculate confident linework, "
        "explosive sense of motion, exaggerated dramatic perspective, dense speed lines, "
        "powerful athletic anatomy, crisp screentone shading, high energy action pose, "
        "impact debris and shockwaves, polished and kinetic, expressive intensity, "
        "sharp graphic contrast"
    ),
    "09 Artist - John Harris (Ender's Game Covers)": (
        "John Harris, Sparth, Jessica Rossier, monumental science fiction vista, "
        "impressionistic loose brushwork, enormous sense of scale, tiny figures against "
        "colossal structures, atmospheric haze and depth, muted harmonious palette, "
        "soft edges dissolving into mist, luminous horizon, painterly abstraction, "
        "contemplative and vast, oil-painting texture"
    ),
    "09 Artist - James Gilleard (Japan by Car)": (
        "James Gilleard, flat mid-century modern illustration, clean geometric shapes, "
        "limited harmonious retro palette, subtle grain texture overlay, elegant "
        "stylized simplification, strong graphic composition, soft warm tones, crisp "
        "vector-like edges, retro-futurist optimism, decorative pattern, minimal "
        "shading, poster-like clarity"
    ),
    "09 Artist - Marek Okon (The Last of Us)": (
        "Marek Okon, vibrant high-tech digital painting, glowing neon accents against "
        "deep shadow, saturated color, polished cinematic rendering, dramatic key "
        "lighting, sleek futuristic hardware, energetic composition, crisp specular "
        "highlights, rich atmospheric depth, bold color contrast, dynamic and "
        "commanding"
    ),
    "09 Artist - Barclay Shaw (Harlan Ellison Covers)": (
        "Barclay Shaw, hyper-real 1980s airbrushed science fiction, glossy chrome and "
        "enamel surfaces, immaculate reflective finish, bold saturated color, hard "
        "specular highlights, meticulous mechanical detail, dramatic studio lighting, "
        "vintage paperback cover composition, smooth flawless gradients, retro "
        "technological optimism"
    ),
    "09 Artist - Tomer Hanuka (The Divine)": (
        "Tomer Hanuka, Asaf Hanuka, Chris Uminga, bold graphic comic illustration, "
        "confident clean ink outlines, flat vivid color fills, dramatic simplified "
        "shadow shapes, expressive stylized faces, high contrast palette, dynamic "
        "poster composition, slight watercolor bleed, pulp cover energy, striking and "
        "immediate"
    ),
    "09 Artist - Benedick Bana (Warhammer 40K Fan Art)": (
        "Benedick Bana, dark high-contrast digital painting blended with grounded "
        "realism, dramatic chiaroscuro, glowing rim light against deep black, gritty "
        "metallic textures, aggressive angular forms, monochrome palette with a single "
        "accent color, cinematic intensity, controlled painterly detail, imposing and "
        "severe"
    ),
}

# Painterly and Comic shipped before the naming scheme existed, then spent a
# while seeded as user presets ("*Painterly" / "*Comic") as a worked example
# of the "*" convention. They are now official built-ins under 01 MAIN, as
# "Digital Painting" and "Digital Comic" -- see the migration in load_config().
SEEDED_USER_PRESETS: dict[str, str] = {}


def default_style_presets() -> dict[str, str]:
    """Built-ins plus any seeded user presets — the fresh-install list."""
    return {**BUILTIN_PRESETS, **SEEDED_USER_PRESETS}

# Negative-prompt presets, which are LAYERS rather than alternatives: they are
# ticked in combination and joined, so each one should cover a single concern
# and be worth stacking with the others.
#
# MEASURED, and it changes how these are written: classifier-free guidance
# encodes the negative prompt in its OWN pass with its OWN full token budget,
# so a heavy negative costs the positive prompt nothing. Terms are left out
# for being INERT -- anatomy fixes do nothing for an empty landscape -- never
# for being expensive. (An earlier comment here claimed the opposite; it was
# wrong. See docs/findings.md.)
#
# SEVERAL LAYERS DELIBERATELY CONTRADICT EACH OTHER. "Photoreal Guard" and
# "Anti-Photo" are opposites; so are the "Quality Floor" and "Ruin Quality"
# pairs, and "Colour Discipline" and "Deep Fried". That is correct -- they are
# layers, you tick the one you want. The inverted ones exist because a
# deliberately awful image is a legitimate thing to want.
#
# The earlier "Universal Clean-up" and "Human Anatomy" layers are superseded:
# the first split into Text & Markings / Framing / Quality Floor (Photo), the
# second into the five Anatomy layers plus Faces & Eyes. Both were doing
# several jobs at once, which is exactly what stacking is meant to avoid.
#
# Source material for these was "WIP todo styles etc/negatives.txt", which is
# a word cloud rather than a design -- the same ~40 terms in eight different
# orders. Vocabulary kept, structure rebuilt. Deliberately NOT carried over:
# embedding filenames (verybadimagenegative_v1.3, ng_deepnegative_v1_75t,
# DeepNegative, fastnegative-xl) which only work with that embedding
# installed locally; Pony tag conventions (score_6, source_pony); and
# "(term:0.8)" weighting syntax, which these APIs encode as literal text.
BUILTIN_NEGATIVE_PRESETS: dict[str, str] = {
    # -- quality floors --------------------------------------------------
    "Quality Floor (Photo)": (
        "low quality, worst quality, low resolution, blurry, out of focus, "
        "motion blur, grainy, noisy, jpeg artifacts, compression artifacts, "
        "overexposed, underexposed, blown highlights, crushed blacks, "
        "poor composition, bad lighting, flat lighting, washed out, "
        "amateur snapshot, badly framed"
    ),
    "Quality Floor (Art)": (
        "amateur drawing, poorly drawn, sloppy linework, wobbly lines, "
        "unfinished, rough draft, messy sketch, bad proportions, stiff and "
        "lifeless, flat shading, muddy colors, low effort, inconsistent style, "
        "childlike scribble, low detail, careless rendering, awkward composition"
    ),

    # -- deliberately inverted: these MAKE a bad image on purpose --------
    "Ruin Quality (Photo)": (
        "professional photography, studio lighting, sharp focus, perfect "
        "exposure, high resolution, polished, retouched, well composed, "
        "award winning, tripod steady, color graded, clean, pristine"
    ),
    "Ruin Quality (Art)": (
        "professional illustration, masterpiece, highly detailed, clean "
        "linework, confident brushwork, polished rendering, expert anatomy, "
        "award winning, refined, well composed, skilled, high fidelity"
    ),
    "Deep Fried": (
        "natural colors, balanced contrast, correct white balance, smooth "
        "gradients, clean edges, even lighting, subtle tones, high fidelity, "
        "unprocessed, pristine, artifact free, accurate color"
    ),

    # -- markings and framing (were both inside "Universal Clean-up") ----
    "Text & Markings": (
        "text, letters, words, caption, subtitles, watermark, signature, "
        "artist name, username, logo, branding, copyright notice, speech "
        "bubble, label, timestamp, UI, HUD, interface elements, menu, "
        "gibberish text, garbled lettering"
    ),
    "Framing": (
        "cropped, out of frame, cut off, head out of frame, poorly framed, "
        "tiling, seams, repeating pattern, border, frame, matting, letterbox, "
        "split image, collage, multiple panels, grid layout"
    ),

    # -- anatomy, split into layers that fail independently --------------
    "Anatomy (General)": (
        "bad anatomy, deformed, disfigured, malformed, mutated, mutation, "
        "bad proportions, gross proportions, disproportionate, elongated, "
        "anatomically incorrect, distorted body, melted, fused body parts, "
        "duplicate body parts, long neck, asymmetrical body"
    ),
    "Anatomy (Hands)": (
        "bad hands, poorly drawn hands, deformed hands, mutated hands, "
        "extra fingers, too many fingers, fewer digits, missing fingers, "
        "fused fingers, webbed fingers, bent fingers, extra thumbs, "
        "malformed knuckles, claw hands, unnatural finger length"
    ),
    "Anatomy (Arms & Limbs)": (
        "extra limbs, missing limbs, extra arms, extra legs, missing arms, "
        "missing legs, disconnected limbs, floating limbs, detached limbs, "
        "malformed limbs, fused limbs, extra foot, poorly drawn feet, "
        "deformed feet, twisted limbs, bent backwards joints"
    ),
    "Anatomy (Pose)": (
        "impossible pose, broken pose, unnatural posture, twisted spine, "
        "contorted body, stiff and rigid, awkward stance, dislocated joints, "
        "floating in midair, no weight or balance, limbs clipping through "
        "body, unnatural neck angle, mannequin pose"
    ),
    "Anatomy (Skin)": (
        "skin blemishes, acne, skin spots, rashes, bruises, scars, "
        "discolored skin, blotchy skin, plastic skin, waxy skin, rubbery "
        "texture, oversmoothed skin, airbrushed to plastic, unnatural skin "
        "tone, mottled complexion, visible seams in skin"
    ),
    "Faces & Eyes": (
        "poorly drawn face, deformed face, asymmetrical face, cross-eyed, "
        "lazy eye, deformed iris, deformed pupils, extra pupils, mismatched "
        "eyes, misaligned eyes, dead eyes, empty stare, uneven eyes, "
        "distorted mouth, crooked teeth, too many teeth, malformed ears"
    ),
    "Anti-Horror": (
        "body horror, grotesque, monstrous, freakish, nightmarish, "
        "eldritch, disturbing, uncanny valley, gore, blood, wounds, "
        "exposed flesh, rotting, decaying, skeletal, hollow eye sockets, "
        "unnatural grin, too many limbs, writhing mass, unsettling"
    ),
    "Extra People": (
        "multiple people, two people, crowd, group, background people, "
        "bystanders, duplicate, clone, twin, mirrored figure, extra person, "
        "reflection of another person, second face"
    ),

    # -- opposites: pick the one matching what you asked for -------------
    "Photoreal Guard": (
        "3d render, cgi, video game screenshot, plastic skin, waxy, "
        "mannequin, doll-like, uncanny valley, oversmoothed, airbrushed, "
        "digital painting, illustration, cartoon, anime, rendered, "
        "artificial lighting, unrealistic materials"
    ),
    "Anti-Photo": (
        "photograph, photo, photorealistic, photorealism, dslr, stock photo, "
        "3d render, cgi, realistic skin texture, camera, lens flare, "
        "depth of field bokeh, film grain, hyperrealistic"
    ),

    # -- scene hygiene ---------------------------------------------------
    "Clean Background": (
        "cluttered, busy background, messy, distracting background, "
        "extra objects, random props, debris, scattered items, visual noise, "
        "crowded composition, background clutter, overlapping elements, "
        "competing focal points"
    ),
    "Colour Discipline": (
        "oversaturated, garish colors, neon oversaturation, washed out, "
        "desaturated, muddy colors, color banding, posterization, "
        "blown highlights, clipped shadows, color fringing, chromatic "
        "aberration, sepia, monochrome, grayscale, color cast, unbalanced tint"
    ),
    "Sprite / Cutout": (
        "background, scenery, landscape, environment, ground plane, floor, "
        "horizon, cast shadow, drop shadow, perspective distortion, "
        "vignette, gradient background, reflections, surrounding objects, "
        "scene context"
    ),
}

DEFAULT_CONFIG: dict = {
    # Prompts tab
    "prompt_file": "",
    "output_dir": "",
    "style_suffix": BUILTIN_PRESETS["01 Main - Digital Art"],
    # None = generate every prompt in the file. An int caps the run at the
    # first N, for style tests.
    "prompt_limit": None,
    # The one-off prompt override: generate ONE image from text typed into the
    # GUI instead of reading the prompt file. Off by default -- a program that
    # ignored the file you picked without being asked to would be a bug.
    #
    # Only the FLAG lives here. The text itself is a separate single_custom.txt
    # beside the program: it is free-form, may contain anything the user
    # pastes, and does not belong wedged into a JSON string field.
    "one_off_enabled": False,
    "style_presets": default_style_presets(),
    "last_preset": "01 Main - Digital Art",

    # Provider tab
    "provider": "cloudflare",
    "model": M.DEFAULT_MODEL,
    "ratio": M.DEFAULT_RATIO,
    "tier": M.DEFAULT_TIER,
    "negative_prompt": "",
    "negative_presets": dict(BUILTIN_NEGATIVE_PRESETS),
    # Which preset layers are currently ticked, in the order they compose.
    # Empty by default: a negative prompt is an opinion, not a default.
    "negative_layers": [],
    "guidance": "",
    "steps": "",
    "random_seed": True,
    "seed": "",

    # Style reference image. The FLAG and the PATH are stored separately and
    # deliberately: unticking the feature must not lose the file the user
    # picked, the same way the one-off override keeps its text.
    #
    # Unlike that text, the path DOES live in config.json -- a path is a
    # short, well-behaved string, where the one-off box is free-form and
    # holds whatever a user pastes into it.
    #
    # An empty path with the flag on is a legitimate state (armed, nothing
    # chosen yet) and the GUI says so rather than treating it as an error.
    "reference_enabled": False,
    "reference_image": "",
    # auto | nearest | lanczos. Auto-detection is measured to be reliable
    # (4 colours / 0.000 round-trip for pixel art vs ~97k / 0.529 for a
    # photo), so the default answers the question for the user -- but the
    # manual options stay, because detection can be wrong and the user knows
    # their own file.
    "reference_resample": R.DEFAULT_RESAMPLE,
    # off | style | strong -- a sentence appended to every prompt asking the
    # model to follow the reference. Off by default so existing batches keep
    # their prompts, filenames and identity unchanged. See core/reference.py.
    "reference_influence": R.DEFAULT_INFLUENCE,

    # Politeness / reliability
    "concurrency": DEFAULT_CONCURRENCY,
    "delay": DEFAULT_DELAY,
    "max_attempts": DEFAULT_MAX_ATTEMPTS,
    "timeout": DEFAULT_TIMEOUT,
    "overwrite": False,
    "output_format": "keep",
    "jpeg_quality": 95,
}


def app_dir() -> Path:
    """Where the program's own files live.

    Next to the exe when frozen, at the project root when run from source --
    the same rule config.json and credentials.json already follow.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    """Next to the exe when frozen, at the project root when run from source."""
    return app_dir() / "config.json"


def load_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config.json is not an object")
    except Exception:
        return _fresh()

    cfg = _fresh()
    cfg.update(data)

    # A user could delete every preset; the built-ins should always come back.
    presets = cfg.get("style_presets")
    if not isinstance(presets, dict) or not presets:
        cfg["style_presets"] = default_style_presets()

    # Upgrade from before the naming scheme: the two original presets first
    # shipped bare, then as seeded user presets "*Painterly" / "*Comic", and
    # are now official built-ins under 01 MAIN. Upgrade from ALL CAPS names
    # to Title Case at the same time -- both are pure renames, done in place
    # (rather than adding duplicates) and followed through to last_preset so
    # a returning user's selection is never left dangling.
    renamed = {
        "Painterly": "01 Main - Digital Painting",
        "*Painterly": "01 Main - Digital Painting",
        "Comic": "01 Main - Digital Comic",
        "*Comic": "01 Main - Digital Comic",
        "00 NONE - BLANK": "00 None - Blank",
        "01 MAIN - DIGITAL ART": "01 Main - Digital Art",
        "01 MAIN - 3D HIGH POLY": "01 Main - 3D High Poly",
        "01 MAIN - 3D LOW POLY": "01 Main - 3D Low Poly",
        "01 MAIN - FRAZETTA OIL PAINT": "01 Main - Frazetta Oil Paint",
        # 02 PHOTO was re-lettered A..S in 2026-09-14 so the dropdown's plain
        # sorted() holds the intended order. Professional/Candid were also
        # rewritten to work in any setting rather than implying a studio, so
        # the old ALL CAPS rows jump straight to the lettered names.
        "02 PHOTO - PROFESSIONAL": "02 Photo - A - Intentional Pro",
        "02 Photo - Professional": "02 Photo - A - Intentional Pro",
        "02 PHOTO - CANDID AMATEUR": "02 Photo - B - Candid Amateur",
        "02 Photo - Candid Amateur": "02 Photo - B - Candid Amateur",
        "02 PHOTO - RAD FISHEYE": "02 Photo - Q - Rad Fisheye",
        "02 Photo - Rad Fisheye": "02 Photo - Q - Rad Fisheye",
        "02 PHOTO - MACRO CLOSEUP": "02 Photo - R - Macro Closeup",
        "02 Photo - Macro Closeup": "02 Photo - R - Macro Closeup",
        "02 PHOTO - TILT SHIFT": "02 Photo - S - Tilt Shift",
        "02 Photo - Tilt Shift": "02 Photo - S - Tilt Shift",
        "03 STYLE - SKETCH": "03 Style - Sketch",
        "03 STYLE - DRAWING": "03 Style - Drawing",
        "03 STYLE - GRAPHITE WATERCOLOR": "03 Style - Graphite Watercolor",
        "03 STYLE - RETRO": "03 Style - Retro",
        "03 STYLE - VECTOR": "03 Style - Vector",
        "03 STYLE - POPART": "03 Style - Popart",
        "03 STYLE - PIXEL FRONT VIEW": "03 Style - Pixel Front View",
        "03 STYLE - PIXEL SIDE VIEW": "03 Style - Pixel Side View",
        "04 SPECIAL - GHOSTLY": "04 Special - Ghostly",
        "04 SPECIAL - WHITESPACE": "04 Special - Whitespace",
        "04 SPECIAL - SPLASH": "04 Special - Splash",
        "04 SPECIAL - GLITCH": "04 Special - Glitch",
        "05 ASSET - PREMIUM PRODUCT SHOT": "05 Asset - Premium Product Shot",
        "05 ASSET - STICKER": "05 Asset - Sticker",
        "05 ASSET - PIXEL FRONT VIEW SINGLE OBJECT": "05 Asset - Pixel Front View Single Object",
        "05 ASSET - PIXEL FRONT VIEW SPRITESHEET": "05 Asset - Pixel Front View Spritesheet",
        "05 ASSET - PIXEL SIDE VIEW SINGLE OBJECT": "05 Asset - Pixel Side View Single Object",
        "05 ASSET - PIXEL SIDE VIEW SPRITESHEET": "05 Asset - Pixel Side View Spritesheet",
        "06 COOL - FUTURISTIC HUMAN WORLD": "06 Cool - Futuristic Human World",
        "06 COOL - COMBAT ROBOT": "06 Cool - Combat Robot",
        "06 COOL - MEGA VEHICLE": "06 Cool - Mega Vehicle",
        "06 COOL - HOMO MUGEN": "06 Cool - Homo Mugen",
        "07 BEAUTY - PRETTY EYES": "07 Beauty - Pretty Eyes",
        "07 BEAUTY - PRETTY LIPS": "07 Beauty - Pretty Lips",
        "07 BEAUTY - PRETTY HAND": "07 Beauty - Pretty Hand",
        "07 BEAUTY - PRETTY EAR": "07 Beauty - Pretty Ear",
        "07 BEAUTY - ENTRANCING PORTRAIT": "07 Beauty - Entrancing Portrait",
        "07 BEAUTY - LATEX BEAUTY": "07 Beauty - Latex Beauty",
        "07 BEAUTY - MIRROR SELFIE ROOM": "07 Beauty - Mirror Selfie Room",
        "07 BEAUTY - MIRROR SELFIE PHONE": "07 Beauty - Mirror Selfie Phone",
        "08 GAMES - ASTRONEER": "08 Games - ASTRONEER (Action/3D)",
        "08 GAMES - PLANETARY ANNIHILATION": "08 Games - Planetary Annihilation (Strategy/3D)",
        "08 GAMES - SUPER MARIO GALAXY": "08 Games - Super Mario Galaxy (Platformer/3D)",
        "08 GAMES - XCOM 2": "08 Games - XCOM 2 (Tactics/3D)",
        "09 ARTIST - NIHEI": "09 Artist - Tsutomu Nihei (Blame!)",
        "09 ARTIST - BLEVINS": "09 Artist - Neil Blevins (Pixar Concept Art)",
        "09 ARTIST - KUCIARA": "09 Artist - Maciej Kuciara (Blade Runner 2049)",
        "09 ARTIST - BALASKAS": "09 Artist - Christopher Balaskas (Beneath Ceaseless Skies Covers)",
        "09 ARTIST - MURATA": "09 Artist - Yusuke Murata (One-Punch Man)",
        "09 ARTIST - HARRIS": "09 Artist - John Harris (Ender's Game Covers)",
        "09 ARTIST - GILLEARD": "09 Artist - James Gilleard (Japan by Car)",
        "09 ARTIST - OKON": "09 Artist - Marek Okon (The Last of Us)",
        "09 ARTIST - SHAW": "09 Artist - Barclay Shaw (Harlan Ellison Covers)",
        "09 ARTIST - HANUKA": "09 Artist - Tomer Hanuka (The Divine)",
        "09 ARTIST - BANA": "09 Artist - Benedick Bana (Warhammer 40K Fan Art)",
    }
    for old, new in renamed.items():
        if old in cfg["style_presets"] and new not in cfg["style_presets"]:
            cfg["style_presets"][new] = cfg["style_presets"].pop(old)
        if cfg.get("last_preset") == old:
            cfg["last_preset"] = new

    # Professional and Candid were REWRITTEN as well as renamed (2026-09-14):
    # both used to assume a studio or an indoor phone snap, and now describe a
    # skill level that works anywhere. The rename above carries the old body
    # across under the new name, and setdefault below would then keep it -- so
    # the superseded text is replaced here, and ONLY when it is untouched. An
    # edited copy is the user's own work and is left exactly as it is.
    rewritten = {
        "02 Photo - A - Intentional Pro": (
            "professional photograph, honest and authentic, perfect studio lighting, "
            "razor sharp focus, high resolution, rich color contrast, vibrant "
            "true-to-life colors, glossy and detailed surfaces, shallow depth of "
            "field, softly blurred background, clean matte backdrop, balanced "
            "exposure, natural highlights and shadows, polished editorial finish, "
            "mesmerising clarity, full frame camera"
        ),
        "02 Photo - B - Candid Amateur": (
            "candid amateur snapshot, phone camera photo, unposed spontaneous moment, "
            "available light, mixed indoor color temperature, slightly off-kilter "
            "framing, mild motion blur, visible sensor noise, flat unedited colors, "
            "harsh direct flash, imperfect exposure, everyday casual realism, "
            "unremarkable composition, authentic and uncurated, gentle lens softness, "
            "ordinary and unstaged"
        ),
    }
    for name, old_text in rewritten.items():
        if cfg["style_presets"].get(name) == old_text:
            cfg["style_presets"][name] = BUILTIN_PRESETS[name]

    # A config saved before the built-ins existed has none of them. Add any
    # that are missing without touching the user's own presets or their edits
    # to a built-in -- only genuinely absent names are filled in.
    for name, text in BUILTIN_PRESETS.items():
        cfg["style_presets"].setdefault(name, text)

    negatives = cfg.get("negative_presets")
    if not isinstance(negatives, dict) or not negatives:
        cfg["negative_presets"] = dict(BUILTIN_NEGATIVE_PRESETS)

    # The two original layers did several jobs each and are superseded by the
    # split ones. Drop them only if untouched -- an edited copy is the user's
    # work and is left alone (it just sorts alongside their other presets).
    superseded = {
        "Universal Clean-up": (
            "watermark, text, signature, logo, username, worst quality, low quality, "
            "low resolution, grainy, jpeg artifacts, blurry, cropped, out of frame"
        ),
        "Human Anatomy": (
            "bad anatomy, deformed, disfigured, mutated, poorly drawn face, "
            "poorly drawn hands, bad hands, extra fingers, fewer digits, "
            "fused fingers, extra limbs, missing limbs, disconnected limbs, "
            "extra arms, extra legs, cross-eyed, duplicate body parts"
        ),
    }
    for name, original in superseded.items():
        if cfg["negative_presets"].get(name) == original:
            cfg["negative_presets"].pop(name)

    for name, text in BUILTIN_NEGATIVE_PRESETS.items():
        cfg["negative_presets"].setdefault(name, text)

    # The single-select dropdown this replaced needed an empty "None" entry to
    # mean "no negative prompt". With checkboxes that is just nothing ticked,
    # so the empty preset is now a confusing no-op layer -- drop it on upgrade.
    if cfg["negative_presets"].get("None", None) == "":
        cfg["negative_presets"].pop("None")
        if not cfg["negative_presets"]:
            cfg["negative_presets"] = dict(BUILTIN_NEGATIVE_PRESETS)

    # A ticked layer whose preset has since been deleted would compose as an
    # empty string and quietly change the negative prompt, so drop it.
    layers = cfg.get("negative_layers")
    if not isinstance(layers, list):
        layers = []
    cfg["negative_layers"] = [
        n for n in layers if n in cfg["negative_presets"]
    ]
    return cfg


def save_config(data: dict) -> None:
    try:
        config_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        # Persistence is a convenience; failing to save must never take the app
        # down mid-batch.
        pass


def _fresh() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg["style_presets"] = default_style_presets()
    cfg["negative_presets"] = dict(BUILTIN_NEGATIVE_PRESETS)
    return cfg
