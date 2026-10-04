from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from brkraw_viewer.ui.components.viewport import ViewportCanvas


class ViewerRightPanel(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, callbacks) -> None:
        super().__init__(parent)
        self._callbacks = callbacks
        self._resize_job: Optional[str] = None
        self._value_var = tk.StringVar(value="[ - ]")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        axis_bar = ttk.LabelFrame(self, text="")
        axis_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        axis_bar.columnconfigure(0, weight=1)
        axis_bar.columnconfigure(1, weight=1)
        axis_bar.columnconfigure(2, weight=1)

        def _axis_box(parent: tk.Misc, axis: str, var: tk.IntVar, on_change, column: int):
            pad_x = (0, 6) if column < 2 else (0, 0)
            box = ttk.Frame(parent)
            box.grid(row=0, column=column, sticky="n", padx=pad_x)
            
            row = ttk.Frame(box)
            row.pack(side=tk.TOP, pady=4)
            ttk.Label(row, text=axis).pack(side=tk.LEFT, padx=(0, 4))
            
            def _on_entry(_event):
                try:
                    val = var.get()
                    on_change(val)
                except Exception:
                    pass

            entry = ttk.Entry(row, textvariable=var, width=5)
            entry.pack(side=tk.LEFT, padx=(0, 4))
            entry.bind("<Return>", _on_entry)
            entry.bind("<FocusOut>", _on_entry)

            scale = tk.Scale(
                row,
                from_=0,
                to=0,
                orient=tk.HORIZONTAL,
                showvalue=False,
                command=on_change,
                length=100,
            )
            scale.pack(side=tk.LEFT)
            scale.configure(variable=var)
            return scale

        self._x_var = tk.IntVar(value=0)
        self._y_var = tk.IntVar(value=0)
        self._z_var = tk.IntVar(value=0)

        self._y_scale = _axis_box(axis_bar, "Y", self._y_var, lambda v: self._on_axis(callbacks, "y", v), 0)
        self._z_scale = _axis_box(axis_bar, "Z", self._z_var, lambda v: self._on_axis(callbacks, "z", v), 1)
        self._x_scale = _axis_box(axis_bar, "X", self._x_var, lambda v: self._on_axis(callbacks, "x", v), 2)

        viewer_host = ttk.Frame(self)
        viewer_host.grid(row=1, column=0, sticky="nsew")
        viewer_host.columnconfigure(0, weight=1)
        viewer_host.columnconfigure(1, weight=1)
        viewer_host.columnconfigure(2, weight=1)
        viewer_host.rowconfigure(0, weight=1)
        viewer_host.bind("<Configure>", self._on_resize)

        self._xz = ViewportCanvas(viewer_host)
        self._xy = ViewportCanvas(viewer_host)
        self._zy = ViewportCanvas(viewer_host)

        self._xz.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._xy.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        self._zy.grid(row=0, column=2, sticky="nsew")
        self._xz.set_click_callback(lambda r, c: self._on_view_click("xz", r, c))
        self._xy.set_click_callback(lambda r, c: self._on_view_click("xy", r, c))
        self._zy.set_click_callback(lambda r, c: self._on_view_click("zy", r, c))
        self._xz.set_scroll_callback(lambda d: self._on_view_scroll("xz", d))
        self._xy.set_scroll_callback(lambda d: self._on_view_scroll("xy", d))
        self._zy.set_scroll_callback(lambda d: self._on_view_scroll("zy", d))
        self._last_zoom_source: Optional[str] = None
        self._xz.set_zoom_callback(lambda delta, rc: self._on_view_zoom("xz", delta, rc))
        self._xy.set_zoom_callback(lambda delta, rc: self._on_view_zoom("xy", delta, rc))
        self._zy.set_zoom_callback(lambda delta, rc: self._on_view_zoom("zy", delta, rc))
        self._xz.set_capture_callback(lambda: self._on_view_capture("xz", self._xz))
        self._xy.set_capture_callback(lambda: self._on_view_capture("xy", self._xy))
        self._zy.set_capture_callback(lambda: self._on_view_capture("zy", self._zy))

        bottom_bar = ttk.Frame(self)
        bottom_bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        bottom_bar.columnconfigure(0, weight=0)
        bottom_bar.columnconfigure(1, weight=1)
        bottom_bar.columnconfigure(2, weight=0)
        
        frame_inner = ttk.Frame(bottom_bar)
        frame_inner.grid(row=0, column=0, sticky="w")
        self._frame_var = tk.IntVar(value=0)
        frame_row, self._frame_scale = self._create_slider_row(
            frame_inner, "Frame", self._frame_var, 
            lambda v: self._on_frame(callbacks, v), length=160
        )
        frame_row.pack(side=tk.LEFT)

        extra_frame = ttk.Frame(bottom_bar)
        extra_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._extra_frame = extra_frame
        self._extra_dim_vars: list[tk.IntVar] = []
        self._extra_dim_scales: list[tk.Scale] = []

        slicepack_box = ttk.Frame(bottom_bar)
        slicepack_box.grid(row=0, column=2, sticky="e")
        self._slicepack_var = tk.IntVar(value=0)
        sp_row, self._slicepack_scale = self._create_slider_row(
            slicepack_box, "Slicepack", self._slicepack_var,
            lambda v: self._on_slicepack(callbacks, v), length=160
        )
        sp_row.pack(side=tk.LEFT)

        self._slicepack_box = slicepack_box
        self._frame_box = frame_inner
        self._bottom_bar = bottom_bar
        self._frames_count = 1
        self._slicepacks_count = 1

        self._last_indices: Optional[tuple[int, int, int]] = None
        self._suspend_callbacks = False

    def _create_slider_row(self, parent: tk.Misc, label: str, var: tk.IntVar, command, length: int = 140) -> tuple[ttk.Frame, tk.Scale]:
        row = ttk.Frame(parent)
        ttk.Label(row, text=label).pack(side=tk.LEFT, padx=(0, 4))
        
        def _on_entry(_event):
            try:
                val = var.get()
                command(val)
            except Exception:
                pass

        entry = ttk.Entry(row, textvariable=var, width=5)
        entry.pack(side=tk.LEFT, padx=(0, 4))
        entry.bind("<Return>", _on_entry)
        entry.bind("<FocusOut>", _on_entry)

        scale = tk.Scale(
            row,
            from_=0,
            to=0,
            orient=tk.HORIZONTAL,
            showvalue=False,
            command=command,
            length=length,
        )
        scale.pack(side=tk.LEFT)
        scale.configure(variable=var)
        return row, scale

    def _on_axis(self, callbacks, axis: str, value: str) -> None:
        if self._suspend_callbacks:
            return
        handler = getattr(callbacks, "on_viewer_axis_change", None)
        if callable(handler):
            handler(axis, int(float(value)))

    def _on_frame(self, callbacks, value: str) -> None:
        if self._suspend_callbacks:
            return
        handler = getattr(callbacks, "on_viewer_frame_change", None)
        if callable(handler):
            handler(int(float(value)))

    def _on_view_capture(self, plane: str, viewport: ViewportCanvas) -> None:
        if self._last_indices is None:
            return
        handler = getattr(self._callbacks, "on_viewer_capture", None)
        if not callable(handler):
            return
        try:
            path = handler(plane, self._last_indices)
        except Exception:
            return
        if not path:
            return
        filename = str(path)
        ok = messagebox.askyesno("Viewport Capture", f"Save capture to:\n{filename}")
        if not ok:
            return
        try:
            viewport.capture_to_file(filename)
        except Exception:
            pass

    def _on_slicepack(self, callbacks, value: str) -> None:
        if self._suspend_callbacks:
            return
        handler = getattr(callbacks, "on_viewer_slicepack_change", None)
        if callable(handler):
            handler(int(float(value)))

    def _on_extra_dim(self, index: int, value: str) -> None:
        if self._suspend_callbacks:
            return
        handler = getattr(self._callbacks, "on_viewer_extra_dim_change", None)
        if callable(handler):
            handler(int(index), int(float(value)))

    def _on_view_click(self, plane: str, row: int, col: int) -> None:
        handler = getattr(self._callbacks, "on_viewer_jump", None)
        if not callable(handler):
            return
        xi = self._x_var.get()
        yi = self._y_var.get()
        zi = self._z_var.get()
        if plane == "xz":
            zi, xi = int(row), int(col)
        elif plane == "xy":
            yi, xi = int(row), int(col)
        elif plane == "zy":
            yi, zi = int(row), int(col)
        handler(xi, yi, zi)

    def _on_view_scroll(self, plane: str, direction: int) -> None:
        if self._suspend_callbacks:
            return
        axis = None
        var = None
        scale = None
        if plane == "xy":
            axis, var, scale = "z", self._z_var, self._z_scale
        elif plane == "xz":
            axis, var, scale = "y", self._y_var, self._y_scale
        elif plane == "zy":
            axis, var, scale = "x", self._x_var, self._x_scale
        if axis is None or var is None or scale is None:
            return
        try:
            max_val = int(scale.cget("to"))
        except Exception:
            max_val = 0
        cur = int(var.get())
        step = 1 if int(direction) > 0 else -1
        nxt = max(0, min(max_val, cur + step))
        if nxt == cur:
            return
        var.set(nxt)
        handler = getattr(self._callbacks, "on_viewer_axis_change", None)
        if callable(handler):
            handler(axis, int(nxt))

    def _on_view_zoom(self, plane: str, delta: float, rc: Optional[tuple[int, int]]) -> None:
        self._last_zoom_source = str(plane)
        handler = getattr(self._callbacks, "on_viewer_zoom_step", None)
        if callable(handler):
            handler(float(delta), str(plane), rc)

    def set_ranges(self, *, x: int, y: int, z: int, frames: int, slicepacks: int) -> None:
        self._x_scale.configure(to=max(x - 1, 0))
        self._y_scale.configure(to=max(y - 1, 0))
        self._z_scale.configure(to=max(z - 1, 0))
        self._frame_scale.configure(to=max(frames - 1, 0))
        self._slicepack_scale.configure(to=max(slicepacks - 1, 0))
        self._frames_count = max(int(frames), 1)
        self._slicepacks_count = max(int(slicepacks), 1)
        if self._frames_count <= 1:
            self._frame_box.grid_remove()
        else:
            self._frame_box.grid()
        if self._slicepacks_count <= 1:
            self._slicepack_box.grid_remove()
        else:
            self._slicepack_box.grid()
        self._update_bottom_visibility()

    def set_extra_dims(self, sizes: list[int], indices: list[int]) -> None:
        if not sizes:
            for widget in self._extra_frame.winfo_children():
                widget.destroy()
            self._extra_dim_vars = []
            self._extra_dim_scales = []
            self._extra_frame.grid_remove()
            self._update_bottom_visibility()
            return
        if len(self._extra_dim_scales) != len(sizes):
            for widget in self._extra_frame.winfo_children():
                widget.destroy()
            self._extra_dim_vars = []
            self._extra_dim_scales = []
            for idx, size in enumerate(sizes):
                var = tk.IntVar(value=0)
                row, scale = self._create_slider_row(
                    self._extra_frame, f"Dim {idx + 5}", var,
                    lambda v, i=idx: self._on_extra_dim(i, v), length=160
                )
                row.grid(row=0, column=idx, sticky="w", padx=(0, 10))
                self._extra_dim_vars.append(var)
                self._extra_dim_scales.append(scale)
        for idx, size in enumerate(sizes):
            try:
                self._extra_dim_scales[idx].configure(to=max(int(size) - 1, 0))
            except Exception:
                pass
            if idx < len(indices):
                self._extra_dim_vars[idx].set(int(indices[idx]))
        self._extra_frame.grid()
        self._update_bottom_visibility()

    def _update_bottom_visibility(self) -> None:
        has_extra = bool(self._extra_dim_scales)
        if self._frames_count <= 1 and self._slicepacks_count <= 1 and not has_extra:
            self._bottom_bar.grid_remove()
        else:
            self._bottom_bar.grid()

    def set_indices(self, *, x: int, y: int, z: int, frame: int, slicepack: int) -> None:
        self._suspend_callbacks = True
        try:
            self._x_var.set(int(x))
            self._y_var.set(int(y))
            self._z_var.set(int(z))
            self._frame_var.set(int(frame))
            self._slicepack_var.set(int(slicepack))
        finally:
            self._suspend_callbacks = False

    def set_views(
        self,
        views: dict,
        *,
        indices: Optional[tuple[int, int, int]] = None,
        res: Optional[dict[str, tuple[float, float]]] = None,
        crosshair: Optional[dict] = None,
        show_crosshair: bool = False,
        lock_scale: bool = True,
        allow_overflow: bool = False,
        overflow_blend: float | None = None,
        zoom_scale: float | None = None,
        window: tuple[float, float] | None = None,
    ) -> None:
        self._last_indices = indices
        if not views:
            self._xz.clear()
            self._xy.clear()
            self._zy.clear()
            return
        crosshair = crosshair or {}
        res = res or {}
        # Shared scale ensures planes stay consistent; blend fit/fill and apply zoom.
        lock_mm_per_px = (
            self._compute_shared_mm_per_px(
                views,
                res,
                fill=allow_overflow,
                overflow_blend=overflow_blend,
                zoom_scale=zoom_scale,
            )
            if lock_scale
            else None
        )
        if "xz" in views:
            self._xz.set_view(
                base=views["xz"],
                title=f"X-Z (y={indices[1] if indices else 0})",
                res=res.get("xz", (1.0, 1.0)),
                crosshair=crosshair.get("xz"),
                focus_rc=crosshair.get("xz"),
                use_cursor_focus=self._last_zoom_source == "xz",
                show_crosshair=show_crosshair,
                mm_per_px=lock_mm_per_px,
                allow_overflow=allow_overflow,
                zoom_scale=zoom_scale,
                window=window,
            )
        if "xy" in views:
            self._xy.set_view(
                base=views["xy"],
                title=f"X-Y (z={indices[2] if indices else 0})",
                res=res.get("xy", (1.0, 1.0)),
                crosshair=crosshair.get("xy"),
                focus_rc=crosshair.get("xy"),
                use_cursor_focus=self._last_zoom_source == "xy",
                show_crosshair=show_crosshair,
                mm_per_px=lock_mm_per_px,
                allow_overflow=allow_overflow,
                zoom_scale=zoom_scale,
                window=window,
            )
        if "zy" in views:
            self._zy.set_view(
                base=views["zy"],
                title=f"Z-Y (x={indices[0] if indices else 0})",
                res=res.get("zy", (1.0, 1.0)),
                crosshair=crosshair.get("zy"),
                focus_rc=crosshair.get("zy"),
                use_cursor_focus=self._last_zoom_source == "zy",
                show_crosshair=show_crosshair,
                mm_per_px=lock_mm_per_px,
                allow_overflow=allow_overflow,
                zoom_scale=zoom_scale,
                window=window,
            )
        self._last_zoom_source = None

    def _compute_shared_mm_per_px(
        self,
        views: dict,
        res: dict[str, tuple[float, float]],
        *,
        fill: bool = False,
        overflow_blend: float | None = None,
        zoom_scale: float | None = None,
    ) -> Optional[float]:
        candidates: list[float] = []
        for plane, viewport in (("xz", self._xz), ("xy", self._xy), ("zy", self._zy)):
            base = views.get(plane)
            if base is None:
                continue
            shape = getattr(base, "shape", None)
            if not shape or len(shape) < 2:
                continue
            rows = int(shape[0])
            cols = int(shape[1])
            row_res, col_res = res.get(plane, (1.0, 1.0))
            try:
                width_mm = float(cols) * float(col_res)
                height_mm = float(rows) * float(row_res)
            except Exception:
                continue
            if width_mm <= 0 or height_mm <= 0:
                continue
            cw, ch = viewport.get_canvas_size()
            if cw < 8 or ch < 8:
                continue
            fit_mm = max(width_mm / float(cw), height_mm / float(ch))
            fill_mm = min(width_mm / float(cw), height_mm / float(ch))
            if overflow_blend is not None:
                blend = max(0.0, min(float(overflow_blend), 1.0))
                target_mm = fit_mm - (fit_mm - fill_mm) * blend
            elif fill:
                target_mm = fill_mm
            else:
                target_mm = fit_mm
            if zoom_scale is not None:
                try:
                    zs = float(zoom_scale)
                    if zs > 0:
                        target_mm = target_mm / zs
                except Exception:
                    pass
            candidates.append(target_mm)
        if not candidates:
            return None
        if overflow_blend is not None:
            return max(candidates)
        if fill:
            # Use the narrow-side fit as the fill target, with a small buffer.
            min_mm = min(candidates)
            max_mm = max(candidates)
            relaxed = min_mm * 1.05
            return min(relaxed, max_mm)
        return max(candidates)

    def _on_resize(self, *_: object) -> None:
        handler = getattr(self._callbacks, "on_viewer_resize", None)
        if not callable(handler):
            return
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.after(50, handler)
