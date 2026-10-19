from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class Sidebar(ttk.Frame):
    """Sidebar widget that lists scans and recos and emits selection callbacks."""
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_select_scan: Callable[[int], None],
        on_select_reco: Callable[[int], None],
    ) -> None:
        """Build the sidebar UI and wire selection callbacks."""
        super().__init__(master, padding=(0, 0, 8, 0))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)  # expand scan list area
        self.rowconfigure(4, weight=1)  # expand reco list area

        self._on_select_scan = on_select_scan  # scan selection callback
        self._on_select_reco = on_select_reco  # reco selection callback
        self._scan_ids: list[int] = []  # listbox index -> scan id
        self._reco_ids: list[int] = []  # listbox index -> reco id

        self._scan_label_var = tk.StringVar(master=self, value="Scans (0)")  # scan count label
        self._reco_label_var = tk.StringVar(master=self, value="Recos (0)")  # reco count label
        self._scan_selected_var = tk.StringVar(master=self, value="Selected: -")  # scan selection text
        self._reco_selected_var = tk.StringVar(master=self, value="Selected: -")  # reco selection text

        def _auto_scrollbar(sb: ttk.Scrollbar) -> Callable[[float, float], None]:
            def _handler(first: float, last: float) -> None:
                try:
                    sb.set(first, last)
                    if float(first) <= 0.0 and float(last) >= 1.0:
                        sb.grid_remove()
                    else:
                        sb.grid()
                except Exception:
                    pass
            return _handler

        # Scan listbox (top)
        ttk.Label(self, textvariable=self._scan_label_var).grid(row=0, column=0, sticky="w", pady=(0, 4))  # top label
        scans_box = ttk.Frame(self)
        scans_box.grid(row=1, column=0, sticky="nsew")
        scans_box.columnconfigure(0, weight=1)  # allow listbox to expand
        scans_box.rowconfigure(0, weight=1)
        scans_box.rowconfigure(1, weight=0)

        self._scan_listbox = tk.Listbox(scans_box, width=20, height=18, exportselection=False)  # scan list
        self._scan_listbox.grid(row=0, column=0, sticky="nsew")
        self._scan_listbox.bind("<<ListboxSelect>>", self._handle_scan_select)

        scan_scroll_y = ttk.Scrollbar(scans_box, orient="vertical", command=self._scan_listbox.yview)
        scan_scroll_y.grid(row=0, column=1, sticky="ns")
        scan_scroll_x = ttk.Scrollbar(scans_box, orient="horizontal", command=self._scan_listbox.xview)
        scan_scroll_x.grid(row=1, column=0, sticky="ew")
        self._scan_listbox.configure(
            yscrollcommand=_auto_scrollbar(scan_scroll_y),
            xscrollcommand=_auto_scrollbar(scan_scroll_x),
        )

        ttk.Label(self, textvariable=self._scan_selected_var).grid(row=2, column=0, sticky="w", pady=(4, 8))  # selection text
        
        # Reco listbox (bottom)
        ttk.Label(self, textvariable=self._reco_label_var).grid(row=3, column=0, sticky="w", pady=(0, 4))  # middle label
        recos_box = ttk.Frame(self)
        recos_box.grid(row=4, column=0, sticky="nsew")
        recos_box.columnconfigure(0, weight=1)  # allow listbox to expand
        recos_box.rowconfigure(0, weight=1)
        recos_box.rowconfigure(1, weight=0)

        self._reco_listbox = tk.Listbox(recos_box, width=20, height=8, exportselection=False)  # reco list
        self._reco_listbox.grid(row=0, column=0, sticky="nsew")
        self._reco_listbox.bind("<<ListboxSelect>>", self._handle_reco_select)

        reco_scroll_y = ttk.Scrollbar(recos_box, orient="vertical", command=self._reco_listbox.yview)
        reco_scroll_y.grid(row=0, column=1, sticky="ns")
        reco_scroll_x = ttk.Scrollbar(recos_box, orient="horizontal", command=self._reco_listbox.xview)
        reco_scroll_x.grid(row=1, column=0, sticky="ew")
        self._reco_listbox.configure(
            yscrollcommand=_auto_scrollbar(reco_scroll_y),
            xscrollcommand=_auto_scrollbar(reco_scroll_x),
        )

        ttk.Label(self, textvariable=self._reco_selected_var).grid(row=5, column=0, sticky="w", pady=(4, 0))  # selection text

    def set_scan_list(self, scan_ids: list[tuple[int, str]] | list[int]) -> None:
        """Replace the scan list with IDs or (id, label) pairs and reset selection."""
        self._scan_listbox.delete(0, "end")
        self._scan_ids = []
        for item in scan_ids:
            if isinstance(item, tuple):
                sid, label = item
            else:
                sid, label = int(item), str(item)
            self._scan_ids.append(int(sid))
            self._scan_listbox.insert("end", label)
        self._scan_label_var.set(f"Scans ({len(self._scan_ids)})")
        self._scan_selected_var.set("Selected: -")

    def set_reco_list(self, reco_ids: list[tuple[int, str]] | list[int]) -> None:
        """Replace the reco list with IDs or (id, label) pairs and reset selection."""
        self._reco_listbox.delete(0, "end")
        self._reco_ids = []
        for item in reco_ids:
            if isinstance(item, tuple):
                rid, label = item
            else:
                rid, label = int(item), str(item)
            self._reco_ids.append(int(rid))
            self._reco_listbox.insert("end", label)
        self._reco_label_var.set(f"Recos ({len(self._reco_ids)})")
        self._reco_selected_var.set("Selected: -")

    def select_scan_id(self, scan_id: int) -> None:
        """Programmatically select a scan ID if it exists in the list."""
        if not self._scan_ids:
            return
        try:
            idx = self._scan_ids.index(int(scan_id))
        except ValueError:
            return
        self._scan_listbox.selection_clear(0, "end")
        self._scan_listbox.selection_set(idx)
        self._scan_listbox.see(idx)
        self._scan_selected_var.set(f"Selected: {scan_id}")

    def select_reco_id(self, reco_id: int) -> None:
        """Programmatically select a reco ID if it exists in the list."""
        if not self._reco_ids:
            return
        try:
            idx = self._reco_ids.index(int(reco_id))
        except ValueError:
            return
        self._reco_listbox.selection_clear(0, "end")
        self._reco_listbox.selection_set(idx)
        self._reco_listbox.see(idx)
        self._reco_selected_var.set(f"Selected: {reco_id}")

    def _handle_scan_select(self, _evt: object) -> None:
        """Handle scan listbox selection events and invoke callback."""
        sel = self._scan_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._scan_ids):
            return
        scan_id = int(self._scan_ids[idx])
        self._scan_selected_var.set(f"Selected: {scan_id}")
        self._on_select_scan(scan_id)

    def _handle_reco_select(self, _evt: object) -> None:
        """Handle reco listbox selection events and invoke callback."""
        sel = self._reco_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._reco_ids):
            return
        reco_id = int(self._reco_ids[idx])
        self._reco_selected_var.set(f"Selected: {reco_id}")
        self._on_select_reco(reco_id)
