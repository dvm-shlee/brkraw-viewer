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


# ---- 4. worker: already loaded means this hook and these options -----------------------------


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _HeldScan:
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
        self.reads = 0

    def get_dataobj(self, reco_id, **kwargs):
        info = self.image_info[reco_id]
        if info.get("dataobj") is None:
            self.reads += 1
            self.image_info[reco_id] = dict(info, dataobj=np.ones(self.shape, dtype=np.float32))
        return self.image_info[reco_id]["dataobj"]


@pytest.fixture
def held_env(monkeypatch):
    scan = _HeldScan()  # 0.125 MB
    monkeypatch.setattr(convert_worker, "_get_loader", lambda path: object())
    monkeypatch.setattr(convert_worker, "_ensure_hook_state", lambda loader, sid, enable_hook: scan)
    monkeypatch.setattr(convert_worker, "_frame_axis_number", lambda _s, _r: None)
    monkeypatch.setattr(convert_worker, "_resolve_affine_for_space", lambda _s, **k: np.eye(4))
    convert_worker._held_recos.clear()
    convert_worker._held_scans.clear()
    convert_worker._meta_cache.clear()
    yield scan
    convert_worker._held_recos.clear()
    convert_worker._held_scans.clear()
    convert_worker._meta_cache.clear()


def _hook_module(monkeypatch, scan, sizes):
    """A hook whose reported output size follows ``sizes[ignore_samples]`` (bytes)."""
    module = types.ModuleType("fake_wi0104_hook")

    def get_dataobj(scan_, reco_id=None, **kwargs):
        return np.zeros((2, 2, 2), np.float32)

    def get_dataobj_info(scan_, reco_id=None, **kwargs):
        return {"nbytes": sizes[kwargs.get("ignore_samples", 0)]}

    get_dataobj.__module__ = module.__name__
    module.get_dataobj = get_dataobj
    module.get_dataobj_info = get_dataobj_info
    monkeypatch.setitem(sys.modules, module.__name__, module)
    scan._converter_hook = {"get_dataobj": get_dataobj}


def _load(job, **kwargs):
    out = _Queue()
    convert_worker._process_load_volume(LoadVolumeRequest(job_id=job, path="p", scan_id=1, reco_id=1, **kwargs), out)
    result = out.items[0]
    if result.shm_name:
        release_shared_array(result.shm_name)
    return result


def test_raw_data_already_held_does_not_hide_a_big_hook_result(held_env, monkeypatch):
    _hook_module(monkeypatch, held_env, {0: 5 * MB})
    first = _load("raw", memory_limit_bytes=4 * MB)  # 0.125 MB: fits, and now it is held
    assert not first.needs_confirm and ("p", 1, 1) in convert_worker._held_recos
    hooked = _load("hooked", memory_limit_bytes=4 * MB, hook_name="fake_wi0104", hook_args={"ignore_samples": 0})
    assert hooked.needs_confirm and hooked.estimated_bytes == 5 * MB


