"""WI-0020: GUI test of docs/user/try-new-features.md sections 2-6 in a real Tk window.

The smoke test only builds the window; this module drives it. A real, mapped ``tk.Tk`` root
holds ``MainWindow(root, ViewerController())`` and a synthetic 4D phantom is loaded the way the app
loads a scan (``_request_viewer_volume`` and the load answer), with the worker faked as in
tests/test_mkj_wi0005_roi_timecourse.py. Mouse input is simulated with ``event_generate`` on the
view canvases. One test per checklist section, named after it:

- s2 Launch: the axial, coronal and sagittal views exist after load.
- s3 ROI tool: Off / Square / Circle buttons; Off moves the crosshair, Square and Circle do not.
- s4 Drag to draw: press-drag-release sets a square and a circle ROI; Esc and Off clear it; a
  plain click sets nothing; another slice on that axis clears it, another frame does not.
- s5 Timecourse plot: the plot shows the ROI mean per frame and falls back after clear.
- s6 Python API: ``set_roi`` / ``roi_timecourse`` / ``clear_roi`` and the example hook's buttons,
  with the hook code taken from the doc text.

Runs only with a display and ``BRKRAW_VIEWER_SMOKE=1`` (use ``xvfb-run``); sections 1 and 7 of the
checklist (install, STYLE.md) are not GUI steps.
"""

from __future__ import annotations

import os
import re
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, TimecourseRequest
from brkraw_viewer.core.roi import RoiDrag, roi_mask
from brkraw_viewer.ui.main import MainWindow
from brkraw_viewer.utils.orientation import reorient_to_ras

GB = 1024 * 1024 * 1024
N = 5
SHAPE = (32, 28, 6, N)
# value = 1000 * frame + position code, so every frame has a different, known mean
_pos = np.arange(32 * 28 * 6, dtype=np.float32).reshape(32, 28, 6)
PHANTOM = np.stack([_pos + 1000.0 * f for f in range(N)], axis=-1)
DOC = Path(__file__).resolve().parents[1] / "docs" / "user" / "try-new-features.md"


def _has_display() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    image_info = {1: {"num_cycles": N, "dataobj": None}}

    def __init__(self):
        self.avail = {1: SimpleNamespace(file_visu_pars={})}

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        if frames is None:
            return PHANTOM.copy()
        start, stop = frames.split(":")
        return PHANTOM[..., int(start) : int(stop or N)].copy()


class Gui:
    """Handles on the real window and helpers that simulate the user."""

    def __init__(self, root, win, ctrl):
        self.root, self.win, self.ctrl = root, win, ctrl
        tab = win.tabs.get_tab("Viewer")._tab_instance
        self.top, self.right = tab.top, tab.right
        self.views = {"xz": self.right._xz, "xy": self.right._xy, "zy": self.right._zy}

    def pump(self, cond=lambda: True, limit=3.0) -> bool:
        """Run the Tk event loop until ``cond()`` holds or ``limit`` seconds passed."""
        end = time.monotonic() + limit
        while True:
            self.root.update()
            if cond():
                return True
            if time.monotonic() > end:
                return False
            time.sleep(0.01)

    def radio(self, text):
        found = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Radiobutton) and str(c.cget("text")) == text:
                    found.append(c)
                walk(c)

        walk(self.right)
        assert len(found) == 1, f"ROI button {text!r}: found {len(found)}"
        return found[0]

    def choose(self, text):
        self.radio(text).invoke()
        self.root.update()

    def xy_of(self, plane, row, col):
        """Canvas pixel at the centre of image pixel (row, col) of a view."""
        img_h, img_w, ox, oy, tw, th = self.views[plane]._render_state
        return (int(ox + (col + 0.5) * tw / img_w), int(oy + (img_h - 1 - row + 0.5) * th / img_h))

    def _gen(self, plane, seq, row, col, **kw):
        x, y = self.xy_of(plane, row, col)
        self.views[plane]._canvas.event_generate(seq, x=x, y=y, **kw)
        self.root.update()

    def click(self, plane, row, col):
        self._gen(plane, "<ButtonPress-1>", row, col)
        self._gen(plane, "<ButtonRelease-1>", row, col)

    def drag(self, plane, start, end):
        self._gen(plane, "<ButtonPress-1>", *start)
        steps = 4
        for i in range(1, steps + 1):
            r = start[0] + (end[0] - start[0]) * i / steps
            c = start[1] + (end[1] - start[1]) * i / steps
            self._gen(plane, "<B1-Motion>", int(round(r)), int(round(c)), state=0x100)
        self._gen(plane, "<ButtonRelease-1>", *end)

    def escape(self, plane="xy"):
        canvas = self.views[plane]._canvas
        self.root.focus_force()
        canvas.focus_force()
        self.root.update()
        canvas.event_generate("<Escape>")
        self.root.update()

    def idx(self):
        st = self.ctrl.state.viewer
        return (st.x_index, st.y_index, st.z_index)

    def answered(self):
        return self.ctrl.roi_timecourse() is not None


