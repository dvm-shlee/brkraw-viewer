"""Tk binding of the label paint tool.

Thin on purpose: the brush, undo and saving live in core/painter.py and core/labelio.py; the
controller maps display pixels to layer voxels. The widgets here are the brush size, the colour
button of the painted label and the Undo / New label layer / Save label... buttons; they sit in
the ROI tool box (roi_tool_box.py), which decides when drawing is on. Pointer events (given in
view image row/col) are forwarded to the controller callbacks: the left button paints, the right
button erases.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Callable, Optional

PAINT_MODES = ("off", "paint", "erase")


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


class PaintTool:
    """The paint widgets and stroke forwarding; ``frame`` is placed by the caller."""

    def __init__(self, parent: tk.Misc, *, callbacks, master: tk.Misc, on_activate: Optional[Callable[[], None]] = None) -> None:
        self._callbacks = callbacks
        self._on_activate = on_activate
        self._drawing = False
        self.color: Optional[tuple[int, int, int]] = None
        self.brush_var = tk.IntVar(master=master, value=3)
        self.frame = ttk.Frame(parent)
        top = ttk.Frame(self.frame)
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(top, text="Brush").pack(side=tk.LEFT, padx=(0, 2))
        self._brush = ttk.Spinbox(top, from_=1, to=99, width=3, textvariable=self.brush_var)
        self._brush.pack(side=tk.LEFT)
        ttk.Label(top, text="Colour").pack(side=tk.LEFT, padx=(6, 2))
        self.color_button = tk.Button(top, width=2, relief=tk.RAISED, command=self.choose_color, state="disabled")
        self.color_button.pack(side=tk.LEFT)
        self._undo_btn = ttk.Button(top, text="Undo", command=self.undo, width=5)
        self._undo_btn.pack(side=tk.LEFT, padx=(6, 0))
        bottom = ttk.Frame(self.frame)
        bottom.pack(side=tk.TOP, fill=tk.X, pady=(4, 0))
        self._new = ttk.Button(bottom, text="New label layer", command=self.new_layer)
        self._new.pack(side=tk.LEFT, padx=(0, 2))
        self._save = ttk.Button(bottom, text="Save label...", command=self.save)
        self._save.pack(side=tk.LEFT, padx=(2, 0))
        self.refresh()

    # ----- state -----

    @property
    def mode(self) -> str:
        """"paint" while drawing is on (the right button erases per press), else "off"."""
        return "paint" if self._drawing else "off"

    @property
    def active(self) -> bool:
        return self._drawing

    def set_drawing(self, on: bool) -> None:
        """Drawing on or off; turning it off ends any stroke."""
        on = bool(on)
        if self._drawing and not on:
            self.cancel()
        self._drawing = on

    def brush_size(self) -> int:
        try:
            return max(1, int(self.brush_var.get()))
        except (tk.TclError, ValueError):
            return 1

    def set_off(self) -> None:
        self.cancel()
        self._drawing = False

    def refresh(self) -> None:
        """Enable the widgets from the controller's state; drawing only for an editable label layer."""
        getter = getattr(self._callbacks, "viewer_paint_state", None)
        state = getter() if callable(getter) else {}
        enabled = bool(state.get("enabled"))
        if not enabled and self._drawing:
            self.set_off()
            if self._on_activate is not None:
                self._on_activate()
        self._brush.configure(state="normal" if enabled else "disabled")
        self._undo_btn.configure(state="normal" if state.get("can_undo") else "disabled")
        self._save.configure(state="normal" if state.get("can_save") else "disabled")
        self._new.configure(state="normal" if state.get("can_new") else "disabled")
        self._refresh_color()

    def _refresh_color(self) -> None:
        getter = getattr(self._callbacks, "viewer_paint_color", None)
        rgb = getter() if callable(getter) else None
        self.color = tuple(int(c) for c in rgb) if rgb is not None else None
        if self.color is None:
            default = self.frame.winfo_toplevel().cget("background") if self.frame.winfo_exists() else "#d9d9d9"
            self.color_button.configure(state="disabled", bg=default, activebackground=default)
            return
        hex_color = _hex(self.color)
        self.color_button.configure(state="normal", bg=hex_color, activebackground=hex_color)

    # ----- user actions -----

    def choose_color(self) -> None:
        """Open the colour dialog; a chosen colour goes to the controller, Cancel changes nothing."""
        handler = getattr(self._callbacks, "on_viewer_paint_color", None)
        if not callable(handler) or self.color is None:
            return
        chosen = colorchooser.askcolor(color=_hex(self.color), parent=self.frame, title="Label colour")
        if not chosen or chosen[0] is None:
            return
        rgb = tuple(int(round(float(c))) for c in chosen[0])
        try:
            handler(rgb)
        except ValueError as exc:
            messagebox.showerror("Label colour", str(exc), parent=self.frame)
        self.refresh()

    def press(self, plane: str, row: float, col: float, erase: bool = False) -> bool:
        handler = getattr(self._callbacks, "on_viewer_paint_press", None)
        if not self._drawing or not callable(handler):
            return False
        return bool(handler(plane, row, col, "erase" if erase else "paint", self.brush_size()))

    def move(self, plane: str, row: float, col: float) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_move", None)
        if self._drawing and callable(handler):
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
