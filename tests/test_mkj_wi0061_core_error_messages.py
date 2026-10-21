"""WI-0061: core/layers.py and core/composite.py errors read '<field>: got ..., expected ...' (STYLE.md:37)."""
from __future__ import annotations

import numpy as np
import pytest

from brkraw_viewer.core.composite import layer_rgba, label_rgba, transparency_mask
from brkraw_viewer.core import composite
from brkraw_viewer.core.layers import Layer, LayerError, LayerStack


def make(lid="a", **kw):
    base = dict(id=lid, name=lid, kind="image", source="scan", space="scanner", shape=(4, 5, 6),
                affine=np.eye(4), dtype="int16")
    base.update(kw)
    return Layer(**base)


def pat(field):
    return rf"^{field}: got .*expected"


LAYER_CASES = [
    ("id", dict(id="")),
    ("kind", dict(kind="mesh")),
    ("source", dict(source="web")),
    ("frame_policy", dict(frame_policy="x")),
    ("interpolation", dict(interpolation="cubic")),
    ("shape", dict(shape=(4, 5))),
    ("affine", dict(affine=np.eye(3))),
    ("frames", dict(frames=0)),
    ("fixed_frame", dict(fixed_frame=1)),
    ("alpha", dict(alpha=1.5)),
    ("window", dict(window=(5, 1))),
    ("transparency", dict(transparency={"bogus": 1})),
    ("editable", dict(editable=True)),
    ("nbytes", dict(nbytes=-1)),
]


@pytest.mark.parametrize("field,kw", LAYER_CASES)
def test_layer_post_init_messages(field, kw):
    with pytest.raises(LayerError, match=pat(field)):
        make("x", **kw)


def stack():
    s = LayerStack()
    s.add(make("base"))
    s.add(make("lab", kind="label", frames=3))
    return s


def test_stack_messages():
    s = stack()
    with pytest.raises(LayerError, match=pat("layer_id")):
        s.get("nope")
    with pytest.raises(LayerError, match=pat("layer_id")):
        s.index("nope")
    with pytest.raises(LayerError, match=pat("id")):
        s.add(make("lab"))
    with pytest.raises(LayerError, match=pat("space")):
        s.add(make("o", space="subject_ras"))
    with pytest.raises(LayerError, match=pat("index")):
        s.add(make("o"), index=0)
    with pytest.raises(LayerError, match=pat("layer_id")):
        s.remove("base")
    with pytest.raises(LayerError, match=pat("layer_id")):
        s.move("base", 1)
    with pytest.raises(LayerError, match=pat("index")):
        s.move("lab", 5)
    with pytest.raises(LayerError, match=pat("cursor")):
        s.set_cursor([1, 2])
    with pytest.raises(LayerError, match=pat("frame")):
        s.set_frame(-1)


@pytest.mark.parametrize("field,kw", [
    ("field", dict(nbytes=3)),
    ("alpha", dict(alpha=2)),
    ("window", dict(window=(5, 1))),
    ("transparency", dict(transparency=3)),
    ("interpolation", dict(interpolation="cubic")),
    ("frame_policy", dict(frame_policy="x")),
    ("fixed_frame", dict(fixed_frame=9)),
    ("name", dict(name=3)),
    ("cmap", dict(cmap=3)),
])
def test_update_messages(field, kw):
    s = stack()
    with pytest.raises(LayerError, match=pat(field)):
        s.update("base", **kw)


def test_update_label_interpolation_and_transparency_keys():
    s = stack()
    with pytest.raises(LayerError, match=pat("interpolation")):
        s.update("lab", interpolation="linear")
    with pytest.raises(LayerError, match=pat("transparency")):
        s.update("base", transparency={"bogus": 1})


def test_composite_messages():
    v = np.zeros((3, 3), dtype=np.int16)
    lut = np.zeros((256, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match=pat("range")):
        transparency_mask(v, {"range": (5, 1)})
    with pytest.raises(ValueError, match=pat("rules")):
        transparency_mask(v, {"bogus": 1})
    with pytest.raises(ValueError, match=pat("lut")):
        layer_rgba(v, lut=np.zeros((4, 3)), vmin=0, vmax=1)
    with pytest.raises(ValueError, match=pat("alpha")):
        layer_rgba(v, lut=lut, vmin=0, vmax=1, alpha=2.0)
    with pytest.raises(ValueError, match=pat("labels")):
        label_rgba(v.astype(float), colors={})
    with pytest.raises(ValueError, match=pat("alpha")):
        label_rgba(v, colors={}, alpha=2.0)
    with pytest.raises(ValueError, match=pat("shape")):
        composite.composite_over(np.zeros((3, 3, 3)), [(np.zeros((2, 2, 3)), np.zeros((2, 2)))])


def test_layer_dtype_and_channels_messages():
    with pytest.raises(LayerError, match=r"^dtype: got .*expected"):
        make("x", kind="rgb", source="array", shape=(4, 5, 6, 3), dtype="int16")
    with pytest.raises(LayerError, match=r"^channels: got .*expected"):
        make("x", channels=2)


def test_rgb_rgba_values_messages():
    with pytest.raises(ValueError, match=r"^values: got .*expected"):
        composite.rgb_rgba(np.zeros((3, 3, 3), dtype=np.complex64))
    with pytest.raises(ValueError, match=r"^values: got .*expected"):
        composite.rgb_rgba(np.zeros((3, 3, 5), dtype=np.uint8))
