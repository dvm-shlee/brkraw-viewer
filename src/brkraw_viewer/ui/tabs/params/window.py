from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, List


class ParamsTab:
    TITLE = "Params"

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        setattr(self.frame, "_tab_instance", self)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        self._param_scope_var = tk.StringVar(master=parent, value="all")
        self._param_query_var = tk.StringVar(master=parent, value="")
        self._params_sort_key = "file"
        self._params_sort_desc = False
        self._params_tree: ttk.Treeview

        self._params_summary_vars: dict[str, tk.StringVar] = {}
        self._params_summary_entries: dict[str, ttk.Entry] = {}

        self._build_params_tab(self.frame)

    def _build_params_tab(self, parent: ttk.Frame) -> None:
        params_tab = parent
        params_tab.columnconfigure(0, weight=1)
        params_tab.rowconfigure(1, weight=1)

        summary_frame = ttk.LabelFrame(params_tab, text="Scan Info", padding=(8, 8))
        summary_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        for col in range(4):
            summary_frame.columnconfigure(col * 2 + 1, weight=1)

        self._params_summary_vars = {
            "Protocol": tk.StringVar(master=parent, value=""),
            "Method": tk.StringVar(master=parent, value=""),
            "TR (ms)": tk.StringVar(master=parent, value=""),
            "TE (ms)": tk.StringVar(master=parent, value=""),
            "FlipAngle (degree)": tk.StringVar(master=parent, value=""),
            "Dim": tk.StringVar(master=parent, value=""),
            "Shape": tk.StringVar(master=parent, value=""),
            "FOV (mm)": tk.StringVar(master=parent, value=""),
        }
        self._params_summary_entries = {}
        for idx, (label, var) in enumerate(self._params_summary_vars.items()):
            row = idx // 4
            col = (idx % 4) * 2
            ttk.Label(summary_frame, text=label).grid(row=row, column=col, sticky="w", padx=6, pady=3)
            entry = ttk.Entry(summary_frame, textvariable=var, width=18)
            entry.grid(row=row, column=col + 1, sticky="ew", padx=(0, 6), pady=3)
            entry.configure(state="readonly")
            self._params_summary_entries[label] = entry

        search_frame = ttk.Frame(params_tab, padding=(6, 6))
        search_frame.grid(row=1, column=0, sticky="nsew")
        search_frame.columnconfigure(0, weight=1)
        search_frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(search_frame)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Target").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self._param_scope_var,
            values=("all", "acqp", "method", "reco", "visu_pars"),
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(8, 12))
        ttk.Label(controls, text="Query").grid(row=0, column=2, sticky="w")
        query_entry = ttk.Entry(controls, textvariable=self._param_query_var)
        query_entry.grid(row=0, column=3, sticky="ew", padx=(8, 12))
        query_entry.bind("<Return>", lambda *_: self._run_param_search())
        ttk.Button(controls, text="Search", command=self._run_param_search).grid(row=0, column=4, sticky="e")

        results_frame = ttk.Frame(search_frame)
        results_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(results_frame, orient=tk.VERTICAL)
        paned.grid(row=0, column=0, sticky="nsew")
        results_frame.rowconfigure(0, weight=1)

        columns = ("file", "key", "type", "value", "full_value")
        tree_frame = ttk.Frame(paned)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", displaycolumns=("file", "key", "type", "value"), height=5)
        tree.grid(row=0, column=0, sticky="nsew")
        tree.heading("file", text="File", anchor="w", command=lambda: self._params_sort_by("file"))
        tree.heading("key", text="Key", anchor="w", command=lambda: self._params_sort_by("key"))
        tree.heading("type", text="Type", anchor="center", command=lambda: self._params_sort_by("type"))
        tree.heading("value", text="Value", anchor="w", command=lambda: self._params_sort_by("value"))
        tree.column("file", width=110, anchor="w")
        tree.column("key", width=220, anchor="w")
        tree.column("type", width=90, anchor="center")
        tree.column("value", width=320, anchor="w")
        self._params_tree = tree
        self._update_params_sort_heading()

        vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vscroll.set)
        tree.bind("<<TreeviewSelect>>", self._on_result_select)

        detail_frame = ttk.LabelFrame(paned, text="Value Detail", padding=(6, 4))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self._detail_text = tk.Text(detail_frame, wrap="word")
        self._detail_text.grid(row=0, column=0, sticky="nsew")
        
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self._detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self._detail_text.configure(yscrollcommand=detail_scroll.set, state=tk.DISABLED)
        
        paned.add(tree_frame, weight=3)
        paned.add(detail_frame, weight=1)

    def _run_param_search(self) -> None:
        query = (self._param_query_var.get() or "").strip()
        scope = (self._param_scope_var.get() or "all").strip()
        
        handler = getattr(self._cb, "on_param_search", None)
        if callable(handler):
            result = handler(scope, query)
            if isinstance(result, dict):
                self.set_search_results(result.get("rows", []), truncated=int(result.get("truncated", 0) or 0))
                return
        self.set_search_results([])

    def set_summary(self, summary: dict[str, Any]) -> None:
        for key, var in self._params_summary_vars.items():
            val = summary.get(key, "") if isinstance(summary, dict) else ""
            var.set(str(val) if val is not None else "")

    def set_search_results(self, rows: List[dict[str, Any]], *, truncated: int = 0) -> None:
        self._params_tree.delete(*self._params_tree.get_children())
        for row in rows:
            display_val = row.get("value", "")
            full_val = row.get("full_value", "")
            if not full_val and display_val:
                full_val = display_val
            self._params_tree.insert(
                "",
                "end",
                values=(
                    row.get("file", ""),
                    row.get("key", ""),
                    row.get("type", ""),
                    display_val,
                    full_val,
                ),
            )
        if truncated:
            self._params_tree.insert(
                "",
                "end",
                values=("", "", "", f"... {truncated} more result(s)", ""),
                tags=("truncated",),
            )
        self._apply_params_sort()
        self._update_params_sort_heading()
        self._clear_detail()

    def _params_sort_by(self, key: str) -> None:
        if self._params_sort_key == key:
            self._params_sort_desc = not self._params_sort_desc
        else:
            self._params_sort_key = key
            self._params_sort_desc = False
        self._apply_params_sort()
        self._update_params_sort_heading()

    def _apply_params_sort(self) -> None:
        if not self._params_tree or not self._params_sort_key:
            return

        col_map = {"file": 0, "key": 1, "type": 2, "value": 3}
        idx = col_map.get(self._params_sort_key)
        if idx is None:
            return

        items = list(self._params_tree.get_children())
        regular_items = []
        truncated_items = []

        for item in items:
            tags = self._params_tree.item(item, "tags")
            if "truncated" in tags:
                truncated_items.append(item)
            else:
                regular_items.append(item)

        def _sort_val(item_id: str) -> tuple[int, Any]:
            values = self._params_tree.item(item_id, "values")
            raw = values[idx] if idx < len(values) else ""
            try:
                return (0, float(raw))
            except Exception:
                return (1, str(raw).lower())

        regular_items.sort(key=_sort_val, reverse=self._params_sort_desc)

        for item in regular_items:
            self._params_tree.move(item, "", "end")
        for item in truncated_items:
            self._params_tree.move(item, "", "end")

    def _update_params_sort_heading(self) -> None:
        if not self._params_tree:
            return
        arrow = "▼" if self._params_sort_desc else "▲"
        for col in ("file", "key", "type", "value"):
            label = col.title()
            if col == self._params_sort_key:
                label = f"{label} {arrow}"
            self._params_tree.heading(col, text=label)

    def _clear_detail(self) -> None:
        if not hasattr(self, "_detail_text"):
            return
        self._detail_text.configure(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.configure(state=tk.DISABLED)

    def _on_result_select(self, _event: tk.Event) -> None:
        if not hasattr(self, "_detail_text"):
            return
        items = self._params_tree.selection()
        if not items:
            self._clear_detail()
            return
        values = self._params_tree.item(items[0], "values")
        # value is at index 3, full_value at index 4
        value = ""
        if len(values) > 4:
            value = values[4]
        elif len(values) > 3:
            value = values[3]
            
        if isinstance(value, str):
            value = value.replace("\\n", "\n")
            try:
                import ast
                import pprint
                val_obj = ast.literal_eval(value)
                if isinstance(val_obj, (dict, list, tuple)):
                    value = pprint.pformat(val_obj, indent=2)
            except Exception:
                pass

        self._detail_text.configure(state=tk.NORMAL)
        self._detail_text.delete("1.0", tk.END)
        self._detail_text.insert(tk.END, str(value))
        self._detail_text.configure(state=tk.DISABLED)
