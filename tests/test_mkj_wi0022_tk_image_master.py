"""WI-0022: UI images are bound to their widget's own Tk root.

A second ``tk.Tk()`` in one process used to fail with ``TclError: image "pyimageN" does not
exist`` because cached icons were bound to the first root. These tests build ``MainWindow`` on
root A, destroy it, build it on root B without ``cache_clear``, and check that ``load_icon``
returns distinct images for distinct masters. GUI tests need a display and BRKRAW_VIEWER_SMOKE=1.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk

import pytest

from brkraw_viewer.app.controller import ViewerController
from brkraw_viewer.ui.assets import load_icon
from brkraw_viewer.ui.main import MainWindow


def _gui_ready() -> None:
    has = sys.platform.startswith("win") or sys.platform == "darwin" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )
    if not has:
        pytest.skip("No display available for Tk")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI tests.")


def _tk() -> tk.Tk:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.withdraw()
    return root


def test_main_window_on_two_roots_in_turn() -> None:
    _gui_ready()
    for _ in range(2):
        root = _tk()
        MainWindow(root, ViewerController())
        root.update_idletasks()
        root.destroy()


def test_load_icon_differs_per_master() -> None:
    _gui_ready()
    a = _tk()
    b = _tk()
    try:
        ia = load_icon("registry.png", size=(18, 18), master=a)
        ib = load_icon("registry.png", size=(18, 18), master=b)
        assert ia is not None and ib is not None
        assert ia is not ib
        assert load_icon("registry.png", size=(18, 18), master=a) is ia
    finally:
        b.destroy()
        a.destroy()
