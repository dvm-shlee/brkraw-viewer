# Stage 3 design note: RGB layer and label painter

Status: draft for the Director's review (office#22, first step). No code is changed by this note.
Every statement about the code is marked **observed** (with file:line, paths relative to
`src/brkraw_viewer/`) or **proposed**.

## Goal

- Add a layer kind `"rgb"` (display only): an array whose last axis holds colour channels is drawn as
  colour over the base scan, with opacity and nearest/linear interpolation. (proposed)
- Add label painting on an editable label layer: paint, erase, brush size, undo, and save the result as a
  label image. The Tk-free core is a new class `LabelEditor`, named so it does not clash with the existing Tk
  class `LabelMapPainter` (`ui/components/label_painter.py:22`). (proposed)
- Out of scope: new colour spaces or per-channel windowing for RGB layers; editable RGB layers; painting on
  image layers; 3-D brushes; redo; autosave; the stage-4 Python handle; resampling a painted layer to another
  grid. (proposed)

## Current state

Observed in `core/layers.py`:

- Kinds are `("image", "label")` only (`core/layers.py:7`); sources `scan/array/file` (`core/layers.py:8`);
  interpolations `linear/nearest` (`core/layers.py:10`).
- `Layer` is a dataclass with `kind`, `shape`, `affine`, `dtype`, `frames`, `alpha`, `cmap`, `window`,
  `transparency`, `interpolation`, `editable`, `nbytes` (`core/layers.py:18-38`).
- Shape must have at least 3 dims, all >= 1 (`core/layers.py:57-58`); a 4th dim is treated as frames
  (`app/controller/viewer.py:720`: `frames = int(arr.shape[3]) if arr.ndim >= 4 else 1`), so a trailing channel axis of 3 would be read as 3 frames today.
- A label layer is forced to `nearest` (`core/layers.py:104-105`); an editable image layer is refused
  (`core/layers.py:106-107`). So `editable=True` is only valid for label layers, but nothing consumes the flag yet
  (no use of `editable` found in `app/` or `ui/` by search; not exhaustive).
- `EDITABLE_FIELDS` (metadata fields, unrelated to the `editable` flag) lists name/visible/alpha/cmap/window/
  transparency/interpolation/frame fields (`core/layers.py:13`); `LayerStack.update` validates then applies them and
  emits `layer_changed` (`core/layers.py:206-268`). Voxel data is not part of `Layer`.
- Voxel data lives outside the stack, in the controller's `_layer_data` dict (`app/controller/viewer.py:89`);
  `_add_array_layer` stores the array there and calls `_render_viewer_views` (`app/controller/viewer.py:695-737`).
- The render path `_layer_planes` samples only the three shown slices through `sample_slice`
  (`app/controller/viewer.py:768-812`, `core/resample.py:176`). Labels go through `label_rgba`, images through
  `layer_rgba`, both returning `(rgb, alpha)` (`app/controller/viewer.py:788-812`, `core/composite.py:46-69`).
  `label_rgba` requires an integer array (`core/composite.py:73-75`).
- Label colours are cached per layer id on first use from the unique ids (`app/controller/viewer.py:760-766`).
- The base viewer already has a separate RGB mode for a 3-frame base volume (`app/controller/viewer.py:833-840`,
  `2110`); it is not a layer kind.
- The ROI tool is the UI pattern: Tk-free state in `core/roi.py` (`RoiDrag`, `core/roi.py:199`; masks
  `core/roi.py:51-117`), and the Tk binding inside `ui/tabs/viewer/right_panel.py` (radio buttons
  `right_panel.py:69-82`, canvas bindings `right_panel.py:116-119`, handlers `right_panel.py:238-273`). There is no
  `ui/roi_tool.py` in the tree, although the requirements name one. STYLE.md states the core/ui split
  (`docs/STYLE.md`, "Layout").

Observed in the existing Tk label painter `ui/components/label_painter.py` (not imported anywhere: a search of
`src/` for `LabelMapPainter` and `label_painter` finds only its own definition):

- `LabelMapPainter(viewport: ViewportCanvas)` is a Tk-bound class (`label_painter.py:22,45`) with a `Brush`
  dataclass (`radius`, `shape` "circle"/"square", `label_painter.py:16-19`).
- It paints into a 2-D `label_map`, or into a writable slice view of a bound 3-D `label_volume`; `set_slice`
  re-binds the view when the shown slice changes (`label_painter.py:48-53,140-160,173-200`).
