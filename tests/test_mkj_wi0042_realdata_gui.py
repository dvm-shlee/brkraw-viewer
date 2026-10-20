"""WI-0042: GUI test of docs/user/try-new-features.md sections 3-5 on a real Bruker dataset.

Dataset: BrkRaw/brkraw-dataset PV5.1 BOLD-EPI (in vivo rat, ParaVision 5.1), scan 11 is the EPI time
series. The study folder comes from ``BRKRAW_VIEWER_REALDATA`` (set by the check); nothing is faked
but the worker process: ``MainWindow(root, ViewerController())`` runs in a real Tk window and the
real worker functions answer in this process. The repetition count is read from the scan's own
``method`` (``PVM_NRepetitions``) or ``acqp`` (``NR``), never hard-coded.

- s3: open the dataset, select scan 11; the ROI tool switches Off / Square / Circle.
- s4: a drag draws a square and a circle ROI; the mask is non-empty and inside the image.
- s5: the timecourse plot of each ROI has one finite, not-all-equal value per repetition.

No skips: a missing variable, dataset or display is a failure.
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
from brkraw_viewer.ui.main import MainWindow

GB = 1024 * 1024 * 1024
SCAN = 11
LOAD_LIMIT = 120.0


def _dataset_path() -> Path:
    raw = os.environ.get("BRKRAW_VIEWER_REALDATA", "").strip()
    if not raw:
        pytest.fail("BRKRAW_VIEWER_REALDATA is not set: it must name the unpacked PV5.1 BOLD-EPI study folder.")
    path = Path(raw)
    if not path.exists():
        pytest.fail(f"BRKRAW_VIEWER_REALDATA points to a missing path: {path}")
    return path


def _read_param(file: Path, names: tuple[str, ...]):
    """First integer of ``##$NAME=`` (``( n )`` array headers are skipped) in a JCAMP file."""
    if not file.is_file():
        return None
    text = file.read_text(encoding="latin-1", errors="replace")
    for name in names:
        m = re.search(r"^##[$]" + re.escape(name) + r"=\s*(?:\([^)]*\)\s*\n)?\s*(-?\d+)", text, flags=re.M)
        if m:
            return int(m.group(1))
    return None


def _repetitions(study: Path) -> int:
    scan_dir = study / str(SCAN)
    n = _read_param(scan_dir / "method", ("PVM_NRepetitions",))
    if n is None:
        n = _read_param(scan_dir / "acqp", ("NR",))
    assert n is not None, f"no PVM_NRepetitions / NR in {scan_dir}"
    return n


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class Gui:
    def __init__(self, root, win, ctrl):
        self.root, self.win, self.ctrl = root, win, ctrl
        tab = win.tabs.get_tab("Viewer")._tab_instance
        self.top, self.right = tab.top, tab.right
        self.views = {"xz": self.right._xz, "xy": self.right._xy, "zy": self.right._zy}

    def pump(self, cond=lambda: True, limit=LOAD_LIMIT) -> bool:
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
        img_h, img_w, ox, oy, tw, th = self.views[plane]._render_state
        return (int(ox + (col + 0.5) * tw / img_w), int(oy + (img_h - 1 - row + 0.5) * th / img_h))

    def _gen(self, plane, seq, row, col, **kw):
        x, y = self.xy_of(plane, row, col)
        self.views[plane]._canvas.event_generate(seq, x=x, y=y, **kw)
        self.root.update()

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

    def answered(self):
        return self.ctrl.roi_timecourse() is not None

    def drag_box(self):
        """Start and end pixel (row, col) of a drag around the centre of the axial image."""
        img_h, img_w = self.views["xy"]._render_state[:2]
        r0, r1 = int(img_h * 0.35), int(img_h * 0.65)
        c0, c1 = int(img_w * 0.35), int(img_w * 0.65)
        return (r0, c0), (r1, c1)


