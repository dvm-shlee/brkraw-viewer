"""WI-0076: a failing hook must not block the others; the cache folder follows viewer.cache.path."""

import logging
from pathlib import Path

import pytest

from brkraw_viewer.app.controller.viewer import ViewerController
from brkraw_viewer.app.services import hooks
from brkraw_viewer.app.services import viewer_config
from brkraw_viewer.app.state import AppState


class _Entry:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def load(self):
        return self.value


def test_hook_class_that_fails_on_creation_is_skipped_with_reason(monkeypatch, caplog):
    class Good:
        name = "good"

        def build_tab(self, parent, app):
            return None

    class BrokenInit:
        def __init__(self):
            raise RuntimeError("init exploded")

    monkeypatch.setattr(
        hooks,
        "list_entry_points",
        lambda group: [_Entry("broken", BrokenInit), _Entry("good", Good)],
    )
    with caplog.at_level(logging.WARNING, logger="brkraw.viewer"):
        loaded = hooks.load_viewer_hooks()
    assert [type(h) for h in loaded] == [Good]
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "broken" in messages and "init exploded" in messages


def _use_config(monkeypatch, tmp_path, cache_line):
    root = tmp_path / "cfg"
    root.mkdir()
    text = "viewer:\n  cache:\n    %s\n" % cache_line if cache_line else "viewer: {}\n"
    (root / "config.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("BRKRAW_CONFIG_HOME", str(root))
    return root


def _controller(tmp_path):
    controller = ViewerController.__new__(ViewerController)
    controller.state = AppState()
    controller.state.dataset.path = tmp_path / "synthetic"
    controller.state.dataset.selected_scan_id = 1
    controller.state.dataset.selected_reco_id = 1
    return controller


# WI-0072 (C9): the Timecourse no longer writes a file, so these two tests now check only
# the folder the exit prompt uses (they also checked the Timecourse file path before).
@pytest.mark.parametrize("relative", [True, False])
def test_cache_folder_follows_viewer_cache_path(monkeypatch, tmp_path, relative):
    target = tmp_path / "elsewhere"
    value = "mycache" if relative else str(target)
    root = _use_config(monkeypatch, tmp_path, "path: %s" % value)
    expected = (root / "mycache") if relative else target
    got = viewer_config.resolve_cache_dir()
    assert got == expected
    assert not str(got).startswith(str(Path.home() / ".brkraw"))
    assert not hasattr(_controller(tmp_path), "_resolve_timecourse_cache_path")


def test_cache_folder_defaults_to_config_folder_cache(monkeypatch, tmp_path):
    root = _use_config(monkeypatch, tmp_path, "")
    assert viewer_config.resolve_cache_dir() == root / "cache"
