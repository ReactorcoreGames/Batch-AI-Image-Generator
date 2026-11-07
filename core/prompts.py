"""Prompt-file loading and filename construction."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Windows reserved device names — a file called `con.png` is not creatable.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

_UNSAFE = re.compile(r"[^a-zA-Z0-9]+")


@dataclass
class PromptLine:
    line_no: int          # 1-based line number in the source file
    original: str
    final: str            # original + style suffix


def load_prompts(path: str | Path, style_suffix: str = "") -> list[PromptLine]:
    """Read a prompt file, one prompt per line.

    MEASURED gotcha: the test files are CRLF with NO trailing newline.
    Reading in text mode with newline=None handles both, and splitlines()
    keeps the final unterminated line — a naive split on '\\n' would leave an
    invisible '\\r' on the end of every prompt, which then travels into the
    request and the filename.

    Blank lines are skipped but do not renumber anything: `line_no` stays the
    real line number in the file, so an error message points at the right line.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    suffix = (style_suffix or "").strip()

    out: list[PromptLine] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        prompt = raw.strip()
        if not prompt:
            continue
        final = f"{prompt} {suffix}".strip() if suffix else prompt
        out.append(PromptLine(line_no=i, original=prompt, final=final))
    return out


# ---------------------------------------------------------------------------
# Prompt length advice
#
# Every model silently truncates a prompt past its encoder's token limit -- no
# error, no warning, the tail simply never reaches the image. The counters this
# backs exist so the user finds out before the model does.
#
# SOFT means soft. Nothing here truncates, rejects, or blocks a run; a long
# prompt is a user's decision to make and some of them tokenize far better than
# the character estimate suggests.
# ---------------------------------------------------------------------------

# A token is roughly 4 characters of ordinary English. Keyword salad
# ("watermark, signature, low-res") tokenizes worse than prose, so a prompt can
# overflow earlier than the character count implies -- which is the direction
# that errs safely for advice.
CHARS_PER_TOKEN = 4.0


@dataclass
class LengthAdvice:
    chars: int
    soft_limit: int
    hard_limit: int
    level: str        # "ok" | "near" | "over"
    message: str

    @property
    def approx_tokens(self) -> int:
        return int(round(self.chars / CHARS_PER_TOKEN))


def length_advice(text: str, soft_limit: int, hard_limit: int,
                  what: str = "Prompt") -> LengthAdvice:
    """Grade a piece of prompt text against a model's character budget.

    Three levels, because two would either nag constantly or say nothing until
    it was already too late:

      ok    -- inside the budget, just report the count
      near  -- within the soft..hard band, a gentle heads-up
      over  -- past the hard limit, where truncation is likely
    """
    chars = len(text or "")
    if chars > hard_limit:
        level = "over"
        message = (f"{chars} characters — past the ~{hard_limit} this model "
                   f"reliably reads. The tail is likely to be ignored.")
    elif chars > soft_limit:
        level = "near"
        message = (f"{chars} characters — nearing the ~{soft_limit} this model "
                   f"handles comfortably.")
    else:
        level = "ok"
        message = f"{chars} / ~{soft_limit} characters"
    return LengthAdvice(chars=chars, soft_limit=soft_limit,
                        hard_limit=hard_limit, level=level, message=message)


# ---------------------------------------------------------------------------
# Negative prompt composition
#
# Negative presets are LAYERS, not alternatives: a quality floor, a human-
# anatomy fixer and a no-text/logo layer are orthogonal concerns a user will
# want combined. Layers are designed to overlap, so duplicate terms are the
# normal case rather than an error.
#
# This is free in a way that is worth stating: classifier-free guidance encodes
# the negative prompt in its own pass, with its own full token budget, so a
# heavy negative costs the positive prompt NOTHING. Terms are dropped here for
# being inert, never for being expensive.
# ---------------------------------------------------------------------------


def split_terms(text: str) -> list[str]:
    """Split a comma-separated negative prompt into its terms."""
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def compose_negative(layers: list[str]) -> str:
    """Join negative layers into one prompt, dropping duplicate terms.

    First occurrence wins, so the order the layers were ticked in survives --
    and since CLIP weights earlier tokens more heavily, that ordering is a
    quality lever rather than cosmetics.

    Matching is case-insensitive and ignores surrounding whitespace, but the
    term is emitted exactly as first written. Repeating a term in SD acts as
    mild emphasis, but across overlapping layers it mostly just burns budget.
    """
    seen: set[str] = set()
    out: list[str] = []
    for layer in layers:
        for term in split_terms(layer):
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
    return ", ".join(out)