- It binds the viewport canvas itself through `bind_canvas`: left button paints the active label, right/middle
  button erases (writes 0), and hover events draw a brush preview (`label_painter.py:86-118`).
- Canvas pixels map to slice indices through `viewport.canvas_to_image` (`label_painter.py:463-466`,
  `ui/components/viewport.py:304-340`), i.e. the index space of the 2-D image shown in that viewport.
- Strokes are gap-free by Bresenham between successive points (`label_painter.py:492-510,557-579`). The stamp is a
  size x size square, or a disc of effective radius `min((size-1)//2, size//2)`, clipped to the slice
  (`label_painter.py:581-619`); a dirty bbox is kept per stroke (`label_painter.py:621-628`).
- It renders its own RGBA overlay from a 256-entry LUT and pushes it with `viewport.set_overlay_rgba`, throttled
  to about 30 FPS (`label_painter.py:277-306,432-459,632-647`; `ui/components/viewport.py:342`), and calls
  `on_stroke_end` / `on_label_changed` on release (`label_painter.py:512-549`).
- Its docstring says it is UI-only and leaves 3-D volumes, undo and saving to the controller
  (`label_painter.py:40-42`): it has no undo, no save, and no knowledge of `Layer`.

Missing (an absence has no file:line; these claims are observed by a search of `src/` for voxel writes and undo
stacks, and each is to be read as proposed work in the Design section, not as a cited code fact; the only cited
anchors are the lines given): an `rgb` kind; a channel-axis rule; any code that mutates layer voxel data; an undo mechanism for voxels (the
only `undo` hits in `src/` are Tk text-widget undo, `ui/tabs/addons/window.py:1015,1139`; the existing label painter
widget states it manages no volumes, undo stacks or saving, `ui/components/label_painter.py:41`); any writer for layer data (NIfTI is written only by the convert worker through `img.to_filename`,
`app/workers/convert_worker.py:264-265`; `nibabel` is imported in `utils/orientation.py:5`).

## Design

All items below are proposed.

### Data model

- `KINDS = ("image", "label", "rgb")`. For `rgb`, the array shape is `(X, Y, Z, 3)` or `(X, Y, Z, 4)` (RGB or
  RGBA), dtype `uint8` (0-255) or float in 0..1 (rescaled to uint8 at load). Other dtypes: `LayerError`.
- `Layer.shape` stays the full array shape; add a field `channels: int = 1` (3 or 4 for `rgb`), and set
  `frames = 1` for `rgb` (the channel axis is never frames). `_add_array_layer` branches on `kind`, so a 4-D array
  with kind `rgb` no longer counts its last axis as frames (change at `app/controller/viewer.py:720`).
- `rgb` forces `editable=False`, like image (extend `core/layers.py:104-107`). `cmap`, `window`, `transparency`
  are ignored for `rgb` (rejected in `update` with a field error so the UI cannot set them).
- Interpolation: `linear` (default) or `nearest` (allowed, unlike label). Opacity: existing `alpha` (0..1) times
  the alpha channel when RGBA.
- Render: a new `rgb_rgba(values, alpha)` in `core/composite.py` returns `(rgb float32, a float32)` like
  `layer_rgba`; `_layer_planes` gets a third branch for `kind == "rgb"` that samples each channel with
  `sample_slice` (one call per channel) and stacks them.

### Existing `LabelMapPainter`: reuse, wrap or replace

Choice (recommended default, Open question 5): **replace in role, reuse the algorithms**. Stage 3 does not attach
the existing Tk class to the viewer; its stamp and line algorithms are ported into the new Tk-free core class
`LabelEditor` (`core/painter.py`), and the existing file is left untouched in stage 3 (removal or a rebase onto
`LabelEditor` is a later decision). Reasons, each from the observations above:

- Wrong coordinate space for layers: it writes at `canvas_to_image` indices of the shown 2-D image
  (`label_painter.py:463-466`, `viewport.py:304-340`), while layers are drawn by resampling the layer volume onto
  the shown grid through a matrix (`sample_slice`, `app/controller/viewer.py:788`). Painting a layer whose grid
  differs from the shown grid needs the inverse mapping (display index -> layer voxel), which belongs in the
  controller/core, not in a viewport widget.
- Second render path: it draws its own overlay with `set_overlay_rgba` (`label_painter.py:277-306`), outside the
  layer compositing in `_layer_planes` (`app/controller/viewer.py:768-812`). The painted layer would then show
  twice, with two palettes (its LUT, `label_painter.py:632-647`, vs `_label_colors`, `viewer.py:760-766`), and
  ignore the layer's `alpha`/`visible`.
