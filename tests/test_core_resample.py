"""T1 resampling tests for the layer core (contract v0.1 C1/C3, WI-0010 -> WI-0072). Tk-free."""
from __future__ import annotations

import math

import numpy as np
import pytest

from brkraw_viewer.core import resample as rs


def rot(axis: int, deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    m = np.eye(4)
    i, j = [(1, 2), (0, 2), (0, 1)][axis]
    m[i, i], m[i, j], m[j, i], m[j, j] = c, -s, s, c
    return m


def affine(zooms, rotation=np.eye(4), shift=(0, 0, 0)) -> np.ndarray:
    a = rotation @ np.diag(list(zooms) + [1.0])
    a[:3, 3] = shift
    return a


# ---- matrix, grid, snap ---------------------------------------------------------------

def test_display_to_layer_is_inverse_layer_times_display():
    d = affine((0.2, 0.2, 0.5), rot(2, 10), (1, 2, 3))
    l = affine((0.3, 0.25, 0.4), rot(0, 25), (-4, 0.5, 2))
    m = rs.display_to_layer_matrix(d, l)
    assert m.shape == (4, 4)
    np.testing.assert_allclose(m, np.linalg.inv(l) @ d, atol=1e-12)


def test_slice_index_grid_axes_and_order():
    for axis, expect_shape in ((0, (4, 5)), (1, (3, 5)), (2, (3, 4))):
        g = rs.slice_index_grid((3, 4, 5), axis, 2)
        assert g.shape == expect_shape + (3,)
        assert g.dtype == np.float64
        assert np.all(g[..., axis] == 2)
    np.testing.assert_array_equal(rs.slice_index_grid((3, 4, 5), 2, 1)[2, 3], [2, 3, 1])
    np.testing.assert_array_equal(rs.slice_index_grid((3, 4, 5), 0, 0)[3, 4], [0, 3, 4])


def test_map_indices_snaps_to_multiples_of_half_only_within_tolerance():
    m = np.eye(4)
    m[0, 3] = -1e-9   # 3 -> 2.999999999, snapped back to 3
    m[1, 3] = 0.25    # 3.25 is not near k/2, kept
    m[2, 3] = 0.5 - 1e-9  # 3.4999999990 -> snapped to 3.5 (v0.1: half-integers too)
    out = rs.map_indices(m, np.array([[3.0, 3.0, 3.0]]))
    assert out[0, 0] == 3.0
    assert out[0, 1] == pytest.approx(3.25, abs=1e-12)
    assert out[0, 2] == 3.5
    big = np.eye(4)
    big[2, 3] = 2e-6  # beyond the tolerance, not snapped
    assert rs.map_indices(big, np.array([[0.0, 0.0, 1.0]]))[0, 2] != 1.0


def test_half_integer_tie_under_float_noise_rounds_half_up():
    # 0.49999999999999994 is the float just below 0.5; without the half snap nearest gives 0.
    vol = np.array([10, 20, 30], dtype=np.int16).reshape(3, 1, 1)
    m = np.eye(4)
    m[0, 3] = 0.49999999999999994
    c = rs.map_indices(m, np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]))
    np.testing.assert_array_equal(c[:, 0], [0.5, 1.5])
    np.testing.assert_array_equal(rs.sample_nearest(vol, c, 0), [20, 30])


# ---- nearest --------------------------------------------------------------------------

def test_nearest_identity_is_exact_and_keeps_dtype():
    vol = np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)
    a = affine((0.3, 0.3, 0.7), rot(1, 20), (5, -2, 1))
    m = rs.display_to_layer_matrix(a, a)
    for axis in range(3):
        c = rs.map_indices(m, rs.slice_index_grid(vol.shape, axis, 1))
        out = rs.sample_nearest(vol, c, 0)
        assert out.dtype == np.uint16
        np.testing.assert_array_equal(out, np.take(vol, 1, axis=axis))


def test_nearest_round_half_up_and_domain():
    vol = np.arange(1, 5, dtype=np.int32).reshape(4, 1, 1)
    pts = np.array([[x, 0, 0] for x in (-0.5, -0.51, 0.49, 0.5, 1.5, 2.4999999, 3.49, 3.5)], float)
    np.testing.assert_array_equal(rs.sample_nearest(vol, pts, -7), [1, -7, 1, 2, 3, 3, 4, -7])


def test_nearest_nan_fill_on_integer_volume_gives_float():
    vol = np.ones((2, 2, 2), dtype=np.int16)
    out = rs.sample_nearest(vol, np.array([[0.0, 0, 0], [5.0, 0, 0]]), np.nan)
    assert out.dtype == np.float64
    assert out[0] == 1.0 and np.isnan(out[1])


