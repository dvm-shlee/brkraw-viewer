"""C2 layer list and events (contract v0.1, WI-0072). Tk-free."""
from __future__ import annotations

import numpy as np
import pytest

from brkraw_viewer.core.layers import Layer, LayerError, LayerStack


def layer(lid, **kw):
    base = dict(id=lid, name=lid, kind="image", source="scan", space="scanner", shape=(4, 5, 6), affine=np.eye(4), dtype="int16")
    base.update(kw)
    return Layer(**base)


@pytest.fixture
def stack():
    s = LayerStack()
    events = []
    s.subscribe(lambda e, i, d: events.append((e, i, d)))
    s.events = events  # type: ignore[attr-defined]
    return s


def test_layer_validation_and_normalisation():
    lay = layer("a", shape=[4.0, 5, 6, 3], affine=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], frames="3", window=(1, 5))
    assert lay.shape == (4, 5, 6, 3) and lay.affine.dtype == np.float64 and lay.frames == 3
    assert lay.window == (1.0, 5.0)
    assert layer("l", kind="label", interpolation="linear").interpolation == "nearest"
    bad = [
        dict(id=""), dict(kind="mesh"), dict(source="web"), dict(frame_policy="x"), dict(interpolation="cubic"),
        dict(shape=(4, 5)), dict(shape=(4, 0, 6)), dict(affine=np.eye(3)), dict(frames=0), dict(fixed_frame=1),
        dict(alpha=1.5), dict(window=(5, 1)), dict(window=(np.nan, 1)), dict(transparency={"bogus": 1}),
        dict(editable=True), dict(nbytes=-1),
    ]
    words = ["id", "kind", "source", "frame_policy", "interpolation", "shape", "shape", "affine", "frames",
             "fixed_frame", "alpha", "window", "window", "transparency", "editable", "nbytes"]
    for kw, word in zip(bad, words):
        with pytest.raises(LayerError, match=word):
            layer("x", **kw)
    assert layer("l2", kind="label", editable=True).editable is True
    assert issubclass(LayerError, ValueError)


def test_add_base_then_layers_with_index_and_space_rule(stack):
    assert stack.base is None
    assert stack.add(layer("base"), index=5) == 0
    assert stack.add(layer("a")) == 1
    assert stack.add(layer("b"), index=1) == 1
    assert stack.ids() == ["base", "b", "a"] and stack.base.id == "base" and len(stack) == 3
    assert [e[:2] for e in stack.events] == [("layer_added", "base"), ("layer_added", "a"), ("layer_added", "b")]
    with pytest.raises(LayerError, match="duplicate"):
        stack.add(layer("a"))
    with pytest.raises(LayerError, match=r"space.*subject_ras.*scanner"):
        stack.add(layer("c", space="subject_ras"))
    with pytest.raises(LayerError, match="index"):
        stack.add(layer("d"), index=0)
    with pytest.raises(LayerError, match="index"):
        stack.add(layer("d"), index=9)
    assert len(stack) == 3


def test_remove_move_and_base_protection(stack):
    for lid in ("base", "a", "b", "c"):
        stack.add(layer(lid, nbytes=10))
    stack.events.clear()
    with pytest.raises(LayerError, match="base"):
        stack.remove("base")
    with pytest.raises(LayerError, match="base"):
        stack.move("base", 2)
    with pytest.raises(LayerError, match="index"):
        stack.move("a", 0)
    with pytest.raises(LayerError, match="unknown"):
        stack.remove("zz")
    stack.move("a", 1)  # no change: no event
    assert stack.events == []
    stack.move("a", 3)
    assert stack.ids() == ["base", "b", "c", "a"]
    assert stack.events[-1] == ("order_changed", None, {"order": ["base", "b", "c", "a"]})
    removed = stack.remove("c")
    assert removed.id == "c"
    assert stack.events[-1] == ("layer_removed", "c", {"index": 2, "nbytes": 10, "source": "scan"})
    for lid in ("b", "a", "base"):
        stack.remove(lid)
    assert len(stack) == 0 and stack.base is None


def test_update_validates_all_first_and_emits_per_changed_field(stack):
    stack.add(layer("base"))
    stack.add(layer("lab", kind="label", frames=3))
    stack.events.clear()
    with pytest.raises(LayerError, match="field.*nbytes"):
        stack.update("base", alpha=0.5, nbytes=3)
    with pytest.raises(LayerError, match="interpolation"):
        stack.update("lab", interpolation="linear")
    with pytest.raises(LayerError, match="alpha"):
        stack.update("base", visible=False, alpha=2)
    assert stack.get("base").visible is True and stack.events == []  # nothing changed
    changed = stack.update("base", alpha=0.5, visible=True, window=[0, 10], transparency={"zero": True})
    assert changed == ["alpha", "window", "transparency"]
    assert [e[2]["field"] for e in stack.events] == changed
    assert stack.get("base").window == (0.0, 10.0)
    assert stack.update("base", window=(0, 10), alpha=0.5) == []
    assert stack.update("lab", fixed_frame=2, frame_policy="fixed") == ["fixed_frame", "frame_policy"]
    with pytest.raises(LayerError, match="fixed_frame"):
        stack.update("lab", fixed_frame=3)
    with pytest.raises(LayerError, match="name"):
        stack.update("lab", name=3)


def test_frame_policy_cursor_frame_and_bytes(stack):
    stack.add(layer("base", frames=10, nbytes=100))
    stack.add(layer("same", frames=10, nbytes=50, source="file"))
    stack.add(layer("other", frames=3, fixed_frame=2, nbytes=7, source="array"))
    stack.add(layer("pinned", frames=10, frame_policy="fixed", fixed_frame=4, nbytes=1))
    stack.set_frame(6)
    assert stack.frame_for("same") == 6 and stack.frame_for("same", 9) == 9
    assert stack.frame_for("other") == 2  # linked, different count -> fixed
    assert stack.frame_for("pinned") == 4
    assert stack.held_nbytes() == 151 and stack.total_nbytes() == 158
    stack.events.clear()
    stack.set_frame(6)
    stack.set_cursor((1, 2, 3))
    stack.set_cursor([1.0, 2.0, 3.0])
    assert stack.events == [("cursor_moved", None, {"cursor": (1.0, 2.0, 3.0)})]
    with pytest.raises(LayerError, match="cursor"):
        stack.set_cursor((1, 2))
    with pytest.raises(LayerError, match="frame"):
        stack.set_frame(-1)


def test_subscribe_order_and_unsubscribe():
    s = LayerStack()
    seen = []
    off_a = s.subscribe(lambda e, i, d: seen.append(("a", e)))
    s.subscribe(lambda e, i, d: seen.append(("b", e)))
    s.add(layer("base"))
    off_a()
    off_a()
    s.set_frame(2)
    assert seen == [("a", "layer_added"), ("b", "layer_added"), ("b", "frame_changed")]


def test_layers_compare_by_identity():
    a, b = layer("a"), layer("a")
    assert a != b and a == a
