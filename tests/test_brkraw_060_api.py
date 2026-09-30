"""Synthetic tests for the brkraw 0.6 API calls the viewer uses (WI-0067, no Tk window, no real dataset)."""

from types import SimpleNamespace

import numpy as np
import pytest

from brkraw.core import layout as layout_core
from brkraw.specs.context_map.output import select_frames

from brkraw_viewer.app.controller import dataset
from brkraw_viewer.app.controller.dataset import DatasetController
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest

MAP_YAML = """\
__meta__:
  category: context_map
  layout_template: "sub-{bids.sub}[_ses-{bids.ses}]_run-{utils.counter}"
bids:
  sub: {from: Subject.ID}
"""


def _write_map(tmp_path):
    path = tmp_path / "study.yaml"
    path.write_text(MAP_YAML, encoding="utf-8")
    return str(path)


def _controller(monkeypatch):
    controller = DatasetController()
    controller._loader = object()
    monkeypatch.setattr(
        layout_core,
        "load_layout_info_parts",
        lambda loader, scan_id, **kw: ({"Subject": {"ID": "s01"}, "Study": {"ID": "7"}}, {}),
    )
    return controller


def test_remapper_load_spec_and_map_parameters_moved(monkeypatch, tmp_path):
    spec = tmp_path / "spec.yaml"
    spec.write_text("Out.k:\n  sources:\n    - {file: method, key: K}\n", encoding="utf-8")
    scan = SimpleNamespace(method={"K": 5})
    controller = DatasetController()
    controller.get_scan = lambda scan_id: scan
    monkeypatch.setattr(dataset.brkapi.info_resolver, "scan", lambda *a, **k: {"Base": 1})
    merged = controller.apply_addon_spec(1, 1, str(spec), "info_spec")
    assert merged == {"Base": 1, "Out": {"k": 5}}


def test_layout_info_adds_context_map_namespaces_and_keeps_originals(monkeypatch, tmp_path):
    controller = _controller(monkeypatch)
    info = controller.layout_info(1, 1, context_map=_write_map(tmp_path), info_spec=None, metadata_spec=None)
    assert info["Subject"] == {"ID": "s01"}
    assert info["bids"] == {"sub": "s01"}


def test_layout_info_without_context_map_has_no_namespace(monkeypatch):
    controller = _controller(monkeypatch)
    info = controller.layout_info(1, 1, context_map=None, info_spec=None, metadata_spec=None)
    assert "bids" not in info


def test_render_layout_passes_namespaces_as_extra(monkeypatch, tmp_path):
    controller = _controller(monkeypatch)
    seen = {}

    def fake_render(loader, scan_id, **kwargs):
        seen.update(kwargs)
        return "name"

    monkeypatch.setattr(layout_core, "render_layout", fake_render)
    out = controller.render_layout(
        1, 1, layout_entries=None, layout_template="{bids.sub}", context_map=_write_map(tmp_path)
    )
    assert out == "name"
    assert seen["extra"] == {"bids": {"sub": "s01"}}
    assert "context_map" not in seen


def test_render_layout_config_template_reads_namespace_tag(monkeypatch, tmp_path):
    controller = _controller(monkeypatch)
    out = controller.render_layout(
        1, 1, layout_entries=None, layout_template="x_{bids.sub}", context_map=_write_map(tmp_path)
    )
    assert out == "x_s01"


def test_render_layout_uses_context_map_template_groups(monkeypatch, tmp_path):
    controller = _controller(monkeypatch)
    path = _write_map(tmp_path)
    template = controller.context_map_meta(path)["layout_template"]
    out = controller.render_layout(1, 1, layout_entries=None, layout_template=template, context_map=path)
    assert out == "sub-s01_run-1"  # the [_ses-...] group drops out: bids.ses is not defined


def test_context_map_meta_is_empty_without_a_map():
    assert DatasetController.context_map_meta(None) == {}


