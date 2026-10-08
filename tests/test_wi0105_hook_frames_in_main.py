"""WI-0105 (D-0145, contract C9): with a converter hook on, main holds the frame it shows, not every
frame of the hook's result, and what is shown is the same as before.

Controller and worker are wired in one process (the worker functions run on submit); the scan is a
synthetic stub whose hook returns all frames. No Tk window.
"""

from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, TimecourseRequest
from brkraw_viewer.utils.orientation import reorient_to_ras

GB = 1024 * 1024 * 1024
N = 8
SHAPE = (64, 64, 32, N)  # 4 MB; one frame 0.5 MB, well over the Python overhead of a test
FULL = (np.arange(int(np.prod(SHAPE)), dtype=np.float32) % 251).reshape(SHAPE) + 1.0


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    image_info = {1: {"num_cycles": N, "dataobj": None}}

    def __init__(self):
        self.avail = {1: SimpleNamespace(file_visu_pars={})}
        self.calls = []
        self.data = FULL.copy()

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append({"axis": axis, "frames": frames, **kwargs})
        if frames is None:
            return self.data.copy()
        start, stop = frames.split(":")
        return self.data[..., int(start) : int(stop or N)].copy()


class _Plot:
    def __init__(self):
        self.lines = None
        self.message = None

    def set_lines(self, x, ys, meta=None, y_fmt=None):
        self.lines = (list(x), [list(y) for y in ys])

    def set_message(self, text):
        self.message = text

    def set_vline(self, value):
        pass


