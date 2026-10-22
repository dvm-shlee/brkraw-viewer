"""WI-0077 (S4-3): ``ViewerController.call_on_main`` and its main-call queue.

Requirement traceability (notes/requirements/viewer-stage4-s4-3-call-on-main.md):
point 2b main thread direct: test_main_thread_returns_directly
point 2d worker thread runs on main: test_worker_call_runs_on_main_thread, test_exception_is_the_same_object
point 2d timeout and cancelled record: test_timeout_cancels_the_call
point 4 shutdown release: test_close_releases_waiter_and_refuses_later_calls
point 2a bad arguments: test_bad_arguments
point 2c no window: test_no_window_from_worker_thread

GUI tests use the ``gui`` fixture of WI-0020 (real Tk window); they run only under a display with
BRKRAW_VIEWER_SMOKE=1. The headless test needs no Tk.
"""

from __future__ import annotations

import threading
import time

import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config

from test_mkj_wi0020_checklist_gui import gui  # noqa: F401  (fixture: real window on a phantom)


class _Worker:
    """Run ``fn`` in a thread; collect its result or exception."""

    def __init__(self, fn):
        self.result = None
        self.error = None
        self.elapsed = None
        self.thread = threading.Thread(target=self._run, args=(fn,))
        self.thread.start()

    def _run(self, fn):
        t0 = time.monotonic()
        try:
            self.result = fn()
        except BaseException as exc:  # noqa: BLE001 - handed to the test thread
            self.error = exc
        self.elapsed = time.monotonic() - t0

    def done(self):
        return not self.thread.is_alive()


def _pump(root, worker, limit=5.0):
    end = time.monotonic() + limit
    while not worker.done() and time.monotonic() < end:
        root.update()
        time.sleep(0.01)
    worker.thread.join(0.5)
    return worker.done()


def test_worker_call_runs_on_main_thread(gui):
    w = _Worker(lambda: gui.ctrl.call_on_main(lambda: threading.current_thread() is threading.main_thread()))
    assert _pump(gui.root, w)
    assert w.error is None
    assert w.result is True


def test_exception_is_the_same_object(gui):
    boom = KeyError("boom")

    def fn():
        raise boom

    w = _Worker(lambda: gui.ctrl.call_on_main(fn))
    assert _pump(gui.root, w)
    assert w.error is boom


def test_timeout_cancels_the_call(gui):
    ran = []
    w = _Worker(lambda: gui.ctrl.call_on_main(lambda: ran.append(1), timeout=0.3))
    w.thread.join(3.0)  # the test thread does not pump: nothing drains the queue
    assert w.done()
    assert isinstance(w.error, TimeoutError)
    assert "timeout: got" in str(w.error) and "expected" in str(w.error)
    for _ in range(30):  # now pump: the cancelled record must not run
        gui.root.update()
        time.sleep(0.01)
    gui.ctrl._drain_main_calls()
    assert ran == []


def test_main_thread_returns_directly(gui):
    ctrl = gui.ctrl
    assert threading.current_thread() is threading.main_thread()
    assert ctrl.call_on_main(lambda: 42) == 42
    assert ctrl._main_calls.empty()
    with pytest.raises(ZeroDivisionError):
        ctrl.call_on_main(lambda: 1 / 0)


def test_close_releases_waiter_and_refuses_later_calls(gui, monkeypatch):
    ctrl = gui.ctrl
    monkeypatch.setattr(ctrl, "_check_disk_cache_on_exit", lambda: None)
    w = _Worker(lambda: ctrl.call_on_main(lambda: 1, timeout=30))
    end = time.monotonic() + 3.0
    while ctrl._main_calls.empty() and not w.done() and time.monotonic() < end:
        time.sleep(0.01)  # no pumping: the record stays queued
    assert not w.done()
    ctrl.on_close()
    w.thread.join(2.0)
    assert w.done()
    assert isinstance(w.error, RuntimeError)
    assert "app: got" in str(w.error) and "expected" in str(w.error)
    assert w.elapsed < 2.5
    late = _Worker(lambda: ctrl.call_on_main(lambda: 1))
    late.thread.join(2.0)
    assert isinstance(late.error, RuntimeError)
    assert "closed viewer" in str(late.error)


