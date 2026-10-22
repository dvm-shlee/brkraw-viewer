# Stage 4 design note: public layer/image Python handle

Status: the Director answered the open questions (office#23, 2026-10-21); still before any code (S4-0). Statements about existing code are
observed and cite file:line (paths under `src/brkraw_viewer/`); everything else is marked (proposed).

## Goal

A notebook or a viewer hook, holding `app` (the controller), can:

- list the layers (id, name, kind, space, shape, affine, visibility);
- read the current image array and its affine (the shown scan, in the display grid);
- add an overlay from a numpy array plus an affine, and get back its id;
- remove an overlay it added.

Out of scope: editing voxels through the handle; loading layers from files; resampling or converting between
spaces (the array must already be in the shown scan's space; see Out of scope under Design); saving; undo; a
versioned/stable API promise beyond "provisional"; calling the handle methods from a non-main thread (use
`app.call_on_main`); making the ROI API permanent.

## Current state

Observed from the code.

- `Layer` is a dataclass with `id, name, kind, source, space, shape, affine, dtype, frames, frame_policy,
  fixed_frame, visible, alpha, cmap, window, transparency, interpolation, editable, nbytes`
  (`core/layers.py:20-41`). Kinds are `image`, `label` only; sources `scan/array/file`
  (`core/layers.py:7-10`). It holds no voxel data.
- `LayerStack` offers `ids()`, `get(id)`, `index(id)`, `base`, `add`, `remove`, `move`, `update`, `subscribe`
  (`core/layers.py:139-182`, `core/layers.py:182`, `core/layers.py:206`, `core/layers.py:215`,
  `core/layers.py:229`). Errors are `LayerError` (a `ValueError`) whose message is a bare word such as
  `"unknown"`, `"duplicate"`, `"base"`, `"space: a vs b"` (`core/layers.py:17`, `core/layers.py:170`,
  `core/layers.py:183-188`, `core/layers.py:209`). Removing layer 0 while others exist is refused
  (`core/layers.py:207-209`). Editable fields are `name, visible, alpha, cmap, window, transparency,
  interpolation, frame_policy, fixed_frame` (`core/layers.py:15`).
- The controller owns `self._layers = LayerStack()` and voxel data in `self._layer_data`
  (`app/controller/viewer.py:90-91`). The base layer (id `"base"`, source `scan`) is rebuilt by
  `_sync_base_layer` whenever the display grid changes, and layers in another space are dropped with a status
  message (`app/controller/viewer.py:662-701`).
- `_add_array_layer(data, affine, *, name, kind="image", space=None, layer_id=None, **fields)` exists but is
  private ("the stage-4 Python handle will offer it"); it uses `np.asarray` (no copy for an ndarray), requires
  ndim >= 3 and a loaded scan, derives `frames` from a 4th dim, auto-names ids `layer-N`, stores the array and
  calls `_render_viewer_views` (`app/controller/viewer.py:703-760`). `_remove_layer(id)` removes the layer and its
  cached data, windows and label colours (`app/controller/viewer.py:762-773`).
- Layer rendering samples only the shown slices (`_layer_planes`, `app/controller/viewer.py:982-1039`); drawing
  runs `_display_grid` then `_sync_base_layer` (`app/controller/viewer.py:1163-1170`).
- The current image: `self._viewer_volume` is the RAS-reoriented volume (`app/controller/viewer.py:79`,
  `app/controller/viewer.py:251`), produced by `_reorient_viewer_volume` from the raw volume and raw affine
  (`app/controller/viewer.py:3032-3051`, the reorient call at `app/controller/viewer.py:3046`). `_display_grid()` (def at `app/controller/viewer.py:638`) returns a
  `Grid(shape, affine, space)` (`app/controller/viewer.py:658`, `core/resample.py:30`). There is no public accessor for either today.
- Provisional ROI API on the controller: `set_roi` (`app/controller/viewer.py:1362`), `clear_roi`
  (`app/controller/viewer.py:1406`), `roi_timecourse(wait=False, timeout=None)` (`app/controller/viewer.py:1413`).
  It raises `ValueError` with the offending value (`app/controller/viewer.py:1381-1392`) and `docs/dev/hooks.md:49`
  states that the stage-4 handle is separate. `roi_timecourse(wait=True)` stays on the Tk main thread and pumps
  events through `_pump_events` (`app/controller/viewer.py:1439-1442`, `app/controller/viewer.py:1445-1456`).
- Threading: observed by grep, `viewer.py` does not import `threading` (the only import near the layer code is
  the layer import at `app/controller/viewer.py:43`) and its only `lock` names are a hook flag
  (`app/controller/viewer.py:106`) and a display option (`app/controller/viewer.py:1177`), so no lock guards the
  layer state. The view is polled via `after` for frame requests (`app/controller/viewer.py:1684-1687`); worker
  results are delivered by `check_results` (`app/controller/viewer.py:1448`). The controller is therefore
  to be treated as not thread-safe (inferred from the absence of locks, not a documented guarantee).
- Hooks receive `app` in `build_tab(parent, app)` and its members are "not a versioned API"
  (`docs/dev/hooks.md:24`, `docs/dev/hooks.md:40-41`).

## Design

Proposed unless a sentence says decided or cites code.

### Lifecycle

Today's behaviour, observed from the code:

- `_sync_base_layer` (`app/controller/viewer.py:662-701`) returns early when the base layer already has the shown
  grid's space, shape and affine (`app/controller/viewer.py:665-671`). When the grid changes it removes every
  layer and rebuilds the base layer from the shown scan (`app/controller/viewer.py:672-692`).
- Other layers in the same space are kept: they are added back (`app/controller/viewer.py:694-696`) and keep their
  own shape and affine. They are drawn through the affine mapping `grid_matrix(grid, Grid(..., layer.affine,
  layer.space))` in `_layer_planes` (`app/controller/viewer.py:1012`), so a kept layer is not resampled in
  storage.
- Layers in another space are dropped with their data (`app/controller/viewer.py:697-699`) and a status message
  `Removed layer(s) in another space: ...` (`app/controller/viewer.py:700-701`).

Proposed rule for handle overlays (proposed (desk, provisional)): they follow the same rule.

- A kept overlay keeps its own shape and affine. `list_layers` shows them, and `get_overlay_array` returns the
  stored array unchanged, never resampled.
- A dropped overlay disappears from `list_layers`, and a later call with its id raises the unknown-id
  `ValueError`.

### Surface

A small handle object, `app.layers_api` (decided, Q4 A), kept thin over `LayerStack` and
`_layer_data`. Tk-free logic goes in a new `core/` module, the controller only binds (per `docs/STYLE.md`,
Layout):

| call | returns | errors |
|---|---|---|
| `list_layers()` | `list[LayerInfo]` (frozen dataclass: `id, name, kind, source, space, shape, affine (copy), dtype, frames, visible, alpha, cmap`) in stack order, base first | none (empty list with nothing loaded) |
| `get_image(copy=True)` | `(array, affine)` of the shown scan in the display grid (`_viewer_volume` and `Grid.affine`) | `ValueError("image: got no loaded scan, expected a loaded scan (open a dataset and select a scan first)")` |
| `add_overlay(data, affine, *, name, kind="image", editable=False, layer_id=None, copy=True, **fields)` | the new layer id (`str`) | `ValueError` per the Errors rule below |
| `get_overlay_array(layer_id, copy=True)` | the stored array (copy by default; `copy=False` a read-only view) | `ValueError` for unknown id or the base layer |
| `app.call_on_main(fn, timeout=5.0)` (on the app, not on `layers_api`) | the return value of `fn` | `TimeoutError`; the exception raised in `fn`; an error on shutdown |
| `set_overlay(layer_id, **fields)` | `None` (wraps `LayerStack.update`, which returns the changed field names; the handle drops them) | `ValueError` for unknown id, the base layer, a field outside the editable fields, or an invalid value |
| `remove_overlay(layer_id)` | `None` | `ValueError` for unknown id, the base layer, or a layer not added from Python |

`fields` are limited to the editable fields (`core/layers.py:15`) so a notebook can set `cmap`, `window`,
`alpha`, `visible` at add time; later changes use `set_overlay` (proposed, wraps
`LayerStack.update`, `core/layers.py:229`). `editable` is a separate keyword, not one of the editable fields: it
is a `Layer` attribute (`core/layers.py:39`) and the stack refuses it on an image layer
(`core/layers.py:127-128`), so it is valid only with `kind="label"`. The base layer is read-only through the handle.

### Errors

Per `docs/STYLE.md` (Errors), each `ValueError` names the field, the offending value and the expected values,
for example `ValueError("layer_id: got 'base', expected an overlay id from list_layers()")` and
`ValueError("data: got shape (4, 4), expected at least 3 dimensions")`. `LayerError` messages are bare words
(`core/layers.py:170`), so the handle translates them rather than leaking them (`LayerError` stays a
`ValueError`, so callers catching `ValueError` keep working). Space is not a parameter in stage 4: the overlay
takes the base layer's space (`app/controller/viewer.py:749`) and a differing space is refused by the stack
(`core/layers.py:187-188`). Decided (Q5 A): `add_overlay` validates shape, affine and space together against the
base layer and refuses with `ValueError`; it never converts or resamples. No scan loaded: the `image` message in the table above, which carries the offending state and the expected one.

### Thread rule

Decided (Q1 B): the handle methods are Tk main thread only, and `app.call_on_main` is in stage 4. Every direct
call must run on the thread that owns the Tk root: hook callbacks and button handlers do. Each method checks
`threading.current_thread() is threading.main_thread()` and raises
`RuntimeError("thread: got <name>, expected the Tk main thread")` otherwise; the guard stays.

`app.call_on_main(fn, timeout=5.0)` is for other threads (a notebook). It schedules `fn` on the Tk main thread with
the view's `after` (`app/controller/viewer.py:1684-1687`) and waits for the result:

- on timeout it raises `TimeoutError`, like `roi_timecourse`;
- an exception raised in `fn` propagates to the caller;
- shutdown: when the Tk root is destroyed or the app closes while a call waits, the waiter is released with an
  error and never hangs.

### Copy vs view

- `get_image(copy=True)` returns a copy by default; `copy=False` returns a read-only view
  (`writeable = False`, so writes raise) valid only until the next dataset, scan, reco, flip or slicepack
  change, because `_viewer_volume` is replaced then (`app/controller/viewer.py:251`).
- `get_overlay_array(layer_id, copy=True)` (decided, Q3 B) returns a copy by default; `copy=False` returns a
  read-only view (`writeable = False`) of the stored array.
- `add_overlay` stores the caller's voxel array by reference today (`np.asarray`, `app/controller/viewer.py:719`,
  stored at `app/controller/viewer.py:758`), but copies the affine: `Layer.__post_init__` runs
  `np.array(self.affine, dtype=np.float64)` (`core/layers.py:64`). Proposed: keep the affine copy as is.
- Decided (Q2 B): `add_overlay(..., copy=True)` copies the voxel array by default; `copy=False` stores the caller's
  array by reference. `nbytes` counts the stored array. The rules:
  - Ownership: with `copy=True` the layer owns its copy and the caller's array may be mutated freely; with
    `copy=False` the caller keeps ownership and is the only one who may mutate it.
  - Lifetime: the stored array lives until `remove_overlay` or until the layer is dropped (Lifecycle above).
  - Mutation: the caller mutates a `copy=False` array only on the Tk main thread, and must then call
    `set_overlay(layer_id)` or an explicit refresh so caches update.
  - Caches affected: `_layer_window` caches a default window per layer and frame in `_layer_windows`
    (`app/controller/viewer.py:964-972`), and `_label_colors` caches label colours per layer in
    `_layer_label_colors` (`app/controller/viewer.py:974-979`). Neither notices a mutated array.
- `list_layers` returns affine copies and no voxel data.

### Fit with the provisional ROI API

The ROI API is independent: one ROI, never saved, cleared on state change (`docs/dev/hooks.md`). The handle adds
no ROI member. Shared rules: same thread rule, same `ValueError` style, same "provisional" label in
`hooks.md`. A later step can let `roi_timecourse` take a layer id (proposed, not in stage 4). Overlays added
through the handle are drawn like any layer, so a ROI over a scan and an overlay coexist unchanged.

### Fit with the stage 3 LabelEditor

`docs/dev/design-stage3.md` proposes `LabelEditor` as a Tk-free class over a label layer's array and lists
"the stage-4 Python handle" as out of its scope. `LabelEditor` exists now (`core/painter.py`). Contract:
`add_overlay(kind="label", editable=True)` returns the layer id (`str`, as in the table); the stored array behind
that id is what a `LabelEditor` mutates; with the default `copy=True` the editor owns the stored array and the
notebook's original is untouched. Reading an edited label back is `get_overlay_array(layer_id, copy=True)`, which
is in stage 4 (decided, Q3 B).

### Stability

The API is provisional until the work items' tests pass; it is marked provisional in `hooks.md` like the ROI
members, with no versioning promise afterwards either.

### Out of scope

Registration or resampling of overlays, and voxel editing through the handle, stay separate (not in stage 4).

## Work items

One worker each; Appetite is the time box. GUI tests run under Xvfb with `BRKRAW_VIEWER_SMOKE=1`
(`docs/STYLE.md`, GUI tests; `docs/dev/gui.md`) and are named `tests/test_mkj_wiNNNN_<topic>.py`.

1. Core handle module (engineer, Appetite: 0.5 day). New Tk-free `core/layer_handle.py` with `LayerInfo`, the
   error translation and copy rules over a `LayerStack` plus a data dict. Tests (no Tk): list order and base
   first, add/remove round trip, duplicate id, unknown id, base refusal, 2-D array refusal, copy semantics
   both ways (`copy=True`: mutating the source after add does not change the layer; `copy=False`: the layer sees the
   change after `set_overlay`), `copy=False` on `get_overlay_array` is read-only, `add_overlay` validation of shape,
   affine and space together (Q5 A, one test per bad input and one per refused conversion), error messages name
   field, value and expected, and the large-volume memory test (`nbytes` accounting, no hidden copy for
   `copy=False`; as a scheduler job if it needs memory). `add_overlay` gains `copy=False` and
   `get_overlay_array` is added here.
2. Controller binding and image accessor (engineer, Appetite: 0.5 day). Wire the handle onto the controller
   (`get_image` from `_viewer_volume` and `_display_grid`, add/remove through `_add_array_layer` and
   `_remove_layer`, thread guard). Tests: headless controller with a fake view (no Tk): no-image errors, shape and
   affine of `get_image`, read-only view, overlay add then `list_layers`, overlay dropped on grid change
   (`_sync_base_layer`), call from a worker thread raises `RuntimeError`, and the Lifecycle rule tests (a kept overlay keeps its shape
   and affine and `get_overlay_array` returns it unchanged; a dropped overlay leaves `list_layers` and its id
   raises the unknown-id `ValueError`).
3. Viewer GUI check (engineer, Appetite: 0.5 day). Under Xvfb: open a sample scan, `add_overlay` from a hook
   callback, assert the layer is listed and the view re-renders; `remove_overlay` removes it; a ROI set
   alongside still answers `roi_timecourse(wait=True)`. Depends on 2.
4. Docs (engineer, Appetite: 0.25 day). Extend `docs/dev/hooks.md` with the handle (provisional) and a notebook
   example; record the thread rule. Depends on 2. Verification (doc-only, no Tk): `mkdocs build --strict`
   from the module root passes (no broken links or nav warnings for `docs/dev/hooks.md`); a citation re-check
   confirms each file:line the new text cites still shows what it claims (+/- 2 lines); the notebook example
   runs as a headless test (`tests/test_mkj_wiNNNN_handle_docs_example.py`, fake view as in item 2) so the
   documented calls and return types match the implemented handle.
5. `call_on_main` (engineer, Appetite: 0.5 day; no longer optional, Q1 B). Tests under Xvfb: call from a thread
   returns the value; timeout raises `TimeoutError`; an exception in `fn` propagates to the caller; a shutdown test
   (the Tk root destroyed or the app closing while a call waits releases the waiter with an error, never hangs).

## Director decisions (office#23, 2026-10-21)

- Q1 B: `app.call_on_main(fn, timeout=...)` is in stage 4: runs `fn` on the Tk main thread, `TimeoutError` on
  timeout, propagates an exception from `fn`, releases the waiter with an error on shutdown. The main-thread guard
  on the handle methods stays.
- Q2 B: `add_overlay(..., copy=True)` copies by default; `copy=False` stores the caller's array by reference (rules
  under Copy vs view).