class _View:
    def __init__(self):
        self.views = []
        self.status = []

    def set_viewer_views(self, views, **kwargs):
        self.views.append({k: np.array(v) for k, v in views.items()})

    def set_status(self, text):
        self.status.append(text)

    def after(self, ms, func):
        func()
        return None

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def env(monkeypatch, tmp_path):
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    for store in (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
                  convert_worker._held_hook_keys, convert_worker._held_hook_data):
        store.clear()
    scan = _Scan()
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda s, r: 3)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda s, **kw: np.eye(4))
    ctrl = ViewerController()
    ctrl.submitted = []

    def submit(req):
        ctrl.submitted.append(req)
        out = _Queue()
        if isinstance(req, LoadVolumeRequest):
            convert_worker._process_load_volume(req, out)
            ctrl._on_volume_result(out.items[0])
        elif isinstance(req, TimecourseRequest):
            convert_worker._process_timecourse(req, out)
            ctrl._on_timecourse_result(out.items[0])

    ctrl._worker = SimpleNamespace(submit=submit, log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 1
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: N
    ctrl._view = _View()
    ctrl.scan = scan
    yield ctrl
    for store in (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
                  convert_worker._held_hook_keys, convert_worker._held_hook_data):
        store.clear()


def _hook_on(ctrl, args=None):
    ctrl._viewer_hook_name = "sordino"
    ctrl._viewer_hook_enabled = True
    ctrl._viewer_hook_args = args if args is not None else {"cache_dir": "x"}


def _plot(ctrl):
    ctrl._timecourse_plot = _Plot()
    ctrl._timecourse_window = SimpleNamespace(winfo_exists=lambda: True)
    return ctrl._timecourse_plot


def _loads(ctrl):
    return [r for r in ctrl.submitted if isinstance(r, LoadVolumeRequest)]


def _expected_views(frame, indices):
    ras, _ = reorient_to_ras(FULL, np.eye(4))
    xi, yi, zi = indices
    data = ras[..., frame]
    return {"xy": data[:, :, zi].T, "xz": data[:, yi, :].T, "zy": data[xi, :, :]}


# ---- requests ----------------------------------------------------------------------------------


def test_hook_request_asks_for_the_shown_frame_only(env):
    _hook_on(env)
    env.state.viewer.frame_index = 3
    env._request_viewer_volume()
    req = _loads(env)[-1]
    assert (req.frame_start, req.frame_count) == (3, 1)
    assert req.hook_name == "sordino" and req.hook_args == {"cache_dir": "x"}


def test_without_a_hook_the_request_is_as_before(env):
    env.state.viewer.frame_index = 2
    env._request_viewer_volume()
    req = _loads(env)[-1]
    assert (req.frame_start, req.frame_count, req.hook_name) == (2, 1, None)


# ---- main holds one frame, the picture is the same --------------------------------------------


def test_main_holds_one_frame_and_the_worker_holds_the_result(env):
    _hook_on(env)
    env._request_viewer_volume()
    assert np.shape(env._viewer_raw_volume) == SHAPE[:3] + (1,)
    assert env._viewer_frames == N
    assert env._viewer_raw_volume.nbytes * N == FULL.nbytes
    key = (str(env.state.dataset.path), 1, 1)
    assert convert_worker._held_recos[key] >= FULL.nbytes
    assert len(env.scan.calls) == 1 and env.scan.calls[0]["frames"] is None


def test_every_frame_shows_what_the_whole_result_showed_before(env):
    _hook_on(env)
    env._request_viewer_volume()
    indices = (env.state.viewer.x_index, env.state.viewer.y_index, env.state.viewer.z_index)
    for frame in (0, 5, 2, 7, 1):
        env.on_viewer_frame_change(frame)
        shown = env._view.views[-1]
        expected = _expected_views(frame, indices)
        for name in ("xy", "xz", "zy"):
            assert np.array_equal(shown[name], expected[name]), (frame, name)
    assert len(env.scan.calls) == 1  # the hook ran once; the slider only asked the worker


def test_a_frame_seen_before_is_shown_from_main_without_a_request(env):
    _hook_on(env)
    env._request_viewer_volume()
    env.on_viewer_frame_change(4)
    env.on_viewer_frame_change(5)
    count = len(_loads(env))
    env.on_viewer_frame_change(4)
    assert len(_loads(env)) == count
    assert env._viewer_raw_volume.shape[3] == 1


def _unique_held(ctrl):
    """Bytes of the distinct frame arrays main holds: the shown one and the recent-frame cache."""
    arrays = {id(e["raw"]): e["raw"] for e in ctrl._frame_cache.values()}
    arrays[id(ctrl._viewer_raw_volume)] = ctrl._viewer_raw_volume
    return sum(int(a.nbytes) for a in arrays.values())


def test_main_keeps_far_less_than_the_whole_result_while_the_slider_moves(env):
    one = FULL.nbytes // N
    env._frame_cache_bytes_limit = 2 * one  # the recent-frame bound (64 MB in the product) scaled to the test
    _hook_on(env)
    env._request_viewer_volume()
    for frame in list(range(N)) + [3, 0, 6]:
        env.on_viewer_frame_change(frame)
        assert _unique_held(env) <= 3 * one, frame  # the shown frame plus at most the recent bound
    assert _unique_held(env) < FULL.nbytes


def test_a_frame_past_the_result_is_clamped_and_cached_under_the_shown_frame(env):
    _hook_on(env)
    env.state.viewer.frame_index = 40
    env._request_viewer_volume()
    assert env.state.viewer.frame_index == N - 1
    assert list(env._frame_cache) == [N - 1]


def test_hook_main_peak_is_one_frame_not_the_result(env):
    _hook_on(env)
    env._request_viewer_volume()  # the worker holds the result; main has frame 0
    env.on_viewer_frame_change(6)
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        env.on_viewer_frame_change(3)
        peak = tracemalloc.get_traced_memory()[1] - before
    finally:
        tracemalloc.stop()
    assert peak < FULL.nbytes, (peak, FULL.nbytes)


# ---- changes of the hook state ----------------------------------------------------------------


def _shown_xy(ctrl):
    return ctrl._view.views[-1]["xy"]


def _xy_of(ctrl, frame, offset=0.0):
    indices = (ctrl.state.viewer.x_index, ctrl.state.viewer.y_index, ctrl.state.viewer.z_index)
    return _expected_views(frame, indices)["xy"] + offset


def test_new_hook_options_do_not_show_a_frame_of_the_old_result(env):
    _hook_on(env)
    env._request_viewer_volume()
    env.on_viewer_frame_change(2)
    env.on_viewer_frame_change(5)  # frames 2 and 5 are now cached from the old result
    env.scan.data = FULL + 1000.0
    env.on_hook_options_apply("sordino", {"cache_dir": "y"})
    assert env._viewer_hook_args == {"cache_dir": "y"}
    assert np.array_equal(_shown_xy(env), _xy_of(env, 5, 1000.0))  # the shown frame is reloaded
    env.on_viewer_frame_change(2)  # a frame cached before must not come back from main
    assert np.array_equal(_shown_xy(env), _xy_of(env, 2, 1000.0))
    assert len(env.scan.calls) == 2  # read again for the new options
    assert len(convert_worker._held_hook_data) == 1  # the old result was let go


def test_changed_options_by_args_change_also_drop_the_frame_cache(env):
    _hook_on(env)
    env._request_viewer_volume()
    env.on_viewer_frame_change(3)
    env.on_viewer_frame_change(6)
    env.scan.data = FULL + 500.0
    env.on_viewer_hook_args_change({"cache_dir": "z"})
    env.on_viewer_frame_change(3)
    assert np.array_equal(_shown_xy(env), _xy_of(env, 3, 500.0))


def test_turning_the_hook_off_lets_the_worker_free_the_result(env):
    _hook_on(env)
    env._request_viewer_volume()
    env.on_viewer_frame_change(4)
    assert convert_worker._held_hook_data
    env.on_viewer_hook_toggle(False, "sordino")
    assert not convert_worker._held_hook_data
    assert env._viewer_hook_enabled is False
    assert len(env._frame_cache) <= 1  # nothing of the hook's frames stays in main


# ---- timecourse --------------------------------------------------------------------------------


def test_hook_timecourse_asks_the_worker_with_the_hook_and_plots_the_whole_series(env):
    _hook_on(env)
    plot = _plot(env)
    env._request_viewer_volume()
    tc = [r for r in env.submitted if isinstance(r, TimecourseRequest)]
    assert tc and tc[-1].hook_name == "sordino" and tc[-1].hook_args == {"cache_dir": "x"}
    ras, _ = reorient_to_ras(FULL, np.eye(4))
    xi, yi, zi = (env.state.viewer.x_index, env.state.viewer.y_index, env.state.viewer.z_index)
    assert plot.lines is not None and plot.lines[1][0] == pytest.approx([float(v) for v in ras[xi, yi, zi, :]])
    assert len(env.scan.calls) == 1  # no second read of the hook, none of the plain data


def test_a_plain_timecourse_answer_is_not_reused_for_the_hook(env):
    _plot(env)
    env._request_viewer_volume()  # plain
    plain_key = env._timecourse_key((1, 1, 1))
    _hook_on(env)
    assert env._timecourse_key((1, 1, 1)) != plain_key
    env._viewer_hook_enabled = False
    assert env._timecourse_key((1, 1, 1)) == plain_key


def test_timecourse_after_other_options_is_a_new_request(env):
    _hook_on(env)
    _plot(env)
    env._request_viewer_volume()
    first = env._timecourse_key((1, 1, 1))
    env._viewer_hook_args = {"cache_dir": "other"}
    assert env._timecourse_key((1, 1, 1)) != first
