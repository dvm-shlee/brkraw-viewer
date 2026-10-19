# Stage 3 design note: RGB layer and label painter

Status: draft for the Director's review (office#22, first step). No code is changed by this note.
Every statement about the code is marked **observed** (with file:line, paths relative to
`src/brkraw_viewer/`) or **proposed**.

## Goal

- Add a layer kind `"rgb"` (display only): an array whose last axis holds colour channels is drawn as
  colour over the base scan, with opacity and nearest/linear interpolation. (proposed)
- Add a `LabelMapPainter` that edits an editable label layer: paint, erase, brush size, undo, and save the
  result as a label image. (proposed)
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
  (`app/controller/viewer.py:713-719`), so a trailing channel axis of 3 would be read as 3 frames today.
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
  with kind `rgb` no longer counts its last axis as frames (change at `app/controller/viewer.py:713-719`).
- `rgb` forces `editable=False`, like image (extend `core/layers.py:104-107`). `cmap`, `window`, `transparency`
  are ignored for `rgb` (rejected in `update` with a field error so the UI cannot set them).
- Interpolation: `linear` (default) or `nearest` (allowed, unlike label). Opacity: existing `alpha` (0..1) times
  the alpha channel when RGBA.
- Render: a new `rgb_rgba(values, alpha)` in `core/composite.py` returns `(rgb float32, a float32)` like
  `layer_rgba`; `_layer_planes` gets a third branch for `kind == "rgb"` that samples each channel with
  `sample_slice` (one call per channel) and stacks them.

### Painter core (pure numpy, Tk-free): `core/painter.py`

```
class LabelMapPainter:
    def __init__(self, data: np.ndarray, *, max_undo_bytes: int = 64 * 2**20)  # integer 3-D array, edited in place
    brush_size: int  (>= 1, voxels, diameter)      mode: "paint" | "erase"      label: int (> 0)
    def set_brush(self, size: int) -> None         # ValueError names field, value, expected (STYLE.md "Errors")
    def stamp(self, axis: int, index: int, row: float, col: float) -> tuple   # one dab; returns changed bbox
    def stroke(self, axis, index, points) -> tuple # dabs along a segment list, filled with no gaps
    def begin_stroke(self) / end_stroke(self)      # one undo step per stroke
    def undo(self) -> bool
    def can_undo(self) -> bool
```

- Brush stamp: a disc mask of diameter `brush_size` in the view plane, following the `ellipse_mask` pattern
  (`core/roi.py:107`), clipped to the slice bounds; points outside the volume are ignored, not an error.
- Paint writes `label`; erase writes 0. dtype is kept; a label beyond the dtype range is a `ValueError`.
- Undo stack: per stroke, store `(flat indices, old values)` of changed voxels only (not whole slices), capped by
  `max_undo_bytes`; the oldest steps drop first. `undo` restores the last stroke and returns False when empty.
- The painter does not know `Layer` or Tk; the controller owns the array (`_layer_data`) and passes it in.
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
| WI-B | engineer | M (1 day) | `core/painter.py` (`LabelMapPainter`) and `core/labelio.py` (`save_label_nifti`) | Headless: stamp shapes for several sizes, bounds clipping, erase, label dtype range, one undo step per stroke, undo cap, no-gap stroke, NIfTI round trip (affine, dtype, values) |
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
5. Where a painted label layer lives: Options: (a) in memory only, saved on request (recommended; matches
   `source="array"` accounting, `core/layers.py:303-306`); (b) autosave to a scratch file on every stroke.
