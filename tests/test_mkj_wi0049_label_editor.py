"""Headless tests for the label painter core and NIfTI writer (WI-0049)."""

import nibabel as nib
import numpy as np
import pytest

from brkraw_viewer.core.labelio import save_label_nifti
from brkraw_viewer.core.painter import LabelEditor


def old_footprint(h, w, row, col, size, shape):
    """The rule of ui/components/label_painter.py::_apply_brush, as a mask."""
    m = np.zeros((h, w), dtype=bool)
    lo, hi = (size - 1) // 2, size // 2
    r0, r1 = max(0, row - lo), min(h - 1, row + hi)
    c0, c1 = max(0, col - lo), min(w - 1, col + hi)
    yy, xx = np.ogrid[r0 : r1 + 1, c0 : c1 + 1]
    if shape == "square" or size == 1:
        m[r0 : r1 + 1, c0 : c1 + 1] = True
    else:
        e = min(lo, hi)
        m[r0 : r1 + 1, c0 : c1 + 1] = (yy - row) ** 2 + (xx - col) ** 2 <= e * e
    return m


@pytest.mark.parametrize("shape", ["disc", "square"])
@pytest.mark.parametrize("size", range(1, 11))
@pytest.mark.parametrize("axis", [0, 1, 2])
def test_stamp_footprint_matches_old_painter(size, shape, axis):
    data = np.zeros((24, 24, 24), dtype=np.uint8)
    ed = LabelEditor(data, shape=shape)
    ed.set_brush(size)
    ed.label = 3
    ed.stamp(axis, 12, 11, 12)
    plane = np.take(data, 12, axis=axis)
    assert np.array_equal(plane != 0, old_footprint(24, 24, 11, 12, size, shape))
    assert set(np.unique(data)) <= {0, 3}
    assert (data != 0).sum() == (plane != 0).sum()


def test_even_size_square_is_asymmetric():
    data = np.zeros((1, 10, 10), dtype=np.uint8)
    ed = LabelEditor(data, shape="square")
    ed.set_brush(4)
    ed.stamp(0, 0, 5, 5)
    rows, cols = np.nonzero(data[0])
    assert (rows.min(), rows.max()) == (4, 7) and (cols.min(), cols.max()) == (4, 7)


def test_clipping_and_outside_ignored():
    data = np.zeros((8, 8, 8), dtype=np.uint8)
    ed = LabelEditor(data, shape="square")
    ed.set_brush(5)
    assert ed.stamp(2, 3, 0, 0) == (0, 0, 2, 2)
    assert data[:, :, 3].sum() == 9
    for args in [(2, 3, -1, 4), (2, 3, 4, 8), (2, 8, 4, 4), (2, -1, 4, 4)]:
        assert ed.stamp(*args) is None
    assert (data != 0).sum() == 9


def test_erase_writes_zero():
    data = np.full((4, 6, 6), 7, dtype=np.uint8)
    ed = LabelEditor(data, shape="square")
    ed.mode = "erase"
    ed.set_brush(3)
    ed.stamp(0, 1, 3, 3)
    assert (data[1, 2:5, 2:5] == 0).all()
    assert (data == 0).sum() == 9


def test_label_beyond_dtype_is_value_error():
    ed = LabelEditor(np.zeros((3, 3, 3), dtype=np.uint8))
    ed.label = 256
    with pytest.raises(ValueError, match="label: got 256"):
        ed.stamp(0, 0, 1, 1)
    ed.mode = "erase"
    ed.stamp(0, 0, 1, 1)


@pytest.mark.parametrize("call,field", [
    (lambda e: e.set_brush(0), "brush_size: got 0"),
    (lambda e: setattr(e, "label", 0), "label: got 0"),
    (lambda e: setattr(e, "mode", "blur"), "mode: got 'blur'"),
    (lambda e: e.stamp(3, 0, 0, 0), "axis: got 3"),
])
def test_error_messages(call, field):
    with pytest.raises(ValueError, match=field):
        call(LabelEditor(np.zeros((3, 3, 3), dtype=np.uint8)))


def test_constructor_errors():
    with pytest.raises(ValueError, match="data: got"):
        LabelEditor(np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="data: got"):
        LabelEditor(np.zeros((3, 3, 3), dtype=float))


def test_one_undo_step_per_stroke():
    data = np.zeros((1, 20, 20), dtype=np.uint8)
    ed = LabelEditor(data)
    ed.set_brush(3)
    ed.stroke(0, 0, [(2, 2), (2, 15)])
    first = data.copy()
    ed.begin_stroke()
    ed.stamp(0, 0, 10, 5)
    ed.stamp(0, 0, 12, 8)
    ed.end_stroke()
    assert ed.undo() is True
    assert np.array_equal(data, first)
    assert ed.undo() is True
    assert not data.any()
    assert ed.can_undo() is False and ed.undo() is False


