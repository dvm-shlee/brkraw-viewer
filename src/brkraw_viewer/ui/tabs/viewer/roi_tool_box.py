"""The "ROI tool" box of the Viewer tab's top row.

Three modes decide who owns the mouse on the views: Crosshair (clicks move the crosshair),
Selection (a one-shot square or circle ROI drag) and Drawing (left button paints, right button
erases a label layer). The box holds the choice and the paint widgets; the view panel reads it
and registers a listener for mode changes.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from brkraw_viewer.ui.tabs.viewer.paint_tool import PaintTool

MODES = ("crosshair", "selection", "drawing")
SHAPES = ("square", "circle")


class RoiToolBox(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, *, callbacks) -> None:
        super().__init__(parent, text="ROI tool", padding=(6, 4))
        self._listener: Optional[Callable[[], None]] = None
        self.mode_var = tk.StringVar(master=self, value="crosshair")
        self.shape_var = tk.StringVar(master=self, value="square")

        mode_row = ttk.Frame(self)
        mode_row.grid(row=0, column=0, sticky="w")
        self._mode_radios: dict[str, ttk.Radiobutton] = {}
        for mode in MODES:
            radio = ttk.Radiobutton(
                mode_row,
                text=mode.capitalize(),
                value=mode,
                variable=self.mode_var,
                command=self._on_mode,
            )
            radio.pack(side=tk.LEFT, padx=(0, 4))
            self._mode_radios[mode] = radio

        self.shape_row = ttk.Frame(self)
        self.shape_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(self.shape_row, text="Shape").pack(side=tk.LEFT, padx=(0, 4))
        self._shape_radios: dict[str, ttk.Radiobutton] = {}
        for shape in SHAPES:
            radio = ttk.Radiobutton(
                self.shape_row,
                text=shape.capitalize(),
                value=shape,
                variable=self.shape_var,
                command=self._on_shape,
            )
            radio.pack(side=tk.LEFT, padx=(0, 4))
            self._shape_radios[shape] = radio
        self.shape_row.update_idletasks()
        self.rowconfigure(1, minsize=self.shape_row.winfo_reqheight() + 4)  # the box keeps its height in every mode
        self.shape_row.grid_remove()  # shown only in Selection

        self.paint = PaintTool(self, callbacks=callbacks, master=self, on_activate=self._paint_changed)
        self.paint.frame.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.refresh()

    # ----- state -----

    @property
    def mode(self) -> str:
        return str(self.mode_var.get())

    @property
    def shape(self) -> str:
        return str(self.shape_var.get())

    def set_listener(self, listener: Optional[Callable[[], None]]) -> None:
        """``listener()`` runs after every mode or shape change (the view panel's hook)."""
        self._listener = listener

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode: got {mode!r}, expected one of {list(MODES)}")
        self.mode_var.set(mode)
        self._on_mode()

    def refresh(self) -> None:
        """Re-read the controller's state; Drawing needs an editable label layer."""
        self.paint.refresh()
        getter = getattr(self.paint._callbacks, "viewer_paint_state", None)
        state = getter() if callable(getter) else {}
        self._mode_radios["drawing"].configure(state="normal" if state.get("enabled") else "disabled")

    # ----- user actions -----

    def _on_mode(self) -> None:
        mode = self.mode
        if mode == "selection":
            self.shape_row.grid()
        else:
            self.shape_row.grid_remove()
        self.paint.set_drawing(mode == "drawing")
        self._notify()

    def _on_shape(self) -> None:
        self._notify()

    def _paint_changed(self) -> None:
        """The paint widgets turned drawing off (no editable label layer any more)."""
        if self.mode == "drawing":
            self.mode_var.set("crosshair")
            self._on_mode()

    def _notify(self) -> None:
        if self._listener is not None:
            self._listener()