@pytest.fixture
def gui(monkeypatch, tmp_path):
    if not _has_display():
        pytest.skip("No display available for Tk")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI tests.")
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    stores = (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
              convert_worker._held_hook_keys, convert_worker._held_hook_data)
    for store in stores:
        store.clear()
    scan = _Scan()
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda s, r: 3)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda s, **kw: np.eye(4))
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    root.geometry("1280x900+0+0")
    ctrl = ViewerController()

    def submit(req):  # the worker answers at once, in this process
        out = _Queue()
        if isinstance(req, LoadVolumeRequest):
            convert_worker._process_load_volume(req, out)
            ctrl._on_volume_result(out.items[0])
        elif isinstance(req, TimecourseRequest):
            convert_worker._process_timecourse(req, out)
            ctrl._on_timecourse_result(out.items[0])

    ctrl._worker = SimpleNamespace(submit=submit, log_queue=None, check_results=lambda: None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 1
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: N
    win = MainWindow(root, ctrl)
    win.tabs.select_tab("Viewer")
    root.update()
    ctrl._request_viewer_volume()  # what selecting the first scan does
    g = Gui(root, win, ctrl)
    assert g.pump(lambda: all(v._render_state is not None for v in g.views.values()), 5.0)
    yield g
    try:
        root.destroy()
    except tk.TclError:
        pass
    for store in stores:
        store.clear()


def _expected(geometry, shape, axis, index):
    ras, _ = reorient_to_ras(PHANTOM, np.eye(4))
    plane = np.take(ras, index, axis=axis)  # (a, b, frames)
    mask = roi_mask(shape, plane.shape[:2], geometry)
    return [float(plane[mask][:, f].mean()) for f in range(N)], int(mask.sum())


def test_s2_launch_shows_axial_coronal_sagittal_views(gui):
    assert set(gui.views) == {"xz", "xy", "zy"}  # coronal, axial, sagittal
    for plane, vp in gui.views.items():
        assert vp.winfo_ismapped(), plane
        assert vp.get_image_shape() is not None, plane
    assert gui.views["xy"].get_image_shape() == (SHAPE[1], SHAPE[0])  # axial: rows y, cols x
    assert gui.views["xz"].get_image_shape() == (SHAPE[2], SHAPE[0])
    assert gui.views["zy"].get_image_shape() == (SHAPE[1], SHAPE[2])


def test_s3_roi_buttons_decide_whether_a_click_moves_the_crosshair(gui):
    assert gui.right._roi_tool_var.get() == "off"  # default
    start = gui.idx()
    row, col = (start[1] + 5) % SHAPE[1], (start[0] + 7) % SHAPE[0]
    gui.click("xy", row, col)
    assert gui.idx()[:2] == (col, row)  # Off: the crosshair moved
    for text, tool in (("Square", "square"), ("Circle", "circle")):
        gui.choose(text)
        before = gui.idx()
        assert gui.right._roi_tool_var.get() == tool  # the new choice replaced the old one
        assert gui.right._roi_drag.tool == tool
        gui.click("xy", (row + 3) % SHAPE[1], (col + 4) % SHAPE[0])
        assert gui.idx() == before, tool
    gui.choose("Off")
    assert gui.right._roi_drag.tool == "off"
    gui.click("xy", 2, 3)
    assert gui.idx()[:2] == (3, 2)


def test_s4_drag_sets_square_and_circle_and_esc_off_click_slice_frame(gui):
    ctrl = gui.ctrl
    gui.choose("Square")
    gui.drag("xy", (5, 4), (12, 14))
    assert gui.pump(gui.answered)
    roi = ctrl._roi
    assert roi["shape"] == "rect" and roi["axis"] == 2
    assert roi["geometry"] == (4.0, 14.0, 5.0, 12.0)  # u = x = col, v = y = row, inclusive
    assert ctrl.roi_timecourse()["n_mask"] == (14 - 4 + 1) * (12 - 5 + 1) == 88
    assert gui.views["xy"]._shape_data is not None  # drawn and kept after release

    gui.choose("Circle")  # the next drag replaces the square
    gui.drag("xy", (6, 6), (14, 14))
    assert gui.pump(lambda: ctrl._roi is not None and ctrl._roi["shape"] == "ellipse")
    assert gui.pump(gui.answered)
    ref = RoiDrag()
    ref.set_tool("circle")
    ref.press("xy", 6, 6)
    axis, _shape, geometry = ref.release("xy", 14, 14)
    assert (ctrl._roi["axis"], ctrl._roi["geometry"]) == (axis, tuple(geometry))
    _, n = _expected(geometry, "ellipse", 2, ctrl._roi["index"])
    assert ctrl.roi_timecourse()["n_mask"] == n > 0
    assert gui.views["xy"]._shape_data[0] == "ellipse"

    gui.escape()  # Esc with the pointer over a view
    assert ctrl._roi is None and gui.views["xy"]._shape_data is None

    gui.drag("xy", (5, 4), (12, 14))
    assert gui.pump(gui.answered)
    gui.choose("Off")  # Off clears too
    assert ctrl._roi is None and gui.views["xy"]._shape_data is None

    gui.choose("Square")
    gui.click("xy", 7, 7)  # a plain click sets nothing
    assert ctrl._roi is None and gui.views["xy"]._shape_data is None

    gui.drag("xy", (5, 4), (12, 14))
    assert gui.pump(gui.answered)
    z = ctrl.state.viewer.z_index
    gui.right._frame_scale.set(2)  # another frame: the ROI stays
    gui.pump(lambda: False, 0.6)  # the frame request is delayed, then answered
    assert ctrl.state.viewer.frame_index == 2
    assert ctrl._roi is not None and gui.pump(gui.answered)
    gui.views["xy"]._canvas.event_generate("<Button-4>", x=40, y=40)  # scroll to another slice
    gui.root.update()
    assert ctrl.state.viewer.z_index != z
    assert ctrl._roi is None and gui.views["xy"]._shape_data is None


def test_s5_timecourse_plot_shows_roi_mean_and_falls_back_after_clear(gui):
    ctrl = gui.ctrl
    gui.choose("Square")
    gui.drag("xy", (5, 4), (12, 14))
    assert gui.pump(gui.answered)
    assert str(gui.top._value_button.cget("state")) == "normal"
    gui.top._value_button.invoke()  # Value: opens the Timecourse window
    gui.root.update()
    plot = ctrl._timecourse_plot
    assert plot is not None and ctrl._timecourse_window.winfo_exists()
    assert gui.pump(lambda: plot._mode == "lines")
    exp, n = _expected((4.0, 14.0, 5.0, 12.0), "rect", 2, ctrl.state.viewer.z_index)
    assert "rect" in plot._meta.title and f"{n} voxels" in plot._meta.title
    assert list(plot._ys[0]) == pytest.approx(exp)
    assert np.diff(list(plot._ys[0])) == pytest.approx([1000.0] * (N - 1))

    gui.escape()
    assert ctrl._roi is None
    assert gui.pump(lambda: plot._mode == "lines" and "ROI" not in plot._meta.title)
    xi, yi, zi = gui.idx()
    ras, _ = reorient_to_ras(PHANTOM, np.eye(4))
    assert list(plot._ys[0]) == pytest.approx([float(v) for v in ras[xi, yi, zi, :]])


def test_s6_python_api_and_the_example_hook(gui, capsys):
    ctrl = gui.ctrl
    ctrl.set_roi("rect", (10, 20, 10, 20), axis=2)
    assert gui.pump(gui.answered)
    tc = ctrl.roi_timecourse()
    assert set(tc) == {"values", "n_mask", "n_per_frame", "shape", "axis", "index"}
    assert tc["n_mask"] == 121 and tc["shape"] == "rect" and tc["axis"] == 2
    assert len(tc["values"]) == N
    assert gui.views["xy"]._shape_data is not None  # drawn on the axial view (axis 2)
    ctrl.clear_roi()
    assert ctrl.roi_timecourse() is None

    # the example hook, code taken from the doc text
    text = DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.S)
    (code,) = [b for b in blocks if "class TryRoiHook" in b]
    ns: dict = {}
    exec(compile(code, "try_roi_hook.py", "exec"), ns)
    hook = ns["TryRoiHook"]()
    assert hook.name == "try-roi"
    host = ttk.Frame(gui.root)
    host.pack()
    frame = hook.build_tab(host, ctrl)
    frame.pack()
    buttons = {str(w.cget("text")): w for w in frame.winfo_children() if isinstance(w, ttk.Button)}
    assert list(buttons) == ["Set rect ROI", "Set ellipse ROI", "Print timecourse", "Clear ROI"]
    capsys.readouterr()

    buttons["Set rect ROI"].invoke()
    assert gui.pump(gui.answered)
    assert ctrl.roi_timecourse()["n_mask"] == 121 and ctrl._roi["axis"] == 2
    assert gui.views["xy"]._shape_data is not None
    assert "121" in capsys.readouterr().out  # printed by the hook's poll
    buttons["Print timecourse"].invoke()
    assert "'n_mask': 121" in capsys.readouterr().out
    buttons["Set ellipse ROI"].invoke()
    assert gui.pump(gui.answered)
    exp, n = _expected((15.0, 15.0, 5.0, 5.0), "ellipse", 2, ctrl.state.viewer.z_index)
    tc = ctrl.roi_timecourse()
    assert tc["shape"] == "ellipse" and tc["n_mask"] == n
    assert tc["values"] == pytest.approx(exp)
    buttons["Clear ROI"].invoke()
    gui.root.update()
    capsys.readouterr()
    buttons["Print timecourse"].invoke()
    assert capsys.readouterr().out.strip() == "None"
    assert ctrl.roi_timecourse() is None and gui.views["xy"]._shape_data is None
