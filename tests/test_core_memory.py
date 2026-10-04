"""T7 memory tests (contract v0.1 C9, WI-0072): one copy per data, no second copy in main,
release on layer change, total budget, hook-reported size. Synthetic data, no Tk window.

tracemalloc sees numpy allocations but not shared-memory mappings, so these tests measure
what the viewer's own code allocates around a load.
"""
from __future__ import annotations

import gc
import mmap
import multiprocessing.shared_memory as shared_memory
import sys
import tracemalloc
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult, TimecourseRequest
from brkraw_viewer.app.workers.shm import create_shared_array, map_shared_array, release_shared_array

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


def _base_is_mmap(arr: np.ndarray) -> bool:
    base = arr
    while isinstance(base, (np.ndarray, memoryview)):
        base = base.base if isinstance(base, np.ndarray) else base.obj
    return isinstance(base, mmap.mmap)


@pytest.fixture(autouse=True)
def _clean_worker_state():
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_scans.clear()
    yield
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_scans.clear()


# ---- main: the shared frame is used, not copied --------------------------------------------


def test_map_shared_array_uses_the_block_and_removes_its_name():
    src = np.arange(4 * 5 * 6, dtype=np.float32).reshape(4, 5, 6)
    name = create_shared_array(src)
    arr = map_shared_array(name, src.shape, str(src.dtype))
    assert np.array_equal(arr, src) and arr.shape == src.shape and arr.dtype == src.dtype
    assert not arr.flags.owndata and _base_is_mmap(arr)
    assert not _shm_exists(name)  # nothing left behind if the program stops now
    view = arr[::-1].transpose(2, 1, 0)  # views keep the mapping alive after the array goes
    del arr
    gc.collect()
    assert view[0, 0, 0] == src[-1, 0, 0]


def test_main_does_not_copy_the_frame_when_a_volume_arrives(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    ctrl._resolve_cycle_frames = lambda: 1
    frame = np.random.default_rng(0).standard_normal((64, 64, 32)).astype(np.float32)  # 0.5 MB
    name = create_shared_array(frame)
    result = LoadVolumeResult(job_id="j", shm_name=name, shape=frame.shape, dtype="float32", affine=np.eye(4).tolist())
    ctrl._viewer_job_id = "j"
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        ctrl._on_volume_result(result)
        peak = tracemalloc.get_traced_memory()[1] - before
    finally:
        tracemalloc.stop()
    assert np.array_equal(ctrl._viewer_raw_volume, frame)
    assert _base_is_mmap(np.asarray(ctrl._viewer_raw_volume))
    assert not _shm_exists(name)
    # the old code copied the frame (peak >= 1x frame); now well below one frame
    assert peak < 0.2 * frame.nbytes, (peak, frame.nbytes)


# ---- worker: one copy, release, budget, hook size -------------------------------------------


class _HeldScan:
    """Like brkraw: a full read is kept in image_info[reco]['dataobj'] (one copy)."""

    def __init__(self, shapes):
        self.shapes = shapes  # reco -> shape
        self.image_info = {r: {"num_cycles": 1, "dataobj": None} for r in shapes}
        self.avail = {
            r: SimpleNamespace(file_visu_pars={"VisuCoreSize": [int(np.prod(s))], "VisuCoreFrameCount": 1,
                                               "VisuCoreWordType": "_32BIT_FLOAT"})
            for r, s in shapes.items()
        }
        self.reads = 0

    def get_dataobj(self, reco_id, **kwargs):
        info = self.image_info[reco_id]
        if info.get("dataobj") is None:
            self.reads += 1
            data = np.ones(self.shapes[reco_id], dtype=np.float32)
            self.image_info[reco_id] = dict(info, dataobj=data)
        return self.image_info[reco_id]["dataobj"]


@pytest.fixture
def held_env(monkeypatch):
    scan = _HeldScan({1: (64, 64, 64), 2: (32, 32, 32)})  # 1 MB and 0.125 MB
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda _s, _r: None)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda _s, **k: np.eye(4))
    return scan


def _load(reco, **kwargs):
    out = _Queue()
    req = LoadVolumeRequest(job_id=f"r{reco}", path="p", scan_id=1, reco_id=reco, **kwargs)
    convert_worker._process_load_volume(req, out)
    return out.items[0]


def test_worker_holds_one_copy_and_adds_no_peak_of_its_own(held_env):
    nbytes = 64 * 64 * 64 * 4
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = tracemalloc.get_traced_memory()[0]
        result = _load(1)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    release_shared_array(result.shm_name)
    assert result.error is None
    # the read itself allocates the one copy (brkraw's job here); the viewer adds nothing
    assert current - start <= 1.05 * nbytes, (current - start, nbytes)
    assert peak - start <= 1.3 * nbytes, (peak - start, nbytes)
    assert convert_worker._held_recos[("p", 1, 1)] == nbytes


