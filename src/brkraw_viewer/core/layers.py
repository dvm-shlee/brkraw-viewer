"""Ordered layer list with change events (WI-0072, contract C2)."""

from dataclasses import dataclass, field, replace
from typing import Tuple, Optional, Dict, Any, List, Callable
import numpy as np

KINDS = ("image", "label", "rgb")
RGB_CHANNELS = (3, 4)
RGB_IGNORED_FIELDS = ("cmap", "window", "transparency")
SOURCES = ("scan", "array", "file")
FRAME_POLICIES = ("linked", "fixed")
INTERPOLATIONS = ("linear", "nearest")
TRANSPARENCY_KEYS = ("zero", "below", "abs_below", "range", "values")
EVENTS = ("layer_added", "layer_removed", "layer_changed", "order_changed", "cursor_moved", "frame_changed")
EDITABLE_FIELDS = ("name", "visible", "alpha", "cmap", "window", "transparency", "interpolation", "frame_policy", "fixed_frame")

class LayerError(ValueError):
    pass

@dataclass(eq=False)  # identity equality: a generated __eq__ would compare the affine arrays
class Layer:
    id: str
    name: str
    kind: str
    source: str
    space: str
    shape: Tuple[int, ...]
    affine: np.ndarray
    dtype: str
    frames: int = 1
    frame_policy: str = "linked"
    fixed_frame: int = 0
    visible: bool = True
    alpha: float = 1.0
    cmap: str = "gray"
    window: Optional[Tuple[float, float]] = None
    transparency: Dict[str, Any] = field(default_factory=dict)
    interpolation: str = "linear"
    editable: bool = False
    nbytes: int = 0
    channels: int = 1

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise LayerError(f"id: got {self.id!r}, expected a non-empty str")
        
        if self.kind not in KINDS:
            raise LayerError(f"kind: got {self.kind!r}, expected one of {sorted(KINDS)}")
        if self.source not in SOURCES:
            raise LayerError(f"source: got {self.source!r}, expected one of {sorted(SOURCES)}")
        if self.frame_policy not in FRAME_POLICIES:
            raise LayerError(f"frame_policy: got {self.frame_policy!r}, expected one of {sorted(FRAME_POLICIES)}")
        if self.interpolation not in INTERPOLATIONS:
            raise LayerError(f"interpolation: got {self.interpolation!r}, expected one of {sorted(INTERPOLATIONS)}")
        
        try:
            self.shape = tuple(int(n) for n in self.shape)
        except (TypeError, ValueError):
            raise LayerError(f"shape: got {self.shape!r}, expected a sequence of integers")
        if len(self.shape) < 3 or any(n < 1 for n in self.shape):
            raise LayerError(f"shape: got {self.shape!r}, expected at least 3 dimensions, each >= 1")
            
        try:
            self.affine = np.array(self.affine, dtype=np.float64)
        except (TypeError, ValueError):
            raise LayerError(f"affine: got {self.affine!r}, expected a numeric 4x4 matrix")
        if self.affine.shape != (4, 4):
            raise LayerError(f"affine: got shape {self.affine.shape}, expected (4, 4)")
            
        if self.kind == "rgb":
            if self.source != "array":
                raise LayerError(f"source: got {self.source!r}, expected 'array' for kind 'rgb'")
            # the last axis holds colour channels, never frames
            if len(self.shape) != 4 or self.shape[3] not in RGB_CHANNELS:
                raise LayerError(f"shape: got {self.shape}, expected (X, Y, Z, 3) or (X, Y, Z, 4) for kind 'rgb'")
            if str(self.dtype) != "uint8":
                raise LayerError(f"dtype: got {str(self.dtype)!r}, expected 'uint8' for kind 'rgb'")
            self.channels = self.shape[3]
            self.frames = 1
        else:
            try:
                ch = int(self.channels)
            except (TypeError, ValueError):
                ch = -1
            if ch != 1:
                raise LayerError(f"channels: got {self.channels!r}, expected 1 for kind {self.kind!r}")

        try:
            self.frames = int(self.frames)
        except (TypeError, ValueError):
            raise LayerError(f"frames: got {self.frames!r}, expected an integer")
        if self.frames < 1:
            raise LayerError(f"frames: got {self.frames!r}, expected an integer >= 1")
            
        try:
            self.fixed_frame = int(self.fixed_frame)
        except (TypeError, ValueError):
            raise LayerError(f"fixed_frame: got {self.fixed_frame!r}, expected an integer")
        if not (0 <= self.fixed_frame < self.frames):
            raise LayerError(f"fixed_frame: got {self.fixed_frame!r}, expected an integer in [0, {self.frames})")
            
        # Field rules
        try:
            self.alpha = float(self.alpha)
        except (TypeError, ValueError):
            raise LayerError(f"alpha: got {self.alpha!r}, expected 0.0..1.0")
        if not (0.0 <= self.alpha <= 1.0):
            raise LayerError(f"alpha: got {self.alpha!r}, expected 0.0..1.0")
            
        if self.window is not None:
            try:
                a, b = self.window
                self.window = (float(a), float(b))
                if not (np.isfinite(self.window[0]) and np.isfinite(self.window[1]) and self.window[1] > self.window[0]):
                    raise LayerError(f"window: got {self.window!r}, expected finite (lo, hi) with hi > lo")
            except (TypeError, ValueError):
                raise LayerError(f"window: got {self.window!r}, expected finite (lo, hi) with hi > lo")
                
        if not isinstance(self.transparency, dict):
            raise LayerError(f"transparency: got {self.transparency!r}, expected a dict")
        if any(k not in TRANSPARENCY_KEYS for k in self.transparency):
            raise LayerError(f"transparency: got {sorted(map(str, self.transparency))}, expected keys within {sorted(TRANSPARENCY_KEYS)}")
        self.transparency = dict(self.transparency)
        
        if self.kind == "label":
            self.interpolation = "nearest"
        elif self.kind == "image" and self.editable:
            raise LayerError("editable: got True, expected False for kind 'image'")
        elif self.kind == "rgb" and self.editable:
            raise LayerError("editable: got True, expected False for kind 'rgb'")
            
        try:
            self.nbytes = int(self.nbytes)
        except (TypeError, ValueError):
            raise LayerError(f"nbytes: got {self.nbytes!r}, expected an integer")
        if self.nbytes < 0:
            raise LayerError(f"nbytes: got {self.nbytes!r}, expected an integer >= 0")

