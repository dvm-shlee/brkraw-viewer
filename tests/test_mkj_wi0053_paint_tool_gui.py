"""WI-0053: GUI test of the label paint tool (stage 3 WI-C) in a real Tk window.

Same set-up as tests/test_mkj_wi0020_checklist_gui.py (a real ``MainWindow``, a synthetic 4D
phantom loaded through the faked worker, mouse input by ``event_generate`` on the view canvases).
Runs only with a display and ``BRKRAW_VIEWER_SMOKE=1`` (use Xvfb, docs/dev/gui.md).

- the paint radios are enabled only while the selected layer is an editable label layer;
- press / motion / release changes the layer data and the rendered plane; Ctrl+Z reverts;
- Esc cancels a stroke in progress; Erase writes 0;
- ROI and paint are mutually exclusive, and a paint click does not move the crosshair;
- Save writes a .nii.gz (file dialog patched); removing a dirty layer asks (dialog patched);
- the Tk root is destroyed in teardown.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
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
N = 3
SHAPE = (32, 28, 6, N)
PHANTOM = np.random.default_rng(0).random(SHAPE).astype(np.float32) * 100.0


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
    def __init__(self, root, win, ctrl):
        self.root, self.win, self.ctrl = root, win, ctrl
        tab = win.tabs.get_tab("Viewer")._tab_instance
        self.right = tab.right
        self.paint = tab.right._paint
        self.views = {"xz": self.right._xz, "xy": self.right._xy, "zy": self.right._zy}

    def pump(self, cond=lambda: True, limit=3.0) -> bool:
        end = time.monotonic() + limit
        while True:
            self.root.update()
            if cond():
                return True
            if time.monotonic() > end:
                return False
            time.sleep(0.01)

    def button(self, text):
        found = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Button) and str(c.cget("text")) == text:
                    found.append(c)
                walk(c)

        walk(self.right)
        assert len(found) == 1, f"button {text!r}: found {len(found)}"
        return found[0]

    def mode(self, mode):
        self.paint._radios[mode].invoke()
        self.root.update()

    def radio_state(self, mode):
        return str(self.paint._radios[mode].cget("state"))

    def roi(self, text):
        found = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Radiobutton) and str(c.cget("text")) == text and c not in self.paint._radios.values():
                    found.append(c)
                walk(c)

        walk(self.right)
        assert len(found) == 1
        found[0].invoke()
        self.root.update()

    def xy_of(self, plane, row, col):
        img_h, img_w, ox, oy, tw, th = self.views[plane]._render_state
        return (int(ox + (col + 0.5) * tw / img_w), int(oy + (img_h - 1 - row + 0.5) * th / img_h))

    def gen(self, plane, seq, row, col, **kw):
        x, y = self.xy_of(plane, row, col)
        self.views[plane]._canvas.event_generate(seq, x=x, y=y, **kw)
        self.root.update()

    def press(self, row, col):
        self.gen("xy", "<ButtonPress-1>", row, col)

    def motion(self, row, col):
        self.gen("xy", "<B1-Motion>", row, col, state=0x100)

    def release(self, row, col):
        self.gen("xy", "<ButtonRelease-1>", row, col)

    def stroke(self, start, end):
        self.press(*start)
        for i in range(1, 5):
            self.motion(int(round(start[0] + (end[0] - start[0]) * i / 4)), int(round(start[1] + (end[1] - start[1]) * i / 4)))
        self.release(*end)

    def key(self, seq):
        canvas = self.views["xy"]._canvas
        self.root.focus_force()
        canvas.focus_force()
        self.root.update()
        canvas.event_generate(seq)
        self.root.update()

    def idx(self):
        st = self.ctrl.state.viewer
        return (st.x_index, st.y_index, st.z_index)

    def plane_alpha(self, layer_pos=0):
        """Alpha of the xy plane of a non-base layer as rendered by the controller, shape (y, x)."""
        ctrl = self.ctrl
        planes = ctrl._layer_planes(ctrl._display_grid(), self.idx(), ctrl.state.viewer.frame_index)
        return planes["xy"][layer_pos][1]


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
    from brkraw_viewer.ui import assets as _assets

    _assets._load_icon_cached.cache_clear()
    root = tk.Tk()
    try:
        root.geometry("1280x900+0+0")
        ctrl = ViewerController()

        def submit(req):
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
        ctrl._request_viewer_volume()
        g = Gui(root, win, ctrl)
        assert g.pump(lambda: all(v._render_state is not None for v in g.views.values()), 5.0)
        yield g
    finally:
        _destroy_root(root)
    for store in stores:
        store.clear()


def _new_layer(gui):
    gui.button("New label layer").invoke()
    gui.root.update()
    lid = gui.ctrl._selected_layer_id
    assert lid is not None
    return lid, gui.ctrl._layer_data[lid]


def test_paint_radios_enabled_only_for_an_editable_label_layer(gui):
    ctrl = gui.ctrl
    grid = ctrl._display_grid()
    assert gui.radio_state("paint") == gui.radio_state("erase") == "disabled"  # no layer selected
    img = ctrl._add_array_layer(np.ones(grid.shape, np.float32), grid.affine, name="img")
    lab = ctrl._add_array_layer(np.zeros(grid.shape, np.uint8), grid.affine, name="lab", kind="label")
    for lid in (img, lab):  # an image layer and a read-only label layer
        ctrl.select_layer(lid)
        gui.root.update()
        assert gui.radio_state("paint") == gui.radio_state("erase") == "disabled", lid
    new_id, _ = _new_layer(gui)  # editable label layer: selected by the button
    assert gui.radio_state("paint") == gui.radio_state("erase") == "normal"
    assert str(gui.button("Save label...").cget("state")) == "normal"
    gui.mode("paint")
    assert gui.paint.active
    ctrl.select_layer(img)  # leaving the editable layer turns the tool off
    gui.root.update()
    assert gui.paint.mode == "off" and gui.radio_state("paint") == "disabled"
    ctrl.select_layer(new_id)
    assert gui.radio_state("paint") == "normal"


def test_stroke_changes_data_and_plane_and_ctrl_z_reverts(gui):
    ctrl = gui.ctrl
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    z = gui.idx()[2]
    crosshair = gui.idx()
    assert not data.any() and not gui.plane_alpha().any()

    gui.stroke((5, 4), (12, 14))  # rows = y, cols = x of the axial view
    assert gui.idx() == crosshair  # the click did not move the crosshair
    assert data[4, 5, z] == 1 and data[14, 12, z] == 1  # both ends, data[x, y, z]
    painted = int((data != 0).sum())
    assert painted >= 11  # a gap-free line of brush size 1
    assert set(np.unique(data)) == {0, 1}
    assert np.flatnonzero(data[:, :, z].T.ravel()).size == painted  # only the shown slice
    alpha = gui.plane_alpha()
    assert alpha.shape == (SHAPE[1], SHAPE[0])
    assert int((alpha > 0).sum()) == painted  # the rendered plane shows exactly the painted voxels
    assert lid in ctrl._layer_dirty
    assert gui.paint._undo.instate(["!disabled"])

    gui.key("<Control-z>")
    assert not data.any() and not gui.plane_alpha().any()
    gui.key("<Control-z>")  # nothing left to undo: no error
    assert not data.any()


def test_erase_and_escape_cancel(gui):
    ctrl = gui.ctrl
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    z = gui.idx()[2]
    gui.stroke((5, 4), (5, 14))
    assert data[4:15, 5, z].tolist() == [1] * 11
    gui.mode("erase")
    gui.stroke((5, 8), (5, 10))
    assert data[4:15, 5, z].tolist() == [1] * 4 + [0] * 3 + [1] * 4
    gui.key("<Control-z>")  # the erase stroke is one undo step
    assert data[4:15, 5, z].tolist() == [1] * 11

    gui.mode("paint")  # Esc drops a stroke in progress
    gui.press(10, 10)
    gui.motion(12, 12)
    assert data[10, 10, z] == 1 and data[12, 12, z] == 1
    gui.key("<Escape>")
    assert data[10, 10, z] == 0 and data[12, 12, z] == 0
    gui.release(12, 12)  # the release after the cancel is harmless
    assert data[4:15, 5, z].tolist() == [1] * 11
    gui.key("<Control-z>")
    assert not data.any()


def test_roi_and_paint_are_exclusive(gui):
    ctrl = gui.ctrl
    _new_layer(gui)
    gui.mode("paint")
    assert gui.paint.mode == "paint" and gui.right._roi_tool_var.get() == "off"
    gui.roi("Square")
    assert gui.right._roi_tool_var.get() == "square" and gui.paint.mode == "off"
    assert gui.right._roi_drag.tool == "square"
    gui.mode("erase")  # choosing a paint tool switches the ROI tool off
    assert gui.paint.mode == "erase" and gui.right._roi_tool_var.get() == "off"
    assert gui.right._roi_drag.tool == "off"
    data = ctrl._layer_data[ctrl._selected_layer_id]
    gui.mode("paint")
    gui.stroke((5, 4), (12, 14))  # a paint drag sets no ROI
    assert ctrl._roi is None and data.any()
    gui.mode("off")
    before = gui.idx()
    gui.press(9, 9)  # Off: a click moves the crosshair again
    gui.release(9, 9)
    assert gui.idx() != before and gui.idx()[:2] == (9, 9)
    assert int(data.sum()) > 0  # and paints nothing


def test_save_writes_nii_gz_and_clears_dirty(gui, monkeypatch, tmp_path):
    import nibabel as nib

    ctrl = gui.ctrl
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(2)
    gui.mode("paint")
    gui.stroke((5, 4), (12, 14))
    assert lid in ctrl._layer_dirty
    target = tmp_path / "painted"  # no suffix: the tool adds .nii.gz
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(target))
    gui.button("Save label...").invoke()
    out = tmp_path / "painted.nii.gz"
    assert out.is_file()
    img = nib.load(str(out))
    assert np.array_equal(np.asarray(img.dataobj), data)
    assert np.allclose(img.affine, ctrl._layers.get(lid).affine)
    assert img.get_data_dtype() == np.uint8
    assert lid not in ctrl._layer_dirty
    assert ctrl._layers.get(lid).editable  # still editable after saving

    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: "")  # cancelled dialog
    other = tmp_path / "cancelled.nii.gz"
    gui.button("Save label...").invoke()
    assert not other.exists()


def test_removing_a_dirty_layer_asks(gui, monkeypatch):
    ctrl = gui.ctrl
    lid, data = _new_layer(gui)
    asked = []
    answers = [False, True]

    def fake_ask(title, message, **kw):
        asked.append((title, message))
        return answers.pop(0)

    monkeypatch.setattr(messagebox, "askyesno", fake_ask)
    clean = ctrl._add_array_layer(np.zeros(data.shape, np.uint8), ctrl._display_grid().affine, name="clean", kind="label")
    assert ctrl._remove_layer(clean) is True and not asked  # a clean layer goes without asking

    gui.paint.brush_var.set(1)
    gui.mode("paint")
    gui.stroke((5, 4), (12, 14))
    assert lid in ctrl._layer_dirty
    assert ctrl._remove_layer(lid) is False  # answer: no
    assert len(asked) == 1 and "unsaved" in asked[0][1]
    assert lid in ctrl._layers.ids() and lid in ctrl._layer_data and data.any()
    assert ctrl._remove_layer(lid) is True  # answer: yes
    assert len(asked) == 2
    assert lid not in ctrl._layers.ids() and lid not in ctrl._layer_data
    assert lid not in ctrl._layer_dirty and lid not in ctrl._layer_editors
    gui.root.update()
    assert gui.paint.mode == "off" and gui.radio_state("paint") == "disabled"


def test_paint_on_a_layer_with_another_grid_orientation(gui):
    """The display pixel maps to the layer voxel through the inverse of the matrix given to sample_slice."""
    ctrl = gui.ctrl
    grid = ctrl._display_grid()
    shape = (grid.shape[1], grid.shape[0], grid.shape[2])  # x and y swapped, x flipped
    # layer index l = P d = (y, nx-1-x, z); the layer affine is A_D @ inv(P), so M = inv(A_L) @ A_D = P
    p = np.array([[0, 1, 0, 0], [-1, 0, 0, grid.shape[0] - 1], [0, 0, 1, 0], [0, 0, 0, 1]], float)
    layer_aff = np.array(grid.affine, dtype=float) @ np.linalg.inv(p)
    lid = ctrl._add_array_layer(np.zeros(shape, np.uint8), layer_aff, name="rot", kind="label", editable=True)
    ctrl.select_layer(lid)
    gui.root.update()
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    z = gui.idx()[2]
    gui.press(5, 4)  # display y=5, x=4
    gui.release(5, 4)
    data = ctrl._layer_data[lid]
    assert data[5, grid.shape[0] - 1 - 4, z] == 1 and int(data.sum()) == 1
    assert int((gui.plane_alpha(layer_pos=0) > 0).sum()) == 1  # drawn back on the same display pixel
    assert gui.plane_alpha(layer_pos=0)[5, 4] > 0


def test_drag_keeps_painting_when_the_mapped_slice_changes(gui):
    """Mapping (x,y,z)->(x,y,z+x): dabs follow the point onto each slice it maps to."""
    ctrl = gui.ctrl
    grid = ctrl._display_grid()
    nx, ny, nz = grid.shape
    p = np.eye(4)
    p[2, 0] = 1.0
    layer_aff = np.array(grid.affine, dtype=float) @ np.linalg.inv(p)
    lid = ctrl._add_array_layer(np.zeros((nx, ny, nz + nx), np.uint8), layer_aff, name="obl", kind="label", editable=True)
    ctrl.select_layer(lid)
    gui.root.update()
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    z = gui.idx()[2]
    gui.press(3, 1)
    gui.motion(3, 3)
    gui.motion(3, 5)
    gui.release(3, 5)
    data = ctrl._layer_data[lid]
    assert data[1, 3, z + 1] == 1 and data[3, 3, z + 3] == 1 and data[5, 3, z + 5] == 1


def test_scaled_grid_paints_the_displayed_voxel(gui):
    """Half-voxel mapped coordinate 0.5 rounds to voxel 1, as the renderer does."""
    ctrl = gui.ctrl
    grid = ctrl._display_grid()
    nx, ny, nz = grid.shape
    p = np.diag([0.5, 1.0, 1.0, 1.0])  # layer index l = d / 2 (coarser layer)
    layer_aff = np.array(grid.affine, dtype=float) @ np.linalg.inv(p)
    lid = ctrl._add_array_layer(np.zeros((nx, ny, nz), np.uint8), layer_aff, name="sc", kind="label", editable=True)
    ctrl.select_layer(lid)
    gui.root.update()
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    z = gui.idx()[2]
    gui.press(2, 1)  # display x=1 -> layer coordinate 0.5 -> voxel 1
    gui.release(2, 1)
    data = ctrl._layer_data[lid]
    assert data[1, 2, z] == 1 and data[0, 2, z] == 0 and int(data.sum()) == 1
