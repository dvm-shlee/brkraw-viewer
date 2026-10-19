from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from brkraw_viewer.ui.assets import load_icon
from brkraw_viewer.ui.components.icon_button import IconButton
from ..sharedtypes import Command


class TopBar(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        path_var: tk.StringVar,
        on_open_folder: Command,
        on_open_archive: Command,
        on_refresh: Command,
        on_open_registry: Command,
    ) -> None:
        super().__init__(master, padding=(10, 10, 10, 6))

        registry_icon = load_icon("registry.png", size=(18, 18), master=self)
        if registry_icon is not None:
            IconButton(self, image=registry_icon, command=on_open_registry).pack(side="right", padx=(6, 6))
        else:
            ttk.Button(self, text="Registry", command=on_open_registry).pack(side="right", padx=(6, 6))

        load_button = ttk.Menubutton(self, text="Load")
        load_menu = tk.Menu(load_button, tearoff=False)
        load_menu.add_command(label="Folder (Study)...", command=on_open_folder)
        load_menu.add_command(label="Archive File (.zip/.PvDatasets)...", command=on_open_archive)
        load_button.configure(menu=load_menu)
        load_button.pack(side="left", padx=(0, 6))

        ttk.Button(self, text="Refresh", command=on_refresh).pack(side="left")

        ttk.Label(self, text="Path:").pack(side="left", padx=(12, 6))
        entry = ttk.Entry(self, textvariable=path_var, width=70, state="readonly")
        entry.pack(side="left", fill="x", expand=True)
