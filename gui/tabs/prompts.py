"""Prompts tab — prompt file, output folder, style suffix, and a live preview
of exactly what will be sent to the API.

The preview matters: the style suffix is appended to every line, so seeing the
final prompt before spending anything is the cheapest possible sanity check.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import ttkbootstrap as ttk
from tkinter import ttk as _tk_ttk
from tkinter import filedialog, messagebox, simpledialog

from core import models as M
from core import prompts as P
from core import reference as R
from gui.tooltip import tip
from gui.scroll import autowrap, make_scrollable
from gui.theme import FONT_BODY, FONT_MONO, FONT_SMALL, PALETTE
from utils.config import BUILTIN_PRESETS, app_dir


class PromptsTab:
    def __init__(self, notebook, app):
        self.app = app
        self.cfg = app.config
        # Set while code (not the user) moves the slider, so the trace that
        # persists the value does not fight the code that is setting it.
        self._syncing_limit = False
        self._total_prompts = 0
        self._build(notebook)
        self.refresh_preview()

    # ------------------------------------------------------------------ #

    def _build(self, notebook) -> None:
        # Scrollable like the other tabs: the style editor and the preview
        # both need real height, and squeezing either to a sliver to make them
        # fit is worse than scrolling.
        tab = make_scrollable(notebook, "  Prompts  ")
        tab.columnconfigure(0, weight=1)

        self._build_files(tab, row=0)
        self._build_presets(tab, row=1)
        self._build_style(tab, row=2)
        self._build_preview(tab, row=3)

    # -- file pickers ---------------------------------------------------

    def _build_files(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Files", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 5))
        f.columnconfigure(1, weight=1)

        # Prompt file
        ttk.Label(f, text="Prompt file:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        self.prompt_var = tk.StringVar(value=self.cfg.get("prompt_file", ""))
        e1 = ttk.Entry(f, textvariable=self.prompt_var)
        e1.grid(row=0, column=1, sticky="ew", pady=4)
        self.app.attach_context_menu(e1)
        self.prompt_var.trace_add("write", lambda *_: self._on_prompt_typed())
        tip(e1, text="A plain .txt file with one prompt per line. "
                         "Blank lines are skipped.")

        b1 = ttk.Button(f, text="Choose Prompt File…", width=22,
                        style="Folder.TButton", command=self._pick_prompt_file)
        b1.grid(row=0, column=2, sticky="w", padx=(8, 0), pady=4)
        tip(b1, text="Pick the .txt file holding your prompts, "
                         "one per line.")

        # Greyed out rather than hidden while the override is on: the file is
        # a setting the user still wants, and a control that vanishes reads as
        # the app losing it. Hiding is for a feature the model CANNOT use.
        self._file_widgets = (e1, b1)

        # Output folder
        ttk.Label(f, text="Save images to:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        self.output_var = tk.StringVar(value=self.cfg.get("output_dir", ""))
        e2 = ttk.Entry(f, textvariable=self.output_var)
        e2.grid(row=1, column=1, sticky="ew", pady=4)
        self.app.attach_context_menu(e2)
        self.output_var.trace_add(
            "write", lambda *_: self.app.set_cfg("output_dir",
                                                 self.output_var.get()))
        tip(e2, text="Images and their .json metadata sidecars land here. "
                        "Re-running the same batch skips images already saved.")

        b2 = ttk.Button(f, text="Choose Output Folder…", width=22,
                        style="Folder.TButton", command=self._pick_output_dir)
        b2.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        b3 = ttk.Button(f, text="Open Output Folder", width=22,
                        style="secondary.TButton",
                        command=lambda: self.app.open_folder(self.output_var.get()))
        b3.grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(0, 2))

        self.file_status = ttk.Label(f, text="", style="secondary.TLabel")
        self.file_status.grid(row=2, column=0, columnspan=2, sticky="w",
                              pady=(0, 2))

        self._build_one_off(f, row=3)

    # -- the one-off prompt override ------------------------------------

    def _build_one_off(self, parent, row: int) -> None:
        """One image from a box of text, instead of a whole prompt file.

        Sits at the BOTTOM OF THIS FRAME, directly under the prompt-file row
        it overrides, so the thing being disabled and the thing disabling it
        are next to each other. In its own frame further down, the cause and
        the effect would be separated by everything in between.
        """
        box = ttk.Frame(parent, style="Surface.TFrame")
        box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        box.columnconfigure(0, weight=1)

        self.one_off_var = tk.BooleanVar(
            value=bool(self.cfg.get("one_off_enabled", False)))
        chk = ttk.Checkbutton(
            box, text="Single custom prompt — ignore the prompt file and "
                      "generate ONE image from the text below",
            variable=self.one_off_var, style="Switch.TCheckbutton",
            command=self._on_one_off_toggled,
        )
        chk.grid(row=0, column=0, sticky="w")
        tip(chk, text="For trying an idea before it is worth writing a file "
                      "for.\n\nEverything else still applies — the style "
                      "suffix is appended, the model, size, negative prompt "
                      "and seed are all the ones on the Provider tab. The "
                      "only difference is where the prompt comes from and "
                      "that there is exactly one of it.\n\nYour prompt file "
                      "is left alone; untick this to go back to it.")

        # The banner states the CONSEQUENCE, not the mode's name. "Override
        # active" tells a user who has forgotten what the mode does nothing;
        # what will happen when they press Start tells them everything.
        self.one_off_banner = ttk.Label(
            box, text="", style="warning.TLabel", wraplength=900,
            justify="left")
        self.one_off_banner.grid(row=1, column=0, sticky="w", pady=(4, 0))
        autowrap(self.one_off_banner, box)

        wrap = ttk.Frame(box, style="Surface.TFrame")
        wrap.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.one_off_text = tk.Text(
            wrap, height=3, wrap="word", font=FONT_BODY,
            bg=PALETTE["bg_input"], fg=PALETTE["text_primary"],
            insertbackground=PALETTE["text_primary"],
            selectbackground=PALETTE["accent_strong"],
            selectforeground=PALETTE["text_primary"],
            relief="flat", borderwidth=6, highlightthickness=1,
            highlightbackground=PALETTE["accent_glow"],
            highlightcolor=PALETTE["accent_mid"],
        )
        self.one_off_text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(wrap, orient="vertical",
                           command=self.one_off_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.one_off_text.configure(yscrollcommand=sb.set)

        # Persisted as its own .txt beside the program rather than in
        # config.json -- see core.prompts for why.
        self.one_off_text.insert("1.0", P.read_one_off(app_dir()))
        self.one_off_text.bind("<KeyRelease>",
                               lambda e: self._on_one_off_changed())
        # A right-click Paste fires no KeyRelease, so keystrokes alone would
        # lose a pasted prompt -- which is exactly how a long prompt arrives.
        # <<Paste>> is bound after the event so the text is already in.
        self.one_off_text.bind(
            "<<Paste>>",
            lambda e: self.one_off_text.after_idle(self._on_one_off_changed),
            add="+")
        self.one_off_text.bind("<FocusOut>",
                               lambda e: self._on_one_off_changed(), add="+")
        self.app.attach_context_menu(self.one_off_text)

        grip = ttk.Frame(box, height=6, style="Surface.TFrame",
                         cursor="sb_v_double_arrow")
        grip.grid(row=3, column=0, sticky="ew", pady=(3, 0))
        _make_resizer(grip, self.one_off_text, min_lines=2, max_lines=12)

        self._sync_one_off_state()

    def one_off_active(self) -> bool:
        """Is the override both switched on and actually holding text?

        Both halves matter: a ticked box over an empty editor must not be
        treated as a runnable batch of one blank prompt.
        """
        return bool(self.one_off_var.get()) and bool(self.one_off_prompt())

    def one_off_prompt(self) -> str:
        return self.one_off_text.get("1.0", "end").strip()

    def _on_one_off_toggled(self) -> None:
        self.app.set_cfg("one_off_enabled", bool(self.one_off_var.get()))
        self._sync_one_off_state()
        self.refresh_preview()

    def _on_one_off_changed(self) -> None:
        P.write_one_off(app_dir(), self.one_off_prompt())
        if self.one_off_var.get():
            self.refresh_preview()

    def _sync_one_off_state(self) -> None:
        """Grey out the prompt-file row, and say what will happen."""
        on = bool(self.one_off_var.get())
        for w in self._file_widgets:
            try:
                w.configure(state="disabled" if on else "normal")
            except tk.TclError:
                pass

        # The box stays EDITABLE while the override is off. Disabling it bought
        # nothing -- a tk.Text does not visibly grey out, so the only effect was
        # a box that silently refused to accept typing. Drafting the next idea
        # before arming the override is a reasonable thing to want to do.

        # The label always says something, and stating the OFF case explicitly
        # is what makes the ON case read as a change rather than as noise. An
        # empty label also left a hole in the layout until the box was ticked.
        if not on:
            self.one_off_banner.configure(
                text="Disabled — using the selected prompt file. "
                     "Tick above to generate one image from the text below "
                     "instead.",
                style="success.TLabel")
        elif not self.one_off_prompt():
            # Ticked with nothing typed is not a runnable batch, and saying so
            # here is cheaper than a dialog at the moment Start is pressed.
            self.one_off_banner.configure(
                text="Override on, but the box below is empty — type a prompt, "
                     "or untick to use your prompt file.",
                style="danger.TLabel")
        else:
            self.one_off_banner.configure(
                text="Override on — generating 1 image from the text below. "
                     "Your prompt file is ignored.",
                style="warning.TLabel")

    def _pick_prompt_file(self) -> None:
        initial = self.prompt_var.get() or str(Path.cwd())
        path = filedialog.askopenfilename(
            parent=self.app.root,
            title="Choose a prompt file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialdir=str(Path(initial).parent if Path(initial).is_file()
                           else Path.cwd()),
        )
        if path:
            self.prompt_var.set(path)

    def _pick_output_dir(self) -> None:
        current = self.output_var.get()
        path = filedialog.askdirectory(
            parent=self.app.root,
            title="Choose where to save generated images",
            initialdir=current if current and Path(current).is_dir()
            else str(Path.cwd()),
        )
        if path:
            self.output_var.set(path)

    def _on_prompt_typed(self) -> None:
        self.app.set_cfg("prompt_file", self.prompt_var.get())
        self.refresh_preview()

    # -- presets --------------------------------------------------------

    def _build_presets(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Style Presets", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Preset:").grid(row=0, column=0, sticky="w",
                                          padx=(0, 8))

        self.preset_var = tk.StringVar(value=self.cfg.get("last_preset", "01 Main - Digital Art"))
        self.preset_combo = ttk.Combobox(
            f, textvariable=self.preset_var, state="readonly",
            values=self._preset_names(), width=52, height=15,
        )
        self.preset_combo.grid(row=0, column=1, sticky="w")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        tip(self.preset_combo,
                text="Load a saved style suffix into the editor below. "
                     "Built-ins are grouped and numbered (e.g. \"01 Main\", "
                     "\"09 Artist\") so related styles sort together; your "
                     "own saved presets always sort to the top.")

        btns = ttk.Frame(f, style="Surface.TFrame")
        btns.grid(row=0, column=2, sticky="e", padx=(8, 0))

        b_save = ttk.Button(btns, text="Save As Preset…", width=17,
                            style="primary.TButton", command=self._save_preset)
        b_save.pack(side="left", padx=2)
        tip(b_save, text="Save the text in the editor below as a new "
                             "named preset (or overwrite an existing one).")

        b_del = ttk.Button(btns, text="Delete Preset", width=15,
                           style="secondary.TButton", command=self._delete_preset)
        b_del.pack(side="left", padx=2)
        tip(b_del, text="Remove the selected preset. The built-in presets "
                            "are restored if you delete everything.")

    def _preset_names(self) -> list[str]:
        """User presets first, then the built-ins in their numbered order.

        The built-ins are named "NN GROUP - NAME" so that a plain sort keeps
        them grouped (see docs/preset-naming-scheme.md). A user's own presets
        belong above all of them, and the leading "*" the Save As dialog
        suggests already sorts that way -- but only by convention, and a name
        typed without it would land somewhere in the middle of the built-ins.
        Partitioning on membership makes it true regardless of the name.
        """
        names = self.cfg.get("style_presets", BUILTIN_PRESETS).keys()
        mine = sorted(n for n in names if n not in BUILTIN_PRESETS)
        builtin = sorted(n for n in names if n in BUILTIN_PRESETS)
        return mine + builtin

    def _on_preset_selected(self, _evt=None) -> None:
        name = self.preset_var.get()
        text = self.cfg.get("style_presets", {}).get(name, "")
        self.style_text.delete("1.0", "end")
        self.style_text.insert("1.0", text)
        self.app.set_cfg("last_preset", name)
        self._on_style_changed()

    def _save_as_default(self) -> str:
        """What the Save As box starts with.

        Nudges toward the naming scheme without enforcing it: saving a tweak
        of "01 MAIN - DIGITAL ART" opens at "*01 MAIN - DIGITAL ART", so the
        user edits a name that is already shaped correctly and already sorts
        to the top. Saving over one of their own presets keeps its name, so
        overwriting stays a matter of pressing OK.
        """
        current = self.preset_var.get()
        if current in BUILTIN_PRESETS:
            return f"*{current}"
        return current or "*"

    def _save_preset(self) -> None:
        current = self.style_text.get("1.0", "end").strip()
        if not current:
            messagebox.showinfo("Nothing to save",
                                "The style suffix editor is empty.",
                                parent=self.app.root)
            return
        name = simpledialog.askstring(
            "Save preset", "Name for this style preset:",
            initialvalue=self._save_as_default(), parent=self.app.root,
        )
        if not name:
            return
        name = name.strip()
        presets = dict(self.cfg.get("style_presets", {}))
        presets[name] = current
        self.cfg["style_presets"] = presets
        self.app.set_cfg("last_preset", name)
        self.preset_combo.configure(values=self._preset_names())
        self.preset_var.set(name)
        self.app.log(f"Saved style preset '{name}'.")

    def _delete_preset(self) -> None:
        name = self.preset_var.get()
        presets = dict(self.cfg.get("style_presets", {}))
        if name not in presets:
            return
        if not messagebox.askyesno("Delete preset",
                                   f"Delete the preset '{name}'?",
                                   parent=self.app.root):
            return
        presets.pop(name, None)
        if not presets:
            presets = dict(BUILTIN_PRESETS)     # never leave the list empty
        self.cfg["style_presets"] = presets
        self.app.save()
        self.preset_combo.configure(values=self._preset_names())
        self.preset_var.set(self._preset_names()[0])
        self._on_preset_selected()

    # -- style suffix editor --------------------------------------------

    def _build_style(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(
            parent, text="Style Suffix — appended to every prompt", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        hint = ttk.Label(
            f,
            text="This text is added to the end of every line in your prompt "
                 "file. Leave it empty to send prompts unchanged.",
            style="secondary.TLabel", wraplength=900, justify="left",
        )
        hint.grid(row=0, column=0, sticky="w", pady=(0, 6))
        autowrap(hint, f)

        # A style suffix can be long, and it is easy to type more than fits.
        # Without a scrollbar the overflow is simply invisible.
        wrap = ttk.Frame(f, style="Surface.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        # tk.Text does not inherit ttk styling — colours must be explicit.
        self.style_text = tk.Text(
            wrap, height=5, wrap="word", font=FONT_BODY,
            bg=PALETTE["bg_input"], fg=PALETTE["text_primary"],
            insertbackground=PALETTE["text_primary"],
            selectbackground=PALETTE["accent_strong"],
            selectforeground=PALETTE["text_primary"],
            relief="flat", borderwidth=6, highlightthickness=1,
            highlightbackground=PALETTE["accent_glow"],
            highlightcolor=PALETTE["accent_mid"],
        )
        self.style_text.grid(row=0, column=0, sticky="nsew")

        style_sb = ttk.Scrollbar(wrap, orient="vertical",
                                 command=self.style_text.yview)
        style_sb.grid(row=0, column=1, sticky="ns")
        self.style_text.configure(yscrollcommand=style_sb.set)

        self.style_text.insert("1.0", self.cfg.get("style_suffix", ""))
        self.style_text.bind("<KeyRelease>", lambda e: self._on_style_changed())
        self.app.attach_context_menu(self.style_text)

        # A drag handle: the editor can be made taller when a preset is long.
        grip = ttk.Frame(f, height=6, style="Surface.TFrame", cursor="sb_v_double_arrow")
        grip.grid(row=2, column=0, sticky="ew", pady=(3, 0))
        _make_resizer(grip, self.style_text, min_lines=3, max_lines=20)

        # The counter measures the WHOLE finished prompt - the longest line in
        # the file plus this suffix - because that combined string is what the
        # model actually receives. Measuring the suffix on its own would read
        # comfortably short right up to the point the model truncated it.
        self.style_count = ttk.Label(f, text="", style="secondary.TLabel")
        self.style_count.grid(row=3, column=0, sticky="w", pady=(4, 0))
        tip(self.style_count,
            text="Roughly how long your longest finished prompt is, against "
                 "what the selected model reads comfortably.\n\n"
                 "This is advice, not a limit - nothing here truncates your "
                 "text. But the MODEL does: past its encoder's budget the tail "
                 "of a prompt is silently dropped, with no error and nothing "
                 "in the image to show that anything went missing.\n\n"
                 "Stable Diffusion models are the tight ones (77 tokens, "
                 "roughly 300 characters). The FLUX klein models read far "
                 "more, so long descriptive prompts are worth writing there "
                 "and largely wasted on SD.")

    def _on_style_changed(self) -> None:
        self.app.set_cfg("style_suffix",
                         self.style_text.get("1.0", "end").strip())
        self.refresh_preview()

    # -- prompt length advice ---------------------------------------------

    def refresh_length_hint(self) -> None:
        """Update the character counter.

        Also called by the Provider tab: changing the model changes the budget
        without changing a single character of the text.
        """
        if not hasattr(self, "style_count"):
            return
        spec = self._current_spec()
        suffix = self.style_text.get("1.0", "end").strip()

        longest, line_no = self._longest_prompt()
        combined = f"{longest} {suffix}".strip() if longest else suffix
        # The reference-influence sentence is part of what the model reads,
        # so it counts against the same budget.
        combined = R.with_influence(combined, self._influence_phrase())

        adv = P.length_advice(combined, spec.prompt_soft_limit,
                              spec.prompt_hard_limit)
        where = (f"  (line {line_no} + suffix)" if longest
                 else "  (style suffix only - no prompt file loaded)")
        self.style_count.configure(
            text=f"Longest finished prompt: {adv.message}{where}",
            style=_LEVEL_STYLE[adv.level])

    def _influence_phrase(self) -> str:
        """The reference-influence sentence the engine will add, or "".

        The GUI decides only whether a reference is ARMED -- the flag and a
        path, the same two halves app._reference_path() requires. Which
        sentence that means for this model is core.reference's call.
        """
        if not self.cfg.get("reference_enabled"):
            return ""
        if not (self.cfg.get("reference_image") or "").strip():
            return ""
        return R.influence_phrase(
            self.cfg.get("reference_influence", R.DEFAULT_INFLUENCE),
            self._current_spec())

    def _current_spec(self):
        try:
            return M.get_model(self.cfg.get("model", M.DEFAULT_MODEL))
        except KeyError:
            return M.get_model(M.DEFAULT_MODEL)

    def _longest_prompt(self) -> tuple[str, int]:
        """The longest raw prompt in the file, with its line number.

        The longest one decides whether anything gets truncated at all, so an
        average would quietly hide the only case that actually matters.
        """
        # With the override on there is exactly one prompt, and grading the
        # file's longest line would measure text nobody is sending.
        if self.one_off_active():
            return self.one_off_prompt(), 1

        path = (self.prompt_var.get() or "").strip()
        if not path or not Path(path).is_file():
            return "", 0
        try:
            lines = P.load_prompts(path)
        except Exception:
            return "", 0
        if not lines:
            return "", 0
        best = max(lines, key=lambda ln: len(ln.original))
        return best.original, best.line_no

    # -- preview --------------------------------------------------------

    def _build_preview(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(
            parent, text="Preview — exactly what will be sent", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(5, 10))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        top = ttk.Frame(f, style="Surface.TFrame")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.columnconfigure(0, weight=1)

        self.count_label = ttk.Label(top, text="No prompt file selected.",
                                     style="primary.TLabel")
        self.count_label.grid(row=0, column=0, sticky="w")

        b = ttk.Button(top, text="Refresh", width=12,
                       style="secondary.TButton", command=self.refresh_preview)
        b.grid(row=0, column=1, sticky="e")
        tip(b, text="Re-read the prompt file from disk. Use this after "
                        "editing the file in a text editor.")

        self._build_limit(top, row=1)

        wrap = ttk.Frame(f, style="Surface.TFrame")
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.preview_text = tk.Text(
            wrap, wrap="word", font=FONT_MONO, height=14,
            bg=PALETTE["bg_input"], fg=PALETTE["text_primary"],
            insertbackground=PALETTE["text_primary"],
            selectbackground=PALETTE["accent_strong"],
            selectforeground=PALETTE["text_primary"],
            relief="flat", borderwidth=6, highlightthickness=1,
            highlightbackground=PALETTE["accent_glow"],
            state="disabled",
        )
        self.preview_text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(wrap, orient="vertical",
                           command=self.preview_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.preview_text.configure(yscrollcommand=sb.set)

        self.preview_text.tag_configure("num", foreground=PALETTE["accent_soft"])
        self.preview_text.tag_configure("suffix",
                                        foreground=PALETTE["text_secondary"])
        # Prompts past the slider's cut — dimmed and struck through, not
        # hidden: they are still in the file, and seeing exactly where the cut
        # falls is the point of having a preview at all.
        self.preview_text.tag_configure("skipped",
                                        foreground=PALETTE["text_muted"],
                                        overstrike=True)
        self.app.attach_context_menu(self.preview_text)

    # -- how many of them to generate ------------------------------------

    def _build_limit(self, parent, row: int) -> None:
        """A slider capping the run at the first N prompts.

        The point is trying a style on 5 of 100 without maintaining a second
        prompt file. It takes the FIRST N, not a random N, because resume keys
        a job on its line number -- so a capped run and a later full run share
        their overlapping images instead of regenerating them.
        """
        box = ttk.Frame(parent, style="Surface.TFrame")
        box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Generate:").grid(row=0, column=0, sticky="w",
                                              padx=(0, 8))

        # from_=1: a batch of zero images is not a thing anyone wants, and the
        # slider's left edge is otherwise a silent no-op run.
        self.limit_scale = ttk.Scale(box, from_=1, to=1, orient="horizontal",
                                     command=self._on_limit_dragged)
        self.limit_scale.grid(row=0, column=1, sticky="ew")
        tip(self.limit_scale,
            text="Generate only the first N prompts in the file.\n\n"
                 "Set to the maximum whenever you load a file, so the "
                 "default is always 'all of them'. Drag it down to try a "
                 "style on a handful first — 5 of 100 — without building "
                 "a separate test file.\n\n"
                 "It always takes the prompts from the TOP of the file, "
                 "which is what lets a later full run reuse the images a "
                 "short test run already made instead of paying for them "
                 "twice.")

        self.limit_label = ttk.Label(box, text="", style="primary.TLabel",
                                     width=18, anchor="w")
        self.limit_label.grid(row=0, column=2, sticky="w", padx=(10, 0))

        b_all = ttk.Button(box, text="All", width=6,
                           style="secondary.TButton", command=self._limit_all)
        b_all.grid(row=0, column=3, sticky="e", padx=(8, 0))
        tip(b_all, text="Reset the slider back to every prompt in the file.")

        self.limit_note = ttk.Label(box, text="", style="secondary.TLabel",
                                    wraplength=900, justify="left")
        self.limit_note.grid(row=1, column=0, columnspan=4, sticky="w",
                             pady=(4, 0))
        autowrap(self.limit_note, box)

    def _limit_all(self) -> None:
        self._set_limit(self._total_prompts)

    def _on_limit_dragged(self, _value=None) -> None:
        if self._syncing_limit:
            return
        # ttk.Scale is continuous; a prompt count is not.
        self._set_limit(int(round(float(self.limit_scale.get()))))

    def _set_limit(self, n: int) -> None:
        total = self._total_prompts
        n = max(1, min(n, total)) if total else 0

        self._syncing_limit = True
        try:
            if total:
                self.limit_scale.set(n)
        finally:
            self._syncing_limit = False

        # Persist None for "all" rather than the number: the prompt file can
        # gain lines between sessions, and a stored 100 would silently cap a
        # file that had grown to 120.
        #
        # But NOT while the override is on. A one-off run pins the total to 1,
        # so n >= total always holds, and writing that through would quietly
        # erase a cap the user had set on their real prompt file.
        if not self.one_off_var.get():
            self.app.set_cfg("prompt_limit",
                             None if (not total or n >= total) else n)
        self._update_limit_labels(n)

        # The batch cost on the Provider tab is per-image x COUNT, so moving
        # the slider has to move the money.
        provider_tab = getattr(self.app, "provider_tab", None)
        if provider_tab is not None:
            provider_tab.recalculate()

    def _update_limit_labels(self, n: int) -> None:
        total = self._total_prompts
        # "Only the first 1 prompt will be generated — a test run" is a
        # nonsense sentence about a batch that has exactly one prompt in it.
        if self.one_off_var.get():
            self.limit_label.configure(text="1 image" if total else "—")
            self.limit_note.configure(text="")
            return
        if not total:
            self.limit_label.configure(text="—")
            self.limit_note.configure(text="")
            return

        self.limit_label.configure(text=f"{n} of {total} image(s)")
        if n >= total:
            self.limit_note.configure(text="Generating every prompt in the file.")
        else:
            self.limit_note.configure(
                text=f"Only the first {n} prompt(s) will be generated — a test "
                     f"run. The remaining {total - n} are skipped; generating "
                     f"the full file later will reuse these {n} images rather "
                     f"than remaking them.")

    def _sync_limit(self, total: int) -> None:
        """Re-point the slider at a newly loaded prompt file.

        Default is ALWAYS the maximum: a file just chosen should generate in
        full unless the user says otherwise. A stored limit is only honoured
        when it is still a real cap on this file.
        """
        self._total_prompts = total
        stored = self.cfg.get("prompt_limit")

        self._syncing_limit = True
        try:
            # to=1 with from_=1 when the file is empty keeps the widget legal.
            self.limit_scale.configure(to=max(total, 1))
            self.limit_scale.configure(state="normal" if total > 1 else "disabled")
        finally:
            self._syncing_limit = False

        n = total
        if isinstance(stored, int) and 0 < stored < total:
            n = stored
        self._set_limit(n)

    # -- preview refresh ---------------------------------------------------

    def refresh_preview(self) -> None:
        path = (self.prompt_var.get() or "").strip()
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        # This box is titled "exactly what will be sent". Leaving it listing
        # the file's prompts while the override is armed would make it lie --
        # the same shape of fault as a sidecar recording a size the provider
        # never delivered.
        if self.one_off_var.get():
            self._sync_one_off_state()
            self._render_one_off_preview()
            return

        if not path:
            self.count_label.configure(text="No prompt file selected.")
            self.file_status.configure(text="")
            self.preview_text.configure(state="disabled")
            self._sync_limit(0)
            self.refresh_length_hint()
            return
        if not Path(path).is_file():
            self.count_label.configure(text="File not found.")
            self.file_status.configure(text=f"Not found: {path}")
            self.preview_text.configure(state="disabled")
            self._sync_limit(0)
            self.refresh_length_hint()
            return

        suffix = self.style_text.get("1.0", "end").strip()
        try:
            lines = P.load_prompts(path, suffix)
        except Exception as e:
            self.count_label.configure(text=f"Could not read the file: {e}")
            self.preview_text.configure(state="disabled")
            self._sync_limit(0)
            self.refresh_length_hint()
            return

        self.count_label.configure(
            text=f"{len(lines)} prompt(s) — one image each.")
        self.file_status.configure(text=f"{len(lines)} prompt(s) loaded.")

        # Re-points the slider at this file, and calls recalculate() for us:
        # the batch total on the Provider tab is per-image cost x COUNT, so
        # both a new prompt file and a moved slider have to move the money.
        self._sync_limit(len(lines))
        limit = self._current_limit()
        phrase = self._influence_phrase()

        for i, ln in enumerate(lines):
            skipped = i >= limit
            self.preview_text.insert(
                "end", f"{ln.line_no:>3}  ", "skipped" if skipped else "num")
            self.preview_text.insert(
                "end", ln.original, "skipped" if skipped else ())
            if suffix:
                self.preview_text.insert(
                    "end", f" {suffix}", "skipped" if skipped else "suffix")
            if phrase:
                added = R.with_influence(ln.final, phrase)[len(ln.final):]
                self.preview_text.insert(
                    "end", added, "skipped" if skipped else "suffix")
            self.preview_text.insert("end", "\n\n")

        self.preview_text.configure(state="disabled")
        self.refresh_length_hint()

    def _render_one_off_preview(self) -> None:
        """Draw the single override prompt, and pin the count at one."""
        prompt = self.one_off_prompt()
        suffix = self.style_text.get("1.0", "end").strip()

        if not prompt:
            self.count_label.configure(
                text="Single custom prompt — nothing typed yet.")
            self.file_status.configure(text="Prompt file ignored (override on).")
            self.preview_text.configure(state="disabled")
            self._sync_limit(0)
            self.refresh_length_hint()
            return

        self.count_label.configure(
            text="Single custom prompt — 1 image.")
        self.file_status.configure(text="Prompt file ignored (override on).")

        self.preview_text.insert("end", "  1  ", "num")
        self.preview_text.insert("end", prompt)
        if suffix:
            self.preview_text.insert("end", f" {suffix}", "suffix")
        phrase = self._influence_phrase()
        if phrase:
            final = f"{prompt} {suffix}".strip() if suffix else prompt
            self.preview_text.insert(
                "end", R.with_influence(final, phrase)[len(final):], "suffix")
        self.preview_text.insert("end", "\n\n")
        self.preview_text.configure(state="disabled")

        # One prompt, so the "generate the first N" slider has nothing left to
        # choose. _sync_limit disables it at a total of 1 already, and this
        # also re-drives the Provider tab's batch cost down to a single image.
        self._sync_limit(1)
        self.refresh_length_hint()

    def _current_limit(self) -> int:
        """How many prompts this run will actually generate."""
        if self.one_off_active():
            return 1
        stored = self.cfg.get("prompt_limit")
        if isinstance(stored, int) and 0 < stored < self._total_prompts:
            return stored
        return self._total_prompts


# Three levels, three colours. "near" uses the warning colour rather than the
# danger one on purpose: being close to the budget is a note, not a fault.
_LEVEL_STYLE = {
    "ok":   "secondary.TLabel",
    "near": "warning.TLabel",
    "over": "danger.TLabel",
}


def _make_resizer(grip, text_widget, min_lines: int = 3, max_lines: int = 20):
    """Let the user drag `grip` to change a Text widget's height.

    tk.Text sizes in lines, not pixels, so the drag is converted through the
    font's line height. Clamped so it cannot be collapsed to nothing or grown
    past the tab.
    """
    import tkinter.font as tkfont

    state = {"y": 0, "start": 0, "line_h": 18}

    def press(event):
        state["y"] = event.y_root
        state["start"] = int(text_widget.cget("height"))
        try:
            state["line_h"] = max(
                tkfont.Font(font=text_widget.cget("font")).metrics("linespace"),
                8)
        except Exception:
            state["line_h"] = 18

    def drag(event):
        delta = (event.y_root - state["y"]) // state["line_h"]
        new_h = max(min_lines, min(max_lines, state["start"] + int(delta)))
        if new_h != int(text_widget.cget("height")):
            text_widget.configure(height=new_h)

    grip.bind("<Button-1>", press)
    grip.bind("<B1-Motion>", drag)
