"""WI-0025: every Tk variable and image gets an explicit master (the window's own root).

While ``MainWindow`` is built, ``tk.Variable.__init__`` and ``tk.Image.__init__`` are recorded; none
may be created with ``master=None`` and each must resolve to the root being built. GUI tests need a
display and BRKRAW_VIEWER_SMOKE=1 (same gate as WI-0022).
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


@pytest.fixture
def recorder(monkeypatch):
    """Record (class name, master argument) of every Tk variable and image created."""
    records: list[tuple[str, object]] = []
    orig_var = tk.Variable.__init__
    orig_img = tk.Image.__init__

    def var_init(self, master=None, *a, **kw):
        records.append((type(self).__name__, master))
        return orig_var(self, master, *a, **kw)

    def img_init(self, imgtype, name=None, cnf={}, master=None, **kw):
        records.append((type(self).__name__, master))
        return orig_img(self, imgtype, name, cnf, master, **kw)

    monkeypatch.setattr(tk.Variable, "__init__", var_init)
    monkeypatch.setattr(tk.Image, "__init__", img_init)
    return records


def _root_of(master):
    return master._root() if master is not None else None


def test_main_window_variables_and_images_have_master(isolated, recorder) -> None:
    _gui_ready()
    from brkraw_viewer.ui.main import MainWindow

    for _ in range(2):  # a second root after the first is destroyed
        root = _tk()
        recorder.clear()
        try:
            MainWindow(root, isolated())
            root.update_idletasks()
            assert len(recorder) > 40
            bad = [(n, m) for n, m in recorder if m is None or _root_of(m) is not root]
            assert bad == []
        finally:
            _destroy_root(root)


def test_bootstrap_icon_has_master(recorder, monkeypatch, tmp_path) -> None:
    _gui_ready()
    import shutil
    from pathlib import Path

    from brkraw_viewer.app import bootstrap

    src_png = Path(bootstrap.__file__).resolve().parents[1] / "assets" / "icon.png"
    # _set_app_icon looks for <file>.parents[2]/assets/icon.png; give it one
    (tmp_path / "assets").mkdir()
    shutil.copy(src_png, tmp_path / "assets" / "icon.png")
    (tmp_path / "x" / "y").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "__file__", str(tmp_path / "x" / "y" / "bootstrap.py"))

    root = _tk()
    try:
        recorder.clear()
        bootstrap._set_app_icon(root)
        assert recorder, "icon.png not loaded"
        assert all(m is root for _, m in recorder)
    finally:
        bootstrap._ICON_REF = None
        _destroy_root(root)