def test_flip_and_permutation():
    rng = np.random.default_rng(1)
    vol = rng.integers(0, 9, size=(4, 5, 6)).astype(np.uint8)
    # layer voxel (i, j, k) sits at display voxel (5 - k, j, i): display = P @ layer
    p = np.zeros((4, 4))
    p[0, 2] = -1
    p[0, 3] = 5
    p[1, 1] = 1
    p[2, 0] = 1
    p[3, 3] = 1
    disp = affine((0.5, 0.5, 0.5), rot(2, 33), (1, 1, 1))
    layer = disp @ p
    disp_vol = np.transpose(vol, (2, 1, 0))[::-1]  # shape (6, 5, 4)
    m = rs.display_to_layer_matrix(disp, layer)
    for axis in range(3):
        for fast in (True, False):
            out = rs.sample_slice(vol, m, disp_vol.shape, axis, 2, interpolation="nearest", fast=fast)
            np.testing.assert_array_equal(out, np.take(disp_vol, 2, axis=axis))


# ---- linear ---------------------------------------------------------------------------

def test_linear_identity_is_exact():
    rng = np.random.default_rng(2)
    vol = rng.standard_normal((5, 6, 7))
    a = affine((0.2, 0.2, 0.6))
    m = rs.display_to_layer_matrix(a, a)
    out = rs.sample_linear(vol, rs.map_indices(m, rs.slice_index_grid(vol.shape, 2, 3)))
    assert out.dtype == np.float64
    np.testing.assert_array_equal(out, vol[:, :, 3])


def test_oblique_identity_is_exact_on_both_paths():
    rng = np.random.default_rng(3)
    vol = rng.standard_normal((6, 5, 4))
    a = affine((0.31, 0.27, 0.73), rot(0, 17) @ rot(2, -29), (3.3, -1.1, 0.7))
    m = rs.display_to_layer_matrix(a, a)  # identity up to float noise
    assert rs.signed_permutation(m) is not None
    for axis in range(3):
        for fast in (True, False):
            out = rs.sample_slice(vol, m, vol.shape, axis, 1, fast=fast)
            np.testing.assert_array_equal(out, np.take(vol, 1, axis=axis))


def _linear_field_case():
    g = np.array([0.7, -1.3, 2.1])
    b = 5.0
    layer = affine((0.3, 0.25, 0.45), rot(2, 30) @ rot(0, 17), (-3.0, 1.5, 0.8))
    disp = affine((0.2, 0.35, 0.3), rot(1, -12), (-2.0, 0.0, 1.0))
    n = (20, 22, 18)
    ijk = np.stack(np.meshgrid(*[np.arange(k) for k in n], indexing="ij"), -1).reshape(-1, 3)
    world = (layer[:3, :3] @ ijk.T).T + layer[:3, 3]
    vol = (world @ g + b).reshape(n)
    return g, b, layer, disp, n, vol


def test_linear_field_on_oblique_grids_is_reproduced():
    g, b, layer, disp, n, vol = _linear_field_case()
    m = rs.display_to_layer_matrix(disp, layer)
    checked = 0
    for axis, idx in ((0, 4), (1, 9), (2, 6)):
        grid = rs.slice_index_grid((14, 14, 14), axis, idx)
        c = rs.map_indices(m, grid)
        out = rs.sample_slice(vol, m, (14, 14, 14), axis, idx)
        dw = (disp[:3, :3] @ grid.reshape(-1, 3).T).T + disp[:3, 3]
        expect = (dw @ g + b).reshape(out.shape)
        inside = np.all((c >= 0) & (c <= np.array(n) - 1), axis=-1)
        outside = np.any((c < -0.5) | (c >= np.array(n) - 0.5), axis=-1)
        np.testing.assert_allclose(out[inside], expect[inside], atol=1e-9)
        assert np.all(np.isnan(out[outside]))
        checked += int(inside.sum())
    assert checked > 50


def test_half_voxel_band_on_oblique_grids_takes_the_clamped_value():
    # v0.1: points in the half-voxel band (-0.5 <= l < 0 or n-1 < l < n-0.5 on an axis,
    # inside the box) take the value at the clamped index.
    g, b, layer, disp, n, vol = _linear_field_case()
    m = rs.display_to_layer_matrix(disp, layer)
    nn = np.array(n)
    band_total = 0
    for axis, idx in ((0, 4), (1, 9), (2, 6)):
        grid = rs.slice_index_grid((14, 14, 14), axis, idx)
        c = rs.map_indices(m, grid)
        out = rs.sample_slice(vol, m, (14, 14, 14), axis, idx)
        in_box = np.all((c >= -0.5) & (c < nn - 0.5), axis=-1)
        in_core = np.all((c >= 0) & (c <= nn - 1), axis=-1)
        band = in_box & ~in_core
        cc = np.clip(c[band], 0, nn - 1)
        expect = ((layer[:3, :3] @ cc.T).T + layer[:3, 3]) @ g + b
        np.testing.assert_allclose(out[band], expect, atol=1e-9)
        band_total += int(band.sum())
    assert band_total > 0


