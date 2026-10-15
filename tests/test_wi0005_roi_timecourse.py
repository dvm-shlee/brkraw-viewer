"""WI-0005: temporary ROI state and ROI timecourse in the controller (no Tk window).

Controller and worker are wired in one process; the scan is a synthetic 4D phantom whose ROI mean
per frame is known. ``set_roi`` / ``clear_roi`` / ``roi_timecourse`` are the provisional API.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, TimecourseRequest
from brkraw_viewer.core.roi import roi_mask
from brkraw_viewer.utils.orientation import reorient_to_ras

GB = 1024 * 1024 * 1024
N = 6
SHAPE = (10, 8, 4, N)
# value = 1000 * frame + position code, so every frame has a different, known mean
_pos = np.arange(10 * 8 * 4, dtype=np.float32).reshape(10, 8, 4)
PHANTOM = np.stack([_pos + 1000.0 * f for f in range(N)], axis=-1)


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


class _Plot:
    def __init__(self):
        self.lines = None
        self.meta = None
        self.message = None

    def set_lines(self, x, ys, meta=None, y_fmt=None):
        self.lines = (list(x), [list(y) for y in ys])
        self.meta = meta
        self.message = None

    def set_message(self, text):
        self.message = text

    def set_vline(self, value):
        pass


class _View:
    def __getattr__(self, name):
        return lambda *a, **k: None

    def after(self, ms, func):
        func()


@pytest.fixture
def env(monkeypatch, tmp_path):
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
    ctrl = ViewerController()
    ctrl.submitted = []
    ctrl.deferred = False
    ctrl.waiting = []

    def answer(req):
        out = _Queue()
        convert_worker._process_timecourse(req, out)
        return out.items[0]

    ctrl.answer = answer

    def submit(req):
        ctrl.submitted.append(req)
        out = _Queue()
        if isinstance(req, LoadVolumeRequest):
            convert_worker._process_load_volume(req, out)
            ctrl._on_volume_result(out.items[0])
        elif isinstance(req, TimecourseRequest):
            if ctrl.deferred and req.roi_mask is not None:
                ctrl.waiting.append(req)
            else:
                ctrl._on_timecourse_result(answer(req))

    ctrl._worker = SimpleNamespace(submit=submit, log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 1
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: N
    ctrl._view = _View()
    ctrl._timecourse_plot = _Plot()
    ctrl._timecourse_window = SimpleNamespace(winfo_exists=lambda: True)
    ctrl._request_viewer_volume()
    yield ctrl
    for store in stores:
        store.clear()


def _expected(shape, geometry, axis, index):
    ras, _ = reorient_to_ras(PHANTOM, np.eye(4))
    plane = np.take(ras, index, axis=axis)  # (a, b, frames)
    mask = roi_mask(shape, plane.shape[:2], geometry)
    return [float(plane[mask][:, f].mean()) for f in range(N)], int(mask.sum())


def test_rect_roi_mean_per_frame_is_the_known_mean(env):
    z = env.state.viewer.z_index
    env.set_roi("rect", (2, 5, 1, 3), axis=2)
    tc = env.roi_timecourse()
    exp, n = _expected("rect", (2, 5, 1, 3), 2, z)
    assert n == 12 and tc["n_mask"] == 12
    assert tc["values"] == pytest.approx(exp)
    assert tc["n_per_frame"] == [12] * N
    assert tc["shape"] == "rect" and tc["axis"] == 2 and tc["index"] == z
    # frames differ by exactly 1000, so the series is a straight line of known slope
    assert np.diff(tc["values"]) == pytest.approx([1000.0] * (N - 1))


def test_ellipse_roi_and_other_axis(env):
    env.set_roi("ellipse", (4.0, 3.0, 2.5, 2.0), axis=0, index=4)
    tc = env.roi_timecourse()
    exp, n = _expected("ellipse", (4.0, 3.0, 2.5, 2.0), 0, 4)
    assert tc["n_mask"] == n and tc["values"] == pytest.approx(exp)
    assert env.state.viewer.x_index == 4


def test_roi_is_plotted_with_shape_and_voxel_count(env):
    env.set_roi("rect", (0, 1, 0, 1))
    plot = env._timecourse_plot
    assert plot.lines is not None and len(plot.lines[0]) == N
    assert "rect" in plot.meta.title and "4 voxels" in plot.meta.title


def test_roi_request_carries_the_mask(env):
    env.set_roi("rect", (0, 2, 0, 1))
    req = [r for r in env.submitted if isinstance(r, TimecourseRequest) and r.roi_mask is not None][-1]
    assert req.roi_axis == 2 and req.roi_index == env.state.viewer.z_index
    assert np.asarray(req.roi_mask).sum() == 6


def test_stale_answer_is_dropped(env):
    env.deferred = True
    env.set_roi("rect", (0, 1, 0, 1))
    env.set_roi("rect", (0, 3, 0, 3))  # replaces the first before it was answered
    first, second = env.waiting
    env._on_timecourse_result(env.answer(first))  # late answer of the replaced ROI
    assert env.roi_timecourse() is None
    env._on_timecourse_result(env.answer(second))
    tc = env.roi_timecourse()
    assert tc["n_mask"] == 16
    env._on_timecourse_result(env.answer(first))  # and a repeat of the old one changes nothing
    assert env.roi_timecourse()["n_mask"] == 16


def test_answer_after_clear_is_dropped(env):
    env.deferred = True
    env.set_roi("rect", (0, 1, 0, 1))
    (req,) = env.waiting
    env.clear_roi()
    env._on_timecourse_result(env.answer(req))
    assert env.roi_timecourse() is None
    assert env._roi_series is None


def test_clear_roi_returns_to_the_voxel_timecourse(env):
    env.set_roi("rect", (0, 1, 0, 1))
    env.clear_roi()
    assert env.roi_timecourse() is None
    assert "ROI" not in (env._timecourse_plot.meta.title if env._timecourse_plot.meta else "")


def test_scan_change_clears_the_roi(env):
    env.set_roi("rect", (0, 1, 0, 1))
    env._clear_timecourse()  # what selecting a scan or reco, or opening or closing a dataset, calls
    assert env._roi is None and env.roi_timecourse() is None


def test_reco_selection_clears_the_roi(env, monkeypatch):
    env.set_roi("rect", (0, 1, 0, 1))
    env.state.dataset.selected_reco_id = 2  # the key no longer matches the answer
    assert env.roi_timecourse() is None


def test_hook_options_slicepack_and_flip_clear_the_roi(env):
    env.set_roi("rect", (0, 1, 0, 1))
    env.on_viewer_hook_args_change({"a": 1})
    assert env._roi is None
    env.set_roi("rect", (0, 1, 0, 1))
    env.on_viewer_slicepack_change(0)
    assert env._roi is None
    env.set_roi("rect", (0, 1, 0, 1))
    env.on_viewer_flip_change("x", True)
    assert env._roi is None


def test_slice_change_clears_the_roi(env):
    env.set_roi("rect", (0, 1, 0, 1), axis=2, index=1)
    env.on_viewer_jump(env.state.viewer.x_index, env.state.viewer.y_index, 2)
    assert env._roi is None and env.roi_timecourse() is None
    env.set_roi("rect", (0, 1, 0, 1), axis=2, index=1)
    env.on_viewer_jump(3, 3, 1)  # same slice on the ROI axis: kept
    assert env._roi is not None and env.roi_timecourse() is not None


def test_bad_input_is_refused_and_keeps_the_old_roi(env):
    env.set_roi("rect", (0, 1, 0, 1))
    with pytest.raises(ValueError):
        env.set_roi("triangle", (0, 1, 0, 1))
    with pytest.raises(ValueError):
        env.set_roi("rect", (0, 1, 0, 1), axis=3)
    with pytest.raises(ValueError):
        env.set_roi("rect", (0, 1, 0, 1), axis=2, index=99)
    assert env.roi_timecourse()["n_mask"] == 4


def test_set_roi_without_an_image_raises(env):
    env._viewer_volume = None
    with pytest.raises(ValueError):
        env.set_roi("rect", (0, 1, 0, 1))


def test_voxel_timecourse_still_works_without_a_roi(env):
    xi, yi, zi = (env.state.viewer.x_index, env.state.viewer.y_index, env.state.viewer.z_index)
    ras, _ = reorient_to_ras(PHANTOM, np.eye(4))
    assert env._timecourse_plot.lines[1][0] == pytest.approx([float(v) for v in ras[xi, yi, zi, :]])
