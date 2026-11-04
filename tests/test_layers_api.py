"""Controller binding app.layers_api; headless, fake view, no Tk window."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config

from test_core_layers_in_viewer import RAW_AFFINE, _View, load, raw_volume


@pytest.fixture
def ctrl(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    c = ViewerController()
    c._view = _View()
    return c


def _fail(exc, field):
    msg = str(exc.value)
    assert f"{field}: got" in msg and "expected" in msg


def _loaded(ctrl):
    load(ctrl, raw_volume())
    grid = ctrl._display_grid()
    return grid, np.zeros(grid.shape, dtype=np.float32)


def _add(ctrl, name="ov", **kw):
    grid, arr = _loaded(ctrl) if ctrl._viewer_volume is None else (ctrl._display_grid(), None)
    if arr is None:
        arr = np.zeros(grid.shape, dtype=np.float32)
    arr[1, 1, 1] = 5.0
    return ctrl.layers_api.add_overlay(arr, grid.affine, name=name, **kw), arr


def test_property_returns_the_same_object(ctrl):
    assert ctrl.layers_api is ctrl.layers_api


def test_no_scan_raises_the_image_error(ctrl):
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.get_image()
    _fail(e, "image")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.add_overlay(np.zeros((2, 2, 2)), np.eye(4), name="x")
    _fail(e, "image")


def test_get_image_shape_affine_and_copy_modes(ctrl):
    grid, _ = _loaded(ctrl)
    arr, aff = ctrl.layers_api.get_image()
    assert arr.shape[:3] == grid.shape
    np.testing.assert_array_equal(aff, grid.affine)
    aff[0, 0] = 99.0
    assert ctrl._display_grid().affine[0, 0] != 99.0
    arr[...] = -1
    assert not np.all(np.asarray(ctrl._viewer_volume) == -1)
    view, _ = ctrl.layers_api.get_image(copy=False)
    assert not view.flags.writeable
    with pytest.raises(ValueError):
        view[0, 0, 0] = 1
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.get_image(copy="x")
    _fail(e, "copy")


def test_add_then_list_base_first_and_view_rendered(ctrl):
    _loaded(ctrl)
    before = len(ctrl._view.calls)
    lid, _ = _add(ctrl)
    infos = ctrl.layers_api.list_layers()
    assert [i.id for i in infos] == ["base", lid]
    assert len(ctrl._view.calls) > before


def test_worker_thread_is_refused(ctrl):
    _loaded(ctrl)
    caught = []

    def work():
        try:
            ctrl.layers_api.list_layers()
        except BaseException as exc:  # captured for the assertion below
            caught.append(exc)

    t = threading.Thread(target=work, name="worker-x")
    t.start()
    t.join()
    assert len(caught) == 1 and isinstance(caught[0], RuntimeError)
    assert "thread: got" in str(caught[0]) and "expected" in str(caught[0])


def test_lifecycle_kept_in_the_same_space(ctrl):
    lid, arr = _add(ctrl)
    old = ctrl.layers_api.list_layers()[1]
    new_aff = RAW_AFFINE.copy()
    new_aff[0, 3] += 3.0
    load(ctrl, raw_volume()[:, :, :3].copy(), new_aff)
    infos = ctrl.layers_api.list_layers()
    assert [i.id for i in infos] == ["base", lid]
    assert infos[0].affine.tolist() != old.affine.tolist() or infos[0].shape != old.shape
    assert infos[1].shape == old.shape
    np.testing.assert_array_equal(infos[1].affine, old.affine)
    got = ctrl.layers_api.get_overlay_array(lid)
    assert got.shape == arr.shape and np.array_equal(got, arr)


def test_lifecycle_dropped_in_another_space(ctrl):
    lid, _ = _add(ctrl)
    ctrl.state.viewer.space = "subject_ras"
    assert [i.id for i in ctrl.layers_api.list_layers()] == ["base"]
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.get_overlay_array(lid)
    _fail(e, "layer_id")


def test_remove_dirty_kept_and_clean_removed(ctrl):
    lid, _ = _add(ctrl, name="a")
    ctrl._layer_dirty.add(lid)
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.remove_overlay(lid)
    _fail(e, "layer_id")
    assert lid in [i.id for i in ctrl.layers_api.list_layers()]
    ctrl._layer_dirty.discard(lid)
    ctrl._layer_label_colors[lid] = {77: (1, 2, 3)}
    ctrl._layer_windows[(lid, 0)] = (0.0, 1.0)
    ctrl.layers_api.remove_overlay(lid)
    assert [i.id for i in ctrl.layers_api.list_layers()] == ["base"]
    assert lid not in ctrl._layer_label_colors
    assert not [k for k in ctrl._layer_windows if k[0] == lid]


def test_refresh_clears_cached_windows(ctrl):
    lid, arr = _add(ctrl, copy=False)
    other = "other-layer"
    ctrl._layer_windows[(lid, 0)] = (-99.0, -98.0)
    ctrl._layer_windows[(other, 0)] = (-99.0, -98.0)
    ctrl._layer_label_colors[lid] = {77: (1, 2, 3)}
    arr[2, 2, 2] = 9.0
    ctrl.layers_api.set_overlay(lid)
    assert ctrl._layer_windows.get((lid, 0)) != (-99.0, -98.0)
    assert ctrl._layer_windows[(other, 0)] == (-99.0, -98.0)
    assert ctrl._layer_label_colors.get(lid) != {77: (1, 2, 3)}


def _labels(ctrl, name="lab"):
    grid, _ = _loaded(ctrl)
    mask = np.zeros(grid.shape, dtype=np.uint8)
    mask[:2, :2, :2] = 1
    mask[3:5, 3:5, 3:5] = 4
    return mask, ctrl.layers_api.add_overlay(mask, grid.affine, name=name, kind="label")


def test_roi_timecourse_layer_gives_per_label_means(ctrl):
    mask, lid = _labels(ctrl)
    vol = np.asarray(ctrl._viewer_volume)
    for call in (ctrl.roi_timecourse, ctrl.layers_api.roi_timecourse):
        out = call(layer=lid)
        assert sorted(out) == [1, 4]  # label 2, 3 have no voxels: not reported
        for k in out:
            assert out[k] == pytest.approx([float(vol[mask == k].mean())])
        assert call(layer=lid, label=4) == {4: out[4]}
        assert call(layer=lid, label=2) == {}


def test_roi_timecourse_layer_errors_use_the_stage4_form(ctrl):
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.roi_timecourse(layer="x")
    _fail(e, "image")
    mask, lid = _labels(ctrl)
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.roi_timecourse(layer="base")
    _fail(e, "layer")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.roi_timecourse(layer="nope")
    _fail(e, "layer")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.roi_timecourse(label=1)
    _fail(e, "layer")


def test_roi_timecourse_layer_from_another_thread_is_refused(ctrl):
    _, lid = _labels(ctrl)
    caught = []

    def work():
        for call in (ctrl.roi_timecourse, ctrl.layers_api.roi_timecourse):
            try:
                call(layer=lid)
            except RuntimeError as exc:
                caught.append(str(exc))

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert len(caught) == 2 and all("thread: got" in m and "expected" in m for m in caught)


def test_no_separate_label_timecourse_method(ctrl):
    assert not hasattr(ctrl, "label_timecourse") and not hasattr(ctrl.layers_api, "label_timecourse")


def _label(ctrl, name="lab"):
    grid, _ = _loaded(ctrl) if ctrl._viewer_volume is None else (ctrl._display_grid(), None)
    arr = np.zeros(grid.shape, dtype=np.uint8)
    arr[1, 1, 1] = 3
    return ctrl.layers_api.add_overlay(arr, grid.affine, name=name, kind="label"), arr


def test_save_then_load_overlay_in_the_same_session(ctrl, tmp_path):
    lid, arr = _label(ctrl)
    out = ctrl.layers_api.save_overlay(lid, tmp_path / "a.nii.gz")
    assert out.exists()
    new = ctrl.layers_api.load_overlay(out)
    assert new != lid
    np.testing.assert_array_equal(ctrl.layers_api.get_overlay_array(new), arr)
    info = {i.id: i for i in ctrl.layers_api.list_layers()}[new]
    assert info.kind == "label" and info.name == "a"


def test_save_refuses_existing_file_unless_overwrite(ctrl, tmp_path):
    lid, _ = _label(ctrl)
    path = tmp_path / "a.nii.gz"
    ctrl.layers_api.save_overlay(lid, path)
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.save_overlay(lid, path)
    _fail(e, "path")
    assert ctrl.layers_api.save_overlay(lid, path, overwrite=True) == path


def test_save_refuses_a_bad_layer_and_name(ctrl, tmp_path):
    lid, _ = _label(ctrl)
    img, _ = _add(ctrl)
    for bad in ("nope", img):
        with pytest.raises(ValueError) as e:
            ctrl.layers_api.save_overlay(bad, tmp_path / "x.nii.gz")
        _fail(e, "layer_id")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.save_overlay(lid, tmp_path / "x.txt")
    _fail(e, "path")


def test_load_refuses_another_grid_or_affine(ctrl, tmp_path):
    from brkraw_viewer.core.labelio import save_label_nifti

    grid, _ = _loaded(ctrl)
    other = np.zeros(tuple(s + 1 for s in grid.shape), dtype=np.uint8)
    save_label_nifti(other, grid.affine, tmp_path / "s.nii.gz")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.load_overlay(tmp_path / "s.nii.gz")
    _fail(e, "shape")
    shifted = np.array(grid.affine, dtype=float)
    shifted[0, 3] += 10.0
    save_label_nifti(np.zeros(grid.shape, dtype=np.uint8), shifted, tmp_path / "t.nii.gz")
    with pytest.raises(ValueError) as e:
        ctrl.layers_api.load_overlay(tmp_path / "t.nii.gz")
    _fail(e, "affine")


def test_overlay_io_from_another_thread(ctrl, tmp_path):
    lid, _ = _label(ctrl)
    caught = []

    def work():
        for call in (lambda: ctrl.layers_api.save_overlay(lid, tmp_path / "b.nii.gz"),
                     lambda: ctrl.layers_api.load_overlay(tmp_path / "b.nii.gz")):
            try:
                call()
            except RuntimeError as exc:
                caught.append(str(exc))

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert len(caught) == 2 and all("thread: got" in m for m in caught)