def test_undo_restores_overwritten_labels():
    data = np.full((1, 6, 6), 5, dtype=np.uint8)
    ed = LabelEditor(data)
    ed.label = 9
    ed.stroke(0, 0, [(1, 1), (4, 4)])
    assert (data == 9).any()
    ed.undo()
    assert (data == 5).all()


def test_undo_byte_cap_drops_oldest():
    data = np.zeros((1, 30, 30), dtype=np.uint8)
    ed = LabelEditor(data, shape="square", max_undo_bytes=1)
    ed.stamp(0, 0, 5, 5)
    assert ed.can_undo() is False
    data[:] = 0
    # one 1-voxel step costs 8 (index) + 1 (value) = 9 bytes; the cap holds two steps
    ed = LabelEditor(data, shape="square", max_undo_bytes=20)
    for k in range(1, 6):
        ed.stamp(0, 0, k, k)
    steps = 0
    while ed.undo():
        steps += 1
    assert steps == 2
    assert data[0, 1, 1] == 1 and data[0, 3, 3] == 1  # older steps were dropped
    assert data[0, 4, 4] == 0 and data[0, 5, 5] == 0


def test_stroke_has_no_gap():
    data = np.zeros((1, 50, 50), dtype=np.uint8)
    ed = LabelEditor(data)
    ed.stroke(0, 0, [(0, 0), (49, 7), (3, 45)])
    plane = data[0]
    assert plane[0, 0] and plane[49, 7] and plane[3, 45]
    painted = {(int(r), int(c)) for r, c in zip(*np.nonzero(plane))}
    seen = {(0, 0)}
    todo = [(0, 0)]
    while todo:
        r, c = todo.pop()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                n = (r + dr, c + dc)
                if n in painted and n not in seen:
                    seen.add(n)
                    todo.append(n)
    assert seen == painted


@pytest.mark.parametrize("hi,dtype", [(255, np.uint8), (256, np.uint16)])
def test_nifti_round_trip(tmp_path, hi, dtype):
    data = np.zeros((4, 5, 6), dtype=np.int32)
    data[1, 2, 3] = hi
    data[0, 0, 0] = 1
    aff = np.diag([2.0, 3.0, 4.0, 1.0])
    aff[:3, 3] = [-1.0, 2.0, 5.5]
    out = tmp_path / "lab.nii.gz"
    save_label_nifti(data, aff, out)
    img = nib.load(str(out))
    assert img.get_data_dtype() == np.dtype(dtype)
    assert np.allclose(img.affine, aff)
    assert np.array_equal(np.asarray(img.dataobj), data)


def test_nifti_errors(tmp_path):
    aff = np.eye(4)
    with pytest.raises(ValueError, match="path: got"):
        save_label_nifti(np.zeros((2, 2, 2), dtype=np.uint8), aff, tmp_path / "a.nii")
    with pytest.raises(ValueError, match="data: got"):
        save_label_nifti(np.zeros((2, 2, 2)), aff, tmp_path / "a.nii.gz")
    with pytest.raises(ValueError, match="affine: got"):
        save_label_nifti(np.zeros((2, 2, 2), dtype=np.uint8), np.eye(3), tmp_path / "a.nii.gz")


def test_undo_same_voxel_two_labels_in_one_stroke():
    ed = LabelEditor(np.zeros((5, 5, 5), dtype=np.uint8))
    ed.begin_stroke()
    ed.label = 1
    ed.stamp(2, 2, 2, 2)
    ed.label = 2
    ed.stamp(2, 2, 2, 2)
    ed.end_stroke()
    assert ed.data[2, 2, 2] == 2
    ed.undo()
    assert ed.data[2, 2, 2] == 0


def test_set_brush_bad_type_message():
    ed = LabelEditor(np.zeros((3, 3, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="brush_size"):
        ed.set_brush("bad")


def test_end_stroke_reports_change_even_beyond_the_undo_cap():
    ed = LabelEditor(np.zeros((5, 5, 5), dtype=np.uint8), max_undo_bytes=0)
    ed.begin_stroke()
    assert ed.end_stroke() is False  # nothing painted
    ed.begin_stroke()
    ed.stamp(2, 2, 2, 2)
    assert ed.end_stroke() is True
    assert not ed.can_undo()  # dropped by the cap, yet reported
    assert ed.end_stroke() is False  # no stroke in progress


def test_cancel_stroke_restores_beyond_the_undo_cap():
    data = np.zeros((5, 5, 5), dtype=np.uint8)
    data[2, 2, 2] = 3
    ed = LabelEditor(data, max_undo_bytes=0)
    ed.begin_stroke()
    ed.label = 1
    ed.stamp(2, 2, 2, 2)
    ed.stamp(2, 1, 1, 1)
    assert ed.cancel_stroke() is True
    assert data[2, 2, 2] == 3 and int(data.sum()) == 3
    assert not ed.can_undo()
    assert ed.cancel_stroke() is False
