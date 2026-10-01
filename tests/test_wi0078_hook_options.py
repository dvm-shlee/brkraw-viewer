"""WI-0078: the converter-hook options button opens one window, and a changed hook option reaches
the reloaded result.

Synthetic data only. No Tk display is needed: the dialog module gets a fake ``tk``/``ttk``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest
from brkraw_viewer.app.workers.shm import read_shared_array, release_shared_array
from brkraw_viewer.ui.tabs.convert.window import ConvertTab
from brkraw_viewer.ui.tabs.viewer.top_panel import ViewerTopPanel
from brkraw_viewer.ui.windows import hook_options


# ---- fake Tk -------------------------------------------------------------------------------


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FakeTk:
    """Counts the Toplevel windows that were created; ``destroy`` makes ``winfo_exists`` False."""

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


@pytest.fixture
def fake_tk(monkeypatch):
    tk = _FakeTk()
    ttk = MagicMock(name="ttk")
    monkeypatch.setattr(hook_options, "tk", tk)
    monkeypatch.setattr(hook_options, "ttk", ttk)

    def _fn(scan, reco_id=None, alpha=1, beta="x", **kwargs):  # preset: alpha, beta
        return None

    monkeypatch.setattr(hook_options.converter_core, "resolve_hook", lambda name: {"get_dataobj": _fn})
    return tk


def _top_panel(hook_name="sordino", hook_args=None):
    panel = SimpleNamespace(
        _hook_name_var=_Var(hook_name),
        _hook_args=hook_args,
    )
    return panel


def _convert_tab(hook_name="sordino", hook_args=None):
    return SimpleNamespace(
        frame=object(),
        _hook_name_var=_Var(hook_name),
        _hook_args=hook_args,
        _hook_options_dialog=None,
        _cb=SimpleNamespace(),
    )


# ---- 1. one window per button -------------------------------------------------------------


def test_viewer_hook_options_button_pressed_twice_opens_one_window(fake_tk):
    panel = _top_panel()
    callbacks = SimpleNamespace()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    ViewerTopPanel._open_hook_options(panel, callbacks)
    ViewerTopPanel._open_hook_options(panel, callbacks)
    assert len(fake_tk.windows) == 1
    # the existing window is brought forward each time
    assert fake_tk.windows[0].lift.call_count == 3


def test_convert_hook_options_button_pressed_twice_opens_one_window(fake_tk):
    tab = _convert_tab()
    ConvertTab._open_hook_options(tab)
    ConvertTab._open_hook_options(tab)
    assert len(fake_tk.windows) == 1


def test_closed_window_is_reopened_not_left_hidden(fake_tk):
    panel = _top_panel()
    callbacks = SimpleNamespace()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    fake_tk.windows[0].destroy()  # the user closed it with the window button
    ViewerTopPanel._open_hook_options(panel, callbacks)
    assert len(fake_tk.windows) == 2
    assert fake_tk.windows[1].alive


def test_withdrawn_window_is_shown_again_not_duplicated(fake_tk):
    panel = _top_panel()
    callbacks = SimpleNamespace()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    panel._hook_options_dialog._close()  # the Close button withdraws the window
    fake_tk.windows[0].deiconify.reset_mock()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    assert len(fake_tk.windows) == 1
    fake_tk.windows[0].deiconify.assert_called()


def test_options_window_shows_the_applied_values_when_pressed_again(fake_tk):
    panel = _top_panel(hook_args={"alpha": 5})
    callbacks = SimpleNamespace()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    dialog = panel._hook_options_dialog
    assert dialog._vars["alpha"].get() == "5"
    dialog._vars["alpha"].set("77")  # typed but not applied
    panel._hook_args = {"alpha": 9}  # the controller applied 9 meanwhile
    ViewerTopPanel._open_hook_options(panel, callbacks)
    assert panel._hook_options_dialog is dialog
    assert dialog._vars["alpha"].get() == "9"


def test_options_window_for_another_hook_is_rebuilt_with_that_hook(fake_tk, monkeypatch):
    panel = _top_panel()
    callbacks = SimpleNamespace()
    ViewerTopPanel._open_hook_options(panel, callbacks)
    panel._hook_name_var.set("other")
    ViewerTopPanel._open_hook_options(panel, callbacks)
    assert len(fake_tk.windows) == 1
    assert panel._hook_options_dialog._hook_name == "other"


def test_apply_sends_the_current_hook_name_and_values(fake_tk):
    panel = _top_panel(hook_args={"alpha": 2})
    got = []
    callbacks = SimpleNamespace(on_hook_options_apply=lambda name, values: got.append((name, values)))
    ViewerTopPanel._open_hook_options(panel, callbacks)
    panel._hook_options_dialog._vars["alpha"].set("4")
    panel._hook_options_dialog._apply()
    assert got == [("sordino", {"alpha": 4, "beta": "x"})]


# ---- 2. the controller: Apply reloads the volume with the new options ------------------------

MB = 1024 * 1024
_submitted: list = []


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(viewer_module.Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    _submitted.clear()
    ctrl._worker = SimpleNamespace(submit=lambda req: _submitted.append(req), log_queue=None)
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 4
    ctrl.state.dataset.selected_reco_id = 1
    ctrl._resolve_cycle_frames = lambda: 10
    ctrl._viewer_hook_name = "sordino"
    return ctrl


def _load_requests():
    return [r for r in _submitted if isinstance(r, LoadVolumeRequest)]


def test_apply_with_hook_on_reloads_with_the_new_options(controller):
    controller._viewer_hook_enabled = True
    controller.on_hook_options_apply("sordino", {"ignore_samples": 2})
    controller.on_hook_options_apply("sordino", {"ignore_samples": 3})
    reqs = _load_requests()
    assert [r.hook_args for r in reqs] == [{"ignore_samples": 2}, {"ignore_samples": 3}]
    assert all(r.hook_name == "sordino" for r in reqs)
    assert all(r.frame_start is None and r.frame_count is None for r in reqs)
    assert reqs[0].job_id != reqs[1].job_id


def test_apply_with_hook_off_stores_the_options_for_later(controller):
    controller._viewer_hook_enabled = False
    controller.on_hook_options_apply("sordino", {"ignore_samples": 2})
    assert _load_requests() == []
    assert controller._viewer_hook_args == {"ignore_samples": 2}
    controller.on_viewer_hook_toggle(True, "sordino")  # switched on afterwards: reloads with them
    # (resolve_hook is the real one; an unknown name leaves the hook off, so only check the args kept)
    assert controller._viewer_hook_args == {"ignore_samples": 2}


def test_reloaded_result_replaces_the_shown_volume(controller):
    controller._viewer_hook_enabled = True
    controller._frame_cache[0] = {"volume": "stale"}  # a frame cached before the hook was on
    first = np.full((2, 2, 2, 3), 1.0)
    second = np.full((2, 2, 2, 3), 2.0)
    shown = []
    controller._render_viewer_views = lambda *a, **k: shown.append(np.array(controller._viewer_volume))
    controller._reorient_viewer_volume = lambda: controller._viewer_raw_volume
    for value, arr in ((1, first), (2, second)):
        controller.on_hook_options_apply("sordino", {"offset": value})
        req = _load_requests()[-1]
        from brkraw_viewer.app.workers.shm import create_shared_array
        from brkraw_viewer.app.workers.protocol import LoadVolumeResult

        name = create_shared_array(arr)
        controller._on_volume_result(
            LoadVolumeResult(job_id=req.job_id, shm_name=name, shape=arr.shape, dtype=str(arr.dtype), frames=3)
        )
    assert [float(v.mean()) for v in shown] == [1.0, 2.0]
    assert controller._frame_cache == {}


def test_result_of_an_older_apply_is_dropped(controller):
    controller._viewer_hook_enabled = True
    controller.on_hook_options_apply("sordino", {"offset": 1})
    controller.on_hook_options_apply("sordino", {"offset": 2})
    old, _new = _load_requests()
    from brkraw_viewer.app.workers.shm import create_shared_array
    from brkraw_viewer.app.workers.protocol import LoadVolumeResult

    arr = np.ones((2, 2, 2, 3))
    controller._render_viewer_views = lambda *a, **k: pytest.fail("an old result must not be drawn")
    controller._on_volume_result(
        LoadVolumeResult(job_id=old.job_id, shm_name=create_shared_array(arr), shape=arr.shape, dtype="float64", frames=3)
    )


# ---- 3. the Convert tab's applied options are not lost on its own checkbox -----------------------


def test_convert_options_survive_the_convert_hook_checkbox(controller):
    shown = []
    controller._view = SimpleNamespace(
        set_convert_hook_state=lambda name, enabled, args: shown.append((name, enabled, args)),
        set_viewer_hook_state=lambda *a, **k: None,  # WI-0088: a Convert Apply also updates the Viewer tab
    )
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    controller.on_convert_hook_toggle(False)
    controller.on_convert_hook_toggle(True)
    assert shown[-1] == ("sordino", True, {"ignore_samples": 4})


# ---- 4. the worker passes the options to the hook and the result follows them ------------------


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _OptionScan:
    """get_dataobj like a hook: the returned values depend on the options it is given."""

    image_info = {1: {"num_cycles": 4, "dataobj": None}}

    def __init__(self):
        self.calls = []
        self.avail = {1: SimpleNamespace(file_visu_pars={})}

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append(dict(kwargs))
        offset = float(kwargs.get("offset", 0))
        return np.stack([np.full((2, 2, 2), offset + k, dtype=np.float32) for k in range(4)], axis=-1)


@pytest.fixture
def worker_env(monkeypatch):
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()
    scan = _OptionScan()
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda s, r: 3)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda s, **kw: np.eye(4))
    yield scan
    convert_worker._meta_cache.clear()
    convert_worker._held_recos.clear()


def _worker_load(hook_args):
    out = _Queue()
    req = LoadVolumeRequest(
        job_id="j", path="p", scan_id=1, reco_id=1, frame_start=None, frame_count=None,
        hook_name="sordino", hook_args=hook_args,
    )
    convert_worker._process_load_volume(req, out)
    result = out.items[0]
    assert result.error is None
    arr, shm = read_shared_array(result.shm_name, result.shape, result.dtype)
    data = arr.copy()
    shm.close()
    release_shared_array(result.shm_name)
    return data


def test_changed_option_reaches_the_hook_and_changes_the_result(worker_env):
    a = _worker_load({"offset": 0})
    b = _worker_load({"offset": 100})
    c = _worker_load({"offset": 0})
    assert [call["offset"] for call in worker_env.calls] == [0, 100, 0]
    assert float(a.mean()) != float(b.mean())
    assert np.array_equal(a, c)