@pytest.mark.parametrize("bad", [0, -1, True, "5"])
def test_bad_arguments(bad):
    ctrl = ViewerController()
    with pytest.raises(ValueError) as ei:
        ctrl.call_on_main(lambda: 1, timeout=bad)
    assert "timeout: got" in str(ei.value) and "expected" in str(ei.value)


def test_bad_callable():
    ctrl = ViewerController()
    with pytest.raises(ValueError) as ei:
        ctrl.call_on_main(3)
    assert "fn: got" in str(ei.value) and "expected" in str(ei.value)


def test_no_window_from_worker_thread(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    ctrl = ViewerController()
    assert ctrl._view is None
    w = _Worker(lambda: ctrl.call_on_main(lambda: 1))
    w.thread.join(2.0)
    assert isinstance(w.error, RuntimeError)
    assert "no window" in str(w.error) and "expected" in str(w.error)


# --- race tests (WI-0079): run-or-cancel and admission decided under _main_lock (headless, no Tk) ---
import numpy as np  # noqa: E402

from test_core_layers_in_viewer import _View, ctrl, load  # noqa: F401,E402  (fake view, fixture, load helper)


class _GatedQueue:
    """Queue whose ``put`` blocks on ``gate`` just before the real put."""

    def __init__(self, real, entered, gate):
        self._real = real
        self._entered = entered
        self._gate = gate

    def put(self, item):
        self._entered.set()
        self._gate.wait(5.0)
        self._real.put(item)

    def get_nowait(self):
        return self._real.get_nowait()

    def empty(self):
        return self._real.empty()


def test_admission_race_close_during_put_gives_runtime_error(ctrl, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ctrl, "_check_disk_cache_on_exit", lambda: None)
    entered, gate = threading.Event(), threading.Event()
    ctrl._main_calls = _GatedQueue(ctrl._main_calls, entered, gate)
    w = _Worker(lambda: ctrl.call_on_main(lambda: 1, timeout=5))
    assert entered.wait(2.0)
    closer = threading.Thread(target=ctrl.on_close)
    closer.start()
    time.sleep(0.2)  # on_close waits for the lock held across the put
    gate.set()
    w.thread.join(1.0)
    assert w.done()  # the 1 s guarantee, checked right after the one-second join
    closer.join(2.0)
    assert not closer.is_alive()
    assert isinstance(ctrl._view, _View)
    assert isinstance(w.error, RuntimeError)
    assert "app: got" in str(w.error) and "expected" in str(w.error)
    assert w.elapsed < 1.0


def test_started_then_timeout_waits_for_the_result(ctrl):  # noqa: F811
    started_evt, release_evt = threading.Event(), threading.Event()

    def fn():
        started_evt.set()
        release_evt.wait(5.0)
        load(ctrl, np.arange(24, dtype=float).reshape(2, 3, 4))
        return "done"

    w = _Worker(lambda: ctrl.call_on_main(fn, timeout=0.3))
    end = time.monotonic() + 2.0
    while ctrl._main_calls.empty() and time.monotonic() < end:
        time.sleep(0.01)
    drainer = threading.Thread(target=ctrl._drain_main_calls)
    drainer.start()
    assert started_evt.wait(2.0)
    time.sleep(0.5)  # past the caller's timeout while fn runs
    release_evt.set()
    w.thread.join(3.0)
    drainer.join(3.0)
    assert w.done() and not drainer.is_alive()
    assert w.error is None
    assert w.result == "done"
    assert ctrl._view.calls


def test_not_started_then_timeout_is_cancelled_and_never_run(ctrl):  # noqa: F811
    ran = []
    w = _Worker(lambda: ctrl.call_on_main(lambda: ran.append(1), timeout=0.2))
    w.thread.join(3.0)
    assert w.done()
    assert isinstance(w.error, TimeoutError)
    ctrl._drain_main_calls()
    assert ran == []
