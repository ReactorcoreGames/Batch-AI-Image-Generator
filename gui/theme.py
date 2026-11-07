"""Custom ttkbootstrap theme — medium-shade teal base with cyan accents.

Built with the injection pattern from `!standard python RC/ttkbootstrap_custom_theme.md`:
the theme is written into STANDARD_THEMES *before* ttk.Window() is constructed, so
StyleBuilderTTK builds the whole Tcl theme from these colours and nothing from a stock
theme bleeds through.

Font is Segoe UI — sans-serif, per the house guidance for a technical/utility tool.
Consolas for the log widget only.
"""

from __future__ import annotations

THEME_NAME = "batchgen"

# ── Palette ──────────────────────────────────────────────────────────────────
# Medium-shade teal base, cyan accents. Contrast checked against WCAG AA:
# text_primary #E8F6F6 on bg_surface #14403F is ~11:1, text_secondary #A9CFCE
# on the same is ~6.2:1 — both comfortably past the 4.5:1 body-text floor.
PALETTE = {
    # Backgrounds (darkest -> lightest)
    "bg_base":       "#0D2E2D",   # root window + tab pane backgrounds
    "bg_surface":    "#14403F",   # cards, frames, LabelFrames
    "bg_input":      "#0A2422",   # Entry, Combobox, Text backgrounds

    # Accents — cyan
    "accent_strong": "#1B9AAA",   # primary buttons, active tab, radio fill
    "accent_mid":    "#31C6D4",   # hover / active state
    "accent_soft":   "#7FE3EC",   # LabelFrame titles, hyperlinks
    "accent_glow":   "#1E5C5A",   # borders, separators

    # Text
    "text_primary":   "#E8F6F6",
    "text_secondary": "#A9CFCE",
    # Deliberately low-contrast: used ONLY to strike out preview rows that a
    # setting has excluded from the run. Never use it for text a user must read.
    "text_muted":     "#6E8F8E",

    # Semantic — kept recognisable
    "success":       "#4CC38A",
    "danger":        "#FF6B6B",
    "warning":       "#FFC94D",
    "info":          "#4FC3F7",
}

# ── Fonts ─────────────────────────────────────────────────────────────────────
FONT_FAMILY    = "Segoe UI"
FONT_TITLE     = (FONT_FAMILY, 20, "bold")
FONT_HEADING   = (FONT_FAMILY, 14, "bold")
FONT_BODY      = (FONT_FAMILY, 11)
FONT_BODY_BOLD = (FONT_FAMILY, 11, "bold")
FONT_SMALL     = (FONT_FAMILY, 10)
FONT_TINY      = (FONT_FAMILY, 9)
FONT_MONO      = ("Consolas", 10)
FONT_MONO_BOLD = ("Consolas", 11, "bold")


# ── Theme injector ────────────────────────────────────────────────────────────

def _inject_custom_theme(name: str = THEME_NAME) -> None:
    """Register the custom theme in ttkbootstrap's STANDARD_THEMES.

    MUST run before ttk.Window(): Style._load_themes() reads that dict during
    Window.__init__(), and after that it is too late.
    """
    from ttkbootstrap.themes.standard import STANDARD_THEMES

    p = PALETTE
    STANDARD_THEMES[name] = {
        "type": "dark",
        "colors": {
            "bg":        p["bg_base"],
            "fg":        p["text_primary"],
            "primary":   p["accent_strong"],
            "secondary": p["bg_surface"],
            "success":   p["success"],
            "info":      p["info"],
            "warning":   p["warning"],
            "danger":    p["danger"],
            "light":     p["bg_surface"],
            "dark":      p["bg_base"],
            "border":    p["accent_glow"],
            "inputbg":   p["bg_input"],
            "inputfg":   p["text_primary"],
            "selectbg":  p["accent_strong"],
            "selectfg":  p["text_primary"],
            "active":    p["accent_mid"],
        },
    }


# ── Fine-tuning layer ─────────────────────────────────────────────────────────

