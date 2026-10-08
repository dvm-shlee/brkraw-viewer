"""Tests of installed Viewer entry points and headless integration seams."""

from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

from brkraw_viewer.app.controller.dataset import DatasetController
from brkraw_viewer.app.services import hooks
from brkraw_viewer.app.state import AppState
from brkraw_viewer.app.services.worker_manager import WorkerManager
from brkraw_viewer.app.workers.protocol import ConvertResult, LoadVolumeResult


def test_viewer_cli_entry_points_load():
    entries = [
        ep for ep in metadata.distribution("brkraw-viewer").entry_points
        if ep.group == "brkraw.cli"
    ]
    assert {ep.name for ep in entries} == {"viewer", "viewer-registry"}
    assert all(callable(ep.load()) for ep in entries)


def test_viewer_hook_discovery_loads_class_and_isolates_broken_entry(monkeypatch):
    class GoodHook:
        name = "sample"

        def build_tab(self, parent, app):
            return None

    class Entry:
        def __init__(self, name, value=None, error=None):
            self.name = name
            self.value = value
            self.error = error

        def load(self):
            if self.error:
                raise self.error
            return self.value

    monkeypatch.setattr(
        hooks,
        "list_entry_points",
        lambda group: [Entry("bad", error=ImportError("missing")), Entry("good", GoodHook)],
    )
    loaded = hooks.load_viewer_hooks()
    assert len(loaded) == 1
    assert isinstance(loaded[0], GoodHook)


def test_dataset_open_and_close_clears_state(monkeypatch, tmp_path):
    class Loader:
        subject = {"ID": "synthetic"}
        avail = {1: {}}

        def __init__(self, path, disable_hook=False):
            assert path == tmp_path
            assert disable_hook is True

        def info(self, *, scope, as_dict):
            assert (scope, as_dict) == ("scan", True)
            return {1: {"Protocol": "Synthetic", "Method": "TEST", "Reco(s)": {}}}

    from brkraw_viewer.app.controller import dataset

    monkeypatch.setattr(dataset.brkapi, "BrukerLoader", Loader)
    controller = DatasetController()
    assert controller.open_dataset(Path(tmp_path)).scan_ids == [1]
    assert controller.scan_entries() == [(1, "E001 - Synthetic (TEST)")]
    controller.close_dataset()
    assert controller.summary is None
    assert controller.list_scans() == []


def test_worker_results_route_to_matching_callback():
    seen = []
    manager = WorkerManager.__new__(WorkerManager)
    manager._on_convert_result = lambda result: seen.append(("convert", result.job_id))
    manager._on_volume_result = lambda result: seen.append(("volume", result.job_id))
    manager._on_timecourse_cache_result = None
    manager._on_registry_result = None

    manager._handle_result(ConvertResult("c", []))
    manager._handle_result(LoadVolumeResult("v", None, (), "float32"))
    assert seen == [("convert", "c"), ("volume", "v")]


def test_volume_request_drops_hook_args_when_hook_disabled():
    from brkraw_viewer.app.controller.viewer import ViewerController

    submitted = []
    controller = ViewerController.__new__(ViewerController)
    controller.state = AppState()
    controller.state.dataset.path = Path("synthetic")
    controller.state.dataset.selected_scan_id = 1
    controller.state.dataset.selected_reco_id = 1
    controller._view = None
    controller._worker = SimpleNamespace(submit=submitted.append)
    controller._viewer_hook_name = "sample"
    controller._viewer_hook_args = {"k": 1}
    controller._viewer_slicepacks = 1
    controller._viewer_frames = 1
    controller._pending_frame_requests = {}
    controller._resolve_cycle_frames = lambda: 1
    # memory-notice state added by WI-0068 (this test skips __init__)
    controller._memory_limit_bytes = 0
    controller._peak_limit_bytes = 0  # WI-0104 item 7
    controller._memory_confirmed = set()
    controller._memory_declined = set()

    controller._viewer_hook_enabled = False
    controller._request_viewer_volume()
    controller._viewer_hook_enabled = True
    controller._request_viewer_volume()

    off, on = submitted
    assert (off.hook_name, off.hook_args) == (None, None)
    assert (on.hook_name, on.hook_args) == ("sample", {"k": 1})
