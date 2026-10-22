"""Tk-free layer handle over LayerStack and the layer data dict (WI-0067, stage 4 item 1).

Implements the note design-stage4-handle.md (Surface, Errors, Copy vs view). Director
answers (office#23): Q2 B add_overlay copies by default (copy=True) and can hold the
caller's array (copy=False); Q3 B get_overlay_array returns a copy or a read-only view;
Q4 A a separate handle object; Q5 A an overlay in another space or grid is refused,
never resampled. The API is provisional until tested. The main-thread guard is a later
item and is not here. Layer construction mirrors the controller's
``_add_array_layer`` without importing it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from .layers import EDITABLE_FIELDS, Layer, LayerStack

HANDLE_KINDS = ("image", "label")


@dataclass(frozen=True)
class LayerInfo:
    """Read-only summary of one layer; the affine is a copy, no voxel data."""

    id: str
    name: str
    kind: str
    source: str
    space: str
    shape: Tuple[int, ...]
    affine: np.ndarray
    dtype: str
    frames: int
    visible: bool
    alpha: float
    cmap: str


def _check_copy(copy: Any) -> None:
    if not isinstance(copy, bool):
        raise ValueError(f"copy: got {copy!r}, expected True or False")


class LayerHandle:
    """Add, change, remove and list overlay layers; the base layer is read-only."""

    def __init__(self, stack: LayerStack, data: Dict[str, np.ndarray], *, on_change: Optional[Callable[[], None]] = None):
        self._stack = stack
        self._data = data
        self._on_change = on_change
        self._owned: Set[str] = set()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def list_layers(self) -> List[LayerInfo]:
        return [
            LayerInfo(
                id=l.id, name=l.name, kind=l.kind, source=l.source, space=l.space,
                shape=tuple(l.shape), affine=np.array(l.affine, copy=True), dtype=str(l.dtype),
                frames=l.frames, visible=l.visible, alpha=l.alpha, cmap=l.cmap,
            )
            for l in self._stack
        ]

    def add_overlay(self, data, affine, *, name: str, kind: str = "image", editable: bool = False,
                    layer_id: Optional[str] = None, copy: bool = True, space: Optional[str] = None,
                    **fields: Any) -> str:
        """Add an overlay layer and return its id.

        Ownership: with copy=True the handle owns its own copy; with copy=False the caller keeps
        ownership and the handle holds a reference to the caller's numpy.ndarray (no conversion).
        Lifetime: the stored array lives until remove_overlay or the layer is dropped.
        Mutation: a copy=False array is mutated only on the Tk main thread, followed by
        set_overlay(layer_id) with no fields to refresh; cached windows and label colours are
        recomputed only then. space None means the base layer's space; another value is refused.
        """
        _check_copy(copy)
        if kind not in HANDLE_KINDS:
            raise ValueError(f"kind: got {kind!r}, expected one of {list(HANDLE_KINDS)}")
        if editable and kind != "label":
            raise ValueError(f"editable: got True, expected False unless kind is 'label' (kind is {kind!r})")
        for key in fields:
            if key not in EDITABLE_FIELDS:
                raise ValueError(f"field: got {key!r}, expected one of {sorted(EDITABLE_FIELDS)}")
        if copy:
            arr = np.array(data, copy=True)
        else:
            if not isinstance(data, np.ndarray):
                raise ValueError(f"data: got {type(data).__name__}, expected a numpy.ndarray when copy=False")
            arr = data
        if arr.ndim < 3:
            raise ValueError(f"data: got shape {arr.shape}, expected at least 3 dimensions")
        base = self._stack.base
        if base is None:
            raise ValueError("image: got no loaded scan, expected a loaded scan (open a dataset and select a scan first)")
        if space is not None and space != base.space:
            raise ValueError(f"space: got {space!r}, expected {base.space!r} (the base layer's space)")
        try:
            aff = np.array(affine, dtype=np.float64, copy=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"affine: got {affine!r}, expected a 4x4 array of numbers") from exc
        if tuple(arr.shape[:3]) != tuple(base.shape[:3]):
            raise ValueError(f"shape: got {tuple(arr.shape[:3])}, expected {tuple(base.shape[:3])} (the base layer's grid)")
        if aff.shape != (4, 4) or not np.allclose(aff, base.affine):
            raise ValueError(f"affine: got {aff.tolist()}, expected {base.affine.tolist()} (the base layer's affine)")
        lid = layer_id or f"layer-{len(self._stack)}"
        while lid in self._stack.ids():
            lid += "+"
        layer = Layer(
            id=lid, name=name, kind=kind, source="array", space=base.space,
            shape=tuple(arr.shape), affine=aff, dtype=str(arr.dtype),
            frames=int(arr.shape[3]) if arr.ndim >= 4 else 1,
            editable=editable, nbytes=int(arr.nbytes), **fields,
        )
        self._stack.add(layer)
        self._data[lid] = arr
        self._owned.add(lid)
        self._changed()
        return lid

    def _overlay_id(self, layer_id: str) -> None:
        if layer_id not in self._stack.ids():
            raise ValueError(f"layer_id: got {layer_id!r}, expected an overlay id from list_layers()")
        if self._stack.base is not None and layer_id == self._stack.base.id:
            raise ValueError(f"layer_id: got {layer_id!r}, expected an overlay id (the base layer is read-only)")

    def get_overlay_array(self, layer_id: str, copy: bool = True) -> np.ndarray:
        """Return an overlay's voxel array: a new copy, or (copy=False) a read-only view."""
        self._overlay_id(layer_id)
        _check_copy(copy)
        arr = self._data[layer_id]
        if copy:
            return np.array(arr, copy=True)
        view = arr.view()
        view.flags.writeable = False
        return view

    def set_overlay(self, layer_id: str, **fields: Any) -> None:
        self._overlay_id(layer_id)
        self._stack.update(layer_id, **fields)  # LayerError passes through unchanged
        self._changed()

    def remove_overlay(self, layer_id: str) -> None:
        self._overlay_id(layer_id)
        if layer_id not in self._owned:
            raise ValueError(f"layer_id: got {layer_id!r}, expected an overlay added through this handle")
        self._stack.remove(layer_id)
        self._data.pop(layer_id, None)
        self._owned.discard(layer_id)
        self._changed()
