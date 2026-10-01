# Brkraw Viewer

BrkRaw Viewer is the visualization application plugin for Bruker datasets.
Its default GUI stays lightweight; optional extensions provide specialized
visualization while sharing the Viewer host and BrkRaw data APIs.

The core BrkRaw package owns data loading and conversion. The Viewer owns
common image display and interactive visualization, including the host for
modality-specific panels.

## Highlights

- Load Bruker study folders, archives, or PvDatasets packages
- Inspect scan metadata and parameter tables
- Preview image volumes in three orthogonal views with orientation controls
- Ask before loading a scan whose data is larger than a configurable size
- Convert datasets to NIfTI with configurable naming/layout
- Optional extensions via `brkraw.viewer.hook` entry points (no core edits required)

The viewer requires `brkraw` 0.6.0rc2 or newer. It shows one image volume at a
time; layer composition, ROI statistics and label editing are planned and not
available yet. See the [Viewer](user/viewer.md) page for the controls and known
limitations.

## Why these features exist

**Viewer**
The Viewer tab gives quick visual confirmation of orientation and scan content
so researchers can make decisions before running heavier pipelines.

**Registry**
The Registry exists to reduce repetitive filesystem navigation. It stores
datasets you care about (in a JSONL file) and opens them from one window; the
`+` menu can add the dataset that is currently open.

**Extensions/hooks**
Extensions are delivered as viewer hooks discovered via the
`brkraw.viewer.hook` entry point. Hooks add a panel to the Extensions tab without
changing the Viewer host, and they coexist with converter hooks and
CLI hooks so UI features can build on the same rule/spec system as brkraw.
For converter hooks, the Convert tab and the Viewer tab's Hook box can render
hook option forms when the hook exposes presets. BrkRaw splits hook args by
function signature, so any remaining hook-only kwargs are the ones shown in the
GUI. Example (minimal):

```python
from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class Options:
    reference: str = "water"
    peak_ppm: float = 3.02

def _build_options(kwargs: Dict[str, Any]) -> Options:
    return Options(
        reference=str(kwargs.get("reference", "water")),
        peak_ppm=float(kwargs.get("peak_ppm", 3.02)),
    )
```

## Getting started

Install the package and run:

```bash
brkraw viewer
```

The tabs are Viewer, Addons, Params, Convert, Extensions, and Config. Viewer
hooks appear under the Extensions tab and are selected manually. You can also
pass a path and an initial scan: `brkraw viewer /path/to/study --scan 3 --reco 1`.
