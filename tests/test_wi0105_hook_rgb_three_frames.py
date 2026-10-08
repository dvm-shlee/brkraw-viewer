"""WI-0105 follow-up (D-0175 option C): a converter hook whose result has exactly 3 frames.

Main holds one frame of the hook result, so it cannot see colour channels by itself. The RGB
toggle is still offered (the result has 3 frames); turning it on asks the worker for the 3 frames,
turning it off asks for one frame again, so main holds 3 frames only while RGB is on (C9).
Controller and worker are wired in one process; the scan is a synthetic stub. No Tk window.
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
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest
from brkraw_viewer.utils.orientation import reorient_to_ras

GB = 1024 * 1024 * 1024
SHAPE3 = (12, 10, 6)


def _full(n):
    shape = SHAPE3 + (n,)
    return (np.arange(int(np.prod(shape)), dtype=np.float32) % 97).reshape(shape) + 1.0


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    def __init__(self, n):
        self.n = n
        self.image_info = {1: {"num_cycles": n, "dataobj": None}}
        self.avail = {1: SimpleNamespace(file_visu_pars={})}
        self.calls = []
        self.data = _full(n)

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append({"axis": axis, "frames": frames, **kwargs})
        return self.data.copy()


class _View:
    def __init__(self):
        self.views = []
        self.rgb = []
        self.ranges = []

    def set_viewer_views(self, views, **kwargs):
        self.views.append({k: np.array(v) for k, v in views.items()})

    def set_viewer_rgb_state(self, enabled, active):
        self.rgb.append((bool(enabled), bool(active)))

    def set_viewer_ranges(self, **kwargs):
        self.ranges.append(kwargs)

    def after(self, ms, func):
        func()
        return None

    def __getattr__(self, name):
        return lambda *a, **k: None


_STORES = (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
           convert_worker._held_hook_keys, convert_worker._held_hook_data)


def _make(monkeypatch, tmp_path, n):
    cfg = viewer_config.default_viewer_config()
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    for store in _STORES:
        store.clear()
    scan = _Scan(n)
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

    ctrl._worker = SimpleNamespace(submit=submit, log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 1
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: n
    ctrl._view = _View()
    ctrl.scan = scan
    ctrl._viewer_hook_name = "colour"
    ctrl._viewer_hook_enabled = True
    ctrl._viewer_hook_args = {"a": 1}
    return ctrl


@pytest.fixture
def three(monkeypatch, tmp_path):
    yield _make(monkeypatch, tmp_path, 3)
    for store in _STORES:
        store.clear()


@pytest.fixture
def four(monkeypatch, tmp_path):
    yield _make(monkeypatch, tmp_path, 4)
    for store in _STORES:
        store.clear()


def _loads(ctrl):
    return [r for r in ctrl.submitted if isinstance(r, LoadVolumeRequest)]


def _indices(ctrl):
    v = ctrl.state.viewer
    return v.x_index, v.y_index, v.z_index


def _ras(n):
    ras, _ = reorient_to_ras(_full(n), np.eye(4))
    return ras


def test_a_three_frame_hook_result_offers_rgb_while_main_holds_one_frame(three):
    three._request_viewer_volume()
    assert np.shape(three._viewer_raw_volume) == SHAPE3 + (1,)
    assert three._view.rgb[-1] == (True, False)  # offered, not on
    assert len(three.scan.calls) == 1


def test_rgb_on_asks_the_worker_for_the_three_frames_and_shows_colour(three):
    three._request_viewer_volume()
    three.state.viewer.x_index, three.state.viewer.y_index, three.state.viewer.z_index = 1, 2, 3
    before = _indices(three)
    assert before == (1, 2, 3)
    three.on_viewer_rgb_toggle(True)
    req = _loads(three)[-1]
    assert (req.frame_start, req.frame_count) == (0, 3)
    assert req.hook_name == "colour"
    assert np.shape(three._viewer_raw_volume) == SHAPE3 + (3,)
    assert three._view.rgb[-1] == (True, True)
    assert _indices(three) == before  # the crosshair does not jump to the centre
    xi, yi, zi = _indices(three)
    ras = _ras(3)
    shown = three._view.views[-1]
    assert np.array_equal(shown["xy"], ras[:, :, zi, :].transpose(1, 0, 2))
    assert np.array_equal(shown["xz"], ras[:, yi, :, :].transpose(1, 0, 2))
    assert np.array_equal(shown["zy"], ras[xi, :, :, :])
    assert len(three.scan.calls) == 1  # the hook was not read again


def test_rgb_off_asks_for_one_frame_again_and_shows_grey(three):
    three._request_viewer_volume()
    three.on_viewer_rgb_toggle(True)
    three.state.viewer.frame_index = 2
    three.state.viewer.x_index = 4
    three.on_viewer_rgb_toggle(False)
    req = _loads(three)[-1]
    assert (req.frame_start, req.frame_count) == (2, 1)
    assert three.state.viewer.x_index == 4  # the crosshair stays
    assert np.shape(three._viewer_raw_volume) == SHAPE3 + (1,)  # main let the other two go
    assert three._view.rgb[-1] == (True, False)
    xi, yi, zi = _indices(three)
    assert np.array_equal(three._view.views[-1]["xy"], _ras(3)[:, :, zi, 2].T)
    assert len(three.scan.calls) == 1


def test_another_load_while_rgb_is_on_asks_for_the_three_frames_again(three):
    three._request_viewer_volume()
    three.on_viewer_rgb_toggle(True)
    three._request_viewer_volume()  # for example after a change of space
    req = _loads(three)[-1]
    assert (req.frame_start, req.frame_count) == (0, 3)
    assert three._view.rgb[-1] == (True, True)


def test_a_frame_change_while_rgb_is_on_does_not_drop_the_colour(three):
    three._request_viewer_volume()
    three.on_viewer_rgb_toggle(True)
    count = len(_loads(three))
    three.on_viewer_frame_change(1)
    assert len(_loads(three)) == count
    assert np.shape(three._viewer_raw_volume) == SHAPE3 + (3,)


def test_a_four_frame_hook_result_does_not_offer_rgb(four):
    four._request_viewer_volume()
    assert four._view.rgb[-1][0] is False
    four.on_viewer_rgb_toggle(True)
    assert four.state.viewer.rgb_mode is False
    assert all((r.frame_start, r.frame_count) != (0, 3) for r in _loads(four))


def test_a_three_block_of_a_longer_result_is_not_colour(four):
    # a request for three frames of a four-frame result (what a stale RGB flag from an earlier
    # scan would ask) must not be drawn as colour channels
    four._request_viewer_volume()
    four.state.viewer.rgb_mode = True
    four._viewer_frames = 3  # as the earlier scan left it
    four._request_viewer_volume()
    assert np.shape(four._viewer_raw_volume)[3] == 3
    assert four._viewer_frames == 4
    assert four._view.rgb[-1][1] is False
    assert four._view.views[-1]["xy"].ndim == 2
