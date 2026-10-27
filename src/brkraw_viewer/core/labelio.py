"""Label NIfTI reader and writer."""

from pathlib import Path
from typing import Tuple, Union

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


def load_label_nifti(path: Union[str, Path]) -> Tuple[np.ndarray, np.ndarray]:
    """Read an integer-valued label NIfTI (.nii or .nii.gz); return (labels, 4x4 affine), data as stored."""
    import nibabel as nib

    src = Path(path)
    if not (src.name.endswith(".nii.gz") or src.name.endswith(".nii")):
        raise ValueError(f"path: got {src.name!r}, expected a name ending in .nii or .nii.gz")
    if not src.is_file():
        raise FileNotFoundError(f"path: got {str(src)!r}, expected an existing file")
    img = nib.load(str(src))
    arr = np.asarray(img.dataobj)
    if arr.ndim not in (3, 4):
        raise ValueError(f"data: got {arr.ndim}-D, expected 3-D or 4-D")
    if arr.dtype.kind == "f":
        if arr.size and not np.all(np.isfinite(arr)):
            raise ValueError("data: got non-finite values, expected integer-valued labels")
        if arr.size and not np.all(arr == np.round(arr)):
            raise ValueError("data: got non-integral float values, expected integer-valued labels")
    elif arr.dtype.kind not in "iu":
        raise ValueError(f"data: got dtype {arr.dtype}, expected an integer or integral float dtype")
    lo = arr.min() if arr.size else 0
    hi = arr.max() if arr.size else 0
    if lo < 0:
        raise ValueError(f"data: got min {int(lo)}, expected labels >= 0")
    if hi > 65535:
        raise ValueError(f"data: got max {int(hi)}, expected <= 65535")
    if arr.dtype.kind == "f":
        arr = arr.astype(np.uint8 if hi <= 255 else np.uint16)
    return arr, np.asarray(img.affine, dtype=float)
