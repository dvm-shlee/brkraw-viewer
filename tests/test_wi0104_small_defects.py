"""WI-0104: six small viewer defects from the waiting list.

1. Task progress window: asking for it again must not orphan the open one.
2. Hook Options: say why nothing opens instead of returning silently.
3. Large-data "No": a declined load must not block a later, different request (hook on, other options).
4. Worker: "already loaded" must also depend on the hook and its options.
5. Addons: the general text editor and a rule-section editor of the same file are not open together.
6. An open Hook Options window follows an Apply made in the other tab.

Synthetic data only. No Tk display: fake ``tk``/``ttk``/``messagebox`` modules.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult
from brkraw_viewer.app.workers.shm import release_shared_array
from brkraw_viewer.ui.main import window as main_window
from brkraw_viewer.ui.tabs.addons import window as addons_window
from brkraw_viewer.ui.tabs.addons.window import AddonsTab
from brkraw_viewer.ui.tabs.convert.window import ConvertTab
from brkraw_viewer.ui.tabs.viewer.top_panel import ViewerTopPanel
from brkraw_viewer.ui.windows import hook_options

MB = 1024 * 1024


# ---- fake Tk ---------------------------------------------------------------------------------


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FakeTk:
    END = "end"

    def __init__(self):
        self.windows = []
        self.StringVar = _Var
        self.Misc = object
        self.Widget = object

    def Toplevel(self, parent=None):
        win = MagicMock(name="Toplevel")
        win.alive = True
        win.winfo_exists.side_effect = lambda: win.alive
        win.destroy.side_effect = lambda: setattr(win, "alive", False)
        self.windows.append(win)
        return win

    def Text(self, *args, **kwargs):
        text = MagicMock(name="Text")
        text.get.return_value = "key: value\n"
        return text


# ---- 1. task progress window -----------------------------------------------------------------


def _main_window(monkeypatch):
    created = []

    def _make(parent, log_queue, title="Task Progress"):
        win = MagicMock(name="TaskProgressWindow")
        win.alive = True
        win.winfo_exists.side_effect = lambda: win.alive
        win.destroy.side_effect = lambda: setattr(win, "alive", False)
        created.append(win)
        return win

    monkeypatch.setattr(main_window, "TaskProgressWindow", _make)
    mw = main_window.MainWindow.__new__(main_window.MainWindow)
    mw._task_window = None
    mw.winfo_toplevel = lambda: "top"
    return mw, created


def test_progress_window_asked_twice_keeps_one_window_and_the_handle(monkeypatch):
    mw, created = _main_window(monkeypatch)
    first = mw.open_worker_popup("queue", "Task")
    second = mw.open_worker_popup("queue", "Task")
    assert len(created) == 1
    assert second is first  # the controller finishes the window it was given; no orphan
    assert mw._task_window is first
    assert first.lift.called


def test_progress_window_is_created_again_after_it_was_closed(monkeypatch):
    mw, created = _main_window(monkeypatch)
    first = mw.open_worker_popup("queue", "Task")
    first.destroy()
    second = mw.open_worker_popup("queue", "Task")
    assert len(created) == 2
    assert second is created[1] and mw._task_window is second


# ---- 2. Hook Options says why it does not open ------------------------------------------------


@pytest.fixture
def fake_tk(monkeypatch):
    tk = _FakeTk()
    monkeypatch.setattr(hook_options, "tk", tk)
    monkeypatch.setattr(hook_options, "ttk", MagicMock(name="ttk"))
    box = MagicMock(name="messagebox")
    monkeypatch.setattr(hook_options, "messagebox", box)
    tk.box = box

    def _fn(scan, reco_id=None, alpha=1, beta="x", **kwargs):  # preset: alpha, beta
        return None

    monkeypatch.setattr(hook_options.converter_core, "resolve_hook", lambda name: {"get_dataobj": _fn})
    return tk


def _panel(hook_name="sordino", hook_args=None):
    return SimpleNamespace(_hook_name_var=_Var(hook_name), _hook_args=hook_args)


def _convert_tab(hook_name="sordino", hook_args=None):
    return SimpleNamespace(
        frame=object(),
        _hook_name_var=_Var(hook_name),
        _hook_args=hook_args,
        _hook_enabled_var=_Var(True),
        _hook_options_dialog=None,
        _cb=SimpleNamespace(),
    )


def _said(tk):
    assert tk.box.showinfo.called, "the user was told nothing"
    return tk.box.showinfo.call_args[0][1]


def test_hook_that_cannot_be_found_is_reported(fake_tk, monkeypatch):
    def _boom(name):
        raise KeyError(name)

    monkeypatch.setattr(hook_options.converter_core, "resolve_hook", _boom)
    ViewerTopPanel._open_hook_options(_panel(), SimpleNamespace())
    assert fake_tk.windows == []
    assert "sordino" in _said(fake_tk)


def test_hook_without_options_is_reported(fake_tk, monkeypatch):
    monkeypatch.setattr(hook_options.converter_core, "resolve_hook", lambda name: {"get_dataobj": lambda scan: None})
    ViewerTopPanel._open_hook_options(_panel(), SimpleNamespace())
    assert fake_tk.windows == []
    assert "no options" in _said(fake_tk).lower()


def test_scan_without_a_hook_is_reported_in_both_tabs(fake_tk):
    ViewerTopPanel._open_hook_options(_panel(hook_name="None"), SimpleNamespace())
    assert "no converter hook" in _said(fake_tk).lower()
    fake_tk.box.reset_mock()
    ConvertTab._open_hook_options(_convert_tab(hook_name=""))
    assert "no converter hook" in _said(fake_tk).lower()
    assert fake_tk.windows == []


def test_convert_tab_reports_a_missing_hook_too(fake_tk, monkeypatch):
    monkeypatch.setattr(hook_options.converter_core, "resolve_hook", lambda name: (_ for _ in ()).throw(KeyError(name)))
    ConvertTab._open_hook_options(_convert_tab())
    assert "sordino" in _said(fake_tk)


def test_a_working_hook_still_opens_without_a_message(fake_tk):
    ViewerTopPanel._open_hook_options(_panel(), SimpleNamespace())
    assert len(fake_tk.windows) == 1
    assert not fake_tk.box.showinfo.called


# ---- controller fixture (3, 6) -----------------------------------------------------------------

_submitted: list = []


class _View:
    def __init__(self, answer=False):
        self.answer = answer
        self.asked = []
        self.status = []
        self.viewer_args = None
        self.convert_args = None

    def confirm_large_load(self, estimated_mb, limit_mb):
        self.asked.append((estimated_mb, limit_mb))
        return self.answer

    def set_status(self, text):
        self.status.append(text)

    def set_viewer_hook_state(self, hook_name, enabled, hook_args, *, allow_toggle=True):
        self.viewer_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def set_convert_hook_state(self, hook_name, enabled, hook_args):
        self.convert_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(viewer_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    ctrl = ViewerController()
    _submitted.clear()
    ctrl._worker = SimpleNamespace(submit=lambda req: _submitted.append(req), log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 4
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: 10
    ctrl._viewer_hook_name = "sordino"
    ctrl._view = _View()
    return ctrl


def _loads():
    return [r for r in _submitted if isinstance(r, LoadVolumeRequest)]


def _needs_confirm(job_id, estimated=3 * MB, limit=1 * MB):
    return LoadVolumeResult(
        job_id=job_id, shm_name=None, shape=(), dtype="", needs_confirm=True, estimated_bytes=estimated, limit_bytes=limit
    )


# ---- 3. "No" to a large load does not block a different request ------------------------------


def test_no_to_the_raw_load_does_not_block_turning_the_hook_on(controller):
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # answer: No
    assert len(_loads()) == 1
    controller.on_viewer_hook_toggle(True, "sordino")
    assert len(_loads()) == 2 and _loads()[-1].hook_name == "sordino"


def test_no_to_a_hooked_load_does_not_block_other_options_or_the_raw_load(controller):
    controller._viewer_hook_enabled = True
    controller.on_hook_options_apply("sordino", {"ignore_samples": 2})
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # answer: No
    controller.on_hook_options_apply("sordino", {"ignore_samples": 3})  # other options: asked afresh
    assert [r.hook_args for r in _loads()] == [{"ignore_samples": 2}, {"ignore_samples": 3}]
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # No again
    controller.on_viewer_hook_toggle(False, "sordino")  # hook off: the plain load is another request
    assert _loads()[-1].hook_name is None


def test_turning_the_hook_off_and_on_again_asks_again_after_no(controller):
    controller._viewer_hook_enabled = True
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # No
    controller.on_viewer_hook_toggle(False, "sordino")
    controller.on_viewer_hook_toggle(True, "sordino")
    hooked = [r for r in _loads() if r.hook_name == "sordino"]
    assert len(hooked) == 2


def test_applying_the_same_options_again_asks_again_after_no(controller):
    controller._viewer_hook_enabled = True
    controller.on_hook_options_apply("sordino", {"a": 1})
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # No
    controller.on_hook_options_apply("sordino", {"a": 1})
    assert len(_loads()) == 2


def test_yes_to_the_raw_load_is_not_a_yes_to_the_hook_result(controller):
    controller._view = _View(answer=True)
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # Yes -> sent again as confirmed
    assert _loads()[-1].memory_confirmed is True
    controller.on_viewer_hook_toggle(True, "sordino")
    assert _loads()[-1].hook_name == "sordino"
    assert _loads()[-1].memory_confirmed is False


def test_the_same_request_repeated_by_itself_is_still_not_asked_again(controller):
    controller._request_viewer_volume()
    controller._on_volume_result(_needs_confirm(_loads()[-1].job_id))  # No
    controller._request_viewer_volume()  # e.g. the frame slider moved
    assert len(_loads()) == 1
    assert len(controller._view.asked) == 1


def test_worker_keep_list_is_still_the_reco_alone_not_the_hook(controller):
    controller._viewer_hook_enabled = True
    controller._request_viewer_volume()
    assert _loads()[-1].keep == ((str(controller.state.dataset.path), 4, 1),)
