"""Main application window.

This is a thin shell around the engine in core/. It owns:
  * the window, theme, header/footer chrome and the notebook
  * config load/save
  * the one background thread the batch runs on, and the marshalling of
    progress events back onto the Tk main thread

THE ONE HARD THREADING RULE: `on_progress` fires on engine worker threads.
Nothing in this file may touch a Tk widget from there — every callback goes
through `root.after(0, ...)`. Getting this wrong produces intermittent crashes
that are miserable to diagnose later.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path

import ttkbootstrap as ttk
from tkinter import ttk as _tk_ttk
from tkinter import messagebox

from core import models as M
from core import prompts as P
from core import reference as R
from core.engine import (
    DEFAULT_MAX_ATTEMPTS,
    BatchConfig,
    BatchEngine,
    Progress,
)
from core.providers import get_provider
from gui.theme import (
    FONT_BODY,
    FONT_SMALL,
    FONT_TINY,
    FONT_TITLE,
    PALETTE,
    THEME_NAME,
    _inject_custom_theme,
    apply_theme,
)
from gui.scroll import block_wheel
from gui.tooltip import tip
from gui.tabs.helpers import HelpersTab
from gui.tabs.prompts import PromptsTab
from gui.tabs.provider import ProviderTab
from gui.tabs.run import RunTab
from utils.config import app_dir, load_config, save_config
from utils.credentials import apply_to_environment

APP_TITLE = "Batch AI Image Generator"
# Short enough to sit beside the title without being clipped at the minimum
# window width. The long form lives in the guide, not the title bar.
APP_SUBTITLE = "A text file of prompts goes in, a folder of images comes out!"
LINKTREE_URL = "https://linktr.ee/reactorcore"

log = logging.getLogger("batchgen")


class _QueueLogHandler(logging.Handler):
    """Routes engine log records to the GUI without touching Tk.

    The handler only puts strings on a queue — it runs on worker threads. The
    main thread drains that queue on a timer. This is the safe half of the
    threading rule.
    """

    def __init__(self, q: "queue.Queue[str]"):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class BatchGenApp:
    def __init__(self) -> None:
        self.config = load_config()
        # Publish saved keys into os.environ before any provider is
        # constructed. Real environment variables still take priority.
        apply_to_environment()

        _inject_custom_theme(THEME_NAME)          # MUST precede Window()
        self.root = ttk.Window(themename=THEME_NAME)
        self.root.title(APP_TITLE)
        self.root.geometry("1100x800")
        self.root.minsize(900, 640)
        self._maximize(self.root)

        style = ttk.Style()
        apply_theme(style, root=self.root)

        self._apply_icon(self.root)

        # Batch state — all mutated on the main thread only.
        self.engine: BatchEngine | None = None
        self._thread: threading.Thread | None = None
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._log_handler = _QueueLogHandler(self._log_queue)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        self._log_file_path: Path | None = None
        self._log_file = None

        self._build_ui()
        self._install_log_handler()
        self.root.after(150, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    #  Chrome                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _maximize(window) -> None:
        """Open maximized.

        The geometry above stays as the restore-down size, so un-maximizing
        gives a sensible window rather than a sliver. 'zoomed' is the Windows
        state name; the -zoomed attribute is the X11 spelling, and neither
        exists everywhere, so both are attempted and neither is fatal.
        """
        try:
            window.state("zoomed")
            return
        except Exception:
            pass
        try:
            window.attributes("-zoomed", True)
        except Exception:
            pass

    def _apply_icon(self, window) -> None:
        icon_paths = [
            Path("assets/icon.ico"),
            Path(__file__).resolve().parent.parent / "assets" / "icon.ico",
            Path(sys.executable).parent / "icon.ico",
            Path.cwd() / "icon.ico",
        ]
        if hasattr(sys, "_MEIPASS"):
            icon_paths.insert(0, Path(sys._MEIPASS) / "icon.ico")
        for p in icon_paths:
            if p.exists():
                try:
                    window.iconbitmap(str(p))
                    return
                except Exception:
                    continue

    def attach_context_menu(self, widget) -> None:
        """Right-click Cut/Copy/Paste/Select All. Required on every Entry."""
        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="Cut",
                         command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="Copy",
                         command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="Paste",
                         command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="Select All",
                         command=lambda: widget.event_generate("<<SelectAll>>"))

        def _show(event):
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", _show)

    def _build_ui(self) -> None:
        self.root.rowconfigure(0, weight=0)     # header
        self.root.rowconfigure(1, weight=0)     # separator
        self.root.rowconfigure(2, weight=1)     # notebook
        self.root.rowconfigure(3, weight=0)     # separator
        self.root.rowconfigure(4, weight=0)     # footer
        self.root.columnconfigure(0, weight=1)

        self._build_header()
        ttk.Separator(self.root, orient="horizontal").grid(
            row=1, column=0, sticky="ew")
        self._build_notebook()
        ttk.Separator(self.root, orient="horizontal").grid(
            row=3, column=0, sticky="ew")
        self._build_footer()

    def _build_header(self) -> None:
        """Title, divider, subtitle and Help on one row.

        Stacking the subtitle under the title cost a whole row of height for
        text that is read once. On one row it stays visible and gives the
        tabs more room.
        """
        hf = ttk.Frame(self.root, padding=(14, 8))
        hf.grid(row=0, column=0, sticky="ew")
        hf.columnconfigure(2, weight=1)

        ttk.Label(hf, text=APP_TITLE, font=FONT_TITLE,
                  style="Base.TLabel").grid(row=0, column=0, sticky="w")

        ttk.Separator(hf, orient="vertical").grid(
            row=0, column=1, sticky="ns", padx=12, pady=2)

        subtitle = ttk.Label(hf, text=APP_SUBTITLE, font=FONT_SMALL,
                             style="BaseSecondary.TLabel", justify="left")
        subtitle.grid(row=0, column=2, sticky="w")

        self.help_btn = ttk.Button(hf, text="Help", width=10,
                                   style="secondary.TButton",
                                   command=self._open_guide)
        self.help_btn.grid(row=0, column=3, sticky="e", padx=(12, 0))
        tip(self.help_btn, text="Open the user guide for this program.")

    def _open_guide(self) -> None:
        """Open guide.md, wherever it ends up living.

        The guide is written during the release phase, so it may legitimately
        not exist yet. Say so plainly instead of failing silently.
        """
        candidates = [
            Path("guide.md"),
            Path(__file__).resolve().parent.parent / "guide.md",
            Path(sys.executable).parent / "guide.md",
            Path.cwd() / "guide.md",
        ]
        if hasattr(sys, "_MEIPASS"):
            candidates.insert(0, Path(sys._MEIPASS) / "guide.md")

        for path in candidates:
            try:
                if path.is_file():
                    os.startfile(str(path))
                    return
            except Exception:
                continue

        messagebox.showinfo(
            "Guide not available yet",
            "The user guide (guide.md) has not been written yet — it is "
            "produced when the program is packaged for release.\n\n"
            "In the meantime, every control in this program has a tooltip: "
            "hover over anything to see what it does.",
            parent=self.root,
        )

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)

        self.prompts_tab = PromptsTab(self.notebook, self)
        self.provider_tab = ProviderTab(self.notebook, self)
        self.run_tab = RunTab(self.notebook, self)
        # Last: a bonus tab of conveniences, not part of the batch workflow.
        self.helpers_tab = HelpersTab(self.notebook, self)

        # Done centrally rather than per widget so a dropdown added later
        # cannot silently reintroduce wheel-changes-value behaviour.
        self._block_wheel_on_value_widgets(self.notebook)

    def _block_wheel_on_value_widgets(self, parent) -> None:
        """Walk the widget tree and stop the wheel from altering any
        Combobox or Spinbox. See gui.scroll.block_wheel."""
        for child in parent.winfo_children():
            if isinstance(child, (ttk.Combobox, ttk.Spinbox,
                                  _tk_ttk.Combobox, _tk_ttk.Spinbox)):
                block_wheel(child)
            self._block_wheel_on_value_widgets(child)

    def _build_footer(self) -> None:
        ff = ttk.Frame(self.root, padding=(14, 6))
        ff.grid(row=4, column=0, sticky="ew")

        ttk.Label(ff, text="Made by Reactorcore", font=FONT_TINY,
                  style="BaseSecondary.TLabel").pack(side="left")

        link = ttk.Label(ff, text=LINKTREE_URL, font=FONT_TINY,
                         style="BaseSecondary.TLabel", cursor="hand2")
        link.configure(foreground=PALETTE["accent_soft"])
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(LINKTREE_URL))

    # ------------------------------------------------------------------ #
    #  Config                                                             #
    # ------------------------------------------------------------------ #

    def save(self) -> None:
        """Persist config. Called on every change, per the house standard."""
        save_config(self.config)

    def set_cfg(self, key: str, value) -> None:
        self.config[key] = value
        self.save()

    # ------------------------------------------------------------------ #
    #  Logging bridge                                                     #
    # ------------------------------------------------------------------ #

    def _install_log_handler(self) -> None:
        engine_log = logging.getLogger("batchgen")
        engine_log.setLevel(logging.INFO)
        engine_log.addHandler(self._log_handler)
        engine_log.propagate = False

    def _drain_log_queue(self) -> None:
        """Main thread: move queued log lines into the Text widget."""
        try:
            while True:
                self.run_tab.append_log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log_queue)

    def log(self, message: str) -> None:
        """Log from the main thread (UI messages, not engine output)."""
        self.run_tab.append_log(message)

    def _use_log_file(self, output_dir: Path) -> None:
        """Point log.txt at the given output folder, opening it if needed.

        Kept in the output folder alongside .batchgen.db and the images, so a
        batch's log lives with its results rather than mixing runs from
        different folders together.
        """
        path = output_dir / "log.txt"
        if self._log_file_path == path and self._log_file is not None:
            return
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
        self._log_file_path = path
        try:
            self._log_file = open(path, "a", encoding="utf-8")
        except OSError:
            self._log_file = None

    def _write_log_file(self, message: str) -> None:
        if self._log_file is None:
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            for line in message.splitlines() or [""]:
                self._log_file.write(f"[{timestamp}] {line}\n")
            self._log_file.flush()
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    #  Building a BatchConfig from the current UI state                   #
    # ------------------------------------------------------------------ #

    def build_batch_config(self) -> BatchConfig | None:
        """Validate the current settings and produce a BatchConfig.

        Returns None (after showing a message) when something is missing, so
        callers can simply bail.
        """
        c = self.config
        prompt_file = (c.get("prompt_file") or "").strip()
        output_dir = (c.get("output_dir") or "").strip()

        # The one-off override replaces the prompt file, so it has to be
        # settled before the file is validated -- otherwise a user running a
        # one-off is stopped for not having picked a file they are not using.
        prompts_tab = getattr(self, "prompts_tab", None)
        one_off = bool(prompts_tab is not None and prompts_tab.one_off_var.get())
        one_off_text = prompts_tab.one_off_prompt() if one_off else ""

        if one_off and not one_off_text:
            messagebox.showwarning(
                "Nothing to generate",
                "The single custom prompt override is on, but the prompt box "
                "is empty.\n\nType a prompt, or untick the override to use "
                "your prompt file.",
                parent=self.root,
            )
            self.notebook.select(0)
            return None

        if not one_off and (not prompt_file or not Path(prompt_file).is_file()):
            messagebox.showwarning(
                "No prompt file",
                "Choose a .txt file with one prompt per line on the Prompts tab.",
                parent=self.root,
            )
            self.notebook.select(0)
            return None
        if not output_dir:
            messagebox.showwarning(
                "No output folder",
                "Choose a folder to save the generated images into "
                "on the Prompts tab.",
                parent=self.root,
            )
            self.notebook.select(0)
            return None

        self._use_log_file(Path(output_dir))

        # Written as a REAL single-line .txt inside the output folder, so the
        # engine never learns that this run came from a text box: resume,
        # filenames, batch identity and the sidecar's source_file all keep
        # working exactly as they do for a hand-written file.
        if one_off:
            try:
                prompt_file = str(P.materialize_one_off(one_off_text, output_dir))
            except Exception as e:
                messagebox.showerror(
                    "Could not start",
                    f"The single custom prompt could not be saved into the "
                    f"output folder:\n\n{e}",
                    parent=self.root,
                )
                return None

        model = c.get("model", M.DEFAULT_MODEL)
        ratio = c.get("ratio", M.DEFAULT_RATIO)
        tier = c.get("tier", M.DEFAULT_TIER)

        # size_for() substitutes the klein-safe High sizes; never compute
        # dimensions here.
        width, height = M.size_for(ratio, tier, model)
        spec = M.get_model(model)
        errs = spec.validate_size(width, height)
        if errs:
            messagebox.showerror(
                "Unsupported size",
                f"{spec.label} cannot generate {width}x{height}:\n\n"
                + "\n".join(errs),
                parent=self.root,
            )
            self.notebook.select(1)
            return None

        return BatchConfig(
            prompt_file=Path(prompt_file),
            output_dir=Path(output_dir),
            model=model,
            ratio=ratio,
            tier=tier,
            width=width,
            height=height,
            style_suffix=c.get("style_suffix", ""),
            # Exactly one image, regardless of any cap saved for the
            # prompt file this run is not reading.
            limit=1 if one_off else _opt_int(c.get("prompt_limit")),
            negative_prompt=_opt_str(c.get("negative_prompt")),
            guidance=_opt_float(c.get("guidance")),
            prompt_expansion=_opt_str(c.get("prompt_expansion")),
            content_filter=_opt_str(c.get("content_filter")),
            # Both halves have to hold for a reference to be in play: the
            # flag AND a path. They are stored separately so unticking keeps
            # the selection, which means neither alone is the answer here.
            reference_image=_reference_path(c),
            reference_resample=c.get("reference_resample", R.DEFAULT_RESAMPLE),
            reference_influence=c.get("reference_influence",
                                      R.DEFAULT_INFLUENCE),
            steps=_opt_int(c.get("steps")),
            seed=None if c.get("random_seed", True) else _opt_int(c.get("seed")),
            random_seed=bool(c.get("random_seed", True)),
            concurrency=int(c.get("concurrency", 2)),
            delay=float(c.get("delay", 1.0)),
            max_attempts=int(c.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            timeout=float(c.get("timeout", 180.0)),
            overwrite=bool(c.get("overwrite", False)),
            output_format=c.get("output_format", "keep"),
            jpeg_quality=int(c.get("jpeg_quality", 95)),
        )

    # ------------------------------------------------------------------ #
    #  Batch lifecycle                                                    #
    # ------------------------------------------------------------------ #

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_batch(self, retry_failed: bool = False,
                    regenerate: bool = False) -> None:
        if self.running:
            return
        cfg = self.build_batch_config()
        if cfg is None:
            return

        spec = M.get_model(cfg.model)

        # The keyed Pollinations mode is a promise to use a key; without one
        # it would silently fall back to the heavily throttled keyless path.
        if (self.config.get("provider") == "pollinations_keyed"
                and not os.environ.get("POLLINATIONS_API_KEY", "").strip()):
            messagebox.showerror(
                "No Pollinations key",
                "You chose 'Pollinations — with API key', but no key is "
                "saved.\n\nEnter one in the API Keys section on the Provider "
                "tab, or switch to 'Pollinations — no key needed'.",
                parent=self.root,
            )
            self.notebook.select(1)
            return

        # Credentials are a whole-batch problem — check before spending time.
        ok, msg = self._check_credentials(spec.provider)
        if not ok:
            messagebox.showerror("Provider not ready", msg, parent=self.root)
            self.notebook.select(1)
            return

        # Paid models get an explicit confirmation with the real number on it.
        try:
            # `with`, because constructing a BatchEngine opens a JobStore --
            # a live sqlite connection on .batchgen.db. Dropping one unclosed
            # here (on every Start press, including ones cancelled at the paid
            # confirmation below) left the database locked and its WAL
            # sidecars on disk until the program exited, so the user could not
            # delete it to redo a batch.
            with BatchEngine(cfg, provider=_NullProvider()) as engine:
                n_jobs = len(engine.load_lines())
                # Prepare the style reference HERE, before the paid
                # confirmation and before a single request. It raises on a
                # missing, unreadable or wrongly-shaped file, and the only
                # other place it would raise is inside a worker thread --
                # where the user has already clicked through the cost dialog
                # and finds out from the log that nothing ran.
                engine.reference()
        except R.ReferenceError as e:
            # Its own dialog, because the fix is different: the message names
            # the actual numbers and what to do about them, and the prompt
            # file is fine.
            messagebox.showerror("Reference image cannot be used", str(e),
                                 parent=self.root)
            self.notebook.select(1)
            return
        except Exception as e:
            messagebox.showerror("Could not read prompts", str(e), parent=self.root)
            return

        est = M.estimate(cfg.model, cfg.width, cfg.height, n_jobs)
        if not est.is_free and not self._confirm_paid(spec, est, n_jobs):
            return

        for w in est.warnings:
            self.log(f"WARNING: {w}")

        self.run_tab.on_batch_starting(n_jobs)
        self.notebook.select(2)

        def _progress(p: Progress) -> None:
            # Worker thread. Snapshot the values and hand them to the main
            # thread — never touch a widget from here.
            snap = _ProgressSnapshot(p)
            self.root.after(0, lambda: self.run_tab.on_progress(snap))

        provider_override = self._provider_for_mode(spec.provider)

        def _work() -> None:
            engine = None
            try:
                engine = BatchEngine(cfg, provider=provider_override,
                                     on_progress=_progress)
                self.engine = engine
                engine.prepare()
                engine.run(retry_failed=retry_failed, regenerate=regenerate)
                cancelled = engine._cancel.is_set()
                quota_msg = engine.quota_exhausted
                self.root.after(
                    0, lambda: self.run_tab.on_batch_finished(cancelled, quota_msg)
                )
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                log.error("batch failed: %s", err)
                self.root.after(0, lambda: self.run_tab.on_batch_error(err))
            finally:
                if engine is not None:
                    try:
                        engine.close()
                    except Exception:
                        pass
                self.engine = None

        self._thread = threading.Thread(target=_work, daemon=True)
        self._thread.start()

    def pause_batch(self) -> None:
        if self.engine is not None:
            self.engine.pause()
            self.log("Paused — in-flight requests will finish first.")

    def resume_batch(self) -> None:
        if self.engine is not None:
            self.engine.resume()
            self.log("Resumed.")

    def cancel_batch(self) -> None:
        if self.engine is not None:
            self.engine.cancel()
            self.log("Cancelling — waiting for in-flight requests…")

    def dry_run(self) -> dict | None:
        cfg = self.build_batch_config()
        if cfg is None:
            return None
        try:
            with BatchEngine(cfg, provider=_NullProvider()) as engine:
                return engine.dry_run()
        except Exception as e:
            messagebox.showerror("Dry run failed", str(e), parent=self.root)
            return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _provider_for_mode(self, backend: str):
        """Build a provider honouring the selected MODE, not just the backend.

        "Pollinations — no key needed" has to mean it: with a key saved, the
        provider would otherwise pick it up from the environment and the two
        dropdown entries would behave identically. Returns None to let the
        engine construct its own provider as usual.
        """
        if (backend == "pollinations"
                and self.config.get("provider") == "pollinations"):
            from core.providers import PollinationsProvider

            # Explicit empty key: ignore whatever is saved or exported.
            return PollinationsProvider(api_key="")
        return None

    def _check_credentials(self, provider_name: str) -> tuple[bool, str]:
        try:
            override = self._provider_for_mode(provider_name)
            with (override or get_provider(provider_name)) as p:
                ok, msg = p.check()
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        if not ok:
            msg = self._explain_missing_creds(msg)
        return ok, msg

    @staticmethod
    def _explain_missing_creds(msg: str) -> str:
        """Point at the API Keys box rather than restating the engine error.

        The engine reports which variable is empty, which is the right thing
        for the CLI. In the GUI there is a box on screen that fixes it, so
        say that instead.
        """
        if "missing credential" not in msg:
            return msg
        if "POLLINATIONS" in msg:
            return (
                "This mode needs a Pollinations API key. Enter it in the API "
                "Keys section on the Provider tab and press Save, or switch "
                "to 'Pollinations — no key needed'."
            )
        return (
            "Cloudflare needs an Account ID and an API Token. Enter both in "
            "the API Keys section on the Provider tab and press Save — there "
            "is a 'Get key' link beside each box. They take effect straight "
            "away, with no restart."
        )

    def _confirm_paid(self, spec, est, n_jobs: int) -> bool:
        lines = [
            f"{spec.label} is a PAID model.",
            "",
            f"Images:        {n_jobs}",
            f"Size:          {est.width}x{est.height}  ({est.tiles} tiles)",
            f"Per image:     ${est.cost_per_image:.5f}",
            f"Per 1000:      ${est.cost_per_1000:.2f}",
            f"This batch:    ${est.total_cost:.4f}",
        ]
        per_day = est.free_images_per_day
        if per_day is not None:
            lines += [
                "",
                f"Cloudflare's free tier includes 10,000 neurons/day "
                f"(resets 00:00 UTC) — about {per_day} images/day at this "
                f"size before any of this cost applies.",
            ]
        # Cost band, in the same words as everywhere else. This is the LAST
        # screen before money is spent, so it is the worst place to describe
        # a price against this project's internal budget policy rather than
        # against a scale the user can act on.
        band = M.cost_band_for_price(est.cost_per_1000)
        if band not in ("free", "low"):
            lines += [
                "",
                f"{M.COST_BAND_LABELS[band]} — ${est.cost_per_1000:,.2f} "
                f"per 1000 images.",
            ]
        lines += ["", "Generate these images?"]
        return messagebox.askyesno(
            "Confirm paid generation", "\n".join(lines), parent=self.root
        )

    def open_folder(self, path: str) -> None:
        try:
            if path and Path(path).is_dir():
                os.startfile(path)
        except Exception as e:
            self.log(f"Could not open folder: {e}")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "Batch running",
                "A batch is still running. Closing will stop it.\n\n"
                "Progress is saved, so you can resume later by starting the "
                "same batch again.\n\nClose anyway?",
                parent=self.root,
            ):
                return
            self.cancel_batch()
        self.save()
        # Flush the one-off prompt box. It saves as you type, but text typed
        # and never blurred before closing would otherwise be lost -- and the
        # whole point of persisting it is not having to retype it.
        prompts_tab = getattr(self, "prompts_tab", None)
        if prompts_tab is not None:
            try:
                P.write_one_off(app_dir(), prompts_tab.one_off_prompt())
            except Exception:
                pass
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


class _ProgressSnapshot:
    """A frozen copy of Progress, safe to read on the main thread.

    Progress is mutated by workers under a lock; reading its fields from the
    UI later could otherwise catch a torn state.
    """

    __slots__ = ("total", "done", "failed", "blocked", "skipped", "in_flight",
                 "cost", "elapsed", "finished", "current")

    def __init__(self, p: Progress):
        self.total = p.total
        self.done = p.done
        self.failed = p.failed
        self.blocked = p.blocked
        self.skipped = p.skipped
        self.in_flight = p.in_flight
        self.cost = p.cost
        self.elapsed = p.elapsed
        self.finished = p.finished
        self.current = p.current


class _NullProvider:
    """Stand-in for dry-run and prompt counting: constructing a real provider
    would open an HTTP client for nothing."""

    name = "none"

    def generate(self, *a, **kw):
        raise RuntimeError("dry run does not generate")

    def check(self):
        return True, "dry run"

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def _reference_path(c: dict) -> Path | None:
    """The style reference path, or None — the flag AND the path must hold.

    They are two separate settings on purpose (unticking must not lose the
    file), so reading either one alone gives the wrong answer: the path
    survives an untick, and the flag can be on before anything is chosen.
    """
    if not c.get("reference_enabled"):
        return None
    path = (c.get("reference_image") or "").strip()
    return Path(path) if path else None


def _opt_str(v) -> str | None:
    s = (v or "").strip() if isinstance(v, str) else v
    return s or None


def _opt_int(v) -> int | None:
    if v is None:
        return None
    try:
        s = str(v).strip()
        return int(s) if s else None
    except (TypeError, ValueError):
        return None


def _opt_float(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None
