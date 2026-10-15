# Viewer Hooks

Viewer hooks are discovered through the `brkraw.viewer.hook` entry point group.
Each hook can provide a tab UI. The current host only calls `build_tab` when
the extension is selected.

Hooks keep modality-specific visualization in extension packages while the
Viewer owns common display behavior. Viewer hooks can coexist with
converter hooks and CLI hooks, so UI features can build on the same conversion
logic without patching the viewer itself.

## Entry point

Add an entry point in your `pyproject.toml`:

```toml
[project.entry-points."brkraw.viewer.hook"]
brkraw-mrs = "brkraw_mrs.viewer_hook:MRSViewerHook"
```

## Hook interface

The host currently uses `name` (falling back to `tab_title`, then `"Extension"`)
and `build_tab(parent, app)`. `build_tab` must return a Tk widget or `None`;
any other return value is refused with a warning. An exception raised by
`build_tab` is logged as a warning and does not stop the viewer, and an entry
point that fails to import is skipped with a warning. An entry point that is a
class is instantiated without arguments; if that raises, the host logs a warning
with the hook name and the reason, skips that hook only, and still loads the others
and the Extensions tab. Other attributes, for example `priority`,
are not read, and hooks are listed in the Extensions tab sorted by name.

```python
class MyHook:
    name = "my-extension"
    def build_tab(self, parent, app):
        ...
```

`app` is the viewer's controller object. These members exist today and are used
by extensions; they are not a versioned API:

- `app.on_viewer_jump(x, y, z)`: move the Viewer tab position
- `app.on_viewer_space_change(value)` and `app.register_viewer_space_listener(cb)`:
  change or follow the Space selection
- `app.state.dataset.selected_scan_id` and `app.state.dataset.selected_reco_id`:
  the current selection
- `app.dataset.get_scan(scan_id)`: the BrkRaw scan object
- Temporary ROI (**provisional**, may change; the stage-4 handle is separate):
  - `app.set_roi(shape, geometry, axis=2, index=None)`: `shape` is `"rect"`
    (`geometry = (u0, u1, v0, v1)`, inclusive pixels) or `"ellipse"`
    (`(cu, cv, ru, rv)`: centre and radii). Pixels are those of display slice
    `index` (default: the shown one) on `axis` (0, 1 or 2 of the RAS-reoriented
    grid), laid out like `volume.take(index, axis)`. A ROI past the slice edge is
    clipped. Raises `ValueError` for a bad shape, geometry or index, or with no
    image loaded. The ROI mean per frame is requested from the worker and shown in
    the Timecourse plot (title: shape and voxel count).
  - `app.clear_roi()`: remove it; the plot returns to the voxel timecourse.
  - `app.roi_timecourse()`: `None` until the answer is in; then a dict with
    `values` (mean of the finite voxels per frame, NaN for a frame with none),
    `n_mask`, `n_per_frame`, `shape`, `axis`, `index`.

  The Viewer tab's ROI tool (Off / Square / Circle, see the user guide) calls the same
  `set_roi` on release and `clear_roi` on Esc or tool off; the overlay follows the
  controller, so a ROI set from Python is drawn on the view of its axis too. A drag
  gives `"rect"` `(u0, u1, v0, v1)` or, for the circle tool, `"ellipse"` `(cu, cv, r, r)`.

  Only one ROI exists and it is never saved. It is cleared when the dataset, scan,
  reco, converter hook or its options, slicepack, flip or the shown slice on its
  axis changes; an answer for an earlier ROI or state is dropped.

Hooks are loaded when the Extensions tab is built, and the panel is built again
when you select it from the list or re-attach the tab. The selection is
remembered for the session. A hook gets no call when a dataset or scan changes:
read the state when you build the panel, or follow Space through
`register_viewer_space_listener`. There is no supported way to draw on the Viewer
tab; the Viewer tab's **Hook** box applies the scan's *converter* hook, which is
a different mechanism.

Some existing extensions define `on_dataset_loaded`, `on_scan_selected` and
`can_handle`, but the current host does not call them. Do not rely on them
until host dispatch is implemented and covered by tests.
