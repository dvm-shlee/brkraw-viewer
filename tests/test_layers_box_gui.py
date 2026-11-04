"""GUI test of the "Layers" box of the Viewer tab in a real Tk window.

Same set-up as tests/test_paint_tool_gui.py (a real ``MainWindow``, a synthetic 4D phantom loaded
through the faked worker). Runs only with a display and ``BRKRAW_VIEWER_SMOKE=1`` (use Xvfb,
docs/dev/gui.md).

- the box sits in the top row, right of Control;
- the list shows the layers in draw order, the base layer last and marked "(base)";
- selecting an editable label layer enables Drawing, any other row disables it;
- New label layer adds a layer and selects it;
- Up and Down change the order of the layer stack and are disabled for the base and at the ends;
- Delete removes a layer (the unsaved-edits question is patched) and never the base;
- colormap and display range apply to an image layer; invalid ranges change nothing;
- the list follows the Python layers API and the visibility toggle.
"""

from __future__ import annotations

from tkinter import messagebox, ttk

import numpy as np
import pytest

from test_paint_tool_gui import _new_layer, gui  # noqa: F401  (fixture: window on a 4D phantom)


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _frame_by_text(root, text):
    found = [w for w in _walk(root) if isinstance(w, ttk.LabelFrame) and str(w.cget("text")) == text]
    assert len(found) == 1, f"LabelFrame {text!r}: found {len(found)}"
    return found[0]


def _state(widget) -> str:
    return str(widget.cget("state"))


def _select(gui, layer_id):
    gui.layers.tree.selection_set(layer_id)
    gui.root.update()
    assert gui.layers.selected_layer == layer_id


def _add_image(gui, name="img"):
    grid = gui.ctrl._display_grid()
    data = np.arange(int(np.prod(grid.shape)), dtype=np.float32).reshape(grid.shape)
    lid = gui.ctrl._add_array_layer(data, grid.affine, name=name)
    gui.root.update()
    return lid


def _add_label(gui, name="lab"):
    grid = gui.ctrl._display_grid()
    lid = gui.ctrl._add_array_layer(np.zeros(grid.shape, np.uint8), grid.affine, name=name, kind="label")
    gui.root.update()
    return lid


def _listed(gui):
    return list(gui.layers.tree.get_children())


def test_box_sits_right_of_control(gui):
    gui.root.update()
    tab = gui.win.tabs.get_tab("Viewer")._tab_instance
    box = _frame_by_text(tab.top, "Layers")
    control = _frame_by_text(tab.top, "Control")
    assert box is tab.top.layers_box is gui.layers
    assert box.winfo_ismapped()
    assert control.winfo_rootx() < box.winfo_rootx()
    assert control.winfo_rootx() + control.winfo_width() <= box.winfo_rootx()


def test_list_order_and_base_marking(gui):
    ctrl = gui.ctrl
    base_id = ctrl._layers.ids()[0]
    assert _listed(gui) == [base_id]
    first = _add_image(gui, "first")
    second = _add_label(gui, "second")
    assert ctrl._layers.ids() == [base_id, first, second]
    assert _listed(gui) == [second, first, base_id]  # the layer drawn last is on top
    tree = gui.layers.tree
    assert str(tree.set(base_id, "name")).endswith("(base)")
    assert "(base)" not in str(tree.set(first, "name")) and str(tree.set(first, "name")) == "first"
    assert str(tree.set(first, "kind")) == "image" and str(tree.set(second, "kind")) == "label"
    assert str(tree.set(first, "vis")) == "☑"


def test_visibility_toggle_sets_visible(gui):
    ctrl = gui.ctrl
    lid = _add_image(gui)
    assert ctrl._layers.get(lid).visible
    gui.layers.toggle_visible(lid)
    gui.root.update()
    assert not ctrl._layers.get(lid).visible
    assert str(gui.layers.tree.set(lid, "vis")) == "☐"
    gui.layers.toggle_visible(lid)
    gui.root.update()
    assert ctrl._layers.get(lid).visible and str(gui.layers.tree.set(lid, "vis")) == "☑"


def test_selecting_a_label_layer_enables_drawing_and_an_image_layer_disables_it(gui):
    ctrl = gui.ctrl
    img = _add_image(gui)
    lab, _data = _new_layer(gui)
    assert gui.layers.selected_layer == lab and ctrl._selected_layer_id == lab
    assert gui.radio_state("paint") == "normal"
    gui.mode("paint")
    assert gui.paint.active
    _select(gui, img)
    assert ctrl._selected_layer_id is None
    assert gui.radio_state("paint") == "disabled" and not gui.paint.active
    assert str(gui.paint.color_button.cget("state")) == "disabled"
    _select(gui, lab)
    assert ctrl._selected_layer_id == lab and gui.radio_state("paint") == "normal"
    assert str(gui.paint.color_button.cget("state")) == "normal"
    base_id = ctrl._layers.ids()[0]
    _select(gui, base_id)
    assert ctrl._selected_layer_id is None and gui.radio_state("paint") == "disabled"


