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
  - `app.roi_timecourse(wait=True, timeout=5.0)`: blocks until the answer for the current ROI
    is in and returns the same dict. Safe in a button callback: Tk events (and the worker's
    result) are still processed while it waits. Raises `TimeoutError` after `timeout` seconds
    (`None` waits without limit) and `ValueError` without a ROI. If the ROI is replaced while
    waiting it returns the new ROI's answer; if it is cleared it raises `ValueError`.

  The Viewer tab's ROI tool (Off / Square / Circle, see the user guide) calls the same
  `set_roi` on release and `clear_roi` on Esc or tool off; the overlay follows the
  controller, so a ROI set from Python is drawn on the view of its axis too. A drag
  gives `"rect"` `(u0, u1, v0, v1)` or, for the circle tool, `"ellipse"` `(cu, cv, r, r)`.

  Only one ROI exists and it is never saved. It is cleared when the dataset, scan,
  reco, converter hook or its options, slicepack, flip or the shown slice on its
  axis changes; an answer for an earlier ROI or state is dropped.
- Layers (**provisional**, office#23; may change until its tests have run in real use):
  - `app.layers_api.list_layers()`: list of read-only `LayerInfo` (`id`, `name`, `kind`,
    `source`, `space`, `shape`, `affine`, `dtype`, `frames`, `visible`, `alpha`, `cmap`),
    the base layer first. No voxel data.
  - `app.layers_api.get_image(copy=True)`: `(array, affine)` of the shown scan. With
    `copy=False` the array is a read-only view.
  - `app.layers_api.add_overlay(data, affine, *, name, kind="image", editable=False, layer_id=None, copy=True, space=None, **fields)`:
    adds an overlay and returns its id (`str`). `kind` is one of the handle kinds
    (for example `"image"` or `"label"`); `editable=True` needs `kind="label"`; `space=None`
    means the shown scan's space; `**fields` are display fields such as `alpha`, `cmap`,
    `visible`, `window`.
  - `app.layers_api.set_overlay(layer_id, **fields)`: change display fields; returns `None`.
    With no fields it refreshes the view after you mutated a `copy=False` array.
  - `app.layers_api.get_overlay_array(layer_id, copy=True)`: the overlay's voxel array
    (`numpy.ndarray`); `copy=False` gives a read-only view.
  - `app.layers_api.remove_overlay(layer_id)`: remove an overlay; returns `None`.
  - `app.call_on_main(fn, timeout=5.0)`: run `fn()` on the Tk main thread and return its
    result. On the main thread it runs at once; from another thread it is queued, `fn`'s
    exception is re-raised to the caller, and `TimeoutError` follows if no answer comes
    within `timeout` seconds (the call is then cancelled).

  Rules:
  - Main thread only: every `layers_api` method raises `RuntimeError` from another thread.
    From a worker thread wrap the call in `call_on_main`.
  - Copies: `copy=True` means the handle owns its own copy. `copy=False` holds the caller's
    array (a `numpy.ndarray`); mutate it on the main thread, then call `set_overlay(layer_id)`
    with no fields to refresh. Views are read-only.
  - An overlay must match the shown scan's space, shape and affine; otherwise `ValueError`.
    Nothing is resampled.
  - Lifecycle: overlays in the same space are kept when the scan or display grid changes;
    overlays in another space are dropped and their ids are then unknown.
  - Out of scope: registration or resampling, and voxel editing through the handle.
  - Errors read `<field>: got ..., expected ...` (for example `shape: got ..., expected ...`).

```python
# example: layers_api
img, affine = app.layers_api.get_image()
mask = (img > img.mean()).astype(np.uint8)
layer_id = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
names = [info.name for info in app.layers_api.list_layers()]  # base first, then "mask"
back = app.layers_api.get_overlay_array(layer_id)  # a copy equal to mask
app.layers_api.set_overlay(layer_id, alpha=0.5)
app.layers_api.remove_overlay(layer_id)
```

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
