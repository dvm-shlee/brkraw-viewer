from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class CollapsibleSection(ttk.Frame):
    """A header line (toggle glyph plus title) that shows or hides a body frame on click.

    Hiding uses ``grid_remove``: the body and everything in it keep their state, variables and callbacks.
    Put the content into ``body``.
    """

    OPEN_GLYPH = "▾"  # down-pointing triangle
    CLOSED_GLYPH = "▸"  # right-pointing triangle

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        expanded: bool = True,
        on_toggle: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._title = str(title)
        self._expanded = bool(expanded)
        self._on_toggle = on_toggle
        self.columnconfigure(0, weight=1)
        self.header = ttk.Label(self, text="", cursor="hand2", padding=(2, 2))
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.bind("<Button-1>", lambda _e: self.toggle())
        self.body = ttk.Frame(self)
        self.body.grid(row=1, column=0, sticky="nsew")
        self._apply()

    @property
    def title(self) -> str:
        return self._title

    @property
    def expanded(self) -> bool:
        return self._expanded

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply()
        if self._on_toggle is not None:
            self._on_toggle(expanded)

    def _apply(self) -> None:
        glyph = self.OPEN_GLYPH if self._expanded else self.CLOSED_GLYPH
        self.header.configure(text=f"{glyph} {self._title}")
        if self._expanded:
            self.body.grid()
        else:
            self.body.grid_remove()