- No undo and no save (`label_painter.py:40-42`); both are stage-3 requirements and must be testable headless.
- Tk-bound state and logic mixed in one class (`label_painter.py:45-83`), against the core/ui split in STYLE.md
  ("Layout"); its brush logic cannot be unit-tested without a Tk viewport.
- Its own bindings (`label_painter.py:98-114`) would stack with the ROI bindings on the same `<ButtonPress-1>`
  (`right_panel.py:116-118`, `add=True`), so one tool at a time needs a single dispatcher anyway.

What is reused (ported, with tests): the Bresenham stroke fill (`label_painter.py:557-579`), the brush footprint
semantics (size = diameter, even sizes by asymmetric half-widths, circle/square, `label_painter.py:591-617`), the
erase-writes-0 rule, and the dirty bbox. The hover brush preview of `ViewportCanvas` (`viewport.py:372`) is reused
as is by the new UI binding.

Alternatives: (b) wrap: keep `LabelMapPainter` as the UI binding and hand it a slice view of the layer array,
adding undo/save around it in the controller; cheaper at first, but keeps the second render path and only works
when the layer grid equals the shown grid. (c) reuse as is: not viable for the reasons above.

### Painter core (pure numpy, Tk-free): `core/painter.py`

```
class LabelEditor:
    def __init__(self, data: np.ndarray, *, max_undo_bytes: int = 64 * 2**20)  # integer 3-D array, edited in place
    brush_size: int  (>= 1, voxels, diameter)      mode: "paint" | "erase"      label: int (> 0)
    def set_brush(self, size: int) -> None         # ValueError names field, value, expected (STYLE.md "Errors")
    def stamp(self, axis: int, index: int, row: float, col: float) -> tuple   # one dab; returns changed bbox
    def stroke(self, axis, index, points) -> tuple # dabs along a segment list, filled with no gaps
    def begin_stroke(self) / end_stroke(self)      # one undo step per stroke
    def undo(self) -> bool
    def can_undo(self) -> bool
```

- Brush stamp: the footprint ported from `label_painter.py:591-617` (size = diameter, a disc by default, square
  optional), in the layer's voxel slice `(axis, index)`, clipped to the slice bounds; points outside the volume are
  ignored, not an error. `row/col` are layer voxel indices: the controller maps a display index to layer voxels
  with the inverse of the matrix it gives `sample_slice` (`app/controller/viewer.py:788`), so painting is correct
  also when the layer grid differs from the shown grid.
- Stroke fill: Bresenham between successive points, ported from `label_painter.py:557-579`.
- Paint writes `label`; erase writes 0. dtype is kept; a label beyond the dtype range is a `ValueError`.
- Undo stack: per stroke, store `(flat indices, old values)` of changed voxels only (not whole slices), capped by
  `max_undo_bytes`; the oldest steps drop first. `undo` restores the last stroke and returns False when empty.
- `LabelEditor` does not know `Layer` or Tk; the controller owns the array (`_layer_data`) and passes it in.
  The array lives in memory only and is written to disk only on Save (no autosave), like any `source="array"`
  layer (array layers are counted in `total_nbytes`, not in `held_nbytes`, `core/layers.py:302-306`).
- Controller glue (`app/controller/viewer.py`): after a stroke, drop the cached colours for that layer id
  (`_layer_label_colors`, `viewer.py:760-766`; otherwise a newly painted id has no colour) and call
  `_render_viewer_views`. A cheaper partial redraw is possible; to be decided in WI-C.

### UI wiring

- Tool toggle like the ROI tool: radio buttons `Off / Paint / Erase` plus a brush-size spinbox and an Undo button,
  next to the ROI box in `ui/tabs/viewer/right_panel.py` (pattern `right_panel.py:69-82`). Tk-free state (tool,
  drag) in `core/painter.py`; the thin binding in a new `ui/tabs/viewer/paint_tool.py` so `right_panel.py` does not
  grow (STYLE.md "Layout"). Tk variables get an explicit `master` (STYLE.md GUI candidates).
- The tool is active only when the selected layer is `kind == "label"` and `editable`; otherwise the radio is
  disabled. Painting and ROI tools are mutually exclusive (one tool at a time) because both bind
  `<ButtonPress-1>` (`right_panel.py:116-118`).
