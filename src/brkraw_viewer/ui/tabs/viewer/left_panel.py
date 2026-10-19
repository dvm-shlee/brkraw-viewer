from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ViewerLeftPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, callbacks) -> None:
        super().__init__(parent)
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="Axes").grid(row=0, column=0, sticky="w", pady=(0, 4))

        self._x_var = tk.IntVar(master=self, value=0)
        self._y_var = tk.IntVar(master=self, value=0)
        self._z_var = tk.IntVar(master=self, value=0)
        self._frame_var = tk.IntVar(master=self, value=0)

        self._x_row, self._x_scale = self._axis_scale("X", self._x_var, lambda v: self._on_axis(callbacks, "x", v))
        self._x_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self._y_row, self._y_scale = self._axis_scale("Y", self._y_var, lambda v: self._on_axis(callbacks, "y", v))
        self._y_row.grid(row=2, column=0, sticky="ew", pady=(0, 4))

        self._z_row, self._z_scale = self._axis_scale("Z", self._z_var, lambda v: self._on_axis(callbacks, "z", v))
        self._z_row.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        ttk.Label(self, text="Frame").grid(row=4, column=0, sticky="w")
        self._frame_scale = tk.Scale(
            self,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            variable=self._frame_var,
            command=lambda v: self._on_frame(callbacks, v),
            length=180,
        )
        self._frame_scale.grid(row=5, column=0, sticky="ew")

    def _axis_scale(self, label: str, var: tk.IntVar, command) -> tuple[ttk.Frame, tk.Scale]:
        row = ttk.Frame(self)
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text=label).grid(row=0, column=0, sticky="w")
        scale = tk.Scale(
            row,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=True,
            variable=var,
            command=command,
            length=160,
        )
        scale.grid(row=0, column=1, sticky="ew")
        return row, scale

    def _on_axis(self, callbacks, axis: str, value: str) -> None:
        handler = getattr(callbacks, "on_viewer_axis_change", None)
        if callable(handler):
            handler(axis, int(float(value)))

    def _on_frame(self, callbacks, value: str) -> None:
        handler = getattr(callbacks, "on_viewer_frame_change", None)
        if callable(handler):
            handler(int(float(value)))

    def set_ranges(self, *, x: int, y: int, z: int, frames: int) -> None:
        self._x_scale.configure(to=max(x - 1, 0))
        self._y_scale.configure(to=max(y - 1, 0))
        self._z_scale.configure(to=max(z - 1, 0))
        self._frame_scale.configure(to=max(frames - 1, 0))

    def set_indices(self, *, x: int, y: int, z: int, frame: int) -> None:
        self._x_var.set(int(x))
        self._y_var.set(int(y))
        self._z_var.set(int(z))
        self._frame_var.set(int(frame))
