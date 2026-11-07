"""Parser for `recipes.md` — the source of the Helpers tab's contents.

`recipes.md` ships beside the exe and is read at runtime, so the doc is the
single source for both the rendered document and the GUI. Editing the file is
how you change the tab; there is no second copy of the prompt text in Python.
That mirrors `core/models.py` being the only place a price is written.

The consequence is that the file's FORMAT is load-bearing. Two markers carry
it, and both were chosen so the document still reads and renders normally:

  * `<links> ... </links>` wraps the LLM site list, one `Name - URL` per line.
  * `<recipe name="...">` wraps a fenced block that becomes a copy button.

Markers rather than shape-matching (any bullet with a URL, the heading nearest
a fence) because shape-matching quietly captures prose added later: the
"Recovering from a bad batch" section is already a bullet list, and a link
added there would have turned up in the GUI for no visible reason. A marker
matches intent, so unrelated edits to the document cannot trip it.

The fences stay inside the `<recipe>` tag rather than being replaced by it:
they are what makes the block render as a copyable code box for someone
reading the document itself, which is still its primary job.

Nothing here raises on malformed input. A user editing recipes.md in Notepad
can break it, and a broken document must degrade to an empty tab that says so
-- never to a program that will not start.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

DOC_NAME = "recipes.md"

# Accept the spaced hyphen and both dashes. The document is written with one of
# them, but a user hand-editing it will type whichever their keyboard offers,
# and an em dash is famously hard to type deliberately. Splitting on the LAST
# separator keeps names containing a dash intact -- a URL has no spaces, so the
# final " - " is always the one before it.
_LINK_SPLIT = re.compile(r"\s+[-–—]\s+")

_LINKS_BLOCK = re.compile(
    r"<links>(.*?)</links>", re.DOTALL | re.IGNORECASE)

# The fence may be ``` or ```` and may carry a language tag; the name attribute
# may use single or double quotes. Being lenient here costs nothing and saves a
# user from a silently empty tab after a reasonable-looking edit.
_RECIPE_BLOCK = re.compile(
    r"""<recipe\s+name\s*=\s*(?P<q>["'])(?P<name>.*?)(?P=q)\s*>"""
    r"""\s*(?P<fence>`{3,})[^\n]*\n"""
    r"""(?P<body>.*?)"""
    r"""\n(?P=fence)\s*"""
    r"""</recipe>""",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class Link:
    """One LLM site from the `<links>` block."""
    name: str
    url: str


@dataclass(frozen=True)
class Recipe:
    """One copyable prompt block."""
    name: str
    text: str


@dataclass(frozen=True)
class Recipes:
    """Everything parsed out of recipes.md, plus how it went.

    `path` is None when the file was not found at all. That is a different
    state from "found but nothing parsed" -- a user who has mangled the fences
    needs to be told the file was read and did not parse, not that it is
    missing, because those have opposite fixes.
    """
    links: tuple[Link, ...]
    recipes: tuple[Recipe, ...]
    path: Path | None

    @property
    def found(self) -> bool:
        return self.path is not None

    @property
    def empty(self) -> bool:
        return not self.links and not self.recipes


def doc_candidates() -> list[Path]:
    """Every place recipes.md might live, best first.

    Same ladder the Help button walks for guide.md: beside the exe when
    frozen, at the project root when run from source.
    """
    candidates = [
        Path(DOC_NAME),
        Path(__file__).resolve().parent.parent / DOC_NAME,
        Path(sys.executable).parent / DOC_NAME,
        Path.cwd() / DOC_NAME,
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / DOC_NAME)
    return candidates


def find_doc() -> Path | None:
    for path in doc_candidates():
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def parse_links(text: str) -> tuple[Link, ...]:
    match = _LINKS_BLOCK.search(text)
    if not match:
        return ()

    out: list[Link] = []
    for raw in match.group(1).splitlines():
        line = raw.strip().lstrip("-*").strip()
        if not line:
            continue
        # Split on the LAST separator: everything before it is the name, so a
        # name containing a dash survives intact.
        parts = _LINK_SPLIT.split(line)
        if len(parts) < 2:
            continue
        url = parts[-1].strip()
        name = line[:line.rfind(url)].strip().rstrip("-–—").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            continue
        out.append(Link(name=name, url=url))
    return tuple(out)


def parse_recipes(text: str) -> tuple[Recipe, ...]:
    out: list[Recipe] = []
    for match in _RECIPE_BLOCK.finditer(text):
        name = match.group("name").strip()
        body = match.group("body").strip("\n")
        if not name or not body.strip():
            continue
        out.append(Recipe(name=name, text=body))
    return tuple(out)


def parse(text: str, path: Path | None = None) -> Recipes:
    return Recipes(links=parse_links(text),
                   recipes=parse_recipes(text),
                   path=path)


def load() -> Recipes:
    """Read and parse recipes.md, degrading to empty rather than raising."""
    path = find_doc()
    if path is None:
        return Recipes(links=(), recipes=(), path=None)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Recipes(links=(), recipes=(), path=path)
    return parse(text, path)
