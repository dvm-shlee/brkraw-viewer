"""Tk binding of the label paint tool (WI-0053, stage 3 WI-C).

Thin on purpose: the brush, undo and saving live in core/painter.py and core/labelio.py; the
controller maps display pixels to layer voxels. This box holds the Off / Paint / Erase choice,
the brush size and the Undo / New label layer / Save label... buttons, and forwards pointer
events (given in view image row/col) to the controller callbacks.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

PAINT_MODES = ("off", "paint", "erase")


class PaintTool:
    """The paint box and its stroke forwarding; ``frame`` is placed by the caller."""

    def __init__(self, parent: tk.Misc, *, callbacks, master: tk.Misc, on_activate: Optional[Callable[[], None]] = None) -> None:
        self._callbacks = callbacks
        self._on_activate = on_activate
        self.mode_var = tk.StringVar(master=master, value="off")
        self.brush_var = tk.IntVar(master=master, value=3)
        self.frame = ttk.Frame(parent)
        ttk.Label(self.frame, text="Paint").pack(side=tk.LEFT, padx=(0, 4))
        self._radios: dict[str, ttk.Radiobutton] = {}
        for mode in PAINT_MODES:
            radio = ttk.Radiobutton(
                self.frame,
                text=mode.capitalize(),
                value=mode,
                variable=self.mode_var,
                command=self._on_mode,
            )
            radio.pack(side=tk.LEFT, padx=(0, 2))
            self._radios[mode] = radio
        ttk.Label(self.frame, text="Brush").pack(side=tk.LEFT, padx=(6, 2))
        self._brush = ttk.Spinbox(self.frame, from_=1, to=99, width=3, textvariable=self.brush_var)
        self._brush.pack(side=tk.LEFT)
        self._undo_btn = ttk.Button(self.frame, text="Undo", command=self.undo, width=5)
        self._undo_btn.pack(side=tk.LEFT, padx=(6, 2))
        self._new = ttk.Button(self.frame, text="New label layer", command=self.new_layer)
        self._new.pack(side=tk.LEFT, padx=(2, 2))
        self._save = ttk.Button(self.frame, text="Save label...", command=self.save)
        self._save.pack(side=tk.LEFT, padx=(2, 0))
        self.refresh()

    # ----- state -----

    @property
    def mode(self) -> str:
        return str(self.mode_var.get())

    @property
    def active(self) -> bool:
        return self.mode != "off"

    def brush_size(self) -> int:
        try:
            return max(1, int(self.brush_var.get()))
        except (tk.TclError, ValueError):
            return 1

    def set_off(self) -> None:
        self.cancel()
        self.mode_var.set("off")

    def refresh(self) -> None:
        """Enable the box from the controller's state; the radios only for an editable label layer."""
        getter = getattr(self._callbacks, "viewer_paint_state", None)
        state = getter() if callable(getter) else {}
        enabled = bool(state.get("enabled"))
        if not enabled and self.active:
            self.set_off()
            if self._on_activate is not None:
                self._on_activate()
        for mode in ("paint", "erase"):
            self._radios[mode].configure(state="normal" if enabled else "disabled")
        self._brush.configure(state="normal" if enabled else "disabled")
        self._undo_btn.configure(state="normal" if state.get("can_undo") else "disabled")
        self._save.configure(state="normal" if state.get("can_save") else "disabled")
        self._new.configure(state="normal" if state.get("can_new") else "disabled")

    # ----- user actions -----

    def _on_mode(self) -> None:
        if not self.active:
            self.cancel()
        if self._on_activate is not None:
            self._on_activate()

    def press(self, plane: str, row: float, col: float) -> bool:
        handler = getattr(self._callbacks, "on_viewer_paint_press", None)
        if not self.active or not callable(handler):
            return False
        return bool(handler(plane, row, col, self.mode, self.brush_size()))

    def move(self, plane: str, row: float, col: float) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_move", None)
        if self.active and callable(handler):
            handler(plane, row, col)

    def release(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_release", None)
        if callable(handler):
            handler()

    def cancel(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_cancel", None)
        if callable(handler):
            handler()

    def undo(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_undo", None)
        if callable(handler):
            handler()
        self.refresh()

    def new_layer(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_new_layer", None)
        if not callable(handler):
            return
        try:
            handler()
        except ValueError as exc:
            messagebox.showerror("New label layer", str(exc), parent=self.frame)
        self.refresh()

    def save(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_save", None)
        if not callable(handler):
            return
        path = filedialog.asksaveasfilename(
            parent=self.frame,
            title="Save label layer",
            defaultextension=".nii.gz",
            filetypes=[("NIfTI (gzip)", "*.nii.gz")],
        )
        if not path:
            return
        path = str(path)
        if not path.endswith(".nii.gz"):
            path += ".nii.gz"
        try:
            handler(path)
        except (ValueError, OSError) as exc:
            messagebox.showerror("Save label", str(exc), parent=self.frame)
        self.refresh()
