"""T4 ROI tests (contract v0.1 C6, WI-0072). Tk-free."""
from __future__ import annotations

import math

import numpy as np
import pytest

from brkraw_viewer.core import roi
from brkraw_viewer.core.resample import sample_slice, display_to_layer_matrix


def _brute_rect(shape, u0, u1, v0, v1):
    out = np.zeros(shape, bool)
    for u in range(shape[0]):
        for v in range(shape[1]):
            out[u, v] = min(u0, u1) <= u <= max(u0, u1) and min(v0, v1) <= v <= max(v0, v1)
    return out


@pytest.mark.parametrize("shape", [(5, 5), (6, 4), (7, 8)])
@pytest.mark.parametrize("box", [(1, 2.5, 0, 1), (2.5, 1, 1, 0), (0.5, 0.5, 0, 3), (-1, 10, -1, 10), (1.2, 3.8, 0.9, 2.1)])
def test_rect_centre_rule_odd_and_even(shape, box):
    m = roi.rect_mask(shape, *box)
    assert m.dtype == bool and m.shape == shape
    np.testing.assert_array_equal(m, _brute_rect(shape, *box))


def test_rect_examples_from_spec():
    assert roi.rect_mask((5, 5), 1, 2.5, 0.5, 0.5).sum() == 0
    m = roi.rect_mask((5, 5), 1, 2.5, 0, 1)
    assert sorted(zip(*np.nonzero(m))) == [(1, 0), (1, 1), (2, 0), (2, 1)]


@pytest.mark.parametrize("shape, c, r, expect", [
    ((5, 5), (2, 2), (1, 1), 5),
    ((5, 5), (2, 2), (2, 2), 13),
    ((6, 6), (2.5, 2.5), (1, 1), 4),       # even size, centre between voxels
    ((6, 6), (2.5, 2.5), (1.5, 1.5), 4),       # 0.25 + 2.25 = 2.5 > 1.5**2: the 8 side voxels are out
    ((6, 6), (2.5, 2.5), (1.6, 1.6), 12),      # 2.5 <= 2.56: they are in
    ((7, 5), (3, 2), (3, 1), 9),
])
def test_ellipse_counts(shape, c, r, expect):
    m = roi.ellipse_mask(shape, c[0], c[1], r[0], r[1])
    u, v = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    brute = ((u - c[0]) / r[0]) ** 2 + ((v - c[1]) / r[1]) ** 2 <= 1.0
    np.testing.assert_array_equal(m, brute)
    assert int(m.sum()) == expect


def test_mask_errors():
    with pytest.raises(ValueError, match="shape"):
        roi.rect_mask((0, 3), 0, 1, 0, 1)
    with pytest.raises(ValueError, match="radius"):
        roi.ellipse_mask((3, 3), 1, 1, 0, 1)
    with pytest.raises(ValueError, match="shape"):
        roi.roi_stats(np.zeros((2, 2)), np.ones((3, 3), bool), np.eye(4))


def test_stats_example_from_spec():
    s = roi.roi_stats(np.array([[1.0, 2.0], [np.nan, 4.0]]), np.ones((2, 2), bool), np.diag([2, 3, 0.5, 1]))
    assert s["n_mask"] == 4 and s["n"] == 3 and s["n_nan"] == 1
    assert s["mean"] == pytest.approx(7 / 3)
    assert s["std"] == pytest.approx(math.sqrt(7 / 3))
    assert (s["min"], s["max"], s["median"]) == (1.0, 4.0, 2.0)
    assert (s["volume_mm3"], s["mask_mm3"]) == pytest.approx((9.0, 12.0))  # det carries float noise
    assert all(type(s[k]) is int for k in ("n_mask", "n", "n_nan"))
    assert all(type(s[k]) is float for k in ("mean", "std", "min", "max", "median", "volume_mm3", "mask_mm3"))


