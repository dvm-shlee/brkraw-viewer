# Viewer Hook Development How-To

This page describes how to develop hooks and extensions for `brkraw-viewer`, in particular how to add
visualization controls such as overlays and colormaps to a viewport.

Given the current structure, the two most important points are:

1. The official interface has no API that controls the existing viewport of the `Viewer` tab directly.
2. For stable development, create and control your own viewport (`ViewportCanvas`) inside the `Extensions` tab.

Sections 1 to 5 describe the current code. Section 6 is a design proposal (draft) that is not implemented yet:
the current version has neither `app.viewer_api` nor the `on_viewer_ready` / `on_viewer_invalidated` calls.

## 1) What a hook can do today

A hook loaded through the `brkraw.viewer.hook` entry point adds its UI to the Extensions tab through
`build_tab(parent, app)`.

`app` is the `ViewerController` instance at runtime. The main callbacks and state to integrate with are:

- `app.on_viewer_jump(x, y, z)`: move the core Viewer position
- `app.on_viewer_space_change(value)`: change the space
- `app.register_viewer_space_listener(cb)`: subscribe to space changes
- `app.state.dataset.selected_scan_id`, `app.state.dataset.selected_reco_id`: the current selection
- `app.dataset.get_scan(scan_id)`: access a scan

Related files:

- `brkraw-viewer/src/brkraw_viewer/ui/tabs/extensions/window.py`
- `brkraw-viewer/src/brkraw_viewer/app/protocols.py`
- `brkraw-viewer/src/brkraw_viewer/app/controller/viewer.py`

## 2) Recommended pattern: own viewport in the Extensions tab

To handle overlays, colormaps and colorbars reliably, use `ViewportCanvas` directly inside the extension UI.

```python
import tkinter as tk
from tkinter import ttk
import numpy as np

from brkraw_viewer.ui.components.viewport import ViewportCanvas, OverlaySpec


def _make_lut_red_yellow() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    lut[:, 0] = 255
    lut[:, 1] = np.arange(256, dtype=np.uint8)
    return lut


class MyExtensionPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._vp = ViewportCanvas(self)
        self._vp.grid(row=0, column=0, sticky="nsew")

    def render_demo(self):
        base = np.random.randn(128, 128).astype(np.float32)
        overlay_map = np.random.rand(128, 128).astype(np.float32)
        mask = overlay_map > 0.6

        ov = OverlaySpec(
            data=overlay_map,
            lut=_make_lut_red_yellow(),
            alpha=0.65,
            vmin=0.0,
            vmax=1.0,
            mask=mask,
        )

        self._vp.set_view(
            base=base,
            overlay=ov,
            title="My Overlay",
            show_colorbar=True,
            colorbar_ticks=[(0.0, "0"), (0.5, "0.5"), (1.0, "1.0")],
            colorbar_label="Activation",
        )
```

Key points:

- `OverlaySpec` controls the LUT, alpha, mask and vmin/vmax
- `show_colorbar=True` shows a colorbar on the right
- `set_overlay_rgba(...)` adds an RGBA layer on top, independent of the parametric overlay

Related files:

- `brkraw-viewer/src/brkraw_viewer/ui/components/viewport.py`
- `brkraw-viewer/src/brkraw_viewer/ui/components/label_painter.py`

## 3) When you need to control the core Viewer tab viewport

### 3-1. Practical alternative (recommended)

Leave the core Viewer alone and apply a hook at the data level, then show the result in the Viewer.

