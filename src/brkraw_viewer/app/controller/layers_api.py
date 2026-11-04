"""Controller binding of the layer handle: ViewerController.layers_api.

Provisional API: it may change until it is tested in use. Main thread only: every
method refuses a call from another thread. Reference: docs/dev/hooks.md.
The binding composes the core LayerHandle over the controller's own layer stack and layer
data; it imports no Tk.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import numpy as np

from ...core.labelio import load_label_nifti, save_label_nifti
from ...core.layer_handle import LayerHandle, LayerInfo, _check_copy

if TYPE_CHECKING:
    from .viewer import ViewerController


def _main_thread() -> None:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(f"thread: got {threading.current_thread().name!r}, expected the Tk main thread")


class LayersAPI:
    """Add, change, remove and list overlay layers of the shown scan (main thread only)."""

    def __init__(self, controller: "ViewerController"):
        self._ctl = controller
        self._handle = LayerHandle(
            controller._layers, controller._layer_data, on_change=controller._render_viewer_views
        )

    def _sync(self) -> None:
        grid = self._ctl._display_grid()
        if grid is not None:
            self._ctl._sync_base_layer(grid)

    def list_layers(self) -> List[LayerInfo]:
        _main_thread()
        self._sync()
        return self._handle.list_layers()

    def get_image(self, copy: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """Return (array, affine) of the shown scan; copy=False gives a read-only view."""
        _main_thread()
        _check_copy(copy)
        grid = self._ctl._display_grid()
        if self._ctl._viewer_volume is None or grid is None:
            raise ValueError("image: got no loaded scan, expected a loaded scan (open a dataset and select a scan first)")
        vol = np.asarray(self._ctl._viewer_volume)
        affine = np.array(grid.affine, copy=True)
        if copy:
            return np.array(vol, copy=True), affine
        view = vol.view()
        view.flags.writeable = False
        return view, affine

    def add_overlay(self, data, affine, *, name: str, kind: str = "image", editable: bool = False,
                    layer_id: Optional[str] = None, copy: bool = True, space: Optional[str] = None,
                    **fields: Any) -> str:
        _main_thread()
        self._sync()
        return self._handle.add_overlay(
            data, affine, name=name, kind=kind, editable=editable, layer_id=layer_id,
            copy=copy, space=space, **fields,
        )

    def set_overlay(self, layer_id: str, **fields: Any) -> None:
        """Change overlay fields; with no fields, refresh after mutating a copy=False array."""
        _main_thread()
        if not fields:
            self._ctl._layer_label_colors.pop(layer_id, None)
            for key in [k for k in self._ctl._layer_windows if k[0] == layer_id]:
                self._ctl._layer_windows.pop(key, None)
        self._handle.set_overlay(layer_id, **fields)

    def get_overlay_array(self, layer_id: str, copy: bool = True) -> np.ndarray:
        _main_thread()
        self._sync()
        return self._handle.get_overlay_array(layer_id, copy=copy)

    def remove_overlay(self, layer_id: str) -> None:
        _main_thread()
        if layer_id in self._ctl._layer_dirty:
            raise ValueError(f"layer_id: got {layer_id!r}, expected a layer without unsaved paint edits (save or discard them first)")
        self._handle.remove_overlay(layer_id)
        self._ctl._drop_layer_data(layer_id)

    def roi_timecourse(self, layer: Optional[str] = None, label: Optional[int] = None,
                       wait: bool = False, timeout: Optional[float] = None) -> Optional[dict]:
        """The drawn ROI's timecourse, or ``{label: values}`` of a label layer (see the controller)."""
        _main_thread()
        return self._ctl.roi_timecourse(layer=layer, label=label, wait=wait, timeout=timeout)

    def save_overlay(self, layer_id: str, path, *, overwrite: bool = False) -> Path:
        """Write a label overlay as .nii.gz; an existing file is refused unless overwrite=True."""
        _main_thread()
        if not isinstance(overwrite, bool):
            raise ValueError(f"overwrite: got {overwrite!r}, expected True or False")
        layer = next((l for l in self._handle.list_layers() if l.id == layer_id), None)
        if layer is None or layer.kind != "label":
            raise ValueError(f"layer_id: got {layer_id!r}, expected a label overlay id from list_layers()")
        out = Path(path)
        if not out.name.endswith(".nii.gz"):
            raise ValueError(f"path: got {out.name!r}, expected a name ending in .nii.gz")
        if out.exists() and not overwrite:
            raise ValueError(f"path: got {str(out)!r}, expected a file that does not exist (pass overwrite=True to replace it)")
        data = self._handle.get_overlay_array(layer_id, copy=False)
        saved = save_label_nifti(data, layer.affine, out)
        self._ctl._layer_dirty.discard(layer_id)
        return saved

    def load_overlay(self, path, *, name: Optional[str] = None, editable: bool = False,
                     layer_id: Optional[str] = None, **fields: Any) -> str:
        """Add a label NIfTI as a label overlay on the shown grid; another space or grid is refused."""
        _main_thread()
        self._sync()
        data, affine = load_label_nifti(path)
        return self._handle.add_overlay(
            data, affine, name=name or Path(path).name.split(".")[0], kind="label",
            editable=editable, layer_id=layer_id, copy=False, **fields,
        )