- Mouse: press begins a stroke, motion adds dabs, release ends it, Ctrl+Z undoes, Esc cancels a stroke in progress
  (mirrors `right_panel.py:119`).
- A way to create an editable empty label layer over the base grid (same shape/affine) is needed, as no layer can
  be made editable from the UI today: a "New label layer" button calling
  `_add_array_layer(kind="label", editable=True)`.

### Save path and format

- Format: NIfTI (`.nii.gz`) with the layer's affine, integer dtype (uint8 if max label <= 255 else uint16).
  Writer: `nibabel` (already imported, `utils/orientation.py:5`); there is no existing viewer writer for layer
  arrays, so a small `core/labelio.py` function `save_label_nifti(data, affine, path)` is proposed, using the
  `img.to_filename` call style of `app/workers/convert_worker.py:264-265`.
- A "Save label..." action in the paint box asks for a path (file dialog) and writes it; the layer stays editable.
  A JSON sidecar with label id -> colour is optional (Open question 3).
- Unsaved edits: removing a dirty label layer asks for confirmation (wired in WI-C).

## Work items

Each item is one worker, one session; Appetite is the maximum effort before the item is cut or re-scoped.

| ID | Role | Appetite | Scope | Tests |
|----|------|----------|-------|-------|
| WI-A | engineer | S (half day) | `rgb` kind in `core/layers.py` and `core/composite.py` (`rgb_rgba`), `_add_array_layer` channel rule, `_layer_planes` branch | Headless `tests/test_mkj_wiNNNN_rgb_layer.py`: kind validation, shape/dtype rules, frames not taken from channels, alpha, nearest vs linear, RGBA alpha, rendered plane colours |
| WI-B | engineer | M (1 day) | `core/painter.py` (`LabelEditor`, porting the stamp and Bresenham code of `ui/components/label_painter.py`) and `core/labelio.py` (`save_label_nifti`); `label_painter.py` left untouched | Headless: stamp shapes for several sizes (same footprints as the existing painter for sizes 1-10), even sizes, bounds clipping, erase, label dtype range, one undo step per stroke, undo cap, no-gap stroke, NIfTI round trip (affine, dtype, values) |
| WI-C | engineer | M (1 day) | Controller glue and `ui/tabs/viewer/paint_tool.py`: tool toggle, brush spinbox, undo, new/save label layer, colour cache invalidation, exclusivity with ROI | GUI test under Xvfb (`BRKRAW_VIEWER_SMOKE=1 xvfb-run -a`, see `docs/dev/gui.md`): toggle enabled only for editable label layers, synthetic press/motion/release changes layer data and the rendered plane, Ctrl+Z reverts, Tk root destroyed in teardown |
| WI-D | engineer | S (half day) | Docs: user guide section and `docs/dev` update; STYLE.md note if the Director adopts the GUI candidates | docs build check if configured; no code tests |

Order: A and B are independent and may run in parallel; C needs both; D last. Each item is verified by the
checker through its declared checks; no test suite runs in a session.

## Open questions for the Director

1. RGB source: should an RGB layer also accept a 3-frame scan result (as the base RGB mode does) or only arrays?
   Options: (a) arrays only (recommended; smallest, keeps frames and channels apart); (b) also a 3-frame scan.
2. Undo depth: Options: (a) byte cap of 64 MiB, oldest dropped (recommended); (b) fixed 50 strokes; (c) unlimited.
3. Save format: Options: (a) NIfTI `.nii.gz` only (recommended); (b) NIfTI plus a JSON colour sidecar;
   (c) also uncompressed `.nii`.
4. Brush dimensionality: Options: (a) 2-D disc in the shown slice (recommended); (b) 3-D sphere; (c) selectable.
   (The in-memory, save-on-request lifetime of a painted layer is taken as decided in Design; autosave is out of
   scope.)
5. The existing Tk `LabelMapPainter` (`ui/components/label_painter.py:22`, unused): Options: (a) replace in role:
   port its stamp and stroke algorithms into the new core `LabelEditor`, wire a new thin binding, leave the old
   file untouched for now (recommended; one render path, correct for any layer grid, headless-testable undo);
   (b) wrap: keep it as the UI binding over a slice view of the layer array and add undo/save in the controller
   (cheaper first step, but a second overlay path and only correct when the layer grid equals the shown grid);
   (c) reuse as is (not recommended: no undo or save, own overlay); (d) as (a) and also delete the old file in
   WI-D.
