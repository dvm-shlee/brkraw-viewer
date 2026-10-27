"""Tests for per-label timecourse means."""

import numpy as np
import pytest

from brkraw_viewer.core.labelstats import label_timecourse


def _ref(data, labels, value):
    d = data if data.ndim == 4 else data[..., None]
    return np.nanmean(d[labels == value], axis=0)


def test_label_zero_skipped_and_absent_not_reported():
    labels = np.zeros((2, 2, 2), dtype=np.int32)
    labels[0, 0, 0] = 1
    labels[1, 1, 1] = 3
    out = label_timecourse(np.ones((2, 2, 2)), labels)
    assert list(out) == [1, 3]
    assert 0 not in out and 2 not in out
    assert all(type(k) is int for k in out)


def test_all_background_gives_empty_dict():
    assert label_timecourse(np.ones((2, 2, 2)), np.zeros((2, 2, 2), dtype=int)) == {}


def test_3d_gives_length_one():
    rng = np.random.default_rng(0)
    data = rng.random((4, 4, 4))
    labels = rng.integers(0, 3, size=(4, 4, 4))
    out = label_timecourse(data, labels)
    assert out
    for k, v in out.items():
        assert v.shape == (1,)
        assert abs(v[0] - data[labels == k].mean()) < 1e-12


def test_4d_matches_mask_mean():
    rng = np.random.default_rng(1)
    data = rng.random((5, 4, 3, 7))
    labels = rng.integers(0, 4, size=(5, 4, 3))
    out = label_timecourse(data, labels)
    assert list(out) == [1, 2, 3]
    for k in (1, 2, 3):
        assert out[k].shape == (7,)
        assert np.max(np.abs(out[k] - _ref(data, labels, k))) < 1e-12


def test_nan_ignored_and_all_nan_frame_is_nan():
    data = np.ones((2, 2, 1, 3))
    labels = np.ones((2, 2, 1), dtype=int)
    data[..., 0] = 2.0
    data[0, 0, 0, 0] = np.nan
    data[..., 1] = np.nan
    out = label_timecourse(data, labels)[1]
    assert out[0] == 2.0
    assert np.isnan(out[1])
    assert out[2] == 1.0


def test_sparse_large_label_values():
    rng = np.random.default_rng(2)
    data = rng.random((3, 3, 3, 4))
    labels = np.zeros((3, 3, 3), dtype=np.int64)
    labels[:2] = 7
    labels[2, :2] = 60000
    out = label_timecourse(data, labels)
    assert list(out) == [7, 60000]
    for k in out:
        assert np.max(np.abs(out[k] - _ref(data, labels, k))) < 1e-12


def test_error_messages():
    data = np.ones((2, 2, 2))
    with pytest.raises(ValueError, match=r"labels\.dtype: got float64, expected"):
        label_timecourse(data, np.ones((2, 2, 2)))
    neg = np.zeros((2, 2, 2), dtype=int)
    neg[0, 0, 0] = -1
    with pytest.raises(ValueError, match=r"labels: got minimum -1, expected"):
        label_timecourse(data, neg)
    with pytest.raises(ValueError, match=r"labels\.shape: got \(2, 2, 3\), expected \(2, 2, 2\)"):
        label_timecourse(data, np.zeros((2, 2, 3), dtype=int))
    with pytest.raises(ValueError, match=r"data\.ndim: got 2, expected 3 or 4"):
        label_timecourse(np.ones((2, 2)), np.zeros((2, 2), dtype=int))
    with pytest.raises(ValueError, match=r"data\.ndim: got 5, expected 3 or 4"):
        label_timecourse(np.ones((2, 2, 2, 2, 2)), np.zeros((2, 2, 2), dtype=int))


def test_large_4d_case():
    rng = np.random.default_rng(3)
    data = rng.random((64, 64, 32, 200), dtype=np.float32)
    labels = rng.integers(0, 20, size=(64, 64, 32))
    out = label_timecourse(data, labels)
    assert len(out) == 19
    assert out[5].shape == (200,)
    ref = data[labels == 5].astype(np.float64).mean(axis=0)
    assert np.max(np.abs(out[5] - ref)) < 1e-9