- Q3 B: `get_overlay_array(layer_id, copy=True)` is in stage 4; `copy=False` returns a read-only view.
- Q4 A: a separate object `app.layers_api`.
- Q5 A: refuse with `ValueError`, no conversion; `add_overlay` validates shape, affine and space together against
  the base layer.
- Extras: the API stays provisional until tested; large-volume memory and copy tests (`nbytes` accounting, no
  hidden copy for `copy=False`); the overlay lifecycle on base scan or display grid change is defined (Lifecycle);
  registration/resampling and voxel editing stay separate (Out of scope).

### Citations to revisit

Refreshed against base 7a1f42a (WI-0047, WI-0049/0055, WI-0063 changed the files). The sentences below cite code
whose meaning changed, not only its position; prose is left as written for the Director to decide.

- `core/layers.py:19-38` -> `core/layers.py:20-41`: `Layer` also has a `channels` field (default 1) after `nbytes`.
- `core/layers.py:7-8` -> `core/layers.py:7`, `core/layers.py:10`: kinds are now `image`, `label`, `rgb`
  (`KINDS`); sources unchanged.
- `core/layers.py:15` -> `core/layers.py:17`; `core/layers.py:147` -> `core/layers.py:170`;
  `core/layers.py:161-166` -> `core/layers.py:183-188`; `core/layers.py:186` -> `core/layers.py:209`: `LayerError`
  messages are no longer bare words; they are structured `field: got X, expected Y (...)` strings, e.g.
  `"layer_id: got 'x', expected one of [...] (unknown layer)"`, `"id: ... (duplicate)"`.