def _destroy_root(root):
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
def real(monkeypatch, tmp_path):
    study = _dataset_path()
    nrep = _repetitions(study)
    if not (sys.platform.startswith("win") or sys.platform == "darwin"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            pytest.fail("No display available for Tk (run through scratch/checks/gui-test.sh).")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.fail("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI tests.")
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    stores = (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
              convert_worker._held_hook_keys, convert_worker._held_hook_data, convert_worker._loader_cache)
    for store in stores:
        store.clear()
    from brkraw_viewer.ui import assets as _assets

    _assets._load_icon_cached.cache_clear()
    root = tk.Tk()
    try:
        root.geometry("1280x900+0+0")
        ctrl = ViewerController()

        def submit(req):  # the real worker functions answer at once, in this process
            out = _Queue()
            if isinstance(req, LoadVolumeRequest):
                convert_worker._process_load_volume(req, out)
                ctrl._on_volume_result(out.items[0])
            elif isinstance(req, TimecourseRequest):
                convert_worker._process_timecourse(req, out)
                ctrl._on_timecourse_result(out.items[0])

        ctrl._worker = SimpleNamespace(submit=submit, log_queue=None, check_results=lambda: None)
        win = MainWindow(root, ctrl)
        win.tabs.select_tab("Viewer")
        root.update()
        g = Gui(root, win, ctrl)
        g.study, g.nrep = study, nrep
        yield g
    finally:
        _destroy_root(root)
    for store in stores:
        store.clear()


def _open_scan(g):
    g.ctrl.action_open_dataset(g.study)
    ids = [e[0] for e in g.ctrl.dataset.scan_entries()]
    assert SCAN in ids, f"scan {SCAN} not in the dataset: {ids}"
    g.ctrl.action_select_scan(SCAN)
    assert g.ctrl.state.dataset.selected_scan_id == SCAN
    assert g.pump(lambda: all(v._render_state is not None for v in g.views.values()))
    assert g.ctrl._viewer_volume is not None, "scan 11 did not load"


def test_s3_open_dataset_select_scan_11_and_switch_roi_tool(real):
    g = real
    assert g.nrep > 1, f"scan {SCAN} repetitions read from the dataset: {g.nrep}"
    _open_scan(g)
    for text in ("Off", "Square", "Circle"):
        g.choose(text)
        assert g.radio(text).instate(["selected"]), f"ROI tool {text!r} not selected"
    g.choose("Off")


def _check_roi_and_plot(g, tool, shape):
    ctrl = g.ctrl
    assert g.nrep > 1, f"repetitions read from the dataset: {g.nrep}"
    g.choose(tool)
    g.drag("xy", *g.drag_box())  # s4: drag on the axial image
    assert g.pump(g.answered), f"{tool}: no ROI timecourse answer"
    roi = ctrl._roi
    assert roi is not None and roi["shape"] == shape and roi["axis"] == 2
    mask = np.asarray(roi["mask"])
    plane = tuple(int(n) for n in np.shape(ctrl._viewer_volume)[:2])
    assert mask.shape == plane, f"mask {mask.shape} is not the image plane {plane}"
    assert int(mask.sum()) > 0, f"{tool}: empty ROI mask"
    assert g.views["xy"]._shape_data is not None  # drawn on the image

    tc = ctrl.roi_timecourse()  # s5: one value per repetition
    assert tc["n_mask"] == int(mask.sum())
    vals = np.asarray(tc["values"], dtype=float)
    assert len(vals) == g.nrep, f"{tool}: {len(vals)} values for {g.nrep} repetitions"
    assert np.all(np.isfinite(vals)), f"{tool}: non-finite values"
    assert not np.all(vals == vals[0]), f"{tool}: all values equal"

    assert str(g.top._value_button.cget("state")) == "normal"
    g.top._value_button.invoke()
    g.root.update()
    plot = ctrl._timecourse_plot
    assert plot is not None and ctrl._timecourse_window.winfo_exists()
    assert g.pump(lambda: plot._mode == "lines", 30.0)
    ys = np.asarray(list(plot._ys[0]), dtype=float)
    assert len(ys) == g.nrep and np.all(np.isfinite(ys)) and not np.all(ys == ys[0])
    assert ys == pytest.approx(vals)
    g.escape()
    assert ctrl._roi is None


def test_s4_s5_square_roi_drag_and_timecourse_plot(real):
    _open_scan(real)
    _check_roi_and_plot(real, "Square", "rect")


def test_s4_s5_circle_roi_drag_and_timecourse_plot(real):
    _open_scan(real)
    _check_roi_and_plot(real, "Circle", "ellipse")