def test_a_label_layer_without_editing_does_not_enable_drawing(gui):
    lab = _add_label(gui)
    _select(gui, lab)
    assert gui.ctrl._selected_layer_id is None and gui.radio_state("paint") == "disabled"


def test_new_label_layer_adds_and_selects(gui):
    ctrl = gui.ctrl
    before = list(ctrl._layers.ids())
    assert str(gui.layers.new_button.cget("state")) == "normal"
    gui.layers.new_button.invoke()
    gui.root.update()
    added = [i for i in ctrl._layers.ids() if i not in before]
    assert len(added) == 1
    lid = added[0]
    assert ctrl._layers.get(lid).kind == "label" and ctrl._layers.get(lid).editable
    assert _listed(gui)[0] == lid and gui.layers.selected_layer == lid
    assert gui.layers.tree.selection() == (lid,)
    assert gui.radio_state("paint") == "normal"
    gui.layers.new_button.invoke()
    gui.root.update()
    assert len(ctrl._layers.ids()) == len(before) + 2
    assert gui.layers.selected_layer == ctrl._selected_layer_id != lid


def test_up_and_down_change_the_order(gui):
    ctrl = gui.ctrl
    base_id = ctrl._layers.ids()[0]
    a, b, c = _add_image(gui, "a"), _add_image(gui, "b"), _add_image(gui, "c")
    assert ctrl._layers.ids() == [base_id, a, b, c]
    _select(gui, base_id)
    assert _state(gui.layers.up_button) == _state(gui.layers.down_button) == "disabled"
    _select(gui, c)  # the top row: Up is disabled
    assert _state(gui.layers.up_button) == "disabled" and _state(gui.layers.down_button) == "normal"
    gui.layers.down_button.invoke()
    gui.root.update()
    assert ctrl._layers.ids() == [base_id, a, c, b]
    assert _listed(gui) == [b, c, a, base_id] and gui.layers.selected_layer == c
    assert _state(gui.layers.up_button) == "normal" and _state(gui.layers.down_button) == "normal"
    gui.layers.down_button.invoke()
    gui.root.update()
    assert ctrl._layers.ids() == [base_id, c, a, b]
    assert _state(gui.layers.down_button) == "disabled"  # next to the base
    assert _state(gui.layers.up_button) == "normal"
    gui.layers.up_button.invoke()
    gui.layers.up_button.invoke()
    gui.root.update()
    assert ctrl._layers.ids() == [base_id, a, b, c]
    assert _state(gui.layers.up_button) == "disabled"
    assert ctrl.on_viewer_layer_move(c, "up") is False  # past the end: nothing happens
    assert ctrl._layers.ids() == [base_id, a, b, c]
    with pytest.raises(ValueError, match="direction: got 'left', expected one of"):
        ctrl.on_viewer_layer_move(c, "left")


def test_delete_removes_a_layer_and_asks_about_unsaved_edits(gui, monkeypatch):
    ctrl = gui.ctrl
    base_id = ctrl._layers.ids()[0]
    img = _add_image(gui)
    _select(gui, base_id)
    assert _state(gui.layers.delete_button) == "disabled"
    with pytest.raises(ValueError, match="expected a non-base layer"):
        ctrl.on_viewer_layer_delete(base_id)
    _select(gui, img)
    assert _state(gui.layers.delete_button) == "normal"
    gui.layers.delete_button.invoke()
    gui.root.update()
    assert img not in ctrl._layers.ids() and _listed(gui) == [base_id]
    assert gui.layers.selected_layer is None
    assert _state(gui.layers.delete_button) == "disabled"

    asked = []

    def ask(title, message, **kw):
        asked.append((title, message))
        return answer[0]

    answer = [False]
    monkeypatch.setattr(messagebox, "askyesno", ask)
    lid, data = _new_layer(gui)
    gui.paint.brush_var.set(1)
    gui.mode("paint")
    gui.stroke((5, 4), (5, 8))
    assert data.any() and lid in ctrl._layer_dirty
    gui.layers.delete_button.invoke()
    gui.root.update()
    assert len(asked) == 1 and lid in ctrl._layers.ids() and lid in _listed(gui)  # kept on No
    answer[0] = True
    gui.layers.delete_button.invoke()
    gui.root.update()
    assert len(asked) == 2 and lid not in ctrl._layers.ids() and _listed(gui) == [base_id]
    assert ctrl.viewer_paint_state()["enabled"] is False


