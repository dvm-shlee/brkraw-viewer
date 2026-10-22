"""Headless tests for core/layer_handle.py (WI-0067, stage 4 item 1)."""
from __future__ import annotations

import re

import numpy as np
import pytest

from brkraw_viewer.core.layer_handle import LayerHandle, LayerInfo
from brkraw_viewer.core.layers import Layer, LayerError, LayerStack


def make(with_base=True):
    stack, data, calls = LayerStack(), {}, []
    if with_base:
        stack.add(Layer(id="base", name="base", kind="image", source="scan", space="scanner",
                        shape=(4, 5, 6), affine=np.eye(4), dtype="int16"))
        data["base"] = np.zeros((4, 5, 6), dtype=np.int16)
    return stack, data, calls, LayerHandle(stack, data, on_change=lambda: calls.append(1))


def raises(exc, field, fn, *a, **k):
    with pytest.raises(exc) as e:
        fn(*a, **k)
    assert re.match(rf"^{field}: got .*expected", str(e.value)), str(e.value)


def test_list_order_and_copy():
    stack, data, calls, h = make()
    assert make(False)[3].list_layers() == []
    h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a")
    h.add_overlay(np.ones((4, 5, 6, 2)), np.eye(4), name="b")
    infos = h.list_layers()
    assert [i.id for i in infos] == stack.ids() and infos[0].id == "base"
    assert isinstance(infos[1], LayerInfo) and infos[2].frames == 2 and infos[1].source == "array"
    infos[1].affine[0, 0] = 9
    assert stack.get(infos[1].id).affine[0, 0] == 1


def test_add_remove_round_trip():
    stack, data, calls, h = make()
    lid = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a", cmap="hot", alpha=0.5)
    assert lid in stack.ids() and lid in data and stack.get(lid).cmap == "hot"
    h.remove_overlay(lid)
    assert lid not in stack.ids() and lid not in data and len(calls) == 2


def test_duplicate_layer_id_gets_unique():
    _, _, _, h = make()
    a = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a", layer_id="x")
    b = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="b", layer_id="x")
    assert a == "x" and b != a


def test_unknown_and_base_refusal():
    _, _, calls, h = make()
    raises(ValueError, "layer_id", h.set_overlay, "nope", alpha=0.5)
    raises(ValueError, "layer_id", h.remove_overlay, "nope")
    raises(ValueError, "layer_id", h.set_overlay, "base", alpha=0.5)
    raises(ValueError, "layer_id", h.remove_overlay, "base")
    assert calls == []


def test_remove_not_added_through_handle():
    stack, data, calls, h = make()
    stack.add(Layer(id="ext", name="ext", kind="image", source="array", space="scanner",
                    shape=(4, 5, 6), affine=np.eye(4), dtype="int16"))
    raises(ValueError, "layer_id", h.remove_overlay, "ext")
    assert calls == []


def test_two_d_and_no_base():
    _, _, calls, h = make()
    raises(ValueError, "data", h.add_overlay, np.zeros((4, 4)), np.eye(4), name="a")
    raises(ValueError, "image", make(False)[3].add_overlay, np.zeros((4, 5, 6)), np.eye(4), name="a")
    assert calls == []


def test_copy_semantics():
    stack, data, _, h = make()
    src = np.ones((4, 5, 6))
    lid = h.add_overlay(src, np.eye(4), name="a")
    src[:] = 7
    assert data[lid].max() == 1 and data[lid] is not src


def test_grid_refusal():
    _, _, calls, h = make()
    raises(ValueError, "shape", h.add_overlay, np.zeros((3, 5, 6)), np.eye(4), name="a")
    aff = np.eye(4)
    aff[0, 3] = 5
    raises(ValueError, "affine", h.add_overlay, np.zeros((4, 5, 6)), aff, name="a")
    assert calls == []


def test_kind_and_editable():
    stack, data, calls, h = make()
    raises(ValueError, "kind", h.add_overlay, np.zeros((4, 5, 6)), np.eye(4), name="a", kind="rgb")
    raises(ValueError, "editable", h.add_overlay, np.zeros((4, 5, 6)), np.eye(4), name="a", editable=True)
    raises(ValueError, "field", h.add_overlay, np.zeros((4, 5, 6)), np.eye(4), name="a", editable_x=1)
    assert calls == [] and len(stack) == 1
    lid = h.add_overlay(np.zeros((4, 5, 6)), np.eye(4), name="l", kind="label", editable=True)
    assert stack.get(lid).editable and len(calls) == 1


def test_set_overlay_and_on_change():
    stack, _, calls, h = make()
    lid = h.add_overlay(np.ones((4, 5, 6)), np.eye(4), name="a")
    h.set_overlay(lid, alpha=0.3, visible=False)
    assert stack.get(lid).alpha == 0.3 and len(calls) == 2
    raises(LayerError, "alpha", h.set_overlay, lid, alpha=3)
    raises(LayerError, "field", h.set_overlay, lid, bogus=1)
    assert len(calls) == 2