def load_style_suffix(path: str | Path | None) -> str:
    """Read a style-suffix file. Joins multiple lines into one line."""
    if not path:
        return ""
    text = Path(path).read_text(encoding="utf-8-sig")
    return " ".join(part.strip() for part in text.splitlines() if part.strip())


# Filler words carry no identifying information but eat most of the filename
# budget. Prompts in a batch usually share a long boilerplate opening
# ("distant low angle background of a ..."), so dropping these keeps the words
# that actually tell one image from another.
_STOPWORDS = frozenset("""
a an the of at in on to for with and or is are be by from as into over under
this that these those it its
""".split())

# Kept short on purpose: Windows' classic MAX_PATH is 260 characters for the
# WHOLE path, and these files live inside a user-chosen output folder that may
# itself be deeply nested. A 75-character name left very little headroom.
DEFAULT_FRAGMENT_LEN = 32
DEFAULT_STEM_LEN = 16
# The style-suffix slug. Suffixes are long prose that shares vocabulary at the
# front across a preset library, so this leans on _squeeze's both-ends trick to
# keep the tail where they diverge.
DEFAULT_STYLE_LEN = 20
# 6 hex chars = 16.7M values. This is a fingerprint for telling two variants of
# one prompt apart within a folder, not a content-addressable store.
HASH_LEN = 6


def sanitize_fragment(
    prompt: str, max_len: int = DEFAULT_FRAGMENT_LEN, drop_stopwords: bool = False
) -> str:
    """Turn a prompt into a safe, readable filename fragment.

    Truncates on a word boundary so the name stays legible rather than ending
    mid-word. With `drop_stopwords`, common filler words are removed first so
    the budget is spent on distinguishing terms.

    Must stay deterministic: resume identifies an already-generated image by
    rebuilding its name, so the same input has to give the same output.
    """
    slug = _UNSAFE.sub("_", prompt).strip("_").lower()

    if drop_stopwords:
        words = [w for w in slug.split("_") if w]
        kept = [w for w in words if w not in _STOPWORDS]
        # If a prompt is nothing but stopwords, keep the original rather than
        # returning an empty fragment.
        if kept:
            slug = "_".join(kept)

    if len(slug) > max_len:
        slug = _squeeze(slug, max_len)
    if not slug:
        slug = "prompt"
    if slug in _RESERVED:
        slug = f"{slug}_"
    return slug


def _squeeze(slug: str, max_len: int) -> str:
    """Fit `slug` into `max_len`, keeping words from BOTH ends.

    Plain truncation keeps only the opening, which is exactly the part a batch
    of prompts tends to share: "distant low angle background of a field at day"
    and "...of a forest at dawn" differ only at the tail. Taking words from the
    front and the back keeps the subject and the variation, which is what makes
    one filename tell itself apart from the next at a glance.
    """
    words = [w for w in slug.split("_") if w]
    if not words:
        return ""

    head: list[str] = []
    tail: list[str] = []
    used = 0
    take_front = True
    front, back = 0, len(words) - 1

    while front <= back:
        word = words[front] if take_front else words[back]
        # +1 for the joining underscore, once there is something to join to.
        cost = len(word) + (1 if (head or tail) else 0)
        if used + cost > max_len:
            break
        if take_front:
            head.append(word)
            front += 1
        else:
            tail.insert(0, word)
            back -= 1
        used += cost
        take_front = not take_front

    out = "_".join(head + tail)
    if not out:
        # A single word longer than the whole budget: hard-cut it.
        out = words[0][:max_len]
    return out.strip("_")