def test_context_map_in_0_5_syntax_is_refused(monkeypatch, tmp_path):
    old = tmp_path / "old.yaml"
    old.write_text("Subject.ID:\n  type: mapping\n  values: {a: b}\n", encoding="utf-8")
    controller = _controller(monkeypatch)
    with pytest.raises(ValueError):
        controller.layout_info(1, 1, context_map=str(old), info_spec=None, metadata_spec=None)


class _FrameScan:
    """Synthetic scan: 4D data (x, y, z, cycle) sliced by brkraw's own select_frames."""

    def __init__(self, data, shape_desc):
        self.data = data
        self.shape_desc = shape_desc
        self.calls = []

    def get_dataobj(self, reco_id, axis=None, frames=None, **kwargs):
        self.calls.append({"axis": axis, "frames": frames, **kwargs})
        assert "cycle_index" not in kwargs and "cycle_count" not in kwargs
        out, _ = select_frames(self.data, self.shape_desc, axis, frames)
        return out


@pytest.fixture
def frame_env(monkeypatch):
    shape_desc = ["spatial", "spatial", "spatial", "cycle"]
    monkeypatch.setattr(convert_worker.brkapi.shape_resolver, "resolve", lambda scan, reco_id: {"shape_desc": shape_desc})
    monkeypatch.setattr(
        convert_worker.brkapi.image_resolver, "normalized_layout", lambda info: ([2, 2, 2, 5], shape_desc)
    )
    data = np.arange(2 * 2 * 2 * 5).reshape(2, 2, 2, 5)
    return _FrameScan(data, shape_desc), data


def test_read_frame_block_selects_one_cycle_and_keeps_the_axis(frame_env):
    scan, data = frame_env
    block = convert_worker._read_frame_block(scan, 1, 3, 1)
    assert block.shape == (2, 2, 2, 1)
    assert np.array_equal(block[..., 0], data[..., 3])
    assert scan.calls == [{"axis": 3, "frames": "3:4"}]


def test_read_frame_block_reads_to_the_end_without_a_count(frame_env):
    scan, data = frame_env
    block = convert_worker._read_frame_block(scan, 1, 2, None)
    assert np.array_equal(block, data[..., 2:])


def test_read_frame_block_none_without_a_frame_axis(monkeypatch):
    monkeypatch.setattr(convert_worker.brkapi.shape_resolver, "resolve", lambda scan, reco_id: {})
    assert convert_worker._read_frame_block(_FrameScan(np.zeros((2, 2, 2)), ["a", "b", "c"]), 1, 0, 1) is None


def test_load_volume_request_uses_frame_fields():
    req = LoadVolumeRequest(job_id="j", path="p", scan_id=1, reco_id=1, frame_start=4, frame_count=1)
    assert (req.frame_start, req.frame_count) == (4, 1)
    assert not hasattr(req, "cycle_index")


def test_addons_tab_applies_a_0_6_context_map(tmp_path, monkeypatch):
    from brkraw_viewer.ui.tabs.addons import window

    path = tmp_path / "m.yaml"
    path.write_text("bids:\n  sub: {from: Subject.ID}\nsidecar:\n  SubjectLabel: {from: Subject.ID}\n", encoding="utf-8")
    shown = {}
    stub = SimpleNamespace(
        _addon_context_map_var=SimpleNamespace(get=lambda: str(path)),
        _resolve_spec_path_for_category=lambda category: "spec.yaml",
        _cb=SimpleNamespace(on_apply_addon_spec=lambda category, spec_path: {"Subject": {"ID": "s01"}}),
        _addon_context_status_var=SimpleNamespace(set=lambda value: shown.setdefault("status", value)),
        _notify_context_map_change=lambda value: None,
        set_output=lambda payload: shown.setdefault("output", payload),
    )
    monkeypatch.setattr(window.messagebox, "showerror", lambda *a, **k: shown.setdefault("error", a))
    window.AddonsTab._apply_context_map(stub)
    assert "error" not in shown
    assert shown["status"] == "applied"
    # the addons tab prefers the metadata spec, so the map's sidecar fields are applied
    assert shown["output"] == {"Subject": {"ID": "s01"}, "SubjectLabel": "s01"}