- `core/layers.py:106-107` -> `core/layers.py:127-128`: the editable refusal now also covers kind `rgb`
  (`core/layers.py:129-130`).
- `app/controller/viewer.py:695-737` -> `app/controller/viewer.py:703-760`: `_add_array_layer` gained an `rgb`
  branch (4-D, last axis 3 or 4 channels, uint8 or float 0..1 converted to uint8); the listed behaviours still hold.
- `app/controller/viewer.py:739-748` -> `app/controller/viewer.py:762-773`: `_remove_layer` now returns `bool` and
  asks for confirmation (tkinter `askyesno`) when the layer has unsaved paint edits; the cache cleanup moved to
  `_drop_layer_data` (`app/controller/viewer.py:774-785`).
- `app/controller/viewer.py:934-941` -> `app/controller/viewer.py:1163-1170`: layer drawing is skipped while RGB
  is on (`if not rgb_on`).
- `app/controller/viewer.py:98` -> `app/controller/viewer.py:106`; `app/controller/viewer.py:951` ->
  `app/controller/viewer.py:1177`: `lock` names in the controller are now more numerous (`_viewer_hook_locked`
  is set at several places, `hook_locked` state); no `threading` import and no lock guarding layer state still
  hold. `app/controller/viewer.py:750-766` -> `app/controller/viewer.py:964-980` is a best match: the window and
  label-colour caches are `_layer_window` and `_layer_label_colors`.
