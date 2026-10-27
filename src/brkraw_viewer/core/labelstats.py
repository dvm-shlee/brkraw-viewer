"""Per-label mean timecourses of a volume (numpy only, no GUI)."""

from typing import Dict

import numpy as np


def label_timecourse(data: np.ndarray, labels: np.ndarray) -> Dict[int, np.ndarray]:
    """Mean of ``data`` over each label's voxels, per frame.

    Parameters
    ----------
    data : numpy.ndarray
        3-D (x, y, z) or 4-D (x, y, z, t) array.
    labels : numpy.ndarray
        3-D integer array with shape ``data.shape[:3]``. Label 0 is background.

    Returns
    -------
    dict[int, numpy.ndarray]
        For every label value > 0 present in ``labels`` (ascending), an array of shape
        (t,) for 4-D data or (1,) for 3-D data. NaN voxels are ignored; a frame whose
        voxels are all NaN gives NaN. Absent labels are not reported.

    Raises
    ------
    ValueError
        If ``data`` is not 3-D or 4-D, ``labels`` is not an integer array, has negative
        values, or its shape differs from ``data.shape[:3]``.
    """
    data = np.asarray(data)
    labels = np.asarray(labels)
    if data.ndim not in (3, 4):
        raise ValueError(f"data.ndim: got {data.ndim}, expected 3 or 4")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ValueError(f"labels.dtype: got {labels.dtype}, expected an integer dtype")
    if labels.shape != data.shape[:3]:
        raise ValueError(f"labels.shape: got {labels.shape}, expected {data.shape[:3]}")
    if labels.size and labels.min() < 0:
        raise ValueError(f"labels: got minimum {int(labels.min())}, expected values >= 0")

    flat_labels = labels.reshape(-1)
    # Compact the (possibly sparse) label values to 0..n-1 so bincount stays small.
    values, inverse = np.unique(flat_labels, return_inverse=True)
    inverse = inverse.reshape(-1)
    if not (values > 0).any():
        return {}
    n = len(values)
    frames = data.reshape(flat_labels.size, -1)
    n_frames = frames.shape[1]
    sums = np.empty((n, n_frames), dtype=np.float64)
    counts = np.empty((n, n_frames), dtype=np.float64)
    for t in range(n_frames):
        frame = frames[:, t].astype(np.float64, copy=False)
        valid = ~np.isnan(frame)
        if valid.all():
            sums[:, t] = np.bincount(inverse, weights=frame, minlength=n)
            counts[:, t] = np.bincount(inverse, minlength=n)
        else:
            sums[:, t] = np.bincount(inverse, weights=np.where(valid, frame, 0.0), minlength=n)
            counts[:, t] = np.bincount(inverse, weights=valid.astype(np.float64), minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = sums / counts
    means[counts == 0] = np.nan
    return {int(v): means[i] for i, v in enumerate(values) if v > 0}