- Change what `scan.get_dataobj(...)` returns through the options of the converter hook that fits the scan
  (`hook_args`, the `Hook Options` button of the Viewer tab's Hook box), so the volume values are transformed
  (the `Hook` of the Viewer tab applies a converter hook, not a viewer hook)
- If needed, return RGB data (3 channels on the last axis) and show it in the Viewer's RGB mode

Note:

- This is not a way to add a separate overlay layer; it transforms or replaces the image.

### 3-2. Internal API access (not recommended, fragile)

Walking the internal widget tree as below reaches the core Viewer viewport objects (`_xy`, `_xz`, `_zy`).
It depends on private fields, so it breaks easily when the structure changes.

```python
def get_core_viewport(app, plane: str):
    view = getattr(app, "_view", None)
    if view is None:
        return None

    tab = view.tabs.get_tab("Viewer")
    tab_inst = getattr(tab, "_tab_instance", None)
    right = getattr(tab_inst, "right", None)
    if right is None:
        return None

    plane = plane.lower().strip()
    if plane == "xy":
        return getattr(right, "_xy", None)
    if plane == "xz":
        return getattr(right, "_xz", None)
    if plane == "zy":
        return getattr(right, "_zy", None)
    return None
```

In practice:

- Use it only for research and internal experiments
- Do not use it in a distributed extension, or guard it (`getattr`, `None` checks)

## 4) Extension skeleton (minimal)

```python
from tkinter import ttk


class MyViewerHook:
    name = "my-extension"

    def build_tab(self, parent, app):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        panel = MyExtensionPanel(frame, app)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.render_demo()
        return frame
```

`pyproject.toml`:

```toml
[project.entry-points."brkraw.viewer.hook"]
my-extension = "my_pkg.viewer_hook:MyViewerHook"
```

## 5) Summary of the guidance

1. There is no official API yet that controls the core Viewer tab directly.
2. The default strategy for overlays and colormaps is to implement them in the `ViewportCanvas` of the Extensions tab.
3. To stay in sync with the core Viewer, connect through `app` callbacks (`on_viewer_jump`, the space listener, ...).
4. If you must touch internal fields, state in the code and the docs that it depends on a private API.

## 6) Proposal: an official API (draft)

This section proposes an official API that lets an extension or hook control the `Viewer` tab viewport safely.
**It is a proposal and is not implemented in the current version**
(`viewer_api`, `on_viewer_ready` and `on_viewer_invalidated` below do not exist in the code).

### 6-1. Goals

1. Extensions no longer depend on private fields (`_view`, `_xy`, `_xz`, `_zy`).
2. Overlays, colormaps and annotations can be controlled per plane (`xy`, `xz`, `zy`).
3. The lifecycle is explicit, so it works across detached tabs, refresh and reload.
4. It is introduced in a backward compatible way, so existing extensions keep working.

### 6-2. Non-goals

1. The first version does not let a plugin replace the whole viewport implementation.
2. The first version does not let outside code change the render pipeline (zoom, fit, aspect) itself.

### 6-3. Proposed API surface

`ViewerController` exposes a "Viewer overlay service".

- `app.viewer_api` (new): the official entry point for extensions
- `app.viewer_api` starts with the minimum below

```python
class ViewerOverlayAPI(Protocol):
    def set_param_overlay(
        self,
        plane: str,                  # "xy" | "xz" | "zy"
        data: np.ndarray,            # (H, W)
        *,
        lut: np.ndarray,             # (256, 3) uint8
        alpha: float = 0.6,
        alpha_map: np.ndarray | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        mask: np.ndarray | None = None,
        show_colorbar: bool = False,
        colorbar_ticks: list[tuple[float, str]] | None = None,
        colorbar_label: str = "",
        owner: str = "default",      # extension namespace
    ) -> None: ...

    def set_rgba_overlay(
        self,
        plane: str,
        rgba: np.ndarray | None,     # (H, W, 4) uint8; None removes it
        *,
        owner: str = "default",
    ) -> None: ...

    def clear_overlay(
        self,
        plane: str | None = None,    # None means every plane
        *,
        owner: str | None = None,    # None means every owner
    ) -> None: ...

    def get_view_shape(self, plane: str) -> tuple[int, int] | None: ...
    def request_redraw(self) -> None: ...
```

Key design points:

- The `owner` concept keeps the overlays of different extensions from colliding
- The controller keeps state per owner; the final compositing happens in the UI layer
- The same owner calling again replaces its overlay; different owners are merged by a stacking policy

### 6-4. State model

The controller gets the following internal state.

- `_viewer_plane_overlays: dict[str, dict[str, OverlayState]]`
  - first key: plane (`xy`, `xz`, `zy`)
  - second key: owner (`mrs`, `seg`, ...)
  - value: `param_overlay`, `rgba_overlay`, `zindex`, `updated_at`

Initial merge policy:

1. One `param_overlay` per owner (the last call wins)
2. One `rgba_overlay` per owner (the last call wins)
3. Between owners, composite in registration order (or by `zindex`), later on top

### 6-5. Lifecycle hooks (recommended addition)

Proposed extension of the `brkraw.viewer.hook` protocol:

```python
class ViewerHook(Protocol):
    ...
    def on_viewer_ready(self, app: Any) -> None: ...
    def on_viewer_invalidated(self, app: Any, reason: str) -> None: ...
```

Intent:

- `on_viewer_ready`: tells the extension when to register its overlays again after the Viewer tab is attached, detached or rebuilt
- `on_viewer_invalidated`: lets the extension clean up its state when the dataset closes, the scan or reco changes, or the tab is rebuilt

### 6-6. Error and validation policy

1. A shape mismatch can be a warning plus a no-op instead of a `ValueError`, selectable by mode
2. The plane string and array dtype are validated strictly at the API entry point
3. A failure does not block the rendering of the whole app; only that owner's overlay is dropped

Recommended defaults:

- Development mode: strict (`raise`)
- Distribution mode: tolerant (`warn + skip`)

### 6-7. Phased introduction

1. Phase 1 (minimal API)
   - `viewer_api.set_param_overlay`, `set_rgba_overlay`, `clear_overlay`
   - Internal owner/plane state storage and compositing
   - Documentation and a sample extension

2. Phase 2 (lifecycle)
   - Introduce `on_viewer_ready` and `on_viewer_invalidated`
   - Provide an example of registering again after detach, attach and refresh

3. Phase 3 (advanced)
   - Extend `zindex` and blending modes
   - Provide performance options (throttle, partial update)

### 6-8. Compatibility strategy

1. Existing extensions are not affected (`viewer_api` is an optional capability)
2. For older versions without the official API:
   - the extension checks `hasattr(app, "viewer_api")` and falls back
3. The private access route only gets a deprecation warning and is not removed at once

### 6-9. Acceptance criteria

1. An extension can show a core Viewer overlay without touching private fields
2. Overlays recover automatically after a tab is detached and attached
3. No stale overlay remains after the dataset changes
4. Two different extensions can register overlays at the same time and both show without conflict
5. A failure of the overlay API does not stop the core Viewer from rendering or responding
