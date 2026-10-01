# GUI Best Practices

When embedding GUI components into BrkRaw Viewer, prefer stability over
aggressive rendering.

## Recommendations

- Defer heavy rendering with `after_idle` to avoid 1x1 canvas issues.
- Clear state on failures to prevent stale data from reappearing.
- Avoid direct access to internal widgets unless the API provides a method.
- Check scan compatibility yourself when the panel is built (the host does not
  call a `can_handle` method) and display a clear message when unsupported.
- Keep callbacks defensive; the viewer may be detached and reattached.

## Overlays in your own viewport

The Viewer tab has no overlay interface. If your panel draws overlays in its own
viewport (for example a `ViewportCanvas`, see `howto.md`):

- Keep the coordinates of the image you display and map clicks back through that
  image, not through the Viewer tab.
- Clamp indices to the image bounds.
- Clear overlays when switching scans or failing to load data.

## Code layout

- `brkraw_viewer/app/controller/` contains the application controller
  (`viewer.py`) and the dataset controller (`dataset.py`).
- `brkraw_viewer/app/services/` and `app/workers/` contain integration services
  (config, registry, hook discovery, worker manager) and the background worker
  with its request/result types and shared-memory helpers.
- `brkraw_viewer/ui/main/` and `ui/tabs/` contain the Tk window and tab UI;
  `ui/windows/` has the registry, study info, hook options and worker log windows.
- `brkraw_viewer/ui/components/` has the reusable viewport and plot widgets. It also
  contains `label_painter.py`, a standalone helper that no tab uses yet.

Keep shared visualization behavior in the Viewer and modality-specific panels
in optional Viewer hooks. Protect behavior with tests before splitting a large
controller into smaller components.

## Tests

`uv run --locked --extra dev pytest` runs the synthetic tests (no Tk window and
no real dataset). The GUI smoke test runs only with `BRKRAW_VIEWER_SMOKE=1` and a
display, and the installed-ecosystem test only with `BRKRAW_ECOSYSTEM_CONTRACT=1`.