def test_stats_against_numpy_on_a_random_mask():
    rng = np.random.default_rng(7)
    x = rng.normal(10, 3, size=(9, 11))
    x[rng.random(x.shape) < 0.1] = np.nan
    m = roi.ellipse_mask(x.shape, 4, 5, 3.2, 4.1)
    s = roi.roi_stats(x, m, np.eye(4))
    good = x[m][np.isfinite(x[m])]
    assert s["n"] == good.size and s["n_mask"] == int(m.sum())
    assert s["mean"] == pytest.approx(good.mean())
    assert s["std"] == pytest.approx(good.std(ddof=1))
    assert s["median"] == pytest.approx(np.median(good))


def test_small_n_gives_nan_where_undefined():
    s0 = roi.roi_stats(np.full((2, 2), np.nan), np.ones((2, 2), bool), np.eye(4))
    assert s0["n"] == 0 and all(math.isnan(s0[k]) for k in ("mean", "std", "min", "max", "median"))
    s1 = roi.roi_stats(np.array([[5.0, np.nan]]), np.array([[True, True]]), np.eye(4))
    assert s1["n"] == 1 and s1["mean"] == 5.0 and math.isnan(s1["std"])


def test_volume_with_oblique_anisotropic_affine_and_outside_layer():
    # display grid D oblique and anisotropic; a layer covering only part of the slice:
    # outside samples are NaN (C3) and count in n_nan, not in n or volume_mm3.
    c, s_ = math.cos(0.3), math.sin(0.3)
    a_d = np.array([[0.2 * c, -0.35 * s_, 0, 1.0], [0.2 * s_, 0.35 * c, 0, -2.0], [0, 0, 0.7, 0.5], [0, 0, 0, 1]])
    voxel = abs(np.linalg.det(a_d[:3, :3]))
    assert voxel == pytest.approx(0.2 * 0.35 * 0.7)
    layer = np.arange(4 * 3 * 2, dtype=float).reshape(4, 3, 2)
    a_l = a_d.copy()  # same orientation, the layer is smaller than the 6x5x2 display grid
    values = sample_slice(layer, display_to_layer_matrix(a_d, a_l), (6, 5, 2), 2, 1)
    m = roi.rect_mask(values.shape, 0, 5, 0, 4)  # whole slice
    st = roi.roi_stats(values, m, a_d)
    assert st["n_mask"] == 30 and st["n"] == 12 and st["n_nan"] == 18
    assert st["volume_mm3"] == pytest.approx(12 * voxel)
    assert st["mask_mm3"] == pytest.approx(30 * voxel)
    assert st["mean"] == pytest.approx(layer[:, :, 1].mean())


# roi_mask: one entry point for rect/ellipse, clipped to the display slice (WI-0004).

