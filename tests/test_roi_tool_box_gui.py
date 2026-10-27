"""GUI test of the "ROI tool" box of the Viewer tab in a real Tk window.

Same set-up as tests/test_paint_tool_gui.py (a real ``MainWindow``, a synthetic 4D phantom loaded
through the faked worker, mouse input by ``event_generate`` on the view canvases). Runs only with a
display and ``BRKRAW_VIEWER_SMOKE=1`` (use Xvfb, docs/dev/gui.md).

- the box sits in the top row between Orientation and Hook; the axis bar above the views has no
  ROI or Paint boxes;
- the modes Crosshair (default), Selection and Drawing; the shape row shows only in Selection;
- Selection sets a square and a circle ROI and returns to Crosshair, the ROI stays;
- Drawing: the left button paints, the right button erases (voxel values asserted);
- the colour button of the painted label: callback, new colour, Cancel, bad rgb;
- leaving Drawing ends a stroke, leaving Selection clears a drag;
"""

from __future__ import annotations

from tkinter import colorchooser, ttk

import numpy as np
import pytest

from brkraw_viewer.core.roi import RoiDrag
from test_paint_tool_gui import _new_layer, gui  # noqa: F401  (fixture: window on a 4D phantom)


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _frame_by_text(root, text):
    found = [w for w in _walk(root) if isinstance(w, ttk.LabelFrame) and str(w.cget("text")) == text]
    assert len(found) == 1, f"LabelFrame {text!r}: found {len(found)}"
    return found[0]


def test_box_sits_between_orientation_and_hook(gui):
    gui.root.update()
    tab = gui.win.tabs.get_tab("Viewer")._tab_instance
    box = _frame_by_text(tab.top, "ROI tool")
    assert box is tab.top.tool_box
    orientation = _frame_by_text(tab.top, "Orientation")
    hook = _frame_by_text(tab.top, "Hook")
    control = _frame_by_text(tab.top, "Control")
    value = _frame_by_text(tab.top, "Value")
    x = {name: w.winfo_rootx() for name, w in (
        ("orientation", orientation), ("box", box), ("hook", hook), ("value", value), ("control", control))}
    assert x["orientation"] < x["box"] < x["hook"]
    assert x["hook"] <= x["value"] < x["control"]  # Value and Control keep their order to the right
    assert box.winfo_ismapped()
    assert not any(w is box for w in _walk(tab.right))


def test_axis_bar_has_no_roi_or_paint_boxes(gui):
    texts = set()
    for w in _walk(gui.right):
        if isinstance(w, (ttk.Radiobutton, ttk.Button, ttk.Label)):
            texts.add(str(w.cget("text")))
    assert not texts & {"ROI", "Paint", "Erase", "Off", "Brush", "Undo", "Square", "Circle", "Colour"}
    assert {"X", "Y", "Z"} <= texts  # the axis boxes stay


def test_three_modes_and_the_default(gui):
    box = gui.box
    assert [str(box._mode_radios[m].cget("text")) for m in ("crosshair", "selection", "drawing")] == [
        "Crosshair", "Selection", "Drawing"]
    assert box.mode == "crosshair" and box.shape == "square"
    assert gui.right._roi_tool_var.get() == "off" and gui.right._roi_drag.tool == "off"
    assert not gui.paint.active
    assert not box.shape_row.winfo_ismapped()  # the shape row is for Selection only
    start = gui.idx()
    row, col = (start[1] + 5) % 28, (start[0] + 7) % 32
    gui.press(row, col)
    gui.release(row, col)
    assert gui.idx()[:2] == (col, row)  # Crosshair: a click moves the crosshair

    box._mode_radios["selection"].invoke()
    gui.root.update()
    assert box.mode == "selection" and box.shape_row.winfo_ismapped()
    assert gui.right._roi_drag.tool == "square" and gui.right._roi_tool_var.get() == "square"
    box._mode_radios["crosshair"].invoke()
    gui.root.update()
    assert not box.shape_row.winfo_ismapped() and gui.right._roi_drag.tool == "off"


def test_drawing_radio_needs_an_editable_label_layer(gui):
    assert str(gui.box._mode_radios["drawing"].cget("state")) == "disabled"
    _new_layer(gui)
    assert str(gui.box._mode_radios["drawing"].cget("state")) == "normal"


def test_selection_sets_square_and_circle_roi_and_returns_to_crosshair(gui):
    ctrl, box = gui.ctrl, gui.box
    before = gui.idx()
    for shape, kind in (("square", "rect"), ("circle", "ellipse")):
        box._mode_radios["selection"].invoke()
        box._shape_radios[shape].invoke()
        gui.root.update()
        gui.stroke((5, 4), (12, 14))
        assert ctrl._roi is not None and ctrl._roi["shape"] == kind and ctrl._roi["axis"] == 2
        ref = RoiDrag()
        ref.set_tool(shape)
        ref.press("xy", 5, 4)
        _axis, _shape, geometry = ref.release("xy", 12, 14)
        assert ctrl._roi["geometry"] == tuple(geometry)  # same path as the former tools
        assert box.mode == "crosshair"  # one shot
        assert gui.right._roi_drag.tool == "off"
        assert gui.views["xy"]._shape_data is not None  # the ROI stays shown
    assert gui.idx() == before  # selecting never moved the crosshair
    gui.key("<Escape>")
    assert ctrl._roi is None and gui.views["xy"]._shape_data is None


