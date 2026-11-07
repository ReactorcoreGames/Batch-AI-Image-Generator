"""Run tab — dry run, batch controls, live progress, and the log.

Everything here runs on the Tk main thread. Progress arrives as an already-
frozen snapshot marshalled by `BatchGenApp` via `root.after(0, ...)`; this
module never reads engine state directly.
"""

from __future__ import annotations

import tkinter as tk

import ttkbootstrap as ttk
from tkinter import messagebox, ttk as _tk_ttk

from core import models as M
from gui.tooltip import tip
from gui.scroll import autowrap, make_scrollable, reserve_lines
from gui.theme import FONT_BODY, FONT_MONO, FONT_SMALL, PALETTE

MAX_LOG_LINES = 2000


class RunTab:
    def __init__(self, notebook, app):
        self.app = app
        self.cfg = app.config
        self._running = False
        self._paused = False
        # How many jobs this run finished (done + skipped) -- what Regenerate
        # would act on. Zero on a fresh tab, which is what keeps it disabled.
        self._finished_jobs = 0
        self._build(notebook)
        self._set_controls(running=False)

    # ------------------------------------------------------------------ #

    def _build(self, notebook) -> None:
        # Scrolls for the same reason the Provider tab does: at the minimum
        # window height the fixed sections above would squeeze the log to
        # nothing. With a scrolling body the log keeps a usable height and the
        # window simply scrolls instead.
        tab = make_scrollable(notebook, "  Run  ")
        tab.columnconfigure(0, weight=1)

        self._build_controls(tab, row=0)
        self._build_progress(tab, row=1)
        self._build_current(tab, row=2)
        self._build_redo(tab, row=3)
        self._build_log(tab, row=4)

    # -- controls --------------------------------------------------------

    def _build_controls(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Batch Controls", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(10, 5))
        # Share the width evenly so no button is clipped at the right edge
        # when the window is at its minimum size. SIX columns, not seven:
        # at the 900px minimum width seven would leave ~118px per button and
        # clip "Regenerate All", so that one starts a second row instead.
        for c in range(6):
            f.columnconfigure(c, weight=1, uniform="ctl")

        self.btn_dry = ttk.Button(f, text="Dry Run",
                                  style="info.TButton", command=self._dry_run)
        self.btn_dry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        tip(self.btn_dry,
                text="Show how many images would be made and what they would "
                     "cost, without contacting the API at all. Costs nothing "
                     "and changes nothing.")

        self.btn_start = ttk.Button(f, text="Start Batch",
                                    style="success.TButton",
                                    command=lambda: self.app.start_batch(False))
        self.btn_start.grid(row=0, column=1, sticky="ew", padx=6)
        tip(self.btn_start,
                text="Begin generating. Images already saved in the output "
                     "folder are skipped, so this doubles as Resume.")

        self.btn_pause = ttk.Button(f, text="Pause",
                                    style="warning.TButton",
                                    command=self._pause)
        self.btn_pause.grid(row=0, column=2, sticky="ew", padx=6)
        tip(self.btn_pause, text="Stop starting new images. Requests "
                                     "already in flight finish normally.")

        self.btn_resume = ttk.Button(f, text="Resume",
                                     style="primary.TButton",
                                     command=self._resume)
        self.btn_resume.grid(row=0, column=3, sticky="ew", padx=6)

        self.btn_cancel = ttk.Button(f, text="Cancel",
                                     style="danger.TButton",
                                     command=self.app.cancel_batch)
        self.btn_cancel.grid(row=0, column=4, sticky="ew", padx=6)
        tip(self.btn_cancel,
                text="Stop the batch. Everything finished so far is kept, and "
                     "starting again picks up where this left off.")

        self.btn_retry = ttk.Button(f, text="Retry Failed",
                                    style="secondary.TButton",
                                    command=lambda: self.app.start_batch(True))
        self.btn_retry.grid(row=0, column=5, sticky="ew", padx=(6, 0))
        tip(self.btn_retry,
                text="Re-queue images that failed for temporary reasons "
                     "(network, rate limits). Images refused by the content "
                     "filter are NOT retried — rewrite those prompts instead.")

    # -- progress --------------------------------------------------------

    def _build_progress(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Progress", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, columnspan=7, sticky="ew",
                           pady=(0, 10))

        self.stats: dict[str, ttk.Label] = {}
        cells = [
            ("done", "Completed", "success.TLabel"),
            ("skipped", "Already there", "secondary.TLabel"),
            ("failed", "Failed", "danger.TLabel"),
            ("blocked", "Blocked", "warning.TLabel"),
            ("in_flight", "In flight", "info.TLabel"),
            ("elapsed", "Elapsed", "primary.TLabel"),
            ("cost", "Cost so far", "primary.TLabel"),
        ]
        for col, (key, caption, style) in enumerate(cells):
            f.columnconfigure(col, weight=1, uniform="stat")
            box = ttk.Frame(f, style="Surface.TFrame")
            box.grid(row=1, column=col, sticky="ew", padx=4)
            box.columnconfigure(0, weight=1)
            val = ttk.Label(box, text="0", style=style, anchor="center",
                            font=("Segoe UI", 15, "bold"))
            val.grid(row=0, column=0, sticky="ew")
            ttk.Label(box, text=caption, style="secondary.TLabel",
                      anchor="center").grid(row=1, column=0, sticky="ew")
            self.stats[key] = val

        self.summary_label = ttk.Label(f, text="Idle.", style="primary.TLabel",
                                       wraplength=980, justify="left")
        self.summary_label.grid(row=2, column=0, columnspan=len(cells),
                                sticky="w", pady=(10, 0))
        autowrap(self.summary_label, f)
        reserve_lines(self.summary_label, 2)

    def _build_current(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Current Prompt", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        f.columnconfigure(0, weight=1)

        self.current_label = ttk.Label(f, text="—", style="secondary.TLabel",
                                       wraplength=980, justify="left")
        self.current_label.grid(row=0, column=0, sticky="w")
        autowrap(self.current_label, f)
        reserve_lines(self.current_label, 2)

    # -- regenerate --------------------------------------------------------

    def _build_redo(self, parent, row: int) -> None:
        """Regenerate lives on its own row, bottom-left, deliberately.

        NOT in Batch Controls: it is the one action that spends again on images
        that already exist, and sitting beside Start made it a mis-click. NOT
        in the Log frame either, next to Clear Log -- that frame is about the
        log, and filing a re-spend beside a harmless view action is exactly the
        pairing to avoid. Fixed width rather than full width, for the same
        reason: a small target, away from everything else.
        """
        f = ttk.Frame(parent, style="Surface.TFrame")
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(2, 0))

        self.btn_regen = ttk.Button(f, text="Regenerate", width=16,
                                    style="quiet.TButton",
                                    command=self._regenerate)
        self.btn_regen.pack(side="left")

        # The reason it is greyed out has to be ON SCREEN, not only in a
        # tooltip: a disabled button with no explanation reads as the program
        # being broken. Mirrors the negative-prompt group's rule.
        self.regen_hint = ttk.Label(f, text="", style="secondary.TLabel",
                                    font=FONT_SMALL)
        self.regen_hint.pack(side="left", padx=(16, 0))

        # Kept SHORT deliberately. The long version said the same thing four
        # ways and was taller than the panel it pointed at; the detail lives
        # in the guide, and the on-screen hint beside the button carries the
        # one fact that changes per run.
        tip(self.btn_regen,
                text="Generates this run's images again, replacing the saved "
                     "ones — for a new random seed, or results that were not "
                     "good.\n\n"
                     "Not needed after changing the model, size or style: "
                     "those already regenerate on a normal Start.\n\n"
                     "Paid models are charged again. Ignores the Overwrite "
                     "setting — it always replaces.")

    # -- log -------------------------------------------------------------

    def _build_log(self, parent, row: int) -> None:
        f = _tk_ttk.LabelFrame(parent, text="Log", padding=10)
        f.grid(row=row, column=0, sticky="ew", padx=10, pady=(5, 10))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # tk.Text takes no ttk styling — bg/fg must be set explicitly.
        self.log_text = tk.Text(
            f, wrap="word", font=FONT_MONO, height=12,
            bg=PALETTE["bg_input"], fg=PALETTE["text_primary"],
            insertbackground=PALETTE["text_primary"],
            selectbackground=PALETTE["accent_strong"],
            selectforeground=PALETTE["text_primary"],
            relief="flat", borderwidth=6, highlightthickness=1,
            highlightbackground=PALETTE["accent_glow"],
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(f, orient="vertical", command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        self.log_text.tag_configure("error", foreground=PALETTE["danger"])
        self.log_text.tag_configure("warn", foreground=PALETTE["warning"])
        self.log_text.tag_configure("ok", foreground=PALETTE["success"])
        self.app.attach_context_menu(self.log_text)

        row_btns = ttk.Frame(f, style="Surface.TFrame")
        row_btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(row_btns, text="Clear Log", width=12,
                   style="secondary.TButton",
                   command=self.clear_log).pack(side="left")

    def append_log(self, message: str) -> None:
        """Main thread only. Engine output arrives here via the app's queue."""
        low = message.lower()
        tag = ("error" if any(w in low for w in ("error", "failed", "fail"))
               else "warn" if any(w in low for w in ("warn", "blocked",
                                                     "rate limited", "backing off"))
               else "ok" if " done" in low else "")

        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", tag)

        # Keep the widget from growing without bound on a long overnight batch.
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{lines - MAX_LOG_LINES}.0")

        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        write_file = getattr(self.app, "_write_log_file", None)
        if write_file is not None:
            write_file(message)

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # -- dry run ---------------------------------------------------------

    def _dry_run(self) -> None:
        info = self.app.dry_run()
        if info is None:
            return

        self.append_log("")
        self.append_log("=== DRY RUN — no API calls, nothing spent ===")
        self.append_log(f"Prompt file : {info['prompt_file']}")
        self.append_log(f"Output dir  : {info['output_dir']}")
        self.append_log(f"Images      : {info['jobs']}")
        self.append_log(f"Model       : {info['model']}  ({info['model_id']})")
        self.append_log(
            f"Size        : {info['size']}  {info['ratio']} {info['tier']} "
            f"— {info['tiles']} tiles, {info['megapixels']} MP")
        if info["is_free"]:
            self.append_log("Cost        : Free")
        else:
            self.append_log(
                f"Cost        : ${info['cost_per_image']:.5f}/image  "
                f"${info['cost_per_1000']:.2f}/1000  "
                f"TOTAL ${info['total_cost']:.4f}")
            if info["free_images_per_day"] is not None:
                self.append_log(
                    f"Free/day    : ~{info['free_images_per_day']} (estimate)")
        # Cost BAND, in the same words as the Provider tab and the CLI. The
        # old line named "the project's $5 per 1000 budget ceiling" -- this
        # project's internal policy, which means nothing to the user reading
        # the log, and which read identically at $5.01 and at $151.
        band = M.cost_band_for_price(info["cost_per_1000"])
        if band not in ("free", "low"):
            self.append_log(
                f"Cost band   : {M.COST_BAND_LABELS[band]} — "
                f"${info['cost_per_1000']:,.2f} per 1000 images")
        for w in info["warnings"]:
            self.append_log(f"WARNING: {w}")
        for e in info["errors"]:
            self.append_log(f"ERROR: {e}")

        self.append_log("Files that would be written:")
        for ln in info["lines"]:
            self.append_log(f"  {ln['line_no']:>3}  {ln['filename']}")
        self.append_log("=== end of dry run ===")

        self.summary_label.configure(
            text=f"Dry run: {info['jobs']} image(s) at {info['size']} — "
                 + ("free." if info["is_free"]
                    else f"${info['total_cost']:.4f} total."))

    # -- batch lifecycle callbacks (main thread) --------------------------

    def on_batch_starting(self, n_jobs: int) -> None:
        self._running = True
        self._paused = False
        # Counts arrive already populated from the database on a resume, so
        # remember the starting point to tell "generated just now" apart from
        # "was already finished in an earlier run".
        self._done_at_start = None
        self._last_skipped = 0
        self._set_controls(running=True)
        self.progress.configure(maximum=max(n_jobs, 1), value=0)
        for key in ("done", "skipped", "failed", "blocked", "in_flight"):
            self.stats[key].configure(text="0")
        self.stats["elapsed"].configure(text="0s")
        self.stats["cost"].configure(text="—")
        self.summary_label.configure(text=f"Running — {n_jobs} image(s) queued.",
                                     style="primary.TLabel")
        self.append_log("")
        self.append_log(f"=== Batch started — {n_jobs} image(s) ===")

    def on_progress(self, p) -> None:
        self._last_skipped = p.skipped
        # done + skipped is exactly what requeue_finished() acts on, so this
        # is the real "is there anything to regenerate" answer rather than a
        # guess at it.
        self._finished_jobs = p.done + p.skipped
        if self._done_at_start is None:
            self._done_at_start = p.done
        self.progress.configure(maximum=max(p.total, 1), value=p.finished)
        self.stats["done"].configure(text=str(p.done))
        self.stats["skipped"].configure(text=str(p.skipped))
        self.stats["failed"].configure(text=str(p.failed))
        self.stats["blocked"].configure(text=str(p.blocked))
        self.stats["in_flight"].configure(text=str(p.in_flight))
        self.stats["elapsed"].configure(text=_fmt_elapsed(p.elapsed))
        self.stats["cost"].configure(
            text="Free" if p.cost <= 0 else f"${p.cost:.4f}")

        self.summary_label.configure(
            text=f"{'Paused' if self._paused else 'Running'} — "
                 f"{p.finished}/{p.total} finished.")
        self.current_label.configure(text=p.current or "—")

    def on_batch_finished(self, cancelled: bool, quota_msg: str | None = None) -> None:
        self._running = False
        self._paused = False
        self._set_controls(running=False)
        word = "Cancelled" if cancelled else "Finished"
        self.append_log(f"=== Batch {word.lower()} ===")

        if quota_msg:
            # Expected condition on a free tier, not a crash: say so plainly,
            # and that the remaining jobs are untouched and can be resumed
            # once the allowance recovers (unpredictable — Cloudflare's stated
            # 00:00 UTC reset has been measured still blocking hours later).
            self.append_log(
                f"=== Stopped: {quota_msg} — remaining jobs left queued, "
                "resume the batch later once the allowance resets ==="
            )
            self.summary_label.configure(
                text=(
                    f"Stopped — {quota_msg}. This is expected on the free "
                    "daily allowance, not an error. The remaining prompts "
                    "are still queued — start the batch again later (the "
                    "reset time is not reliable, so just try again after a "
                    "while) and it will pick up where it left off."
                ),
                style="warning.TLabel",
            )
            return

        blocked = int(self.stats["blocked"].cget("text") or 0)
        failed = int(self.stats["failed"].cget("text") or 0)
        done = int(self.stats["done"].cget("text") or 0)
        skipped = getattr(self, "_last_skipped", 0)
        started_with = getattr(self, "_done_at_start", None) or 0
        fresh = max(done - started_with, 0)

        # Distinguish what this run did from what was already finished. On a
        # resume the engine reports the batch's cumulative totals, so reporting
        # `done` as "just generated" would claim work that never happened.
        if fresh:
            parts = [f"{word}. {fresh} image(s) generated"]
            if skipped:
                parts.append(f"{skipped} already existed and were kept")
            if started_with:
                parts.append(f"{done} of {started_with + fresh} done in total")
        elif skipped or started_with:
            # Say what to do about it. A user ticked Overwrite expecting this
            # case to regenerate, got "nothing left to do", and had no idea
            # which control actually does that -- Overwrite never re-queues a
            # finished job, so it cannot be the answer.
            already = skipped + started_with
            parts = [f"{word}. Nothing left to do — all {already} image(s) "
                     f"were already generated. To make them again, use "
                     f"Regenerate below (Overwrite does not do this)"]
        else:
            parts = [f"{word}. No images generated"]
        if failed:
            parts.append(f"{failed} failed — 'Retry Failed' will try these again")
        if blocked:
            parts.append(f"{blocked} blocked by the content filter — those "
                         f"prompts need rewriting, retrying will not help")
        self.summary_label.configure(
            text=". ".join(parts) + ".",
            style="danger.TLabel" if (failed or blocked) else "success.TLabel")

        if blocked:
            self.append_log(
                "NOTE: blocked images were refused by the provider's content "
                "filter. That is permanent — rewrite those prompts rather than "
                "retrying them.")

    def on_batch_error(self, message: str) -> None:
        self._running = False
        self._paused = False
        self._set_controls(running=False)
        self.append_log(f"ERROR: {message}")
        self.summary_label.configure(text=f"Batch stopped: {message}",
                                     style="danger.TLabel")

    # -- control state ---------------------------------------------------

    def _pause(self) -> None:
        self.app.pause_batch()
        self._paused = True
        self._set_controls(running=True)

    def _resume(self) -> None:
        self.app.resume_batch()
        self._paused = False
        self._set_controls(running=True)

    def _regenerate(self) -> None:
        """Generate the whole batch again, replacing what is already there.

        Confirmed even on a free model: the images on disk are about to be
        replaced, and that is not undoable. The PRICE confirmation is separate
        and still happens downstream in start_batch().
        """
        n = self._finished_jobs
        if not messagebox.askyesno(
            "Regenerate?",
            f"This generates {n} image(s) again and replaces the ones already "
            "saved in the output folder.\n\n"
            "You do not need this after changing the model, size or style "
            "suffix — those already produce new files on a normal Start. Use "
            "it when nothing changed and you want another attempt.\n\n"
            "On a paid model those images are charged again. Continue?",
            parent=self.app.root,
        ):
            return
        self.app.start_batch(regenerate=True)

    def _set_controls(self, running: bool) -> None:
        idle = "normal" if not running else "disabled"
        self.btn_dry.configure(state=idle)
        self.btn_start.configure(state=idle)
        self.btn_retry.configure(state=idle)

        # Regenerate needs something to regenerate. Enabled on a fresh Run tab
        # it was indistinguishable from Start: it would build the batch, find
        # nothing finished, requeue zero jobs and just run normally -- Start
        # wearing the wrong label.
        has_work = getattr(self, "_finished_jobs", 0) > 0
        self.btn_regen.configure(
            state="normal" if (not running and has_work) else "disabled")
        if running:
            self.regen_hint.configure(text="")
        elif has_work:
            n = self._finished_jobs
            self.regen_hint.configure(
                text=f"Generates {n} image{'' if n == 1 else 's'} again, "
                     "replacing the saved ones.")
        else:
            self.regen_hint.configure(
                text="Available once a batch has finished.")
        self.btn_cancel.configure(state="normal" if running else "disabled")
        self.btn_pause.configure(
            state="normal" if running and not self._paused else "disabled")
        self.btn_resume.configure(
            state="normal" if running and self._paused else "disabled")


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {(s % 3600) // 60}m"
