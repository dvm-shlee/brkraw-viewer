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
