"""WI-0068: viewer display-speed fixes (synthetic data only, no Tk window, no real dataset)."""

from __future__ import annotations

import multiprocessing.shared_memory as shared_memory
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult
from brkraw_viewer.app.workers.shm import create_shared_array, read_shared_array, release_shared_array

MB = 1024 * 1024


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def _shm_exists(name: str) -> bool:
    try:
        shm = shared_memory.SharedMemory(name=name)
    except FileNotFoundError:
        return False
    shm.close()
    return True


def _free(result) -> None:
    if getattr(result, "shm_name", None):
        release_shared_array(result.shm_name)


@pytest.fixture(autouse=True)
def _clean_worker_state():
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    yield
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()


class _Scan:
    """Synthetic 4D scan (x, y, z, cycle): one frame per get_dataobj(axis=, frames=) call."""

    def __init__(self, n_cycles=5, visu=None):
        self.data = np.arange(2 * 3 * 4 * n_cycles, dtype=np.int16).reshape(2, 3, 4, n_cycles)
        self.image_info = {1: {"num_cycles": n_cycles, "dataobj": None}}
        self.avail = {1: SimpleNamespace(file_visu_pars=visu or {})}
        self.reads = 0

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.reads += 1
        if frames is None:
            return self.data
        start, stop = frames.split(":")
        return self.data[..., int(start) : int(stop or self.data.shape[3])]


@pytest.fixture
def worker_env(monkeypatch):
    scan = _Scan()
    counts = {"axis": 0, "affine": 0}

    def axis(_scan, _reco):
        counts["axis"] += 1
        return 3

    def affine(_scan, **kwargs):
        counts["affine"] += 1
        return np.eye(4)

    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", axis)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", affine)
    return scan, counts


def _load(frame, **kwargs):
    out = _Queue()
    req = LoadVolumeRequest(
        job_id=f"j{frame}", path="p", scan_id=1, reco_id=1, frame_start=frame, frame_count=1, **kwargs
    )
    convert_worker._process_load_volume(req, out)
    return out.items[0]


# ---- 1. axis number and affine are computed once, not for every frame --------------------


def test_frame_axis_and_affine_are_computed_once_for_many_frames(worker_env):
    scan, counts = worker_env
    for frame in range(5):
        result = _load(frame)
        assert result.error is None
        arr, shm = read_shared_array(result.shm_name, result.shape, result.dtype)
        assert np.array_equal(arr[..., 0], scan.data[..., frame])
        shm.close()
        _free(result)
    assert counts == {"axis": 1, "affine": 1}


def test_affine_is_recomputed_when_a_request_setting_changes(worker_env):
    _scan, counts = worker_env
    _free(_load(0))
    _free(_load(1, flip_x=True))
    _free(_load(2, flip_x=True))
    _free(_load(3, space="raw"))
    assert counts["affine"] == 3
    assert counts["axis"] == 1


# ---- 2. timecourse: answered by the worker from the held data (WI-0072 C9; the full-volume
#      .npy file of WI-0068 is gone, so its contiguous-save test was replaced) ---------------