class LayerStack:
    def __init__(self):
        self._layers: List[Layer] = []
        self._subscribers: List[Callable] = []
        self.cursor = None
        self.frame = 0

    def _emit(self, event: str, layer_id: Optional[str], detail: Dict[str, Any]):
        for callback in self._subscribers:
            callback(event, layer_id, detail)

    def subscribe(self, callback: Callable) -> Callable[[], None]:
        self._subscribers.append(callback)
        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)
        return unsubscribe

    def __len__(self) -> int:
        return len(self._layers)

    def __iter__(self):
        return iter(self._layers)

    def ids(self) -> List[str]:
        return [l.id for l in self._layers]

    def get(self, layer_id: str) -> Layer:
        for l in self._layers:
            if l.id == layer_id:
                return l
        raise LayerError(f"layer_id: got {layer_id!r}, expected one of {self.ids()} (unknown layer)")

    def index(self, layer_id: str) -> int:
        for i, l in enumerate(self._layers):
            if l.id == layer_id:
                return i
        raise LayerError(f"layer_id: got {layer_id!r}, expected one of {self.ids()} (unknown layer)")

    @property
    def base(self) -> Optional[Layer]:
        return self._layers[0] if self._layers else None

    def add(self, layer: Layer, index: Optional[int] = None) -> int:
        if any(l.id == layer.id for l in self._layers):
            raise LayerError(f"id: got {layer.id!r}, expected an id not already in the stack (duplicate)")
        
        base = self.base
        if base and layer.space != base.space:
            raise LayerError(f"space: got {layer.space!r}, expected {base.space!r} (the base layer's space)")
            
        if not self._layers:
            self._layers.insert(0, layer)
            pos = 0
        else:
            if index is None:
                self._layers.append(layer)
                pos = len(self._layers) - 1
            else:
                if not (1 <= index <= len(self._layers)):
                    raise LayerError(f"index: got {index!r}, expected an integer in [1, {len(self._layers)}]")
                self._layers.insert(index, layer)
                pos = index
                
        self._emit("layer_added", layer.id, {"index": pos})
        return pos

    def remove(self, layer_id: str) -> Layer:
        idx = self.index(layer_id)
        if idx == 0 and len(self._layers) > 1:
            raise LayerError(f"layer_id: got {layer_id!r}, expected a non-base layer (the base layer cannot be removed while others exist)")
        
        layer = self._layers.pop(idx)
        self._emit("layer_removed", layer_id, {"index": idx, "nbytes": layer.nbytes, "source": layer.source})
        return layer

    def move(self, layer_id: str, new_index: int) -> None:
        old_idx = self.index(layer_id)
        if old_idx == 0:
            raise LayerError(f"layer_id: got {layer_id!r}, expected a non-base layer (the base layer cannot be moved)")
        if not (1 <= new_index <= len(self._layers) - 1):
            raise LayerError(f"index: got {new_index!r}, expected an integer in [1, {len(self._layers) - 1}]")
            
        if old_idx == new_index:
            return
            
        layer = self._layers.pop(old_idx)
        self._layers.insert(new_index, layer)
        self._emit("order_changed", None, {"order": self.ids()})

    def update(self, layer_id: str, **fields) -> List[str]:
        layer = self.get(layer_id)
        
        # Validation phase
        normalized = {}
        for key, value in fields.items():
            if key not in EDITABLE_FIELDS:
                raise LayerError(f"field: got {key!r}, expected one of {sorted(EDITABLE_FIELDS)}")
            if layer.kind == "rgb" and key in RGB_IGNORED_FIELDS:
                raise LayerError(f"field: got {key!r}, expected a field other than {sorted(RGB_IGNORED_FIELDS)} for kind 'rgb' (colour comes from the channels)")
            
            if key == "alpha":
                try:
                    v = float(value)
                    if not (0.0 <= v <= 1.0): raise LayerError(f"alpha: got {value!r}, expected a number in 0.0..1.0")
                    normalized[key] = v
                except (TypeError, ValueError): raise LayerError(f"alpha: got {value!r}, expected a number in 0.0..1.0")
            elif key == "window":
                if value is None:
                    normalized[key] = None
                else:
                    try:
                        a, b = value
                        v = (float(a), float(b))
                        if not (np.isfinite(v[0]) and np.isfinite(v[1]) and v[1] > v[0]):
                            raise LayerError(f"window: got {value!r}, expected None or finite (lo, hi) with hi > lo")
                        normalized[key] = v
                    except (TypeError, ValueError): raise LayerError(f"window: got {value!r}, expected None or finite (lo, hi) with hi > lo")
            elif key == "transparency":
                if not isinstance(value, dict): raise LayerError(f"transparency: got {value!r}, expected a dict")
                if any(k not in TRANSPARENCY_KEYS for k in value): raise LayerError(f"transparency: got {sorted(map(str, value))}, expected keys within {sorted(TRANSPARENCY_KEYS)}")
                normalized[key] = dict(value)
            elif key == "interpolation":
                if value not in INTERPOLATIONS: raise LayerError(f"interpolation: got {value!r}, expected one of {sorted(INTERPOLATIONS)}")
                if layer.kind == "label" and value != "nearest": raise LayerError(f"interpolation: got {value!r}, expected 'nearest' for kind 'label'")
                normalized[key] = value
            elif key == "frame_policy":
                if value not in FRAME_POLICIES: raise LayerError(f"frame_policy: got {value!r}, expected one of {sorted(FRAME_POLICIES)}")
                normalized[key] = value
            elif key == "fixed_frame":
                try:
                    v = int(value)
                    if not (0 <= v < layer.frames): raise LayerError(f"fixed_frame: got {value!r}, expected an integer in [0, {layer.frames})")
                    normalized[key] = v
                except (TypeError, ValueError): raise LayerError(f"fixed_frame: got {value!r}, expected an integer in [0, {layer.frames})")
            elif key in ("name", "cmap"):
                if not isinstance(value, str):
                    if key == "name": raise LayerError(f"name: got {value!r}, expected a str")
                    raise LayerError(f"cmap: got {value!r}, expected a str")
                normalized[key] = value
            elif key == "visible":
                normalized[key] = bool(value)
            else:
                # This part should not be reached due to EDITABLE_FIELDS check
                raise LayerError(f"field: got {key!r}, expected one of {sorted(EDITABLE_FIELDS)}")

        # Application phase
        changed = []
        for key in fields:
            new_val = normalized[key]
            current_val = getattr(layer, key)
            if new_val != current_val:
                setattr(layer, key, new_val)
                changed.append(key)
                self._emit("layer_changed", layer_id, {"field": key})
        
        return changed

    def set_cursor(self, ijk) -> None:
        try:
            new_cursor = tuple(float(v) for v in ijk)
            if len(new_cursor) != 3:
                raise LayerError(f"cursor: got {ijk!r}, expected three numbers")
        except (TypeError, ValueError):
            raise LayerError(f"cursor: got {ijk!r}, expected three numbers")
            
        if new_cursor != self.cursor:
            self.cursor = new_cursor
            self._emit("cursor_moved", None, {"cursor": self.cursor})

    def set_frame(self, frame) -> None:
        try:
            f = int(frame)
        except (TypeError, ValueError):
            raise LayerError(f"frame: got {frame!r}, expected an integer >= 0")
        if f < 0:
            raise LayerError(f"frame: got {frame!r}, expected an integer >= 0")
            
        if f != self.frame:
            self.frame = f
            self._emit("frame_changed", None, {"frame": self.frame})

    def frame_for(self, layer_id: str, base_frame: Optional[int] = None) -> int:
        layer = self.get(layer_id)
        bf = base_frame if base_frame is not None else self.frame
        
        if layer.frame_policy == "linked" and layer.frames == self.base.frames:
            return min(bf, layer.frames - 1)
        return layer.fixed_frame

    def held_nbytes(self) -> int:
        return sum(l.nbytes for l in self._layers if l.source in ("scan", "file"))

    def total_nbytes(self) -> int:
        return sum(l.nbytes for l in self._layers)
