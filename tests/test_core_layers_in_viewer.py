"""Layers drawn by the controller and viewport through the layer core (C1-C4, WI-0072).

Synthetic data only, no Tk window. The controller's layer methods are internal until the
stage-4 Python handle; these tests call them directly.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.core.composite import composite_over, window_to_index
from brkraw_viewer.core.layers import LayerError
from brkraw_viewer.core.window import default_window
from brkraw_viewer.ui.components.viewport import ViewportCanvas
from brkraw_viewer.utils.orientation import ras_display_affine, reorient_to_ras


class _View:
    def __init__(self):
        self.calls = []
        self.status = []

    def set_viewer_views(self, views, **kwargs):
        if views:
            self.calls.append((views, kwargs))

    def set_status(self, text):
        self.status.append(text)

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def ctrl(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    c = ViewerController()
    c._view = _View()
    return c


def rot(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    m = np.eye(4)
    i, j = [(1, 2), (0, 2), (0, 1)][axis]
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


# a raw affine with a flip and an axis swap, so the display grid differs from the raw grid
RAW_AFFINE = np.array([[0.0, -0.3, 0.0, 4.0], [0.25, 0.0, 0.0, -2.0], [0.0, 0.0, 0.5, 1.0], [0, 0, 0, 1]])


def load(c, raw, affine=RAW_AFFINE):
    c._viewer_raw_volume = raw
    c._viewer_raw_affine = affine
    c._viewer_volume = c._reorient_viewer_volume()
    c._viewer_shape = c._viewer_volume.shape
    c.state.viewer.x_index, c.state.viewer.y_index, c.state.viewer.z_index = (n // 2 for n in c._viewer_shape[:3])
    c._render_viewer_views()
    return c._view.calls[-1]


def raw_volume():
    return np.random.default_rng(3).integers(0, 1000, size=(6, 7, 5)).astype(np.float32)


def test_base_only_sends_no_layers_and_layer0_is_the_display_grid(ctrl):
    raw = raw_volume()
    views, kw = load(ctrl, raw)
    assert kw["layers"] is None
    base = ctrl._layers.base
    disp, a_d = reorient_to_ras(raw, RAW_AFFINE)
    assert base.id == "base" and base.space == "scanner" and tuple(base.shape) == disp.shape
    np.testing.assert_allclose(base.affine, a_d, atol=1e-12)
    np.testing.assert_allclose(ras_display_affine(RAW_AFFINE, raw.shape), a_d, atol=1e-12)


def _grey(values, window):
    return window_to_index(values, *window)


def test_the_scan_itself_as_a_layer_lines_up_pixel_for_pixel(ctrl):
    # C1 + C3 end to end: the raw array on the raw grid, drawn over the display grid,
    # must equal the base views exactly (signed permutation -> exact values).
    raw = raw_volume()
    views, _ = load(ctrl, raw)
    lid = ctrl._add_array_layer(raw, RAW_AFFINE, name="self", alpha=1.0)
    views, kw = ctrl._view.calls[-1]
    layers = kw["layers"]
    window = default_window(raw)
    for plane in ("xy", "xz", "zy"):
        (rgb, a), = layers[plane]
        assert rgb.shape[:2] == views[plane].shape
        np.testing.assert_array_equal(rgb[..., 0], _grey(views[plane], window))
        assert np.all(a == 1.0)
    ctrl._layers.update(lid, visible=False)
    ctrl._render_viewer_views()
    assert all(v == [] for v in ctrl._view.calls[-1][1]["layers"].values())
    ctrl._remove_layer(lid)
    assert ctrl._view.calls[-1][1]["layers"] is None and lid not in ctrl._layer_data


def test_oblique_linear_field_is_sampled_at_the_display_world_points(ctrl):
    raw = raw_volume()
    load(ctrl, raw)
    _, a_d = reorient_to_ras(raw, RAW_AFFINE)  # independent of the controller's own A_D
    g, b = np.array([0.7, -1.3, 2.1]), 5.0
    lay_aff = rot(2, 25) @ rot(0, 10) @ np.diag([0.2, 0.15, 0.3, 1.0])
    lay_aff[:3, 3] = (-1.5, -3.5, -0.5)
    n = (40, 40, 30)
    ijk = np.stack(np.meshgrid(*[np.arange(k) for k in n], indexing="ij"), -1).reshape(-1, 3)
    field = (((lay_aff[:3, :3] @ ijk.T).T + lay_aff[:3, 3]) @ g + b).reshape(n)
    window = (float(field.min()), float(field.max()))
    ctrl._add_array_layer(field, lay_aff, name="field", window=window, transparency={})
    views, kw = ctrl._view.calls[-1]
    xi, yi, zi = ctrl.state.viewer.x_index, ctrl.state.viewer.y_index, ctrl.state.viewer.z_index
    (rgb, a), = kw["layers"]["xy"]
    ny, nx = views["xy"].shape  # xy view is (y, x) at z = zi
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    disp_idx = np.stack([xx, yy, np.full_like(xx, zi)], -1).reshape(-1, 3).astype(float)
    world = (a_d[:3, :3] @ disp_idx.T).T + a_d[:3, 3]
    expect = (world @ g + b).reshape(ny, nx)
    lidx = ((np.linalg.inv(lay_aff) @ np.c_[world, np.ones(len(world))].T).T[:, :3]).reshape(ny, nx, 3)
    inside = np.all((lidx >= 0) & (lidx <= np.array(n) - 1), axis=-1)
    outside = np.any((lidx < -0.5) | (lidx >= np.array(n) - 0.5), axis=-1)
    assert inside.sum() > 10 and outside.sum() > 0
    got = rgb[..., 0][inside].astype(int)
    want = _grey(expect, window)[inside].astype(int)
    assert np.max(np.abs(got - want)) <= 1  # float rounding at a grey-level edge
    assert np.all(a[outside] == 0.0)  # outside the layer: transparent (NaN)


def test_label_layer_nearest_palette_and_background(ctrl):
    raw = raw_volume()
    views, _ = load(ctrl, raw)
    lab = np.zeros(raw.shape, dtype=np.uint16)
    lab[2:4, 3:5, :] = 3
    ctrl._add_array_layer(lab, RAW_AFFINE, name="labels", kind="label", alpha=0.5)
    views, kw = ctrl._view.calls[-1]
    disp_lab, _ = reorient_to_ras(lab, RAW_AFFINE)
    zi = ctrl.state.viewer.z_index
    (rgb, a), = kw["layers"]["xy"]
    expect_mask = (disp_lab[:, :, zi].T == 3)
    np.testing.assert_array_equal(a > 0, expect_mask)
    assert np.all(a[expect_mask] == 0.5)
    assert ctrl._layers.get("layer-1").interpolation == "nearest"


def test_other_space_is_refused_and_a_space_change_drops_layers(ctrl):
    raw = raw_volume()
    load(ctrl, raw)
    with pytest.raises(LayerError, match="space"):
        ctrl._add_array_layer(raw, RAW_AFFINE, name="x", space="subject_ras")
    ctrl._add_array_layer(raw, RAW_AFFINE, name="kept")
    assert len(ctrl._layers) == 2
    ctrl.state.viewer.space = "subject_ras"  # the shown scan is now in another space
    ctrl._render_viewer_views()
    assert len(ctrl._layers) == 1 and ctrl._layers.base.space == "subject_ras"
    assert ctrl._layer_data == {} and any("another space" in s for s in ctrl._view.status)
    with pytest.raises(ValueError, match="3 dimensions"):
        ctrl._add_array_layer(np.zeros((2, 2)), np.eye(4), name="flat")


def test_layers_survive_a_new_scan_in_the_same_space(ctrl):
    raw = raw_volume()
    load(ctrl, raw)
    lid = ctrl._add_array_layer(raw, RAW_AFFINE, name="kept")
    load(ctrl, raw[:, :, :3].copy())  # another grid, same space: layer kept, base replaced
    assert ctrl._layers.ids() == ["base", lid]
    assert tuple(ctrl._layers.base.shape) == ctrl._viewer_volume.shape


def test_viewport_composites_layers_and_skips_a_mismatched_one():
    base = np.full((3, 4, 3), 100, dtype=np.uint8)
    rgb = np.zeros((3, 4, 3), np.float32)
    rgb[..., 1] = 200
    a = np.full((3, 4), 0.5, np.float32)
    bad = (np.zeros((2, 2, 3), np.float32), np.ones((2, 2), np.float32))
    out = ViewportCanvas._composite_layers(base, [(rgb, a), bad])
    np.testing.assert_array_equal(out, composite_over(base, [(rgb, a)]))
    assert ViewportCanvas._composite_layers(base, []) is base
