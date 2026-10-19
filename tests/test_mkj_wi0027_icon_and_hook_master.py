"""WI-0027: the window icon is found in the package assets; hook option vars get a master."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path

import pytest

import brkraw_viewer
from brkraw_viewer.app import bootstrap


def test_icon_path_is_package_asset() -> None:
    png, _ico = bootstrap._icon_paths()
    expected = Path(brkraw_viewer.__file__).resolve().parent / "assets" / "icon.png"
    assert png.exists()
    assert png == expected


def test_hook_option_var_gets_master_positionally() -> None:
    src = (Path(bootstrap.__file__).resolve().parents[1] / "ui" / "windows" / "hook_options.py").read_text()
    assert "tk.StringVar(self._window)" in src


def test_set_app_icon_keeps_image_bound_to_root() -> None:
    has = sys.platform.startswith("win") or sys.platform == "darwin" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    if not has:
        pytest.skip("No display available for Tk")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI tests.")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    try:
        bootstrap._ICON_REF = None
        bootstrap._set_app_icon(root)
        img = bootstrap._ICON_REF
        assert img is not None
        assert img.tk is root.tk
    finally:
        try:
            root.destroy()
        finally:
            if getattr(tk, "_default_root", None) is root:
                tk._default_root = None
