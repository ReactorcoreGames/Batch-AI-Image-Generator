"""A scrollable tab body.

The Provider tab has more controls than fit at the minimum window height, and
a tab whose bottom section is simply unreachable is a bug, not a compromise.
This wraps the tab content in a canvas that scrolls when it needs to and stays
out of the way when it doesn't.
"""

from __future__ import annotations

import tkinter as tk

import ttkbootstrap as ttk

from gui.theme import PALETTE


def make_scrollable(notebook, label: str) -> ttk.Frame:
    """Add a scrolling tab to `notebook` and return the frame to build into."""
    outer = ttk.Frame(notebook)
    notebook.add(outer, text=label)
    outer.rowconfigure(0, weight=1)
    outer.columnconfigure(0, weight=1)

    canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0,
                       background=PALETTE["bg_base"])
    canvas.grid(row=0, column=0, sticky="nsew")

    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)

    inner = ttk.Frame(canvas, style="ScrollInner.TFrame")
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.columnconfigure(0, weight=1)

    def _on_inner_configure(_evt=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        # Only show the scrollbar when the content actually overflows —
        # a permanently visible dead scrollbar looks broken.
        needed = inner.winfo_reqheight() > canvas.winfo_height()
        if needed and not scrollbar.winfo_ismapped():
            scrollbar.grid(row=0, column=1, sticky="ns")
        elif not needed and scrollbar.winfo_ismapped():
            scrollbar.grid_remove()

    def _on_canvas_configure(evt) -> None:
        canvas.itemconfig(inner_id, width=evt.width)
        _on_inner_configure()

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    # Bind the wheel to this canvas only, while the pointer is over it.
    # bind_all would hijack scrolling for every widget in the app, including
    # the log and preview Text widgets on other tabs.
    def _wheel(evt):
        if inner.winfo_reqheight() > canvas.winfo_height():
            canvas.yview_scroll(int(-evt.delta / 120), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    return inner


def block_wheel(widget) -> None:
    """Stop the mouse wheel from changing a Combobox/Spinbox value.

    Tk lets the wheel cycle these controls whenever the pointer is over them.
    Inside a scrolling tab that is actively harmful: scrolling past a dropdown
    silently changes a setting, and the page jumps as the widget swallows the
    event instead of passing it on. Values are picked by clicking; the wheel
    should only ever scroll the page.
    """
    def _swallow(event):
        # "break" stops Tk's own handler from changing the value. The tab's
        # canvas keeps its own bind_all wheel handler, so the page still
        # scrolls normally.
        return "break"

    widget.bind("<MouseWheel>", _swallow)
    widget.bind("<Button-4>", _swallow)      # X11 wheel up
    widget.bind("<Button-5>", _swallow)      # X11 wheel down


def reserve_lines(label, lines: int, collapse_when_empty: bool = True,
                  sticky_height: bool = True) -> None:
    """Stabilise a label's height without permanently reserving dead space.

    These status and warning labels appear, change length and vanish. Left to
    size themselves, every change resizes their frame and the whole section
    visibly jumps -- which is why a fixed reservation was used first. But a
    label that is empty most of the time then holds `lines` rows of blank space
    forever, and several of them together push real controls off the screen.

    So the reservation is a HIGH-WATER MARK instead: the row grows to fit
    whatever text is set and never shrinks back while text is present, so
    swapping one message for a shorter one still cannot make the section jump.
    When the label goes empty the row collapses to nothing, because there is
    then no text whose height needs protecting.

    `lines` remains the ceiling: the row is never reserved taller than that,
    which keeps a wildly long message from stretching the section.
    Pass collapse_when_empty=False for the rare label that should always hold
    its space.

    Pass sticky_height=False when the text is driven by an explicit user
    CHOICE rather than by a background event. The high-water mark exists to
    stop *unprompted* changes from making a section jump; when the user has
    just picked a different model, the panel resizing is the expected
    response, and holding the tallest model's height forever leaves visible
    dead space under every shorter one.
    """
    try:
        import tkinter.font as tkfont

        font = tkfont.Font(font=label.cget("font"))
        line_h = font.metrics("linespace")
    except Exception:
        line_h = 18

    label.configure(anchor="nw")
    label.grid_configure(sticky="new")
    parent = label.master
    info = label.grid_info()
    if not info:
        return
    row = int(info["row"])
    state = {"peak": 0}

    def _apply() -> None:
        text = label.cget("text")
        if not text and collapse_when_empty:
            # Nothing to protect: give the space back rather than holding it.
            state["peak"] = 0
            parent.grid_rowconfigure(row, minsize=0)
            return
        needed = label.winfo_reqheight()
        # Never taller than the declared ceiling.
        capped = min(needed, line_h * lines + 4)
        if not sticky_height:
            # Track the text exactly, in both directions. For a label driven by
            # an explicit user CHOICE -- picking a model, say -- the high-water
            # mark below is wrong: a three-line note for one model left two
            # blank lines behind when the user selected a one-line model, and
            # the gap never closed for the rest of the session. Resizing on a
            # deliberate selection reads as the panel responding, not jumping.
            state["peak"] = capped
            parent.grid_rowconfigure(row, minsize=capped)
            return
        # Never shorter than the tallest text this label has shown while
        # occupied -- that is what stops a shorter replacement message from
        # making the section jump. Right for status text that changes on its
        # own (a batch result, a credential check); wrong for user selections.
        if capped > state["peak"]:
            state["peak"] = capped
            parent.grid_rowconfigure(row, minsize=capped)

    # <Configure> fires after Tk has laid the new text out, so winfo_reqheight
    # is the real wrapped height by then. But it does NOT fire when the text is
    # merely cleared, which left an emptied label holding its old height
    # forever -- exactly the dead space this is meant to avoid. So the label's
    # own `configure` is wrapped as well: that catches every text change, and
    # the recheck is deferred to idle so Tk has re-laid the label out first.
    label.bind("<Configure>", lambda _e: _apply(), add="+")

    original_configure = label.configure

    def _configure(*args, **kwargs):
        result = original_configure(*args, **kwargs)
        if args or "text" in kwargs:
            label.after_idle(_apply)
        return result

    label.configure = _configure
    label.config = _configure
    _apply()


def autowrap(label, parent, padding: int = 40) -> None:
    """Keep a wrapping Label's `wraplength` matched to its container's width.

    A hardcoded wraplength clips as soon as the window is narrower than the
    value it was written for. Binding it to the real width means the text
    reflows on resize instead.
    """
    def _resize(evt) -> None:
        width = max(evt.width - padding, 120)
        if label.cget("wraplength") != width:
            label.configure(wraplength=width)

    parent.bind("<Configure>", _resize, add="+")
