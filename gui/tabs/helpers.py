"""Helpers tab — small conveniences that save a trip out of the program.

Currently one thing: the LLM prompt recipes. These are prompts for a *chat
assistant*, not for the image generator — you paste one into Claude or ChatGPT,
and what comes back is what you feed this program. The tab exists because
copying a fenced block out of a rendered markdown file by hand is fiddly and
easy to get wrong (clip the fence, miss the last line); a button cannot.

Everything shown here is parsed out of `recipes.md` at load time -- see
`core/recipes.py` for why the document is the source rather than a copy in
Python. The Reload button is what makes that claim true in practice: edit the
file in Notepad, hit Reload, see the change without restarting.

Deliberately NOT here: any in-program AI. Running these prompts through
Workers AI was considered and cut -- they are judgement tasks ("no subject
matter", "distil the visual elements") that small instruct models fail quietly,
and it would spend the image quota to do it badly.

Links sit ABOVE the recipes, matching the document, because that is the order
of use: open the site first so it loads while you fetch the prompt.
"""

from __future__ import annotations

import os
import webbrowser

import ttkbootstrap as ttk
from tkinter import ttk as _tk_ttk

from core import recipes as R
from gui.scroll import autowrap, make_scrollable
from gui.theme import FONT_BODY, FONT_SMALL, FONT_TINY, PALETTE
from gui.tooltip import tip

# What each block puts on the clipboard and what to do with the answer.
#
# These are the ONE thing not parsed from the document: the prose around each
# block is explanatory paragraphs, not caption-shaped. Keyed by recipe name,
# with a blank fallback -- a recipe added to recipes.md still gets a working
# button, just without a caption. So the drift risk here is cosmetic; the
# prompt text itself, which is the part that matters, has no second copy.
CAPTIONS: dict[str, tuple[str, str]] = {
    "Style preset": (
        "Asks for a reusable style block — look only, no subject matter.",
        "Paste your description of the look where it says "
        "DESCRIBE_THE_LOOK_YOU_WANT.\n\nWhat comes back goes in the style "
        "suffix box on the Prompts tab, where it is appended to every prompt "
        "in the batch.",
    ),
    "Vignette": (
        "Turns a piece of writing into one prompt describing the scene.",
        "Paste your text where it says YOUR_TEXT.\n\nWhat comes back is a "
        "single prompt — one line for your prompt file, or paste it straight "
        "into the single custom prompt box on the Prompts tab.",
    ),
    "Visual metaphor": (
        "Like Vignette, but depicts what the text MEANS rather than what "
        "happens in it.",
        "Paste your text where it says YOUR_TEXT.\n\nUse this when the "
        "literal scene is dull or abstract — a chapter about grief, a blog "
        "post about latency — and you want an image that carries the idea.",
    ),
    "Mood board": (
        "Asks for 8 varied prompts from one piece of text — a whole batch.",
        "Paste your text where it says YOUR_TEXT.\n\nThe reply is already in "
        "the right shape: one prompt per line, no numbering. Save it as a "
        ".txt and point the Prompts tab at it.",
    ),
    "Condense a prompt": (
        "Squeezes flowing prose down to fit Stable Diffusion's ~300 "
        "characters.",
        "Paste your long prompt where it says YOUR_PROMPT.\n\nOnly needed on "
        "the three SD models, which are never shown more than ~300 "
        "characters and drop the rest silently. FLUX.2 klein reads about "
        "2000, so a long prompt pays off there instead of being wasted.",
    ),
}


