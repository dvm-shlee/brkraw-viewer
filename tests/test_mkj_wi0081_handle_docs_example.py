"""hooks.md layers section: the example runs and the documented names exist (WI-0081); headless."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from brkraw_viewer.app.controller import viewer as viewer_module
from brkraw_viewer.app.controller.layers_api import LayersAPI
from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import viewer_config

from test_core_layers_in_viewer import _View, load, raw_volume

HOOKS = Path(__file__).resolve().parents[1] / "docs" / "dev" / "hooks.md"
FENCE = "`" * 3


@pytest.fixture
def ctrl(monkeypatch, tmp_path):
    monkeypatch.setattr(viewer_module, "load_viewer_config", lambda root=None: viewer_config.default_viewer_config())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    c = ViewerController()
    c._view = _View()
    return c


def _example() -> str:
    blocks = re.findall(FENCE + r"python\n(.*?)" + FENCE, HOOKS.read_text(), flags=re.S)
    found = [b for b in blocks if b.lstrip().startswith("# example: layers_api")]
    assert len(found) == 1, f"expected one layers_api example, got {len(found)}"
    lines = found[0].splitlines()
    indent = len(lines[0]) - len(lines[0].lstrip())
    return "\n".join(line[indent:] for line in lines)


def test_example_runs_and_leaves_no_overlay(ctrl):
    load(ctrl, raw_volume())
    ns = {"app": ctrl, "np": np}
    exec(compile(_example(), "hooks.md:layers_api", "exec"), ns)
    assert isinstance(ns["layer_id"], str)
    assert len(ns["names"]) == 2 and ns["names"][-1] == "mask"
    np.testing.assert_array_equal(ns["back"], ns["mask"])
    assert [i.id for i in ctrl.layers_api.list_layers()] == ["base"]


def test_documented_members_exist(ctrl):
    text = HOOKS.read_text()
    start = text.index("- Layers (**provisional**")
    end = text.index("Hooks are loaded when", start)
    section = text[start:end]
    api = set(re.findall(r"app\.layers_api\.(\w+)", section))
    top = set(re.findall(r"app\.(?!layers_api)(\w+)", section))
    assert {"list_layers", "get_image", "add_overlay", "set_overlay", "get_overlay_array", "remove_overlay"} <= api
    assert "call_on_main" in top
    for name in api:
        assert hasattr(LayersAPI, name) and getattr(ctrl.layers_api, name)
    for name in top:
        assert getattr(ctrl, name) is not None
