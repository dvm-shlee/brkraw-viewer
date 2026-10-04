"""Grids and on-demand slice resampling (layer core contract C1 and C3, WI-0072).

A layer's grid is ``(shape[:3], A)``: ``A`` maps voxel index -> world mm in one named
space, integer indices are voxel centres. The display grid ``D = (S_D, A_D)`` is the base
layer after ``reorient_to_ras`` (axis permutation and flips only). A pixel of a display
slice with display index ``d`` reads the layer at ``l = M d`` with
``M = inv(A_L) @ A_D``. Only the displayed slice is sampled; nothing resampled is kept.

numpy only; no Tk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

import numpy as np

#: Components of ``M d`` within this distance of a multiple of 0.5 are snapped to it, and
#: matrix entries within it of an integer count as integers for the fast path.
SNAP_TOL = 1e-6

INTERPOLATIONS = ("linear", "nearest")


class SpaceMismatchError(ValueError):
    """A layer is in another coordinate space than the base (no silent conversion, C1)."""


@dataclass(frozen=True)
class Grid:
    """Voxel grid of a layer: 3D shape, 4x4 index->world affine and the space name."""

    shape: Tuple[int, int, int]
    affine: np.ndarray = field(repr=False)
    space: str = "scanner"

    def __post_init__(self) -> None:
        shape = tuple(int(n) for n in self.shape)
        if len(shape) != 3 or min(shape) < 1:
            raise ValueError(f"grid shape must be three positive ints, got {self.shape!r}")
        aff = np.array(self.affine, dtype=np.float64)
        if aff.shape != (4, 4):
            raise ValueError(f"grid affine must be 4x4, got {aff.shape}")
        if not np.all(np.isfinite(aff)):
            raise ValueError("grid affine must be finite")
        if abs(np.linalg.det(aff[:3, :3])) < 1e-12:
            raise ValueError("grid affine is singular")
        aff.setflags(write=False)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "affine", aff)
        object.__setattr__(self, "space", str(self.space))

    @property
    def voxel_volume_mm3(self) -> float:
        return float(abs(np.linalg.det(self.affine[:3, :3])))


def display_to_layer_matrix(display_affine: np.ndarray, layer_affine: np.ndarray) -> np.ndarray:
    """``M = inv(A_L) @ A_D``: display index -> layer index."""
    return np.linalg.inv(np.asarray(layer_affine, dtype=np.float64)) @ np.asarray(
        display_affine, dtype=np.float64
    )


def grid_matrix(display: Grid, layer: Grid) -> np.ndarray:
    """``M`` for a layer on the display grid; refuses a layer in another space (C1)."""
    if display.space != layer.space:
        raise SpaceMismatchError(
            f"layer is in space {layer.space!r} but the display is in {display.space!r}; "
            "convert it explicitly first"
        )
    return display_to_layer_matrix(display.affine, layer.affine)


def slice_index_grid(display_shape: Sequence[int], axis: int, index: int) -> np.ndarray:
    """Display indices of one slice, shape ``(a, b, 3)`` float64.

    The two remaining axes keep their order, so the result lines up with
    ``np.take(display_volume, index, axis=axis)``.
    """
    if axis not in (0, 1, 2):
        raise ValueError(f"axis must be 0, 1 or 2, got {axis!r}")
    others = [d for d in range(3) if d != axis]
    a, b = (int(display_shape[d]) for d in others)
    g = np.empty((a, b, 3), dtype=np.float64)
    u, v = np.meshgrid(np.arange(a), np.arange(b), indexing="ij")
    g[..., others[0]] = u
    g[..., others[1]] = v
    g[..., axis] = float(index)
    return g


def map_indices(matrix: np.ndarray, ijk: np.ndarray) -> np.ndarray:
    """Apply ``M`` to ``(..., 3)`` indices; snap components within SNAP_TOL of k/2 to k/2."""
    m = np.asarray(matrix, dtype=np.float64)
    out = np.asarray(ijk, dtype=np.float64) @ m[:3, :3].T + m[:3, 3]
    half = np.round(out * 2.0) / 2.0
    return np.where(np.abs(out - half) < SNAP_TOL, half, out)


def signed_permutation(matrix: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """``(R, t)`` with integer ``R`` (signed permutation) and integer ``t`` when ``M`` is one
    within SNAP_TOL (the same-grid fast path), else None."""
    m = np.asarray(matrix, dtype=np.float64)
    lin = m[:3, :3]
    r = np.round(lin)
    if np.any(np.abs(lin - r) >= SNAP_TOL) or not np.all(np.isin(r, (-1.0, 0.0, 1.0))):
        return None
    if not (np.all(np.abs(r).sum(axis=0) == 1) and np.all(np.abs(r).sum(axis=1) == 1)):
        return None
    t = np.round(m[:3, 3])
    if np.any(np.abs(m[:3, 3] - t) >= SNAP_TOL):
        return None
    return r.astype(np.int64), t.astype(np.int64)


def _fill_dtype(volume: np.ndarray, fill: object) -> np.dtype:
    f = np.asarray(fill)
    if f.dtype.kind == "f" and np.isnan(f) and volume.dtype.kind not in "fc":
        return np.dtype(np.float64)
    return volume.dtype


def sample_nearest(volume: np.ndarray, coords: np.ndarray, fill: object = 0) -> np.ndarray:
    """Nearest-neighbour sampling: ``idx = floor(l + 0.5)`` (round half up), valid when
    ``0 <= idx <= n - 1`` on every axis, else ``fill``. Keeps the volume dtype unless the
    fill is NaN and the volume is integer (then float64)."""
    vol = np.asarray(volume)
    n = np.asarray(vol.shape[:3])
    idx = np.floor(np.asarray(coords, dtype=np.float64) + 0.5).astype(np.int64)
    valid = np.all((idx >= 0) & (idx <= n - 1), axis=-1)
    safe = np.where(valid[..., None], idx, 0)
    dtype = _fill_dtype(vol, fill)
    out = vol[safe[..., 0], safe[..., 1], safe[..., 2]].astype(dtype, copy=False)
    return np.where(valid, out, np.asarray(fill).astype(dtype))


def sample_linear(volume: np.ndarray, coords: np.ndarray, fill: float = np.nan) -> np.ndarray:
    """Trilinear sampling (float64). Valid on the half-open box ``-0.5 <= l < n - 0.5`` (the
    nearest footprint), coordinates clamped to ``[0, n - 1]``; a corner with weight 0 never
    contributes, so a NaN next to an exactly hit voxel does not spread; outside -> ``fill``."""
    vol = np.asarray(volume)
    c = np.asarray(coords, dtype=np.float64)
    n = np.asarray(vol.shape[:3])
    valid = np.all((c >= -0.5) & (c < n - 0.5), axis=-1)
    c = np.clip(c, 0, n - 1)
    i0 = np.minimum(np.floor(c), np.maximum(n - 2, 0)).astype(np.int64)
    t = np.where(n == 1, 0.0, c - i0)
    i1 = np.where(n == 1, i0, i0 + 1)
    acc = np.zeros(c.shape[:-1], dtype=np.float64)
    for k0 in (0, 1):
        for k1 in (0, 1):
            for k2 in (0, 1):
                w = np.ones(c.shape[:-1], dtype=np.float64)
                ix = []
                for d, k in enumerate((k0, k1, k2)):
                    w = w * (t[..., d] if k else 1.0 - t[..., d])
                    ix.append(i1[..., d] if k else i0[..., d])
                val = vol[ix[0], ix[1], ix[2]].astype(np.float64)
                acc = acc + np.where(w != 0, w * val, 0.0)
    return np.where(valid, acc, fill)


def _fast_slice(volume: np.ndarray, rt: Tuple[np.ndarray, np.ndarray], grid: np.ndarray,
                fill: object, dtype: np.dtype) -> np.ndarray:
    r, t = rt
    d = grid.astype(np.int64)
    idx = d @ r.T + t
    n = np.asarray(volume.shape[:3])
    valid = np.all((idx >= 0) & (idx <= n - 1), axis=-1)
    safe = np.where(valid[..., None], idx, 0)
    out = np.asarray(volume)[safe[..., 0], safe[..., 1], safe[..., 2]].astype(dtype, copy=False)
    return np.where(valid, out, np.asarray(fill).astype(dtype))


def sample_slice(
    volume: np.ndarray,
    matrix: np.ndarray,
    display_shape: Sequence[int],
    axis: int,
    index: int,
    *,
    interpolation: str = "linear",
    fill: Optional[object] = None,
    fast: bool = True,
) -> np.ndarray:
    """One display slice of a 3D layer volume (C3).

    ``interpolation``: ``"linear"`` (images, float64, default fill NaN) or ``"nearest"``
    (labels, default fill 0, dtype kept). When ``M`` is a signed permutation with integer
    offset (same grid up to flips/permutation) the values are indexed directly; the result
    equals the general path, including the fill outside the layer.
    """
    vol = np.asarray(volume)
    if vol.ndim != 3:
        raise ValueError(f"sample_slice takes one 3D frame, got ndim={vol.ndim}")
    if interpolation not in INTERPOLATIONS:
        raise ValueError(f"interpolation must be one of {INTERPOLATIONS}, got {interpolation!r}")
    if fill is None:
        fill = np.nan if interpolation == "linear" else 0
    grid = slice_index_grid(display_shape, axis, index)
    rt = signed_permutation(matrix) if fast else None
    if rt is not None:
        if interpolation == "linear":
            dtype = np.dtype(np.float64)
        else:
            dtype = _fill_dtype(vol, fill)
        return _fast_slice(vol, rt, grid, fill, dtype)
    coords = map_indices(matrix, grid)
    if interpolation == "nearest":
        return sample_nearest(vol, coords, fill)
    return sample_linear(vol, coords, fill=float(fill))
