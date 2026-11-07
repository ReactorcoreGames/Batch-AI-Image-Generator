"""
Wildcard Prompt Maker — quick and dirty tkinter GUI.

Write a prompt template with {wildcard} placeholders, define named wildcard
sets (label + comma-separated entries), and generate every combination into
a .txt file beside this script — one prompt per line, ready for the
Batch AI Image Generator.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from wildcard_row import WildcardRow
import generator

DEFAULT_TEMPLATE = "Distant high angle background of a {location} at {time_of_day}. {weather} weather."
DEFAULT_FILENAME = "wildcard_prompts.txt"

DEFAULT_WILDCARDS = [
    ("location", "plains, forest, mountains, desert"),
    ("time_of_day", "dawn, day, dusk, night"),
    ("weather", "clear, cloudy, rainy, snowy"),
]


class WildcardPromptMakerApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        self.master = master
        self.rows = []

        self.grid(row=0, column=0, sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._build_template_section()
        self._build_wildcards_section()
        self._build_output_section()
        self._build_status_section()

        for label, entries in DEFAULT_WILDCARDS:
            self._add_row(label, entries)

        self._refresh_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_template_section(self):
        frame = ttk.LabelFrame(self, text="Prompt template", padding=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(0, weight=1)

        hint = ttk.Label(
            frame,
            text="Use {label} as a stand-in for each wildcard set defined below.",
            foreground="#666",
        )
        hint.grid(row=0, column=0, sticky="w", pady=(0, 4))

        text_frame = ttk.Frame(frame)
        text_frame.grid(row=1, column=0, sticky="ew")
        text_frame.columnconfigure(0, weight=1)

        self.template_text = tk.Text(text_frame, height=4, wrap="word", undo=True, font=("Segoe UI", 10))
        self.template_text.grid(row=0, column=0, sticky="ew")
        self.template_text.insert("1.0", DEFAULT_TEMPLATE)

        template_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.template_text.yview)
        template_scroll.grid(row=0, column=1, sticky="ns")
        self.template_text.configure(yscrollcommand=template_scroll.set)

        self.template_text.bind("<<Modified>>", self._on_template_modified)

    def _on_template_modified(self, event):
        self.template_text.edit_modified(False)
        self._refresh_preview()

    def get_template(self):
        return self.template_text.get("1.0", "end-1c")

    def _build_wildcards_section(self):
        outer = ttk.LabelFrame(self, text="Wildcard sets", padding=8)
        outer.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        outer.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Label", width=16, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Entries (comma-separated)", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(0, 6))

        # Scrollable area for rows
        canvas = tk.Canvas(outer, height=220, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.rows_frame = ttk.Frame(canvas)

        self.rows_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        scrollbar.grid(row=1, column=1, sticky="ns")
        outer.rowconfigure(1, weight=1)

        self.rows_frame.columnconfigure(0, weight=1)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        add_btn = ttk.Button(outer, text="+ Add wildcard set", command=lambda: self._add_row("", ""))
        add_btn.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def _build_output_section(self):
        frame = ttk.LabelFrame(self, text="Output", padding=8)
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Filename:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.filename_var = tk.StringVar(value=DEFAULT_FILENAME)
        ttk.Entry(frame, textvariable=self.filename_var).grid(row=0, column=1, sticky="ew")

        ttk.Label(frame, text="Folder:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.folder_var = tk.StringVar(value=os.path.dirname(os.path.abspath(__file__)))
        folder_entry = ttk.Entry(frame, textvariable=self.folder_var)
        folder_entry.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(frame, text="Browse...", command=self._browse_folder).grid(row=1, column=2, padx=(6, 0), pady=(6, 0))

    def _build_status_section(self):
        frame = ttk.Frame(self)
        frame.grid(row=3, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(frame, textvariable=self.status_var, foreground="#666", wraplength=560, justify="left")
        self.status_label.grid(row=0, column=0, sticky="w")

        generate_btn = ttk.Button(frame, text="Generate .txt", command=self._generate)
        generate_btn.grid(row=0, column=1, sticky="e", padx=(10, 0))

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def _add_row(self, label="", entries=""):
        row = WildcardRow(self.rows_frame, on_remove=self._remove_row, on_change=self._refresh_preview)
        row.set_label(label)
        row.set_entries_raw(entries)
        row.grid(row=len(self.rows), column=0, sticky="ew", pady=2)
        self.rows.append(row)
        self._refresh_preview()

    def _remove_row(self, row):
        row.destroy()
        self.rows.remove(row)
        self._regrid_rows()
        self._refresh_preview()

    def _regrid_rows(self):
        for i, row in enumerate(self.rows):
            row.grid(row=i, column=0, sticky="ew", pady=2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _collect_wildcard_sets(self):
        sets = {}
        for row in self.rows:
            label = row.get_label()
            if not label:
                continue
            sets[label] = generator.parse_entries(row.get_entries_raw())
        return sets

    def _browse_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or ".")
        if chosen:
            self.folder_var.set(chosen)

    def _refresh_preview(self):
        template = self.get_template()
        wildcard_sets = self._collect_wildcard_sets()
        lines, warnings = generator.generate_prompts(template, wildcard_sets)

        parts = []
        if lines:
            parts.append(f"Will generate {len(lines)} prompt(s).")
            example = lines[0]
            if len(example) > 120:
                example = example[:117] + "..."
            parts.append(f"Example: {example}")
        if warnings:
            parts.append("Warning: " + " | ".join(warnings))

        self.status_var.set("\n".join(parts) if parts else "")

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    def _generate(self):
        template = self.get_template()
        wildcard_sets = self._collect_wildcard_sets()
        lines, warnings = generator.generate_prompts(template, wildcard_sets)

        if not lines:
            messagebox.showerror("Cannot generate", "\n".join(warnings) if warnings else "No prompts to generate.")
            return

        folder = self.folder_var.get().strip() or os.path.dirname(os.path.abspath(__file__))
        filename = self.filename_var.get().strip() or DEFAULT_FILENAME
        if not filename.lower().endswith(".txt"):
            filename += ".txt"

        output_path = generator.unique_output_path(folder, filename)

        if os.path.exists(output_path):
            if not messagebox.askyesno("File exists", f"{filename} already exists in that folder.\nOverwrite it?"):
                return

        try:
            generator.write_prompts_file(output_path, lines)
        except OSError as e:
            messagebox.showerror("Could not write file", str(e))
            return

        message = f"Wrote {len(lines)} prompts to:\n{output_path}"
        if warnings:
            message += "\n\nWarnings:\n" + "\n".join(warnings)
        messagebox.showinfo("Done", message)


def run():
    root = tk.Tk()
    root.title("Wildcard Prompt Maker")
    root.geometry("760x620")
    root.minsize(640, 520)
    WildcardPromptMakerApp(root)
    root.mainloop()
