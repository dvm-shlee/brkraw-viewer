from __future__ import annotations

import logging
import yaml
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Any, Dict, Optional, Mapping

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from brkraw.apps import addon as addon_app
from brkraw.core import config as config_core

logger = logging.getLogger("brkraw.viewer")


class _Tooltip:
    def __init__(self, widget: tk.Widget, text_func) -> None:
        self._widget = widget
        self._text_func = text_func
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: tk.Event) -> None:
        text = self._text_func().strip()
        if not text or self._tip is not None:
            return
        tip = tk.Toplevel(self._widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(tip, text=text, padx=6, pady=4, background="#ffffe0", relief="solid", borderwidth=1)
        label.pack()
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 6
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event: tk.Event) -> None:
        if self._tip is None:
            return
        self._tip.destroy()
        self._tip = None


class AddonsTab:
    TITLE = "Addons"

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        setattr(self.frame, "_tab_instance", self)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        # One editor window per target file (and rule category), so a later Save cannot overwrite
        # the changes of an earlier window (WI-0079).
        self._editor_windows: Dict[tuple, Any] = {}
        self._addon_rule_sections: Dict[str, Dict[str, Any]] = {}
        self._addon_spec_sections: Dict[str, Dict[str, Any]] = {}
        self._addon_context_map_var = tk.StringVar(value="")
        self._addon_context_status_var = tk.StringVar(value="No context map")
        self._addon_transform_text: Optional[tk.Text] = None
        self._spec_tabs: Optional[ttk.Notebook] = None

        self._info_output_text: Optional[tk.Text] = None

        for category in ("info_spec", "metadata_spec", "converter_hook"):
            self._addon_rule_sections[category] = {
                "file_var": tk.StringVar(value="None"),
                "name_var": tk.StringVar(value="None"),
                "auto_var": tk.BooleanVar(value=True),
                "status_var": tk.StringVar(value="Not configured"),
                "desc_var": tk.StringVar(value=""),
                "hook_var": tk.StringVar(value="None"),
                "file_combo": None,
                "combo": None,
                "browse_button": None,
                "new_button": None,
                "desc_tooltip": None,
            }
        for category in ("info_spec", "metadata_spec"):
            self._addon_spec_sections[category] = {
                "auto_var": tk.BooleanVar(value=True),
                "file_var": tk.StringVar(value="None"),
                "name_var": tk.StringVar(value=""),
                "status_var": tk.StringVar(value="Not configured"),
                "desc_var": tk.StringVar(value=""),
                "combo": None,
                "name_entry": None,
                "browse_button": None,
                "new_button": None,
                "desc_tooltip": None,
            }

        self._addon_context_new_button: Optional[ttk.Button] = None
        self._addon_rule_file_map: Dict[str, str] = {}
        self._addon_rule_display_by_path: Dict[str, str] = {}
        self._addon_rule_choices_by_category: Dict[str, Dict[str, dict]] = {}
        self._addon_spec_choices: Dict[str, Dict[str, dict]] = {}
        self._addon_spec_display_by_path: Dict[str, str] = {}
        self._default_info_spec_display: str = "Default"

        self._build_addon_tab(self.frame)
        self.refresh_installed()

    def _build_addon_tab(self, parent: tk.Misc) -> None:
        addon_tab = parent
        addon_tab.columnconfigure(0, weight=1)
        addon_tab.columnconfigure(1, weight=1)
        addon_tab.rowconfigure(0, weight=1)
        small_button_width = 3

        left_stack, right_stack = self._build_split_panes(addon_tab)
        self._build_spec_tabs(left_stack, small_button_width)
        self._build_transform_section(left_stack, small_button_width)
        self._build_output_section(right_stack)
        self._build_context_section(right_stack, small_button_width)

    def _build_split_panes(self, parent: tk.Misc) -> tuple[ttk.Frame, ttk.Frame]:
        paned = ttk.Panedwindow(parent, orient="horizontal")
        paned.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)

        left_container = ttk.Frame(paned, padding=(6, 6))
        right_container = ttk.Frame(paned, padding=(6, 6))
        paned.add(left_container, weight=1)
        paned.add(right_container, weight=1)

        left_container.columnconfigure(0, weight=1)
        left_container.rowconfigure(0, weight=1)
        right_container.columnconfigure(0, weight=1)
        right_container.rowconfigure(0, weight=1)

        left_stack = ttk.Frame(left_container)
        left_stack.grid(row=0, column=0, sticky="nsew")
        left_stack.columnconfigure(0, weight=1)
        left_stack.rowconfigure(0, weight=0)
        left_stack.rowconfigure(1, weight=0)

        right_stack = ttk.Frame(right_container)
        right_stack.grid(row=0, column=0, sticky="nsew")
        right_stack.columnconfigure(0, weight=1)
        right_stack.rowconfigure(0, weight=3)
        right_stack.rowconfigure(1, weight=0)
        right_stack.rowconfigure(2, weight=1)

        return left_stack, right_stack

    def _build_spec_tabs(self, parent: tk.Misc, small_button_width: int) -> None:
        spec_tabs = ttk.Notebook(parent)
        spec_tabs.grid(row=0, column=0, sticky="ew")
        self._spec_tabs = spec_tabs
        parent.columnconfigure(0, weight=1)
        for category, title in (
            ("info_spec", "Info"),
            ("metadata_spec", "Metadata"),
            ("converter_hook", "Hook"),
        ):
            tab = ttk.Frame(spec_tabs)
            tab.columnconfigure(0, weight=1)
            spec_tabs.add(tab, text=title)
            self._build_rule_spec_section(tab, category, small_button_width)
        spec_tabs.bind("<<NotebookTabChanged>>", self._on_spec_tab_changed)

    def _build_rule_spec_section(self, parent: tk.Misc, category: str, small_button_width: int) -> None:
        section = ttk.Frame(parent, padding=(8, 8))
        section.grid(row=0, column=0, sticky="ew")
        section.columnconfigure(0, weight=1)

        rule_frame = ttk.LabelFrame(section, text="Rule", padding=(6, 6))
        rule_frame.grid(row=0, column=0, sticky="ew")
        rule_frame.columnconfigure(1, weight=1)

        rule_state = self._addon_rule_sections[category]
        ttk.Label(rule_frame, text="file").grid(row=0, column=0, sticky="w")
        rule_state["file_combo"] = ttk.Combobox(
            rule_frame,
            textvariable=rule_state["file_var"],
            state="readonly",
            values=("None",),
        )
        rule_state["file_combo"].grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 6))
        rule_state["file_combo"].bind(
            "<<ComboboxSelected>>",
            lambda *_: self._on_rule_file_selected(category),
        )
        rule_state["browse_button"] = ttk.Button(
            rule_frame,
            text="Browse",
            command=lambda: self._browse_rule_file(category),
        )
        rule_state["browse_button"].grid(row=0, column=3, sticky="e")

        ttk.Label(rule_frame, text="name").grid(row=1, column=0, sticky="w", pady=(8, 0))
        name_row = ttk.Frame(rule_frame)
        name_row.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        name_row.columnconfigure(0, weight=1)
        rule_state["combo"] = ttk.Combobox(
            name_row,
            textvariable=rule_state["name_var"],
            state="readonly",
            values=("None",),
        )
        rule_state["combo"].grid(row=0, column=0, sticky="ew")
        rule_state["combo"].bind("<<ComboboxSelected>>", lambda *_: self._on_rule_selected(category))
        ttk.Checkbutton(
            name_row,
            text="Auto",
            variable=rule_state["auto_var"],
            command=lambda: self._on_rule_auto_toggle(category),
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))
        rule_state["desc_tooltip"] = _Tooltip(rule_state["combo"], lambda: rule_state["desc_var"].get())

        ttk.Label(rule_frame, text="status").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(rule_frame, textvariable=rule_state["status_var"]).grid(
            row=2,
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(8, 0),
        )
        rule_buttons = ttk.Frame(rule_frame)
        rule_buttons.grid(row=2, column=2, columnspan=2, sticky="e", pady=(8, 0))
        rule_state["new_button"] = ttk.Button(
            rule_buttons,
            text="New",
            width=small_button_width,
            command=lambda: self._new_rule_file(category),
        )
        rule_state["new_button"].pack(side=tk.LEFT)
        ttk.Button(
            rule_buttons,
            text="Edit",
            width=small_button_width,
            command=lambda: self._edit_rule_file(category),
        ).pack(side=tk.LEFT, padx=(6, 0))

        spec_frame = ttk.LabelFrame(section, text="Spec", padding=(6, 6))
        spec_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        spec_frame.columnconfigure(1, weight=1)

        if category not in self._addon_spec_sections:
            ttk.Label(spec_frame, text="Available Hook").grid(row=0, column=0, sticky="w")
            ttk.Entry(spec_frame, textvariable=rule_state["hook_var"], state="readonly").grid(
                row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0)
            )
            return

        spec_state = self._addon_spec_sections[category]
        ttk.Checkbutton(
            spec_frame,
            text="Follow applied rule for spec selection",
            variable=spec_state["auto_var"],
            command=lambda: self._on_spec_auto_toggle(category),
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(spec_frame, text="file").grid(row=1, column=0, sticky="w", pady=(8, 0))
        spec_state["combo"] = ttk.Combobox(
            spec_frame,
            textvariable=spec_state["file_var"],
            state="readonly",
            values=("None",),
        )
        spec_state["combo"].grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 6), pady=(8, 0))
        spec_state["combo"].bind("<<ComboboxSelected>>", lambda *_: self._on_spec_file_selected(category))
        spec_state["browse_button"] = ttk.Button(
            spec_frame,
            text="Browse",
            command=lambda: self._browse_spec_file(category),
        )
        spec_state["browse_button"].grid(row=1, column=3, sticky="e", pady=(8, 0))

        ttk.Label(spec_frame, text="name").grid(row=2, column=0, sticky="w", pady=(8, 0))
        spec_state["name_entry"] = ttk.Entry(spec_frame, textvariable=spec_state["name_var"], state="readonly")
        spec_state["name_entry"].grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        spec_state["desc_tooltip"] = _Tooltip(
            spec_state["name_entry"],
            lambda: spec_state["desc_var"].get(),
        )

        ttk.Label(spec_frame, text="status").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(spec_frame, textvariable=spec_state["status_var"]).grid(
            row=3,
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(8, 0),
        )
        spec_buttons = ttk.Frame(spec_frame)
        spec_buttons.grid(row=3, column=2, columnspan=2, sticky="e", pady=(8, 0))
        spec_state["new_button"] = ttk.Button(
            spec_buttons,
            text="New",
            width=small_button_width,
            command=lambda: self._new_spec_file(category),
        )
        spec_state["new_button"].pack(side=tk.LEFT)
        ttk.Button(
            spec_buttons,
            text="Edit",
            width=small_button_width,
            command=lambda: self._edit_spec_file(category),
        ).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(
            spec_frame,
            text="Apply Spec",
            command=lambda: self._apply_selected_spec(category),
        ).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 0))

    def _build_transform_section(self, parent: tk.Misc, small_button_width: int) -> None:
        transform_frame = ttk.LabelFrame(parent, text="Transform", padding=(8, 8))
        transform_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        transform_frame.columnconfigure(1, weight=1)

        ttk.Label(transform_frame, text="Location").grid(row=0, column=0, sticky="nw")
        self._addon_transform_text = tk.Text(transform_frame, height=3, wrap="word")
        self._addon_transform_text.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 6))
        self._addon_transform_text.configure(state=tk.DISABLED)
        ttk.Button(transform_frame, text="Edit", width=small_button_width, command=self._edit_transform_file).grid(
            row=0, column=3, sticky="e"
        )

    def _build_output_section(self, parent: tk.Misc) -> None:
        output_frame = ttk.LabelFrame(parent, text="Output", padding=(8, 8))
        output_frame.grid(row=0, column=0, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self._info_output_text = tk.Text(output_frame, wrap="word")
        self._info_output_text.grid(row=0, column=0, sticky="nsew")
        info_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self._info_output_text.yview)
        info_scroll.grid(row=0, column=1, sticky="ns")
        self._info_output_text.configure(yscrollcommand=info_scroll.set)
        self._info_output_text.configure(state=tk.DISABLED)
        self._info_output_text.bind("<Button-3>", self._on_output_context_menu)
        self._info_output_text.bind("<ButtonRelease-3>", self._on_output_context_menu)
        self._info_output_text.bind("<Button-2>", self._on_output_context_menu)
        self._info_output_text.bind("<ButtonRelease-2>", self._on_output_context_menu)
        self._info_output_text.bind("<Control-Button-1>", self._on_output_context_menu)

        output_actions = ttk.Frame(parent)
        output_actions.grid(row=1, column=0, sticky="e", pady=(10, 0))
        ttk.Button(output_actions, text="Reset", command=self._reset_addon_state).pack(side=tk.LEFT)
        ttk.Button(output_actions, text="Save As", command=self._save_addon_output).pack(side=tk.LEFT, padx=(8, 0))

    def _build_context_section(self, parent: tk.Misc, small_button_width: int) -> None:
        context_container = ttk.Frame(parent)
        context_container.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        context_container.columnconfigure(0, weight=1)
        context_container.grid_anchor("n")
        context_inner = ttk.Frame(context_container)
        context_inner.grid(row=0, column=0, sticky="ew")
        context_inner.columnconfigure(0, weight=1)

        map_frame = ttk.LabelFrame(context_inner, text="Context Map", padding=(8, 8))
        map_frame.grid(row=0, column=0, sticky="ew")

        path_row = ttk.Frame(map_frame)
        path_row.pack(fill="x")
        path_row.columnconfigure(1, weight=1)
        ttk.Label(path_row, text="path").grid(row=0, column=0, sticky="w")
        ttk.Entry(path_row, textvariable=self._addon_context_map_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(8, 6)
        )
        ttk.Button(path_row, text="Open", command=self._browse_context_map).grid(row=0, column=2, sticky="e")

        status_row = ttk.Frame(map_frame)
        status_row.pack(fill="x", pady=(8, 0))
        status_row.columnconfigure(2, weight=1)
        ttk.Label(status_row, textvariable=self._addon_context_status_var).grid(row=0, column=0, sticky="w")
        status_buttons = ttk.Frame(status_row)
        status_buttons.grid(row=0, column=3, sticky="e")
        self._addon_context_new_button = ttk.Button(
            status_buttons,
            text="New",
            width=small_button_width,
            command=self._new_context_map,
        )
        self._addon_context_new_button.pack(side=tk.LEFT)
        ttk.Button(
            status_buttons,
            text="Edit",
            width=small_button_width,
            command=self._edit_context_map,
        ).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Button(map_frame, text="Apply Context Map", command=self._apply_context_map).pack(
            fill="x", pady=(10, 0)
        )

        # No manual resize handler needed; Panedwindow manages layout.

    def _notify_unwired(self, message: str) -> None:
        messagebox.showinfo("Not wired", message)

    def _on_rule_file_selected(self, category: str) -> None:
        state = self._addon_rule_sections[category]
        selection = (state["file_var"].get() or "").strip()
        path = self._resolve_rule_file_selection(selection)
        if not path:
            state["status_var"].set("skipped")
            spec_state = self._addon_spec_sections.get(category)
            if spec_state is not None:
                if category == "info_spec" and self._default_info_spec_display:
                    spec_state["file_var"].set(self._default_info_spec_display)
                else:
                    spec_state["file_var"].set("None")
                self._update_spec_details(category)
            return
        self._load_rule_file(category, path)

    def _on_rule_selected(self, category: str) -> None:
        state = self._addon_rule_sections[category]
        selection = (state["name_var"].get() or "").strip()
        choices = self._addon_rule_choices_by_category.get(category, {})
        record = choices.get(selection)
        if record:
            state["desc_var"].set(record.get("description", "") or "")
            state["status_var"].set("Ready")
            if category == "converter_hook":
                state["hook_var"].set(record.get("use") or "None")
        else:
            state["desc_var"].set("")
            state["status_var"].set("Not configured")
            if category == "converter_hook":
                state["hook_var"].set("None")

    def _on_spec_file_selected(self, category: str) -> None:
        state = self._addon_spec_sections[category]
        if state["auto_var"].get():
            state["auto_var"].set(False)
        self._update_spec_details(category)
        self._refresh_transform_files(category=category)

    def _on_transform_file_selected(self) -> None:
        _ = None

    def _browse_transform_file(self) -> None:
        self._notify_unwired("Transform selection is now derived from the spec.")

    def _new_transform_file(self) -> None:
        self._notify_unwired("Transform creation is not wired yet.")

    def _edit_transform_file(self) -> None:
        if self._addon_transform_text is None:
            return
        try:
            content = self._addon_transform_text.get("1.0", tk.END).strip()
        except Exception:
            return
        if not content:
            return
        first_line = content.splitlines()[0].strip()
        if not first_line or first_line == "None":
            return
        path = Path(first_line).expanduser()
        if not path.is_absolute():
            path = Path(first_line).resolve()
        if not path.exists():
            messagebox.showwarning("Transform", f"Transform not found:\n{path}")
            return
        self._open_text_editor(path=path, title="Edit transform")

    def _reset_addon_state(self) -> None:
        if self._info_output_text is None:
            return
        self._info_output_text.configure(state=tk.NORMAL)
        self._info_output_text.delete("1.0", tk.END)
        self._info_output_text.configure(state=tk.DISABLED)

    def refresh_installed(self) -> None:
        self._refresh_rule_files()
        self._refresh_transform_files()
        self._refresh_spec_choices()
        for category in self._addon_rule_sections:
            self._on_rule_auto_toggle(category)
            self._on_rule_selected(category)
        for category in self._addon_spec_sections:
            self._on_spec_auto_toggle(category)
            self._update_spec_details(category)

    def show_default_info_spec(self) -> None:
        if "info_spec" not in self._addon_spec_sections:
            return
        spec_state = self._addon_spec_sections["info_spec"]
        if (spec_state["file_var"].get() or "").strip() in ("", "None"):
            spec_state["file_var"].set(self._default_info_spec_display)
            self._update_spec_details("info_spec")
        spec_path = self._resolve_spec_path_for_category("info_spec")
        handler = getattr(self._cb, "on_apply_addon_spec", None)
        if callable(handler):
            payload = handler("info_spec", spec_path)
            self.set_output(payload)

    def _refresh_rule_files(self) -> None:
        self._addon_rule_file_map = {}
        self._addon_rule_display_by_path = {}
        self._addon_rule_choices_by_category = {cat: {} for cat in self._addon_rule_sections}
        try:
            installed = addon_app.list_installed(root=None)
        except Exception:
            installed = {}
        rules = installed.get("rules", []) if isinstance(installed, dict) else []
        paths = config_core.paths(root=None)
        seen_relpaths: set[str] = set()
        for entry in rules:
            if not isinstance(entry, dict):
                continue
            relpath = entry.get("file")
            if not relpath or relpath in seen_relpaths:
                continue
            seen_relpaths.add(relpath)
            basename = str(relpath).split("/")[-1]
            display = basename
            if display in self._addon_rule_file_map:
                display = f"{basename} ({relpath})"
            full_path = str((paths.rules_dir / relpath).resolve())
            self._addon_rule_file_map[display] = full_path
            self._addon_rule_display_by_path[full_path] = display

        values = sorted(self._addon_rule_file_map.keys()) if self._addon_rule_file_map else ["None"]
        for category, rule_state in self._addon_rule_sections.items():
            file_combo = rule_state.get("file_combo")
            if file_combo is not None:
                file_combo.configure(values=values)
            current = (rule_state["file_var"].get() or "").strip()
            if current in ("", "None") and values:
                rule_state["file_var"].set(values[0])
            path = self._resolve_rule_file_selection(rule_state["file_var"].get())
            self._load_rule_file(category, path)
            self._apply_rule_combo_state(category)

    def _resolve_rule_file_selection(self, selection: str) -> Optional[str]:
        if not selection or selection == "None":
            return None
        path = self._addon_rule_file_map.get(selection)
        if path:
            return path
        if Path(selection).exists():
            return selection
        return None

    def _load_rule_file(self, category: str, path: Optional[str]) -> None:
        rule_state = self._addon_rule_sections[category]
        if not path:
            self._addon_rule_choices_by_category[category] = {}
            rule_state["name_var"].set("None")
            combo = rule_state.get("combo")
            if combo is not None:
                combo.configure(values=("None",))
            rule_state["status_var"].set("skipped")
            rule_state["desc_var"].set("")
            return
        try:
            import yaml
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self.set_output(f"Failed to load rule file:\n{exc}")
            return
        if not isinstance(data, dict):
            data = {}
        choices: Dict[str, Dict[str, Any]] = {}
        for cat, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if cat != category:
                    continue
                name = str(item.get("name") or "Unnamed")
                rule = dict(item)
                choices[name] = rule
        self._addon_rule_choices_by_category[category] = choices
        values = sorted(choices.keys()) if choices else ["None"]
        combo = rule_state.get("combo")
        if combo is not None:
            combo.configure(values=values)
        if values:
            rule_state["name_var"].set(values[0])

    def _apply_rule_combo_state(self, category: str) -> None:
        rule_state = self._addon_rule_sections[category]
        auto = bool(rule_state["auto_var"].get())
        file_combo = rule_state.get("file_combo")
        if file_combo is not None:
            state = "disabled" if auto else ("readonly" if self._addon_rule_file_map else "disabled")
            file_combo.configure(state=state)
        combo = rule_state.get("combo")
        if combo is not None:
            has_choices = bool(self._addon_rule_choices_by_category.get(category))
            state = "disabled" if auto else ("readonly" if has_choices else "disabled")
            combo.configure(state=state)

    def _refresh_spec_choices(self) -> None:
        specs = []
        try:
            installed = addon_app.list_installed(root=None)
            specs = installed.get("specs", []) if isinstance(installed, dict) else []
        except Exception:
            specs = []
        self._addon_spec_choices = {cat: {} for cat in self._addon_spec_sections}
        self._addon_spec_display_by_path = {}
        values_by_category: Dict[str, list[str]] = {cat: [] for cat in self._addon_spec_sections}
        seen_display: Dict[str, set[str]] = {cat: set() for cat in self._addon_spec_sections}
        for spec in specs:
            file_name = str(spec.get("file") or "").strip()
            name = str(spec.get("name") or "").strip()
            kind = str(spec.get("category") or spec.get("kind") or "").strip()
            if kind and kind not in values_by_category:
                continue
            spec_path = None
            if file_name:
                spec_path = addon_app.resolve_spec_reference(file_name, category=kind or None, root=None)
            if spec_path is None and name:
                spec_path = addon_app.resolve_spec_reference(name, category=kind or None, root=None)
            if spec_path is None:
                continue
            display = file_name or Path(spec_path).name
            if display in seen_display.get(kind, set()):
                extra = name or file_name
                if extra:
                    display = f"{display} ({extra})"
                else:
                    display = f"{display} ({spec_path})"
            record = dict(spec)
            record["path"] = str(spec_path)
            if kind in self._addon_spec_choices:
                self._addon_spec_choices[kind][display] = record
            self._addon_spec_display_by_path[str(spec_path)] = display
            if kind in values_by_category:
                values_by_category[kind].append(display)
                seen_display[kind].add(display)

        # Always include default scan.yaml (displayed as "Default") for info_spec.
        if "info_spec" in values_by_category:
            display = self._default_info_spec_display
            if display not in values_by_category["info_spec"]:
                values_by_category["info_spec"].insert(0, display)
                seen_display["info_spec"].add(display)

        for category, spec_state in self._addon_spec_sections.items():
            values = sorted(values_by_category.get(category, [])) if values_by_category.get(category) else ["None"]
            combo = spec_state.get("combo")
            if combo is not None:
                combo.configure(values=values, state="readonly" if values and values != ["None"] else "disabled")
            if values and (spec_state["file_var"].get() or "").strip() in ("", "None"):
                spec_state["file_var"].set(values[0])
            if category == "info_spec":
                if self._default_info_spec_display not in values:
                    values.insert(0, self._default_info_spec_display)
                    if combo is not None:
                        combo.configure(values=values, state="readonly")

    def _refresh_transform_files(self, *, category: Optional[str] = None) -> None:
        if self._addon_transform_text is None:
            return
        selected = category or self._current_spec_category()
        if selected == "converter_hook":
            sources = ["None"]
            self._addon_transform_text.configure(state=tk.NORMAL)
            self._addon_transform_text.delete("1.0", tk.END)
            self._addon_transform_text.insert("1.0", "\n".join(sources))
            self._addon_transform_text.configure(state=tk.DISABLED)
            return
        spec_category = selected or "metadata_spec"
        spec_path = self._resolve_spec_path_for_category(spec_category)
        sources: list[str] = []
        if spec_path:
            try:
                meta = yaml.safe_load(Path(str(spec_path)).read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            if isinstance(meta, dict):
                meta = meta.get("__meta__", meta)
            if isinstance(meta, dict):
                raw = meta.get("transforms_source") or meta.get("transform_source") or meta.get("transform")
                if isinstance(raw, list):
                    sources = [str(item) for item in raw if item is not None]
                elif isinstance(raw, str) and raw.strip():
                    sources = [raw.strip()]
        sources = [self._resolve_transform_source(src, spec_path) for src in sources]
        if not sources:
            sources = ["None"]
        self._addon_transform_text.configure(state=tk.NORMAL)
        self._addon_transform_text.delete("1.0", tk.END)
        self._addon_transform_text.insert("1.0", "\n".join(sources))
        self._addon_transform_text.configure(state=tk.DISABLED)

    def _resolve_transform_source(self, source: str, spec_path: Optional[str]) -> str:
        if not source:
            return ""
        raw = str(source).strip()
        if not raw:
            return ""
        path = Path(raw).expanduser()
        if path.is_absolute():
            return str(path)
        base_dir = None
        if spec_path:
            try:
                base_dir = Path(str(spec_path)).expanduser().resolve().parent
            except Exception:
                base_dir = None
        if base_dir is not None:
            candidate = (base_dir / path).resolve()
            if candidate.exists():
                return str(candidate)
        try:
            transforms_dir = config_core.paths(root=None).transforms_dir
            candidate = (Path(transforms_dir) / path).resolve()
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass
        return str(path.resolve())

    def _current_spec_category(self) -> Optional[str]:
        if self._spec_tabs is None:
            return None
        try:
            index = self._spec_tabs.index("current")
        except Exception:
            return None
        mapping = {
            0: "info_spec",
            1: "metadata_spec",
            2: "converter_hook",
        }
        return mapping.get(index)

    def _on_spec_tab_changed(self, _event: tk.Event) -> None:
        self._refresh_transform_files()

    def _resolve_spec_path_for_category(self, category: str) -> Optional[str]:
        spec_state = self._addon_spec_sections[category]
        if spec_state["auto_var"].get():
            handler = getattr(self._cb, "resolve_addon_spec", None)
            if callable(handler):
                path = handler(category)
                return str(path) if path is not None else None
            return None
        selection = (spec_state["file_var"].get() or "").strip()
        if not selection or selection == "None":
            return None
        if category == "info_spec" and selection == self._default_info_spec_display:
            return ""
        record = self._addon_spec_choices.get(category, {}).get(selection)
        if record:
            path = record.get("path")
            if path:
                return str(path)
        resolved = addon_app.resolve_spec_reference(selection, category=category, root=None)
        return str(resolved) if resolved is not None else None

    def _update_spec_details(self, category: str) -> None:
        spec_state = self._addon_spec_sections[category]
        if spec_state["auto_var"].get():
            handler = getattr(self._cb, "resolve_addon_spec", None)
            raw_path = handler(category) if callable(handler) else None
            path = str(raw_path) if raw_path is not None else None
            if path:
                display = self._addon_spec_display_by_path.get(path, path)
                spec_state["file_var"].set(display)
                try:
                    meta = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
                if isinstance(meta, dict):
                    meta = meta.get("__meta__", meta)
                name = ""
                desc = ""
                if isinstance(meta, dict):
                    name = str(meta.get("name") or "")
                    desc = str(meta.get("description") or "")
                spec_state["name_var"].set(name or Path(path).name)
                spec_state["desc_var"].set(desc)
                spec_state["status_var"].set("applied")
                return
            spec_state["name_var"].set("None")
            spec_state["desc_var"].set("")
            spec_state["status_var"].set("skipped")
            if category == "info_spec":
                spec_state["file_var"].set(self._default_info_spec_display)
            self._refresh_transform_files(category=category)
            return
        selection = (spec_state["file_var"].get() or "").strip()
        record = self._addon_spec_choices.get(category, {}).get(selection)
        if record:
            spec_state["name_var"].set(record.get("name", "") or "")
            spec_state["desc_var"].set(record.get("description", "") or "")
            spec_state["status_var"].set("Ready")
        else:
            spec_state["name_var"].set("")
            spec_state["desc_var"].set("")
            spec_state["status_var"].set("Not configured")
        self._refresh_transform_files(category=category)

    def _on_rule_auto_toggle(self, category: str) -> None:
        rule_state = self._addon_rule_sections[category]
        auto = bool(rule_state["auto_var"].get())
        combo = rule_state.get("combo")
        if combo is not None:
            combo.configure(state="disabled" if auto else "readonly")
        file_combo = rule_state.get("file_combo")
        if file_combo is not None:
            file_combo.configure(state="disabled" if auto else "readonly")
        for btn in (rule_state.get("browse_button"), rule_state.get("new_button")):
            if btn is None:
                continue
            btn.configure(state=tk.DISABLED if auto else tk.NORMAL)
        if auto:
            handler = getattr(self._cb, "resolve_addon_rule_file", None)
            if callable(handler):
                result = handler(category)
                if isinstance(result, tuple) and len(result) >= 2:
                    raw_path, rule_name = result[0], result[1]
                else:
                    raw_path, rule_name = None, ""
                path = str(raw_path) if raw_path is not None else None
                if path:
                    display = self._addon_rule_display_by_path.get(path, path)
                    rule_state["file_var"].set(display)
                    self._load_rule_file(category, path)
                    if rule_name:
                        rule_state["name_var"].set(rule_name)
                    rule_state["status_var"].set("applied")
                    if category == "converter_hook":
                        choice = self._addon_rule_choices_by_category.get(category, {}).get(rule_name or "")
                        rule_state["hook_var"].set(choice.get("use") if choice else "None")
                else:
                    rule_state["file_var"].set("None")
                    rule_state["name_var"].set("None")
                    rule_state["desc_var"].set("")
                    rule_state["status_var"].set("skipped")
                    if category == "converter_hook":
                        rule_state["hook_var"].set("None")

    def _on_spec_auto_toggle(self, category: str) -> None:
        spec_state = self._addon_spec_sections[category]
        auto = bool(spec_state["auto_var"].get())
        combo = spec_state.get("combo")
        if combo is not None:
            combo.configure(state="disabled" if auto else "readonly")
        name_entry = spec_state.get("name_entry")
        if name_entry is not None:
            try:
                name_entry.configure(state="disabled" if auto else "readonly")
            except Exception:
                pass
        for btn in (spec_state.get("browse_button"), spec_state.get("new_button")):
            if btn is None:
                continue
            btn.configure(state=tk.DISABLED if auto else tk.NORMAL)
        self._update_spec_details(category)
        if auto:
            handler = getattr(self._cb, "resolve_addon_spec", None)
            if callable(handler):
                raw_path = handler(category)
                path = str(raw_path) if raw_path is not None else None
                if path:
                    display = self._addon_spec_display_by_path.get(path, path)
                    spec_state["file_var"].set(display)
                    self._update_spec_details(category)
                elif category == "info_spec":
                    spec_state["file_var"].set(self._default_info_spec_display)
                    self._update_spec_details(category)
        self._refresh_transform_files(category=category)

    def _apply_selected_spec(self, category: str) -> None:
        spec_path = self._resolve_spec_path_for_category(category)
        if not spec_path:
            messagebox.showinfo("Spec", "No spec selected.")
            return
        handler = getattr(self._cb, "on_apply_addon_spec", None)
        if callable(handler):
            payload = handler(category, spec_path)
            self.set_output(payload)
            return
        self._notify_unwired("Apply spec is not wired yet.")

    def _browse_rule_file(self, category: str) -> None:
        path = filedialog.askopenfilename(
            title="Select rule YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        rule_state = self._addon_rule_sections[category]
        rule_state["file_var"].set(path)
        self._load_rule_file(category, path)

    def _new_rule_file(self, category: str) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new rule file",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        Path(path).write_text("# rules\n", encoding="utf-8")
        rule_state = self._addon_rule_sections[category]
        rule_state["file_var"].set(path)
        self._open_text_editor(path=Path(path), title="Edit rule")

    def _edit_rule_file(self, category: str) -> None:
        rule_state = self._addon_rule_sections[category]
        path = self._resolve_rule_file_selection(rule_state["file_var"].get())
        if not path:
            return
        self._open_rule_section_editor(path=Path(path), category=category)

    def _browse_spec_file(self, category: str) -> None:
        path = filedialog.askopenfilename(
            title="Select spec YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        spec_state = self._addon_spec_sections[category]
        spec_state["auto_var"].set(False)
        spec_state["file_var"].set(path)
        self._on_spec_file_selected(category)

    def _new_spec_file(self, category: str) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new spec file",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        Path(path).write_text("# spec\n", encoding="utf-8")
        spec_state = self._addon_spec_sections[category]
        spec_state["auto_var"].set(False)
        spec_state["file_var"].set(path)
        self._open_text_editor(path=Path(path), title="Edit spec")

    def _edit_spec_file(self, category: str) -> None:
        path = self._resolve_spec_path_for_category(category)
        if not path:
            return
        self._open_text_editor(path=Path(path), title="Edit spec")

    @staticmethod
    def _editor_key(path: Path, category: Optional[str] = None) -> tuple:
        try:
            resolved = str(Path(path).resolve())
        except Exception:
            resolved = str(path)
        return (resolved, category)

    def _show_existing_editor(self, key: tuple) -> bool:
        """Bring the open editor window of ``key`` forward. Returns False when there is none."""
        win = self._editor_windows.get(key)
        if win is None:
            return False
        try:
            if not win.winfo_exists():
                self._editor_windows.pop(key, None)
                return False
            win.deiconify()
            win.lift()
            win.focus_force()
        except Exception:
            self._editor_windows.pop(key, None)
            return False
        return True

    def _open_text_editor(self, *, path: Path, title: str) -> None:
        key = self._editor_key(path)
        if self._show_existing_editor(key):
            return
        win = tk.Toplevel(self.frame)
        self._editor_windows[key] = win
        win.title(title)
        win.geometry("640x480")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        text = tk.Text(win, wrap="word")
        text.grid(row=0, column=0, sticky="nsew")
        try:
            text.configure(undo=True)
        except Exception:
            pass
        self._bind_text_shortcuts(text)
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        try:
            content = path.read_text(encoding="utf-8")
            if path.suffix.lower() in {".yml", ".yaml"}:
                try:
                    content = self._format_yaml_text(content, flow_lists=False)
                except Exception:
                    pass
            text.insert("1.0", content)
        except Exception:
            pass
        actions = ttk.Frame(win)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        actions.columnconfigure(0, weight=1)
        def _save() -> None:
            try:
                path.write_text(text.get("1.0", tk.END), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Editor", f"Failed to save:\n{path}\n{exc}")
        ttk.Button(actions, text="Save", command=_save).grid(row=0, column=1, sticky="e")

    def _open_rule_section_editor(self, *, path: Path, category: str) -> None:
        key = self._editor_key(path, category)
        if self._show_existing_editor(key):
            return
        win = tk.Toplevel(self.frame)
        self._editor_windows[key] = win
        win.title(f"Edit rule ({category})")
        win.geometry("720x520")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        text = tk.Text(win, wrap="word")
        text.grid(row=0, column=0, sticky="nsew")
        try:
            text.configure(undo=True)
        except Exception:
            pass
        self._bind_text_shortcuts(text)
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)

        def _load_section() -> None:
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                content = ""
            section_data: Any = []
            try:
                yaml_rt = self._yaml_rt()
                doc = yaml_rt.load(content) if content.strip() else None
                if isinstance(doc, dict):
                    section_data = doc.get(category, [])
            except Exception:
                section_data = []
            try:
                section_text = self._dump_yaml_block(section_data)
            except Exception:
                section_text = ""
            text.delete("1.0", tk.END)
            text.insert("1.0", section_text)

        def _save_section() -> None:
            raw = text.get("1.0", tk.END)
            try:
                section = yaml.safe_load(raw) if raw.strip() else []
            except Exception as exc:
                messagebox.showerror("Editor", f"Failed to parse YAML:\n{exc}")
                return
            if section is None:
                section = []
            if not isinstance(section, list):
                messagebox.showerror("Editor", "Rule section must be a list.")
                return
            try:
                yaml_rt = self._yaml_rt()
                doc = yaml_rt.load(path.read_text(encoding="utf-8")) if path.exists() else CommentedMap()
                if doc is None or not isinstance(doc, dict):
                    doc = CommentedMap()
                doc[category] = section
                self._apply_top_level_spacing(doc)
                import io

                stream = io.StringIO()
                yaml_rt.dump(doc, stream)
                path.write_text(stream.getvalue(), encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Editor", f"Failed to save:\n{exc}")
                return
            messagebox.showinfo("Editor", f"Saved:\n{path}")
            self.refresh_installed()

        actions = ttk.Frame(win)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Save", command=_save_section).grid(row=0, column=1, sticky="e")
        _load_section()

    def _dump_yaml_block(self, payload: Any) -> str:
        yaml_rt = self._yaml_rt()
        data = payload
        if isinstance(payload, list):
            data = CommentedSeq(payload)
        self._apply_top_level_spacing(data)
        import io

        stream = io.StringIO()
        yaml_rt.dump(data, stream)
        return stream.getvalue()

    @staticmethod
    def _bind_text_shortcuts(text: tk.Text) -> None:
        def _select_all(_event: tk.Event) -> str:
            text.tag_add("sel", "1.0", "end-1c")
            return "break"

        def _undo(_event: tk.Event) -> str:
            try:
                text.edit_undo()
            except Exception:
                pass
            return "break"

        def _redo(_event: tk.Event) -> str:
            try:
                text.edit_redo()
            except Exception:
                pass
            return "break"

        def _copy(_event: tk.Event) -> str:
            text.event_generate("<<Copy>>")
            return "break"

        def _paste(_event: tk.Event) -> str:
            text.event_generate("<<Paste>>")
            return "break"

        def _cut(_event: tk.Event) -> str:
            text.event_generate("<<Cut>>")
            return "break"

        shortcuts = {
            "<Control-a>": _select_all,
            "<Control-z>": _undo,
            "<Control-y>": _redo,
            "<Control-c>": _copy,
            "<Control-v>": _paste,
            "<Control-x>": _cut,
            "<Command-a>": _select_all,
            "<Command-z>": _undo,
            "<Command-Shift-Z>": _redo,
            "<Command-c>": _copy,
            "<Command-v>": _paste,
            "<Command-x>": _cut,
        }
        for sequence, handler in shortcuts.items():
            text.bind(sequence, handler)

    def _on_output_context_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self._info_output_text, tearoff=0)
        menu.add_command(label="Copy", command=self._copy_output_selection)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_output_selection(self) -> None:
        if self._info_output_text is None:
            return
        try:
            text = self._info_output_text.get(tk.SEL_FIRST, tk.SEL_LAST)
        except Exception:
            return
        self._info_output_text.clipboard_clear()
        self._info_output_text.clipboard_append(text)

    def _save_addon_output(self) -> None:
        self._notify_unwired("Save output is not wired yet.")

    def _notify_context_map_change(self, path: Optional[str]) -> None:
        handler = getattr(self._cb, "on_addon_context_map_change", None)
        if callable(handler):
            handler(path if path else None)

    def _browse_context_map(self) -> None:
        path = filedialog.askopenfilename(
            title="Select context map YAML",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_context_map_var.set(path)
        self._addon_context_status_var.set("Selected")
        self._notify_context_map_change(path)

    def _new_context_map(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Create new context map",
            defaultextension=".yaml",
            filetypes=(("YAML", "*.yaml *.yml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._addon_context_map_var.set(path)
        self._addon_context_status_var.set("Selected")
        self._notify_context_map_change(path)
        self._open_text_editor(path=Path(path), title="Edit context map")

    def _edit_context_map(self) -> None:
        path = (self._addon_context_map_var.get() or "").strip()
        if not path or path == "None":
            return
        self._open_text_editor(path=Path(path), title="Edit context map")

    def _apply_context_map(self) -> None:
        path = (self._addon_context_map_var.get() or "").strip()
        if not path or path == "None":
            self.set_output("No context map selected.")
            return
        self._notify_context_map_change(path)
        if not Path(path).exists():
            messagebox.showwarning("Context Map", f"Context map not found:\n{path}")
            return
        spec_category = "metadata_spec"
        spec_path = self._resolve_spec_path_for_category(spec_category)
        if not spec_path:
            spec_category = "info_spec"
            spec_path = self._resolve_spec_path_for_category(spec_category)
        if not spec_path:
            self.set_output("No spec selected.")
            return
        handler = getattr(self._cb, "on_apply_addon_spec", None)
        if not callable(handler):
            self._notify_unwired("Apply context map is not wired yet.")
            return
        current = handler(spec_category, spec_path)
        try:
            from brkraw.specs import context_map as context_map_core
            context_map_core.validate_context_map(Path(path))
            map_data = context_map_core.load_context_map(path)
        except Exception as exc:
            messagebox.showerror("Context Map", f"Context map validation failed:\n{exc}")
            return
        if not isinstance(current, Mapping):
            messagebox.showerror("Context Map", "Spec output is not a mapping.")
            return
        # 0.6 context maps: originals stay as they are; the map adds namespaces
        # (info_spec) or sidecar fields (metadata_spec).
        target = "metadata_spec" if spec_category == "metadata_spec" else "info_spec"
        try:
            remapped = context_map_core.apply_context_map(current, map_data, target=target, context=None)
        except Exception as exc:
            messagebox.showerror("Context Map", f"Failed to apply context map:\n{exc}")
            return
        self._addon_context_status_var.set("applied")
        self.set_output(remapped)

    def set_output(self, payload: Any) -> None:
        if self._info_output_text is None:
            return
        text = self._format_payload(payload)
        self._info_output_text.configure(state=tk.NORMAL)
        self._info_output_text.delete("1.0", tk.END)
        self._info_output_text.insert(tk.END, text)
        self._info_output_text.configure(state=tk.DISABLED)

    def _format_payload(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, str):
            text = payload.strip()
            if text:
                try:
                    import json
                    parsed = json.loads(text)
                except Exception:
                    return payload
                try:
                    return self._dump_yaml(parsed)
                except Exception:
                    return payload
            return payload
        try:
            return self._dump_yaml(payload)
        except Exception:
            return str(payload)

    def _dump_yaml(self, payload: Any) -> str:
        yaml_rt = self._yaml_rt()
        data = self._coerce_flow_lists(payload)
        self._apply_top_level_spacing(data)
        import io

        stream = io.StringIO()
        yaml_rt.dump(data, stream)
        return stream.getvalue()

    def _format_yaml_text(self, text: str, *, flow_lists: bool) -> str:
        yaml_rt = self._yaml_rt()
        data = yaml_rt.load(text) if text.strip() else None
        if data is None:
            return text
        if flow_lists:
            data = self._coerce_flow_lists(data)
        self._apply_top_level_spacing(data)
        import io

        stream = io.StringIO()
        yaml_rt.dump(data, stream)
        return stream.getvalue()

    @staticmethod
    def _yaml_rt() -> YAML:
        yaml_rt = YAML(typ="rt")
        yaml_rt.indent(mapping=2, sequence=4, offset=2)
        yaml_rt.width = 120
        yaml_rt.default_flow_style = False
        yaml_rt.preserve_quotes = True
        return yaml_rt

    def _coerce_flow_lists(self, payload: Any) -> Any:
        if isinstance(payload, CommentedSeq):
            payload.fa.set_flow_style()
            for idx, item in enumerate(payload):
                payload[idx] = self._coerce_flow_lists(item)
            return payload
        if isinstance(payload, list):
            seq = CommentedSeq()
            for item in payload:
                seq.append(self._coerce_flow_lists(item))
            seq.fa.set_flow_style()
            return seq
        if isinstance(payload, CommentedMap):
            for key in list(payload.keys()):
                payload[key] = self._coerce_flow_lists(payload[key])
            return payload
        if isinstance(payload, dict):
            mapping = CommentedMap()
            for key, value in payload.items():
                mapping[key] = self._coerce_flow_lists(value)
            return mapping
        return payload

    @staticmethod
    def _apply_top_level_spacing(payload: Any) -> None:
        if not isinstance(payload, CommentedMap):
            return
        keys = list(payload.keys())
        for key in keys[1:]:
            payload.yaml_set_comment_before_after_key(key, before="\n")