class HelpersTab:
    def __init__(self, notebook, app):
        self.app = app
        self.data = R.load()
        self._build(notebook)

    # ------------------------------------------------------------------ #

    def _build(self, notebook) -> None:
        tab = make_scrollable(notebook, "  Helpers  ")
        tab.columnconfigure(0, weight=1)
        self._tab = tab

        self._build_header(tab, row=0)

        # The parsed content lives in its own frame so Reload can destroy and
        # rebuild just this part, leaving the header (and its Reload button)
        # alone.
        self.body = ttk.Frame(tab)
        self.body.grid(row=1, column=0, sticky="ew")
        self.body.columnconfigure(0, weight=1)

        self._build_body()

    def _build_header(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="LLM prompt recipes", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 5))
        f.columnconfigure(0, weight=1)

        intro = ttk.Label(
            f,
            text="Prompts to paste into a chat assistant — Claude, ChatGPT or "
                 "similar — to help you write prompts for this program. Copy "
                 "one, paste it, replace the placeholder, and bring the answer "
                 "back here.",
            style="secondary.TLabel", justify="left", wraplength=900)
        intro.grid(row=0, column=0, sticky="w")
        autowrap(intro, f)

        # State the consequence: this is a file you can edit, and editing it
        # changes what you see here. A user who opens recipes.md in Notepad --
        # deliberately or by accident -- should already know that.
        self.source_label = ttk.Label(
            f, text="", style="secondary.TLabel", font=FONT_SMALL,
            justify="left", wraplength=900)
        self.source_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
        autowrap(self.source_label, f)

        btns = ttk.Frame(f, style="Surface.TFrame")
        btns.grid(row=2, column=0, sticky="w", pady=(8, 0))

        reload_btn = ttk.Button(btns, text="Reload", width=12,
                                style="secondary.TButton",
                                command=self.reload)
        reload_btn.grid(row=0, column=0, sticky="w")
        tip(reload_btn, text="Re-read recipes.md from disk.\n\nUse this after "
                             "editing the file, to see your changes without "
                             "restarting the program.")

        open_btn = ttk.Button(btns, text="Open recipes.md", width=18,
                              style="secondary.TButton",
                              command=self._open_doc)
        open_btn.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tip(open_btn, text="Open recipes.md in your text editor.\n\nIt holds "
                           "these prompts plus extra advice that does not "
                           "appear on this tab.")
        self._open_btn = open_btn

    # -- the parsed part, rebuilt on reload ------------------------------

    def _build_body(self) -> None:
        self._refresh_source_label()

        if not self.data.found or self.data.empty:
            self._build_problem()
            return

        row = 0
        if self.data.links:
            self._build_links(self.body, row=row)
            row += 1
        if self.data.recipes:
            self._build_recipes(self.body, row=row)

    def _build_links(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Open an assistant", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)

        hint = ttk.Label(
            f, text="Any of these will do. Open one first so it is ready by "
                    "the time you have copied a prompt.",
            style="secondary.TLabel", font=FONT_SMALL, justify="left",
            wraplength=900)
        hint.grid(row=0, column=0, sticky="w", pady=(0, 6))
        autowrap(hint, f)

        # Surface.TFrame, not a bare Frame: the default TFrame is bg_base and
        # would paint a dark rectangle behind each link inside this LabelFrame.
        strip = ttk.Frame(f, style="Surface.TFrame")
        strip.grid(row=1, column=0, sticky="w")

        # Small text links, not buttons: these are other people's products and
        # a footnote is the honest weight for them. Laid out in a row so the
        # whole set costs one line.
        for col, link in enumerate(self.data.links):
            lab = ttk.Label(strip, text=link.name, font=FONT_BODY,
                            cursor="hand2")
            lab.configure(foreground=PALETTE["accent_soft"])
            lab.grid(row=0, column=col, sticky="w",
                     padx=(0, 18) if col < len(self.data.links) - 1 else 0)
            lab.bind("<Button-1>",
                     lambda e, u=link.url: webbrowser.open(u))
            tip(lab, text=f"Open {link.url} in your browser.")

    def _build_recipes(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Copy a prompt", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(5, 10))
        f.columnconfigure(1, weight=1)

        for i, recipe in enumerate(self.data.recipes):
            caption, tooltip = CAPTIONS.get(recipe.name, ("", ""))

            btn = ttk.Button(
                f, text=f"Copy: {recipe.name}", width=26,
                style="secondary.TButton",
                command=lambda r=recipe: self._copy(r))
            btn.grid(row=i, column=0, sticky="w", pady=4)

            chars = len(recipe.text)
            lines = recipe.text.count("\n") + 1
            detail = (f"Puts {chars} characters ({lines} lines) on the "
                      f"clipboard.")
            tip(btn, text=(f"{tooltip}\n\n{detail}" if tooltip else detail))

            if caption:
                lab = ttk.Label(f, text=caption, style="secondary.TLabel",
                                font=FONT_SMALL, justify="left",
                                wraplength=700)
                lab.grid(row=i, column=1, sticky="w", padx=(12, 0), pady=4)

        self.copy_status = ttk.Label(f, text="", style="success.TLabel",
                                     font=FONT_SMALL)
        self.copy_status.grid(row=len(self.data.recipes), column=0,
                              columnspan=2, sticky="w", pady=(8, 0))

    def _build_problem(self) -> None:
        """Say which of the two failures happened. They have opposite fixes."""
        f = _tk_ttk.LabelFrame(self.body, text="Nothing to show", padding=10)
        f.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(0, weight=1)

        if not self.data.found:
            text = (f"{R.DOC_NAME} was not found beside the program, so there "
                    f"is nothing to show here. It ships with the program — if "
                    f"it has been moved or deleted, put it back next to the "
                    f"exe and press Reload.")
        else:
            text = (f"{R.DOC_NAME} was found and read, but no links or "
                    f"prompts could be parsed out of it. The program looks "
                    f"for a <links> block and <recipe name=\"...\"> tags "
                    f"around the fenced prompt blocks; if those have been "
                    f"edited away, restore them and press Reload. The file "
                    f"itself is otherwise unharmed.")

        lab = ttk.Label(f, text=text, style="warning.TLabel", justify="left",
                        wraplength=900)
        lab.grid(row=0, column=0, sticky="w")
        autowrap(lab, f)

    # -- actions ---------------------------------------------------------

    def _refresh_source_label(self) -> None:
        if not self.data.found:
            self.source_label.configure(
                text=f"Source: {R.DOC_NAME} — not found.",
                style="warning.TLabel")
            self._open_btn.configure(state="disabled")
            return

        self._open_btn.configure(state="normal")
        n_r = len(self.data.recipes)
        n_l = len(self.data.links)

        # Found but nothing parsed: let the panel below carry the explanation
        # rather than reporting "(0 links, 0 prompts)" as though that were a
        # normal reading.
        if self.data.empty:
            self.source_label.configure(
                text=f"Source: {R.DOC_NAME} — found, but nothing could be "
                     f"read out of it.",
                style="warning.TLabel")
            return

        self.source_label.configure(
            text=(f"These come from {R.DOC_NAME} beside the program "
                  f"({n_l} link{'s' if n_l != 1 else ''}, "
                  f"{n_r} prompt{'s' if n_r != 1 else ''}). Edit that file "
                  f"and they change here — press Reload to pick up your "
                  f"changes."),
            style="secondary.TLabel")

    def reload(self) -> None:
        self.data = R.load()
        for child in self.body.winfo_children():
            child.destroy()
        self._build_body()
        # A dropdown added to this tab later must not become wheel-scrollable
        # by having skipped the central pass, which ran before this rebuild.
        self.app._block_wheel_on_value_widgets(self.body)

    def _copy(self, recipe: R.Recipe) -> None:
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(recipe.text)
        # Tk's clipboard is owned by the app while it runs; update() makes the
        # selection available to other programs immediately rather than at the
        # next idle moment, which matters when the user alt-tabs at once.
        self.app.root.update()
        self.copy_status.configure(
            text=f"Copied “{recipe.name}” — paste it into your assistant.")
        self.app.log(f"Copied recipe to clipboard: {recipe.name}")

    def _open_doc(self) -> None:
        if self.data.path is None:
            return
        try:
            os.startfile(str(self.data.path))
        except Exception as exc:
            self.app.log(f"Could not open {R.DOC_NAME}: {exc}")
