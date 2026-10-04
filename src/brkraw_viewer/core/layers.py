"""Ordered layer list with change events (WI-0072, contract C2)."""

from dataclasses import dataclass, field, replace
from typing import Tuple, Optional, Dict, Any, List, Callable
import numpy as np

KINDS = ("image", "label")
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

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise LayerError("id")
        
        if self.kind not in KINDS:
            raise LayerError("kind")
        if self.source not in SOURCES:
            raise LayerError("source")
        if self.frame_policy not in FRAME_POLICIES:
            raise LayerError("frame_policy")
        if self.interpolation not in INTERPOLATIONS:
            raise LayerError("interpolation")
        
        try:
            self.shape = tuple(int(n) for n in self.shape)
        except (TypeError, ValueError):
            raise LayerError("shape")
        if len(self.shape) < 3 or any(n < 1 for n in self.shape):
            raise LayerError("shape")
            
        try:
            self.affine = np.array(self.affine, dtype=np.float64)
        except (TypeError, ValueError):
            raise LayerError("affine")
        if self.affine.shape != (4, 4):
            raise LayerError("affine")
            
        try:
            self.frames = int(self.frames)
        except (TypeError, ValueError):
            raise LayerError("frames")
        if self.frames < 1:
            raise LayerError("frames")
            
        try:
            self.fixed_frame = int(self.fixed_frame)
        except (TypeError, ValueError):
            raise LayerError("fixed_frame")
        if not (0 <= self.fixed_frame < self.frames):
            raise LayerError("fixed_frame")
            
        # Field rules
        try:
            self.alpha = float(self.alpha)
        except (TypeError, ValueError):
            raise LayerError("alpha")
        if not (0.0 <= self.alpha <= 1.0):
            raise LayerError("alpha")
            
        if self.window is not None:
            try:
                a, b = self.window
                self.window = (float(a), float(b))
                if not (np.isfinite(self.window[0]) and np.isfinite(self.window[1]) and self.window[1] > self.window[0]):
                    raise LayerError("window")
            except (TypeError, ValueError):
                raise LayerError("window")
                
        if not isinstance(self.transparency, dict):
            raise LayerError("transparency")
        if any(k not in TRANSPARENCY_KEYS for k in self.transparency):
            raise LayerError("transparency")
        self.transparency = dict(self.transparency)
        
        if self.kind == "label":
            self.interpolation = "nearest"
        elif self.kind == "image" and self.editable:
            raise LayerError("editable")
            
        try:
            self.nbytes = int(self.nbytes)
        except (TypeError, ValueError):
            raise LayerError("nbytes")
        if self.nbytes < 0:
            raise LayerError("nbytes")

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
        raise LayerError("unknown")

    def index(self, layer_id: str) -> int:
        for i, l in enumerate(self._layers):
            if l.id == layer_id:
                return i
        raise LayerError("unknown")

    @property
    def base(self) -> Optional[Layer]:
        return self._layers[0] if self._layers else None

    def add(self, layer: Layer, index: Optional[int] = None) -> int:
        if any(l.id == layer.id for l in self._layers):
            raise LayerError("duplicate")
        
        base = self.base
        if base and layer.space != base.space:
            raise LayerError(f"space: {layer.space} vs {base.space}")
            
        if not self._layers:
            self._layers.insert(0, layer)
            pos = 0
        else:
            if index is None:
                self._layers.append(layer)
                pos = len(self._layers) - 1
            else:
                if not (1 <= index <= len(self._layers)):
                    raise LayerError("index")
                self._layers.insert(index, layer)
                pos = index
                
        self._emit("layer_added", layer.id, {"index": pos})
        return pos

    def remove(self, layer_id: str) -> Layer:
        idx = self.index(layer_id)
        if idx == 0 and len(self._layers) > 1:
            raise LayerError("base")
        
        layer = self._layers.pop(idx)
        self._emit("layer_removed", layer_id, {"index": idx, "nbytes": layer.nbytes, "source": layer.source})
        return layer

    def move(self, layer_id: str, new_index: int) -> None:
        old_idx = self.index(layer_id)
        if old_idx == 0:
            raise LayerError("base")
        if not (1 <= new_index <= len(self._layers) - 1):
            raise LayerError("index")
            
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
                raise LayerError(f"field: {key}")
            
            if key == "alpha":
                try:
                    v = float(value)
                    if not (0.0 <= v <= 1.0): raise LayerError("alpha")
                    normalized[key] = v
                except (TypeError, ValueError): raise LayerError("alpha")
            elif key == "window":
                if value is None:
                    normalized[key] = None
                else:
                    try:
                        a, b = value
                        v = (float(a), float(b))
                        if not (np.isfinite(v[0]) and np.isfinite(v[1]) and v[1] > v[0]):
                            raise LayerError("window")
                        normalized[key] = v
                    except (TypeError, ValueError): raise LayerError("window")
            elif key == "transparency":
                if not isinstance(value, dict): raise LayerError("transparency")
                if any(k not in TRANSPARENCY_KEYS for k in value): raise LayerError("transparency")
                normalized[key] = dict(value)
            elif key == "interpolation":
                if value not in INTERPOLATIONS: raise LayerError("interpolation")
                if layer.kind == "label" and value != "nearest": raise LayerError("interpolation")
                normalized[key] = value
            elif key == "frame_policy":
                if value not in FRAME_POLICIES: raise LayerError("frame_policy")
                normalized[key] = value
            elif key == "fixed_frame":
                try:
                    v = int(value)
                    if not (0 <= v < layer.frames): raise LayerError("fixed_frame")
                    normalized[key] = v
                except (TypeError, ValueError): raise LayerError("fixed_frame")
            elif key in ("name", "cmap"):
                if not isinstance(value, str): raise LayerError(key)
                normalized[key] = value
            elif key == "visible":
                normalized[key] = bool(value)
            else:
                # This part should not be reached due to EDITABLE_FIELDS check
                raise LayerError("field")

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
                raise LayerError("cursor")
        except (TypeError, ValueError):
            raise LayerError("cursor")
            
        if new_cursor != self.cursor:
            self.cursor = new_cursor
            self._emit("cursor_moved", None, {"cursor": self.cursor})

    def set_frame(self, frame) -> None:
        try:
            f = int(frame)
        except (TypeError, ValueError):
            raise LayerError("frame")
        if f < 0:
            raise LayerError("frame")
            
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
