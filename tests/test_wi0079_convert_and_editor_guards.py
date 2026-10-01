"""WI-0079: Convert refuses a repeated click while the same conversion is running, and the Addons
text editors open one window per target and show a failed Save.

Synthetic data only. No Tk display is needed: the Addons module gets a fake ``tk``/``ttk``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers.protocol import ConvertRequest, ConvertResult
from brkraw_viewer.ui.tabs.addons import window as addons_window
from brkraw_viewer.ui.tabs.addons.window import AddonsTab


# ---- 1. Convert: repeated click ---------------------------------------------------------------

_submitted: list = []


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(viewer_module.Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    _submitted.clear()
    ctrl._worker = SimpleNamespace(submit=lambda req: _submitted.append(req), log_queue=None)
    ctrl._view = MagicMock(name="view")
    ctrl.state.dataset.path = tmp_path / "study"
    ctrl.state.dataset.selected_scan_id = 4
    ctrl.state.dataset.selected_reco_id = 1
    ctrl.resolve_addon_spec = lambda category: None

    def _plan(**kwargs):
        return [str(tmp_path / "out" / f"scan{kwargs['scan_id']:03d}.nii.gz")]

    ctrl._plan_output_paths = _plan
    return ctrl


def _convert(ctrl, tmp_path):
    ctrl.on_convert_submit(
        output_dir=str(tmp_path / "out"),
        base_name="",
        space="scanner",
        subject_type=None,
        subject_pose=None,
        flip=(False, False, False),
        hook_enabled=False,
        hook_name="",
        hook_args=None,
        sidecar_enabled=False,
        sidecar_format="json",
    )


def _converts():
    return [r for r in _submitted if isinstance(r, ConvertRequest)]


def test_repeated_click_queues_the_same_conversion_once(controller, tmp_path):
    _convert(controller, tmp_path)
    _convert(controller, tmp_path)
    _convert(controller, tmp_path)
    assert len(_converts()) == 1


def test_repeated_click_tells_the_user(controller, tmp_path):
    _convert(controller, tmp_path)
    controller._view.reset_mock()
    _convert(controller, tmp_path)
    assert controller._view.notify_warning.called
    message = controller._view.notify_warning.call_args[0][1]
    assert "already" in message.lower()
    assert any("already" in str(c).lower() for c in controller._view.set_status.call_args_list)


def test_another_scan_is_not_blocked(controller, tmp_path):
    _convert(controller, tmp_path)
    controller.state.dataset.selected_scan_id = 5
    _convert(controller, tmp_path)
    assert [r.scan_id for r in _converts()] == [4, 5]


def test_same_scan_can_run_again_after_the_result(controller, tmp_path):
    _convert(controller, tmp_path)
    controller._on_convert_result(ConvertResult(job_id=_converts()[0].job_id, saved_paths=["a"]))
    _convert(controller, tmp_path)
    assert len(_converts()) == 2


def test_same_scan_can_run_again_after_a_failed_result(controller, tmp_path):
    _convert(controller, tmp_path)
    controller._on_convert_result(ConvertResult(job_id=_converts()[0].job_id, saved_paths=[], error="boom"))
    _convert(controller, tmp_path)
    assert len(_converts()) == 2


def test_worker_loop_error_without_job_id_frees_convert(controller, tmp_path):
    _convert(controller, tmp_path)
    controller._on_convert_result(ConvertResult(job_id="", saved_paths=[], error="Worker loop error: x"))
    _convert(controller, tmp_path)
    assert len(_converts()) == 2


def test_different_scan_with_the_same_output_file_is_refused(controller, tmp_path):
    controller._plan_output_paths = lambda **kwargs: [str(tmp_path / "out" / "same.nii.gz")]
    _convert(controller, tmp_path)
    controller.state.dataset.selected_scan_id = 5
    _convert(controller, tmp_path)
    assert len(_converts()) == 1


def test_a_dead_worker_does_not_leave_convert_blocked(controller, tmp_path):
    _convert(controller, tmp_path)
    controller._worker = SimpleNamespace(
        submit=lambda req: _submitted.append(req), log_queue=None, is_alive=lambda: False
    )
    _convert(controller, tmp_path)
    assert len(_converts()) == 2


# ---- 2. Addons text editors -------------------------------------------------------------------


class _FakeTk:
    END = "end"

    def __init__(self):
        self.windows = []

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


@pytest.fixture
def addons(monkeypatch):
    tk = _FakeTk()
    ttk = MagicMock(name="ttk")
    box = MagicMock(name="messagebox")
    monkeypatch.setattr(addons_window, "tk", tk)
    monkeypatch.setattr(addons_window, "ttk", ttk)
    monkeypatch.setattr(addons_window, "messagebox", box)
    tab = AddonsTab.__new__(AddonsTab)
    tab.frame = MagicMock(name="frame")
    tab._editor_windows = {}
    tab._bind_text_shortcuts = lambda text: None
    tab.refresh_installed = lambda: None
    tab.tk, tab.ttk, tab.box = tk, ttk, box
    return tab


def _save_command(tab):
    return tab.ttk.Button.call_args_list[-1].kwargs["command"]


def test_text_editor_for_the_same_file_opens_one_window(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    addons._open_text_editor(path=path, title="Edit rule")
    addons._open_text_editor(path=path, title="Edit rule")
    addons._open_text_editor(path=path, title="Edit rule")
    assert len(addons.tk.windows) == 1


def test_pressing_again_brings_the_existing_window_forward(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    addons._open_text_editor(path=path, title="Edit rule")
    win = addons.tk.windows[0]
    addons._open_text_editor(path=path, title="Edit rule")
    assert win.lift.called


def test_text_editor_for_another_file_gets_its_own_window(addons, tmp_path):
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("a: 1\n", encoding="utf-8")
    b.write_text("b: 1\n", encoding="utf-8")
    addons._open_text_editor(path=a, title="Edit rule")
    addons._open_text_editor(path=b, title="Edit rule")
    assert len(addons.tk.windows) == 2


def test_closed_text_editor_can_be_opened_again(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    addons._open_text_editor(path=path, title="Edit rule")
    addons.tk.windows[0].destroy()
    addons._open_text_editor(path=path, title="Edit rule")
    assert len(addons.tk.windows) == 2


def test_same_path_spelled_differently_is_one_target(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    addons._open_text_editor(path=path, title="Edit rule")
    addons._open_text_editor(path=tmp_path / "sub" / ".." / "rule.yaml", title="Edit rule")
    assert len(addons.tk.windows) == 1


def test_rule_section_editor_opens_one_window_per_file_and_category(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("info_spec: []\n", encoding="utf-8")
    addons._yaml_rt = lambda: MagicMock()
    addons._open_rule_section_editor(path=path, category="info_spec")
    addons._open_rule_section_editor(path=path, category="info_spec")
    assert len(addons.tk.windows) == 1
    addons._open_rule_section_editor(path=path, category="metadata_spec")
    assert len(addons.tk.windows) == 2


def test_failed_save_is_shown_to_the_user(addons, tmp_path):
    path = tmp_path / "missing_folder" / "rule.yaml"  # the folder does not exist: write fails
    addons._open_text_editor(path=path, title="Edit rule")
    _save_command(addons)()
    assert addons.box.showerror.called
    assert "save" in addons.box.showerror.call_args[0][1].lower()


def test_save_writes_the_file(addons, tmp_path):
    path = tmp_path / "rule.yaml"
    path.write_text("a: 1\n", encoding="utf-8")
    addons._open_text_editor(path=path, title="Edit rule")
    _save_command(addons)()
    assert path.read_text(encoding="utf-8") == "key: value\n"
    assert not addons.box.showerror.called
