"""ROI masks and statistics on one display slice (WI-0072, contract C6)."""

import math
from typing import Tuple, Dict, Any, Sequence
import numpy as np


ROI_SHAPES = ("rect", "ellipse")


def drag_geometry(tool: str, start_uv: Tuple[float, float], end_uv: Tuple[float, float]) -> Tuple[str, Tuple[float, ...]]:
    """Turn a drag operation into an ROI shape and geometry.

    Parameters
    ----------
    tool : str
        'square' or 'circle'.
    start_uv : (u, v)
        Start point of the drag in pixels.
    end_uv : (u, v)
        End point of the drag in pixels.

    Returns
    -------
    (shape, geometry)
        For 'square': ('rect', (u0, u1, v0, v1)) where u0, u1 are min/max of u, etc.
        For 'circle': ('ellipse', (cu, cv, r, r)) where (cu, cv) is the center and r is
        half the distance between start and end.

    Raises
    ------
    ValueError
        If tool is not 'square' or 'circle', or if start and end points are identical.
    """
    u0, v0 = start_uv
    u1, v1 = end_uv

    if u0 == u1 and v0 == v1:
        raise ValueError("drag start and end points must be different")

    if tool == "square":
        return "rect", (min(u0, u1), max(u0, u1), min(v0, v1), max(v0, v1))
    if tool == "circle":
        cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
        r = math.sqrt((u1 - u0)**2 + (v1 - v0)**2) / 2
        return "ellipse", (cu, cv, r, r)

    raise ValueError(f"unknown tool {tool!r}; expected 'square' or 'circle'")


def roi_mask(shape: str, slice_shape: Tuple[int, int], geometry: Sequence[float]) -> np.ndarray:
    """Boolean mask of a temporary ROI on one display slice, clipped to the slice.

    Parameters
    ----------
    shape : str
        "rect" or "ellipse".
    slice_shape : (int, int)
        Size (nu, nv) of the display slice in pixels.
    geometry : sequence of float
        For "rect": (u0, u1, v0, v1), inclusive pixel bounds; the corners may be given in either order.
        For "ellipse": (cu, cv, ru, rv), centre and radii in pixels.

    Returns
    -------
    numpy.ndarray
        Bool array of shape ``slice_shape``. A ROI that extends past the slice keeps only the inside
        part; a ROI fully outside the slice gives an all-False mask.

    Raises
    ------
    ValueError
        If ``shape`` is unknown, ``geometry`` has the wrong length or is not finite, or the
        slice or radii are invalid (raised by ``rect_mask`` / ``ellipse_mask``).
    """
    if shape not in ROI_SHAPES:
        raise ValueError(f"unknown ROI shape {shape!r}; expected 'rect' or 'ellipse'")
    if len(slice_shape) != 2:
        raise ValueError("slice_shape must be (nu, nv)")
    nu, nv = int(slice_shape[0]), int(slice_shape[1])

    if len(geometry) != 4:
        raise ValueError(f"geometry for {shape!r} must have 4 values")
    g = [float(x) for x in geometry]
    if not all(math.isfinite(x) for x in g):
        raise ValueError("geometry values must be finite")

    if shape == "rect":
        return rect_mask((nu, nv), g[0], g[1], g[2], g[3])
    return ellipse_mask((nu, nv), g[0], g[1], g[2], g[3])


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
