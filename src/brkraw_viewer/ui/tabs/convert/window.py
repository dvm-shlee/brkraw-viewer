from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Any

from brkraw_viewer.ui.windows.hook_options import HookOptionsDialog, show_hook_options

class ConvertTab:
    TITLE = "Convert"

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        setattr(self.frame, "_tab_instance", self)

        # scrollable container for tall layouts
        self._canvas = tk.Canvas(self.frame, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._scrollbar.grid(row=0, column=1, sticky="ns")
        self._content = ttk.Frame(self._canvas)
        self._content_id = self._canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel()

        # layout vars
        self._layout_source_var = tk.StringVar(value="Config")
        self._layout_auto_var = tk.BooleanVar(value=True)
        self._layout_rule_var = tk.StringVar(value="")
        self._layout_info_spec_var = tk.StringVar(value="")
        self._layout_metadata_spec_var = tk.StringVar(value="")
        self._layout_context_map_var = tk.StringVar(value="")
        self._layout_template_var = tk.StringVar(value="")
        self._layout_template_manual = ""
        self._slicepack_suffix_var = tk.StringVar(value="_slpack{index}")
        self._layout_source_combo: Optional[ttk.Combobox] = None
        self._layout_template_entry: Optional[ttk.Entry] = None
        self._layout_key_listbox: Optional[tk.Listbox] = None
        self._layout_key_add_button: Optional[ttk.Button] = None
        self._layout_key_remove_button: Optional[ttk.Button] = None
        self._layout_syncing = False

        # output vars
        self._output_dir_var = tk.StringVar(value=os.getcwd())
        self._output_dir_var.trace_add("write", lambda *_: self._on_output_dir_change())
        self._convert_sidecar_var = tk.BooleanVar(value=False)
        self._convert_sidecar_format_var = tk.StringVar(value="json")
        self._use_viewer_orientation_var = tk.BooleanVar(value=True)
        self._space_var = tk.StringVar(value="scanner")
        self._subject_type_var = tk.StringVar(value="Biped")
        self._pose_primary_var = tk.StringVar(value="Head")
        self._pose_secondary_var = tk.StringVar(value="Supine")
        self._flip_x_var = tk.BooleanVar(value=False)
        self._flip_y_var = tk.BooleanVar(value=False)
        self._flip_z_var = tk.BooleanVar(value=False)
        self._use_viewer_check: Optional[ttk.Checkbutton] = None
        self._flip_x_check: Optional[ttk.Checkbutton] = None
        self._flip_y_check: Optional[ttk.Checkbutton] = None
        self._flip_z_check: Optional[ttk.Checkbutton] = None

        # hook vars
        self._hook_enabled_var = tk.BooleanVar(value=True)
        self._hook_name_var = tk.StringVar(value="None")
        self._hook_args: Optional[dict] = None
        self._hook_options_dialog: Optional[HookOptionsDialog] = None

        self._build()
        self._update_convert_space_controls()
        self._layout_template_var.trace_add("write", lambda *_: self._on_layout_template_change())
        self._refresh_scroll_region()

    def _build(self) -> None:
        root = self._content
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        main_grid = ttk.Frame(root, padding=(6, 6))
        main_grid.grid(row=0, column=0, sticky="nsew")
        main_grid.columnconfigure(0, weight=1, uniform="convert_cols")
        main_grid.columnconfigure(1, weight=1, uniform="convert_cols")
        main_grid.rowconfigure(0, weight=0)
        main_grid.rowconfigure(1, weight=1)

        layout_left = ttk.Frame(main_grid)
        layout_left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 6))
        layout_left.columnconfigure(1, weight=1)
        layout_left.columnconfigure(2, weight=0)

        ttk.Label(layout_left, text="Layout source").grid(row=0, column=0, sticky="w")
        self._layout_source_combo = ttk.Combobox(
            layout_left,
            textvariable=self._layout_source_var,
            values=("GUI template", "Context map", "Config"),
            state="readonly",
            width=14,
        )
        self._layout_source_combo.grid(row=0, column=1, sticky="ew")
        self._layout_source_combo.bind("<<ComboboxSelected>>", lambda *_: self._update_layout_controls())
        ttk.Checkbutton(
            layout_left,
            text="Auto",
            variable=self._layout_auto_var,
            command=self._update_layout_controls,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(layout_left, text="Rule").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(layout_left, textvariable=self._layout_rule_var, state="readonly").grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ttk.Label(layout_left, text="Info spec").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(layout_left, textvariable=self._layout_info_spec_var, state="readonly").grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk.Label(layout_left, text="Metadata spec").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(layout_left, textvariable=self._layout_metadata_spec_var, state="readonly").grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk.Label(layout_left, text="Context map").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(layout_left, textvariable=self._layout_context_map_var, state="readonly").grid(
            row=4, column=1, columnspan=2, sticky="ew", pady=(6, 0)
        )
        ttk.Label(layout_left, text="Template").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self._layout_template_entry = ttk.Entry(layout_left, textvariable=self._layout_template_var)
        self._layout_template_entry.grid(
            row=5, column=1, columnspan=2, sticky="ew", pady=(10, 0)
        )
        ttk.Label(layout_left, text="Slicepack suffix").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(layout_left, textvariable=self._slicepack_suffix_var, state="readonly").grid(
            row=6, column=1, columnspan=2, sticky="ew", pady=(6, 0)
        )

        keys_frame = ttk.LabelFrame(main_grid, text="Keys", padding=(6, 6))
        keys_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 6))
        keys_frame.columnconfigure(0, weight=1)
        keys_frame.rowconfigure(1, weight=1)
        self._layout_key_listbox = tk.Listbox(keys_frame, width=28, height=10, exportselection=False)
        self._layout_key_listbox.grid(row=1, column=0, sticky="nsew")
        keys_scroll = ttk.Scrollbar(keys_frame, orient="vertical", command=self._layout_key_listbox.yview)
        keys_scroll.grid(row=1, column=1, sticky="ns")
        self._layout_key_listbox.configure(yscrollcommand=keys_scroll.set)
        self._layout_key_listbox.bind("<Double-Button-1>", lambda *_: self._add_selected_layout_key())
        key_buttons = ttk.Frame(keys_frame)
        key_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        key_buttons.columnconfigure(0, weight=1)
        key_buttons.columnconfigure(1, weight=1)
        self._layout_key_add_button = ttk.Button(key_buttons, text="+", command=self._add_selected_layout_key)
        self._layout_key_add_button.grid(row=0, column=0, sticky="ew")
        self._layout_key_remove_button = ttk.Button(key_buttons, text="-", command=self._remove_selected_layout_key)
        self._layout_key_remove_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        convert_left = ttk.Frame(main_grid)
        convert_left.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(6, 0))
        convert_left.columnconfigure(0, weight=1)

        output_row = ttk.Frame(convert_left)
        output_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        output_row.columnconfigure(1, weight=1)
        ttk.Label(output_row, text="Output folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(output_row, textvariable=self._output_dir_var).grid(row=0, column=1, sticky="ew", padx=(8, 6))
        ttk.Button(output_row, text="Browse", command=self._browse_output_dir).grid(row=0, column=2, sticky="e")

        sidecar_row = ttk.Frame(convert_left)
        sidecar_row.grid(row=1, column=0, sticky="w", pady=(0, 10))
        ttk.Checkbutton(
            sidecar_row,
            text="Metadata Sidecar",
            variable=self._convert_sidecar_var,
            command=self._update_sidecar_controls,
        ).pack(side=tk.LEFT)
        self._sidecar_format_frame = ttk.Frame(sidecar_row)
        self._sidecar_format_frame.pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(self._sidecar_format_frame, text="Format").pack(side=tk.LEFT)
        ttk.Radiobutton(
            self._sidecar_format_frame,
            text="JSON",
            value="json",
            variable=self._convert_sidecar_format_var,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Radiobutton(
            self._sidecar_format_frame,
            text="YAML",
            value="yaml",
            variable=self._convert_sidecar_format_var,
        ).pack(side=tk.LEFT, padx=(6, 0))

        use_viewer_row = ttk.Frame(convert_left)
        use_viewer_row.grid(row=2, column=0, sticky="w")
        self._use_viewer_check = ttk.Checkbutton(
            use_viewer_row,
            text="Use Viewer orientation",
            variable=self._use_viewer_orientation_var,
            command=self._on_use_viewer_orientation_toggle,
        )
        self._use_viewer_check.pack(side=tk.LEFT)

        space_row = ttk.Frame(convert_left)
        space_row.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        space_row.columnconfigure(1, weight=1, uniform="orient")
        ttk.Label(space_row, text="Space").grid(row=0, column=0, sticky="w")
        self._space_combo = ttk.Combobox(
            space_row,
            textvariable=self._space_var,
            values=("raw", "scanner", "subject_ras"),
            state="readonly",
            width=14,
        )
        self._space_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._space_combo.bind("<<ComboboxSelected>>", lambda *_: self._update_convert_space_controls())

        subject_row = ttk.Frame(convert_left)
        subject_row.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        subject_row.columnconfigure(1, weight=1)
        ttk.Label(subject_row, text="Subject Type").grid(row=0, column=0, sticky="w")
        self._subject_type_combo = ttk.Combobox(
            subject_row,
            textvariable=self._subject_type_var,
            values=("Biped", "Quadruped", "Phantom", "Other", "OtherAnimal"),
            state="disabled",
        )
        self._subject_type_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        pose_row = ttk.Frame(convert_left)
        pose_row.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        pose_row.columnconfigure(1, weight=1, uniform="orient")
        pose_row.columnconfigure(2, weight=1, uniform="orient")
        ttk.Label(pose_row, text="Pose").grid(row=0, column=0, sticky="w")
        self._pose_primary_combo = ttk.Combobox(
            pose_row,
            textvariable=self._pose_primary_var,
            values=("Head", "Foot"),
            state="disabled",
        )
        self._pose_primary_combo.grid(row=0, column=1, sticky="ew", padx=(8, 4))
        self._pose_secondary_combo = ttk.Combobox(
            pose_row,
            textvariable=self._pose_secondary_var,
            values=("Supine", "Prone", "Left", "Right"),
            state="disabled",
        )
        self._pose_secondary_combo.grid(row=0, column=2, sticky="ew")

        flip_row = ttk.Frame(convert_left)
        flip_row.grid(row=6, column=0, sticky="w", pady=(0, 0))
        ttk.Label(flip_row, text="Flip").pack(side=tk.LEFT, padx=(0, 6))
        self._flip_x_check = ttk.Checkbutton(flip_row, text="X", variable=self._flip_x_var)
        self._flip_x_check.pack(side=tk.LEFT)
        self._flip_y_check = ttk.Checkbutton(flip_row, text="Y", variable=self._flip_y_var)
        self._flip_y_check.pack(side=tk.LEFT, padx=(6, 0))
        self._flip_z_check = ttk.Checkbutton(flip_row, text="Z", variable=self._flip_z_var)
        self._flip_z_check.pack(side=tk.LEFT, padx=(6, 0))

        hook_frame = ttk.LabelFrame(convert_left, text="", padding=(6, 6))
        hook_frame.grid(row=7, column=0, sticky="ew", pady=(0, 0))
        hook_frame.columnconfigure(2, weight=1)
        ttk.Checkbutton(
            hook_frame,
            text="",
            variable=self._hook_enabled_var,
            command=self._on_hook_toggle,
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(hook_frame, text="Available Hook:").grid(row=0, column=1, sticky="w")
        ttk.Label(hook_frame, textvariable=self._hook_name_var).grid(row=0, column=2, sticky="w", padx=(6, 0))
        ttk.Button(
            hook_frame,
            text="Edit Options",
            command=self._open_hook_options,
        ).grid(row=0, column=3, sticky="e", padx=(8, 0))

        actions = ttk.Frame(convert_left)
        actions.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1, uniform="convert_actions")
        actions.columnconfigure(1, weight=1, uniform="convert_actions")
        ttk.Button(actions, text="Preview Outputs", command=self._on_preview).grid(row=0, column=0, sticky="ew")
        ttk.Button(actions, text="Convert", command=self._on_convert).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        preview_box = ttk.LabelFrame(main_grid, text="Output Preview", padding=(6, 6))
        preview_box.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(6, 0))
        preview_box.columnconfigure(0, weight=1)
        preview_box.columnconfigure(1, weight=0)
        preview_box.rowconfigure(0, weight=1)
        preview_box.rowconfigure(1, weight=0)

        self._settings_text = tk.Text(preview_box, wrap="word", height=10)
        self._settings_text.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        settings_scroll = ttk.Scrollbar(preview_box, orient="vertical", command=self._settings_text.yview)
        settings_scroll.grid(row=0, column=1, sticky="ns", pady=(0, 6))
        self._settings_text.configure(yscrollcommand=settings_scroll.set)
        self._settings_text.configure(state=tk.DISABLED)

        self._preview_text = tk.Text(preview_box, wrap="none", height=3)
        self._preview_text.grid(row=1, column=0, sticky="ew")
        preview_scroll_y = ttk.Scrollbar(preview_box, orient="vertical", command=self._preview_text.yview)
        preview_scroll_y.grid(row=1, column=1, sticky="ns")
        preview_scroll_x = ttk.Scrollbar(preview_box, orient="horizontal", command=self._preview_text.xview)
        preview_scroll_x.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._preview_text.configure(yscrollcommand=preview_scroll_y.set, xscrollcommand=preview_scroll_x.set)
        self._preview_text.configure(state=tk.DISABLED)

        self._update_sidecar_controls()
        self._update_convert_space_controls()
        self._update_layout_controls()

    def _on_content_configure(self, _event: tk.Event) -> None:
        self._refresh_scroll_region()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        try:
            self._canvas.itemconfigure(self._content_id, width=event.width)
        except Exception:
            pass
        self._refresh_scroll_region()

    def _bind_mousewheel(self) -> None:
        # Bind once to ensure handler exists for refresh_scroll_region.
        try:
            self._canvas.bind("<MouseWheel>", self._on_mousewheel, add="+")
            self._canvas.bind("<Button-4>", self._on_mousewheel, add="+")
            self._canvas.bind("<Button-5>", self._on_mousewheel, add="+")
        except Exception:
            pass
        try:
            self._content.bind("<MouseWheel>", self._on_mousewheel, add="+")
            self._content.bind("<Button-4>", self._on_mousewheel, add="+")
            self._content.bind("<Button-5>", self._on_mousewheel, add="+")
        except Exception:
            pass

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            if event.num == 4:
                self._canvas.yview_scroll(-1, "units")
                return
            if event.num == 5:
                self._canvas.yview_scroll(1, "units")
                return
            delta = int(getattr(event, "delta", 0))
            if delta != 0:
                self._canvas.yview_scroll(int(-delta / 120), "units")
        except Exception:
            pass

    def _refresh_scroll_region(self) -> None:
        try:
            self._content.update_idletasks()
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        except Exception:
            pass

        for widget in (self._canvas, self._content):
            try:
                widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
                widget.bind("<Button-4>", self._on_mousewheel, add="+")
                widget.bind("<Button-5>", self._on_mousewheel, add="+")
            except Exception:
                pass
    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output directory")
        if path:
            self._output_dir_var.set(path)

    def _update_sidecar_controls(self) -> None:
        enabled = bool(self._convert_sidecar_var.get())
        for child in self._sidecar_format_frame.winfo_children():
            state = "normal" if enabled else "disabled"
            if isinstance(child, ttk.Widget):
                try:
                    child.state(["!disabled"] if enabled else ["disabled"])
                    continue
                except Exception:
                    pass
            cfg: Any = getattr(child, "configure", None)
            if callable(cfg):
                try:
                    cfg(state=state)
                except Exception:
                    pass

    def _update_convert_space_controls(self) -> None:
        use_viewer = self._use_viewer_orientation_var.get()
        state = "disabled" if use_viewer else "readonly"
        if self._space_combo is not None:
            try:
                if use_viewer:
                    self._space_combo.state(["disabled"])
                else:
                    self._space_combo.state(["!disabled", "readonly"])
            except Exception:
                pass
        if self._subject_type_combo is not None:
            try:
                if use_viewer:
                    self._subject_type_combo.state(["disabled"])
                else:
                    self._subject_type_combo.state(["!disabled", "readonly"])
            except Exception:
                pass
        if self._pose_primary_combo is not None:
            try:
                if use_viewer:
                    self._pose_primary_combo.state(["disabled"])
                else:
                    self._pose_primary_combo.state(["!disabled", "readonly"])
            except Exception:
                pass
        if self._pose_secondary_combo is not None:
            try:
                if use_viewer:
                    self._pose_secondary_combo.state(["disabled"])
                else:
                    self._pose_secondary_combo.state(["!disabled", "readonly"])
            except Exception:
                pass
        flip_state = tk.DISABLED if use_viewer else tk.NORMAL
        for btn in (self._flip_x_check, self._flip_y_check, self._flip_z_check):
            if btn is None:
                continue
            try:
                btn.configure(state=flip_state)
            except Exception:
                pass

    def _on_use_viewer_orientation_toggle(self) -> None:
        self._update_convert_space_controls()
        handler = getattr(self._cb, "on_convert_use_viewer_orientation_change", None)
        if callable(handler):
            handler(self._use_viewer_orientation_var.get())

    def _update_layout_controls(self) -> None:
        self._sync_layout_source_state()
        editable = self._layout_template_enabled()
        if self._layout_template_entry is not None:
            try:
                if editable:
                    self._layout_template_entry.state(["!disabled"])
                else:
                    self._layout_template_entry.state(["disabled"])
            except Exception:
                pass
        list_state = tk.NORMAL if editable else tk.DISABLED
        if self._layout_key_listbox is not None:
            try:
                self._layout_key_listbox.configure(state=list_state)
            except Exception:
                pass
        for btn in (self._layout_key_add_button, self._layout_key_remove_button):
            if btn is None:
                continue
            try:
                btn.configure(state=tk.NORMAL if editable else tk.DISABLED)
            except Exception:
                pass
        if not editable:
            if self._layout_key_listbox is not None:
                try:
                    self._layout_key_listbox.selection_clear(0, tk.END)
                except Exception:
                    pass
        self._emit_layout_change()

    def _selected_layout_key(self) -> Optional[str]:
        if self._layout_key_listbox is None:
            return None
        selection = self._layout_key_listbox.curselection()
        if not selection:
            return None
        return str(self._layout_key_listbox.get(int(selection[0])))

    def _layout_template_enabled(self) -> bool:
        if self._layout_auto_var.get():
            return False
        return (self._layout_source_var.get() or "") == "GUI template"

    def _layout_source_choices(self) -> list[str]:
        return ["GUI template", "Context map", "Config"]

    def _sync_layout_source_state(self) -> None:
        if self._layout_source_combo is None:
            return
        if bool(self._layout_auto_var.get()):
            self._layout_source_combo.configure(state="disabled")
            return
        self._layout_source_combo.configure(state="readonly")
        if self._layout_source_var.get() not in self._layout_source_choices():
            self._layout_source_var.set("Config")

    def _on_layout_template_change(self) -> None:
        if not bool(self._layout_auto_var.get()):
            self._layout_template_manual = (self._layout_template_var.get() or "")
        self._emit_layout_change()

    def _emit_layout_change(self) -> None:
        if self._layout_syncing:
            return
        handler = getattr(self._cb, "on_convert_layout_change", None)
        if callable(handler):
            handler(
                self._layout_source_var.get(),
                bool(self._layout_auto_var.get()),
                self._layout_template_var.get(),
            )

    def _add_selected_layout_key(self) -> None:
        key = self._selected_layout_key()
        if not key:
            return
        if not self._layout_template_enabled():
            messagebox.showinfo("Layout", "Template editing is disabled when Auto is enabled.")
            return
        current = self._layout_template_var.get() or ""
        self._layout_template_var.set(f"{current}{{{key}}}")

    def _remove_selected_layout_key(self) -> None:
        key = self._selected_layout_key()
        if not key:
            return
        if not self._layout_template_enabled():
            messagebox.showinfo("Layout", "Template editing is disabled when Auto is enabled.")
            return
        current = self._layout_template_var.get() or ""
        token = f"{{{key}}}"
        idx = current.find(token)
        if idx < 0:
            return
        self._layout_template_var.set(current[:idx] + current[idx + len(token):])

    def _on_preview(self) -> None:
        handler = getattr(self._cb, "on_convert_preview", None)
        if not callable(handler):
            messagebox.showerror("Convert", "Preview handler not wired.")
            return
        handler(
            output_dir=self._output_dir_var.get(),
            layout_source=self._layout_source_var.get(),
            layout_auto=self._layout_auto_var.get(),
            layout_template=self._layout_template_var.get(),
            slicepack_suffix=self._slicepack_suffix_var.get(),
            sidecar_enabled=self._convert_sidecar_var.get(),
            sidecar_format=self._convert_sidecar_format_var.get(),
        )

    def _on_output_dir_change(self) -> None:
        handler = getattr(self._cb, "on_convert_output_dir_change", None)
        if callable(handler):
            handler(self._output_dir_var.get())

    def _open_hook_options(self) -> None:
        hook_name = (self._hook_name_var.get() or "").strip()
        if not hook_name or hook_name == "None":
            return

        def _apply(values: dict) -> None:
            self._hook_args = dict(values)
            handler = getattr(self._cb, "on_convert_hook_options_apply", None)
            if callable(handler):
                handler(hook_name, self._hook_args)

        show_hook_options(
            self,
            self.frame,
            hook_name=hook_name,
            hook_args=self._hook_args,
            on_apply=_apply,
        )

    def _on_convert(self) -> None:
        handler = getattr(self._cb, "on_convert_submit", None)
        if not callable(handler):
            messagebox.showerror("Convert", "Convert handler not wired.")
            return
        space_value = self._space_var.get()
        subject_type = self._subject_type_var.get() if space_value == "subject_ras" else None
        subject_pose = f"{self._pose_primary_var.get()}_{self._pose_secondary_var.get()}" if space_value == "subject_ras" else None
        handler(
            output_dir=self._output_dir_var.get(),
            base_name=self._layout_template_var.get(),
            space=space_value,
            subject_type=subject_type,
            subject_pose=subject_pose,
            flip=(self._flip_x_var.get(), self._flip_y_var.get(), self._flip_z_var.get()),
            hook_enabled=self._hook_enabled_var.get(),
            hook_name=self._hook_name_var.get(),
            hook_args=self._hook_args,
            sidecar_enabled=self._convert_sidecar_var.get(),
            sidecar_format=self._convert_sidecar_format_var.get(),
            use_viewer_orientation=self._use_viewer_orientation_var.get(),
        )

    def _on_hook_toggle(self) -> None:
        handler = getattr(self._cb, "on_convert_hook_toggle", None)
        if callable(handler):
            handler(self._hook_enabled_var.get())

    def set_hook_state(self, hook_name: str, enabled: bool, hook_args: Optional[dict]) -> None:
        self._hook_name_var.set(hook_name or "None")
        self._hook_enabled_var.set(bool(enabled))
        self._hook_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def set_layout_fields(
        self,
        *,
        rule: str,
        info_spec: str,
        metadata_spec: str,
        context_map: str,
        template: str,
        slicepack_suffix: str,
    ) -> None:
        self._layout_syncing = True
        try:
            self._layout_rule_var.set(rule)
            self._layout_info_spec_var.set(info_spec)
            self._layout_metadata_spec_var.set(metadata_spec)
            self._layout_context_map_var.set(context_map)
            self._layout_template_var.set(template)
            self._slicepack_suffix_var.set(slicepack_suffix)
            self._update_layout_controls()
        finally:
            self._layout_syncing = False

    def set_layout_keys(self, keys: list[str]) -> None:
        if self._layout_key_listbox is None:
            return
        self._layout_key_listbox.delete(0, tk.END)
        for key in keys:
            self._layout_key_listbox.insert(tk.END, key)

    def set_preview_text(self, text: str) -> None:
        self._preview_text.configure(state=tk.NORMAL)
        self._preview_text.delete("1.0", tk.END)
        self._preview_text.insert(tk.END, text)
        self._preview_text.configure(state=tk.DISABLED)

    def set_settings_text(self, text: str) -> None:
        self._settings_text.configure(state=tk.NORMAL)
        self._settings_text.delete("1.0", tk.END)
        self._settings_text.insert(tk.END, text)
        self._settings_text.configure(state=tk.DISABLED)

    def set_orientation_fields(
        self,
        *,
        use_viewer: bool,
        space: str,
        subject_type: Optional[str],
        pose_primary: str,
        pose_secondary: str,
        flip: tuple[bool, bool, bool],
    ) -> None:
        self._use_viewer_orientation_var.set(bool(use_viewer))
        if use_viewer:
            if space:
                self._space_var.set(space)
            if subject_type:
                self._subject_type_var.set(subject_type)
            if pose_primary:
                self._pose_primary_var.set(pose_primary)
            if pose_secondary:
                self._pose_secondary_var.set(pose_secondary)
            self._flip_x_var.set(bool(flip[0]))
            self._flip_y_var.set(bool(flip[1]))
            self._flip_z_var.set(bool(flip[2]))
        self._update_convert_space_controls()
