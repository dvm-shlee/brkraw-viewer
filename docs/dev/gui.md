# GUI Best Practices

When embedding GUI components into BrkRaw Viewer, prefer stability over
aggressive rendering.

## Recommendations

- Defer heavy rendering with `after_idle` to avoid 1x1 canvas issues.
- Clear state on failures to prevent stale data from reappearing.
- Avoid direct access to internal widgets unless the API provides a method.
- Validate scan compatibility in `can_handle` and display a clear message when
  unsupported.
- Keep callbacks defensive; the viewer may be detached and reattached.

## Underlay overlays

If you draw overlays in a custom viewer:

- Use the viewer's render state for consistent coordinates.
- Clamp indices to the image bounds.
- Clear overlays when switching scans or failing to load data.

## Code layout

- `brkraw_viewer/app/controller/` contains application and dataset controllers.
- `brkraw_viewer/app/services/` and `app/workers/` contain integration services
  and background work.
- `brkraw_viewer/ui/main/` and `ui/tabs/` contain the Tk window and tab UI.

Keep shared visualization behavior in the Viewer and modality-specific panels
in optional Viewer hooks. Protect behavior with tests before splitting a large
controller into smaller components.
