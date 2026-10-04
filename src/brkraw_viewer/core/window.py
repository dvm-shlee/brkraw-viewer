"""Default display window of a layer frame (layer core contract C5, WI-0072).

The window is computed once per loaded 3D frame from the whole frame, not from the
slice on screen, so every slice of the frame is shown with the same brightness.
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

#: Upper bound on the number of voxels the default window reads (strided subsample).
MAX_WINDOW_SAMPLES = 1_000_000
#: Percentiles of the finite values used as (vmin, vmax).
WINDOW_PERCENTILES = (1.0, 99.0)

Window = Tuple[float, float]


def window_sample(frame: np.ndarray, max_samples: int = MAX_WINDOW_SAMPLES) -> np.ndarray:
    """Deterministic strided subsample of ``frame`` (all voxels when it is small enough).

    Every ``step``-th voxel in C order, ``step = ceil(size / max_samples)``. Reads through
    ``ndarray.flat`` so a non-contiguous frame (one frame of a 4D array) is not copied whole.
    Complex values are replaced by their magnitude (as the viewport displays them).
    """
    a = np.asarray(frame)
    if max_samples < 1:
        raise ValueError("max_samples must be >= 1")
    size = int(a.size)
    if size == 0:
        return np.empty(0, dtype=np.float64)
    step = max(1, math.ceil(size / int(max_samples)))
    sample = a.reshape(-1) if (step == 1 and a.flags.c_contiguous) else a.flat[::step]
    sample = np.asarray(sample)
    if np.iscomplexobj(sample):
        sample = np.abs(sample)
    return sample.astype(np.float64, copy=False)


def default_window(frame: np.ndarray, max_samples: int = MAX_WINDOW_SAMPLES) -> Window:
    """(vmin, vmax) = 1st and 99th percentile of the finite values of the whole frame.

    Uses :func:`window_sample`. With no finite value the window is (0.0, 1.0); when the
    two percentiles are equal (a constant frame) ``vmax = vmin + 1.0``, matching the
    viewport's earlier per-slice rule.
    """
    sample = window_sample(frame, max_samples)
    finite = sample[np.isfinite(sample)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo, hi = np.percentile(finite, WINDOW_PERCENTILES)
    vmin, vmax = float(lo), float(hi)
    if np.isclose(vmin, vmax):
        vmax = vmin + 1.0
    return (vmin, vmax)


def normalize_window(window: object) -> Window | None:
    """A user or default window as a float pair, or None when it is not usable."""
    if window is None:
        return None
    try:
        vmin, vmax = (float(window[0]), float(window[1]))  # type: ignore[index]
    except Exception:
        return None
    if not (math.isfinite(vmin) and math.isfinite(vmax)):
        return None
    if vmax <= vmin or np.isclose(vmin, vmax):
        vmax = vmin + 1.0
    return (vmin, vmax)
