"""Layer transparency rules and straight-alpha compositing (WI-0072, contract C4)."""

from typing import Any, Dict, List, Tuple, Optional, Union, Sequence
import numpy as np


def transparency_mask(values: Any, rules: Optional[Dict[str, Any]] = None) -> np.ndarray:
    v = np.asarray(values, dtype=np.float64)
    mask = np.isnan(v)
    if rules is None or not rules:
        return mask

    for key, val in rules.items():
        if key == "zero":
            if val:
                mask |= (v == 0)
        elif key == "below":
            mask |= (v < val)
        elif key == "abs_below":
            mask |= (np.abs(v) < val)
        elif key == "range":
            lo, hi = val
            if lo > hi:
                raise ValueError("range: lo must be <= hi")
            mask |= (v >= lo) & (v <= hi)
        elif key == "values":
            mask |= np.isin(v, val)
        else:
            raise ValueError(f"unknown rule: {key}")

    return mask


def window_to_index(values: Any, vmin: float, vmax: float) -> np.ndarray:
    v = np.asarray(values, dtype=np.float64)
    vmin = float(vmin)
    vmax = float(vmax)
    if (vmax - vmin) <= 0 or np.isclose(vmin, vmax):
        vmax = vmin + 1.0
    
    norm = np.clip((v - vmin) / (vmax - vmin), 0.0, 1.0)
    norm = np.where(np.isnan(norm), 0.0, norm)
    return np.floor(norm * 255.0).astype(np.uint8)


def layer_rgba(
    values: Any, *, lut: Any, vmin: float, vmax: float, 
    alpha: float = 1.0, visible: bool = True, rules: Optional[Dict[str, Any]] = None
) -> Tuple[np.ndarray, np.ndarray]:
    lut_arr = np.asarray(lut, dtype=np.uint8)
    if lut_arr.shape != (256, 3):
        raise ValueError("lut must have shape (256, 3)")
    
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be between 0.0 and 1.0")
    
    idx = window_to_index(values, vmin, vmax)
    rgb = lut_arr[idx].astype(np.float32)
    
    hidden = transparency_mask(values, rules)
    
    # a = alpha * (1.0 if visible else 0.0) where not hidden, else 0.0
    vis_val = alpha * (1.0 if visible else 0.0)
    a = np.where(hidden, 0.0, vis_val).astype(np.float32)
    
    return rgb, a


def label_rgba(
    labels: Any, *, colors: Dict[int, Tuple[int, int, int]], 
    alpha: float = 1.0, visible: bool = True, hidden_labels: Optional[set] = None
) -> Tuple[np.ndarray, np.ndarray]:
    lab = np.asarray(labels)
    if lab.dtype.kind not in "iu":
        raise ValueError("labels must be an integer array")
    
    if not (0.0 <= alpha <= 1.0):
        raise ValueError("alpha must be between 0.0 and 1.0")
    
    h, w = lab.shape
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    
    # For each (k, c) in colors.items() with k != 0 set rgb[lab == k] = c
    for k, c in colors.items():
        if k != 0:
            rgb[lab == k] = c
            
    # a = alpha * (1.0 if visible else 0.0) where:
    # pixel's label is in colors, is not 0, and is not in hidden_labels
    vis_val = alpha * (1.0 if visible else 0.0)
    
    # Condition: (lab in colors) AND (lab != 0) AND (lab not in hidden_labels)
    # We can use np.isin for the set checks
    color_keys = list(colors.keys())
    in_colors = np.isin(lab, color_keys)
    not_zero = (lab != 0)
    
    if hidden_labels is not None:
        not_hidden = ~np.isin(lab, list(hidden_labels))
    else:
        not_hidden = np.ones_like(lab, dtype=bool)
        
    mask = in_colors & not_zero & not_hidden
    a = np.where(mask, vis_val, 0.0).astype(np.float32)
    
    return rgb, a


def composite_over(base_rgb: np.ndarray, layers: List[Tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    out = np.asarray(base_rgb, dtype=np.float64)
    h, w, c = out.shape
    
    for rgb, a in layers:
        rgb_arr = np.asarray(rgb, dtype=np.float64)
        a_arr = np.asarray(a, dtype=np.float64)
        
        if rgb_arr.shape != (h, w, 3) or a_arr.shape != (h, w):
            raise ValueError("shape mismatch in layer")
            
        a3 = a_arr[:, :, np.newaxis]
        out = a3 * rgb_arr + (1.0 - a3) * out
        
    return np.clip(np.floor(out + 0.5), 0, 255).astype(np.uint8)
