import nibabel as nib
import numpy as np
import pytest

from brkraw_viewer.core.labelio import load_label_nifti, save_label_nifti

AFF = np.array([[2.0, 0, 0, -5], [0, 1.5, 0, 3], [0, 0, 1.0, 7], [0, 0, 0, 1]])


def _write(path, arr, dtype=None):
    img = nib.Nifti1Image(arr, AFF)
    if dtype is not None:
        img.set_data_dtype(dtype)
    img.to_filename(str(path))
    return path


@pytest.mark.parametrize("hi,dtype", [(5, np.uint8), (1000, np.uint16)])
def test_round_trip(tmp_path, hi, dtype):
    data = np.zeros((4, 5, 3), dtype=np.int32)
    data[1, 2, 1] = hi
    out = save_label_nifti(data, AFF, tmp_path / "a.nii.gz")
    got, aff = load_label_nifti(out)
    assert got.dtype == dtype
    assert np.array_equal(got, data)
    assert np.allclose(aff, AFF) and aff.shape == (4, 4)


def test_nii_accepted(tmp_path):
    data = np.arange(24, dtype=np.uint8).reshape(2, 3, 4)
    got, _ = load_label_nifti(_write(tmp_path / "a.nii", data))
    assert np.array_equal(got, data)


def test_wrong_extension(tmp_path):
    with pytest.raises(ValueError, match="path: got"):
        load_label_nifti(tmp_path / "a.txt")


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_label_nifti(tmp_path / "none.nii.gz")


def test_float_integral(tmp_path):
    data = np.zeros((3, 3, 3), dtype=np.float32)
    data[0, 0, 0] = 7
    got, _ = load_label_nifti(_write(tmp_path / "f.nii.gz", data, np.float32))
    assert got.dtype == np.uint8 and got[0, 0, 0] == 7
    data[1, 1, 1] = 300
    got, _ = load_label_nifti(_write(tmp_path / "g.nii.gz", data, np.float32))
    assert got.dtype == np.uint16 and got[1, 1, 1] == 300


def test_float_non_integral(tmp_path):
    data = np.full((3, 3, 3), 0.5, dtype=np.float32)
    with pytest.raises(ValueError, match="data: got"):
        load_label_nifti(_write(tmp_path / "h.nii.gz", data, np.float32))


def test_negative(tmp_path):
    data = np.full((3, 3, 3), -1, dtype=np.int16)
    with pytest.raises(ValueError, match="data: got"):
        load_label_nifti(_write(tmp_path / "n.nii.gz", data, np.int16))


def test_3d_and_4d(tmp_path):
    for shape in [(3, 4, 5), (3, 4, 5, 2)]:
        data = np.ones(shape, dtype=np.uint8)
        got, _ = load_label_nifti(save_label_nifti(data, AFF, tmp_path / f"d{len(shape)}.nii.gz"))
        assert got.shape == shape
