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


# ---- 2. timecourse npy is written from a contiguous array ---------------------------------


def test_timecourse_cache_is_saved_contiguous_and_equal(monkeypatch, tmp_path):
    data = np.arange(3 * 4 * 5 * 6, dtype=np.int16).reshape(3, 4, 5, 6)
    # an affine that swaps x and y makes reorient_to_ras return a permuted, non-contiguous view
    affine = np.array([[0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    scan = SimpleNamespace(get_dataobj=lambda reco_id, **kw: data)
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda scan, **kw: affine)
    saved = {}
    real_save = np.save

    def spy_save(path, arr, **kw):
        saved["c_contiguous"] = bool(arr.flags["C_CONTIGUOUS"])
        return real_save(path, arr, **kw)

    monkeypatch.setattr(convert_worker.np, "save", spy_save)
    from brkraw_viewer.utils.orientation import reorient_to_ras

    view, _ = reorient_to_ras(np.asarray(data), affine)
    assert not view.flags["C_CONTIGUOUS"], "the synthetic case must produce a non-contiguous view"
    out = _Queue()
    req = convert_worker.TimecourseCacheRequest(
        job_id="t", path="p", scan_id=1, reco_id=1, cache_path=str(tmp_path / "tc.npy")
    )
    convert_worker._process_timecourse_cache(req, out)
    assert out.items[0].error is None
    assert saved["c_contiguous"] is True
    assert np.array_equal(np.load(tmp_path / "tc.npy"), view)


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


# ---- 4. the timecourse cache key follows the source file's change time -------------------


def test_timecourse_cache_key_changes_when_the_source_changes(controller, tmp_path):
    study = tmp_path / "study.zip"
    study.write_bytes(b"first")
    controller.state.dataset.path = study
    first = controller._resolve_timecourse_cache_path()
    assert controller._resolve_timecourse_cache_path() == first
    os.utime(study, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert controller._resolve_timecourse_cache_path() != first


def test_timecourse_cache_key_for_a_folder_uses_the_2dseq_time(controller, tmp_path):
    folder = tmp_path / "study"
    pdata = folder / "3" / "pdata" / "1"
    pdata.mkdir(parents=True)
    seq = pdata / "2dseq"
    seq.write_bytes(b"x")
    controller.state.dataset.path = folder
    first = controller._resolve_timecourse_cache_path()
    os.utime(seq, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert controller._resolve_timecourse_cache_path() != first


# ---- 5. cache settings: only what the code uses, and the docs say so ---------------------


def test_default_cache_settings_are_the_ones_the_code_reads():
    cache = viewer_config.default_viewer_config()["cache"]
    assert set(cache) == {"memory_limit_mb"}
    assert cache["memory_limit_mb"] == 1024


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
    cfg["cache"]["memory_limit_mb"] = "bad"
    assert ViewerController()._memory_limit_bytes == 1024 * MB


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
    assert req.memory_limit_bytes == 1024 * MB and req.memory_confirmed is False


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