def test_loading_another_layer_releases_the_first_and_none_keeps_it(held_env):
    _free = lambda r: release_shared_array(r.shm_name)  # noqa: E731
    _free(_load(1, keep=(("p", 1, 1),)))
    assert held_env.image_info[1]["dataobj"] is not None
    _free(_load(2, keep=(("p", 1, 2),)))  # the viewer now shows reco 2 only
    assert held_env.image_info[1]["dataobj"] is None  # freed
    assert ("p", 1, 1) not in convert_worker._held_recos
    assert convert_worker._held_recos == {("p", 1, 2): 32 * 32 * 32 * 4}
    _free(_load(1))  # keep=None: the old behaviour, nothing is released
    assert held_env.image_info[2]["dataobj"] is not None
    assert set(convert_worker._held_recos) == {("p", 1, 1), ("p", 1, 2)}
    assert held_env.reads == 3  # reco 1 was read again after it was freed


def test_budget_counts_what_other_layers_hold(held_env):
    one, small = 64 * 64 * 64 * 4, 32 * 32 * 32 * 4
    release_shared_array(_load(1, keep=None).shm_name)
    limit = one + small - 1
    # reco 1 stays held: 1 MB + 0.125 MB > limit -> ask, and say what is held
    asked = _load(2, memory_limit_bytes=limit, keep=(("p", 1, 1), ("p", 1, 2)))
    assert asked.needs_confirm and asked.estimated_bytes == small and asked.held_bytes == one
    # reco 1 is no longer shown: freed first, then 0.125 MB alone fits
    ok = _load(2, memory_limit_bytes=limit, keep=(("p", 1, 2),))
    assert not ok.needs_confirm and ok.shm_name
    release_shared_array(ok.shm_name)


def test_controller_asks_with_the_total_held(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    ctrl._worker = SimpleNamespace(submit=lambda req: None, log_queue=None)
    asked = []
    ctrl._view = SimpleNamespace(
        confirm_large_load=lambda est, lim: asked.append((est, lim)) or False,
        set_status=lambda text: None,
    )
    ctrl._on_large_load_notice(
        LoadVolumeResult(job_id="x", shm_name=None, shape=(), dtype="", needs_confirm=True,
                         estimated_bytes=1000 * MB, limit_bytes=1536 * MB, held_bytes=600 * MB)
    )
    assert asked == [(1600.0, 1536.0)]


def test_hook_reports_its_output_size(held_env, monkeypatch):
    module = types.ModuleType("fake_viewer_hook_mod")

    def get_dataobj(scan, reco_id=None, **kwargs):
        return np.zeros((2, 2, 2), np.float32)

    def get_dataobj_info(scan, reco_id=None, **kwargs):
        return {"nbytes": 5 * MB, "shape": (1,)}

    get_dataobj.__module__ = module.__name__
    module.get_dataobj = get_dataobj
    module.get_dataobj_info = get_dataobj_info
    monkeypatch.setitem(sys.modules, module.__name__, module)
    held_env._converter_hook = {"get_dataobj": get_dataobj}
    out = _Queue()
    req = LoadVolumeRequest(job_id="h", path="p", scan_id=1, reco_id=2, hook_name="fake", memory_limit_bytes=4 * MB)
    convert_worker._process_load_volume(req, out)
    # 2dseq is 0.125 MB, but the hook says 5 MB: the notice uses the hook's size
    assert out.items[0].needs_confirm and out.items[0].estimated_bytes == 5 * MB
    assert convert_worker._hook_output_nbytes(SimpleNamespace(), 1, {}) is None  # no hook: unknown


# ---- worker: the timecourse adds no full copy ------------------------------------------------


def test_timecourse_reads_one_voxel_without_copying_the_volume(monkeypatch):
    data = np.random.default_rng(1).standard_normal((32, 32, 16, 64)).astype(np.float32)  # 4 MB
    flip = np.diag([-1.0, 1.0, 1.0, 1.0])  # reorientation flips x: a view, not a copy
    scan = SimpleNamespace(get_dataobj=lambda reco_id, **kw: data, image_info={1: {"dataobj": data}})
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda _s, **k: flip)
    out = _Queue()
    convert_worker._process_timecourse(TimecourseRequest(job_id="w", path="p", scan_id=1, reco_id=1), out)
    gc.collect()
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        start = tracemalloc.get_traced_memory()[0]
        for i in range(10):
            req = TimecourseRequest(job_id=f"t{i}", path="p", scan_id=1, reco_id=1, index=(i, 2 * i, i % 16))
            convert_worker._process_timecourse(req, out)
        peak = tracemalloc.get_traced_memory()[1] - start
    finally:
        tracemalloc.stop()
    assert all(r.error is None for r in out.items)
    assert out.items[-1].values == data[32 - 1 - 9, 18, 9, :].astype(float).tolist()  # x flipped
    assert peak < 0.05 * data.nbytes, (peak, data.nbytes)
    assert convert_worker._held_recos[("p", 1, 1)] == data.nbytes
