"""WI-0104 item 7 (D-0170): the hook's reconstruction peak in the question.

With a hook on, ``peak_nbytes`` (one volume's reconstruction + the result buffer + three cache
frames, already complete: never add them again) plus what the viewer holds for other data is
compared with a share of the installed memory (``viewer.cache.hook_memory_percent``, default
25 %, 0 = off). One question for both checks; no question when the hook itself would refuse
(peak over its own ``limit_nbytes``).

Synthetic data only; no Tk display, no real memory reading.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult
from brkraw_viewer.app.workers.shm import release_shared_array

MB = 1024 * 1024
GB = 1024 * MB
_submitted: list = []


class _View:
    def __init__(self, answer=False):
        self.answer = answer
        self.calls = []
        self.status = []

    def confirm_large_load(self, estimated_mb, limit_mb, message=None):
        self.calls.append((estimated_mb, limit_mb, message))
        return self.answer

    def set_status(self, text):
        self.status.append(text)

    def __getattr__(self, name):
        return lambda *a, **k: None


def _controller(monkeypatch, tmp_path, cache=None, installed=(16 * GB, False)):
    cfg = viewer_config.default_viewer_config()
    if cache is not None:
        cfg["cache"] = dict(cache)
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    monkeypatch.setattr(memory_limit, "installed_memory", lambda: installed)
    monkeypatch.setattr(viewer_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    ctrl = ViewerController()
    _submitted.clear()
    ctrl._worker = SimpleNamespace(submit=lambda req: _submitted.append(req), log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 4
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: 10
    ctrl._view = _View()
    return ctrl


def _last_request():
    return [r for r in _submitted if isinstance(r, LoadVolumeRequest)][-1]


# ---- 7. controller: the share for the hook's peak ---------------------------------------------


def test_default_config_has_the_hook_share_of_25_percent():
    assert viewer_config.default_viewer_config()["cache"]["hook_memory_percent"] == 25


def test_hook_request_carries_a_quarter_of_the_installed_memory(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(16 * GB, False))
    ctrl._request_viewer_volume()
    assert _last_request().peak_limit_bytes == 4 * GB


def test_hook_percent_comes_from_its_own_key(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, cache={"memory_limit_mb": "auto", "hook_memory_percent": 40})
    ctrl._request_viewer_volume()
    assert _last_request().peak_limit_bytes == int(16 * GB * 0.40)


@pytest.mark.parametrize("value, expected", [(0, 0), ("x", 4 * GB), (True, 4 * GB), (-3, 0), (150, 16 * GB)])
def test_hook_percent_edges(monkeypatch, tmp_path, value, expected):
    ctrl = _controller(monkeypatch, tmp_path, cache={"hook_memory_percent": value})
    ctrl._request_viewer_volume()
    assert _last_request().peak_limit_bytes == expected


def test_memory_limit_zero_turns_the_hook_question_off_too(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, cache={"memory_limit_mb": 0})
    ctrl._request_viewer_volume()
    assert _last_request().peak_limit_bytes == 0


def _peak_notice(job_id, image=30 * MB, peak=5 * GB, held=0, peak_limit=4 * GB, reason="peak", limit=1 * GB):
    return LoadVolumeResult(
        job_id=job_id, shm_name=None, shape=(), dtype="", needs_confirm=True, estimated_bytes=image,
        limit_bytes=limit, held_bytes=held, peak_bytes=peak, peak_limit_bytes=peak_limit, reason=reason,
    )


def test_peak_notice_shows_image_peak_percent_and_the_key(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(16 * GB, False))
    ctrl._viewer_hook_enabled = True
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(_peak_notice(_last_request().job_id))
    est, lim, message = ctrl._view.calls[0]
    assert "5,120 MB" in message  # reconstruction peak
    assert "31 %" in message or "32 %" in message  # 5 GiB of 16 GiB = 31.25 %
    assert "25 %" in message and "viewer.cache.hook_memory_percent" in message
    assert "30 MB" in message  # the image itself
    assert "Continue" in message


def test_both_reasons_give_one_notice_with_both_lines(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(8 * GB, False))
    ctrl._viewer_hook_enabled = True
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(
        _peak_notice(_last_request().job_id, image=2 * GB, peak=6 * GB, peak_limit=2 * GB, reason="both", limit=int(8 * GB * 0.16))
    )
    assert len(ctrl._view.calls) == 1
    message = ctrl._view.calls[0][2]
    assert "16 %" in message and "viewer.cache.hook_memory_percent" in message


# ---- 7. worker --------------------------------------------------------------------------------


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _Scan:
    def __init__(self, shape=(32, 32, 32)):
        self.shape = shape
        self.image_info = {1: {"num_cycles": 1, "dataobj": None}}
        self.avail = {
            1: SimpleNamespace(
                file_visu_pars={
                    "VisuCoreSize": [int(np.prod(shape))],
                    "VisuCoreFrameCount": 1,
                    "VisuCoreWordType": "_32BIT_FLOAT",
                }
            )
        }

    def get_dataobj(self, reco_id, **kwargs):
        info = self.image_info[reco_id]
        if info.get("dataobj") is None:
            self.image_info[reco_id] = dict(info, dataobj=np.ones(self.shape, dtype=np.float32))
        return self.image_info[reco_id]["dataobj"]


@pytest.fixture
def env(monkeypatch):
    scan = _Scan()  # 0.125 MB
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda _s, _r: None)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda _s, **k: np.eye(4))
    for d in (convert_worker._held_recos, convert_worker._held_scans, convert_worker._meta_cache, convert_worker._held_hook_keys):
        d.clear()
    yield scan
    for d in (convert_worker._held_recos, convert_worker._held_scans, convert_worker._meta_cache, convert_worker._held_hook_keys):
        d.clear()


def _hook(monkeypatch, scan, info):
    """A hook whose ``get_dataobj_info`` returns ``info`` (a dict, or a function of kwargs)."""
    module = types.ModuleType("fake_wi0104_peak_hook")

    def get_dataobj(scan_, reco_id=None, **kwargs):
        return np.zeros((2, 2, 2), np.float32)

    def get_dataobj_info(scan_, reco_id=None, **kwargs):
        return info(kwargs) if callable(info) else dict(info)

    get_dataobj.__module__ = module.__name__
    module.get_dataobj = get_dataobj
    module.get_dataobj_info = get_dataobj_info
    monkeypatch.setitem(sys.modules, module.__name__, module)
    scan._converter_hook = {"get_dataobj": get_dataobj}


def _load(job="j", **kwargs):
    out = _Queue()
    kwargs.setdefault("hook_name", "fake_wi0104_peak")
    kwargs.setdefault("hook_args", {"a": 1})
    convert_worker._process_load_volume(LoadVolumeRequest(job_id=job, path="p", scan_id=1, reco_id=1, **kwargs), out)
    result = out.items[0]
    if result.shm_name:
        release_shared_array(result.shm_name)
    return result


def test_small_image_big_peak_asks_once_with_the_peak(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 5 * GB, "limit_nbytes": 64 * GB})
    result = _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB)
    assert result.needs_confirm and result.reason == "peak"
    assert result.peak_bytes == 5 * GB and result.peak_limit_bytes == 4 * GB
    assert result.estimated_bytes == 1 * MB and result.limit_bytes == 1 * GB


def test_big_image_alone_still_asks_as_before(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 2 * GB, "peak_nbytes": 2 * GB + 100 * MB, "limit_nbytes": 64 * GB})
    result = _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB)
    assert result.needs_confirm and result.reason == "size" and result.estimated_bytes == 2 * GB


def test_both_checks_give_one_result_with_reason_both(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 2 * GB, "peak_nbytes": 6 * GB, "limit_nbytes": 64 * GB})
    out = _Queue()
    convert_worker._process_load_volume(
        LoadVolumeRequest(
            job_id="b", path="p", scan_id=1, reco_id=1, hook_name="fake_wi0104_peak", hook_args={"a": 1},
            memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB,
        ),
        out,
    )
    assert len(out.items) == 1 and out.items[0].reason == "both"


def test_the_share_boundary_is_inclusive(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 4 * GB, "limit_nbytes": 64 * GB})
    assert not _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB).needs_confirm
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_hook_keys.clear()
    assert _load("again", memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB - 1).needs_confirm


def test_other_held_data_counts_with_the_peak(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 3 * GB, "limit_nbytes": 64 * GB})
    assert not _load("a", memory_limit_bytes=8 * GB, peak_limit_bytes=4 * GB, other_held_bytes=1 * GB).needs_confirm
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_hook_keys.clear()
    asked = _load("b", memory_limit_bytes=8 * GB, peak_limit_bytes=4 * GB, other_held_bytes=1 * GB + 1)
    assert asked.needs_confirm and asked.held_bytes == 1 * GB + 1 and asked.reason == "peak"
    # held data is not added twice: the peak is the hook's own number
    assert asked.peak_bytes == 3 * GB


def test_cached_result_has_a_small_peak_and_is_not_asked(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 1 * MB + 30 * MB, "limit_nbytes": 64 * GB, "cached": True})
    assert not _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB).needs_confirm


def test_an_older_hook_without_peak_nbytes_works_as_before(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB})
    assert not _load(memory_limit_bytes=1 * GB, peak_limit_bytes=1).needs_confirm
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_hook_keys.clear()
    _hook(monkeypatch, env, {"nbytes": 5 * MB})
    assert _load("big", memory_limit_bytes=1 * MB, peak_limit_bytes=1).reason == "size"


def test_peak_over_the_hooks_own_limit_is_not_asked(env, monkeypatch):
    # the hook will refuse this itself and say what to change; asking first helps no one
    _hook(monkeypatch, env, {"nbytes": 2 * GB, "peak_nbytes": 40 * GB, "limit_nbytes": 32 * GB})
    result = _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB)
    assert not result.needs_confirm  # it goes on to the hook, whose error the user then sees


def test_peak_exactly_at_the_hooks_limit_is_still_asked(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 32 * GB, "limit_nbytes": 32 * GB})
    assert _load(memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB).needs_confirm


def test_share_zero_turns_only_the_peak_check_off(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 50 * GB, "limit_nbytes": 64 * GB})
    assert not _load(memory_limit_bytes=1 * GB, peak_limit_bytes=0).needs_confirm
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    convert_worker._held_hook_keys.clear()
    _hook(monkeypatch, env, {"nbytes": 5 * MB, "peak_nbytes": 50 * GB, "limit_nbytes": 64 * GB})
    assert _load("size", memory_limit_bytes=1 * MB, peak_limit_bytes=0).reason == "size"


def test_confirmed_or_already_loaded_is_not_asked_again(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 5 * GB, "limit_nbytes": 64 * GB})
    assert _load("yes", memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB, memory_confirmed=True).needs_confirm is False
    # now it is held: the same request again (a later frame redraw) is not asked
    assert not _load("again", memory_limit_bytes=1 * GB, peak_limit_bytes=4 * GB).needs_confirm


def test_a_plain_load_ignores_the_peak_share(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 1 * MB, "peak_nbytes": 50 * GB, "limit_nbytes": 64 * GB})
    result = _load(hook_name=None, hook_args=None, memory_limit_bytes=1 * GB, peak_limit_bytes=1)
    assert not result.needs_confirm


def test_the_hook_info_helper_gives_the_three_numbers(env, monkeypatch):
    _hook(monkeypatch, env, {"nbytes": 7, "peak_nbytes": 9, "limit_nbytes": 11})
    assert convert_worker._hook_output_info(env, 1, {}) == {"nbytes": 7, "peak_nbytes": 9, "limit_nbytes": 11}
    assert convert_worker._hook_output_nbytes(env, 1, {}) == 7
    _hook(monkeypatch, env, {"nbytes": 7, "peak_nbytes": "x"})
    assert convert_worker._hook_output_info(env, 1, {}) == {"nbytes": 7, "peak_nbytes": None, "limit_nbytes": None}


def test_cancel_status_names_the_peak_when_the_peak_was_the_reason(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(16 * GB, False))
    ctrl._viewer_hook_enabled = True
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(_peak_notice(_last_request().job_id))  # answer: No
    assert "peak" in ctrl._view.status[-1] and "4096 MB" in ctrl._view.status[-1]
    assert "cancelled" in ctrl._view.status[-1]


def test_no_to_a_peak_notice_is_remembered_per_request_like_any_other_no(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path)
    ctrl._viewer_hook_enabled = True
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(_peak_notice(_last_request().job_id))  # No
    count = len([r for r in _submitted if isinstance(r, LoadVolumeRequest)])
    ctrl._request_viewer_volume()  # the slider moved: not asked again
    assert len([r for r in _submitted if isinstance(r, LoadVolumeRequest)]) == count
    assert len(ctrl._view.calls) == 1
    ctrl._view = _View(answer=True)
    ctrl._on_volume_result(_peak_notice(_last_request().job_id))  # Yes -> sent again as confirmed
    assert _last_request().memory_confirmed is True