def test_timecourse_is_answered_on_the_reoriented_grid_without_a_file(monkeypatch, tmp_path):
    data = np.arange(3 * 4 * 5 * 6, dtype=np.int16).reshape(3, 4, 5, 6)
    # an affine that swaps x and y makes the displayed grid a permuted view of the data
    affine = np.array([[0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    scan = SimpleNamespace(get_dataobj=lambda reco_id, **kw: data, image_info={})
    calls = {"affine": 0}

    def affine_once(_scan, **kw):
        calls["affine"] += 1
        return affine

    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", affine_once)
    monkeypatch.setattr(convert_worker.np, "save", lambda *a, **k: pytest.fail("no file is written"))
    from brkraw_viewer.utils.orientation import reorient_to_ras

    view, _ = reorient_to_ras(np.asarray(data), affine)
    out = _Queue()
    for index in ((0, 0, 0), (3, 2, 4), (1, 2, 3)):
        req = convert_worker.TimecourseRequest(job_id="t", path="p", scan_id=1, reco_id=1, index=index)
        convert_worker._process_timecourse(req, out)
        result = out.items[-1]
        assert result.error is None and result.frames == 6 and result.index == index
        assert result.values == view[index].astype(float).tolist()
    assert calls["affine"] == 1  # computed once for many voxels
    bad = convert_worker.TimecourseRequest(job_id="b", path="p", scan_id=1, reco_id=1, index=(9, 0, 0))
    convert_worker._process_timecourse(bad, out)
    assert out.items[-1].values is None and "outside" in out.items[-1].error
    assert not list(tmp_path.iterdir())


# ---- 3. an abandoned worker result frees its shared memory --------------------------------


@pytest.fixture
def controller(monkeypatch, tmp_path):
    # never read the real user config or cache folder in a test
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    ctrl._worker = SimpleNamespace(submit=lambda req: ctrl_submitted.append(req), log_queue=None)
    ctrl_submitted.clear()
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 3
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: 1
    return ctrl


ctrl_submitted: list = []


def test_stale_volume_result_releases_its_shared_memory(controller):
    name = create_shared_array(np.ones((2, 2, 2), dtype=np.int16))
    assert _shm_exists(name)
    controller._viewer_job_id = "current-job"
    stale = LoadVolumeResult(job_id="old-job", shm_name=name, shape=(2, 2, 2), dtype="int16")
    controller._on_volume_result(stale)
    assert not _shm_exists(name)


def test_unreadable_volume_result_releases_its_shared_memory(controller, monkeypatch):
    name = create_shared_array(np.ones((2, 2, 2), dtype=np.int16))
    controller._viewer_job_id = "job"
    # wrong dtype string makes read_shared_array fail after the block exists
    bad = LoadVolumeResult(job_id="job", shm_name=name, shape=(2, 2, 2), dtype="not-a-dtype")
    controller._on_volume_result(bad)
    assert not _shm_exists(name)


# ---- 4. timecourse requests: one per voxel and setting, stale answers dropped (WI-0072 C9;
#      replaces the two .npy cache-key tests of WI-0068, the file no longer exists) ----------


def test_timecourse_request_is_sent_once_per_voxel_and_old_answers_are_dropped(controller):
    from brkraw_viewer.app.workers.protocol import TimecourseResult

    controller._request_timecourse((1, 2, 3))
    controller._request_timecourse((1, 2, 3))  # same voxel and settings: not sent again
    assert len(ctrl_submitted) == 1
    first = ctrl_submitted[-1]
    assert first.index == (1, 2, 3) and (first.scan_id, first.reco_id) == (3, 1)
    controller.state.viewer.flip_x = True
    controller._request_timecourse((1, 2, 3))  # a setting changed: new request
    assert len(ctrl_submitted) == 2 and ctrl_submitted[-1].flip_x is True
    controller._on_timecourse_result(TimecourseResult(job_id=first.job_id, values=[9.0], frames=1))
    assert controller._timecourse_series is None  # the older job's answer is ignored
    latest = ctrl_submitted[-1]
    controller._on_timecourse_result(TimecourseResult(job_id=latest.job_id, values=[1.0, 2.0], frames=2))
    key, values = controller._timecourse_series
    assert values == [1.0, 2.0] and key == controller._timecourse_key((1, 2, 3))
    controller._clear_timecourse()
    assert controller._timecourse_series is None and controller._timecourse_pending is None


# ---- 5. cache settings: only what the code uses, and the docs say so ---------------------


def test_default_cache_settings_are_the_ones_the_code_reads():
    cache = viewer_config.default_viewer_config()["cache"]
    assert set(cache) == {"memory_limit_mb", "hook_memory_percent"}  # WI-0104 items 8 and 7
    assert cache["memory_limit_mb"] == "auto"  # 16 % of the installed memory, at least 512 MB (WI-0104 item 8, D-0169)


def test_config_docs_describe_every_default_cache_setting_and_retired_keys():
    docs = (Path(__file__).resolve().parents[1] / "docs" / "user" / "config.md").read_text(encoding="utf-8")
    for key in viewer_config.default_viewer_config()["cache"]:
        assert key in docs
    for retired in ("cache.enabled", "cache.max_items"):
        assert retired in docs and "ignored" in docs


def test_memory_limit_setting_is_read_by_the_controller(monkeypatch, tmp_path):
    cfg = viewer_config.default_viewer_config()
    cfg["cache"]["memory_limit_mb"] = 2
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    assert ViewerController()._memory_limit_bytes == 2 * MB
    cfg["cache"]["memory_limit_mb"] = 0
    assert ViewerController()._memory_limit_bytes == 0
    cfg["cache"]["memory_limit_mb"] = "bad"  # not a number and not "auto": the automatic value (WI-0104 item 8)
    from brkraw_viewer.app.services import memory_limit

    monkeypatch.setattr(memory_limit, "installed_memory", lambda: (10 * 1024 * MB, False))
    assert ViewerController()._memory_limit_bytes == int(10 * 1024 * MB * 0.16)


# ---- 6. notice before loading a big reco: worker side ------------------------------------


def _visu(size, frames, word="_16BIT_SGN_INT"):
    return {"VisuCoreSize": size, "VisuCoreFrameCount": frames, "VisuCoreWordType": word}


def test_expected_nbytes_from_visu_pars_only():
    scan = _Scan(visu=_visu([72, 72], 28800))
    assert convert_worker._expected_nbytes(scan, 1) == 72 * 72 * 28800 * 2
    scan = _Scan(visu=_visu([16, 16, 16], 10, "_32BIT_FLOAT"))
    assert convert_worker._expected_nbytes(scan, 1) == 16 * 16 * 16 * 10 * 4
    assert convert_worker._expected_nbytes(_Scan(visu={}), 1) is None


def test_load_above_the_limit_asks_and_reads_nothing(worker_env):
    scan, _counts = worker_env
    scan.avail[1] = SimpleNamespace(file_visu_pars=_visu([10, 10], 100))  # 20,000 bytes
    result = _load(0, memory_limit_bytes=10_000)
    assert result.needs_confirm is True
    assert result.estimated_bytes == 20_000 and result.limit_bytes == 10_000
    assert result.shm_name is None and result.error is None
    assert scan.reads == 0


def test_default_limit_lets_1_gb_open_and_asks_above_1536_mb(worker_env):
    # WI-0072 (D-0095 3): 1536 MB for the total held; with nothing else held a 1 GB scan opens.
    scan, _counts = worker_env
    limit = 1536 * MB  # a config number (an older config keeps its 1536); the default is now "auto"
    for size_bytes, asks in ((1000 * 1000 * 1000, False), (1024 * MB, False), (1536 * MB, False), (1538 * MB, True)):
        convert_worker._held_recos.clear()
        convert_worker._meta_cache.clear()
        scan.avail[1] = SimpleNamespace(file_visu_pars=_visu([size_bytes // 2], 1))  # 2 bytes per value
        result = _load(0, memory_limit_bytes=limit)
        assert result.needs_confirm is asks, size_bytes
        if not asks:
            _free(result)
    assert scan.reads == 3


def test_load_at_or_below_the_limit_does_not_ask(worker_env):
    scan, _counts = worker_env
    scan.avail[1] = SimpleNamespace(file_visu_pars=_visu([10, 10], 100))
    result = _load(0, memory_limit_bytes=20_000)  # equal to the size: no notice
    assert result.needs_confirm is False and result.shm_name
    _free(result)
    assert scan.reads == 1


def test_confirmed_zero_limit_and_already_held_loads_do_not_ask(worker_env):
    scan, _counts = worker_env
    scan.avail[1] = SimpleNamespace(file_visu_pars=_visu([10, 10], 100))
    for kwargs in ({"memory_limit_bytes": 1, "memory_confirmed": True}, {"memory_limit_bytes": 0}):
        convert_worker._held_recos.clear()
        result = _load(0, **kwargs)
        assert not result.needs_confirm and result.shm_name
        _free(result)
    # once the reco is held, later frames never ask again even with a tiny limit
    result = _load(1, memory_limit_bytes=1)
    assert not result.needs_confirm
    _free(result)


def test_unknown_size_does_not_ask(worker_env):
    scan, _counts = worker_env
    scan.avail[1] = SimpleNamespace(file_visu_pars={})
    result = _load(0, memory_limit_bytes=1)
    assert not result.needs_confirm
    _free(result)


# ---- 6. notice: controller side ----------------------------------------------------------


class _View:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []
        self.status = []

    def confirm_large_load(self, estimated_mb, limit_mb):
        self.asked.append((estimated_mb, limit_mb))
        return self.answer

    def set_status(self, text):
        self.status.append(text)

    def __getattr__(self, name):  # any other view call is a no-op
        return lambda *a, **k: None


def _needs_confirm(job_id, estimated=3 * MB, limit=1 * MB):
    return LoadVolumeResult(
        job_id=job_id, shm_name=None, shape=(), dtype="", needs_confirm=True, estimated_bytes=estimated, limit_bytes=limit
    )


def test_request_carries_the_limit(controller):
    controller._request_viewer_volume()
    req = ctrl_submitted[-1]
    assert req.memory_limit_bytes == controller._memory_limit_bytes > 0 and req.memory_confirmed is False
    assert req.keep == ((str(controller.state.dataset.path), 3, 1),)  # C9: only this reco stays held


def test_user_continues_then_the_load_is_sent_again_as_confirmed(controller):
    view = _View(True)
    controller._view = view
    controller._request_viewer_volume()
    first = ctrl_submitted[-1]
    controller._on_volume_result(_needs_confirm(first.job_id))
    assert view.asked == [(3.0, 1.0)]
    assert len(ctrl_submitted) == 2
    assert ctrl_submitted[-1].memory_confirmed is True
    # later requests for the same reco stay confirmed
    controller._request_viewer_volume()
    assert ctrl_submitted[-1].memory_confirmed is True


def test_user_cancels_then_nothing_is_loaded_and_not_asked_again(controller):
    view = _View(False)
    controller._view = view
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(ctrl_submitted[-1].job_id))
    assert len(ctrl_submitted) == 1
    assert any("cancel" in text.lower() for text in view.status)
    controller._request_viewer_volume()  # e.g. the frame slider moved
    assert len(ctrl_submitted) == 1
    assert len(view.asked) == 1


def test_selecting_a_reco_again_clears_the_cancel(controller):
    view = _View(False)
    controller._view = view
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(ctrl_submitted[-1].job_id))
    assert controller._memory_declined
    controller._forget_memory_choices()
    assert not controller._memory_declined and not controller._memory_confirmed


def test_stale_confirm_request_is_ignored(controller):
    view = _View(True)
    controller._view = view
    controller._viewer_job_id = "current"
    controller._on_volume_result(_needs_confirm("old"))
    assert view.asked == [] and ctrl_submitted == []
