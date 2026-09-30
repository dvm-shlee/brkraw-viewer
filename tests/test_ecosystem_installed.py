"""Installed core, Viewer, and hook template contract smoke test.

Run with BRKRAW_ECOSYSTEM_CONTRACT=1 after installing all three checkouts.
No Paravision data or GUI display is required.
"""

import argparse
import os
from importlib import metadata

import pytest

from brkraw.core.entrypoints import list_entry_points
from brkraw.specs.hook import resolve_hook


@pytest.mark.skipif(
    os.environ.get("BRKRAW_ECOSYSTEM_CONTRACT") != "1",
    reason="run in the cross-repository contract CI job",
)
def test_installed_ecosystem_entry_points():
    assert metadata.distribution("brkraw")
    assert metadata.distribution("brkraw-viewer")
    assert metadata.distribution("brkraw-hook-template")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    viewer_entries = [ep for ep in list_entry_points("brkraw.cli") if ep.name == "viewer"]
    assert len(viewer_entries) == 1
    viewer_entries[0].load()(subparsers)
    assert "viewer" in subparsers.choices

    template_entries = list_entry_points("brkraw.converter_hook", "template")
    assert len(template_entries) == 1
    hook = resolve_hook("template")
    assert hook and all(callable(value) for value in hook.values())
