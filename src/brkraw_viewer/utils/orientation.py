from __future__ import annotations

from typing import Sequence, Tuple
import numpy as np
import nibabel as nib

_RAS = np.array([[0, 1], [1, 1], [2, 1]])


def _ras_transform(affine: np.ndarray) -> np.ndarray:
    ornt = nib.orientations.io_orientation(affine)
    return nib.orientations.ornt_transform(ornt, _RAS)


def ras_display_affine(affine: np.ndarray, shape: Sequence[int]) -> np.ndarray:
    """Affine of the display grid D (layer core C1): the grid after :func:`reorient_to_ras`.

    ``A_D = A @ inv_ornt_aff(T, shape)``; only axes are permuted and flipped, so any
    obliquity of ``A`` stays in ``A_D``. Needs only the shape, not the data.
    """
    affine = np.asarray(affine, dtype=float)
    transform = _ras_transform(affine)
    return affine @ nib.orientations.inv_ornt_aff(transform, tuple(int(n) for n in shape))


def reorient_to_ras(data: np.ndarray, affine: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    data = np.asarray(data)
    affine = np.asarray(affine, dtype=float)
    transform = _ras_transform(affine)
    new_data = nib.orientations.apply_orientation(data, transform)
    new_affine = affine @ nib.orientations.inv_ornt_aff(transform, data.shape)
    return new_data, new_affine