def test_a_loaded_hook_result_does_not_hide_a_bigger_one_for_other_options(held_env, monkeypatch):
    _hook_module(monkeypatch, held_env, {0: MB // 8, 1: 9 * MB})
    small = _load("small", memory_limit_bytes=4 * MB, hook_name="fake_wi0104", hook_args={"ignore_samples": 0})
    assert not small.needs_confirm
    big = _load("big", memory_limit_bytes=4 * MB, hook_name="fake_wi0104", hook_args={"ignore_samples": 1})
    assert big.needs_confirm and big.estimated_bytes == 9 * MB


def test_the_same_request_again_is_not_asked_again(held_env, monkeypatch):
    _hook_module(monkeypatch, held_env, {0: MB // 8})
    same = {"hook_name": "fake_wi0104", "hook_args": {"ignore_samples": 0}}
    assert not _load("a", memory_limit_bytes=MB, **same).needs_confirm  # fits, now loaded
    for job in ("b", "c"):  # e.g. later frames of the same reco and hook
        assert not _load(job, memory_limit_bytes=1, **same).needs_confirm
    assert not _load("raw1", memory_limit_bytes=MB).needs_confirm  # a different request, small enough
    assert not _load("raw2", memory_limit_bytes=1).needs_confirm  # now held as raw: same request, no ask


def test_timecourse_reading_the_plain_data_is_remembered_next_to_the_hook_result(held_env, monkeypatch):
    from brkraw_viewer.app.workers.protocol import TimecourseRequest

    shape = (8, 8, 4, 4)
    held_env.shape = shape
    held_env.avail[1].file_visu_pars["VisuCoreSize"] = [int(np.prod(shape))]
    _hook_module(monkeypatch, held_env, {0: MB // 8})
    same = {"hook_name": "fake_wi0104", "hook_args": {"ignore_samples": 0}}
    assert not _load("hooked", memory_limit_bytes=MB, **same).needs_confirm
    out = _Queue()
    convert_worker._process_timecourse(TimecourseRequest(job_id="tc", path="p", scan_id=1, reco_id=1), out)
    assert out.items[0].error is None  # it read the plain data and holds it too
    # both are now loaded: neither the plain request nor the hook request is asked again
    assert not _load("raw", memory_limit_bytes=1).needs_confirm
    assert not _load("hooked2", memory_limit_bytes=1, **same).needs_confirm


def test_released_reco_is_checked_again(held_env, monkeypatch):
    _load("raw", memory_limit_bytes=MB)
    convert_worker._release_reco(("p", 1, 1))
    asked = _load("raw2", memory_limit_bytes=1)
    assert asked.needs_confirm


# ---- 5. Addons: general editor and rule-section editor of one file ----------------------------


@pytest.fixture
def addons(monkeypatch):
    tk = _FakeTk()
    box = MagicMock(name="messagebox")
    monkeypatch.setattr(addons_window, "tk", tk)
    monkeypatch.setattr(addons_window, "ttk", MagicMock(name="ttk"))
    monkeypatch.setattr(addons_window, "messagebox", box)
    tab = AddonsTab.__new__(AddonsTab)
    tab.frame = MagicMock(name="frame")
    tab._editor_windows = {}
    tab._bind_text_shortcuts = lambda text: None
    tab.refresh_installed = lambda: None
    tab._yaml_rt = lambda: MagicMock()
    tab.tk, tab.box = tk, box
    return tab


def _rule(tmp_path, name="rule.yaml"):
    path = tmp_path / name
    path.write_text("info_spec: []\n", encoding="utf-8")
    return path


def test_rule_section_editor_is_refused_while_the_general_editor_is_open(addons, tmp_path):
    path = _rule(tmp_path)
    addons._open_text_editor(path=path, title="Edit rule")
    general = addons.tk.windows[0]
    addons._open_rule_section_editor(path=path, category="info_spec")
    assert len(addons.tk.windows) == 1
    assert general.lift.called  # the open one comes forward
    assert addons.box.showinfo.called and "close" in addons.box.showinfo.call_args[0][1].lower()


def test_general_editor_is_refused_while_a_rule_section_editor_is_open(addons, tmp_path):
    path = _rule(tmp_path)
    addons._open_rule_section_editor(path=path, category="info_spec")
    section = addons.tk.windows[0]
    addons._open_text_editor(path=path, title="Edit rule")
    assert len(addons.tk.windows) == 1
    assert section.lift.called
    assert addons.box.showinfo.called


def test_the_other_editor_opens_once_the_first_is_closed(addons, tmp_path):
    path = _rule(tmp_path)
    addons._open_text_editor(path=path, title="Edit rule")
    addons.tk.windows[0].destroy()
    addons._open_rule_section_editor(path=path, category="info_spec")
    assert len(addons.tk.windows) == 2 and not addons.box.showinfo.called


def test_two_categories_of_one_file_and_other_files_stay_independent(addons, tmp_path):
    path, other = _rule(tmp_path), _rule(tmp_path, "other.yaml")
    addons._open_rule_section_editor(path=path, category="info_spec")
    addons._open_rule_section_editor(path=path, category="metadata_spec")
    addons._open_text_editor(path=other, title="Edit rule")
    assert len(addons.tk.windows) == 3
    assert not addons.box.showinfo.called


# ---- 6. an open Hook Options window follows an Apply made in the other tab --------------------


def _vars(panel):
    return {k: v.get() for k, v in panel._hook_options_dialog._vars.items()}


def test_viewer_options_window_shows_what_the_convert_tab_applied(fake_tk):
    panel = _panel(hook_args={"alpha": 5})
    ViewerTopPanel._open_hook_options(panel, SimpleNamespace())
    assert _vars(panel)["alpha"] == "5"
    ViewerTopPanel.set_hook_args(panel, {"alpha": 8, "beta": "y"})  # the controller, after an Apply elsewhere
    assert _vars(panel) == {"alpha": "8", "beta": "y"}
    assert len(fake_tk.windows) == 1


def test_convert_options_window_shows_what_the_viewer_tab_applied(fake_tk):
    tab = _convert_tab(hook_args={"alpha": 5})
    ConvertTab._open_hook_options(tab)
    assert tab._hook_options_dialog._vars["alpha"].get() == "5"
    ConvertTab.set_hook_state(tab, "sordino", True, {"alpha": 11})
    assert tab._hook_options_dialog._vars["alpha"].get() == "11"
    assert len(fake_tk.windows) == 1


def test_apply_in_the_same_tab_does_not_rebuild_the_form(fake_tk):
    panel = _panel(hook_args={"alpha": 5})
    got = []
    callbacks = SimpleNamespace(on_hook_options_apply=lambda name, values: got.append(values))
    ViewerTopPanel._open_hook_options(panel, callbacks)
    dialog = panel._hook_options_dialog
    dialog._vars["alpha"].set("4")
    dialog._apply()
    var_before = dialog._vars["alpha"]
    ViewerTopPanel.set_hook_args(panel, got[-1])  # the controller echoes the applied values back
    assert dialog._vars["alpha"] is var_before  # nothing re-rendered, a typed value is not lost
    assert dialog._vars["alpha"].get() == "4"


def test_a_closed_options_window_is_not_reopened_by_a_refresh(fake_tk):
    panel = _panel(hook_args={"alpha": 5})
    ViewerTopPanel._open_hook_options(panel, SimpleNamespace())
    panel._hook_options_dialog._close()
    fake_tk.windows[0].deiconify.reset_mock()
    ViewerTopPanel.set_hook_args(panel, {"alpha": 8})
    assert not fake_tk.windows[0].deiconify.called
    ViewerTopPanel._open_hook_options(panel, SimpleNamespace())  # opened again: shows the new value
    assert _vars(panel)["alpha"] == "8"


def test_without_an_options_window_nothing_happens(fake_tk):
    panel = _panel(hook_args=None)
    ViewerTopPanel.set_hook_args(panel, {"alpha": 8})
    assert panel._hook_args == {"alpha": 8} and fake_tk.windows == []


def test_controller_apply_in_one_tab_reaches_the_other_tab_view(controller):
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    assert controller._view.viewer_args == {"ignore_samples": 4}
