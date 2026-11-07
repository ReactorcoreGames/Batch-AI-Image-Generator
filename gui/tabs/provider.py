"""Provider tab — model, size, the live cost calculator, and politeness controls.

The calculator is the headline feature: pick a model and a size and the real
price appears immediately, before anything is spent. Every figure comes from
`core.models.estimate()` — nothing about pricing or dimensions is computed here.

Two measured findings drive the warnings shown on this tab:
  * High tier is klein-only. SD models degrade above ~1024.
  * High is 64% slower on klein-4b (16.1s vs 9.8s). On an overnight batch that
    costs more than the money does.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

import ttkbootstrap as ttk
from tkinter import ttk as _tk_ttk
from tkinter import filedialog, messagebox, simpledialog

from core import models as M
from core.engine import DEFAULT_MAX_ATTEMPTS
from core import prompts as P
from core import reference as R
from core.imagecheck import CONVERT_FORMATS
from core.providers.cloudflare import (
    CREDIT_PURCHASE_FEE_PERCENT,
    CREDITS_DASHBOARD_URL,
    USAGE_DASHBOARD_URL,
)
from gui.tooltip import tip
from gui.scroll import autowrap, make_scrollable, reserve_lines
from gui.theme import FONT_BODY, FONT_MONO, FONT_SMALL, PALETTE
from utils.config import BUILTIN_NEGATIVE_PRESETS
from utils.credentials import (
    FIELDS,
    FIELDS_BY_KEY,
    effective_value,
    load_credentials,
    save_credentials,
)

def reference_hint(spec: M.ModelSpec, influence: str, armed: bool) -> str:
    """The line under the Influence dropdown: what it adds, in the model's
    own words, plus how to write it by hand.

    Per MODEL rather than a constant: klein addresses the reference by index
    ("image 0", Cloudflare's own example), and the other families have no
    documented index convention, so telling a nano-banana user to write
    "image 0" would be advice with nothing behind it.
    """
    phrase = R.influence_phrase(influence, spec)
    if not armed:
        head = (f"Will add \u201c{phrase}\u201d to every prompt once a "
                f"reference image is in use.")
    else:
        head = f"Adds to the end of every prompt: \u201c{phrase}\u201d"
    return (f"{head}\nTo write it yourself, {spec.short_name} knows the "
            f"reference as \u201c{spec.reference_prompt_name}\u201d.")

# Prompt-expansion modes as the user sees them. "raw" is the API's value for
# "do not expand", which is an unhelpful name in a dropdown -- Off says what
# it does. The program defaults to Off; the API defaults to "low".
EXPANSION_LABELS: dict[str, str] = {
    "raw": "Off — use my prompt exactly",
    "low": "Light",
    "medium": "Moderate",
    "high": "Heavy",
}

# Content-filter modes, in the wording a user reads rather than the wire
# vocabulary. Only p-image and FLUX.2 pro accept any of these; every other
# model in the lineup exposes no filter control at all and the box disables.
FILTER_LABELS: dict[str, str] = {
    "default": "Provider default",
    "permissive": "Most permissive",
    "off": "Off (as far as the model allows)",
}

# Length-advice levels mapped to label styles. "near" is a warning
# rather than a danger: being close to a model's prompt budget is a
# note, not a fault.
_LEVEL_STYLE = {
    "ok":   "secondary.TLabel",
    "near": "warning.TLabel",
    "over": "danger.TLabel",
}

# The dropdown lists usage *modes*, not just services: Pollinations behaves
# very differently with and without a key (keyless is capped at one queued
# request per IP), so making that an explicit choice is clearer than a hidden
# behaviour change when a key happens to be present.
PROVIDERS = [
    ("cloudflare", "Cloudflare Workers AI"),
    ("pollinations", "Pollinations — no key needed"),
    ("pollinations_keyed", "Pollinations — with API key"),
]

# Modes that map onto the same underlying provider implementation.
PROVIDER_BACKEND = {
    "cloudflare": "cloudflare",
    "pollinations": "pollinations",
    "pollinations_keyed": "pollinations",
}

# NO MODULE-LEVEL TIER LABELS. They used to live here as one hardcoded
# sentence per tier, written when the lineup was five Cloudflare-native models
# ("High — biggest; klein models only, and ~64% slower"). That is now wrong or
# irrelevant for most of the lineup, and on nano-banana-2 it was actively
# dangerous: it described a SIZE while the control was changing the PRICE by
# up to 2.3x. Labels are now built per model by M.tier_description(), which
# derives them from the registry -- so a model whose pricing shape changes
# updates its own dropdown without an edit here.


class ProviderTab:
    def __init__(self, notebook, app):
        self.app = app
        self.cfg = app.config
        # True only while _set_param_entry is writing a placeholder into a
        # parameter box, so the var traces can tell "the program is showing
        # what this model uses" apart from "the user typed something".
        self._placeholding = False
        self._build(notebook)
        self._sync_model_list()
        self.recalculate()

    # ------------------------------------------------------------------ #

    def _build(self, notebook) -> None:
        # This tab has more sections than fit at the minimum window height, so
        # it scrolls; the scrollbar only appears when it is actually needed.
        tab = make_scrollable(notebook, "  Provider  ")
        tab.columnconfigure(0, weight=1)

        self._build_model(tab, row=0)
        self._build_credentials(tab, row=1)
        self._build_size(tab, row=2)
        self._build_calculator(tab, row=3)
        self._build_generation(tab, row=4)
        self._build_reference(tab, row=5)
        self._build_politeness(tab, row=6)

    # -- provider + model ------------------------------------------------

    def _build_model(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Provider & Model", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 5))
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Provider:").grid(row=0, column=0, sticky="w",
                                            padx=(0, 8), pady=3)
        self.provider_var = tk.StringVar(
            value=_label_for(self.cfg.get("provider", "cloudflare")))
        pc = ttk.Combobox(f, textvariable=self.provider_var, state="readonly",
                          values=[lbl for _, lbl in PROVIDERS], width=32)
        pc.grid(row=0, column=1, sticky="w", pady=3)
        pc.bind("<<ComboboxSelected>>", self._on_provider_changed)
        tip(pc, text="Cloudflare Workers AI is the main provider - its "
                     "three Stable Diffusion models are free. Pollinations "
                     "needs no key at all but is slower and may watermark.")

        self.provider_note = ttk.Label(f, text="", style="secondary.TLabel",
                                       wraplength=900, justify="left")
        self.provider_note.grid(row=5, column=0, columnspan=3, sticky="w",
                                pady=(2, 0))

        # The link TARGET changes with the model, not just its text: native
        # models bill NEURONS (the Workers AI page) while gateway models bill
        # prepaid CREDIT (the AI Gateway page). Pointing a gateway user at the
        # neuron dashboard -- which this program did until 2026-09-05 -- shows
        # them a quota their batch does not draw on at all. Retargeted in
        # _set_usage_link(), called from recalculate().
        self.usage_link = link = ttk.Label(f, text="",
                         style="secondary.TLabel", cursor="hand2")
        link.configure(foreground=PALETTE["accent_soft"])
        link.grid(row=0, column=2, sticky="e", padx=(8, 0), pady=3)
        self._usage_url = USAGE_DASHBOARD_URL
        link.bind("<Button-1>", lambda e: webbrowser.open(self._usage_url))
        self._usage_tip = tip(link, text="")

        ttk.Label(f, text="Model:").grid(row=1, column=0, sticky="w",
                                         padx=(0, 8), pady=3)
        self.model_var = tk.StringVar()
        # Widened from 44: the cost marker and the format suffix push the
        # longest label ("P-Image (paid, ultra-fast, prompt-enhanced) $ — JPEG")
        # past the old width, and a truncated model name is worse than a wide
        # dropdown.
        # height is in ROWS, not pixels. 15 shows the whole lineup (13 models
        # today) without scrolling, so the paid options at the bottom of the
        # list are seen rather than discovered by dragging.
        #
        # width 60 fits the longest label -- currently the default marker on
        # "SDXL Lightning (default, free, fastest) — JPEG". A truncated model
        # name is worse than a wide dropdown; this has now been widened twice
        # (44 -> 52 -> 60) as labels gained markers, so measure it rather than
        # assuming, via the check in tests/test_engine.py.
        self.model_combo = ttk.Combobox(f, textvariable=self.model_var,
                                        state="readonly", width=60, height=15)
        self.model_combo.grid(row=1, column=1, sticky="w", pady=3)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_changed)
        # Deliberately SHORT. This tooltip previously carried a paragraph for
        # every model in the lineup -- 2958 characters by the time the eighth
        # gateway model landed -- which at the default wraplength measured 984px
        # tall against 816px of usable screen: the last paragraphs were simply
        # unreachable, with nothing to indicate they existed. gui/tooltip.py now
        # widens an oversized tooltip rather than clipping it, but the real fault
        # was the growth pattern: each new model appended its own prose here.
        #
        # Per-model detail now lives in `self.model_note` directly below the
        # dropdown, fed from ModelSpec.price_note -- visible without hovering,
        # and bounded because it describes ONE model rather than all thirteen.
        # Keep this tooltip about how to READ the list, never about a model.
        tip(self.model_combo,
            text="Unmarked models are FREE. $ is within $5 per 1000, "
                 "$$ is up to $50 per 1000, $$$ is above that — a browsing "
                 "guide only; the Cost Calculator below is the real figure "
                 "at your chosen size.\n\n"
                 "The suffix after the dash is the file type the model "
                 "actually returns, which is worth knowing before a batch: "
                 "several of these declare one format and send another.\n\n"
                 "Details of the selected model appear just below this "
                 "dropdown.")

        # Per-model detail, updated on selection. Replaces the paragraph-per-
        # model tooltip described above.
        self.model_note = ttk.Label(f, text="", style="secondary.TLabel",
                                    wraplength=900, justify="left")
        self.model_note.grid(row=2, column=0, columnspan=3, sticky="w",
                             pady=(6, 0))
        autowrap(self.model_note, f)
        reserve_lines(self.model_note, 4, sticky_height=False)

        # Prepaid-credit warning for gateway models. Kept SEPARATE from
        # model_note and styled as a warning because it is a prerequisite, not
        # a description: without credit loaded these models cannot run at all.
        # It used to appear only in the Cost Calculator's note further down the
        # tab, which meant a user could configure an entire batch and discover
        # at run time that it could never have started.
        self.credit_note = ttk.Label(f, text="", style="warning.TLabel",
                                     wraplength=900, justify="left",
                                     cursor="hand2")
        self.credit_note.grid(row=3, column=0, columnspan=3, sticky="w",
                              pady=(4, 0))
        self.credit_note.bind(
            "<Button-1>", lambda e: webbrowser.open(CREDITS_DASHBOARD_URL))
        autowrap(self.credit_note, f)
        reserve_lines(self.credit_note, 3, sticky_height=False)

        # NO LICENCE LABEL. Removed 2026-09-05: it stated that outputs are the
        # user's to use commercially, which is what a user already assumes of
        # an image they generated -- so it spent a permanent row reassuring
        # nobody. The per-model licence text stays in ModelSpec.licence for the
        # docs, which is where anyone who actually needs it will look.
        autowrap(self.provider_note, f)
        reserve_lines(self.provider_note, 1)

    # -- credentials -----------------------------------------------------

    def _build_credentials(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="API Keys", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(1, weight=1)

        intro = ttk.Label(
            f,
            text="Paste your keys here and press Save. They are kept in "
                 "credentials.json next to this program, and are never "
                 "written into your settings, the job database, or an output "
                 "folder. Cloudflare needs both boxes; Pollinations works "
                 "with no key at all.",
            style="secondary.TLabel", wraplength=900, justify="left")
        intro.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        autowrap(intro, f)

        self.cred_vars = {}
        self.cred_entries = {}
        self.cred_source = {}

        saved = load_credentials()
        for i, field in enumerate(FIELDS, start=1):
            key = field["key"]
            ttk.Label(f, text=field["label"] + ":").grid(
                row=i, column=0, sticky="w", padx=(0, 8), pady=3)

            var = tk.StringVar(value=saved.get(key, ""))
            entry = ttk.Entry(f, textvariable=var,
                              show="*" if field["secret"] else "")
            entry.grid(row=i, column=1, sticky="ew", pady=3)
            self.app.attach_context_menu(entry)
            tip(entry, text=field["help"])

            self.cred_vars[key] = var
            self.cred_entries[key] = entry

            side = ttk.Frame(f, style="Surface.TFrame")
            side.grid(row=i, column=2, sticky="w", padx=(8, 0), pady=3)

            src = ttk.Label(side, text="", style="secondary.TLabel")
            src.pack(side="left")
            self.cred_source[key] = src

            if field.get("url"):
                get = ttk.Label(side, text="  Get key \u2197",
                                style="secondary.TLabel", cursor="hand2")
                get.configure(foreground=PALETTE["accent_soft"])
                get.pack(side="left")
                get.bind("<Button-1>",
                         lambda e, u=field["url"]: webbrowser.open(u))
                tip(get, text="Open the page where you create this key.")

        self.show_keys_var = tk.BooleanVar(value=False)
        show = ttk.Checkbutton(f, text="Show keys",
                               variable=self.show_keys_var,
                               command=self._toggle_key_visibility)
        show.grid(row=len(FIELDS) + 1, column=0, columnspan=2, sticky="w",
                  pady=(8, 0))
        tip(show, text="Reveal the key text so you can check what you pasted.")

        btns = ttk.Frame(f, style="Surface.TFrame")
        btns.grid(row=len(FIELDS) + 1, column=2, sticky="e", padx=(8, 0),
                  pady=(8, 0))

        save_btn = ttk.Button(btns, text="Save Keys", width=13,
                              style="primary.TButton", command=self._save_creds)
        save_btn.pack(side="left", padx=2)
        tip(save_btn, text="Save these keys so the program remembers them "
                           "next time. No restart needed.")

        self.chk_btn = ttk.Button(btns, text="Check Credentials", width=19,
                                  style="secondary.TButton",
                                  command=self._check_creds)
        self.chk_btn.pack(side="left", padx=2)
        tip(self.chk_btn, text="Contact the provider and confirm the key "
                               "works right now.")

        self.creds_label = ttk.Label(f, text="", style="secondary.TLabel",
                                     wraplength=900, justify="left")
        self.creds_label.grid(row=len(FIELDS) + 2, column=0, columnspan=3,
                              sticky="w", pady=(8, 0))
        autowrap(self.creds_label, f)
        reserve_lines(self.creds_label, 2)

        self._refresh_cred_sources()

    def _toggle_key_visibility(self) -> None:
        shown = self.show_keys_var.get()
        for key, entry in self.cred_entries.items():
            if FIELDS_BY_KEY[key]["secret"]:
                entry.configure(show="" if shown else "*")

    def _refresh_cred_sources(self) -> None:
        """Label each key with where its value is actually coming from."""
        for key, label in self.cred_source.items():
            _value, source = effective_value(key)
            if source == "saved":
                label.configure(text="saved", style="success.TLabel")
            elif source == "environment":
                # Still supported, just no longer the advertised route.
                label.configure(text="from environment variable",
                                style="success.TLabel")
            else:
                label.configure(text="not set yet",
                                style="secondary.TLabel")

    def _save_creds(self) -> None:
        values = {k: v.get() for k, v in self.cred_vars.items()}
        ok, msg = save_credentials(values)
        if ok:
            # Publish immediately so the next request uses the new key. Not
            # needing a restart is the entire point of storing them here.
            for key, value in values.items():
                if value.strip():
                    os.environ[key] = value.strip()
            self.creds_label.configure(
                text="Keys saved - no restart needed. " + msg,
                style="success.TLabel")
            self.app.log("API keys saved (" + msg + ")")
        else:
            self.creds_label.configure(text=msg, style="danger.TLabel")
        self._refresh_cred_sources()

    def _sync_model_list(self) -> None:
        mode = _key_for(self.provider_var.get())
        specs = M.models_for_provider(PROVIDER_BACKEND[mode])
        self._model_labels = {self._label(s): s.key for s in specs}
        self.model_combo.configure(values=list(self._model_labels.keys()))

        want = self.cfg.get("model", M.DEFAULT_MODEL)
        for label, key in self._model_labels.items():
            if key == want:
                self.model_var.set(label)
                break
        else:
            first = next(iter(self._model_labels), "")
            self.model_var.set(first)
            if first:
                self.app.set_cfg("model", self._model_labels[first])

    @staticmethod
    def _label(spec: M.ModelSpec) -> str:
        """Model name, relative cost marker, and the format it actually returns.

        The format matters when choosing a model and there is no other way to
        discover it -- the content-type header is wrong for several of these.

        The $/$$/$$$ marker makes relative cost visible while BROWSING, rather
        than only after selecting a model and reading the calculator. It is
        computed at a fixed reference size so it never flickers as the tier
        changes; the calculator below remains the accurate number.
        """
        fmt = {"jpg": "JPEG", "png": "PNG"}.get(spec.output_format,
                                                spec.output_format.upper())
        marker = M.cost_tier_marker(spec.key)
        cost = f" {marker}" if marker else ""
        # Marking the default IN the list beats explaining it in the tooltip:
        # it is visible while browsing, which is exactly when it is useful.
        # Folded INSIDE the label's existing parenthetical rather than appended
        # as a second one -- "(free, fastest) (default)" reads as two competing
        # asides where "(default, free, fastest)" reads as one description.
        label = spec.label
        if spec.key == M.DEFAULT_MODEL:
            label = (f"{label[:label.index('(') + 1]}default, "
                     f"{label[label.index('(') + 1:]}" if "(" in label
                     else f"{label} (default)")
        return f"{label}{cost} — {fmt}"

    def _set_combo_availability(self, combo, var, *, enabled: bool,
                                enabled_value: str, disabled_text: str) -> None:
        """Enable a combo, or grey it out with a reason in place of a value.

        A disabled ttk.Combobox still LOOKS clickable, so leaving the previous
        selection visible invites a click that does nothing. Showing the reason
        instead makes the state self-explanatory.

        The disabled text is never a valid mode label, and the readback helpers
        fall through to the program default on an unrecognised label, so this
        cannot leak into config even if something later reads it.
        """
        if enabled:
            combo.configure(state="readonly")
            if var.get() != enabled_value:
                var.set(enabled_value)
        else:
            # Must be writable to change the text, then re-disabled.
            combo.configure(state="normal")
            var.set(disabled_text)
            combo.configure(state="disabled")

    def _selected_expansion(self) -> str:
        label = self.expansion_combo.get()
        for mode, text in EXPANSION_LABELS.items():
            if text == label:
                return mode
        return M.DEFAULT_PROMPT_EXPANSION

    def _selected_filter(self) -> str:
        label = self.filter_var.get()
        for mode, text in FILTER_LABELS.items():
            if text == label:
                return mode
        return M.DEFAULT_CONTENT_FILTER

    def _current_model_key(self) -> str:
        return self._model_labels.get(self.model_var.get(),
                                      self.cfg.get("model", M.DEFAULT_MODEL))

    def _on_provider_changed(self, _evt=None) -> None:
        self.app.set_cfg("provider", _key_for(self.provider_var.get()))
        self._sync_model_list()
        self._on_model_changed()

    def _on_model_changed(self, _evt=None) -> None:
        self.app.set_cfg("model", self._current_model_key())
        self.recalculate()

    def _check_creds(self) -> None:
        """Verify credentials off the main thread.

        This makes a network call and shells out to read a Windows user
        variable. Doing that on the main thread froze the UI, and the
        update_idletasks() used to force the "Checking..." text through re-ran
        layout mid-update, which is what made the whole tab visibly scrunch.
        """
        mode = _key_for(self.provider_var.get())
        provider = PROVIDER_BACKEND[mode]
        self.chk_btn.configure(state="disabled")
        self.creds_label.configure(text="Checking…",
                                   style="secondary.TLabel")

        def work():
            ok, msg = self.app._check_credentials(provider)
            self.app.root.after(0, lambda: done(ok, msg))

        def done(ok, msg):
            self.chk_btn.configure(state="normal")
            self.creds_label.configure(
                text=("OK — " if ok else "Not ready — ") + msg,
                style="success.TLabel" if ok else "danger.TLabel",
            )
            self.app.log(
                ("Credentials OK: " if ok else "Credentials problem: ") + msg)
            self._refresh_cred_sources()

        threading.Thread(target=work, daemon=True).start()

    # -- size ------------------------------------------------------------

    def _build_size(self, parent, row: int) -> None:
        """Image size controls.

        LAYOUT NOTE: every column here is pinned to a fixed minimum width and
        the labels are fixed-width too. Left to size themselves, the grid
        re-flowed on every selection -- picking 16:9 instead of 3:2 nudged the
        dropdowns sideways, and a longer size readout or a tier warning shoved
        them further. Nothing in this frame may be allowed to depend on the
        width of its own text.
        """
        f = _tk_ttk.LabelFrame(parent, text="Image Size", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)

        # col 0 captions, col 1 controls, col 2 readout, col 3 soaks up slack.
        f.columnconfigure(0, minsize=120, weight=0)
        f.columnconfigure(1, minsize=330, weight=0)
        f.columnconfigure(2, minsize=250, weight=0)
        f.columnconfigure(3, weight=1)

        ttk.Label(f, text="Aspect ratio:").grid(row=0, column=0, sticky="w",
                                                padx=(0, 8), pady=3)
        self.ratio_var = tk.StringVar(value=self.cfg.get("ratio", M.DEFAULT_RATIO))
        rc = ttk.Combobox(f, textvariable=self.ratio_var, state="readonly",
                          values=list(M.RATIOS), width=10)
        rc.grid(row=0, column=1, sticky="w", pady=3)
        rc.bind("<<ComboboxSelected>>", self._on_size_changed)
        tip(rc, text="16:9 suits game backgrounds. Square (1:1) is "
                     "cheapest on paid models — it packs into fewer "
                     "billing tiles.")

        # THE ANSWER TO "what am I actually getting", so it is rendered as a
        # figure rather than as another line of body text. It used to sit
        # inline beside the ratio dropdown at body size, competing with the
        # captions for attention while being the one value on this panel the
        # user is actually looking for.
        #
        # Split in two: the pixel dimensions large, the derived detail (tiles,
        # megapixels) small underneath. The pair spans both control rows so it
        # reads as the RESULT of the two dropdowns beside it rather than as a
        # third setting.
        size_box = ttk.Frame(f, style="Surface.TFrame")
        size_box.grid(row=0, column=2, rowspan=2, columnspan=2, sticky="w",
                      padx=(16, 0), pady=3)

        # Fixed width and a left anchor: the text changes length constantly
        # (768 x 432 vs 1792 x 1008) and must not move its neighbours.
        self.size_label = ttk.Label(size_box, text="", style="Figure.TLabel",
                                    width=16, anchor="w")
        self.size_label.grid(row=0, column=0, sticky="w")

        # Tiles and megapixels: real information, but secondary to the pixels
        # and suppressed entirely on the flat-priced models where a tile count
        # is a meaningless number.
        self.size_detail = ttk.Label(size_box, text="",
                                     style="secondary.TLabel",
                                     font=FONT_SMALL, width=32, anchor="w")
        self.size_detail.grid(row=1, column=0, sticky="w")

        # "Size / quality tier", not "Quality tier": it picks a RESOLUTION,
        # and on one model a price. "Quality" alone implies a fidelity knob --
        # something that makes the same image better -- which is not what it is.
        ttk.Label(f, text="Size / quality tier:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.tier_var = tk.StringVar(value=self.cfg.get("tier", M.DEFAULT_TIER))
        # Width 70 holds the longest per-model label, which now carries a size
        # and (on the price-lever models) a price. MEASURED across every
        # model x tier x ratio, not eyeballed -- and pinned by a test, because
        # the labels are generated and so can grow without anyone noticing.
        self.tier_combo = ttk.Combobox(
            f, textvariable=self.tier_var, state="readonly", width=70)
        self.tier_combo.grid(row=1, column=1, sticky="w", pady=3)
        self.tier_combo.bind("<<ComboboxSelected>>", self._on_size_changed)
        # The SELECTED TIER is tracked here, not read back out of the label.
        # The labels change with the model, so a reverse lookup on the visible
        # text would break the moment the list was rebuilt under a selection.
        self._tier = self.cfg.get("tier", M.DEFAULT_TIER)
        if self._tier not in M.TIERS:
            self._tier = M.DEFAULT_TIER
        tip(self.tier_combo,
            text="How big each image is. The sizes are chosen to be the "
                 "largest that fit each price bracket, so Standard gives you "
                 "considerably more pixels than the obvious round number "
                 "would, at no extra cost.\n\n"
                 "What this changes depends on the model, and the options "
                 "above say which: on most models it changes only the size, "
                 "on the free models the speed too, and on Nano Banana 2 it "
                 "changes what you PAY — up to about 2.3x between Draft and "
                 "High.\n\n"
                 "Several models render at one fixed size and ignore this "
                 "entirely; on those the control is disabled and the reason "
                 "is given below.")

        ttk.Label(f, text="Save images as:").grid(row=2, column=0, sticky="w",
                                                  padx=(0, 8), pady=3)
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(
            f, textvariable=self.format_var, state="readonly",
            values=list(CONVERT_FORMATS.values()), width=44)
        self.format_combo.grid(row=2, column=1, sticky="w", pady=3)
        current = self.cfg.get("output_format", "keep")
        self.format_combo.set(CONVERT_FORMATS.get(current,
                                                  CONVERT_FORMATS["keep"]))
        self.format_combo.bind("<<ComboboxSelected>>", self._on_format_changed)
        tip(self.format_combo,
            text="Providers offer no file-type option and are not honest "
                 "about what they send, so this converts the image on your "
                 "own machine after downloading.\n\n"
                 "'Keep original' saves exactly what arrived and is always "
                 "the best quality.\n\n"
                 "Converting cannot improve an image. Turning a JPEG into a "
                 "PNG reproduces the JPEG's pixels exactly - measured "
                 "identical - in a file about 8x larger, because PNG stores "
                 "the already-discarded detail losslessly rather than "
                 "restoring it. Choose a format for what you need to DO with "
                 "the files, never for quality.")

        # States what this model actually delivers. Without it the format
        # choice is guesswork: the content-type header cannot be trusted, so
        # there is no other way for anyone to know.
        self.format_native = ttk.Label(f, text="", style="secondary.TLabel",
                                       wraplength=900, justify="left")
        self.format_native.grid(row=3, column=0, columnspan=4, sticky="w",
                                pady=(2, 0))
        autowrap(self.format_native, f)
        reserve_lines(self.format_native, 2, sticky_height=False)

        self.size_warning = ttk.Label(f, text="", style="warning.TLabel",
                                      wraplength=900, justify="left")
        self.size_warning.grid(row=4, column=0, columnspan=4, sticky="w",
                               pady=(6, 0))
        autowrap(self.size_warning, f)
        # Four lines is the CEILING, not a permanent reservation: the row grows
        # to fit whatever is shown (the longest case is the klein High-tier
        # text -- the size-substitution note plus the "64% slower" note, which
        # wraps to four lines at the default width) and collapses entirely when
        # there is no warning, which is most of the time.
        reserve_lines(self.size_warning, 4, sticky_height=False)

    def _on_format_changed(self, _evt=None) -> None:
        label = self.format_combo.get()
        for key, text in CONVERT_FORMATS.items():
            if text == label:
                self.app.set_cfg("output_format", key)
                break
        self.recalculate()

    def _selected_tier(self) -> str:
        """The chosen tier, by POSITION rather than by label text.

        The labels are rebuilt per model, so matching the visible string back
        to a tier would fail exactly when the model changes -- silently
        resetting the user's tier to the default. The index is stable because
        the dropdown always lists M.TIERS in order.
        """
        idx = self.tier_combo.current()
        if 0 <= idx < len(M.TIERS):
            return M.TIERS[idx]
        return self._tier

    def _sync_tier_labels(self, model_key: str, ratio: str) -> None:
        """Re-label the tier dropdown for the selected model, keeping the tier."""
        self.tier_combo.configure(
            values=[M.tier_description(model_key, t, ratio) for t in M.TIERS])
        self.tier_combo.current(M.TIERS.index(self._tier))

    def _on_size_changed(self, _evt=None) -> None:
        self._tier = self._selected_tier()
        self.app.set_cfg("ratio", self.ratio_var.get())
        self.app.set_cfg("tier", self._tier)
        self.recalculate()

    # -- the live calculator ---------------------------------------------

    def _build_calculator(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Cost Calculator", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        for c in range(4):
            f.columnconfigure(c, weight=1, uniform="calc")

        self.figures: dict[str, ttk.Label] = {}
        cells = [
            ("per_image", "Per image"),
            ("per_1000", "Per 1000 images"),
            ("this_batch", "This batch"),
            ("per_day", "Free images per day"),
        ]
        for col, (key, caption) in enumerate(cells):
            box = ttk.Frame(f, style="Surface.TFrame")
            box.grid(row=0, column=col, sticky="ew", padx=4)
            box.columnconfigure(0, weight=1)
            val = ttk.Label(box, text="—", style="Figure.TLabel", anchor="center")
            val.grid(row=0, column=0, sticky="ew")
            ttk.Label(box, text=caption, style="secondary.TLabel",
                      anchor="center").grid(row=1, column=0, sticky="ew")
            self.figures[key] = val

        self.calc_note = ttk.Label(f, text="", style="secondary.TLabel",
                                   wraplength=980, justify="left")
        self.calc_note.grid(row=1, column=0, columnspan=4, sticky="w",
                            pady=(10, 0))
        autowrap(self.calc_note, f)
        reserve_lines(self.calc_note, 3, sticky_height=False)

        self.budget_label = ttk.Label(f, text="", style="danger.TLabel",
                                      wraplength=980, justify="left")
        self.budget_label.grid(row=2, column=0, columnspan=4, sticky="w",
                               pady=(4, 0))
        autowrap(self.budget_label, f)
        reserve_lines(self.budget_label, 2, sticky_height=False)

    def recalculate(self) -> None:
        """Refresh every derived figure. Cheap and pure — call it freely."""
        model_key = self._current_model_key()
        if not model_key:
            return
        spec = M.get_model(model_key)
        ratio = self.ratio_var.get()
        tier = self._selected_tier()

        # Re-label the tier dropdown for THIS model before anything reads it:
        # the options carry the model's own sizes, and on nano-banana-2 its
        # prices. Done here rather than only on model change so that switching
        # the RATIO updates the sizes shown in the options too.
        self._sync_tier_labels(model_key, ratio)

        width, height = M.size_for(ratio, tier, model_key)
        n = self._prompt_count()
        est = M.estimate(model_key, width, height, max(n, 1))

        # Size readout, plus a note when the tier size was substituted.
        # Compare against whichever table is authoritative FOR THIS MODEL.
        # p-image has its own table (it caps at 1440 and needs multiples of
        # 16), so measuring "was this substituted?" against the shared table
        # would flag every one of its sizes as a substitution.
        override = M.SIZE_TABLE_OVERRIDES.get(model_key)
        tabled = (override[ratio][tier] if override is not None
                  else M.SIZES[ratio][tier])
        substituted = (width, height) != tabled
        # Tiles are Cloudflare's NATIVE billing unit. Gateway models bill a
        # flat price per image, so a tile count beside one is a meaningless
        # number that implies headroom ("generate large, downscale locally")
        # which does not exist there. Show megapixels only.
        # Tiles are shown only where they are a BILLING fact the user can act
        # on -- a paid, tile-priced model, where a size inside the same tile
        # count is free headroom. On a free model the count is arithmetic with
        # no consequence, and on a flat-priced one it implies headroom that
        # does not exist; both used to print it because bills_per_tile
        # defaults True and free models never overrode it.
        if est.bills_per_tile and not est.is_free:
            size_text = f"{width} x {height}"
            size_detail = f"{est.tiles} billing tiles · {est.megapixels:.2f} MP"
        elif spec.size_style == "aspect_ratio_resolution" and not spec.sizes_published:
            # Krea does not publish the pixel dimensions "1K" resolves to, and
            # it cannot be probed without spending. The program never SENDS
            # these numbers (the model takes a ratio enum), so being wrong here
            # cannot break a request — but presenting a guess as fact would be
            # dishonest, and the true size is recorded from the returned image.
            #
            # Keyed on sizes_published, NOT on size_style. This branch was
            # written for krea and then keyed on the style it happened to use,
            # which made it wrong the moment a second model shared that style:
            # nano-banana speaks the identical aspect_ratio+resolution
            # vocabulary but Google DOES publish its exact dimensions, so
            # marking those "~ estimated" would be the mirror-image dishonesty
            # already avoided for Recraft. The question is "are these numbers
            # a guess?", so that is what the flag asks.
            size_text = f"~{width} x {height}"
            size_detail = f"~{est.megapixels:.2f} MP — estimated, not published"
        else:
            size_text = f"{width} x {height}"
            size_detail = f"{est.megapixels:.2f} MP"
        self.size_label.configure(text=size_text)
        self.size_detail.configure(text=size_detail)

        # Warnings, graded by severity. The registry's max_safe_dimension is a
        # single 1024px threshold covering a range of outcomes: at High (2048px)
        # SD models genuinely fall apart, but at Standard (1536px) they are fine
        # -- measured 2026-08-31, lightning at 1536x864 produced a coherent
        # scene with no duplicated structures or geometry drift (out/sizecheck/).
        # Showing the same alarming text for both would teach users to ignore
        # it, so a modest overshoot is phrased as a note, not a warning.
        msgs: list[str] = []
        style = "warning.TLabel"
        if est.errors:
            msgs.extend(est.errors)
            style = "danger.TLabel"
        elif est.warnings:
            longest = max(width, height)
            if longest > spec.max_safe_dimension * 1.75:
                msgs.extend(est.warnings)
            else:
                msgs.append(
                    f"{longest}px is above {spec.short_name}'s trained size "
                    f"of {spec.max_safe_dimension}px. In testing this tier "
                    f"still looks good; the klein models handle it natively "
                    f"and are free for the first several dozen images a day, "
                    f"so try one if you see repeated shapes or drifting "
                    f"geometry."
                )
                style = "secondary.TLabel"
        if substituted and not est.errors:
            msgs.append(
                f"High tier resized to {width}x{height} — {spec.short_name} tops out "
                f"at {spec.max_dimension}px, so the tabled "
                f"{tabled[0]}x{tabled[1]} would be rejected."
            )
        # A tier dropdown that silently does nothing reads as a bug rather
        # than a model limitation, so say which it is. Two distinct cases:
        # krea has NO ladder at all (locked to 1K), while p-image has one that
        # collapses for some ratios because its 1440 cap and the x16 rule bite.
        if not M.has_tier_ladder(model_key):
            self.tier_combo.configure(state="disabled")
            # THREE models reach here for THREE different reasons, and the
            # text has to say which — printing one model's reason for another
            # is a plausible-sounding lie, which is exactly what this line did
            # before Recraft was added and again before nano-banana was.
            #
            #   krea         genuinely locked to resolution="1K"; the API
            #                validator accepts no other value
            #   Recraft      one fixed published size per ratio, in an opaque
            #                enum — no resolution concept at all
            #   nano-banana  the API DECLARES 1K/2K/4K, and the program pins
            #                it to 1K by choice. A different statement, and
            #                the user is owed the real one.
            if spec.key in M.NANO_BANANA_TIER_RESOLUTION:
                # Phrased as the program's CHOICE, because it is one. Saying
                # "it is locked to 1K" here would be the same lie this branch
                # exists to prevent: the API declares 2K and 4K, and it is
                # this program that declines to send them.
                why = ("this program pins it to 1K, since Google publishes no "
                       "2K or 4K price for the Lite model and a batch whose "
                       "cost cannot be quoted is worse than a smaller one")
            elif spec.size_style == "aspect_ratio_resolution":
                why = "it is locked to 1K resolution"
            else:
                why = ("its size is a fixed published value, not a dimension "
                       "you can choose")
            msgs.append(
                f"{spec.short_name} renders at ONE size per ratio ({width}x{height} "
                f"here): {why}. The quality tier therefore has no effect and "
                f"is disabled. Note this is smaller than the other models' "
                f"Standard tier ({M.SIZES[ratio]['standard'][0]}x"
                f"{M.SIZES[ratio]['standard'][1]}), and every image costs the "
                f"same regardless — fewer pixels, same cost."
            )
        else:
            self.tier_combo.configure(state="readonly")
            if (not est.bills_per_tile
                    and tier in ("standard", "high")
                    and not est.errors
                    and M.size_for(ratio, "standard", model_key)
                    == M.size_for(ratio, "high", model_key)):
                msgs.append(
                    f"Standard and High are the same size ({width}x{height}) "
                    f"for this ratio on {spec.short_name} — it caps at "
                    f"{spec.max_dimension}px and requires multiples of 16, and "
                    f"the price is flat per image regardless, so there is "
                    f"nothing to gain from the higher tier here."
                )
        if (tier == "high" and est.bills_per_tile
                and not est.errors and not est.warnings):
            msgs.append(
                "High tier is roughly 64% slower per image than Standard "
                "(measured 16.1s vs 9.8s on klein-4b). On a large overnight "
                "batch that matters more than the price does."
            )
        self.size_warning.configure(text="  ".join(msgs), style=style)

        mode = _key_for(self.provider_var.get())
        if mode == "pollinations":
            self.provider_note.configure(
                text="Pollinations accepts only ONE request at a time per IP "
                     "address, and without a key it also waits 15 seconds "
                     "between them. Fine for a handful of images; slow for a "
                     "large batch. A key shortens the gap but not the "
                     "one-at-a-time limit.",
                style="warning.TLabel")
        elif mode == "pollinations_keyed":
            self.provider_note.configure(
                text="A key raises your quota and shortens the gap between "
                     "requests, but Pollinations still accepts only ONE "
                     "request at a time per IP address (measured), so images "
                     "are generated one after another either way.",
                style="secondary.TLabel")
        else:
            self.provider_note.configure(text="", style="secondary.TLabel")

        # The usage link goes to a Cloudflare dashboard; it is meaningless
        # while another provider is selected.
        if mode == "cloudflare":
            self.usage_link.grid()
            self._set_usage_link(spec)
        else:
            self.usage_link.grid_remove()

        self._set_model_notes(spec, est)

        # Say what this model delivers, and flag a conversion that gains
        # nothing. The content-type header lies, so this registry value
        # (measured per model) is the only honest source.
        native = spec.output_format
        chosen = self.cfg.get("output_format", "keep")
        native_name = {"jpg": "JPEG", "png": "PNG"}.get(native, native.upper())

        if chosen in ("keep", "", "original"):
            self.format_native.configure(
                text=f"This model returns {native_name}. Files will be saved "
                     f"as {native_name}, exactly as received.",
                style="secondary.TLabel")
        elif chosen == native or (chosen == "jpg" and native == "jpg"):
            self.format_native.configure(
                text=f"This model already returns {native_name}, so no "
                     f"conversion happens.",
                style="secondary.TLabel")
        elif native == "jpg" and chosen == "png":
            self.format_native.configure(
                text=f"This model returns JPEG. Saving as PNG stores those "
                     f"exact pixels in a file roughly 8x larger — it cannot "
                     f"recover detail the JPEG already discarded.",
                style="warning.TLabel")
        elif native == "png" and chosen == "jpg":
            self.format_native.configure(
                text="This model returns PNG (lossless). Saving as JPEG makes "
                     "much smaller files but discards some detail permanently.",
                style="warning.TLabel")
        else:
            self.format_native.configure(
                text=f"This model returns {native_name}; images will be "
                     f"converted to {chosen.upper()} after downloading.",
                style="secondary.TLabel")

        # The four figures, coloured by the SAME band as the note below them
        # so the panel does not grade the same price two different ways.
        # FigureOver is reserved for the top two bands: applying it at $5.01,
        # as the old over_budget flag did, made a mild cost look like an alarm.
        _band = M.cost_band_for_price(est.cost_per_1000)
        fig_style = ("FigureOver.TLabel" if _band in ("high", "extreme")
                     else "FigureFree.TLabel" if est.is_free
                     else "Figure.TLabel")

        if est.is_free:
            self.figures["per_image"].configure(text="Free", style=fig_style)
            self.figures["per_1000"].configure(text="Free", style=fig_style)
            self.figures["this_batch"].configure(text="Free", style=fig_style)
            self.figures["per_day"].configure(text="No cap", style=fig_style)
        else:
            self.figures["per_image"].configure(
                text=f"${est.cost_per_image:.5f}", style=fig_style)
            self.figures["per_1000"].configure(
                text=f"${est.cost_per_1000:.2f}", style=fig_style)
            self.figures["this_batch"].configure(
                text=f"${est.total_cost:.4f}" if n else "—", style=fig_style)
            per_day = est.free_images_per_day
            # None means two different things: a free model (no cost at all)
            # or a gateway model, which is paid but drawn from prepaid credit
            # rather than the daily neuron allowance. Only the latter reaches
            # this branch, so "n/a" is the honest reading -- not "0", which
            # would imply the allowance was spent.
            self.figures["per_day"].configure(
                text=str(per_day) if per_day is not None else "n/a",
                style=fig_style)

        note = [spec.price_note]
        if n:
            note.append(f"{n} prompt(s) currently loaded.")
        else:
            note.append("Load a prompt file to see the batch total.")
        if not est.is_free:
            per_day = est.free_images_per_day
            if per_day is None and not est.bills_per_tile:
                note.append(
                    "This model is billed from PREPAID CREDIT in your "
                    "Cloudflare account, not from the free daily neuron "
                    "allowance — so there is no free quota to use up first, "
                    "and every image costs from the first one. Add credit in "
                    "the Cloudflare dashboard before running a batch."
                )
            if per_day is not None:
                note.append(
                    f"Cloudflare's free tier includes 10,000 neurons/day, "
                    f"resetting at 00:00 UTC — at this size that's roughly "
                    f"{per_day} images/day at NO extra cost, before this "
                    f"price applies at all. The {per_day} figure is a "
                    f"measured rate from Cloudflare's own usage API, not a "
                    f"guess."
                )
        self.calc_note.configure(text=" ".join(note))

        # COST BAND, not "over budget". The old wording said a price
        # "exceeds the $5.00 ceiling for this project" -- which describes this
        # project's internal budget policy, something the user has never heard
        # of and cannot act on, and which was binary besides: $5.01 and $151
        # got the identical sentence.
        #
        # Graded on the price of the size ACTUALLY SELECTED, not on the
        # dropdown's fixed reference size, because that is the price the user
        # is about to pay -- on nano-banana-2 the tier moves it across bands.
        band = M.cost_band_for_price(est.cost_per_1000)
        if band in ("free", "low"):
            # Nothing to warn about. LOW COST is already stated by the
            # dropdown marker and the model note; repeating it here as a
            # warning would train users to ignore the line that matters.
            self.budget_label.configure(text="")
        else:
            label = M.COST_BAND_LABELS[band]
            batch = (f"This batch of {n} image(s): ${est.total_cost:,.2f}."
                     if n else
                     f"Load a prompt file to see what a batch would cost.")
            if band == "extreme":
                # Leads with the BATCH TOTAL rather than the per-1000 rate:
                # "$151 per 1000" reads as abstract where "this batch costs
                # $75.50" does not, and the total is the number that lands on
                # the card. Naming the count keeps a small total visibly small
                # because the batch is small, not because the model is cheap.
                detail = ("Intended for occasional single images rather than "
                          "batch work — check the total before you start.")
            elif band == "high":
                detail = ("Fine for a small batch; check the total before "
                          "running a large one.")
            else:
                detail = "Reasonable for a batch, but it is not free."
            self.budget_label.configure(
                text=f"{label} — ${est.cost_per_1000:,.2f} per 1000 images. "
                     f"{batch} {detail}",
                style=M.COST_BAND_STYLES[band])


        # Prompt expansion applies only to models that rewrite the prompt, and
        # the content filter is adjustable on exactly two. Disabling the combo
        # elsewhere is the honest presentation -- but a GREYED COMBO STILL
        # SHOWING A VALUE reads as a control the user may click, and it then
        # does nothing. Reported as confusing 2026-09-06.
        #
        # Same lesson as the disabled numeric boxes: a disabled control has to
        # show something honest rather than a leftover setting. So the combo
        # displays why it is off, and the real choice is restored the moment a
        # model that supports it is selected.
        #
        # The placeholder is display-only and MUST NOT be persisted -- both
        # readback helpers match on the visible label and fall back to the
        # program default when nothing matches, so the placeholder can never
        # be written to config as a mode. Config is only touched by the user's
        # own <<ComboboxSelected>>, which a disabled combo cannot fire.
        self._set_combo_availability(
            self.expansion_combo, self.expansion_var,
            enabled=spec.supports_prompt_expansion,
            enabled_value=EXPANSION_LABELS.get(
                self.cfg.get("prompt_expansion", M.DEFAULT_PROMPT_EXPANSION),
                EXPANSION_LABELS[M.DEFAULT_PROMPT_EXPANSION]),
            disabled_text="not supported by this model",
        )
        self._set_combo_availability(
            self.filter_combo, self.filter_var,
            enabled=bool(spec.content_filter_field),
            enabled_value=FILTER_LABELS.get(
                self.cfg.get("content_filter", M.DEFAULT_CONTENT_FILTER),
                FILTER_LABELS[M.DEFAULT_CONTENT_FILTER]),
            disabled_text="not adjustable on this model",
        )

        # Seed controls die entirely on a model with no seed field. Guarded
        # because the model combo can fire before the seed widgets exist.
        if hasattr(self, "seed_entry"):
            self._on_seed_mode()

        # Steps and guidance only apply to models that accept them.
        #
        # A disabled ttk.Entry with nothing in it is indistinguishable from an
        # empty one waiting to be filled in -- the greying is subtle and the
        # box is small. So a disabled box states what is actually being used,
        # which turns "why can I not type here?" into a fact.
        self._set_param_entry(
            self.steps_entry, self.steps_var, spec.steps_settable,
            spec.default_steps, self.cfg.get("steps", ""))
        self._set_param_entry(
            self.guidance_entry, self.guidance_var, spec.supports_guidance,
            spec.default_guidance, self.cfg.get("guidance", ""))
        self.negative_text.configure(
            state="normal" if spec.supports_negative_prompt else "disabled")
        self._set_negative_group(spec)
        self.param_note.configure(text=self._param_note(spec))
        # The reference readout depends on the MODEL (whether it is supported
        # at all) and on the SIZE (the ratio note), so it re-renders here
        # rather than only when the file changes.
        self.refresh_reference()

        # A different model is a different prompt budget even when not one
        # character of the text has changed, so both counters re-grade here.
        self.refresh_negative_hint()
        prompts_tab = getattr(self.app, "prompts_tab", None)
        if prompts_tab is not None:
            prompts_tab.refresh_length_hint()

    def _set_usage_link(self, spec: M.ModelSpec) -> None:
        """Point the dashboard link at the pot THIS model is billed from.

        Native and gateway models draw on entirely separate balances, and each
        dashboard page is meaningless for the other family -- so the link text,
        target and tooltip all switch together. Getting this wrong is not a
        cosmetic slip: it sends a user to a page showing plenty of free quota
        while their batch fails for want of credit, or vice versa.
        """
        if spec.call_style == "gateway":
            self._usage_url = CREDITS_DASHBOARD_URL
            self.usage_link.configure(text="Check AI Gateway credits ↗")
            self._usage_tip.text = (
                "This model is billed from PREPAID CREDIT on the AI Gateway "
                "page, not from the free daily neuron allowance — so the "
                "Workers AI usage page will not show it, and there is no free "
                "quota to use up first.\n\n"
                "The same page is where credit is loaded: find the 'Credits "
                "Available' card, then Manage, then Top-up credits. Cloudflare "
                f"adds a {CREDIT_PURCHASE_FEE_PERCENT}% fee on purchases, so "
                f"$100 of credit costs "
                f"${100 * (100 + CREDIT_PURCHASE_FEE_PERCENT) / 100:.0f}.\n\n"
                "You can also set an auto top-up threshold there, which is "
                "worth doing before a large overnight batch — running out "
                "part-way stops the run, though everything finished is kept "
                "and the batch resumes.")
        else:
            self._usage_url = USAGE_DASHBOARD_URL
            self.usage_link.configure(text="Check Workers AI usage ↗")
            self._usage_tip.text = (
                "The three free models (SDXL Lightning, SDXL Base, "
                "DreamShaper) genuinely bill zero neurons, so there is no cap "
                "to check for those.\n\n"
                "For the two klein models, 'free images per day' here is an "
                "ESTIMATE computed by this program from a measured neuron "
                "rate — roughly 75 images/day on klein 4B and 7 on klein 9B "
                "at Standard 16:9, and fewer at a larger size. It is an "
                "estimate, not a live reading: your real usage and remaining "
                "allowance are on this dashboard.")

    def _set_model_notes(self, spec: M.ModelSpec, est) -> None:
        """Per-model detail below the dropdown, and the credit prerequisite.

        `price_note` already carries the per-model prose that used to be
        appended, model by model, to the model combobox's tooltip -- which grew
        to 2958 characters and overflowed the screen. Showing it here is both
        bounded (one model's worth) and visible without hovering.
        """
        # Colour by cost band, from the SAME table the calculator and the
        # dropdown marker use, so the app never grades one price three ways.
        # EXTREME is red rather than amber: at $151 per 1000 the difference
        # between "this costs money" and "this costs a lot of money" is the
        # whole point, and an extreme model reading like a low-cost one is how
        # someone runs a 500-image batch by accident.
        self.model_note.configure(
            text=spec.price_note or "",
            style=M.COST_BAND_STYLES[M.cost_band(spec.key)])

        # A prerequisite, not a description: without credit these models do not
        # run at all, and the failure arrives at request time as an HTTP 402
        # after the batch has already been set up.
        if spec.call_style == "gateway":
            self.credit_note.configure(
                text="NEEDS PREPAID CREDIT — this model is billed from your "
                     "Cloudflare AI Gateway credit balance, not from the free "
                     "daily allowance, so every image costs from the first "
                     "one. Load credit before starting a batch: Cloudflare "
                     "dashboard, AI Gateway, 'Credits Available', Manage, "
                     f"Top-up credits (a {CREDIT_PURCHASE_FEE_PERCENT}% fee "
                     "applies to purchases). Click here to open that page.")
            self.credit_note.grid()
        else:
            self.credit_note.configure(text="")
            self.credit_note.grid_remove()

    def _set_negative_group(self, spec: M.ModelSpec) -> None:
        """Fold the negative-prompt controls away on models that ignore them.

        NOT hiding the feature: the "Negative prompt" group and a line saying
        why it is unavailable stay on screen, so the user can always see that
        the feature exists and learn which models have it. What collapses is
        only the 20-checkbox layer list and the text box -- 431px that is
        otherwise held permanently on 10 of the 13 models, pushing the model
        parameters below the fold for no benefit.

        The user's negative text is untouched throughout; selecting an SD
        model brings the controls back with everything still in them.
        """
        widgets = (self._neg_rows if hasattr(self, "_neg_rows") else ())
        if spec.supports_negative_prompt:
            for w in widgets:
                w.grid()
            self.neg_unsupported.configure(text="")
            self.neg_unsupported.grid_remove()
            return
        for w in widgets:
            w.grid_remove()
        self.neg_unsupported.configure(
            text=f"Not used by {spec.short_name}. Only the three "
                 f"Stable Diffusion models accept a negative prompt; the FLUX "
                 f"and paid models ignore it entirely, so there is nothing to "
                 f"set here. Your saved layers and text are kept.")
        self.neg_unsupported.grid()

    def _set_param_entry(self, entry, var, supported: bool,
                         default, saved) -> None:
        """Enable a parameter box, or disable it and say what is used instead.

        Two distinct disabled cases, and they must not read the same:
          * the model has a KNOWN fixed value (klein's 4 steps)  -> show it
          * the model takes no such parameter at all             -> "n/a"

        What is shown while disabled is a PLACEHOLDER, never a setting. The
        user's own saved value is restored as soon as a model that accepts the
        parameter is selected again, and `_placeholding` keeps the var's trace
        from persisting the placeholder in the meantime -- without it, opening
        a Recraft model would write "n/a" into config.json as the user's step
        count and send it to the next model that does take one.
        """
        self._placeholding = True
        try:
            if supported:
                entry.configure(state="normal")
                if var.get() != str(saved):
                    var.set(str(saved))
            else:
                entry.configure(state="normal")   # writable for this set only
                var.set(str(default) if default is not None else "n/a")
                entry.configure(state="disabled")
        finally:
            self._placeholding = False

    def _param_note(self, spec: M.ModelSpec) -> str:
        bits = []
        if not spec.steps_settable:
            # Two different cases: klein has a KNOWN fixed count (4, distilled),
            # while the gateway models take no steps parameter at all. Printing
            # "a fixed step count of None" for the latter reads as a bug.
            if spec.default_steps is not None:
                bits.append(f"{spec.short_name} has a fixed step count of "
                            f"{spec.default_steps} and cannot be changed — it "
                            f"is a distilled model, built to render in that "
                            f"many steps.")
            else:
                bits.append(f"{spec.short_name} does not expose a step "
                            f"count — the provider chooses it.")
        if not spec.supports_negative_prompt:
            bits.append("This model does not accept a negative prompt.")
        if not spec.supports_guidance:
            bits.append("This model does not accept a guidance value.")
        if not spec.supports_seed:
            # Not "the seed box is greyed out" but "reproducibility is
            # impossible here" — the difference matters to anyone using a
            # fixed seed to compare prompt wordings.
            bits.append(
                f"{spec.short_name} accepts NO seed — the seed controls are "
                f"disabled because there is nothing to send. Two runs of the "
                f"same prompt will differ, and no setting can make them "
                f"match; use another model when you need to compare wordings "
                f"fairly."
            )
        if spec.supports_prompt_expansion:
            mode = self._selected_expansion()
            if mode == "raw":
                bits.append(
                    f"Prompt expansion is OFF — {spec.short_name} will use "
                    f"your words exactly as written. Expansion is what this "
                    f"model is built around, so leaving it off gives up part "
                    f"of what you are paying for."
                )
            elif mode == "high":
                bits.append(
                    f"Prompt expansion is HEAVY — {spec.short_name} will take "
                    f"real liberty with style, mood and composition. Good for "
                    f"exploring from a short prompt; risky for a batch, where "
                    f"you usually want every image to stay consistent."
                )
            else:
                bits.append(
                    f"Prompt expansion is ON ({EXPANSION_LABELS[mode]}) — "
                    f"{spec.short_name} fills in lighting, colour and "
                    f"composition detail before generating. A short prompt "
                    f"gets expanded a lot; a long, detailed one like yours is "
                    f"mostly polished rather than rewritten."
                )
        if spec.content_filter_field:
            mode = self._selected_filter()
            if mode == "default":
                bits.append("Content filter: the provider's own setting "
                            "(nothing is sent) — STRICTER than this "
                            "program's default. Switch to Most permissive if "
                            "prompts are being refused unexpectedly.")
            else:
                bits.append(
                    f"Content filter: {FILTER_LABELS[mode].upper()} — this "
                    f"model is being asked for its loosest moderation "
                    f"setting, which is what this program defaults to on the "
                    f"two models that offer one. Unverified against the live "
                    f"API."
                )
        else:
            bits.append("This model's content filter cannot be adjusted — a "
                        "refused prompt comes back as a black image and is "
                        "marked BLOCKED.")

        # A refusal is the ONE way a user can be charged for an image they
        # cannot use, and nothing else in the UI says so. It is not a
        # malformed-request problem (the program validates sizes, so a bad
        # request never reaches a provider) -- the request is well formed, the
        # provider generates, bills, and returns a black frame. Cloudflare
        # also vision-checks the OUTPUT, so ordinary prompts get flagged on a
        # frame the user never sees.
        #
        # Keyed on whether the model actually BILLS, not on its cost band:
        # klein-4b and p-image are "low cost" and still charge for a refusal.
        if not spec.is_free:
            bits.append("Note: a refused prompt still costs you on a paid "
                        "model — the image is generated and billed before it "
                        "comes back blank. It is marked BLOCKED and never "
                        "retried, so you pay at most once. Test new wording "
                        "on a free model first.")
        return " ".join(bits)

    def _prompt_count(self) -> int:
        """How many images this run will actually make.

        The slider on the Prompts tab caps the run, and the cost figures here
        are per-image x COUNT -- so ignoring the cap would quote the price of a
        100-image batch for a 5-image test.
        """
        try:
            path = (self.cfg.get("prompt_file") or "").strip()
            if not path or not Path(path).is_file():
                return 0
            total = len(P.load_prompts(path))
            limit = self.cfg.get("prompt_limit")
            if isinstance(limit, int) and 0 < limit < total:
                return limit
            return total
        except Exception:
            return 0

    # -- generation parameters -------------------------------------------

    def _build_generation(self, parent, row: int) -> None:
        """Generation settings, in two labelled groups.

        LAYOUT NOTE, 2026-09-05. This was one flat 4-column grid holding a
        20-checkbox block, a text box and four unrelated single controls, and
        it read as the odd one out on the tab: columns 2 and 3 existed only
        for Steps and Fixed seed, so Guidance sat at one end of a row with
        Steps stranded at the other and nothing between them.

        The two groups are the real division. "Negative prompt" is one
        feature -- layers compose into the box, the counter grades the box --
        and every part of it is dead on the models that accept no negative
        prompt. "Model parameters" are independent dials that happen to share
        a panel. Splitting them means each group can use the column layout
        that suits it rather than compromising on a shared one.

        NOTHING IS HIDDEN. A control that vanishes when the model changes
        reads as the app losing a setting, and the user cannot then tell
        "this model ignores it" from "where did that go?". Controls disable
        and `param_note` says why -- which is the existing, deliberate
        behaviour and is preserved exactly.
        """
        f = _tk_ttk.LabelFrame(parent, text="Generation Settings", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(0, weight=1)

        # -- group 1: everything to do with the negative prompt -------------
        # Kept on self so the contents can COLLAPSE on a model that accepts no
        # negative prompt -- 10 of the 13 models. The group itself and its
        # explanation always stay on screen, so the feature never silently
        # disappears; only the 20 checkboxes and the text box fold away, which
        # is otherwise 431px of permanently dead panel.
        self.neg_group = neg = _tk_ttk.LabelFrame(
            f, text="Negative prompt", padding=8)
        neg.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        neg.columnconfigure(1, weight=1)

        # Shown INSTEAD of the controls when the model ignores them. Sits in
        # the same grid row as the layers so the group keeps one shape.
        self.neg_unsupported = ttk.Label(
            neg, text="", style="secondary.TLabel", wraplength=900,
            justify="left")
        self.neg_unsupported.grid(row=3, column=0, columnspan=4, sticky="w")
        autowrap(self.neg_unsupported, neg)

        # -- group 2: the per-model dials -----------------------------------
        par = _tk_ttk.LabelFrame(f, text="Model parameters", padding=8)
        par.grid(row=1, column=0, sticky="ew")
        par.columnconfigure(1, weight=1)
        par.columnconfigure(3, weight=1)

        # Negative presets are LAYERS, not alternatives. A quality floor, an
        # anatomy fixer and a no-text layer are orthogonal concerns a user will
        # want combined, so these are checkboxes rather than the single-select
        # dropdown the style presets use.
        #
        # This is affordable because the negative prompt is encoded in its own
        # classifier-free-guidance pass with its own full token budget -- it
        # takes nothing away from the scene description.
        neg_layers_caption = ttk.Label(neg, text="Negative layers:")
        neg_layers_caption.grid(row=0, column=0, sticky="nw",
                                padx=(0, 8), pady=3)

        self.neg_layers_frame = ttk.Frame(neg, style="Surface.TFrame")
        self.neg_layers_frame.grid(row=0, column=1, sticky="ew", pady=3)
        self.neg_layer_vars: dict[str, tk.BooleanVar] = {}

        neg_btns = ttk.Frame(neg, style="Surface.TFrame")
        neg_btns.grid(row=0, column=2, columnspan=2, sticky="ne", pady=3)

        b_nsave = ttk.Button(neg_btns, text="Save As Layer…", width=17,
                             style="primary.TButton",
                             command=self._save_negative_preset)
        b_nsave.pack(side="left", padx=2)
        tip(b_nsave, text="Save the text in the box below as a new named "
                          "layer (or overwrite an existing one).\n\n"
                          "A good layer covers ONE concern - a quality floor, "
                          "or anatomy, or text and logos - so that it is worth "
                          "stacking with the others.")

        b_ndel = ttk.Button(neg_btns, text="Delete Layer", width=15,
                            style="secondary.TButton",
                            command=self._delete_negative_preset)
        b_ndel.pack(side="left", padx=2)
        tip(b_ndel, text="Remove the selected layer. Tick exactly one layer "
                         "to choose which. The built-in layers come back if "
                         "you delete every one of them.")

        neg_prompt_caption = ttk.Label(neg, text="Negative prompt:")
        neg_prompt_caption.grid(row=1, column=0, sticky="nw",
                                padx=(0, 8), pady=3)

        # A multi-line box: negative prompts grow into long comma-separated
        # lists, and a single-line Entry hides everything past the first few
        # words with no indication there is more.
        neg_wrap = ttk.Frame(neg, style="Surface.TFrame")
        neg_wrap.grid(row=1, column=1, columnspan=3, sticky="ew", pady=3)
        neg_wrap.columnconfigure(0, weight=1)

        self.negative_text = tk.Text(
            neg_wrap, height=3, wrap="word", font=FONT_BODY,
            bg=PALETTE["bg_input"], fg=PALETTE["text_primary"],
            insertbackground=PALETTE["text_primary"],
            selectbackground=PALETTE["accent_strong"],
            selectforeground=PALETTE["text_primary"],
            relief="flat", borderwidth=5, highlightthickness=1,
            highlightbackground=PALETTE["accent_glow"],
            highlightcolor=PALETTE["accent_mid"],
        )
        self.negative_text.grid(row=0, column=0, sticky="ew")
        self.negative_text.insert("1.0", self.cfg.get("negative_prompt", ""))
        self.negative_text.bind("<KeyRelease>",
                                lambda e: self._on_negative_changed())
        self.app.attach_context_menu(self.negative_text)

        neg_sb = ttk.Scrollbar(neg_wrap, orient="vertical",
                               command=self.negative_text.yview)
        neg_sb.grid(row=0, column=1, sticky="ns")
        self.negative_text.configure(yscrollcommand=neg_sb.set)

        tip(self.negative_text,
            text="Things to keep out of every image, comma separated — e.g. "
                 "'text, watermark, signature, people, blurry, extra limbs'. "
                 "Stable Diffusion models only; the FLUX klein models ignore "
                 "it.\n\n"
                 "Ticking layers above replaces what is in here. Edit freely "
                 "afterwards - your changes are kept until you tick another "
                 "layer.")

        # The negative prompt is encoded separately from the positive one and
        # gets its own budget, so it needs its own counter rather than being
        # folded into the Prompts tab figure.
        self.neg_count = ttk.Label(neg, text="", style="secondary.TLabel")
        self.neg_count.grid(row=2, column=1, columnspan=3, sticky="w",
                            pady=(2, 0))

        # Everything in this group that folds away on a model with no negative
        # prompt. The group frame and neg_unsupported are deliberately NOT in
        # here -- they are what stays visible so the feature never vanishes.
        self._neg_rows = (neg_layers_caption, self.neg_layers_frame, neg_btns,
                          neg_prompt_caption, neg_wrap, self.neg_count)
        tip(self.neg_count,
            text="How long the negative prompt is against what this model "
                 "reads comfortably. Advice only - nothing here truncates it, "
                 "but the model silently drops whatever runs past its own "
                 "budget.\n\n"
                 "This budget is the negative prompt's OWN. It is encoded in a "
                 "separate pass from your scene description, so a long list "
                 "here takes nothing away from the prompt itself - stack as "
                 "many layers as are actually useful.\n\n"
                 "It does overflow sooner than it looks like it should, "
                 "though: a comma-separated keyword list tokenizes far less "
                 "efficiently than ordinary prose.")

        ttk.Label(par, text="Guidance:").grid(row=0, column=0, sticky="w",
                                            padx=(0, 8), pady=3)
        self.guidance_var = tk.StringVar(value=str(self.cfg.get("guidance", "")))
        # Kept on self: this was a local `g`, so nothing could disable it --
        # the box stayed editable on the eight models that accept no guidance
        # at all, while param_note said the opposite two lines below.
        self.guidance_entry = g = ttk.Entry(
            par, textvariable=self.guidance_var, width=10)
        g.grid(row=0, column=1, sticky="w", pady=3)
        self.app.attach_context_menu(g)
        # Guarded by _placeholding: _set_param_entry writes a placeholder into
        # this var to show what a disabled box is using, and without the guard
        # that placeholder would be SAVED as the user's guidance value and
        # then sent to the next model that does accept one.
        self.guidance_var.trace_add(
            "write", lambda *_: None if self._placeholding else
            self.app.set_cfg("guidance", self.guidance_var.get()))
        tip(g, text="How strictly the image follows the prompt.\n\n"
                    "Typical range 1-20. Around 7-8 is the usual sweet spot "
                    "for Stable Diffusion; 1-3 gives the model more freedom "
                    "and 15+ tends to look harsh and over-saturated.\n\n"
                    "Measured per model: DreamShaper LCM genuinely needs a "
                    "low value (around 1) — anything higher risks a broken, "
                    "colour-crushed image. SDXL Base and SDXL Lightning both "
                    "want a normal-to-moderate value (around 8) — a low "
                    "value smears detail on SDXL Base and looks over-"
                    "sharpened/crunchy on Lightning. FLUX klein is also a "
                    "guidance-distilled model and wants a low value (around "
                    "1), per Black Forest Labs' own model card — it takes "
                    "guidance but not steps.\n\n"
                    "Leave empty for the model's own default - usually best, "
                    "since the right value per model is applied "
                    "automatically.")

        ttk.Label(par, text="Steps:").grid(row=0, column=2, sticky="e",
                                         padx=(12, 8), pady=3)
        self.steps_var = tk.StringVar(value=str(self.cfg.get("steps", "")))
        self.steps_entry = ttk.Entry(par, textvariable=self.steps_var, width=10)
        self.steps_entry.grid(row=0, column=3, sticky="w", pady=3)
        self.app.attach_context_menu(self.steps_entry)
        self.steps_var.trace_add(
            "write", lambda *_: None if self._placeholding else
            self.app.set_cfg("steps", self.steps_var.get()))
        tip(self.steps_entry,
            text="How many refinement passes the model makes. More is slower, "
                 "and past a point makes no visible difference.\n\n"
                 "Allowed range 1-20 on this provider. SDXL Lightning is "
                 "distilled for about 8 — if 8 looks a little sharp or "
                 "over-crunchy for your taste, try pushing steps toward 20 "
                 "for a softer, more detailed look before touching anything "
                 "else. DreamShaper LCM needs at least 8 — measured: 4 steps "
                 "produced a duplicated, warped subject even with correct "
                 "guidance, so treat 8 as a floor, not just a default. SDXL "
                 "Base wants its full budget, around 20. The FLUX klein "
                 "models are fixed at 4 and ignore this box entirely.\n\n"
                 "Leave empty for the model's own default.")

        ttk.Label(par, text="Prompt expansion:").grid(
            row=1, column=0, sticky="e", padx=(0, 8), pady=3)
        self.expansion_var = tk.StringVar(
            value=self.cfg.get("prompt_expansion", M.DEFAULT_PROMPT_EXPANSION))
        self.expansion_combo = ttk.Combobox(
            par, textvariable=self.expansion_var, state="readonly", width=28,
            values=[EXPANSION_LABELS[m] for m in M.PROMPT_EXPANSION_MODES])
        self.expansion_combo.grid(row=1, column=1, sticky="w", pady=3)
        self.expansion_combo.set(
            EXPANSION_LABELS.get(self.expansion_var.get(),
                                 EXPANSION_LABELS[M.DEFAULT_PROMPT_EXPANSION]))
        self.expansion_combo.bind(
            "<<ComboboxSelected>>",
            lambda *_: self.app.set_cfg("prompt_expansion",
                                        self._selected_expansion()))
        tip(self.expansion_combo,
            text="Some models REWRITE your prompt before generating, to add "
                 "detail they think is missing. Only the Krea models do this "
                 "on this provider; the box is disabled for everything else.\n\n"
                 "This program defaults to Off, which is NOT the API's own "
                 "default — left alone, Krea expands prompts unless told not "
                 "to, and images come back not quite matching what you "
                 "wrote.\n\n"
                 "Why it matters more here than in a one-off generator: the "
                 "text sent is your prompt PLUS the style suffix, and "
                 "expansion rewrites the whole thing. It can reword your "
                 "style addon as readily as your subject — and the style "
                 "suffix is the part meant to stay identical across every "
                 "image in the batch, so letting it drift defeats the point "
                 "of having one.\n\n"
                 "Expansion is still worth trying on short or sparse prompts, "
                 "where there is genuinely detail missing for it to add. Keep "
                 "it Off for prompts you have written carefully.")

        ttk.Label(par, text="Content filter:").grid(
            row=2, column=0, sticky="e", padx=(0, 8), pady=3)
        self.filter_var = tk.StringVar(
            value=self.cfg.get("content_filter", M.DEFAULT_CONTENT_FILTER))
        self.filter_combo = ttk.Combobox(
            par, textvariable=self.filter_var, state="readonly", width=28,
            values=[FILTER_LABELS[m] for m in M.CONTENT_FILTER_MODES])
        self.filter_combo.grid(row=2, column=1, sticky="w", pady=3)
        self.filter_combo.set(
            FILTER_LABELS.get(self.filter_var.get(),
                              FILTER_LABELS[M.DEFAULT_CONTENT_FILTER]))
        self.filter_combo.bind(
            "<<ComboboxSelected>>",
            lambda *_: self._on_filter_changed())
        tip(self.filter_combo,
            # Trimmed 2026-09-05 from 1233 characters, which measured 924px
            # tall -- fine on a 1080p screen, over the edge on a laptop. The
            # per-model consequence of the CURRENT setting is stated by
            # param_note below the controls, so this covers only what the
            # control is and why its default is what it is.
            text="How strict the provider's own content filter should be.\n\n"
                 "Only P-Image and FLUX.2 pro offer this; the box is disabled "
                 "elsewhere. Every other model has a filter you cannot touch, "
                 "and when one of those refuses a prompt it says nothing — it "
                 "returns a black image, which this program marks BLOCKED.\n\n"
                 "Most permissive is the default here, and asks for the "
                 "loosest setting the model itself offers. That suits a BATCH "
                 "tool: a false flag costs a slot in an overnight run you only "
                 "check the next morning, not a quick rerun.\n\n"
                 "It does not disable moderation — the provider still enforces "
                 "its own limits, and a genuinely refused prompt stays "
                 "refused.")

        self.random_seed_var = tk.BooleanVar(
            value=bool(self.cfg.get("random_seed", True)))
        self.random_seed_check = ttk.Checkbutton(
            par, text="Random seed for each image "
                    "(uncheck to compare prompts fairly)",
            variable=self.random_seed_var,
            command=self._on_seed_mode)
        self.random_seed_check.grid(row=3, column=0, columnspan=2, sticky="w",
                                    pady=(6, 3))
        tip(self.random_seed_check,
            text="Random seeds give variety. A fixed seed makes two "
                 "runs comparable — useful when testing prompt wording. "
                 "Every seed used is recorded in the image's .json file.\n\n"
                 "Some models accept no seed at all (Recraft and Nano "
                 "Banana), in which case "
                 "these controls are disabled — runs cannot be made "
                 "reproducible on those models by any means.")

        self.seed_label = ttk.Label(par, text="Fixed seed:")
        self.seed_label.grid(row=3, column=2, sticky="e",
                             padx=(12, 8), pady=(6, 3))
        self.seed_var = tk.StringVar(value=str(self.cfg.get("seed", "")))
        self.seed_entry = ttk.Entry(par, textvariable=self.seed_var, width=10)
        self.seed_entry.grid(row=3, column=3, sticky="w", pady=(6, 3))
        self.app.attach_context_menu(self.seed_entry)
        self.seed_var.trace_add(
            "write", lambda *_: self.app.set_cfg("seed", self.seed_var.get()))

        # Built after the box exists: ticking a layer writes into it.
        self._rebuild_negative_layers()

        self.param_note = ttk.Label(par, text="", style="secondary.TLabel",
                                    wraplength=980, justify="left")
        self.param_note.grid(row=4, column=0, columnspan=4, sticky="w",
                             pady=(6, 0))
        autowrap(self.param_note, par)
        reserve_lines(self.param_note, 2, sticky_height=False)

        self._on_seed_mode()

    def _on_filter_changed(self) -> None:
        self.app.set_cfg("content_filter", self._selected_filter())
        # The note below the controls spells out what the current setting
        # actually does on the selected model, so it has to re-render.
        self.param_note.configure(text=self._param_note(self._current_spec()))

    def _current_spec(self) -> M.ModelSpec:
        return M.get_model(self._current_model_key())

    def _on_negative_changed(self) -> None:
        self.app.set_cfg("negative_prompt",
                         self.negative_text.get("1.0", "end").strip())
        self.refresh_negative_hint()

    # -- negative presets -------------------------------------------------

    def _negative_preset_names(self) -> list[str]:
        return sorted(self.cfg.get("negative_presets",
                                   BUILTIN_NEGATIVE_PRESETS).keys())

    def _rebuild_negative_layers(self) -> None:
        """Redraw the checkbox list from the saved presets.

        Called on build and after any save/delete. The ticked set is preserved
        across the rebuild so adding a layer does not clear the user's choice.
        """
        ticked = set(self._ticked_layers())
        for child in self.neg_layers_frame.winfo_children():
            child.destroy()
        self.neg_layer_vars = {}

        names = self._negative_preset_names()
        for i, name in enumerate(names):
            var = tk.BooleanVar(value=name in ticked)
            cb = ttk.Checkbutton(
                self.neg_layers_frame, text=name, variable=var,
                command=self._on_negative_layers_changed,
            )
            # Two columns: the list is short now but grows with the content
            # sessions, and a single column would push the box off the tab.
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 14))
            self.neg_layer_vars[name] = var

    def _ticked_layers(self) -> list[str]:
        """Ticked layer names, in the order they compose.

        Falls back to the saved config before the widgets exist, which is what
        makes the selection survive a restart.
        """
        if not getattr(self, "neg_layer_vars", None):
            saved = self.cfg.get("negative_layers", [])
            return [n for n in saved if isinstance(n, str)]
        return [n for n in self._negative_preset_names()
                if self.neg_layer_vars[n].get()]

    def _on_negative_layers_changed(self) -> None:
        """Compose the ticked layers into the box.

        This REPLACES the box's contents, which is the honest behaviour for a
        live-joined composition -- a merge would make it impossible to untick
        a layer and actually be rid of its terms. Hand edits are preserved
        until the next tick, and that is the documented trade.
        """
        names = self._ticked_layers()
        self.app.set_cfg("negative_layers", names)

        presets = self.cfg.get("negative_presets", {})
        composed = P.compose_negative([presets.get(n, "") for n in names])

        self.negative_text.delete("1.0", "end")
        self.negative_text.insert("1.0", composed)
        self._on_negative_changed()

    def _save_negative_preset(self) -> None:
        current = self.negative_text.get("1.0", "end").strip()
        if not current:
            messagebox.showinfo("Nothing to save",
                                "The negative prompt box is empty.",
                                parent=self.app.root)
            return
        ticked = self._ticked_layers()
        name = simpledialog.askstring(
            "Save negative layer", "Name for this negative layer:",
            initialvalue=ticked[0] if len(ticked) == 1 else "",
            parent=self.app.root,
        )
        if not name:
            return
        name = name.strip()
        presets = dict(self.cfg.get("negative_presets", {}))
        presets[name] = current
        self.cfg["negative_presets"] = presets
        self.app.save()
        self._rebuild_negative_layers()
        self.app.log(f"Saved negative layer '{name}'.")

    def _delete_negative_preset(self) -> None:
        # With checkboxes there is no single "selected" layer, so deletion
        # needs exactly one ticked to be unambiguous. Guessing which of three
        # ticked layers to delete would be worse than asking.
        ticked = self._ticked_layers()
        if len(ticked) != 1:
            messagebox.showinfo(
                "Which layer?",
                "Tick exactly one layer to delete it.\n\n"
                f"{len(ticked)} are ticked right now.",
                parent=self.app.root)
            return
        name = ticked[0]

        presets = dict(self.cfg.get("negative_presets", {}))
        if name not in presets:
            return
        if not messagebox.askyesno("Delete layer",
                                   f"Delete the negative layer '{name}'?",
                                   parent=self.app.root):
            return
        presets.pop(name, None)
        if not presets:
            presets = dict(BUILTIN_NEGATIVE_PRESETS)   # never leave it empty
        self.cfg["negative_presets"] = presets
        self.app.set_cfg("negative_layers", [])
        self.app.save()
        self._rebuild_negative_layers()
        self._on_negative_layers_changed()

    def refresh_negative_hint(self) -> None:
        """Update the negative prompt's character counter."""
        if not hasattr(self, "neg_count"):
            return
        spec = M.get_model(self.cfg.get("model", M.DEFAULT_MODEL))
        if not spec.supports_negative_prompt:
            # Counting characters the model will never read would be noise.
            self.neg_count.configure(text="", style="secondary.TLabel")
            return
        text = self.negative_text.get("1.0", "end").strip()
        if not text:
            self.neg_count.configure(text="", style="secondary.TLabel")
            return
        adv = P.length_advice(text, spec.prompt_soft_limit,
                              spec.prompt_hard_limit)
        self.neg_count.configure(text=f"Negative prompt: {adv.message}",
                                 style=_LEVEL_STYLE[adv.level])

    def _on_seed_mode(self) -> None:
        random = self.random_seed_var.get()
        self.app.set_cfg("random_seed", random)
        # A model with no seed field cannot be made reproducible at all, so
        # both controls go dead rather than sitting there implying otherwise.
        # Same treatment as krea's tier dropdown and the content-filter combo:
        # disable the control and explain it in the note, never leave a widget
        # that silently does nothing.
        # This runs once during _build_generation, before the model dropdown
        # has been populated, so the spec is not knowable yet. Assume a seed
        # is supported then; _on_model_changed re-runs this as soon as it is.
        supports_seed = (self._current_spec().supports_seed
                         if hasattr(self, "_model_labels") else True)
        if not supports_seed:
            self.random_seed_check.configure(state="disabled")
            self.seed_label.configure(state="disabled")
            self.seed_entry.configure(state="disabled")
            return
        self.random_seed_check.configure(state="normal")
        self.seed_label.configure(state="normal")
        self.seed_entry.configure(state="disabled" if random else "normal")

    # -- politeness ------------------------------------------------------

    # -- style reference image -------------------------------------------

    def _build_reference(self, parent, row: int) -> None:
        """One global style reference image, on the models that can take one.

        A style lever the style-suffix TEXT cannot reach: it carries a look
        rather than a description of one. Five models accept a local file
        (both klein, both nano-banana, flux-2-pro); the rest genuinely cannot,
        which is a MEASUREMENT rather than a scope choice -- see
        REFERENCE_IMAGE_EXCLUSIONS in core/models.py.

        NOTHING IS HIDDEN on an unsupported model. The group, the path and the
        reason all stay on screen: the rule is that hiding a control the user
        might want reads as the app losing a setting, while a feature the
        model CANNOT USE is honest to disable -- as long as it says why.
        """
        f = _tk_ttk.LabelFrame(parent, text="Style Reference Image", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(1, weight=1)

        self.ref_enabled_var = tk.BooleanVar(
            value=bool(self.cfg.get("reference_enabled", False)))
        self.ref_check = ttk.Checkbutton(
            f, text="Use a reference image", variable=self.ref_enabled_var,
            command=self._on_reference_toggled)
        self.ref_check.grid(row=0, column=0, columnspan=3, sticky="w",
                            pady=(0, 6))
        tip(self.ref_check,
            text="Send one image along with every prompt in the batch, so the "
                 "model matches its look.\n\n"
                 "The style suffix describes a style in words; this shows the "
                 "model one. They work together - the preset carries the "
                 "words, the reference carries the look.")

        ttk.Label(f, text="Reference file:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        self.ref_path_var = tk.StringVar(
            value=self.cfg.get("reference_image", ""))
        self.ref_entry = ttk.Entry(f, textvariable=self.ref_path_var)
        self.ref_entry.grid(row=1, column=1, sticky="ew", pady=4)
        self.app.attach_context_menu(self.ref_entry)
        self.ref_path_var.trace_add("write", lambda *_: self._on_reference_path())
        tip(self.ref_entry,
            text="A PNG, JPEG or WebP file. No particular size or shape is "
                 "needed - the program resizes it for you and says what it "
                 "did.")

        ref_btns = ttk.Frame(f, style="Surface.TFrame")
        ref_btns.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        self.ref_browse = ttk.Button(
            ref_btns, text="Choose Image\u2026", width=16,
            style="Folder.TButton", command=self._pick_reference)
        self.ref_browse.pack(side="left")

        self.ref_clear = ttk.Button(
            ref_btns, text="Clear", width=8, style="secondary.TButton",
            command=lambda: self.ref_path_var.set(""))
        self.ref_clear.pack(side="left", padx=(4, 0))
        tip(self.ref_clear,
            text="Forget the selected image. The tickbox stays as it is.")

        # A PREVIEW, because this is the cheapest possible guard against
        # "wrong sprite for 200 images". Seeing the file beats reading its
        # path, and the path is often a truncated long one.
        preview_wrap = ttk.Frame(f, style="Surface.TFrame")
        preview_wrap.grid(row=2, column=0, sticky="nw", padx=(0, 8), pady=4)
        self._ref_preview_wrap = preview_wrap
        self.ref_preview = ttk.Label(preview_wrap, style="secondary.TLabel")
        self.ref_preview.pack()
        # Tk drops an image the moment nothing references it, so the
        # PhotoImage is kept on the instance rather than in a local.
        self._ref_thumb = None

        # The status label. FOUR states and it ALWAYS says something --
        # modelled on the one-off prompt banner, which established both the
        # pattern and the reason: stating the off case is what makes the on
        # case read as a change rather than as noise, and an empty label
        # leaves a hole in the layout until something happens.
        #
        # It states the CONSEQUENCE, not the verdict. "Aspect ratio mismatch"
        # is a verdict; "your reference is 1:1 but you are generating 16:9, so
        # the model will re-frame the composition" is what will happen.
        self.ref_status = ttk.Label(
            f, text="", style="secondary.TLabel", wraplength=900,
            justify="left")
        # Its OWN full-width row rather than beside the thumbnail. autowrap
        # measures the CONTAINER, so a label sharing a row with the 96px
        # preview was being given a wraplength ~100px wider than the space it
        # actually had, and the text ran off the right edge -- visible in a
        # screenshot, invisible in the code.
        self.ref_status.grid(row=2, column=1, columnspan=2, sticky="nw",
                             pady=4)
        autowrap(self.ref_status, f, padding=150)
        # sticky_height=False: this re-renders on MODEL and RATIO selection,
        # and holding the tallest model's height would leave permanent dead
        # space under every shorter message. The ratchet is for text that
        # changes on its own, not for text driven by an explicit choice.
        # Three FACTS, each on its own line, and any of them can wrap at a
        # narrow window: the transformation, the floor warning, the ratio
        # note. Measured at the 900px minimum width, that is four lines.
        reserve_lines(self.ref_status, 4, sticky_height=False)

        ttk.Label(f, text="Resizing:").grid(row=3, column=0, sticky="w",
                                            padx=(0, 8), pady=4)

        # THREE STATES, not a checkbox. Auto-detection is measured to be
        # reliable (4 colours / 0.000 round-trip for pixel art against ~97k /
        # 0.529 for a photo), so a checkbox would make every user answer a
        # question the program can usually answer itself. The manual options
        # stay because detection CAN be wrong and the user knows their file.
        self.ref_resample_var = tk.StringVar(
            value=R.RESAMPLE_LABELS.get(
                self.cfg.get("reference_resample", R.DEFAULT_RESAMPLE),
                R.RESAMPLE_LABELS[R.DEFAULT_RESAMPLE]))
        self.ref_resample_combo = ttk.Combobox(
            f, textvariable=self.ref_resample_var, state="readonly", width=26,
            values=[R.RESAMPLE_LABELS[m] for m in R.RESAMPLE_MODES])
        self.ref_resample_combo.grid(row=3, column=1, sticky="w", pady=4)
        self.ref_resample_combo.bind(
            "<<ComboboxSelected>>", self._on_reference_resample)
        tip(self.ref_resample_combo,
            text="How the image is resized to fit.\n\n"
                 "Auto looks at the picture and decides - it is right almost "
                 "always.\n\n"
                 "Pixel art keeps hard pixel edges crisp, which is what you "
                 "want for a sprite. Photo smooths, which is right for "
                 "everything else. Pick one yourself if Auto guesses wrong.")

        ttk.Label(f, text="Influence:").grid(row=4, column=0, sticky="w",
                                             padx=(0, 8), pady=4)

        # No model in the feature has a strength FIELD, so this is the only
        # lever there is: a sentence added to every prompt. Words, not a
        # weight -- hence a dropdown of named levels rather than a slider,
        # which would promise a precision the models do not have.
        self.ref_influence_var = tk.StringVar(
            value=R.INFLUENCE_LABELS.get(
                self.cfg.get("reference_influence", R.DEFAULT_INFLUENCE),
                R.INFLUENCE_LABELS[R.DEFAULT_INFLUENCE]))
        self.ref_influence_combo = ttk.Combobox(
            f, textvariable=self.ref_influence_var, state="readonly",
            width=26, values=[R.INFLUENCE_LABELS[m] for m in R.INFLUENCE_MODES])
        self.ref_influence_combo.grid(row=4, column=1, sticky="w", pady=4)
        self.ref_influence_combo.bind(
            "<<ComboboxSelected>>", self._on_reference_influence)
        tip(self.ref_influence_combo,
            text="Adds a sentence to the end of every prompt asking the "
                 "model to follow the reference more closely, so you do not "
                 "have to type it into each one.\n\n"
                 "The reference image does most of the work by itself - this "
                 "is a nudge on top, and no model offers a real strength "
                 "setting. Every level, None included, adds its sentence "
                 "while a reference is in use.\n\n"
                 "The sentence shows in the Prompts tab preview and counts "
                 "towards the prompt length.")

        # Model-aware, re-rendered with the group: what the dropdown adds in
        # THIS model's words, and how to write it by hand.
        self.ref_hint = ttk.Label(
            f, style="secondary.TLabel", wraplength=900, justify="left",
            text="")
        self.ref_hint.grid(row=5, column=0, columnspan=3, sticky="w",
                           pady=(6, 0))
        autowrap(self.ref_hint, f)
        # Re-renders on influence and model choice, so no ratchet.
        reserve_lines(self.ref_hint, 3, sticky_height=False)

        self._ref_widgets = (self.ref_check, self.ref_entry, self.ref_browse,
                             self.ref_clear, self.ref_resample_combo,
                             self.ref_influence_combo)

    # -- style reference: events and state --------------------------------

    def _on_reference_toggled(self) -> None:
        self.app.set_cfg("reference_enabled", bool(self.ref_enabled_var.get()))
        self.refresh_reference()
        self._refresh_prompt_preview()

    def _on_reference_path(self) -> None:
        self.app.set_cfg("reference_image", self.ref_path_var.get())
        self.refresh_reference()
        self._refresh_prompt_preview()

    def _on_reference_influence(self, _evt=None) -> None:
        # By INDEX, never by reading the label back -- same rule as the tier
        # and resampler dropdowns.
        i = self.ref_influence_combo.current()
        mode = (R.INFLUENCE_MODES[i] if 0 <= i < len(R.INFLUENCE_MODES)
                else R.DEFAULT_INFLUENCE)
        self.app.set_cfg("reference_influence", mode)
        self.refresh_reference()
        self._refresh_prompt_preview()

    def _refresh_prompt_preview(self) -> None:
        """Redraw the Prompts tab preview, which shows the influence sentence.

        Called from the reference EVENT handlers, deliberately not from
        refresh_reference(): that runs inside recalculate(), and the preview
        calls back into recalculate() through the prompt-count slider.
        """
        prompts_tab = getattr(self.app, "prompts_tab", None)
        if prompts_tab is not None:
            prompts_tab.refresh_preview()

    def _on_reference_resample(self, _evt=None) -> None:
        self.app.set_cfg("reference_resample", self._selected_resample())
        self.refresh_reference()

    def _selected_resample(self) -> str:
        """The resampler mode, recovered BY INDEX, never by reading the label.

        The same rule the tier dropdown follows: the visible strings are
        display text, and a reverse lookup on them silently resets the user's
        choice the moment one is reworded.
        """
        i = self.ref_resample_combo.current()
        if 0 <= i < len(R.RESAMPLE_MODES):
            return R.RESAMPLE_MODES[i]
        return R.DEFAULT_RESAMPLE

    def _pick_reference(self) -> None:
        current = self.ref_path_var.get()
        start = (Path(current).parent
                 if current and Path(current).is_file() else Path.cwd())
        path = filedialog.askopenfilename(
            parent=self.app.root,
            title="Choose a style reference image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"),
                       ("All files", "*.*")],
            initialdir=str(start),
        )
        if path:
            self.ref_path_var.set(path)
            # Choosing a file is the moment the user means to use it. Leaving
            # the tick off here would silently ignore the thing they just
            # picked, which is the failure the preview exists to prevent.
            if not self.ref_enabled_var.get():
                self.ref_enabled_var.set(True)
                self._on_reference_toggled()

    def refresh_reference(self) -> None:
        """Re-render the whole group for the current model, size and file.

        Every verdict here comes from core.reference -- this method RENDERS a
        PreparedReference, it does not decide anything. `cli dry-run` prints
        the same object, which is what keeps the label and the batch from
        ever disagreeing about what will actually be sent.
        """
        model_key = self._current_model_key()
        if not model_key:
            return
        spec = M.get_model(model_key)

        # Unsupported model: everything disables, and the reason stays on
        # screen naming the models that DO work. A disabled control still has
        # to say why it is disabled.
        if spec.reference_field is None:
            for w in self._ref_widgets:
                try:
                    w.configure(state="disabled")
                except tk.TclError:
                    pass
            self._set_ref_preview(None)
            self.ref_status.configure(
                text=f"Not available on {spec.short_name} \u2014 it accepts no "
                     f"reference image. Use {M.reference_models_sentence()} "
                     f"instead. Your selection is kept.",
                style="secondary.TLabel")
            self.ref_hint.configure(text="")
            return

        for w in self._ref_widgets:
            try:
                w.configure(state="readonly"
                            if w in (self.ref_resample_combo,
                                     self.ref_influence_combo) else "normal")
            except tk.TclError:
                pass

        path = self.ref_path_var.get().strip()
        on = bool(self.ref_enabled_var.get())
        self.ref_hint.configure(text=reference_hint(
            spec, self.cfg.get("reference_influence", R.DEFAULT_INFLUENCE),
            armed=on and bool(path)))

        if not on:
            self._set_ref_preview(None)
            self.ref_status.configure(
                text="Off \u2014 the style suffix alone drives the look. Tick "
                     "above to send a reference image with every prompt.",
                style="success.TLabel")
            return
        if not path:
            self._set_ref_preview(None)
            self.ref_status.configure(
                text="On, but no image chosen \u2014 pick one, or untick to "
                     "generate from the prompt and style suffix alone.",
                style="danger.TLabel")
            return

        ratio = self.ratio_var.get()
        width, height = M.size_for(ratio, self._selected_tier(), model_key)
        try:
            prepared = R.prepare(path, self._selected_resample(),
                                 output_size=(width, height))
        except R.ReferenceError as e:
            self._set_ref_preview(None)
            # Missing and unreadable are DIFFERENT states with different
            # fixes, and the message core.reference raises already says which.
            self.ref_status.configure(text=str(e), style="danger.TLabel")
            return

        self._set_ref_preview(prepared)
        # One fact per LINE. Run together on one line these three sentences
        # read as a wall and the important one (what is being sent) is lost
        # in the middle of it.
        lines = [prepared.describe()]
        style = "success.TLabel"
        if prepared.warnings:
            # A resize below the floor, or a ratio that differs from the
            # output, is worth saying out loud -- but neither is an error:
            # the program handles both and the batch runs.
            lines.extend(prepared.warnings)
            style = ("info.TLabel" if prepared.transform != "none"
                     else "warning.TLabel")
        self.ref_status.configure(text="\n".join(lines), style=style)

    def _set_ref_preview(self, prepared) -> None:
        """Show a small thumbnail of what is armed, or clear it.

        Built from the PREPARED bytes rather than from the file, so the
        preview is of the image that will actually be sent -- including the
        nearest upscale, which is the whole point of showing it for a sprite.
        """
        if prepared is None:
            self._ref_thumb = None
            self.ref_preview.configure(image="", text="")
            return
        try:
            import base64
            import io as _io

            from PIL import Image

            with Image.open(_io.BytesIO(prepared.data)) as im:
                thumb = im.copy()
            # NEAREST for pixel art here too, and for the same reason the
            # resize uses it: a blurred thumbnail of a sprite misrepresents
            # the thing being sent.
            resample = (Image.NEAREST if prepared.resampler == "nearest"
                        else Image.LANCZOS)
            thumb.thumbnail((96, 96), resample)
            buf = _io.BytesIO()
            thumb.convert("RGB").save(buf, format="PNG")
            self._ref_thumb = tk.PhotoImage(
                data=base64.b64encode(buf.getvalue()).decode("ascii"))
            self.ref_preview.configure(image=self._ref_thumb, text="")
        except Exception:
            # A preview is a convenience. Never let one stop the tab working.
            self._ref_thumb = None
            self.ref_preview.configure(image="", text="")

    def _build_politeness(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(
            parent, text="Politeness & Reliability", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(5, 10))
        f.columnconfigure(5, weight=1)

        intro = ttk.Label(
            f,
            text="These defaults are deliberately conservative. The free tiers "
                 "are a courtesy, not an entitlement — sending requests faster "
                 "risks rate limits and, on a shared free tier, the account "
                 "itself. Raise them only if you know the provider is fine "
                 "with it.",
            style="secondary.TLabel", wraplength=980, justify="left",
        )
        intro.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        autowrap(intro, f)

        self.conc_var = tk.StringVar(value=str(self.cfg.get("concurrency", 2)))
        self.delay_var = tk.StringVar(value=str(self.cfg.get("delay", 1.0)))
        self.attempts_var = tk.StringVar(
            value=str(self.cfg.get("max_attempts", DEFAULT_MAX_ATTEMPTS)))
        self.timeout_var = tk.StringVar(value=str(self.cfg.get("timeout", 180.0)))

        specs = [
            ("Concurrent requests:", self.conc_var, "concurrency", 1, 8,
             "How many images are generated at once. 1-2 is the polite range."),
            ("Delay between requests (s):", self.delay_var, "delay", 0, 60,
             "A deliberate pause before each request. Shared across all "
             "workers, so 2 workers with a 1s delay still means one request "
             "per second overall."),
            ("Max attempts per image:", self.attempts_var, "max_attempts", 1, 10,
             "How many times a failing image is retried before giving up. "
             "Content-filter blocks are never retried — those are "
             "permanent. PAID models ignore this and get ONE attempt "
             "with no retry, because a retry is billed as a brand new "
             "image; rate limits are exempt, since they are refused "
             "before they cost anything."),
            ("Request timeout (s):", self.timeout_var, "timeout", 10, 600,
             "Give up on a single request after this long, so one wedged "
             "request cannot stall an overnight batch."),
        ]
        for i, (label, var, key, lo, hi, hint) in enumerate(specs):
            r, c = divmod(i, 2)
            ttk.Label(f, text=label).grid(row=1 + r, column=c * 3,
                                          sticky="w", padx=(0, 8), pady=3)
            sb = ttk.Spinbox(f, textvariable=var, from_=lo, to=hi, width=8,
                             command=lambda k=key, v=var: self._save_number(k, v))
            sb.grid(row=1 + r, column=c * 3 + 1, sticky="w", pady=3)
            self.app.attach_context_menu(sb)
            var.trace_add("write",
                          lambda *_, k=key, v=var: self._save_number(k, v))
            tip(sb, text=hint)

        self.overwrite_var = tk.BooleanVar(
            value=bool(self.cfg.get("overwrite", False)))
        # The old label was "Overwrite images that already exist", which reads
        # as "regenerate everything" -- and a user ticked it, pressed Start,
        # and got nothing, because a finished job is never re-queued for this
        # flag to apply to. It governs ONLY the on-disk collision check for
        # jobs that actually run, so the label now says that and points at the
        # control that does the other thing.
        ow = ttk.Checkbutton(
            f, text="Replace files instead of saving alongside them "
                    "(only affects images being generated now)",
            variable=self.overwrite_var,
            command=lambda: self.app.set_cfg("overwrite",
                                             self.overwrite_var.get()))
        ow.grid(row=3, column=0, columnspan=6, sticky="w", pady=(8, 0))
        tip(ow, text="Leave this off. It only applies to images this run is "
                     "actually generating: off, a new image that would land on "
                     "an existing filename is saved as `..._2` instead; on, it "
                     "replaces that file.\n\n"
                     "This does NOT redo finished images. A batch that is "
                     "already complete stays complete either way — use "
                     "Regenerate on the Run tab for that.")

    def _save_number(self, key: str, var: tk.StringVar) -> None:
        raw = var.get().strip()
        if not raw:
            return
        try:
            value = float(raw) if key in ("delay", "timeout") else int(raw)
        except ValueError:
            return
        self.app.set_cfg(key, value)


def _label_for(key: str) -> str:
    for k, lbl in PROVIDERS:
        if k == key:
            return lbl
    return PROVIDERS[0][1]


def _key_for(label: str) -> str:
    for k, lbl in PROVIDERS:
        if lbl == label:
            return k
    return PROVIDERS[0][0]
