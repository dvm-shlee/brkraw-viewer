"""Tk-free layer core of the viewer (layer core contract v0.1, WI-0010; built in WI-0072).

numpy only. The viewport, the controller and later the Python handle use these
functions; nothing here imports Tk.
"""
from .composite import composite_over, label_rgba, layer_rgba, transparency_mask, window_to_index
from .roi import ellipse_mask, rect_mask, roi_stats
from .resample import (
    Grid,
    SpaceMismatchError,
    display_to_layer_matrix,
    grid_matrix,
    map_indices,
    sample_linear,
    sample_nearest,
    sample_slice,
    signed_permutation,
    slice_index_grid,
)
from .window import MAX_WINDOW_SAMPLES, default_window, normalize_window, window_sample

__all__ = [
    "Grid",
    "MAX_WINDOW_SAMPLES",
    "SpaceMismatchError",
    "composite_over",
    "default_window",
    "display_to_layer_matrix",
    "ellipse_mask",
    "grid_matrix",
    "label_rgba",
    "layer_rgba",
    "map_indices",
    "normalize_window",
    "rect_mask",
    "roi_stats",
    "sample_linear",
    "sample_nearest",
    "sample_slice",
    "signed_permutation",
    "slice_index_grid",
    "transparency_mask",
    "window_sample",
    "window_to_index",
]
