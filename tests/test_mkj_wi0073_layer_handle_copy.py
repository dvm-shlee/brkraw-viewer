"""Headless tests for LayerHandle copy=False, get_overlay_array and space check (WI-0073, S4-1)."""
from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from brkraw_viewer.core.layer_handle import LayerHandle
from brkraw_viewer.core.layers import Layer, LayerStack


def make(shape=(4, 5, 6)):
    stack, data, calls = LayerStack(), {}, []
    stack.add(Layer(id="base", name="base", kind="image", source="scan", space="scanner",
                    shape=shape, affine=np.eye(4), dtype="int16"))
    data["base"] = np.zeros((1, 1, 1), dtype=np.int16)
    return stack, data, calls, LayerHandle(stack, data, on_change=lambda: calls.append(1))


def msg(fn, *a, **k):
    with pytest.raises(ValueError) as e:
        fn(*a, **k)
    text = str(e.value)
    assert ": got" in text and "expected" in text, text
    return text


def test_copy_true_isolates_source():
    stack, data, _, h = make()
    src = np.ones((4, 5, 6), dtype=np.float32)
    lid = h.add_overlay(src, np.eye(4), name="a")
    src[:] = 7
    assert float(data[lid].max()) == 1.0
    assert stack.get(lid).nbytes == data[lid].nbytes == src.nbytes


def test_copy_false_shares_and_refreshes():
    stack, data, calls, h = make()
    src = np.ones((4, 5, 6), dtype=np.float32)
    lid = h.add_overlay(src, np.eye(4), name="a", copy=False)
    assert data[lid] is src and np.shares_memory(src, data[lid])
    assert stack.get(lid).nbytes == src.nbytes
    src[0, 0, 0] = 5
    assert h.get_overlay_array(lid, copy=False)[0, 0, 0] == 5
    n = len(calls)
    h.set_overlay(lid)
    assert len(calls) == n + 1


def test_bad_data_type_and_bad_copy_flag():
    _, _, _, h = make()
    assert "data: got list" in msg(h.add_overlay, [[[1]]], np.eye(4), name="a", copy=False)
    assert "copy: got" in msg(h.add_overlay, np.ones((4, 5, 6)), np.eye(4), name="a", copy="yes")
    lid = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a")
    assert "copy: got" in msg(h.get_overlay_array, lid, copy="yes")


def test_get_overlay_array_copy_and_view():
    _, data, _, h = make()
    lid = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a")
    c = h.get_overlay_array(lid)
    assert np.array_equal(c, data[lid]) and not np.shares_memory(c, data[lid])
    v = h.get_overlay_array(lid, copy=False)
    assert v.flags.writeable is False and np.shares_memory(v, data[lid])
    with pytest.raises(ValueError):
        v[0, 0, 0] = 3
    assert data[lid].flags.writeable
    assert "layer_id: got" in msg(h.get_overlay_array, "nope")
    assert "layer_id: got" in msg(h.get_overlay_array, "base")


def test_space_shape_affine_mismatch_store_nothing():
    stack, data, calls, h = make()
    before = h.list_layers()
    assert "space: got" in msg(h.add_overlay, np.ones((4, 5, 6)), np.eye(4), name="a", space="other")
    assert "shape: got" in msg(h.add_overlay, np.ones((3, 5, 6)), np.eye(4), name="a")
    assert "affine: got" in msg(h.add_overlay, np.ones((4, 5, 6)), np.eye(4) * 2, name="a")
    assert len(h.list_layers()) == len(before) and len(data) == 1 and not calls
    h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="ok", space="scanner")


def test_large_volume_memory_tracemalloc():
    stack, data, _, h = make(shape=(256, 256, 256))
    big = np.zeros((256, 256, 256), dtype=np.float32)
    assert big.nbytes >= 64 * 1024 * 1024
    tracemalloc.start()
    try:
        base0 = tracemalloc.get_traced_memory()[0]
        lid0 = h.add_overlay(big, np.eye(4), name="ref", copy=False)
        used0 = tracemalloc.get_traced_memory()[0] - base0
        base1 = tracemalloc.get_traced_memory()[0]
        lid1 = h.add_overlay(big, np.eye(4), name="cp", copy=True)
        used1 = tracemalloc.get_traced_memory()[0] - base1
    finally:
        tracemalloc.stop()
    assert used0 < 1024 * 1024
    assert used1 >= big.nbytes
    assert stack.get(lid0).nbytes == big.nbytes == stack.get(lid1).nbytes == data[lid1].nbytes
    assert data[lid0] is big
