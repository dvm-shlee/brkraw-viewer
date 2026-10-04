"""T3 display-window tests (contract v0.1 C5, WI-0072): one window per frame, every slice the same.

Synthetic data only, no Tk window.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.core import window as cw
from brkraw_viewer.ui.components.viewport import ViewportCanvas


def gradient(shape=(16, 12, 10)) -> np.ndarray:
    """Values rise along z and x, so every z slice has its own range (the old defect)."""
    x, y, z = np.meshgrid(*[np.arange(n, dtype=np.float32) for n in shape], indexing="ij")
    return 100.0 * z + 3.0 * x + 0.5 * y


def test_default_window_is_the_volume_percentile_not_a_slice_percentile():
    vol = gradient()
    lo, hi = cw.default_window(vol)
    expect = np.percentile(vol, (1.0, 99.0))
    assert (lo, hi) == pytest.approx(tuple(float(v) for v in expect))
    # the old per-slice rule gives a different range on each z slice
    per_slice = {tuple(np.round(np.percentile(vol[:, :, k], (1, 99)), 6)) for k in range(vol.shape[2])}
    assert len(per_slice) == vol.shape[2]


def test_subsample_is_deterministic_bounded_and_strided():
    vol = np.arange(10 * 10 * 10, dtype=np.float64).reshape(10, 10, 10)
    s = cw.window_sample(vol, max_samples=64)
    assert s.size <= 64
    np.testing.assert_array_equal(s, vol.reshape(-1)[:: int(np.ceil(1000 / 64))])
    np.testing.assert_array_equal(s, cw.window_sample(vol, max_samples=64))
    # a non-contiguous frame of a 4D array samples the same voxels as its contiguous copy
    v4 = np.arange(6 * 5 * 4 * 3, dtype=np.float32).reshape(6, 5, 4, 3)
    frame = v4[..., 1]
    assert not frame.flags.c_contiguous
    np.testing.assert_array_equal(cw.window_sample(frame, 17), cw.window_sample(np.ascontiguousarray(frame), 17))
    assert cw.default_window(frame, 17) == cw.default_window(np.ascontiguousarray(frame), 17)


def test_window_ignores_non_finite_and_handles_constant_and_empty():
    vol = gradient()
    vol[0, 0, 0] = np.nan
    vol[1, 1, 1] = np.inf
    lo, hi = cw.default_window(vol)
    finite = vol[np.isfinite(vol)]
    assert (lo, hi) == pytest.approx(tuple(float(v) for v in np.percentile(finite, (1, 99))))
    assert cw.default_window(np.full((3, 3, 3), 7.0)) == (7.0, 8.0)
    assert cw.default_window(np.full((2, 2, 2), np.nan)) == (0.0, 1.0)
    assert cw.default_window(np.array([1 + 1j, 3 + 4j]).reshape(2, 1, 1)) == pytest.approx(
        tuple(float(v) for v in np.percentile([np.sqrt(2), 5.0], (1, 99)))
    )


def test_normalize_window():
    assert cw.normalize_window(None) is None
    assert cw.normalize_window((1, 3)) == (1.0, 3.0)
    assert cw.normalize_window((3, 3)) == (3.0, 4.0)
    assert cw.normalize_window((5, 1)) == (5.0, 6.0)
    assert cw.normalize_window((np.nan, 1)) is None
    assert cw.normalize_window("x") is None


def test_viewport_maps_one_value_to_one_grey_on_every_slice():
    vol = gradient()
    win = cw.default_window(vol)
    grey_of_value: dict[float, set] = {}
    for axis in range(3):
        for k in range(vol.shape[axis]):
            sl = np.take(vol, k, axis=axis)
            rgb = ViewportCanvas._base_to_rgb(sl, win)
            for v, g in zip(sl.reshape(-1).tolist(), rgb[..., 0].reshape(-1).tolist()):
                grey_of_value.setdefault(v, set()).add(g)
    assert all(len(g) == 1 for g in grey_of_value.values())
    # without a window (older callers) the viewport still falls back to the slice's own range
    a = ViewportCanvas._base_to_rgb(vol[:, :, 0])
    b = ViewportCanvas._base_to_rgb(vol[:, :, 5])
    assert a[..., 0].max() == 255 and b[..., 0].max() == 255


class _View:
    def __init__(self):
        self.windows = []

    def set_viewer_views(self, views, **kwargs):
        if views:
            self.windows.append(kwargs.get("window"))

    def __getattr__(self, name):  # any other view call is a no-op
        return lambda *a, **k: None


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    ctrl = ViewerController()
    ctrl._view = _View()
    return ctrl


def test_controller_sends_the_same_frame_window_for_every_slice_position(controller):
    vol = gradient()
    controller._viewer_volume = vol
    controller._viewer_shape = vol.shape
    windows = []
    for zi in range(vol.shape[2]):
        controller.state.viewer.z_index = zi
        controller.state.viewer.x_index = zi % vol.shape[0]
        controller._render_viewer_views()
        windows.append(controller._view.windows[-1])
    assert len(set(windows)) == 1
    assert windows[0] == pytest.approx(cw.default_window(vol))


def test_controller_window_is_per_frame_and_reset_with_a_new_volume(controller, monkeypatch):
    calls = []
    real = viewer_module.default_window
    monkeypatch.setattr(viewer_module, "default_window", lambda f: calls.append(f.shape) or real(f))
    v4 = np.stack([gradient(), 10.0 * gradient()], axis=3)
    controller._viewer_volume = v4
    controller._viewer_shape = v4.shape
    controller._viewer_frames = 2
    for frame in (0, 1, 0, 1):
        controller.state.viewer.frame_index = frame
        for zi in (0, 3, 7):
            controller.state.viewer.z_index = zi
            controller._render_viewer_views()
    w = controller._view.windows
    assert w[0] == pytest.approx(cw.default_window(v4[..., 0]))
    assert w[3] == pytest.approx(cw.default_window(v4[..., 1]))
    assert len(set(w[0:3] + w[6:9])) == 1 and len(set(w[3:6] + w[9:12])) == 1
    assert len(calls) == 2  # computed once per frame, not per slice or per render
    controller._viewer_volume = gradient() + 5.0  # a new volume object: recomputed
    controller.state.viewer.frame_index = 0
    controller._render_viewer_views()
    assert len(calls) == 3
    assert controller._view.windows[-1] == pytest.approx(cw.default_window(gradient() + 5.0))