def test_half_voxel_border_is_clamped_to_edge():
    vol = np.array([10.0, 20.0, 30.0]).reshape(3, 1, 1)
    pts = np.array([[x, 0, 0] for x in (-0.5, -0.51, 0.0, 0.5, 2.0, 2.49, 2.5)], float)
    out = rs.sample_linear(vol, pts)
    np.testing.assert_allclose(out[[0, 2, 3, 4, 5]], [10, 10, 15, 30, 30])
    assert np.isnan(out[1]) and np.isnan(out[6])


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_zero_weight_nan_corner_is_ignored_on_every_axis(axis):
    base = np.array([1.0, np.nan, 3.0])
    shape = [1, 1, 1]
    shape[axis] = 3
    vol = base.reshape(shape)

    def pt(x):
        p = [0.0, 0.0, 0.0]
        p[axis] = x
        return p

    out = rs.sample_linear(vol, np.array([pt(0.0), pt(2.0), pt(0.5)]))
    assert out[0] == 1.0
    assert out[1] == 3.0
    assert np.isnan(out[2])


def test_single_slice_axis():
    vol = np.arange(6, dtype=float).reshape(2, 3, 1)
    out = rs.sample_linear(vol, np.array([[0.5, 1.0, 0.0], [0.5, 1.0, 0.4], [0.5, 1.0, 0.6]]))
    np.testing.assert_allclose(out[:2], [2.5, 2.5])
    assert np.isnan(out[2])


def test_custom_fill():
    vol = np.ones((2, 2, 2))
    assert rs.sample_linear(vol, np.array([[5.0, 0, 0]]), fill=-1.0)[0] == -1.0


# ---- fast path ------------------------------------------------------------------------

def test_signed_permutation_detection():
    assert rs.signed_permutation(np.eye(4)) is not None
    flip = np.eye(4)
    flip[0, 0] = -1
    flip[0, 3] = 4 + 5e-7
    r, t = rs.signed_permutation(flip)
    np.testing.assert_array_equal(t, [4, 0, 0])
    half = np.eye(4)
    half[1, 3] = 0.5
    assert rs.signed_permutation(half) is None  # offset not an integer
    scaled = np.eye(4)
    scaled[2, 2] = 2.0
    assert rs.signed_permutation(scaled) is None
    rotated = rot(2, 30)
    assert rs.signed_permutation(rotated) is None
    double = np.zeros((4, 4))
    double[0, 0] = double[1, 0] = double[2, 2] = double[3, 3] = 1
    assert rs.signed_permutation(double) is None


@pytest.mark.parametrize("interpolation", ["nearest", "linear"])
def test_fast_path_equals_general_path_including_out_of_range(interpolation):
    rng = np.random.default_rng(5)
    vol = rng.integers(1, 100, size=(5, 4, 6)).astype(np.int32)
    m = np.zeros((4, 4))
    m[0, 1] = 1     # layer i = display j
    m[1, 2] = -1    # layer j = 5 - display k (runs past both ends for k > 5 and k < 2)
    m[1, 3] = 5
    m[2, 0] = 1     # layer k = display i - 2 (negative for i < 2)
    m[2, 3] = -2
    m[3, 3] = 1
    disp_shape = (9, 7, 8)
    assert rs.signed_permutation(m) is not None
    for axis in range(3):
        for idx in (0, 3, disp_shape[axis] - 1):
            a = rs.sample_slice(vol, m, disp_shape, axis, idx, interpolation=interpolation, fast=True)
            b = rs.sample_slice(vol, m, disp_shape, axis, idx, interpolation=interpolation, fast=False)
            assert a.dtype == b.dtype
            np.testing.assert_array_equal(a, b)
    out = rs.sample_slice(vol, m, disp_shape, 2, 7, interpolation=interpolation)
    fill_count = int(np.sum(out == 0)) if interpolation == "nearest" else int(np.sum(np.isnan(out)))
    assert fill_count == out.size  # k = 7 -> layer j = -2, all outside


# ---- grids and spaces -----------------------------------------------------------------

def test_grid_validation_and_space_refusal():
    g = rs.Grid((4, 5, 6), affine((0.5, 0.5, 1.0)), "scanner")
    assert g.voxel_volume_mm3 == pytest.approx(0.25)
    with pytest.raises(ValueError):
        rs.Grid((4, 5), np.eye(4))
    with pytest.raises(ValueError):
        rs.Grid((4, 5, 6), np.zeros((4, 4)))
    with pytest.raises(ValueError):
        rs.Grid((4, 5, 6), np.eye(3))
    other = rs.Grid((4, 5, 6), np.eye(4), "subject_ras")
    with pytest.raises(rs.SpaceMismatchError):
        rs.grid_matrix(g, other)
    np.testing.assert_allclose(rs.grid_matrix(g, g), np.eye(4), atol=1e-12)


def test_sample_slice_rejects_bad_input():
    with pytest.raises(ValueError):
        rs.sample_slice(np.zeros((2, 2)), np.eye(4), (2, 2, 2), 0, 0)
    with pytest.raises(ValueError):
        rs.sample_slice(np.zeros((2, 2, 2)), np.eye(4), (2, 2, 2), 0, 0, interpolation="cubic")
    with pytest.raises(ValueError):
        rs.slice_index_grid((2, 2, 2), 3, 0)
