"""Label NIfTI writer (WI-0049, stage 3 design WI-B)."""

from pathlib import Path
from typing import Union

import numpy as np


def save_label_nifti(data: np.ndarray, affine: np.ndarray, path: Union[str, Path]) -> Path:
    """Write a label array as .nii.gz (uint8 if max <= 255 else uint16), keeping the affine."""
    import nibabel as nib

    arr = np.asarray(data)
    if arr.dtype.kind not in "iu":
        raise ValueError(f"data: got dtype {arr.dtype}, expected an integer dtype")
    if arr.ndim < 2:
        raise ValueError(f"data: got {arr.ndim}-D, expected 2-D or more")
    mat = np.asarray(affine, dtype=float)
    if mat.shape != (4, 4):
        raise ValueError(f"affine: got shape {mat.shape}, expected (4, 4)")
    out = Path(path)
    if not out.name.endswith(".nii.gz"):
        raise ValueError(f"path: got {out.name!r}, expected a name ending in .nii.gz")
    lo = int(arr.min()) if arr.size else 0
    hi = int(arr.max()) if arr.size else 0
    if lo < 0:
        raise ValueError(f"data: got min {lo}, expected labels >= 0")
    if hi > 65535:
        raise ValueError(f"data: got max {hi}, expected <= 65535")
    dtype = np.uint8 if hi <= 255 else np.uint16
    img = nib.Nifti1Image(arr.astype(dtype), mat)
    img.set_data_dtype(dtype)
    img.to_filename(str(out))
    return out
