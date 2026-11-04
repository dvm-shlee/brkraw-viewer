"""Window geometry: the top row fits, the status bar stays visible, the window stays on screen.

``fit_geometry`` is a pure function and is tested without Tk. The GUI tests need a display and
``BRKRAW_VIEWER_SMOKE=1`` (use ``xvfb-run``) like the other GUI tests; the window is built with a
real ``MainWindow`` and ``run_app``'s geometry steps are applied to it.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from brkraw_viewer.app import bootstrap
from brkraw_viewer.app.bootstrap import (
    MIN_HEIGHT,
    MIN_WIDTH,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    fit_geometry,
    geometry_string,
)
from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.ui.main import MainWindow


def _inside(area, x, y, w, h):
    ax, ay, aw, ah = area
    return x >= ax and y >= ay and x + w <= ax + aw and y + h <= ay + ah


# ---- pure function ----

@pytest.mark.parametrize(
    "area",
    [(0, 0, 1280, 944), (0, 25, 1024, 600), (-1920, 0, 1366, 700), (0, 0, 640, 400), (100, 50, 300, 200)],
)
def test_fit_geometry_stays_inside_small_area(area):
    w, h, x, y, min_w, min_h = fit_geometry((WINDOW_WIDTH, WINDOW_HEIGHT), (1400, MIN_HEIGHT), area)
    assert _inside(area, x, y, w, h)
    assert w <= area[2] and h <= area[3]
    assert min_w <= w <= area[2]
    assert min_h <= h <= area[3]
    assert min_w <= area[2] and min_h <= area[3]


def test_fit_geometry_keeps_request_on_large_area():
    area = (0, 0, 2560, 1400)
    w, h, x, y, min_w, min_h = fit_geometry((WINDOW_WIDTH, WINDOW_HEIGHT), (MIN_WIDTH, MIN_HEIGHT), area)
    assert (w, h) == (WINDOW_WIDTH, WINDOW_HEIGHT)
    assert (min_w, min_h) == (MIN_WIDTH, MIN_HEIGHT)
    assert _inside(area, x, y, w, h)
    assert x == (area[2] - w) // 2 and y == (area[3] - h) // 2


def test_fit_geometry_minimum_never_exceeds_area():
    area = (0, 0, 700, 500)
    w, h, x, y, min_w, min_h = fit_geometry((2000, 2000), (1500, 1500), area)
    assert min_w <= area[2] and min_h <= area[3]
    assert (min_w, min_h) == (w, h)
    assert _inside(area, x, y, w, h)


@pytest.mark.parametrize(
    "size, expected",
    [((1350, 640, 8, 8), "1350x640+8+8"), ((800, 600, -1280, 40), "800x600+-1280+40"), ((900, 500, -5, -7), "900x500+-5+-7")],
)
def test_geometry_string_signs(size, expected):
    assert geometry_string(*size) == expected


# ---- real window ----

def _has_display() -> bool:
    try:
        r = tk.Tk()
    except tk.TclError:
        return False
    r.destroy()
    return True


@pytest.fixture
def window(monkeypatch, tmp_path):
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("GUI tests need BRKRAW_VIEWER_SMOKE=1 (run under Xvfb)")
    if not _has_display():
        pytest.fail("BRKRAW_VIEWER_SMOKE=1 needs a display (run under Xvfb)")
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * 1024**3, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    from brkraw_viewer.ui import assets as _assets

    _assets._load_icon_cached.cache_clear()
    root = tk.Tk()
    try:
        root.minsize(MIN_WIDTH, MIN_HEIGHT)
        root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        ctrl = ViewerController()
        ctrl._worker = SimpleNamespace(submit=lambda req: None, log_queue=None, check_results=lambda: None)
        win = MainWindow(root, ctrl)
        win.tabs.select_tab("Viewer")
        bootstrap.center_on_current_monitor(root)
        _pump(root)
        yield SimpleNamespace(root=root, win=win)
    finally:
        try:
            for job in root.tk.call("after", "info"):
                try:
                    root.after_cancel(job)
                except tk.TclError:
                    pass
            root.destroy()
        except tk.TclError:
            pass
        finally:
            if getattr(tk, "_default_root", None) is root:
                tk._default_root = None


def _pump(root, rounds: int = 5) -> None:
    for _ in range(rounds):
        root.update_idletasks()
        root.update()


def _top(win):
    return win.tabs.get_tab("Viewer")._tab_instance.top


def _right_edge_of_boxes(win) -> int:
    top = _top(win)
    return max(b.winfo_rootx() + b.winfo_width() for b in top._boxes)


def test_top_row_boxes_fit_in_window(window):
    root, win = window.root, window.win
    win_right = root.winfo_rootx() + root.winfo_width()
    assert _right_edge_of_boxes(win) <= win_right
    # even gaps between neighbouring boxes
    boxes = sorted(_top(win)._boxes, key=lambda b: b.winfo_rootx())
    gaps = {boxes[i + 1].winfo_rootx() - (boxes[i].winfo_rootx() + boxes[i].winfo_width()) for i in range(4)}
    assert len(gaps) == 1


def test_top_row_boxes_share_one_top_edge(window):
    assert len({b.winfo_rooty() for b in _top(window.win)._boxes}) == 1


def test_minimum_width_is_the_top_row_width(window):
    root, win = window.root, window.win
    min_w, _ = root.minsize()
    assert min_w >= _top(win).required_width()
    assert min_w <= bootstrap.usable_area(root)[2]


def test_status_bar_visible_at_start_and_minimum_height(window):
    root, win = window.root, window.win
    status = win.status

    def bottom_ok() -> bool:
        _pump(root)
        return status.winfo_ismapped() and status.winfo_y() + status.winfo_height() <= win.winfo_height() and (
            status.winfo_height() > 1
        )

    assert bottom_ok()
    _, min_h = root.minsize()
    root.geometry(f"{root.winfo_width()}x{min_h}")
    assert bottom_ok()


def test_window_inside_usable_area_and_minimum_capped(window):
    root = window.root
    area = bootstrap.usable_area(root)
    _pump(root)
    assert _inside(area, root.winfo_x(), root.winfo_y(), root.winfo_width(), root.winfo_height())
    min_w, min_h = root.minsize()
    assert min_w <= area[2] and min_h <= area[3]
