"""The "Layers" box of the Viewer tab's top row.

Lists the layers in draw order (top row is drawn last, the base layer is the last row) with a
visibility toggle, and holds the buttons New label layer, Up, Down and Delete. Selecting an editable
label layer makes it the paint target; for a non-base image layer the box also sets the colormap and
the display range. The widgets are thin: every change goes through the controller callbacks, and the
list is rebuilt from ``viewer_layer_rows`` whenever the controller renders (so layers added or removed
from the GUI, from the Python layers API or by a scan reload show up).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Optional

CMAPS = ("gray", "hot", "red", "green", "blue")
_ON = "☑"
_OFF = "☐"


def _fmt(value: float) -> str:
    return f"{float(value):g}"


class LayersBox(ttk.LabelFrame):
    def __init__(self, parent: tk.Misc, *, callbacks, on_changed: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent, text="Layers", padding=(6, 4))
        self._callbacks = callbacks
        self._on_changed = on_changed
        self._rows: list[dict] = []
        self._selected: Optional[str] = None
        self._synced: Optional[tuple] = None
        self._busy = False
        self.columnconfigure(0, weight=1)

        list_frame = ttk.Frame(self)
        list_frame.grid(row=0, column=0, sticky="ew")
        list_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_frame,
            columns=("vis", "name", "kind"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        self.tree.heading("vis", text="")
        self.tree.heading("name", text="Name")
        self.tree.heading("kind", text="Kind")
        self.tree.column("vis", width=24, minwidth=24, stretch=False, anchor="center")
        self.tree.column("name", width=90, minwidth=60, stretch=True)
        self.tree.column("kind", width=44, minwidth=40, stretch=False)
        self.tree.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-1>", self._on_click, add="+")

        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.new_button = ttk.Button(buttons, text="New label layer", command=self.new_layer)
        self.new_button.pack(side=tk.LEFT, padx=(0, 1))
        self.up_button = ttk.Button(buttons, text="Up", width=3, command=lambda: self.move("up"))
        self.up_button.pack(side=tk.LEFT, padx=1)
        self.down_button = ttk.Button(buttons, text="Down", width=4, command=lambda: self.move("down"))
        self.down_button.pack(side=tk.LEFT, padx=1)
        self.delete_button = ttk.Button(buttons, text="Delete", width=5, command=self.delete)
        self.delete_button.pack(side=tk.LEFT, padx=(1, 0))

        style = ttk.Frame(self)
        style.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(style, text="Colormap").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.cmap_var = tk.StringVar(master=self, value="gray")
        self.cmap_combo = ttk.Combobox(style, textvariable=self.cmap_var, values=CMAPS, state="disabled", width=6)
        self.cmap_combo.grid(row=0, column=1, sticky="w")
        self.apply_button = ttk.Button(style, text="Apply", width=6, command=self.apply_style, state="disabled")
        self.apply_button.grid(row=0, column=2, sticky="e", padx=(6, 0))
        ttk.Label(style, text="Min").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(3, 0))
        self.min_var = tk.StringVar(master=self, value="")
        self.max_var = tk.StringVar(master=self, value="")
        range_row = ttk.Frame(style)
        range_row.grid(row=1, column=1, columnspan=2, sticky="w", pady=(3, 0))
        self.min_entry = ttk.Entry(range_row, textvariable=self.min_var, width=6, state="disabled")
        self.min_entry.pack(side=tk.LEFT)
        ttk.Label(range_row, text="Max").pack(side=tk.LEFT, padx=(6, 4))
        self.max_entry = ttk.Entry(range_row, textvariable=self.max_var, width=6, state="disabled")
        self.max_entry.pack(side=tk.LEFT)
        for entry in (self.min_entry, self.max_entry):
            entry.bind("<Return>", lambda _e: self.apply_style())
        self.error_var = tk.StringVar(master=self, value="")
        ttk.Label(self, textvariable=self.error_var, foreground="#b00020", wraplength=210).grid(
            row=3, column=0, sticky="w"
        )
        self.refresh()

    # ----- state -----

    @property
    def selected_layer(self) -> Optional[str]:
        return self._selected

    def _row(self, layer_id: Optional[str]) -> Optional[dict]:
        for row in self._rows:
            if row["id"] == layer_id:
                return row
        return None

    def refresh(self) -> None:
        """Rebuild the list from the controller; keeps the selection and any typed range."""
        getter = getattr(self._callbacks, "viewer_layer_rows", None)
        rows = list(getter()) if callable(getter) else []
        sel_getter = getattr(self._callbacks, "viewer_selected_layer", None)
        ctrl_sel = sel_getter() if callable(sel_getter) else None
        ids = [r["id"] for r in rows]
        if ctrl_sel is not None and ctrl_sel in ids:
            self._selected = ctrl_sel  # the paint target (new layer, API, Python) wins
        elif self._selected not in ids:
            self._selected = None
        else:
            chosen = next(r for r in rows if r["id"] == self._selected)
            if chosen["kind"] == "label" and chosen["editable"]:
                self._selected = None  # the paint target was cleared elsewhere
        self._rows = rows
        self._busy = True
        try:
            self.tree.delete(*self.tree.get_children())
            for row in rows:
                name = f"{row['name']} (base)" if row["base"] else str(row["name"])
                self.tree.insert(
                    "", tk.END, iid=row["id"], values=(_ON if row["visible"] else _OFF, name, row["kind"])
                )
            if self._selected is not None:
                self.tree.selection_set(self._selected)
                self.tree.see(self._selected)
        finally:
            self._busy = False
        self._refresh_buttons()
        self._refresh_style()

    def _refresh_buttons(self) -> None:
        row = self._row(self._selected)
        getter = getattr(self._callbacks, "viewer_paint_state", None)
        state = getter() if callable(getter) else {}
        self.new_button.configure(state="normal" if state.get("can_new") else "disabled")
        self.up_button.configure(state="normal" if row and row["can_up"] else "disabled")
        self.down_button.configure(state="normal" if row and row["can_down"] else "disabled")
        self.delete_button.configure(state="normal" if row and row["can_delete"] else "disabled")

    def _refresh_style(self) -> None:
        row = self._row(self._selected)
        if row is None or not row["can_style"]:
            self._synced = None
            self.cmap_var.set("gray")
            self.min_var.set("")
            self.max_var.set("")
            self.cmap_combo.configure(state="disabled")
            self.min_entry.configure(state="disabled")
            self.max_entry.configure(state="disabled")
            self.apply_button.configure(state="disabled")
            self.error_var.set("")
            return
        self.cmap_combo.configure(state="readonly")
        self.min_entry.configure(state="normal")
        self.max_entry.configure(state="normal")
        self.apply_button.configure(state="normal")
        key = (row["id"], row["cmap"], row["window"])
        if key != self._synced:  # do not overwrite what the user is typing on unrelated redraws
            self._synced = key
            self.cmap_var.set(row["cmap"])
            window = row["window"]
            self.min_var.set("" if window is None else _fmt(window[0]))
            self.max_var.set("" if window is None else _fmt(window[1]))
            self.error_var.set("")

    # ----- user actions -----

    def _call(self, name: str, *args):
        handler = getattr(self._callbacks, name, None)
        if not callable(handler):
            return None
        return handler(*args)

    def _after_change(self) -> None:
        self.refresh()
        if self._on_changed is not None:
            self._on_changed()

    def _on_select(self, _event: Optional[tk.Event] = None) -> None:
        if self._busy:
            return
        chosen = self.tree.selection()
        layer_id = chosen[0] if chosen else None
        if layer_id == self._selected:
            return  # the echo of a refresh
        self._selected = layer_id
        self._call("on_viewer_layer_select", layer_id)
        self._after_change()

    def _on_click(self, event: tk.Event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        layer_id = self.tree.identify_row(event.y)
        if layer_id:
            self.toggle_visible(layer_id)

    def toggle_visible(self, layer_id: str) -> None:
        row = self._row(layer_id)
        if row is None:
            return
        self._call("on_viewer_layer_visible", layer_id, not row["visible"])
        self._after_change()

    def new_layer(self) -> None:
        handler = getattr(self._callbacks, "on_viewer_paint_new_layer", None)
        if not callable(handler):
            return
        try:
            handler()
        except ValueError as exc:
            messagebox.showerror("New label layer", str(exc), parent=self)
        self._after_change()

    def move(self, direction: str) -> None:
        if self._selected is None:
            return
        try:
            self._call("on_viewer_layer_move", self._selected, direction)
        except ValueError as exc:
            messagebox.showerror("Layers", str(exc), parent=self)
        self._after_change()

    def delete(self) -> None:
        if self._selected is None:
            return
        try:
            self._call("on_viewer_layer_delete", self._selected)
        except ValueError as exc:
            messagebox.showerror("Layers", str(exc), parent=self)
        self._after_change()

    def apply_style(self) -> None:
        """Send the colormap and range; empty Min and Max mean the automatic window."""
        row = self._row(self._selected)
        if row is None or not row["can_style"]:
            return
        lo_text, hi_text = self.min_var.get().strip(), self.max_var.get().strip()
        window = None
        if lo_text or hi_text:
            try:
                lo, hi = float(lo_text), float(hi_text)
            except ValueError:
                self.error_var.set(f"Min and Max: got {lo_text!r} and {hi_text!r}, expected two numbers or both empty")
                return
            if not lo < hi:
                self.error_var.set(f"Min and Max: got {lo_text!r} and {hi_text!r}, expected Min < Max")
                return
            window = (lo, hi)
        try:
            self._call("on_viewer_layer_style", row["id"], str(self.cmap_var.get()), window)
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.error_var.set("")
        self._after_change()
