"""WI-0032: blocking ``roi_timecourse(wait=True, timeout=...)`` in a real Tk window.

Requirement traceability (notes/requirements/roi-timecourse-wait.md):
R1 no-argument form unchanged: test_r1_plain_call_does_not_wait (the older ROI tests stay as they are).
R2 wait returns the non-blocking dict: test_r2_wait_returns_the_answer.
R3 safe on the Tk main thread, events keep flowing: test_r3_wait_inside_a_button_callback_keeps_tk_alive.
R4 TimeoutError / ValueError: test_r4_timeout_raises, test_r4_no_roi_raises_at_once.
R5 ROI changed or cleared while waiting: test_r5_replaced_roi_gives_the_new_answer,
   test_r5_cleared_roi_raises.

The window and phantom come from tests/test_mkj_wi0020_checklist_gui.py (``gui`` fixture, torn down
there with the root destroyed). The worker is replaced by a deferred one: requests are held and the
answers are delivered from ``check_results``, as the real worker's results arrive from its queue.
Runs only with a display and ``BRKRAW_VIEWER_SMOKE=1``.
"""

from __future__ import annotations

import time
import tkinter as tk
from types import SimpleNamespace

import pytest

from test_mkj_wi0020_checklist_gui import _expected, gui  # noqa: F401  (fixture: real window on a phantom)


@pytest.fixture
def slow(gui):
    """The window's worker, answering only after ``ticks`` calls of ``check_results``."""
    ctrl = gui.ctrl
    immediate = ctrl._worker.submit
    held = []
    state = SimpleNamespace(ticks=3, held=held, polls=0, frozen=False)

    def submit(req):
        held.append(req)

    def check_results():
        state.polls += 1
        if state.frozen or state.polls < state.ticks:
            return
        while held:
            immediate(held.pop(0))

    ctrl._worker = SimpleNamespace(submit=submit, log_queue=None, check_results=check_results)
    return state


def test_r1_plain_call_does_not_wait(gui, slow):
    gui.ctrl.set_roi("rect", (2, 5, 1, 3), axis=2)
    t0 = time.monotonic()
    assert gui.ctrl.roi_timecourse() is None  # pending, returns at once
    assert time.monotonic() - t0 < 0.5
    assert slow.polls == 0


def test_r2_wait_returns_the_answer(gui, slow):
    ctrl = gui.ctrl
    ctrl.set_roi("rect", (2, 5, 1, 3), axis=2)
    got = ctrl.roi_timecourse(wait=True, timeout=5.0)
    assert got == ctrl.roi_timecourse()
    values, n = _expected((2, 5, 1, 3), "rect", 2, got["index"])
    assert got["n_mask"] == n
    assert got["values"] == pytest.approx(values)
    assert slow.polls >= slow.ticks  # it did wait for the worker


def test_r3_wait_inside_a_button_callback_keeps_tk_alive(gui, slow):
    ctrl, root = gui.ctrl, gui.root
    ctrl.set_roi("ellipse", (14.0, 12.0, 4.0, 4.0), axis=2)
    seen = {"after": 0, "result": None}

    def tick():
        seen["after"] += 1  # a Tk timer firing while the callback is blocked in the wait
        if seen["after"] < 1000:
            root.after(5, tick)

    def on_click():
        seen["result"] = ctrl.roi_timecourse(wait=True, timeout=5.0)

    btn = tk.Button(root, command=on_click)
    btn.pack()
    root.after(5, tick)
    btn.invoke()  # runs on the Tk main thread, like a hook's button
    assert seen["result"] is not None and seen["result"]["shape"] == "ellipse"
    assert seen["after"] >= 1
    btn.destroy()


def test_r4_timeout_raises(gui, slow):
    slow.frozen = True
    gui.ctrl.set_roi("rect", (2, 5, 1, 3), axis=2)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError, match="ROI timecourse"):
        gui.ctrl.roi_timecourse(wait=True, timeout=0.3)
    assert 0.25 <= time.monotonic() - t0 < 3.0
    slow.frozen = False  # the window is still usable: a later wait succeeds
    assert gui.ctrl.roi_timecourse(wait=True, timeout=5.0)["shape"] == "rect"


def test_r4_no_roi_raises_at_once(gui, slow):
    t0 = time.monotonic()
    with pytest.raises(ValueError):
        gui.ctrl.roi_timecourse(wait=True, timeout=5.0)
    assert time.monotonic() - t0 < 0.5


def test_r5_replaced_roi_gives_the_new_answer(gui, slow):
    ctrl = gui.ctrl
    ctrl.set_roi("rect", (0, 1, 0, 1), axis=2)  # 4 voxels
    gui.root.after(30, lambda: ctrl.set_roi("rect", (0, 3, 0, 3), axis=2))  # 16 voxels
    got = ctrl.roi_timecourse(wait=True, timeout=5.0)
    assert got["n_mask"] == 16
    assert got["values"] == pytest.approx(_expected((0, 3, 0, 3), "rect", 2, got["index"])[0])


def test_r5_cleared_roi_raises(gui, slow):
    ctrl = gui.ctrl
    ctrl.set_roi("rect", (0, 1, 0, 1), axis=2)
    gui.root.after(30, ctrl.clear_roi)
    with pytest.raises(ValueError):
        ctrl.roi_timecourse(wait=True, timeout=5.0)
    assert ctrl.roi_timecourse() is None
