"""T2 transparency and compositing tests (contract v0.1 C4, WI-0072). Tk-free, 4x4 arrays."""
from __future__ import annotations

import numpy as np
import pytest

from brkraw_viewer.core import composite as cp

V = np.array(
    [
        [0.0, 1.0, -1.0, np.nan],
        [2.0, -3.0, 0.5, 5.0],
        [7.0, 0.0, -0.2, 9.0],
        [10.0, 4.0, 3.0, -8.0],
    ]
)
GRAY = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 3, axis=1)


def test_nan_is_always_transparent_and_nothing_else_by_default():
    for rules in (None, {}, {"zero": False}):
        m = cp.transparency_mask(V, rules)
        assert m.dtype == bool and m.shape == (4, 4)
        np.testing.assert_array_equal(m, np.isnan(V))


@pytest.mark.parametrize(
    "rules, expect",
    [
        ({"zero": True}, (V == 0)),
        ({"below": 1.0}, (V < 1.0)),
        ({"abs_below": 1.0}, (np.abs(V) < 1.0)),
        ({"range": (-1.0, 2.0)}, (V >= -1.0) & (V <= 2.0)),
        ({"values": [4.0, 9.0, 123.0]}, np.isin(V, [4.0, 9.0])),
        ({"zero": True, "below": -2.0}, (V == 0) | (V < -2.0)),
    ],
)
def test_each_rule_and_or_combination(rules, expect):
    with np.errstate(invalid="ignore"):
        m = cp.transparency_mask(V, rules)
    np.testing.assert_array_equal(m, np.asarray(expect) | np.isnan(V))


def test_rule_errors():
    with pytest.raises(ValueError, match="range"):
        cp.transparency_mask(V, {"range": (2.0, 1.0)})
    with pytest.raises(ValueError, match="unknown rule.*bogus"):
        cp.transparency_mask(V, {"bogus": 1})


def test_window_to_index_examples_and_constant_window():
    idx = cp.window_to_index(np.array([0.0, 5.0, 10.0, 20.0, -3.0, np.nan]), 0.0, 10.0)
    assert idx.dtype == np.uint8
    np.testing.assert_array_equal(idx, [0, 127, 255, 255, 0, 0])
    np.testing.assert_array_equal(cp.window_to_index(np.array([3.0, 3.5, 4.0]), 3.0, 3.0), [0, 127, 255])
    np.testing.assert_array_equal(cp.window_to_index(np.array([3.0, 4.0]), 5.0, 1.0), [0, 0])


def test_layer_rgba_colours_alpha_visibility_and_rules():
    rgb, a = cp.layer_rgba(V, lut=GRAY, vmin=0.0, vmax=10.0, alpha=0.4, rules={"zero": True})
    assert rgb.shape == (4, 4, 3) and rgb.dtype == np.float32
    assert a.shape == (4, 4) and a.dtype == np.float32
    assert rgb[1, 3, 0] == 127.0 and rgb[3, 0, 0] == 255.0
    expect_a = np.where(np.isnan(V) | (V == 0), 0.0, 0.4).astype(np.float32)
    np.testing.assert_array_equal(a, expect_a)
    _, a_hidden = cp.layer_rgba(V, lut=GRAY, vmin=0.0, vmax=10.0, alpha=0.4, visible=False)
    assert not a_hidden.any()
    with pytest.raises(ValueError, match="lut"):
        cp.layer_rgba(V, lut=np.zeros((10, 3)), vmin=0, vmax=1)
    with pytest.raises(ValueError, match="alpha"):
        cp.layer_rgba(V, lut=GRAY, vmin=0, vmax=1, alpha=1.5)


def test_label_rgba_background_hidden_and_uncoloured_labels():
    lab = np.array([[0, 1, 2, 3], [1, 1, 0, 2], [3, 3, 3, 0], [2, 0, 1, 9]], dtype=np.uint16)
    colors = {0: (9, 9, 9), 1: (255, 0, 0), 2: (0, 255, 0), 3: (0, 0, 255)}
    rgb, a = cp.label_rgba(lab, colors=colors, alpha=0.5, hidden_labels={3})
    np.testing.assert_array_equal(rgb[0, 1], [255, 0, 0])
    np.testing.assert_array_equal(rgb[0, 0], [0, 0, 0])  # label 0 is background, never coloured
    expect_a = np.where(np.isin(lab, [1, 2]), 0.5, 0.0).astype(np.float32)  # 3 hidden, 9 uncoloured
    np.testing.assert_array_equal(a, expect_a)
    with pytest.raises(ValueError, match="labels"):
        cp.label_rgba(lab.astype(float), colors=colors)


def test_composite_over_worked_example_and_identity():
    base = np.full((4, 4, 3), 100, dtype=np.uint8)
    red = np.zeros((4, 4, 3), np.float32)
    red[..., 0] = 200
    blue = np.zeros((4, 4, 3), np.float32)
    blue[..., 2] = 255
    out = cp.composite_over(base, [(red, np.full((4, 4), 0.5, np.float32)), (blue, np.full((4, 4), 0.2, np.float32))])
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out[0, 0], [120, 40, 91])
    np.testing.assert_array_equal(cp.composite_over(base, []), base)
    # alpha 0 leaves the base, alpha 1 replaces it, order matters (top wins)
    a0 = np.zeros((4, 4), np.float32)
    a1 = np.ones((4, 4), np.float32)
    np.testing.assert_array_equal(cp.composite_over(base, [(red, a0)]), base)
    np.testing.assert_array_equal(cp.composite_over(base, [(red, a1), (blue, a1)])[2, 2], [0, 0, 255])
    np.testing.assert_array_equal(cp.composite_over(base, [(blue, a1), (red, a1)])[2, 2], [200, 0, 0])
    with pytest.raises(ValueError, match="shape"):
        cp.composite_over(base, [(red[:2], a1)])


def test_full_pipeline_transparent_pixels_show_the_base():
    base = np.full((4, 4, 3), 50, dtype=np.uint8)
    rgb, a = cp.layer_rgba(V, lut=GRAY, vmin=0.0, vmax=10.0, alpha=1.0, rules={"below": 1.0})
    out = cp.composite_over(base, [(rgb, a)])
    hidden = np.isnan(V) | (V < 1.0)
    np.testing.assert_array_equal(out[hidden], np.full((int(hidden.sum()), 3), 50))
    assert out[3, 0, 0] == 255 and out[1, 3, 0] == 127
