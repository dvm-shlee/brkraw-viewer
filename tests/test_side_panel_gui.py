"""GUI test of the foldable side panel of the Viewer tab (real ``MainWindow``, Xvfb, BRKRAW_VIEWER_SMOKE=1).

- ``CollapsibleSection`` toggles its body;
- default fold state: Orientation, ROI tool and Layers open, Hook, Value and Control folded;
- folding the panel and restoring it keeps widget identity and variable values;
- the ROI tool box and the Layers box still work after a fold / unfold cycle;
- the panel scrolls when the boxes are taller than the window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from brkraw_viewer.ui.components.collapsible import CollapsibleSection
from test_layers_box_gui import _add_image, _listed  # noqa: F401
from test_paint_tool_gui import gui  # noqa: F401  (fixture: window on a 4D phantom)


def _panel(gui):
    gui.root.update()
    return gui.win.tabs.get_tab("Viewer")._tab_instance.top


def test_section_toggles_its_body():
    import os

    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.skip("GUI tests need BRKRAW_VIEWER_SMOKE=1 (run under Xvfb)")
    root = tk.Tk()
    try:
        calls = []
        sec = CollapsibleSection(root, "Demo", expanded=False, on_toggle=calls.append)
        sec.pack()
        ttk.Label(sec.body, text="inside").pack()
        root.update()
        assert sec.title == "Demo" and not sec.expanded and not sec.body.winfo_ismapped()
        assert "Demo" in str(sec.header.cget("text"))
        sec.toggle()
        root.update()
        assert sec.expanded and sec.body.winfo_ismapped()
        sec.header.event_generate("<Button-1>")
        root.update()
        assert not sec.expanded and not sec.body.winfo_ismapped()
        sec.set_expanded(False)  # no change, no callback
        sec.set_expanded(True)
        assert calls == [True, False, True]
    finally:
        root.destroy()


def test_default_fold_state(gui):
    panel = _panel(gui)
    open_now = {name: sec.expanded for name, sec in panel.sections.items()}
    assert open_now == {
        "Orientation": True, "ROI tool": True, "Hook": False, "Value": False, "Control": False, "Layers": True}
    for name, sec in panel.sections.items():
        assert sec.body.winfo_ismapped() == open_now[name], name
    assert panel.panel_open


def test_each_section_toggles(gui):
    panel = _panel(gui)
    for name, sec in panel.sections.items():
        before = sec.expanded
        sec.toggle()
        gui.root.update()
        assert sec.body.winfo_ismapped() == (not before), name
        sec.toggle()
        gui.root.update()
        assert sec.body.winfo_ismapped() == before, name


def test_panel_collapse_restore_keeps_widgets_and_values(gui):
    panel = _panel(gui)
    views = [gui.views[k] for k in ("xz", "xy", "zy")]
    wide = gui.views["xy"].winfo_width()
    tool_box, layers_box = panel.tool_box, panel.layers_box
    zoom_scale, crosshair = panel._zoom_scale, panel._crosshair_var
    panel._zoom_entry_var.set("2.50")
    crosshair.set(False)
    panel.sections["Control"].set_expanded(True)
    panel.set_panel_open(False)
    gui.root.update()
    assert not panel.panel_open and not panel._wrap.winfo_ismapped()
    assert panel.winfo_width() < 60
    assert gui.pump(lambda: gui.views["xy"].winfo_width() > wide)  # the views take the freed width
    panel.set_panel_open(True)
    gui.root.update()
    assert panel.panel_open and panel._wrap.winfo_ismapped()
    assert panel.tool_box is tool_box and panel.layers_box is layers_box and panel._zoom_scale is zoom_scale
    assert [gui.views[k] for k in ("xz", "xy", "zy")] == views
    assert panel._zoom_entry_var.get() == "2.50" and crosshair.get() is False
    assert panel.sections["Control"].expanded


def test_roi_tool_and_layers_work_after_fold_cycle(gui):
    panel = _panel(gui)
    for name in ("ROI tool", "Layers"):
        panel.sections[name].toggle()
    panel.set_panel_open(False)
    panel.set_panel_open(True)
    for name in ("ROI tool", "Layers"):
        panel.sections[name].toggle()
    gui.root.update()
    gui.box.set_mode("selection")
    gui.root.update()
    assert gui.box.mode == "selection"
    gui.box._mode_radios["crosshair"].invoke()
    assert gui.box.mode == "crosshair"
    before = _listed(gui)
    lid = _add_image(gui)
    assert _listed(gui)[0] == lid and len(_listed(gui)) == len(before) + 1


def test_panel_scrolls_when_boxes_overflow(gui):
    panel = _panel(gui)
    for sec in panel.sections.values():
        sec.set_expanded(True)
    gui.win.winfo_toplevel().geometry("1100x520")
    gui.pump(lambda: panel._canvas.winfo_height() < panel._inner.winfo_reqheight())
    assert panel._inner.winfo_reqheight() > panel._canvas.winfo_height()
    assert panel._canvas.yview()[1] < 1.0
    assert panel._scroll.winfo_ismapped()
    panel._canvas.yview_scroll(3, "units")
    gui.root.update()
    assert panel._canvas.yview()[0] > 0.0


def test_fold_runs_the_viewport_refit(gui):
    panel = _panel(gui)
    right = gui.win.tabs.get_tab("Viewer")._tab_instance.right
    calls = []
    right._callbacks = type("CB", (), {"on_viewer_resize": staticmethod(lambda: calls.append(1))})()

    def _settle():
        gui.root.update()
        gui.root.after(150, gui.root.quit)
        gui.root.mainloop()
        gui.root.update()

    panel.sections["Hook"].toggle()
    _settle()
    assert len(calls) >= 1
    panel.toggle_panel()
    _settle()
    assert len(calls) >= 2
    panel.toggle_panel()
    _settle()
    assert len(calls) >= 3
