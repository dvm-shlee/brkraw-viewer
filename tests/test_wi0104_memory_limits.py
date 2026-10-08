"""WI-0104 items 8 and 7 (D-0169, D-0170): memory limit from the installed memory, and the
hook's reconstruction peak in the question.

8. ``viewer.cache.memory_limit_mb`` missing or ``auto``: 16 % of the installed memory (at least
   512 MB); a number wins (also an old config's number); 0 never asks. Over the limit is a
   warning the user answers with continue or cancel, and the notice says where the number
   came from.
7. With a hook on, ``peak_nbytes`` (one volume's reconstruction + the result buffer + three cache
   frames, already complete) plus what the viewer holds for other data is compared with a share of
   the installed memory (``viewer.cache.hook_memory_percent``, default 25 %). One question for both
   checks; no question when the hook itself would refuse (peak over its own limit).

Synthetic data only; no Tk display, no real memory reading.
"""

from __future__ import annotations

import ctypes
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult
from brkraw_viewer.app.workers.shm import release_shared_array
from brkraw_viewer.ui.main import window as main_window

MB = 1024 * 1024
GB = 1024 * MB


def _ml():
    from brkraw_viewer.app.services import memory_limit

    return memory_limit


# ---- 8. installed memory and the limit --------------------------------------------------------


@pytest.mark.parametrize("value", [None, "auto", "AUTO", " auto ", "", "garbage", True, [], {}])
def test_missing_or_auto_is_sixteen_percent_of_the_installed_memory(value):
    ml = _ml().resolve_memory_limit(value, (8 * GB, False))
    assert ml.limit_bytes == int(8 * GB * 0.16)
    assert ml.mode == "auto" and not ml.floor_applied and not ml.installed_assumed


def test_small_installed_memory_gets_the_512_mb_floor():
    ml = _ml().resolve_memory_limit("auto", (2 * GB, False))  # 16 % = 327 MB
    assert ml.limit_bytes == 512 * MB and ml.floor_applied


def test_a_number_in_the_config_wins_even_the_old_default():
    for number in (1536, 600, 4000, 1.5):
        ml = _ml().resolve_memory_limit(number, (64 * GB, False))
        assert ml.limit_bytes == int(number * MB) and ml.mode == "config"
    assert _ml().resolve_memory_limit(300, (64 * GB, False)).limit_bytes == 300 * MB  # below the floor too


def test_zero_never_asks_and_negative_is_the_same():
    for value in (0, 0.0, -5):
        ml = _ml().resolve_memory_limit(value, (8 * GB, False))
        assert ml.limit_bytes == 0 and ml.mode == "off"


def test_installed_memory_not_readable_assumes_4_gb(monkeypatch):
    mod = _ml()
    monkeypatch.setattr(mod, "_read_installed_bytes", lambda: (_ for _ in ()).throw(OSError("no")))
    assert mod.installed_memory() == (4 * GB, True)
    ml = mod.resolve_memory_limit("auto", mod.installed_memory())
    assert ml.installed_assumed and ml.limit_bytes == int(4 * GB * 0.16)
    monkeypatch.setattr(mod, "_read_installed_bytes", lambda: 0)  # a zero answer is not an answer
    assert mod.installed_memory() == (4 * GB, True)
    monkeypatch.setattr(mod, "_read_installed_bytes", lambda: 16 * GB)
    assert mod.installed_memory() == (16 * GB, False)


def test_windows_reads_global_memory_status_ex(monkeypatch):
    mod = _ml()

    def fake_status(ref):
        ref._obj.ullTotalPhys = 12 * GB
        return 1

    fake = SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=fake_status))
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert mod._read_installed_bytes() == 12 * GB
    failing = SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=lambda ref: 0))
    monkeypatch.setattr(ctypes, "windll", failing, raising=False)
    with pytest.raises(OSError):
        mod._read_installed_bytes()
    assert mod.installed_memory() == (4 * GB, True)


def test_this_machine_reports_something_sensible():
    value, assumed = _ml().installed_memory()
    assert value >= 256 * MB and isinstance(assumed, bool)


def test_the_default_config_says_auto_and_no_longer_1536():
    assert viewer_config.default_viewer_config()["cache"]["memory_limit_mb"] == "auto"


# ---- 8/7: the controller ---------------------------------------------------------------------

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
    monkeypatch.setattr(_ml(), "installed_memory", lambda: installed)
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


def test_request_carries_the_automatic_limit(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(8 * GB, False))
    ctrl._request_viewer_volume()
    assert _last_request().memory_limit_bytes == int(8 * GB * 0.16)


