"""
A single wildcard-set row: [label entry] [entries entry] [remove button]
"""

import tkinter as tk
from tkinter import ttk


class WildcardRow(ttk.Frame):
    def __init__(self, parent, on_remove, on_change):
        super().__init__(parent)
        self.on_remove = on_remove
        self.on_change = on_change

        self.label_var = tk.StringVar()

        self.label_entry = ttk.Entry(self, textvariable=self.label_var, width=16)
        self.label_entry.grid(row=0, column=0, padx=(0, 6), pady=(0, 2), sticky="nw")

        entries_frame = ttk.Frame(self)
        entries_frame.grid(row=0, column=1, padx=(0, 6), pady=(0, 2), sticky="ew")
        entries_frame.columnconfigure(0, weight=1)

        self.entries_text = tk.Text(entries_frame, width=60, height=3, wrap="word", undo=True)
        self.entries_text.grid(row=0, column=0, sticky="ew")
        entries_scroll = ttk.Scrollbar(entries_frame, orient="vertical", command=self.entries_text.yview)
        entries_scroll.grid(row=0, column=1, sticky="ns")
        self.entries_text.configure(yscrollcommand=entries_scroll.set)

        self.remove_btn = ttk.Button(self, text="Remove", width=8, command=self._remove)
        self.remove_btn.grid(row=0, column=2, sticky="ne")

        self.columnconfigure(1, weight=1)

        self.label_var.trace_add("write", lambda *_: self.on_change())
        self.entries_text.bind("<<Modified>>", self._on_text_modified)

    def _on_text_modified(self, event):
        self.entries_text.edit_modified(False)
        self.on_change()

    def _remove(self):
        self.on_remove(self)

    def get_label(self):
        return self.label_var.get().strip()

    def get_entries_raw(self):
        return self.entries_text.get("1.0", "end-1c")

    def set_label(self, text):
        self.label_var.set(text)

    def set_entries_raw(self, text):
        self.entries_text.delete("1.0", "end")
        self.entries_text.insert("1.0", text)