def apply_theme(style, root=None) -> None:
    """Fine-tune styles StyleBuilderTTK doesn't fully control.

    Call immediately after ttk.Window() and ttk.Style(), before building widgets.
    """
    import tkinter.ttk as _stdlib_ttk

    p = PALETTE

    if root is not None:
        root.configure(bg=p["bg_base"])

    style.configure(
        ".",
        background=p["bg_base"],
        foreground=p["text_primary"],
        bordercolor=p["accent_glow"],
        darkcolor=p["bg_base"],
        lightcolor=p["bg_surface"],
        troughcolor=p["bg_base"],
        selectbackground=p["accent_strong"],
        selectforeground=p["text_primary"],
        fieldbackground=p["bg_input"],
        font=FONT_BODY,
        borderwidth=1,
    )

    # LabelFrame — configure BOTH engines. We use stdlib _tk_ttk.LabelFrame for
    # the padding= fix, and it reads the Tcl style, so this catches it too.
    for s in (style, _stdlib_ttk.Style()):
        s.configure("TLabelframe", background=p["bg_surface"],
                    bordercolor=p["accent_glow"])
        s.configure("TLabelframe.Label", background=p["bg_surface"],
                    foreground=p["accent_soft"], font=FONT_BODY_BOLD)

    # Frames
    style.configure("TFrame", background=p["bg_base"])
    style.configure("Surface.TFrame", background=p["bg_surface"])
    style.configure("ScrollInner.TFrame", background=p["bg_base"])

    # Labels — default sits on a surface (most labels live inside LabelFrames)
    style.configure("TLabel", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_BODY)
    style.configure("Base.TLabel", background=p["bg_base"],
                    foreground=p["text_primary"], font=FONT_BODY)
    style.configure("BaseSecondary.TLabel", background=p["bg_base"],
                    foreground=p["text_secondary"], font=FONT_SMALL)
    style.configure("secondary.TLabel", background=p["bg_surface"],
                    foreground=p["text_secondary"], font=FONT_SMALL)
    style.configure("primary.TLabel", background=p["bg_surface"],
                    foreground=p["accent_soft"], font=FONT_BODY)
    style.configure("success.TLabel", background=p["bg_surface"],
                    foreground=p["success"], font=FONT_BODY)
    style.configure("danger.TLabel", background=p["bg_surface"],
                    foreground=p["danger"], font=FONT_BODY)
    style.configure("warning.TLabel", background=p["bg_surface"],
                    foreground=p["warning"], font=FONT_BODY)
    style.configure("info.TLabel", background=p["bg_surface"],
                    foreground=p["info"], font=FONT_BODY)

    # Big readouts for the live calculator
    style.configure("Figure.TLabel", background=p["bg_surface"],
                    foreground=p["accent_soft"], font=(FONT_FAMILY, 16, "bold"))
    style.configure("FigureFree.TLabel", background=p["bg_surface"],
                    foreground=p["success"], font=(FONT_FAMILY, 16, "bold"))
    style.configure("FigureOver.TLabel", background=p["bg_surface"],
                    foreground=p["danger"], font=(FONT_FAMILY, 16, "bold"))
    style.configure("Heading.TLabel", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_HEADING)
    style.configure("Mono.TLabel", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_MONO)

    # Buttons
    style.configure("TButton", background=p["bg_surface"],
                    foreground=p["text_primary"], bordercolor=p["accent_glow"],
                    font=FONT_BODY)
    style.map("TButton", background=[("active", p["accent_glow"])])
    style.configure("primary.TButton", background=p["accent_strong"],
                    foreground=p["text_primary"], bordercolor=p["accent_glow"],
                    font=FONT_BODY_BOLD)
    style.map("primary.TButton",
              background=[("active", p["accent_mid"]), ("pressed", p["accent_glow"])])
    style.configure("secondary.TButton", background=p["bg_surface"],
                    foreground=p["text_secondary"], bordercolor=p["accent_glow"],
                    font=FONT_BODY)
    style.map("secondary.TButton", background=[("active", p["accent_glow"])])
    # `secondary` paints itself bg_surface -- the SAME colour as the frame it
    # usually sits in -- so it reads as floating text rather than a button, and
    # its `active` colour is the one the button already has. That is tolerable
    # inside a bordered frame (Clear Log) and not tolerable for a standalone
    # control, so this variant gives it a real surface and a hover that moves.
    style.configure("quiet.TButton", background=p["accent_glow"],
                    foreground=p["text_primary"], bordercolor=p["accent_glow"],
                    font=FONT_BODY)
    # No explicit `disabled` background: the other batch buttons (Pause,
    # Cancel) let ttkbootstrap dim their own colour, and overriding it to
    # bg_surface made this one disappear into the frame instead of looking
    # disabled like its neighbours.
    style.map("quiet.TButton",
              background=[("active", p["accent_strong"]),
                          ("pressed", p["bg_input"])],
              foreground=[("disabled", p["text_muted"])])
    style.configure("success.TButton", background=p["success"],
                    foreground="#062318", bordercolor=p["success"],
                    font=FONT_BODY_BOLD)
    style.configure("danger.TButton", background=p["danger"],
                    foreground="#2A0606", bordercolor=p["danger"],
                    font=FONT_BODY_BOLD)
    style.configure("warning.TButton", background=p["warning"],
                    foreground="#2A2000", bordercolor=p["warning"],
                    font=FONT_BODY_BOLD)
    style.configure("info.TButton", background=p["info"],
                    foreground="#04202B", bordercolor=p["info"],
                    font=FONT_BODY_BOLD)

    # File/folder picker buttons
    style.configure("Folder.TButton", background=p["accent_strong"],
                    foreground=p["text_primary"], bordercolor=p["accent_glow"],
                    font=FONT_BODY)
    style.map("Folder.TButton",
              background=[("active", p["accent_mid"]), ("pressed", p["accent_glow"])])

    # Inputs
    style.configure("TEntry", fieldbackground=p["bg_input"],
                    foreground=p["text_primary"], bordercolor=p["accent_glow"],
                    insertcolor=p["text_primary"], font=FONT_BODY)
    style.configure("TCombobox", fieldbackground=p["bg_input"],
                    foreground=p["text_primary"], background=p["bg_surface"],
                    arrowcolor=p["accent_soft"], font=FONT_BODY)
    style.map("TCombobox",
              fieldbackground=[("readonly", p["bg_input"])],
              foreground=[("readonly", p["text_primary"])])
    style.configure("TSpinbox", fieldbackground=p["bg_input"],
                    foreground=p["text_primary"], background=p["bg_surface"],
                    arrowcolor=p["accent_soft"], font=FONT_BODY)

    # Notebook
    style.configure("TNotebook", background=p["bg_base"], bordercolor=p["bg_base"])
    style.configure("TNotebook.Tab", background=p["bg_surface"],
                    foreground=p["text_secondary"], font=FONT_BODY,
                    padding=(16, 7))
    style.map("TNotebook.Tab",
              background=[("selected", p["accent_strong"])],
              foreground=[("selected", p["text_primary"])])

    # Selection widgets
    style.configure("TRadiobutton", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_BODY)
    style.configure("primary.TRadiobutton", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_BODY)
    style.configure("TCheckbutton", background=p["bg_surface"],
                    foreground=p["text_primary"], font=FONT_BODY)

    # Progress bar
    style.configure("TProgressbar", background=p["accent_strong"],
                    troughcolor=p["bg_input"], bordercolor=p["accent_glow"])
    style.configure("striped.Horizontal.TProgressbar",
                    background=p["accent_strong"], troughcolor=p["bg_input"])

    style.configure("TSeparator", background=p["accent_glow"])

    # NOTE: do NOT style TScrollbar here. ttkbootstrap intercepts
    # style.configure() for scrollbars and re-runs element_create() on image
    # elements it has already registered, raising
    # "Duplicate element Horizontal.TScrollbar.thumb". Scrollbars pick up the
    # injected palette on their own, so there is nothing to gain by trying.

    # Treeview — the job list on the Run tab
    style.configure("Treeview", background=p["bg_input"],
                    fieldbackground=p["bg_input"], foreground=p["text_primary"],
                    bordercolor=p["accent_glow"], font=FONT_SMALL, rowheight=22)
    style.configure("Treeview.Heading", background=p["bg_surface"],
                    foreground=p["accent_soft"], font=FONT_BODY_BOLD)
    style.map("Treeview",
              background=[("selected", p["accent_strong"])],
              foreground=[("selected", p["text_primary"])])
