"""ROI masks and statistics on one display slice (WI-0072, contract C6)."""

import math
from typing import Tuple, Dict, Any
import numpy as np


def rect_mask(shape: Tuple[int, int], u0: float, u1: float, v0: float, v1: float) -> np.ndarray:
    nu, nv = shape
    if nu < 1 or nv < 1:
        raise ValueError("shape must be >= 1")

    ulo, uhi = min(u0, u1), max(u0, u1)
    vlo, vhi = min(v0, v1), max(v0, v1)

    u = np.arange(nu)[:, None]
    v = np.arange(nv)[None, :]

    return (u >= ulo) & (u <= uhi) & (v >= vlo) & (v <= vhi)


def ellipse_mask(shape: Tuple[int, int], cu: float, cv: float, ru: float, rv: float) -> np.ndarray:
    nu, nv = shape
    if nu < 1 or nv < 1:
        raise ValueError("shape must be >= 1")
    if ru <= 0 or rv <= 0:
        raise ValueError("radius must be > 0")

    u = np.arange(nu)[:, None]
    v = np.arange(nv)[None, :]

    return ((u - cu) / ru) ** 2 + ((v - cv) / rv) ** 2 <= 1.0


def roi_stats(values: np.ndarray, mask: np.ndarray, affine: np.ndarray) -> Dict[str, Any]:
    x = np.asarray(values, dtype=np.float64)
    m = np.asarray(mask, dtype=bool)
    if x.shape != m.shape:
        raise ValueError("shape of values and mask must match")

    aff = np.asarray(affine, dtype=np.float64)
    voxel_mm3 = abs(float(np.linalg.det(aff[:3, :3])))

    sel = x[m]
    n_mask = int(sel.size)
    good = sel[np.isfinite(sel)]
    n = int(good.size)
    n_nan = n_mask - n

    res = {
        "n_mask": n_mask,
        "n": n,
        "n_nan": n_nan,
        "mean": float(np.mean(good)) if n > 0 else math.nan,
        "std": float(np.std(good, ddof=1)) if n >= 2 else math.nan,
        "min": float(np.min(good)) if n > 0 else math.nan,
        "max": float(np.max(good)) if n > 0 else math.nan,
        "median": float(np.median(good)) if n > 0 else math.nan,
        "volume_mm3": float(n * voxel_mm3),
        "mask_mm3": float(n_mask * voxel_mm3),
    }
    return res
