"""WI-0088: hook options are kept once per hook name and both tabs show and use the same values.

Applying in the Convert tab used to reach only the Convert tab; the Viewer tab (its Hook Options window
and the shown result) kept the older options. Synthetic only, no Tk display.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest

_submitted: list = []


class _Tabs:
    """Stands in for MainWindow: what each tab's panel/tab object holds, as set_*_hook_state would store it."""

    def __init__(self):
        self.viewer_args = None
        self.convert_args = None
        self.convert_enabled = None

    def set_viewer_hook_state(self, hook_name, enabled, hook_args, *, allow_toggle=True):
        self.viewer_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def set_convert_hook_state(self, hook_name, enabled, hook_args):
        self.convert_enabled = enabled
        self.convert_args = dict(hook_args) if isinstance(hook_args, dict) else None

    def __getattr__(self, name):  # status line, progress and other view calls: not under test
        return lambda *a, **k: None


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
    ctrl._view = _Tabs()
    return ctrl


def _loads():
    return [r for r in _submitted if isinstance(r, LoadVolumeRequest)]


# ---- A. Convert tab Apply -> Viewer tab ---------------------------------------------------


def test_convert_apply_reaches_the_viewer_tab_options(controller):
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    assert controller._view.viewer_args == {"ignore_samples": 4}  # the Viewer tab's Hook Options window
    assert controller._viewer_hook_args == {"ignore_samples": 4}  # what the Viewer would load with
    assert controller._view.convert_args == {"ignore_samples": 4}


def test_convert_apply_with_viewer_hook_on_reloads_the_shown_result(controller):
    controller._viewer_hook_enabled = True
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    reqs = _loads()
    assert [r.hook_args for r in reqs] == [{"ignore_samples": 4}]
    assert reqs[0].hook_name == "sordino"


def test_convert_apply_with_viewer_hook_off_only_stores(controller):
    controller._viewer_hook_enabled = False
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    assert _loads() == []
    assert controller._viewer_hook_args == {"ignore_samples": 4}


def test_convert_apply_for_another_hook_name_does_not_touch_the_viewer_hook(controller):
    controller.on_convert_hook_options_apply("other", {"x": 1})
    assert controller._viewer_hook_args is None
    assert controller._view.viewer_args is None
    assert controller._hook_args_by_name["other"] == {"x": 1}


# ---- B. Viewer tab Apply -> Convert tab ---------------------------------------------------


def test_viewer_apply_reaches_the_convert_tab_options(controller):
    controller.on_hook_options_apply("sordino", {"ignore_samples": 2})
    assert controller._view.convert_args == {"ignore_samples": 2}
    assert controller._view.viewer_args == {"ignore_samples": 2}


def test_alternating_applies_keep_one_latest_value_in_both_tabs(controller):
    controller.on_hook_options_apply("sordino", {"ignore_samples": 2})
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 5})
    assert controller._view.viewer_args == controller._view.convert_args == {"ignore_samples": 5}
    controller.on_hook_options_apply("sordino", {"ignore_samples": 7})
    assert controller._view.viewer_args == controller._view.convert_args == {"ignore_samples": 7}


def test_viewer_hook_switched_on_after_a_convert_apply_uses_the_new_options(controller):
    controller.on_convert_hook_options_apply("sordino", {"ignore_samples": 4})
    assert controller._viewer_hook_args == {"ignore_samples": 4}