def _brute_ellipse(shape, cu, cv, ru, rv):
    u, v = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    return ((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2 <= 1.0


def test_roi_mask_rect_matches_rect_mask():
    m = roi.roi_mask("rect", (5, 6), (1, 2.5, 0, 1))
    assert m.dtype == bool and m.shape == (5, 6)
    np.testing.assert_array_equal(m, roi.rect_mask((5, 6), 1, 2.5, 0, 1))
    np.testing.assert_array_equal(roi.roi_mask("rect", (5, 6), (2.5, 1, 1, 0)), m)  # corners in either order


def test_roi_mask_ellipse_matches_ellipse_mask():
    m = roi.roi_mask("ellipse", (7, 5), (3, 2, 3, 1))
    assert m.dtype == bool and m.shape == (7, 5)
    np.testing.assert_array_equal(m, roi.ellipse_mask((7, 5), 3, 2, 3, 1))
    assert int(m.sum()) == 9


def test_roi_mask_rect_partly_outside_is_clipped():
    # u in [-2, 1] keeps rows 0-1; v in [3, 9] keeps columns 3-4 of a 5x5 slice
    m = roi.roi_mask("rect", (5, 5), (-2, 1, 3, 9))
    assert m.shape == (5, 5)
    assert sorted(zip(*np.nonzero(m))) == [(0, 3), (0, 4), (1, 3), (1, 4)]


def test_roi_mask_ellipse_partly_outside_is_clipped():
    m = roi.roi_mask("ellipse", (5, 5), (0, 0, 2, 2))
    assert m.shape == (5, 5) and m.dtype == bool
    brute = _brute_ellipse((5, 5), 0, 0, 2, 2)
    np.testing.assert_array_equal(m, brute)
    assert int(m.sum()) == 6  # (0,0), (0,1), (0,2), (1,0), (1,1), (2,0): only the in-slice part
    assert m[0, 0] and not m[4, 4]


@pytest.mark.parametrize("geometry", [(10, 12, 0, 1), (-9, -7, -9, -7), (5, 6, 0, 4)])
def test_roi_mask_rect_fully_outside_is_empty(geometry):
    m = roi.roi_mask("rect", (5, 5), geometry)
    assert m.shape == (5, 5) and m.dtype == bool and not m.any()


@pytest.mark.parametrize("geometry", [(-20, -20, 2, 2), (30, 2, 1.5, 1.5)])
def test_roi_mask_ellipse_fully_outside_is_empty(geometry):
    m = roi.roi_mask("ellipse", (5, 5), geometry)
    assert m.shape == (5, 5) and m.dtype == bool and not m.any()


def test_roi_mask_accepts_numpy_slice_shape_and_geometry():
    m = roi.roi_mask("rect", (np.int64(4), np.int32(3)), np.array([0, 3, 0, 2]))
    assert m.shape == (4, 3) and m.all()


def test_roi_mask_invalid_shape_raises():
    with pytest.raises(ValueError, match="shape"):
        roi.roi_mask("square", (5, 5), (0, 1, 0, 1))
    with pytest.raises(ValueError, match="shape"):
        roi.roi_mask("Rect", (5, 5), (0, 1, 0, 1))


def test_roi_mask_bad_geometry_or_slice_raises():
    with pytest.raises(ValueError, match="4 values"):
        roi.roi_mask("rect", (5, 5), (0, 1, 0))
    with pytest.raises(ValueError, match="finite"):
        roi.roi_mask("ellipse", (5, 5), (float("nan"), 1, 1, 1))
    with pytest.raises(ValueError, match="radius"):
        roi.roi_mask("ellipse", (5, 5), (2, 2, 0, 1))
    with pytest.raises(ValueError, match="slice_shape"):
        roi.roi_mask("rect", (5,), (0, 1, 0, 1))
    with pytest.raises(ValueError, match="shape"):
        roi.roi_mask("rect", (0, 5), (0, 1, 0, 1))


def test_roi_mask_is_exported_from_core():
    from brkraw_viewer import core

    assert core.roi_mask is roi.roi_mask
    assert "roi_mask" in core.__all__


def test_drag_geometry_square():
    # Normal drag
    assert roi.drag_geometry("square", (10, 20), (30, 40)) == ("rect", (10, 30, 20, 40))
    # Reverse drag
    assert roi.drag_geometry("square", (30, 40), (10, 20)) == ("rect", (10, 30, 20, 40))
    # Mixed drag
    assert roi.drag_geometry("square", (10, 40), (30, 20)) == ("rect", (10, 30, 20, 40))


def test_drag_geometry_circle():
    # Normal drag
    # dist = sqrt(20^2 + 20^2) = sqrt(800) = 28.284...; r = 14.142...
    res_shape, res_geom = roi.drag_geometry("circle", (10, 20), (30, 40))
    assert res_shape == "ellipse"
    assert res_geom[0] == 20.0 # cu
    assert res_geom[1] == 30.0 # cv
    assert res_geom[2] == pytest.approx(math.sqrt(800) / 2) # r
    assert res_geom[3] == res_geom[2] # r


def test_drag_geometry_errors():
    # Zero size drag
    with pytest.raises(ValueError, match="different"):
        roi.drag_geometry("square", (10, 10), (10, 10))
    with pytest.raises(ValueError, match="different"):
        roi.drag_geometry("circle", (10, 10), (10, 10))
    # Bad tool
    with pytest.raises(ValueError, match="unknown tool"):
        roi.drag_geometry("triangle", (10, 10), (20, 20))
