"""WI-0087: the two examples of try-new-features.md section 9 (layers API) run in a real Tk window.

Each marked block is extracted from the page, executed to define the hook class, and its buttons
are invoked on the ``gui`` fixture of WI-0020 (real window on a phantom). GUI tests need a
display and BRKRAW_VIEWER_SMOKE=1 (use ``xvfb-run``).
"""
from __future__ import annotations

import re
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from test_mkj_wi0020_checklist_gui import gui  # noqa: F401  (gui: fixture)

PAGE = Path(__file__).resolve().parents[1] / "docs" / "user" / "try-new-features.md"
FENCE = "`" * 3


def _block(marker: str) -> str:
    blocks = re.findall(FENCE + r"python\n(.*?)" + FENCE, PAGE.read_text(), flags=re.S)
    found = [b for b in blocks if b.lstrip().startswith(marker)]
    assert len(found) == 1, f"expected one {marker!r} block, got {len(found)}"
    return found[0]


def _hook_class(marker: str):
    ns: dict = {"__name__": "try_layers_hook"}
    exec(compile(_block(marker), f"try-new-features.md:{marker}", "exec"), ns)
    return ns["TryLayersHook"]


def _buttons(frame) -> dict:
    return {w.cget("text"): w for w in frame.winfo_children() if isinstance(w, ttk.Button)}


def _layers(app):
    return app.layers_api.list_layers()


def _overlays(app):
    return [i for i in _layers(app) if i.id != "base"]


def _press(gui, button, until, timeout=5.0):
    button.invoke()
    assert gui.pump(until, timeout), f"timed out after pressing {button.cget('text')!r}"


def _views_have_layers(gui):
    return all(len(v._last_layers) > 0 for v in gui.views.values())


def _views_empty(gui):
    return all(len(v._last_layers) == 0 for v in gui.views.values())


def _run_sequence(gui, hook, labels, settle):
    app = gui.ctrl
    parent = tk.Frame(gui.root)
    frame = hook.build_tab(parent, app)
    frame.pack()
    btn = _buttons(frame)
    add, half, remove = (btn[t] for t in labels)
    arr, _ = app.layers_api.get_image()
    shape = tuple(arr.shape[:3])
    assert _overlays(app) == []

    _press(gui, add, lambda: len(_overlays(app)) == 1)
    infos = _layers(app)
    assert infos[0].id == "base" and [i.name for i in infos] == [infos[0].name, "mask"]
    assert tuple(infos[1].shape[:3]) == shape
    assert gui.pump(lambda: _views_have_layers(gui), 5.0)

    _press(gui, half, lambda: bool(_overlays(app)) and _overlays(app)[0].alpha == 0.5)
    assert _overlays(app)[0].alpha == 0.5

    _press(gui, remove, lambda: not _overlays(app))
    assert _overlays(app) == []
    assert gui.pump(lambda: _views_empty(gui), 5.0)
    settle()


def test_hook_example_buttons_add_halve_and_remove(gui):
    hook = _hook_class("# example: checklist_layers_hook")()
    _run_sequence(gui, hook, ("Add mask", "Half alpha", "Remove"), lambda: None)


def test_thread_example_buttons_add_halve_and_remove(gui):
    hook = _hook_class("# example: checklist_layers_thread")()

    def settle():
        end = time.monotonic() + 5.0
        while any(t.is_alive() for t in hook.threads) and time.monotonic() < end:
            gui.root.update()
            time.sleep(0.01)
        assert hook.threads and not any(t.is_alive() for t in hook.threads)
        assert hook.errors == []

    _run_sequence(gui, hook, ("Add mask (thread)", "Half alpha (thread)", "Remove (thread)"), settle)


def test_blocks_are_present_once_and_documented():
    text = PAGE.read_text()
    assert re.search(r"^## 9\. .*Layers API", text, flags=re.M)
    for marker in ("# example: checklist_layers_hook", "# example: checklist_layers_thread"):
        assert text.count(marker) == 1
        _block(marker)
