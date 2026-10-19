from __future__ import annotations

import datetime as dt
import logging
import shutil
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

from brkraw.core import config as config_core

logger = logging.getLogger("brkraw.viewer")


class ConfigTab:
    TITLE = "Config"

    def __init__(self, parent: tk.Misc, callbacks) -> None:
        self._cb = callbacks
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        try:
            self.frame.grid_anchor("n")
        except Exception:
            pass

        self._config_text: tk.Text
        self._config_path_var: tk.StringVar
        self._build_config_tab(self.frame)
        self._load_config_text()

    def _build_config_tab(self, config_tab: ttk.Frame) -> None:
        config_tab.columnconfigure(0, weight=1)
        config_tab.rowconfigure(1, weight=1)
        config_bar = ttk.Frame(config_tab, padding=(6, 6))
        config_bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(config_bar, text="Save", command=self._save_config_text).pack(side=tk.LEFT)
        ttk.Button(config_bar, text="Backup", command=self._backup_config_text).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(config_bar, text="Reset", command=self._reset_config_text).pack(side=tk.LEFT, padx=(6, 0))
        self._config_path_var = tk.StringVar(master=config_tab, value="")
        ttk.Label(config_bar, textvariable=self._config_path_var).pack(side=tk.LEFT, padx=(12, 0))

        config_body = ttk.Frame(config_tab, padding=(6, 6))
        config_body.grid(row=1, column=0, sticky="nsew")
        config_body.columnconfigure(0, weight=1)
        config_body.rowconfigure(0, weight=1)
        self._config_text = tk.Text(config_body, wrap="none")
        self._config_text.grid(row=0, column=0, sticky="nsew")
        config_scroll = ttk.Scrollbar(config_body, orient="vertical", command=self._config_text.yview)
        config_scroll.grid(row=0, column=1, sticky="ns")
        self._config_text.configure(yscrollcommand=config_scroll.set)

    def _load_config_text(self) -> None:
        try:
            paths = config_core.ensure_initialized(root=None, create_config=True, exist_ok=True)
            self._config_path_var.set(str(paths.config_file))
            content = paths.config_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to load config.yaml: %s", exc, exc_info=logger.isEnabledFor(logging.DEBUG))
            self._config_path_var.set("")
            self._config_text.delete("1.0", tk.END)
            self._config_text.insert(tk.END, f"# Failed to load config.yaml: {exc}\n")
            return
        self._config_text.delete("1.0", tk.END)
        self._config_text.insert(tk.END, content)

    def _save_config_text(self) -> None:
        try:
            paths = config_core.ensure_initialized(root=None, create_config=True, exist_ok=True)
            self._config_path_var.set(str(paths.config_file))
            text = self._config_text.get("1.0", tk.END)
            paths.config_file.write_text(text, encoding="utf-8")
            logger.info("Saved config.yaml: %s", paths.config_file)
        except Exception as exc:
            logger.error("Failed to save config.yaml: %s", exc, exc_info=logger.isEnabledFor(logging.DEBUG))
            messagebox.showerror("Save error", f"Failed to save config.yaml:\n{exc}")

    def _backup_config_text(self) -> None:
        try:
            paths = config_core.ensure_initialized(root=None, create_config=True, exist_ok=True)
            config_path = paths.config_file
            self._config_path_var.set(str(config_path))
            if not config_path.exists():
                messagebox.showwarning("Backup", f"Config file not found:\n{config_path}")
                return
            ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = Path(f"{config_path}.bak-{ts}")
            shutil.copy2(config_path, backup_path)
            logger.info("Backed up config.yaml: %s", backup_path)
            messagebox.showinfo("Backup", f"Created backup:\n{backup_path}")
        except Exception as exc:
            logger.error("Failed to back up config.yaml: %s", exc, exc_info=logger.isEnabledFor(logging.DEBUG))
            messagebox.showerror("Backup error", f"Failed to back up config.yaml:\n{exc}")

    def _reset_config_text(self) -> None:
        try:
            config_core.reset_config(root=None)
            logger.info("Reset config.yaml to defaults.")
        except Exception as exc:
            logger.error("Failed to reset config.yaml: %s", exc, exc_info=logger.isEnabledFor(logging.DEBUG))
            messagebox.showerror("Reset error", f"Failed to reset config.yaml:\n{exc}")
            return
        self._load_config_text()
