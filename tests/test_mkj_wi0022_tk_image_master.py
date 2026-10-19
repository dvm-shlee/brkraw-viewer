"""WI-0022: UI images are bound to their widget's own Tk root.

A second ``tk.Tk()`` in one process used to fail with ``TclError: image "pyimageN" does not
exist`` because cached icons were bound to the first root. These tests build ``MainWindow`` on
root A, destroy it, build it on root B without ``cache_clear``, and check that ``load_icon``
returns distinct images for distinct masters. GUI tests need a display and BRKRAW_VIEWER_SMOKE=1.

Rework 2 cause (found in the source): the per-root icon cache read the default root with
``tk._get_default_root()``, which creates a hidden ``Tk`` when there is none. The WI-0020 fixture
calls ``_load_icon_cached.cache_clear()`` before its ``tk.Tk()``, so the hidden root became the
default; the ROI tool's ``StringVar`` (no master) bound to it, Radiobutton choices never reached
the variable, and the WI-0020 s3-s5 mouse tests failed. ``test_no_default_root_is_created``
guards this. The window tests isolate the controller (no real worker, no home config) and tear
each root down like the WI-0020 fixture.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.ui import assets
from brkraw_viewer.ui.assets import load_icon

GB = 1024 * 1024 * 1024


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


def _destroy_root(root: tk.Tk) -> None:
    """Cancel every pending ``after`` job, destroy the root, reset the default root."""
    try:
        jobs = root.tk.splitlist(root.tk.call("after", "info"))
    except tk.TclError:
        jobs = ()
    for job in jobs:
        try:
            root.after_cancel(job)
        except tk.TclError:
            pass
    try:
        root.destroy()
    except tk.TclError:
        pass
    finally:
        if getattr(tk, "_default_root", None) is root:
            tk._default_root = None


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """No home config, no hooks, no real worker process (as the WI-0020 ``gui`` fixture)."""
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})

    def controller() -> ViewerController:
        ctrl = ViewerController()
        ctrl._worker = SimpleNamespace(submit=lambda req: None, log_queue=None, check_results=lambda: None)
        return ctrl

    return controller


def test_no_default_root_is_created(monkeypatch) -> None:
    monkeypatch.setattr(tk, "_default_root", None)
    assets._load_icon_cached.cache_clear()
    assert load_icon("registry.png", size=(18, 18)) is None
    assert tk._default_root is None


def test_main_window_on_two_roots_in_turn(isolated) -> None:
    _gui_ready()
    from brkraw_viewer.ui.main import MainWindow

    for _ in range(2):
        root = _tk()
        try:
            win = MainWindow(root, isolated())
            root.update_idletasks()
            assert tk._default_root is root
            panel = win.tabs.get_tab("Viewer")._tab_instance.right
            assert panel._roi_tool_var._root is root  # bound to this window's root
        finally:
            _destroy_root(root)


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
        _destroy_root(b)
        _destroy_root(a)
