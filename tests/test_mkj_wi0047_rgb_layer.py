"""RGB layer kind: validation, rgb_rgba and the controller branch (stage 3 WI-A, WI-0047).

Synthetic data only, headless (no Tk window).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.core.composite import rgb_rgba
from brkraw_viewer.core.layers import KINDS, Layer, LayerError, LayerStack

AFFINE = np.diag([1.0, 1.0, 1.0, 1.0])


def make_layer(**over):
    kw = dict(
        id="c", name="c", kind="rgb", source="array", space="scanner",
        shape=(4, 5, 6, 3), affine=AFFINE, dtype="uint8",
    )
    kw.update(over)
    return Layer(**kw)


class _View:
    def __init__(self):
        self.calls = []

    def set_viewer_views(self, views, **kwargs):
        if views:
            self.calls.append((views, kwargs))

    def set_status(self, text):
        pass

    def __getattr__(self, name):
        return lambda *a, **k: None


@pytest.fixture
def ctrl(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    c = ViewerController()
    c._view = _View()
    raw = np.random.default_rng(1).integers(0, 1000, size=(8, 7, 6)).astype(np.float32)
    c._viewer_raw_volume = raw
    c._viewer_raw_affine = AFFINE
    c._viewer_volume = c._reorient_viewer_volume()
    c._viewer_shape = c._viewer_volume.shape
    c.state.viewer.x_index, c.state.viewer.y_index, c.state.viewer.z_index = (n // 2 for n in c._viewer_shape[:3])
    c._render_viewer_views()
    return c


def planes(c):
    return c._view.calls[-1][1]["layers"]


def display_shape(c):
    return tuple(c._viewer_shape[:3])


# --- kind validation -------------------------------------------------------------------

def test_rgb_is_a_kind():
    assert "rgb" in KINDS and KINDS[:2] == ("image", "label")


def test_rgb_layer_fields():
    lay = make_layer()
    assert lay.channels == 3 and lay.frames == 1
    assert make_layer(shape=(4, 5, 6, 4)).channels == 4
    # the channel axis is never frames, even when frames is asked for
    assert make_layer(frames=4, shape=(4, 5, 6, 4)).frames == 1
    assert lay.interpolation == "linear"
    assert make_layer(interpolation="nearest").interpolation == "nearest"


@pytest.mark.parametrize("shape", [(4, 5, 6), (4, 5, 6, 2), (4, 5, 6, 5), (4, 5, 6, 3, 1)])
def test_rgb_shape_rules(shape):
    with pytest.raises(LayerError, match=r"shape: got .*expected"):
        make_layer(shape=shape)


@pytest.mark.parametrize("dtype", ["float32", "int16", "uint16", "bool"])
def test_rgb_dtype_rules(dtype):
    with pytest.raises(LayerError, match=r"dtype: got .*expected 'uint8'"):
        make_layer(dtype=dtype)


def test_rgb_is_not_editable_and_ignores_scalar_fields():
    with pytest.raises(LayerError, match="editable"):
        make_layer(editable=True)
    stack = LayerStack()
    stack.add(Layer(id="base", name="b", kind="image", source="scan", space="scanner",
                    shape=(4, 5, 6), affine=AFFINE, dtype="float32"))
    stack.add(make_layer())
    for key, value in (("cmap", "hot"), ("window", (0, 1)), ("transparency", {"zero": True})):
        with pytest.raises(LayerError, match=rf"field: got '{key}'"):
            stack.update("c", **{key: value})
    assert stack.update("c", alpha=0.4, interpolation="nearest") == ["alpha", "interpolation"]
    assert stack.frame_for("c", 3) == 0


def test_other_kinds_keep_one_channel_and_their_rules():
    img = make_layer(kind="image", shape=(4, 5, 6, 3), dtype="float32")
    assert img.frames == 1 and img.channels == 1  # 3 frames when asked: unchanged semantics
    assert make_layer(kind="image", shape=(4, 5, 6, 3), dtype="float32", frames=3).frames == 3
    assert make_layer(kind="label", dtype="int16", shape=(4, 5, 6)).interpolation == "nearest"
    with pytest.raises(LayerError, match="channels"):
        make_layer(kind="image", shape=(4, 5, 6), dtype="float32", channels=3)


# --- rgb_rgba ----------------------------------------------------------------------------

def test_rgb_rgba_colours_and_alpha():
    v = np.zeros((2, 3, 3))
    v[...] = (200, 100, 50)
    rgb, a = rgb_rgba(v, alpha=0.5)
    assert rgb.dtype == np.float32 and a.dtype == np.float32 and rgb.shape == (2, 3, 3) and a.shape == (2, 3)
    np.testing.assert_array_equal(rgb[0, 0], (200, 100, 50))
    assert np.all(a == np.float32(0.5))
    _, a_hidden = rgb_rgba(v, alpha=0.5, visible=False)
    assert np.all(a_hidden == 0.0)


def test_rgb_rgba_alpha_channel_scales_alpha():
    v = np.zeros((1, 3, 4))
    v[0, :, :3] = (10, 20, 30)
    v[0, :, 3] = (255, 128, 0)
    rgb, a = rgb_rgba(v, alpha=0.5)
    np.testing.assert_allclose(a[0], [0.5, 0.5 * 128 / 255, 0.0], atol=1e-6)
    np.testing.assert_array_equal(rgb[0, 1], (10, 20, 30))


def test_rgb_rgba_outside_is_transparent_and_values_are_clipped():
    v = np.full((1, 2, 3), 300.0)
    v[0, 1] = np.nan
    rgb, a = rgb_rgba(v)
    np.testing.assert_array_equal(rgb[0, 0], (255, 255, 255))
    assert a[0, 0] == 1.0 and a[0, 1] == 0.0


def test_rgb_rgba_errors_follow_the_style_rule():
    with pytest.raises(ValueError, match=r"values: got shape .*expected"):
        rgb_rgba(np.zeros((2, 2, 2)))
    with pytest.raises(ValueError, match=r"values: got dtype .*expected"):
        rgb_rgba(np.zeros((2, 2, 3), dtype=bool))
    with pytest.raises(ValueError, match="alpha"):
        rgb_rgba(np.zeros((2, 2, 3)), alpha=1.5)


# --- controller --------------------------------------------------------------------------

def colour_volume(c, rgb=(200, 100, 50), channels=3, extra=None):
    arr = np.zeros(display_shape(c) + (channels,), dtype=np.uint8)
    arr[..., :3] = rgb
    if channels == 4:
        arr[..., 3] = 255 if extra is None else extra
    return arr


def test_channels_are_never_frames_and_base_frames_unchanged(ctrl):
    arr = colour_volume(ctrl, channels=4)
    lid = ctrl._add_array_layer(arr, ctrl._layers.base.affine, name="rgba", kind="rgb")
    lay = ctrl._layers.get(lid)
    assert lay.kind == "rgb" and lay.frames == 1 and lay.channels == 4 and lay.dtype == "uint8"
    assert lay.nbytes == arr.nbytes and tuple(lay.shape) == arr.shape
    # an image layer of the same array still reads the last axis as frames
    iid = ctrl._add_array_layer(arr.astype(np.float32), ctrl._layers.base.affine, name="img")
    assert ctrl._layers.get(iid).frames == 4


def test_rendered_plane_colours_and_alpha(ctrl):
    ctrl._add_array_layer(colour_volume(ctrl), ctrl._layers.base.affine, name="c", kind="rgb", alpha=0.5)
    for plane, (rgb, a) in ((p, planes(ctrl)[p][-1]) for p in ("xy", "xz", "zy")):
        np.testing.assert_array_equal(rgb[..., 0], 200)
        np.testing.assert_array_equal(rgb[..., 1], 100)
        np.testing.assert_array_equal(rgb[..., 2], 50)
        assert np.all(a == np.float32(0.5)), plane
        assert (rgb.shape[:2] == ctrl._view.calls[-1][0][plane].shape)


def test_rgba_alpha_channel_in_the_rendered_plane(ctrl):
    ctrl._add_array_layer(colour_volume(ctrl, channels=4, extra=128), ctrl._layers.base.affine,
                          name="c", kind="rgb", alpha=1.0)
    rgb, a = planes(ctrl)["xy"][-1]
    np.testing.assert_allclose(a, 128 / 255, atol=1e-6)
    np.testing.assert_array_equal(rgb[..., 0], 200)


def test_float_channels_are_rescaled_to_uint8(ctrl):
    arr = np.zeros(display_shape(ctrl) + (3,))
    arr[..., 0], arr[..., 1], arr[..., 2] = 1.0, 0.5, 0.0
    lid = ctrl._add_array_layer(arr, ctrl._layers.base.affine, name="f", kind="rgb")
    assert ctrl._layer_data[lid].dtype == np.uint8
    rgb, _ = planes(ctrl)["xy"][-1]
    np.testing.assert_array_equal(rgb[0, 0], (255, 128, 0))


@pytest.mark.parametrize(
    "arr, match",
    [
        (np.zeros((4, 5, 6)), r"data: got shape"),
        (np.zeros((4, 5, 6, 2), dtype=np.uint8), r"data: got shape"),
        (np.zeros((4, 5, 6, 3, 1), dtype=np.uint8), r"data: got shape"),
        (np.zeros((4, 5, 6, 3), dtype=np.int16), r"data: got dtype"),
        (np.full((4, 5, 6, 3), 2.0), r"data: got float values"),
        (np.full((4, 5, 6, 3), np.nan), r"data: got float values"),
    ],
)
def test_controller_rejects_bad_rgb_arrays(ctrl, arr, match):
    with pytest.raises(ValueError, match=match):
        ctrl._add_array_layer(arr, ctrl._layers.base.affine, name="bad", kind="rgb")
    assert len(ctrl._layers) == 1


def test_nearest_vs_linear_sampling(ctrl):
    shape = display_shape(ctrl)
    arr = np.zeros(shape + (3,), dtype=np.uint8)
    arr[..., 0] = (10 * np.arange(shape[0]))[:, None, None]
    aff = ctrl._layers.base.affine.copy()
    aff[:3, 3] += aff[:3, 0] * 0.25  # layer index = display index - 0.25 along x
    lid = ctrl._add_array_layer(arr, aff, name="g", kind="rgb", interpolation="linear")
    rgb_lin, _ = planes(ctrl)["xy"][-1]  # (y, x)
    ctrl._layers.update(lid, interpolation="nearest")
    ctrl._render_viewer_views()
    rgb_near, _ = planes(ctrl)["xy"][-1]
    i = np.arange(1, shape[0])
    np.testing.assert_allclose(rgb_lin[0, 1:, 0], 10 * (i - 0.25), atol=1e-4)
    np.testing.assert_array_equal(rgb_near[0, 1:, 0], 10 * i)
