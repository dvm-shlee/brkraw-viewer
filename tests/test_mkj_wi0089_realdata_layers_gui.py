"""WI-0089: the layers API (``app.layers_api``) on the public PV5.1 BOLD-EPI dataset in a real Tk window.

One module-scoped real window (as WI-0042: ``MainWindow(root, ViewerController())``, in-process
worker) with scan 11 selected. The study folder comes from ``BRKRAW_VIEWER_REALDATA``. Every test
asserts values read from the data (never hard-coded shapes or counts) and prints one line
``REALDATA-LAYERS <test>: key=value ...`` (shown by ``pytest -rA``). No skips: a missing variable,
dataset or display is a failure. Run through scratch/checks/gui-test.sh (Xvfb, BRKRAW_VIEWER_SMOKE=1).
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import memory_limit, viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, TimecourseRequest
from brkraw_viewer.ui.main import MainWindow

from test_mkj_wi0042_realdata_gui import (  # noqa: F401
    GB,
    LOAD_LIMIT,
    Gui,
    _destroy_root,
    _dataset_path,
    _open_scan,
    _Queue,
    _repetitions,
)


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    study = _dataset_path()
    nrep = _repetitions(study)
    if not (sys.platform.startswith("win") or sys.platform == "darwin"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            pytest.fail("No display available for Tk (run through scratch/checks/gui-test.sh).")
    if os.environ.get("BRKRAW_VIEWER_SMOKE") != "1":
        pytest.fail("Set BRKRAW_VIEWER_SMOKE=1 to enable GUI tests.")
    home = tmp_path_factory.mktemp("home")
    mp = pytest.MonkeyPatch()
    cfg = viewer_config.default_viewer_config()
    mp.setattr(viewer_module, "load_viewer_config", lambda root=None: cfg)
    mp.setattr(memory_limit, "installed_memory", lambda: (64 * GB, False))
    mp.setattr(Path, "home", classmethod(lambda cls: home))
    mp.setattr(viewer_module.brkapi.hook, "resolve_hook", lambda name: {})
    stores = (convert_worker._meta_cache, convert_worker._held_recos, convert_worker._held_scans,
              convert_worker._held_hook_keys, convert_worker._held_hook_data, convert_worker._loader_cache)
    for store in stores:
        store.clear()
    from brkraw_viewer.ui import assets as _assets

    _assets._load_icon_cached.cache_clear()
    root = tk.Tk()
    try:
        root.geometry("1280x900+0+0")
        ctrl = ViewerController()

        def submit(req):  # the real worker functions answer at once, in this process
            out = _Queue()
            if isinstance(req, LoadVolumeRequest):
                convert_worker._process_load_volume(req, out)
                ctrl._on_volume_result(out.items[0])
            elif isinstance(req, TimecourseRequest):
                convert_worker._process_timecourse(req, out)
                ctrl._on_timecourse_result(out.items[0])

        ctrl._worker = SimpleNamespace(submit=submit, log_queue=None, check_results=lambda: None)
        win = MainWindow(root, ctrl)
        win.tabs.select_tab("Viewer")
        root.update()
        g = Gui(root, win, ctrl)
        g.study, g.nrep = study, nrep
        _open_scan(g)
        yield g
    finally:
        _destroy_root(root)
        mp.undo()
        for store in stores:
            store.clear()


def _report(test, **kv):
    print("REALDATA-LAYERS " + test + ": " + " ".join(f"{k}={v}" for k, v in kv.items()), flush=True)


def _diag(affine):
    return [round(float(x), 4) for x in np.diag(affine)[:3]]


def _threshold_mask(app):
    """uint8 mask on the 3D grid: (mean over frames if 4D, else arr) > its mean; and the affine."""
    arr, affine = app.layers_api.get_image()
    base = arr.mean(axis=3) if arr.ndim == 4 else arr
    mask = (base > base.mean()).astype(np.uint8)
    return mask, affine


def _ids(app):
    return [info.id for info in app.layers_api.list_layers()]


def test_get_image_returns_finite_array_and_affine(real):
    app = real.ctrl
    t0 = time.monotonic()
    arr, affine = app.layers_api.get_image()
    assert arr.ndim >= 3
    assert np.all(np.isfinite(arr))
    assert affine.shape == (4, 4) and np.all(np.isfinite(affine))
    view, _ = app.layers_api.get_image(copy=False)
    assert view.flags.writeable is False
    with pytest.raises(ValueError):
        view[(0,) * view.ndim] = 1
    _report("get_image", shape=tuple(arr.shape), affine_diag=_diag(affine),
            min=float(arr.min()), max=float(arr.max()), elapsed=round(time.monotonic() - t0, 3))


def test_threshold_overlay_is_listed_and_readable(real):
    app = real.ctrl
    t0 = time.monotonic()
    mask, affine = _threshold_mask(app)
    n_mask = int(mask.sum())
    assert mask.dtype == np.uint8 and 0 < n_mask < mask.size
    lid = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
    try:
        layers = app.layers_api.list_layers()
        assert layers[0].id == "base" and len(layers) == 2
        info = layers[1]
        assert info.id == lid and info.name == "mask"
        assert tuple(info.shape) == mask.shape
        assert np.allclose(info.affine, affine)
        assert np.array_equal(app.layers_api.get_overlay_array(lid), mask)
        app.layers_api.set_overlay(lid, alpha=0.5)
        shown = {i.id: i for i in app.layers_api.list_layers()}[lid]
        assert shown.alpha == pytest.approx(0.5)
        assert real.pump(lambda: all(v._last_layers for v in real.views.values()), 30.0)
        _report("threshold_overlay", shape=mask.shape, affine_diag=_diag(affine), n_mask=n_mask,
                alpha=shown.alpha, elapsed=round(time.monotonic() - t0, 3))
    finally:
        app.layers_api.remove_overlay(lid)


def test_roi_timecourse_with_overlay_present(real):
    g = real
    app = g.ctrl
    t0 = time.monotonic()
    mask, affine = _threshold_mask(app)
    lid = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
    try:
        nu, nv = (int(n) for n in np.shape(app._viewer_volume)[:2])
        geometry = (nu // 3, 2 * nu // 3, nv // 3, 2 * nv // 3)
        app.set_roi("rect", geometry, axis=2)
        tc = app.roi_timecourse(wait=True, timeout=LOAD_LIMIT)
        vals = np.asarray(tc["values"], dtype=float)
        assert len(vals) == g.nrep, f"{len(vals)} values for {g.nrep} repetitions"
        assert np.all(np.isfinite(vals)) and not np.all(vals == vals[0])
        assert tc["n_mask"] > 0
        assert lid in _ids(app)
        _report("roi_timecourse", n_mask=tc["n_mask"], repetitions=len(vals),
                tc_min=float(vals.min()), tc_max=float(vals.max()), elapsed=round(time.monotonic() - t0, 3))
    finally:
        app.clear_roi()
        app.layers_api.remove_overlay(lid)


def test_other_thread_uses_call_on_main(real):
    g = real
    app = g.ctrl
    t0 = time.monotonic()
    mask, affine = _threshold_mask(app)  # built on the main thread
    out = {}
    first = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")  # first overlay, main thread

    def work():
        try:
            out["id"] = app.call_on_main(
                lambda: app.layers_api.add_overlay(mask, affine, name="from-thread", kind="label"), timeout=30.0)
            out["ids"] = app.call_on_main(lambda: [i.id for i in app.layers_api.list_layers()], timeout=30.0)
        except BaseException as exc:  # noqa: BLE001 - checked by the test thread
            out["error"] = exc
        try:
            app.layers_api.list_layers()  # direct call off the main thread
        except BaseException as exc:  # noqa: BLE001
            out["direct"] = exc

    th = threading.Thread(target=work)
    th.start()
    end = time.monotonic() + LOAD_LIMIT
    while th.is_alive() and time.monotonic() < end:
        g.root.update()
        time.sleep(0.01)
    th.join(0.5)
    assert not th.is_alive()
    try:
        assert "error" not in out, out.get("error")
        assert out["id"] != first and out["ids"][0] == "base"
        assert first in out["ids"] and out["id"] in out["ids"]
        assert isinstance(out.get("direct"), RuntimeError)
        _report("other_thread", overlay_id=out["id"], n_layers=len(out["ids"]),
                direct_error=type(out["direct"]).__name__, elapsed=round(time.monotonic() - t0, 3))
    finally:
        for lid in (out.get("id"), first):
            if lid in _ids(app):
                app.layers_api.remove_overlay(lid)


def test_remove_overlays_leaves_only_the_base(real):
    app = real.ctrl
    t0 = time.monotonic()
    mask, affine = _threshold_mask(app)
    first = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
    second = app.layers_api.add_overlay(mask, affine, name="mask2", kind="label")
    assert _ids(app) == ["base", first, second]
    app.layers_api.remove_overlay(first)
    app.layers_api.remove_overlay(second)
    assert _ids(app) == ["base"]
    assert real.pump(lambda: all(not v._last_layers for v in real.views.values()), 30.0)
    with pytest.raises((ValueError, KeyError)):
        app.layers_api.remove_overlay(first)
    _report("remove", removed=2, remaining=len(_ids(app)), elapsed=round(time.monotonic() - t0, 3))