def test_drawing_left_drag_paints_and_right_drag_erases(gui):
    ctrl = gui.ctrl
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    gui.box._mode_radios["drawing"].invoke()
    gui.root.update()
    assert gui.box.mode == "drawing" and gui.paint.active
    assert gui.right._roi_drag.tool == "off"
    z, crosshair = gui.idx()[2], gui.idx()
    assert not data.any()

    gui.btn = 1
    gui.stroke((5, 4), (5, 14))  # rows = y, cols = x of the axial view
    assert data[4:15, 5, z].tolist() == [1] * 11
    assert gui.idx() == crosshair  # no crosshair move while drawing

    gui.btn = 3
    gui.stroke((5, 8), (5, 10))  # the right button erases
    assert data[4:15, 5, z].tolist() == [1] * 4 + [0] * 3 + [1] * 4
    assert set(np.unique(data)) == {0, 1}
    assert gui.idx() == crosshair
    gui.key("<Control-z>")  # an erase stroke is one undo step, as before
    assert data[4:15, 5, z].tolist() == [1] * 11
    gui.key("<Control-z>")
    assert not data.any()
    assert lid in ctrl._layers.ids()


def test_a_stroke_of_one_button_ignores_the_other_button(gui):
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    gui.box._mode_radios["drawing"].invoke()
    z = gui.idx()[2]
    gui.btn = 1
    gui.press(5, 4)
    gui.btn = 3
    gui.press(5, 6)  # a second press while the left stroke runs is ignored
    gui.motion(5, 8)
    gui.release(5, 8)
    gui.btn = 1
    gui.motion(5, 5)
    gui.release(5, 5)
    assert data[4, 5, z] == 1 and data[5, 5, z] == 1 and data[6, 5, z] == 0 and data[8, 5, z] == 0


def test_colour_button_sets_the_label_colour(gui, monkeypatch):
    ctrl, paint = gui.ctrl, gui.paint
    assert str(paint.color_button.cget("state")) == "disabled"  # no paint target
    assert ctrl.viewer_paint_color() is None
    lid, data = _new_layer(gui)
    assert str(paint.color_button.cget("state")) == "normal"
    default = ctrl.viewer_paint_color()
    assert default is not None and paint.color == default
    assert str(paint.color_button.cget("bg")) == "#%02x%02x%02x" % default

    seen = []

    def fake(**kw):
        seen.append(kw)
        return ((10, 200, 30), "#0ac81e")

    monkeypatch.setattr(colorchooser, "askcolor", fake)
    paint.color_button.invoke()
    gui.root.update()
    assert len(seen) == 1
    assert ctrl._layer_label_colors[lid][1] == (10, 200, 30)
    assert ctrl.viewer_paint_color() == (10, 200, 30) and paint.color == (10, 200, 30)
    assert str(paint.color_button.cget("bg")) == "#0ac81e"

    gui.paint.brush_var.set(1)  # the colour survives painting
    gui.box._mode_radios["drawing"].invoke()
    gui.btn = 1
    gui.press(5, 4)
    gui.release(5, 4)
    assert data.any() and ctrl._layer_label_colors[lid][1] == (10, 200, 30)
    z = gui.idx()[2]
    assert data[4, 5, z] == 1
    planes = ctrl._layer_planes(ctrl._display_grid(), gui.idx(), ctrl.state.viewer.frame_index)
    rgb = np.asarray(planes["xy"][0][0])
    assert tuple(int(round(float(c))) for c in rgb[5, 4][:3]) == (10, 200, 30)  # drawn in the chosen colour

    monkeypatch.setattr(colorchooser, "askcolor", lambda **kw: (None, None))  # Cancel
    paint.color_button.invoke()
    gui.root.update()
    assert ctrl.viewer_paint_color() == (10, 200, 30)
    assert str(paint.color_button.cget("bg")) == "#0ac81e"


def test_on_viewer_paint_color_rejects_a_bad_rgb(gui):
    ctrl = gui.ctrl
    assert ctrl.on_viewer_paint_color((1, 2, 3)) is False  # no paint target
    _new_layer(gui)
    assert ctrl.on_viewer_paint_color((1, 2, 3)) is True
    for bad in ((1, 2), (1, 2, 3, 4), (0, 0, 256), (-1, 0, 0), (1.5, 2, 3), (1, 2, "3"), "red", None):
        with pytest.raises(ValueError, match="rgb: got .* expected three ints in 0..255"):
            ctrl.on_viewer_paint_color(bad)
    assert ctrl.viewer_paint_color() == (1, 2, 3)  # unchanged


def test_leaving_drawing_ends_a_stroke_and_leaving_selection_clears_a_drag(gui):
    ctrl, box = gui.ctrl, gui.box
    _lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    box._mode_radios["drawing"].invoke()
    gui.btn = 1
    gui.press(10, 10)
    assert ctrl._paint_stroke is not None
    box._mode_radios["crosshair"].invoke()
    gui.root.update()
    assert ctrl._paint_stroke is None and not gui.paint.active
    assert not data.any()  # switching tools drops the stroke in progress

    box._mode_radios["selection"].invoke()
    gui.press(5, 4)
    gui.motion(9, 9)
    assert gui.right._roi_drag.dragging
    box._mode_radios["drawing"].invoke()
    gui.root.update()
    assert not gui.right._roi_drag.dragging and ctrl._roi is None
    assert gui.right._roi_drag.tool == "off" and box.mode == "drawing"
