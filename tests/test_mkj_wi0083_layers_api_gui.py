"""WI-0083 (S4-4): the layers API (``app.layers_api``) in a real Tk window.

Requirement traceability (notes/requirements/viewer-stage4-s4-4-gui.md):
point 1 hook-callback add: test_hook_callback_adds_a_label_overlay
point 2 remove: test_remove_overlay_clears_every_view
point 3 ROI coexists: test_roi_timecourse_is_unchanged_by_an_overlay
point 4 other thread: test_add_overlay_from_a_worker_thread_via_call_on_main
point 5 copy rule: test_copy_false_overlay_refresh_rerenders_views

``app`` is the ``ViewerController`` of the ``gui`` fixture (WI-0020, real window on a phantom). The
tests run only under a display with BRKRAW_VIEWER_SMOKE=1 (use ``xvfb-run``).
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from test_mkj_wi0020_checklist_gui import N, _expected, gui  # noqa: F401  (gui: fixture)


def _mask_for_shown_image(app):
    """uint8 label mask on the shown image's grid, with a block of label 1, and its affine."""
    arr, affine = app.layers_api.get_image()
    mask = np.zeros(arr.shape[:3], dtype=np.uint8)
    mask[8:20, 6:18, 1:5] = 1
    return mask, affine


def _add_in_callback(gui):
    """Run ``add_overlay`` inside a ``root.after(0, ...)`` callback, as a hook button would."""
    app = gui.ctrl
    out = {}

    def cb():
        try:
            mask, affine = _mask_for_shown_image(app)
            out["id"] = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test
            out["error"] = exc

    gui.root.after(0, cb)
    assert gui.pump(lambda: bool(out), 5.0)
    if "error" in out:
        raise out["error"]
    return out


def _all_views_have_layers(gui):
    return all(len(v._last_layers) > 0 for v in gui.views.values())


def _all_views_empty(gui):
    return all(len(v._last_layers) == 0 for v in gui.views.values())


def test_hook_callback_adds_a_label_overlay(gui):
    app = gui.ctrl
    assert _all_views_empty(gui)  # no overlay yet
    lid = _add_in_callback(gui)["id"]
    assert gui.pump(lambda: _all_views_have_layers(gui), 5.0)
    layers = app.layers_api.list_layers()
    assert len(layers) == 2 and layers[0].id == "base" and layers[1].id == lid
    assert layers[1].name == "mask"


def test_remove_overlay_clears_every_view(gui):
    app = gui.ctrl
    lid = _add_in_callback(gui)["id"]
    assert gui.pump(lambda: _all_views_have_layers(gui), 5.0)
    app.layers_api.remove_overlay(lid)
    assert gui.pump(lambda: _all_views_empty(gui), 5.0)
    ids = [info.id for info in app.layers_api.list_layers()]
    assert lid not in ids and ids == ["base"]


def test_roi_timecourse_is_unchanged_by_an_overlay(gui):
    app = gui.ctrl
    geometry = (2, 5, 1, 3)
    exp, n = _expected(tuple(float(g) for g in geometry), "rect", 2, app.state.viewer.z_index)

    app.set_roi("rect", geometry, axis=2)
    without = app.roi_timecourse(wait=True, timeout=5.0)
    assert without["values"] == pytest.approx(exp) and without["n_mask"] == n
    without_values = list(without["values"])
    app.clear_roi()

    lid = _add_in_callback(gui)["id"]
    assert gui.pump(lambda: _all_views_have_layers(gui), 5.0)
    app.set_roi("rect", geometry, axis=2)
    with_overlay = app.roi_timecourse(wait=True, timeout=5.0)
    assert with_overlay["values"] == pytest.approx(without_values)
    assert with_overlay["n_mask"] == n
    assert len(with_overlay["values"]) == N
    assert lid in [info.id for info in app.layers_api.list_layers()]  # the overlay is still listed


def test_add_overlay_from_a_worker_thread_via_call_on_main(gui):
    app = gui.ctrl
    mask, affine = _mask_for_shown_image(app)  # built on the main thread
    out = {}

    def work():
        try:
            out["id"] = app.call_on_main(
                lambda: app.layers_api.add_overlay(mask, affine, name="from-thread", kind="label"),
                timeout=5.0,
            )
        except BaseException as exc:  # noqa: BLE001 - checked by the test thread
            out["error"] = exc
        try:
            app.layers_api.list_layers()  # direct call off the main thread
        except BaseException as exc:  # noqa: BLE001
            out["direct"] = exc

    th = threading.Thread(target=work)
    th.start()
    end = time.monotonic() + 5.0
    while th.is_alive() and time.monotonic() < end:
        gui.root.update()
        time.sleep(0.01)
    th.join(0.5)
    assert not th.is_alive()
    assert "error" not in out, out.get("error")
    assert out["id"] in [info.id for info in app.layers_api.list_layers()]
    assert isinstance(out["direct"], RuntimeError)
    assert "thread: got" in str(out["direct"])


def test_copy_false_overlay_refresh_rerenders_views(gui):
    app = gui.ctrl
    mask, affine = _mask_for_shown_image(app)
    mask[:] = 1  # a fully set array, so zeroing part of it is a visible change
    lid = app.layers_api.add_overlay(mask, affine, name="live", kind="label", copy=False)
    assert gui.pump(lambda: _all_views_have_layers(gui), 5.0)

    # Observable: the render count. ``set_view`` (viewport.py, line ~534) assigns ``_last_layers``
    # on every render the controller sends, so each view's call count rises after the refresh.
    counts = {name: 0 for name in gui.views}
    for name, view in gui.views.items():
        orig = view.set_view

        def counted(*a, _orig=orig, _name=name, **kw):
            counts[_name] += 1
            return _orig(*a, **kw)

        view.set_view = counted

    live = app.layers_api.get_overlay_array(lid, copy=False)
    live[:10] = 0  # the caller mutates its own array in place
    app.layers_api.set_overlay(lid)  # refresh on the main thread
    assert gui.pump(lambda: all(c > 0 for c in counts.values()), 5.0)
    again = app.layers_api.get_overlay_array(lid, copy=False)
    assert again[:10].sum() == 0 and again[10:].sum() > 0
    assert int(again.sum()) == int(mask.sum())  # same storage as the caller's array (copy=False)