def test_request_carries_the_number_from_an_old_config(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, cache={"memory_limit_mb": 1536}, installed=(64 * GB, False))
    ctrl._request_viewer_volume()
    assert _last_request().memory_limit_bytes == 1536 * MB


def test_request_zero_means_never_ask(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, cache={"memory_limit_mb": 0})
    ctrl._request_viewer_volume()
    assert _last_request().memory_limit_bytes == 0


def test_refresh_reads_the_limit_again(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(8 * GB, False))
    cfg = viewer_config.default_viewer_config()
    cfg["cache"]["memory_limit_mb"] = 700
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    ctrl._apply_memory_config(cfg)
    ctrl._request_viewer_volume()
    assert _last_request().memory_limit_bytes == 700 * MB


def _size_notice(job_id, estimated=3 * GB, limit=1 * GB, held=0):
    return LoadVolumeResult(
        job_id=job_id, shm_name=None, shape=(), dtype="", needs_confirm=True,
        estimated_bytes=estimated, limit_bytes=limit, held_bytes=held,
    )


def test_the_notice_shows_the_automatic_value_and_its_basis(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path, installed=(8 * GB, False))
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(_size_notice(_last_request().job_id, 3 * GB, int(8 * GB * 0.16)))
    est, lim, message = ctrl._view.calls[0]
    assert est == 3 * 1024.0 and lim == pytest.approx(8 * 1024 * 0.16)
    assert "16 %" in message and "8,192 MB" in message and "automatic" in message
    assert "viewer.cache.memory_limit_mb" in message  # how to change it
    assert "Continue" in message  # a warning with a choice, not a stop


def test_the_notice_names_the_floor_the_assumption_and_the_config(monkeypatch, tmp_path):
    small = _controller(monkeypatch, tmp_path, installed=(2 * GB, False))
    small._request_viewer_volume()
    small._on_volume_result(_size_notice(_last_request().job_id, 3 * GB, 512 * MB))
    assert "512 MB" in small._view.calls[0][2] and "minimum" in small._view.calls[0][2]

    unknown = _controller(monkeypatch, tmp_path, installed=(4 * GB, True))
    unknown._request_viewer_volume()
    unknown._on_volume_result(_size_notice(_last_request().job_id, 3 * GB, int(4 * GB * 0.16)))
    assert "could not be read" in unknown._view.calls[0][2] and "4,096 MB" in unknown._view.calls[0][2]

    fixed = _controller(monkeypatch, tmp_path, cache={"memory_limit_mb": 1536})
    fixed._request_viewer_volume()
    fixed._on_volume_result(_size_notice(_last_request().job_id, 3 * GB, 1536 * MB))
    text = fixed._view.calls[0][2]
    assert "1,536 MB" in text and "viewer.cache.memory_limit_mb" in text and "automatic" not in text


def test_continue_loads_and_cancel_does_not(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path)
    ctrl._view = _View(answer=True)
    ctrl._request_viewer_volume()
    before = len(_submitted)
    ctrl._on_volume_result(_size_notice(_last_request().job_id))
    assert len(_submitted) == before + 1 and _last_request().memory_confirmed is True
    stop = _controller(monkeypatch, tmp_path)
    stop._request_viewer_volume()
    before = len(_submitted)
    stop._on_volume_result(_size_notice(_last_request().job_id))
    assert len(_submitted) == before and "cancelled" in stop._view.status[-1]


def test_a_view_that_does_not_know_the_message_argument_still_works(monkeypatch, tmp_path):
    ctrl = _controller(monkeypatch, tmp_path)
    asked = []
    ctrl._view = SimpleNamespace(
        confirm_large_load=lambda est, lim: asked.append((est, lim)) or False, set_status=lambda text: None
    )
    ctrl._request_viewer_volume()
    ctrl._on_volume_result(_size_notice(_last_request().job_id))
    assert len(asked) == 1


def test_the_window_shows_the_given_message(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        main_window.messagebox, "askyesno", lambda title, text, **k: seen.update(title=title, text=text) or True
    )
    win = SimpleNamespace(winfo_toplevel=lambda: None)
    assert main_window.MainWindow.confirm_large_load(win, 3000.0, 1000.0, message="THE REASON") is True
    assert "THE REASON" in seen["text"]
    main_window.MainWindow.confirm_large_load(win, 3000.0, 1000.0)  # old call still works
    assert "3,000 MB" in seen["text"]