def test_colormap_and_range_apply_to_an_image_layer(gui):
    ctrl, box = gui.ctrl, gui.layers
    img = _add_image(gui)
    lab = _add_label(gui)
    base_id = ctrl._layers.ids()[0]
    for lid in (base_id, lab):  # base, label: the controls are disabled
        _select(gui, lid)
        assert _state(box.cmap_combo) == "disabled" and _state(box.apply_button) == "disabled"
        assert _state(box.min_entry) == "disabled" and _state(box.max_entry) == "disabled"
    _select(gui, img)
    assert _state(box.cmap_combo) == "readonly" and _state(box.apply_button) == "normal"
    assert _state(box.min_entry) == "normal" and _state(box.max_entry) == "normal"
    assert tuple(box.cmap_combo.cget("values")) == ("gray", "hot", "red", "green", "blue")
    assert box.cmap_var.get() == "gray" and box.min_var.get() == box.max_var.get() == ""

    box.cmap_var.set("hot")
    box.min_var.set("10")
    box.max_var.set("50.5")
    box.apply_button.invoke()
    gui.root.update()
    layer = ctrl._layers.get(img)
    assert layer.cmap == "hot" and layer.window == (10.0, 50.5)
    assert box.error_var.get() == "" and box.min_var.get() == "10" and box.max_var.get() == "50.5"
    assert ctrl._layer_window(layer, 0, np.zeros((2, 2, 2))) == (10.0, 50.5)

    box.cmap_var.set("blue")  # Enter in an entry applies, too
    gui.root.focus_force()
    box.min_entry.focus_force()
    gui.root.update()
    box.min_entry.event_generate("<Return>")
    gui.root.update()
    assert ctrl._layers.get(img).cmap == "blue" and ctrl._layers.get(img).window == (10.0, 50.5)

    box.min_var.set("")  # empty Min and Max restore the automatic window
    box.max_var.set("")
    box.apply_button.invoke()
    gui.root.update()
    assert ctrl._layers.get(img).window is None and ctrl._layers.get(img).cmap == "blue"

    _select(gui, lab)  # the row shows its own values when it is selected again
    _select(gui, img)
    assert box.cmap_var.get() == "blue" and box.min_var.get() == box.max_var.get() == ""


def test_invalid_ranges_change_nothing_and_show_an_error(gui):
    ctrl, box = gui.ctrl, gui.layers
    img = _add_image(gui)
    _select(gui, img)
    box.cmap_var.set("hot")
    box.min_var.set("3")
    box.max_var.set("9")
    box.apply_button.invoke()
    gui.root.update()
    before = (ctrl._layers.get(img).cmap, ctrl._layers.get(img).window)
    assert before == ("hot", (3.0, 9.0))
    for lo, hi in (("9", "3"), ("5", "5"), ("a", "7"), ("1", ""), ("", "4"), ("nan", "2"), ("0", "inf")):
        box.cmap_var.set("red")
        box.min_var.set(lo)
        box.max_var.set(hi)
        box.apply_button.invoke()
        gui.root.update()
        assert (ctrl._layers.get(img).cmap, ctrl._layers.get(img).window) == before, (lo, hi)
        assert box.error_var.get() != "", (lo, hi)
    box.cmap_var.set("hot")
    box.min_var.set("1")
    box.max_var.set("2")
    box.apply_button.invoke()
    gui.root.update()
    assert box.error_var.get() == "" and ctrl._layers.get(img).window == (1.0, 2.0)
    with pytest.raises(ValueError, match="cmap: got 'jet', expected one of"):
        ctrl.on_viewer_layer_style(img, "jet", None)
    with pytest.raises(ValueError, match="window: got .* expected finite"):
        ctrl.on_viewer_layer_style(img, "gray", (2, 1))
    lab = _add_label(gui)
    with pytest.raises(ValueError, match="expected a non-base image layer"):
        ctrl.on_viewer_layer_style(lab, "gray", None)
    assert ctrl._layers.get(img).window == (1.0, 2.0)


def test_the_list_follows_the_layers_api(gui):
    ctrl = gui.ctrl
    api = ctrl.layers_api
    base_id = ctrl._layers.ids()[0]
    grid = ctrl._display_grid()
    data = np.ones(grid.shape, np.float32)
    lid = api.add_overlay(data, grid.affine, name="from api")
    gui.root.update()
    assert _listed(gui) == [lid, base_id]
    assert str(gui.layers.tree.set(lid, "name")) == "from api"
    api.set_overlay(lid, visible=False, name="renamed")
    gui.root.update()
    assert str(gui.layers.tree.set(lid, "vis")) == "☐" and str(gui.layers.tree.set(lid, "name")) == "renamed"
    _select(gui, lid)
    api.set_overlay(lid, cmap="green", window=(0.0, 4.0))
    gui.root.update()
    assert gui.layers.cmap_var.get() == "green" and gui.layers.min_var.get() == "0" and gui.layers.max_var.get() == "4"
    api.remove_overlay(lid)
    gui.root.update()
    assert _listed(gui) == [base_id] and gui.layers.selected_layer is None
