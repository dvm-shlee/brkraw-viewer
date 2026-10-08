"""WI-0105 (D-0145, contract C9): with a converter hook on, the worker keeps the hook's whole
result and sends main only the frame asked for, like a plain 4D scan.

Worker side only: synthetic scan stub, no Tk window, no real hook. The scan stub honours
``frames=`` the way brkraw 0.6 and the sordino hook do, and counts how often it was read.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, TimecourseRequest
from brkraw_viewer.app.workers.shm import read_shared_array, release_shared_array

MB = 1024 * 1024
N = 6
SHAPE = (2, 3, 4, N)
KEY = ("p", 1, 1)


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    image_info = {1: {"num_cycles": N, "dataobj": None}}

    def __init__(self):
        self.data = np.arange(int(np.prod(SHAPE)), dtype=np.float32).reshape(SHAPE)
        self.calls = []
        self.avail = {1: SimpleNamespace(file_visu_pars={})}
        self.result = None  # what get_dataobj returns when set (a tuple for slicepacks, a 3D array)

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append({"axis": axis, "frames": frames, **kwargs})
        if self.result is not None:
            return self.result
        data = self.data * (1 + len(self.calls) * 0.0)  # a new array object on every read
        if frames is None:
            return data.copy()
        start, stop = frames.split(":")
        return data[..., int(start) : int(stop or N)].copy()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for store in (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
                  convert_worker._held_hook_keys):
        store.clear()
    convert_worker._held_hook_data.clear()
    scan = _Scan()
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda s, r: 3)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda s, **kw: np.eye(4))
    yield scan
    for store in (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
                  convert_worker._held_hook_keys):
        store.clear()
    convert_worker._held_hook_data.clear()


def _load(**kwargs):
    out = _Queue()
    kwargs.setdefault("job_id", "j")
    req = LoadVolumeRequest(path="p", scan_id=1, reco_id=1, **kwargs)
    convert_worker._process_load_volume(req, out)
    result = out.items[0]
    if result.shm_name is None:
        return result, None
    arr, shm = read_shared_array(result.shm_name, result.shape, result.dtype)
    data = arr.copy()
    del arr
    shm.close()
    release_shared_array(result.shm_name)
    return result, data


def _hooked(frame, **kwargs):
    kwargs.setdefault("hook_name", "sordino")
    kwargs.setdefault("hook_args", {"cache_dir": "x"})
    return _load(frame_start=frame, frame_count=1, **kwargs)


def _timecourse(**kwargs):
    out = _Queue()
    req = TimecourseRequest(job_id="t", path="p", scan_id=1, reco_id=1, **kwargs)
    convert_worker._process_timecourse(req, out)
    return out.items[0]


# ---- a frame request with a hook sends one frame of the held result -----------------------------


def test_hook_frame_request_sends_only_that_frame(_env):
    result, data = _hooked(2)
    assert result.error is None
    assert data.shape == (2, 3, 4, 1)
    assert np.array_equal(data[..., 0], _env.data[..., 2])
    assert result.frames == N  # the whole result has N frames, though main got one


def test_hook_is_read_once_for_all_frames_and_never_for_a_frame_slice(_env):
    for frame in (0, 3, 5, 1):
        _result, data = _hooked(frame)
        assert np.array_equal(data[..., 0], _env.data[..., frame])
    assert len(_env.calls) == 1
    assert _env.calls[0]["frames"] is None  # a hook such as sordino honours frames=: never one frame


def test_worker_counts_the_held_hook_result(_env):
    _hooked(0)
    assert convert_worker._held_recos[KEY] >= _env.data.nbytes


def test_frame_beyond_the_result_is_the_last_frame(_env):
    result, data = _hooked(99)
    assert np.array_equal(data[..., 0], _env.data[..., N - 1])
    assert result.frames == N


def test_hook_result_without_a_frame_axis_is_sent_whole(_env):
    _env.result = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    result, data = _hooked(3)
    assert data.shape == (2, 3, 4)
    assert result.frames == 1


def test_request_for_all_frames_still_returns_every_frame_and_holds_it(_env):
    result, data = _load(frame_start=None, frame_count=None, hook_name="sordino", hook_args={"cache_dir": "x"})
    assert data.shape == SHAPE and result.frames == N
    _result, frame = _hooked(4)
    assert len(_env.calls) == 1
    assert np.array_equal(frame[..., 0], _env.data[..., 4])


def test_slicepack_is_chosen_from_the_held_result(_env):
    first = np.zeros(SHAPE, dtype=np.float32)
    second = np.ones(SHAPE, dtype=np.float32)
    _env.result = (first, second)
    result, data = _hooked(1, slicepack_index=1)
    assert result.slicepacks == 2 and data.shape == (2, 3, 4, 1) and data.max() == 1
    _result, data0 = _hooked(1, slicepack_index=0)
    assert data0.max() == 0
    assert len(_env.calls) == 1


# ---- the held result follows the request ------------------------------------------------------


def test_a_plain_request_for_the_reco_frees_the_held_hook_result(_env):
    _hooked(0)
    assert KEY in convert_worker._held_hook_data  # held before
    _result, _data = _load(frame_start=1, frame_count=1)  # no hook
    assert not convert_worker._held_hook_data
    assert convert_worker._held_recos[KEY] < _env.data.nbytes


def _hook_says_5_mb(monkeypatch):
    info = {"nbytes": 5 * MB, "peak_nbytes": None, "limit_nbytes": None}
    monkeypatch.setattr(convert_worker, "_hook_output_info", lambda scan, reco_id, kwargs: dict(info))


def test_other_hook_options_replace_the_held_result_and_ask_again(_env, monkeypatch):
    _hook_says_5_mb(monkeypatch)
    _hooked(0, memory_limit_bytes=10 * MB)
    assert len(_env.calls) == 1
    asked, _data = _hooked(0, hook_args={"cache_dir": "y"}, memory_limit_bytes=4 * MB)
    assert asked.needs_confirm and len(_env.calls) == 1  # asked, did not read: other options are a different load
    out = _Queue()
    convert_worker._process_load_volume(
        LoadVolumeRequest(job_id="j", path="p", scan_id=1, reco_id=1, frame_start=0, frame_count=1,
                          hook_name="sordino", hook_args={"cache_dir": "y"}, memory_limit_bytes=4 * MB,
                          memory_confirmed=True),
        out,
    )
    assert out.items[0].error is None and len(_env.calls) == 2
    held = convert_worker._held_hook_data
    assert len(held) == 1  # one hook result per reco: the old options were let go


def test_the_same_request_is_not_asked_again_for_the_next_frame(_env, monkeypatch):
    _hook_says_5_mb(monkeypatch)
    _hooked(0, memory_limit_bytes=4 * MB, memory_confirmed=True)
    result, data = _hooked(3, memory_limit_bytes=4 * MB)  # below the size, but already held
    assert not result.needs_confirm and data is not None


def test_turning_the_hook_off_and_on_asks_again_because_the_result_was_let_go(_env, monkeypatch):
    _hook_says_5_mb(monkeypatch)
    _hooked(0, memory_limit_bytes=4 * MB, memory_confirmed=True)
    _load(frame_start=0, frame_count=1)  # hook off: frees the hook result
    result, _data = _hooked(0, memory_limit_bytes=4 * MB)
    assert result.needs_confirm  # not confirmed in this request and nothing held for it any more


def test_removing_the_layer_frees_the_held_hook_result(_env):
    _hooked(0)
    assert KEY in convert_worker._held_hook_data  # held before
    convert_worker._release_reco(KEY)
    assert not convert_worker._held_hook_data
    assert KEY not in convert_worker._held_recos


def test_another_reco_in_keep_frees_the_held_hook_result(_env):
    _hooked(0)
    assert KEY in convert_worker._held_hook_data  # held before
    other = ("p", 1, 2)
    convert_worker._release_others(keep=(other,), current=other)
    assert not convert_worker._held_hook_data


# ---- timecourse from the held hook result ------------------------------------------------------


def test_hook_timecourse_is_answered_from_the_held_result(_env):
    _hooked(0)
    calls = len(_env.calls)
    result = _timecourse(index=(1, 2, 3), hook_name="sordino", hook_args={"cache_dir": "x"})
    assert result.error is None
    assert result.values == [float(v) for v in _env.data[1, 2, 3, :]]
    assert result.frames == N
    assert len(_env.calls) == calls  # not read again, no plain 2dseq read either


def test_hook_timecourse_without_a_held_result_says_so(_env):
    result = _timecourse(index=(0, 0, 0), hook_name="sordino", hook_args={})
    assert result.values is None
    assert "reload" in (result.error or "").lower()
    assert _env.calls == []


def test_hook_timecourse_keeps_the_held_bytes(_env):
    _hooked(0)
    _timecourse(index=(0, 0, 0), hook_name="sordino", hook_args={"cache_dir": "x"})
    assert convert_worker._held_recos[KEY] >= _env.data.nbytes


def test_hook_roi_timecourse_is_answered_from_the_held_result(_env):
    _hooked(0)
    mask = np.ones((3, 4), dtype=bool)
    result = _timecourse(index=(0, 0, 0), roi_axis=0, roi_index=1, roi_mask=mask,
                         hook_name="sordino", hook_args={"cache_dir": "x"})
    assert result.error is None
    assert result.values == pytest.approx([float(_env.data[1, :, :, f].mean()) for f in range(N)])
