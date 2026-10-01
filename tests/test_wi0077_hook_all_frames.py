"""WI-0077: a request for all frames (frame_start and frame_count both None, what the viewer sends
when a converter hook such as sordino is on) must return every frame, not only the first one.

Synthetic data only; the scan stub honours ``frames=`` like brkraw 0.6 and the sordino hook do.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest
from brkraw_viewer.app.workers.shm import read_shared_array, release_shared_array

N_CYCLES = 5


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    image_info = {1: {"num_cycles": N_CYCLES, "dataobj": None}}

    def __init__(self):
        self.data = np.arange(2 * 3 * 4 * N_CYCLES, dtype=np.int16).reshape(2, 3, 4, N_CYCLES)
        self.calls = []
        self.avail = {1: SimpleNamespace(file_visu_pars={})}

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append({"axis": axis, "frames": frames, **kwargs})
        if frames is None:
            return self.data
        start, stop = frames.split(":")
        return self.data[..., int(start) : int(stop or self.data.shape[3])]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    scan = _Scan()
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda s, r: 3)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda s, **kw: np.eye(4))
    yield scan
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()


def _load(**kwargs):
    out = _Queue()
    req = LoadVolumeRequest(job_id="j", path="p", scan_id=1, reco_id=1, **kwargs)
    convert_worker._process_load_volume(req, out)
    result = out.items[0]
    assert result.error is None
    arr, shm = read_shared_array(result.shm_name, result.shape, result.dtype)
    data = arr.copy()
    shm.close()
    release_shared_array(result.shm_name)
    return result, data


def test_hook_request_for_all_frames_returns_every_frame(_env):
    result, data = _load(frame_start=None, frame_count=None, hook_name="sordino", hook_args={"cache_dir": "x"})
    assert data.shape == (2, 3, 4, N_CYCLES)
    assert result.frames == N_CYCLES
    assert np.array_equal(data, _env.data)


def test_request_for_all_frames_without_hook_returns_every_frame(_env):
    result, data = _load(frame_start=None, frame_count=None)
    assert data.shape[3] == N_CYCLES
    assert result.frames == N_CYCLES


def test_all_frames_request_does_not_ask_the_reader_for_a_frame_slice(_env):
    _load(frame_start=None, frame_count=None, hook_name="sordino", hook_args={})
    assert all(call["frames"] is None for call in _env.calls)


def test_single_frame_request_still_reads_one_frame(_env):
    result, data = _load(frame_start=3, frame_count=1)
    assert data.shape == (2, 3, 4, 1)
    assert np.array_equal(data[..., 0], _env.data[..., 3])
    assert result.frames == 1


def test_start_only_request_reads_to_the_end(_env):
    _result, data = _load(frame_start=2, frame_count=None)
    assert data.shape == (2, 3, 4, N_CYCLES - 2)
    assert np.array_equal(data, _env.data[..., 2:])
