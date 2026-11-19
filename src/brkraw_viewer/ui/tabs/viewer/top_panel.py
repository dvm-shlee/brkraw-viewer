from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from brkraw_viewer.ui.components.collapsible import CollapsibleSection
from brkraw_viewer.ui.tabs.viewer.roi_tool_box import RoiToolBox
from brkraw_viewer.ui.tabs.viewer.layers_box import LayersBox
from brkraw_viewer.ui.windows.hook_options import refresh_open_dialog, show_hook_options


class ViewerTopPanel(ttk.Frame):
    _GAP = 8
    MIN_VIEWPORT_WIDTH = 480

    def __init__(self, parent: tk.Misc, *, callbacks, on_fold=None) -> None:
        super().__init__(parent)
        self._callbacks = callbacks
        self._on_fold = on_fold
        self._suspend_zoom = False
        self._sections: dict[str, CollapsibleSection] = {}
        self._panel_open = True

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self._handle = ttk.Button(self, text="\u25b8", width=2, command=self.toggle_panel)
        self._handle.grid(row=0, column=0, sticky="ns", padx=(0, 2))

        self._wrap = ttk.Frame(self)
        self._wrap.grid(row=0, column=1, sticky="nsew")
        self._wrap.rowconfigure(0, weight=1)
        self._wrap.columnconfigure(0, weight=1)
        self._canvas = tk.Canvas(
            self._wrap,
            highlightthickness=0,
            borderwidth=0,
            width=1,
            height=1,
            background=ttk.Style(self).lookup("TFrame", "background") or self.cget("background"),
        )
        self._scroll = ttk.Scrollbar(self._wrap, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scroll.grid(row=0, column=1, sticky="ns")
        self._inner = ttk.Frame(self._canvas)
        self._inner.columnconfigure(0, weight=1)
        self._window = self._canvas.create_window(0, 0, window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._on_wheel, add="+")

        def section(title: str, expanded: bool) -> CollapsibleSection:
            sec = CollapsibleSection(self._inner, title, expanded=expanded, on_toggle=lambda _o: self._after_fold())
            sec.grid(row=len(self._sections), column=0, sticky="ew", pady=(0, 4))
            sec.body.columnconfigure(0, weight=1)
            self._sections[title] = sec
            return sec

        sec_orientation = section("Orientation", True)
        sec_tool = section("ROI tool", True)
        sec_hook = section("Hook", False)
        sec_value = section("Value", False)
        sec_control = section("Control", False)
        sec_layers = section("Layers", True)

        self.orientation_frame = ttk.Frame(sec_orientation.body, padding=(4, 2))
        self.orientation_frame.grid(row=0, column=0, sticky="nsew")
        self.orientation_frame.columnconfigure(1, weight=1, uniform="viewer_orientation_cols")
        self.orientation_frame.columnconfigure(2, weight=1, uniform="viewer_orientation_cols")

        ttk.Label(self.orientation_frame, text="Space").grid(row=0, column=0, sticky="w", padx=(0, 4))
        space_radio_frame = ttk.Frame(self.orientation_frame)
        space_radio_frame.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 4))
        self._space_var = tk.StringVar(master=self, value="scanner")
        for label, value in (("raw", "raw"), ("scanner", "scanner"), ("subject_ras", "subject_ras")):
            ttk.Radiobutton(
                space_radio_frame,
                text=label,
                value=value,
                command=lambda v=value: self._on_space(callbacks, v),
                variable=self._space_var,
            ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Label(self.orientation_frame, text="Type").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._subject_type_var = tk.StringVar(master=self, value="Biped")
        self._subject_type_combo = ttk.Combobox(
            self.orientation_frame,
            textvariable=self._subject_type_var,
            state="readonly",
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            width=7,
        )
        self._subject_type_combo.grid(row=1, column=1, sticky="ew", padx=(0, 4))
        self._subject_type_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        ttk.Button(
            self.orientation_frame,
            text="RESET",
            width=6,
            command=lambda: self._on_subject_reset(callbacks),
        ).grid(row=1, column=2, sticky="ew", padx=(4, 0))

        ttk.Label(self.orientation_frame, text="Pose").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
        self._pose_primary_var = tk.StringVar(master=self, value="Head")
        self._pose_secondary_var = tk.StringVar(master=self, value="Supine")
        self._pose_primary_combo = ttk.Combobox(
            self.orientation_frame,
            textvariable=self._pose_primary_var,
            state="readonly",
            values=("Head", "Foot"),
            width=7,
        )
        self._pose_primary_combo.grid(row=2, column=1, sticky="ew", padx=(0, 4), pady=(6, 0))
        self._pose_primary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))
        self._pose_secondary_combo = ttk.Combobox(
            self.orientation_frame,
            textvariable=self._pose_secondary_var,
            state="readonly",
            values=("Supine", "Prone", "Left", "Right"),
            width=7,
        )
        self._pose_secondary_combo.grid(row=2, column=2, sticky="ew", padx=(4, 0), pady=(6, 0))
        self._pose_secondary_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_subject_change(callbacks))

        flip_row = ttk.Frame(self.orientation_frame)
        flip_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(flip_row, text="Flip").pack(side=tk.LEFT, padx=(0, 8))
        self._flip_x_var = tk.BooleanVar(master=self, value=False)
        self._flip_y_var = tk.BooleanVar(master=self, value=False)
        self._flip_z_var = tk.BooleanVar(master=self, value=False)
        ttk.Checkbutton(
            flip_row,
            text="X",
            variable=self._flip_x_var,
            command=lambda: self._on_flip(callbacks, "x"),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Checkbutton(
            flip_row,
            text="Y",
            variable=self._flip_y_var,
            command=lambda: self._on_flip(callbacks, "y"),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Checkbutton(
            flip_row,
            text="Z",
            variable=self._flip_z_var,
            command=lambda: self._on_flip(callbacks, "z"),
        ).pack(side=tk.LEFT)

        self.tool_box = RoiToolBox(sec_tool.body, callbacks=callbacks)
        self.tool_box.configure(text="")  # the section header carries the title
        self.tool_box.grid(row=0, column=0, sticky="nsew")

        hook_frame = ttk.Frame(sec_hook.body, padding=(6, 4))
        hook_frame.grid(row=0, column=0, sticky="nsew")
        hook_frame.columnconfigure(1, weight=1)

        self._hook_name_var = tk.StringVar(master=self, value="Disabled")
        self._hook_enabled_var = tk.BooleanVar(master=self, value=False)
        self._hook_args: dict | None = None

        self._hook_check = ttk.Checkbutton(
            hook_frame,
            text="Apply",
            variable=self._hook_enabled_var,
            command=lambda: self._on_hook_toggle(callbacks),
            state="disabled",
        )
        self._hook_check.grid(row=0, column=0, sticky="w", padx=(0, 6))
        name_entry = ttk.Entry(hook_frame, textvariable=self._hook_name_var, width=10, state="readonly")
        name_entry.grid(row=0, column=1, sticky="ew")
        self._hook_options_button = ttk.Button(
            hook_frame,
            text="Hook Options",
            command=lambda: self._open_hook_options(callbacks),
            state="disabled",
        )
        self._hook_options_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self._value_var = tk.StringVar(master=self, value="-")
        value_frame = ttk.Frame(sec_value.body, padding=(6, 4))
        value_frame.grid(row=0, column=0, sticky="nsew")
        value_frame.columnconfigure(0, weight=1)
        
        self._value_button = ttk.Button(
            value_frame,
            textvariable=self._value_var,
            command=self._on_timecourse,
            state="disabled",
        )
        self._value_button.grid(row=0, column=0, sticky="ew")

        self.control_frame = ttk.Frame(sec_control.body, padding=(6, 4))
        self.control_frame.grid(row=0, column=0, sticky="nsew")
        self.control_frame.columnconfigure(0, weight=1)

        self._crosshair_var = tk.BooleanVar(master=self, value=True)
        self._rgb_var = tk.BooleanVar(master=self, value=False)
        ttk.Checkbutton(
            self.control_frame,
            text="Crosshair",
            variable=self._crosshair_var,
            command=lambda: self._on_crosshair(callbacks),
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._rgb_check = ttk.Checkbutton(
            self.control_frame,
            text="RGB",
            variable=self._rgb_var,
            command=lambda: self._on_rgb(callbacks),
        )
        self._rgb_check.grid(row=1, column=0, sticky="w", pady=(0, 4))
        
        zoom_box = ttk.Frame(self.control_frame)
        zoom_box.grid(row=2, column=0, pady=(4, 0), sticky="ew")
        
        zoom_top = ttk.Frame(zoom_box)
        zoom_top.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(zoom_top, text="Zoom").pack(side=tk.LEFT, padx=(0, 4))
        
        self._zoom_entry_var = tk.StringVar(master=self, value="1.00")
        self._zoom_entry = ttk.Entry(zoom_top, textvariable=self._zoom_entry_var, width=6)
        self._zoom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._zoom_entry.bind("<Return>", self._on_zoom_entry)
        self._zoom_entry.bind("<FocusOut>", self._on_zoom_entry)

        self._zoom_scale = tk.Scale(
            zoom_box,
            from_=1.0,
            to=4.0,
            resolution=0.01,
            digits=3,
            orient=tk.HORIZONTAL,
            showvalue=False,
            length=80,
            command=self._on_zoom,
        )
        self._zoom_scale.set(1.0)
        self._zoom_scale.pack(side=tk.TOP, fill=tk.X, expand=True)

        self.layers_box = LayersBox(sec_layers.body, callbacks=callbacks, on_changed=self.tool_box.refresh)
        self.layers_box.configure(text="")  # the section header carries the title
        self.layers_box.grid(row=0, column=0, sticky="nsew")

    # ---- side panel: scrolling and folding ----

    def _on_inner_configure(self, _event: object = None) -> None:
        try:
            self._canvas.configure(scrollregion=self._canvas.bbox("all"), width=self._inner.winfo_reqwidth())
            if self._inner.winfo_reqheight() <= self._canvas.winfo_height():
                self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass

    def _on_canvas_configure(self, event: tk.Event) -> None:
        try:
            self._canvas.itemconfigure(self._window, width=max(int(event.width), 1))
            if self._inner.winfo_reqheight() <= int(event.height):
                self._canvas.yview_moveto(0.0)
        except tk.TclError:
            pass

    def _on_wheel(self, event: tk.Event) -> None:
        try:
            if not self.winfo_exists() or not self._panel_open:
                return
            target = self.winfo_containing(event.x_root, event.y_root)
            while target is not None and target is not self:
                target = target.master
            if target is None:
                return
            if self._inner.winfo_reqheight() <= self._canvas.winfo_height():
                return
            num = getattr(event, "num", 0)
            if num == 4:
                step = -1
            elif num == 5:
                step = 1
            else:
                delta = int(getattr(event, "delta", 0))
                if delta == 0:
                    return
                step = -1 if delta > 0 else 1
                if abs(delta) >= 120:  # Windows reports multiples of 120; macOS small steps
                    step = int(-delta / 120)
            self._canvas.yview_scroll(step, "units")
        except (tk.TclError, KeyError, AttributeError):
            pass

    @property
    def sections(self) -> dict[str, CollapsibleSection]:
        """The foldable sections by title, in panel order."""
        return dict(self._sections)

    @property
    def panel_open(self) -> bool:
        return self._panel_open

    def toggle_panel(self) -> None:
        self.set_panel_open(not self._panel_open)

    def set_panel_open(self, is_open: bool) -> None:
        is_open = bool(is_open)
        if is_open == self._panel_open:
            return
        self._panel_open = is_open
        if is_open:
            self._wrap.grid()
            self._handle.configure(text="\u25b8")
        else:
            self._wrap.grid_remove()
            self._handle.configure(text="\u25c2")
        self._after_fold()

    def _after_fold(self) -> None:
        # Refresh the scroll region, then run the viewport refit (the one bound to <Configure>) explicitly.
        self.after_idle(self._on_inner_configure)
        if callable(self._on_fold):
            self.after_idle(self._on_fold)

    def panel_width(self) -> int:
        """Width of the open side panel: handle, boxes and scrollbar."""
        return int(
            self._handle.winfo_reqwidth() + self._inner.winfo_reqwidth() + self._scroll.winfo_reqwidth() + self._GAP
        )

    def required_width(self) -> int:
        """Smallest sensible width: the open side panel plus a minimum viewport width."""
        return self.panel_width() + self.MIN_VIEWPORT_WIDTH

    def _on_hook_toggle(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_hook_toggle", None)
        if callable(handler):
            handler(self._hook_enabled_var.get(), self._hook_name_var.get())

    def _open_hook_options(self, callbacks) -> None:
        hook_name = (self._hook_name_var.get() or "").strip()

        def _apply(values: dict) -> None:
            handler = getattr(callbacks, "on_hook_options_apply", None)
            if callable(handler):
                handler(hook_name, values)
                return
            fallback = getattr(callbacks, "on_viewer_hook_args_change", None)
            if callable(fallback):
                fallback(values)
        show_hook_options(self, self, hook_name=hook_name, hook_args=self._hook_args, on_apply=_apply)

    def _on_crosshair(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_crosshair_toggle", None)
        if callable(handler):
            handler(self._crosshair_var.get())

    def _on_rgb(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_rgb_toggle", None)
        if callable(handler):
            handler(self._rgb_var.get())

    def _on_zoom(self, value: str) -> None:
        if self._suspend_zoom:
            return
        val = float(value)
        self._zoom_entry_var.set(f"{val:.2f}")
        handler = getattr(self._callbacks, "on_viewer_zoom_change", None)
        if callable(handler):
            handler(val)

    def _on_zoom_entry(self, _event: tk.Event) -> None:
        try:
            val = float(self._zoom_entry_var.get())
            self._zoom_scale.set(val) 
        except ValueError:
            pass

    def set_zoom_value(self, value: float) -> None:
        self._suspend_zoom = True
        try:
            self._zoom_scale.set(float(value))
            self._zoom_entry_var.set(f"{float(value):.2f}")
        finally:
            self._suspend_zoom = False

    def _on_flip(self, callbacks, axis: str) -> None:
        var = getattr(self, f"_flip_{axis}_var", None)
        if var is None:
            return
        handler = getattr(callbacks, "on_viewer_flip_change", None)
        if callable(handler):
            handler(axis, var.get())

    def set_flip_values(self, x: bool, y: bool, z: bool) -> None:
        self._flip_x_var.set(bool(x))
        self._flip_y_var.set(bool(y))
        self._flip_z_var.set(bool(z))

    def _on_space(self, callbacks, value: str) -> None:
        handler = getattr(callbacks, "on_viewer_space_change", None)
        if callable(handler):
            handler(value)

    def _on_subject_reset(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_subject_reset", None)
        if callable(handler):
            handler()

    def _on_subject_change(self, callbacks) -> None:
        handler = getattr(callbacks, "on_viewer_subject_change", None)
        if callable(handler):
            handler(
                self._subject_type_var.get(),
                self._pose_primary_var.get(),
                self._pose_secondary_var.get(),
            )

    def set_subject_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self._subject_type_combo.configure(state=state)
        self._pose_primary_combo.configure(state=state)
        self._pose_secondary_combo.configure(state=state)

    def set_subject_values(self, subject_type: str, pose_primary: str, pose_secondary: str) -> None:
        if subject_type:
            self._subject_type_var.set(subject_type)
        if pose_primary:
            self._pose_primary_var.set(pose_primary)
        if pose_secondary:
            self._pose_secondary_var.set(pose_secondary)

    def set_hook_state(self, hook_name: str, enabled: bool, *, allow_toggle: bool = True) -> None:
        has_hook = bool(hook_name and hook_name != "None")
        display_name = hook_name if has_hook else "Disabled"
        self._hook_name_var.set(display_name)
        if not has_hook:
            self._hook_enabled_var.set(False)
        else:
            self._hook_enabled_var.set(bool(enabled))
        state = "normal" if allow_toggle and has_hook else "disabled"
        try:
            self._hook_check.configure(state=state)
        except Exception: pass
        try:
            self._hook_options_button.configure(state=state)
        except Exception: pass

    def set_hook_args(self, hook_args: dict | None) -> None:
        self._hook_args = dict(hook_args) if isinstance(hook_args, dict) else None
        # an open Hook Options window shows what was applied, also when it was applied in the Convert tab
        refresh_open_dialog(self, (self._hook_name_var.get() or "").strip(), self._hook_args)

    def set_rgb_state(self, *, enabled: bool, active: bool) -> None:
        self._rgb_var.set(bool(active))
        state = "normal" if enabled else "disabled"
        try:
            self._rgb_check.configure(state=state)
        except Exception: pass

    def set_value_display(self, value_text: str, *, plot_enabled: bool) -> None:
        text = value_text.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        self._value_var.set(text)
        state = "normal" if plot_enabled else "disabled"
        try:
            self._value_button.configure(state=state)
        except Exception: pass

    def _on_timecourse(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_timecourse_toggle", None)
        if callable(handler):
            handler()

    def set_controls_enabled(self, enabled: bool) -> None:
        target_state = "normal" if enabled else "disabled"
        def _recursive_set(widget):
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly" if enabled else "disabled")
                elif isinstance(widget, (ttk.Entry, tk.Entry, ttk.Button, ttk.Checkbutton, ttk.Radiobutton, tk.Scale)):
                    widget.configure(state=target_state)
            except Exception: pass
            for child in widget.winfo_children():
                _recursive_set(child)
        if hasattr(self, "orientation_frame"):
            _recursive_set(self.orientation_frame)
        if hasattr(self, "control_frame"):
            _recursive_set(self.control_frame)


ViewerSidePanel = ViewerTopPanel
