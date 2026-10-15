"""ROI masks and statistics on one display slice (WI-0072, contract C6)."""

import math
from typing import Tuple, Dict, Any, Optional, Sequence
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


# View plane -> slice axis. The base images are xy = (y, x), xz = (z, x), zy = (y, z) as
# (row, col); the ROI plane is laid out like volume.take(index, axis), so u, v are the two
# remaining axes in order.
_PLANE_AXIS = {"xy": 2, "xz": 1, "zy": 0}
ROI_TOOLS = ("off", "square", "circle")


def plane_axis(plane: str) -> int:
    """Slice axis (0, 1, 2) shown by a view plane ('xy', 'xz' or 'zy')."""
    try:
        return _PLANE_AXIS[plane]
    except KeyError:
        raise ValueError(f"unknown plane {plane!r}; expected 'xy', 'xz' or 'zy'") from None


def rc_to_uv(plane: str, row: float, col: float) -> Tuple[float, float]:
    """Image (row, col) of a view plane to ROI slice pixels (u, v)."""
    plane_axis(plane)
    # xy and xz images are transposed (row = v, col = u); zy is stored as (u, v).
    return (float(row), float(col)) if plane == "zy" else (float(col), float(row))


def uv_to_rc(plane: str, u: float, v: float) -> Tuple[float, float]:
    """ROI slice pixels (u, v) back to image (row, col) of a view plane."""
    plane_axis(plane)
    return (float(u), float(v)) if plane == "zy" else (float(v), float(u))


def roi_extent(plane: str, shape: str, geometry: Sequence[float]) -> Tuple[float, float, float, float]:
    """Pixel-edge extent (row0, row1, col0, col1) of a ROI in a view plane, for drawing.

    Edges are in image index space (pixel i spans i to i + 1).
    """
    if shape not in ROI_SHAPES:
        raise ValueError(f"unknown ROI shape {shape!r}; expected 'rect' or 'ellipse'")
    if len(geometry) != 4:
        raise ValueError(f"geometry for {shape!r} must have 4 values")
    g = [float(x) for x in geometry]
    if shape == "rect":
        u0, u1 = min(g[0], g[1]), max(g[0], g[1]) + 1.0
        v0, v1 = min(g[2], g[3]), max(g[2], g[3]) + 1.0
    else:
        u0, u1 = g[0] - g[2] + 0.5, g[0] + g[2] + 0.5
        v0, v1 = g[1] - g[3] + 0.5, g[1] + g[3] + 0.5
    ra, ca = uv_to_rc(plane, u0, v0)
    rb, cb = uv_to_rc(plane, u1, v1)
    return min(ra, rb), max(ra, rb), min(ca, cb), max(ca, cb)


class RoiDrag:
    """Tk-free state of the ROI tool on the Viewer tab: tool choice and one drag at a time.

    press / move / release take image (row, col) of one view plane. release returns
    (axis, shape, geometry) for the controller's set_roi, or None when the drag was empty or
    the tool is off. cancel (Esc) drops a drag in progress.
    """

    def __init__(self) -> None:
        self.tool = "off"
        self._plane: Optional[str] = None
        self._start: Optional[Tuple[float, float]] = None
        self._end: Optional[Tuple[float, float]] = None

    @property
    def active(self) -> bool:
        return self.tool != "off"

    @property
    def dragging(self) -> bool:
        return self._start is not None

    def set_tool(self, tool: str) -> None:
        if tool not in ROI_TOOLS:
            raise ValueError(f"unknown ROI tool {tool!r}; expected one of {ROI_TOOLS}")
        self.tool = tool
        self.cancel()

    def cancel(self) -> None:
        self._plane = self._start = self._end = None

    def press(self, plane: str, row: float, col: float) -> bool:
        if not self.active:
            return False
        plane_axis(plane)
        self._plane = plane
        self._start = self._end = rc_to_uv(plane, row, col)
        return True

    def move(self, plane: str, row: float, col: float) -> Optional[Tuple[str, str, Tuple[float, float, float, float]]]:
        """Update the drag; returns (shape, extent) to draw as (plane, shape, extent), or None."""
        if self._start is None or plane != self._plane:
            return None
        self._end = rc_to_uv(plane, row, col)
        if self._end == self._start:
            return None
        shape, geom = drag_geometry(self.tool, self._start, self._end)
        return plane, shape, roi_extent(plane, shape, geom)

    def release(self, plane: str, row: float, col: float) -> Optional[Tuple[int, str, Tuple[float, ...]]]:
        if self._start is None or plane != self._plane:
            self.cancel()
            return None
        start, end = self._start, rc_to_uv(plane, row, col)
        self.cancel()
        if start == end:  # a click without a drag sets nothing
            return None
        shape, geom = drag_geometry(self.tool, start, end)
        return plane_axis(plane), shape, tuple(geom)
