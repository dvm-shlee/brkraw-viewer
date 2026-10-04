from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .top_panel import ViewerTopPanel
from .left_panel import ViewerLeftPanel
from .right_panel import ViewerRightPanel
from .status_bar import ViewerStatusBar


class ViewerTab:
    TITLE = "Viewer"

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=0)
        self.frame.rowconfigure(1, weight=1)
        self.frame.rowconfigure(2, weight=0)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        setattr(self.frame, "_tab_instance", self)

        self.top = ViewerTopPanel(self.frame, callbacks=self._cb)
        self.top.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        self.right = ViewerRightPanel(self.frame, callbacks=self._cb)
        self.right.grid(row=1, column=0, sticky="nsew", padx=8)

        self.status = ViewerStatusBar(self.frame)
        self.status.grid(row=2, column=0, sticky="ew", padx=8, pady=(6, 8))

    def set_views(
        self,
        views: dict,
        *,
        indices: tuple[int, int, int] | None = None,
        res: dict[str, tuple[float, float]] | None = None,
        crosshair: dict | None = None,
        show_crosshair: bool = False,
        lock_scale: bool = True,
        allow_overflow: bool = False,
        overflow_blend: float | None = None,
        zoom_scale: float | None = None,
        window: tuple[float, float] | None = None,
        layers: dict | None = None,
    ) -> None:
        self.right.set_views(
            views,
            indices=indices,
            res=res,
            crosshair=crosshair,
            show_crosshair=show_crosshair,
            lock_scale=lock_scale,
            allow_overflow=allow_overflow,
            overflow_blend=overflow_blend,
            zoom_scale=zoom_scale,
            window=window,
            layers=layers,
        )

    def set_subject_enabled(self, enabled: bool) -> None:
        self.top.set_subject_enabled(enabled)

    def set_status(self, text: str) -> None:
        self.status.set_text(text)

    def set_subject_values(self, subject_type: str, pose_primary: str, pose_secondary: str) -> None:
        self.top.set_subject_values(subject_type, pose_primary, pose_secondary)

    def set_hook_state(self, hook_name: str, enabled: bool, *, allow_toggle: bool = True) -> None:
        self.top.set_hook_state(hook_name, enabled, allow_toggle=allow_toggle)

    def set_hook_args(self, hook_args: dict | None) -> None:
        self.top.set_hook_args(hook_args)

    def set_rgb_state(self, *, enabled: bool, active: bool) -> None:
        self.top.set_rgb_state(enabled=enabled, active=active)

    def set_zoom_value(self, value: float) -> None:
        self.top.set_zoom_value(value)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.top.set_controls_enabled(enabled)

    def set_value_display(self, value_text: str, *, plot_enabled: bool) -> None:
        self.top.set_value_display(value_text, plot_enabled=plot_enabled)