def distinguishing_words(prompt: str, corpus: Sequence[str]) -> str:
    """Drop words this prompt SHARES with the rest of the batch.

    MEASURED 2026-09-13 against the shipped test_prompts.txt, whose first four
    lines differ in exactly the words that matter (field/forest/desert, day/
    dawn/dusk, cloudy/rainy/clear). `_squeeze` keeps words from both ends, but
    a batch's boilerplate sits at BOTH ends -- "Distant low angle background of
    a ..." and "... weather." -- while the variation sits in the middle. So all
    four named themselves `distant_low_angle_..._weather`, and at a 20-char
    budget all four collapsed to the IDENTICAL `distant_low_weather`. The
    subject never appeared at any budget.

    Position is the wrong signal; repetition is the right one. Boilerplate is
    boilerplate precisely because it repeats, and the engine has already loaded
    every line before it names anything, so this can be measured rather than
    guessed. Keeping only words appearing in at most half the lines turns those
    same four into `field_day_cloudy` / `forest_dawn_rainy` / `desert_dusk_clear`
    / `wasteland_night_thunderstorm` -- distinguishable, and shorter.

    Returns the prompt unchanged when there is no corpus to compare against (a
    one-off, or a single-line file), where the stopword pass is all there is.
    """
    words = [w for w in _UNSAFE.sub(" ", prompt).lower().split() if w]
    if len(corpus) < 2 or not words:
        return prompt

    seen = [
        {w for w in _UNSAFE.sub(" ", other).lower().split() if w}
        for other in corpus
    ]
    # "At most half" rather than "not in every line": with 4 lines sharing a
    # preamble, a word in 3 of them is still boilerplate. Ties round up so a
    # 2-line batch keeps anything not in both.
    cutoff = max(1, len(seen) // 2)
    kept = [w for w in words if sum(1 for s in seen if w in s) <= cutoff]

    # Every word is shared (a batch of near-identical lines): keep the original
    # rather than returning nothing, and let the hash do the distinguishing.
    return " ".join(kept) if kept else prompt


def _hash_tag(parts: Sequence[object], length: int = HASH_LEN) -> str:
    """A short DERIVED fingerprint of everything that affects the image.

    Derived, never random. A random tag would make build_filename()
    unrebuildable, and `existing_output()` rebuilds the name to find an image
    already on disk -- so random would break crash-resume and overwrite
    protection for every batch, and silently re-bill an entire paid batch on
    any rerun because nothing would ever be recognised.

    Collisions are the FEATURE: two runs colliding means "this is the same
    image", which is exactly what resume is for.
    """
    key = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()[:length]


def image_hash_parts(
    final_prompt: str,
    model: str,
    width: int,
    height: int,
    negative_prompt: str | None = None,
    guidance: float | None = None,
    steps: int | None = None,
    prompt_expansion: str | None = None,
    content_filter: str | None = None,
    reference_hash: str | None = None,
) -> list[object]:
    """The image-affecting settings, in a fixed order, for `_hash_tag`.

    `final_prompt` already contains the style suffix, which is what makes a
    changed style produce a changed filename -- the whole point of the tag.

    The SEED is deliberately absent. Including it would mean a random-seed
    rerun always writes a new file and resume could never skip anything;
    excluding it keeps resume meaningful and leaves "roll it again" to the
    explicit Regenerate action.

    `reference_hash` is the style reference image's CONTENT hash -- of the
    prepared bytes actually sent, never of the path. A path would let a
    different sprite swapped in under the same filename reattach to the
    finished batch, find the old images on disk and generate nothing: the
    identical failure shape as the style-suffix bug already fixed once here.

    It is appended at the END, and OMITTED ENTIRELY when no reference is in
    use -- not appended as None. That distinction is the whole of the
    backward compatibility, and it was verified rather than assumed: the
    parts are joined with a separator, so a trailing None appends an empty
    FIELD and changes the digest. Appending it unconditionally would have
    renamed every image in every batch made before this feature existed, so
    each one would have looked unfinished, resumed, and regenerated -- an
    entire re-bill on a paid model, from a filename change nobody asked for.
    """
    parts: list[object] = [
        final_prompt, model, width, height, negative_prompt, guidance,
        steps, prompt_expansion, content_filter,
    ]
    if reference_hash is not None:
        parts.append(reference_hash)
    return parts


def build_filename(
    source_file: str | Path,
    line_no: int,
    prompt: str,
    ext: str = ".png",
    max_fragment: int = DEFAULT_FRAGMENT_LEN,
    style_suffix: str = "",
    corpus: Sequence[str] | None = None,
    hash_parts: Sequence[object] | None = None,
) -> str:
    """`txtfile-NNN-key_words--style_words-hash.ext`

    Deterministic matters: it is what lets resume recognise an image that is
    already on disk without consulting the database.

    Compact matters too. Windows still enforces a 260-character limit on the
    full path for many applications (Explorer's own copy/rename dialogs among
    them), and these files live in a user-chosen folder that may itself be
    deeply nested.

    The style suffix appears as a SLUG of the real text rather than the preset's
    name, because a preset can be edited without being re-saved -- a name would
    then assert a style the image does not have, while a slug of what was
    actually sent cannot lie. It is divided from the prompt by a DOUBLE dash:
    single dashes everywhere else make the two read as one continuous phrase,
    and `--` is the only divider that survives slugging.
    """
    stem = sanitize_fragment(Path(source_file).stem, max_len=DEFAULT_STEM_LEN)

    body = distinguishing_words(prompt, corpus or ())
    frag = sanitize_fragment(body, max_len=max_fragment, drop_stopwords=True)
    if not ext.startswith("."):
        ext = "." + ext

    name = f"{stem}-{line_no:03d}-{frag}"
    if (style_suffix or "").strip():
        style = sanitize_fragment(
            style_suffix, max_len=DEFAULT_STYLE_LEN, drop_stopwords=True
        )
        name = f"{name}--{style}"
    if hash_parts is not None:
        name = f"{name}-{_hash_tag(hash_parts)}"
    return f"{name}{ext}"


def existing_output(
    output_dir: str | Path,
    source_file: str | Path,
    line_no: int,
    prompt: str,
    style_suffix: str = "",
    corpus: Sequence[str] | None = None,
    hash_parts: Sequence[object] | None = None,
) -> Path | None:
    """Find an already-generated image for this job, whatever its extension.

    The extension is not knowable in advance — it comes from sniffing the
    response — so resume has to glob rather than assume.

    Every naming argument must match what `_write_output` passed, or resume
    looks for a name nothing was ever written under: it would then regenerate
    an image that is already on disk, at full price on a paid model.
    """
    d = Path(output_dir)
    if not d.is_dir():
        return None
    prefix = build_filename(
        source_file, line_no, prompt, ext=".x", style_suffix=style_suffix,
        corpus=corpus, hash_parts=hash_parts,
    )[:-2]
    for p in sorted(d.glob(f"{prefix}.*")):
        if p.suffix.lower() != ".json" and p.is_file() and p.stat().st_size > 0:
            return p
    return None


def unique_path(path: Path) -> Path:
    """Add a numeric suffix rather than clobbering an existing file."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"could not find a free filename near {path}")


# ---------------------------------------------------------------------------
# The one-off prompt override
#
# Authoring a .txt is a chore when the question is "does this idea work at
# all?" -- one image, then decide. The override answers that without a file.
#
# It is materialised as a REAL single-line .txt rather than being threaded
# through the engine as a special case, and that is the whole design. The
# prompt file is not merely an input: its path keys `find_batch()` for resume,
# its stem seeds `build_filename()`, and it is recorded in every sidecar as
# `source_file`. A sentinel path would make two different one-off prompts
# collide on one batch row and one filename. Writing a file means resume,
# naming, batch identity and metadata all keep working by construction, with
# no engine change at all.
# ---------------------------------------------------------------------------

# Where the persisted override text lives. Beside the program, like config.json
# -- NOT inside it: this is free-form user text, and a JSON string field is a
# poor home for something the user may paste anything into.
ONE_OFF_FILENAME = "single_custom.txt"

# Each RUN gets its own file inside this folder, named from the prompt, so two
# different one-offs are two different batches rather than one batch whose job
# row disagrees with the image beside it.
ONE_OFF_DIRNAME = ".oneoff"


def one_off_store_path(base_dir: str | Path) -> Path:
    """The persisted override text file, beside the program."""
    return Path(base_dir) / ONE_OFF_FILENAME


def read_one_off(base_dir: str | Path) -> str:
    """Load the saved override text. Missing or unreadable reads as empty."""
    try:
        return one_off_store_path(base_dir).read_text(
            encoding="utf-8-sig").strip()
    except Exception:
        # Absent on first run, and a failure here must never block the GUI
        # from building -- an empty box is the correct fallback either way.
        return ""


def write_one_off(base_dir: str | Path, text: str) -> None:
    """Persist the override text. Best-effort, like save_config()."""
    try:
        one_off_store_path(base_dir).write_text(
            (text or "").strip() + "\n", encoding="utf-8")
    except Exception:
        pass


def materialize_one_off(prompt: str, output_dir: str | Path) -> Path:
    """Write `prompt` to a single-line .txt and return its path.

    Lives in a dot-folder inside the output directory rather than in the
    system temp: the engine's database sits beside the images for the same
    reason, and a resume of this exact one-off has to find the same path it
    ran under. Temp files get swept.

    The name comes from the prompt itself, so the generated image is called
    `misty_forest-001-....png` rather than `oneoff-001-...`. Same prompt means
    same path means the same batch -- which is what makes re-running a one-off
    resume rather than duplicate.
    """
    text = (prompt or "").strip()
    if not text:
        raise ValueError("the one-off prompt is empty")
    # Newlines would make this several prompts; the override is deliberately
    # ONE image, so they collapse into one line.
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())

    d = Path(output_dir) / ONE_OFF_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    stem = sanitize_fragment(text, max_len=DEFAULT_STEM_LEN, drop_stopwords=True)
    path = d / f"{stem}.txt"

    # A different prompt that sanitizes to the same stem must not silently
    # reuse the other one's batch, so disambiguate on CONTENT, not on
    # existence -- an identical prompt keeps its path and resumes.
    if path.exists():
        try:
            if path.read_text(encoding="utf-8-sig").strip() != text:
                path = unique_path(path)
        except Exception:
            path = unique_path(path)

    path.write_text(text + "\n", encoding="utf-8")
    return path
