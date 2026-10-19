from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from brkraw_viewer.ui.assets import load_icon
from brkraw_viewer.ui.components.icon_button import IconButton, Command


class StatusBar(ttk.Frame):
    """Status bar widget with a label and optional worker-log button."""
    def __init__(
            self, 
            master: tk.Misc, 
            *, 
            status_var: tk.StringVar,
            on_open_worker_log: Optional[Command] = None
    ) -> None:
        """Create the status label and wire the worker-log action if provided."""
        super().__init__(master)
        self._worker_icon = load_icon("worker-logs.png", size=(16, 16), master=self)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        label = ttk.Label(
            self,
            textvariable=status_var,
            relief="sunken",
            anchor="w",
            padding=(8, 4),
        )
        label.grid(row=0, column=0, sticky="ew")
        if callable(on_open_worker_log) and self._worker_icon is not None:
            btn = IconButton(
                self,
                image=self._worker_icon,
                command=on_open_worker_log,
            )
            btn.grid(row=0, column=1, sticky="nsew", padx=(4, 10), pady=2)
