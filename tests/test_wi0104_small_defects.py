"""WI-0104: six small viewer defects from the waiting list.

1. Task progress window: asking for it again must not orphan the open one.
2. Hook Options: say why nothing opens instead of returning silently.
3. Large-data "No": a declined load must not block a later, different request (hook on, other options).
4. Worker: "already loaded" must also depend on the hook and its options.
5. Addons: the general text editor and a rule-section editor of the same file are not open together.
6. An open Hook Options window follows an Apply made in the other tab.

Synthetic data only. No Tk display: fake ``tk``/``ttk``/``messagebox`` modules.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.workers import convert_worker
from brkraw_viewer.app.workers.protocol import LoadVolumeRequest, LoadVolumeResult
from brkraw_viewer.app.workers.shm import release_shared_array
from brkraw_viewer.ui.main import window as main_window
from brkraw_viewer.ui.tabs.addons import window as addons_window
from brkraw_viewer.ui.tabs.addons.window import AddonsTab
from brkraw_viewer.ui.tabs.convert.window import ConvertTab
from brkraw_viewer.ui.tabs.viewer.top_panel import ViewerTopPanel
from brkraw_viewer.ui.windows import hook_options

MB = 1024 * 1024


# ---- fake Tk ---------------------------------------------------------------------------------


class _Var:
    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, value):
        self._v = value


class _FakeTk:
    END = "end"

    def __init__(self):
        self.windows = []
        self.StringVar = _Var
        self.Misc = object
        self.Widget = object

    def Toplevel(self, parent=None):
        win = MagicMock(name="Toplevel")
        win.alive = True
        win.winfo_exists.side_effect = lambda: win.alive
        win.destroy.side_effect = lambda: setattr(win, "alive", False)
        self.windows.append(win)
        return win

    def Text(self, *args, **kwargs):
        text = MagicMock(name="Text")
        text.get.return_value = "key: value\n"
        return text


# ---- 1. task progress window -----------------------------------------------------------------


def _main_window(monkeypatch):
    created = []

    def _make(parent, log_queue, title="Task Progress"):
        win = MagicMock(name="TaskProgressWindow")
        win.alive = True
        win.winfo_exists.side_effect = lambda: win.alive
        win.destroy.side_effect = lambda: setattr(win, "alive", False)
        created.append(win)
        return win

    monkeypatch.setattr(main_window, "TaskProgressWindow", _make)
    mw = main_window.MainWindow.__new__(main_window.MainWindow)
    mw._task_window = None
    mw.winfo_toplevel = lambda: "top"
    return mw, created


def test_progress_window_asked_twice_keeps_one_window_and_the_handle(monkeypatch):
    mw, created = _main_window(monkeypatch)
    first = mw.open_worker_popup("queue", "Task")
    second = mw.open_worker_popup("queue", "Task")
    assert len(created) == 1
    assert second is first  # the controller finishes the window it was given; no orphan
    assert mw._task_window is first
    assert first.lift.called


def test_progress_window_is_created_again_after_it_was_closed(monkeypatch):
    mw, created = _main_window(monkeypatch)
    first = mw.open_worker_popup("queue", "Task")
    first.destroy()
    second = mw.open_worker_popup("queue", "Task")
    assert len(created) == 2
    assert second is created[1] and mw._task_window is second
