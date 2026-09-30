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
- Preview image volumes with orientation controls
- Convert datasets with configurable naming/layout
- Optional extensions via `brkraw.viewer.hook` entry points (no core edits required)

## Why these features exist

**Viewer**
The Viewer tab gives quick visual confirmation of orientation and scan content
so researchers can make decisions before running heavier pipelines.

**Registry**
The Registry exists to reduce repetitive filesystem navigation. It stores
datasets you care about and lets you reload the current session in one click.

**Extensions/hooks**
Extensions are delivered as viewer hooks discovered via the
`brkraw.viewer.hook` entry point. Hooks can add tabs without changing the
Viewer host, and they coexist with converter hooks and
CLI hooks so UI features can build on the same rule/spec system as brkraw.
For converter hooks, the Convert tab can render hook option forms when the
hook exposes presets. BrkRaw splits hook args by function signature, so any
remaining hook-only kwargs are the ones shown in the GUI. Example (minimal):

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

The main tabs are Viewer, Addon, Params, Convert, and Config. Viewer hooks
appear under the Extensions tab and are selected manually.
