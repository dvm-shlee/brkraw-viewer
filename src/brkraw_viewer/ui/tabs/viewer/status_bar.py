from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ViewerStatusBar(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self._text_var = tk.StringVar(master=self, value="Viewer status")
        ttk.Label(self, textvariable=self._text_var, anchor="w").grid(row=0, column=0, sticky="ew")

    def set_text(self, text: str) -> None:
        self._text_var.set(str(text))
