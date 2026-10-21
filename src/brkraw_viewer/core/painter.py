"""Label painter core (WI-0049, stage 3 design WI-B), pure numpy and Tk-free.

The stamp footprint and the Bresenham line are ported from
ui/components/label_painter.py (_apply_brush, _iter_line_rc).
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

BRUSH_MODES = ("paint", "erase")
BRUSH_SHAPES = ("disc", "square")

BBox = Tuple[int, int, int, int]


def _union(a: Optional[BBox], b: Optional[BBox]) -> Optional[BBox]:
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def iter_line_rc(r0: int, c0: int, r1: int, c1: int):
    """Yield (row, col) along a line in index space (Bresenham)."""
    r0, c0, r1, c1 = int(r0), int(c0), int(r1), int(c1)
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r0 < r1 else -1
    sc = 1 if c0 < c1 else -1
    err = dr - dc
    r, c = r0, c0
    while True:
        yield r, c
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r += sr
        if e2 < dr:
            err += dr
            c += sc


class LabelEditor:
    """Edit an integer 3-D label array in place with a brush and per-stroke undo.

    The slice for ``axis`` is the array with that axis dropped; row and col index
    the two remaining axes in array order.
    """

    def __init__(self, data: np.ndarray, *, max_undo_bytes: int = 64 * 2**20,
                 shape: str = "disc") -> None:
        if not isinstance(data, np.ndarray) or data.ndim != 3:
            got = getattr(data, "shape", type(data).__name__)
            raise ValueError(f"data: got {got}, expected a 3-D numpy array")
        if data.dtype.kind not in "iu":
            raise ValueError(f"data: got dtype {data.dtype}, expected an integer dtype")
        if int(max_undo_bytes) < 0:
            raise ValueError(f"max_undo_bytes: got {max_undo_bytes}, expected >= 0")
        if shape not in BRUSH_SHAPES:
            raise ValueError(f"shape: got {shape!r}, expected one of {list(BRUSH_SHAPES)}")
        self.data = data
        self.max_undo_bytes = int(max_undo_bytes)
        self.shape = shape
        self.brush_size = 1
        self._mode = "paint"
        self._label = 1
        self._undo: List[Tuple[np.ndarray, np.ndarray]] = []
        self._undo_bytes = 0
        self._active: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None

    # -- settings ---------------------------------------------------------
    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in BRUSH_MODES:
            raise ValueError(f"mode: got {value!r}, expected one of {list(BRUSH_MODES)}")
        self._mode = value

    @property
    def label(self) -> int:
        return self._label

    @label.setter
    def label(self, value: int) -> None:
        try:
            ok = not isinstance(value, bool) and int(value) == value and int(value) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError(f"label: got {value!r}, expected an integer > 0")
        self._label = int(value)

    def set_brush(self, size: int) -> None:
        try:
            ok = not isinstance(size, bool) and int(size) == size and int(size) >= 1
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise ValueError(f"brush_size: got {size!r}, expected an integer >= 1")
        self.brush_size = int(size)

    # -- painting ---------------------------------------------------------
    def _value(self) -> int:
        if self._mode == "erase":
            return 0
        info = np.iinfo(self.data.dtype)
        if self._label > info.max:
            raise ValueError(f"label: got {self._label}, expected <= {info.max} for dtype {self.data.dtype}")
        return self._label

    def _slice_dims(self, axis: int) -> Tuple[int, int]:
        if isinstance(axis, bool) or axis not in (0, 1, 2):
            raise ValueError(f"axis: got {axis!r}, expected one of [0, 1, 2]")
        rest = [a for a in range(3) if a != axis]
        return rest[0], rest[1]

    def _dab(self, axis: int, index: int, row: int, col: int, value: int) -> Optional[BBox]:
        ra, ca = self._slice_dims(axis)
        h, w = self.data.shape[ra], self.data.shape[ca]
        index = int(index)
        if not (0 <= index < self.data.shape[axis]) or not (0 <= row < h) or not (0 <= col < w):
            return None
        size = self.brush_size
        half_lo = (size - 1) // 2
        half_hi = size // 2
        r0, r1 = max(0, row - half_lo), min(h - 1, row + half_hi)
        c0, c1 = max(0, col - half_lo), min(w - 1, col + half_hi)
        yy, xx = np.ogrid[r0 : r1 + 1, c0 : c1 + 1]
        if self.shape == "square" or size == 1:
            mask = np.ones((r1 - r0 + 1, c1 - c0 + 1), dtype=bool)
        else:
            eff_r = min(half_lo, half_hi)
            mask = (yy - row) ** 2 + (xx - col) ** 2 <= eff_r * eff_r
        sel: List[object] = [index, index, index]
        sel[ra] = slice(r0, r1 + 1)
        sel[ca] = slice(c0, c1 + 1)
        sub = self.data[tuple(sel)]
        changed = mask & (sub != value)
        rr, cc = np.nonzero(changed)
        if rr.size:
            coords: List[object] = [index, index, index]
            coords[ra] = rr + r0
            coords[ca] = cc + c0
            key = tuple(coords)
            flat = np.ravel_multi_index(key, self.data.shape)
            old = self.data[key].copy()
            self.data[key] = value
            if self._active is not None:
                self._active.append((flat, old))
        return (r0, c0, r1, c1)

    def _run(self, fn):
        own = self._active is None
        if own:
            self.begin_stroke()
        try:
            return fn()
        finally:
            if own:
                self.end_stroke()

    def stamp(self, axis: int, index: int, row: float, col: float) -> Optional[BBox]:
        """One dab; returns the slice bbox (r0, c0, r1, c1), None if outside."""
        value = self._value()
        r, c = int(round(row)), int(round(col))
        return self._run(lambda: self._dab(axis, index, r, c, value))

    def stroke(self, axis: int, index: int, points: Sequence[Tuple[float, float]]) -> Optional[BBox]:
        """Dabs along the segments between successive points, no gaps."""
        value = self._value()
        pts = [(int(round(r)), int(round(c))) for r, c in points]

        def go() -> Optional[BBox]:
            box: Optional[BBox] = None
            if len(pts) == 1:
                return self._dab(axis, index, pts[0][0], pts[0][1], value)
            for (ra, ca), (rb, cb) in zip(pts[:-1], pts[1:]):
                for r, c in iter_line_rc(ra, ca, rb, cb):
                    box = _union(box, self._dab(axis, index, r, c, value))
            return box

        return self._run(go)

    # -- undo -------------------------------------------------------------
    def begin_stroke(self) -> None:
        if self._active is None:
            self._active = []

    def end_stroke(self) -> None:
        parts, self._active = self._active, None
        if not parts:
            return
        flat = np.concatenate([p[0] for p in parts])
        old = np.concatenate([p[1] for p in parts])
        flat, first = np.unique(flat, return_index=True)  # keep earliest old value per voxel
        old = old[first]
        self._undo.append((flat, old))
        self._undo_bytes += flat.nbytes + old.nbytes
        while self._undo and self._undo_bytes > self.max_undo_bytes:
            f, o = self._undo.pop(0)
            self._undo_bytes -= f.nbytes + o.nbytes

    def undo(self) -> bool:
        if self._active is not None:
            self.end_stroke()
        if not self._undo:
            return False
        flat, old = self._undo.pop()
        self._undo_bytes -= flat.nbytes + old.nbytes
        self.data[np.unravel_index(flat, self.data.shape)] = old
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)
