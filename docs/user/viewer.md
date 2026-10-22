# Viewer

The default Viewer tab provides **visual QC and orientation checks** without
committing to a conversion. The Viewer application also hosts specialized
visualization panels supplied by optional extensions.

This fits the brkraw philosophy by keeping the viewer lightweight while leaning
on the same BrkRaw loaders and orientation logic used by the CLI.

## Loading data

Use the Load menu to open:

- Study folders
- Zip archives
- PvDatasets packages

The scan and reconstruction lists on the left control what is shown in the
viewport; the first scan is selected when a dataset opens. **Refresh** re-reads
the settings, reopens the current dataset and selects the same scan and
reconstruction again. The **Study Info** button opens the study parameters.

For a shared or external registry file, launch with:

`brkraw viewer --registry /path/to/registry.jsonl`

Before it reads a scan, the viewer estimates the size of the data and asks first
when it is larger than `viewer.cache.memory_limit_mb`; see
[Config](config.md#memory-notice).

## Views

The Viewer tab shows three orthogonal views of the volume: X-Z, X-Y and Z-Y.

- **Click** a view to move the X/Y/Z position (the crosshair).
- **Mouse wheel** over a view steps through the slices of that view.
- **Shift + mouse wheel** zooms, and moves the position to the voxel under the pointer.
- The **X, Y, Z** boxes and sliders set the position directly.
- **Frame** appears when the data has more than one frame, **Slicepack** when the
  scan has more than one slicepack, and **Dim 5, Dim 6, ...** for data with more
  than four dimensions.
- The camera button at the lower right of a view offers to save that view as a
  PNG file in the Convert tab's output folder (the current working folder until
  you set one), with the scan layout name plus the position and plane in the file
  name.

The views are scaled for display between the 1st and 99th percentile of the whole
frame (from at most one million evenly spaced voxels), computed once when the frame is
loaded. All three views and every slice of a frame use the same brightness range, so
moving to another slice does not change how bright a value looks. There is no
window/level control yet (see [Known limitations](#known-limitations)).

## Controls

- **Space**: raw, scanner, or subject RAS
- **Subject type / pose**: manual orientation selection, available when viewing
  subject RAS; **RESET** returns to the values taken from the scan
- **Flip**: per-axis visual flip for quick inspection
- **Crosshair**: toggle the crosshair
- **RGB**: show data whose fourth axis has three channels as colour; disabled for
  other data
- **Zoom**: scale the view from 1x to 4x
- **Value**: the value at the crosshair. For multi-frame data the button opens a
  **Timecourse** window with the voxel's time series; clicking the plot moves to
  that frame, and its capture button saves the plot as PNG.
- **Hook**: when a converter hook is selected for the scan by the rules, **Apply**
  displays the data as that hook returns it, and **Hook Options** edits the hook
  options. This is the converter hook of the scan, not a viewer extension. The options are
  shared with the Convert tab's hook options (kept once per hook): **Apply** in either tab
  changes them for both, and an open Hook Options window in the other tab shows the new
  values. If the options window cannot open (the scan has no hook, the hook cannot be
  loaded, or it has no options), a message says which.

The status line under the views shows space, hook, zoom, RGB, crosshair and slicepack.
Tabs can be detached into their own window and re-attached from the right-click menu on
the tab title. The icon at the right of the main status bar opens the worker log.

## ROI timecourse

The **ROI** buttons above the views (Off, Square, Circle) draw a temporary region of interest
on one view and plot its mean timecourse.

1. Choose **Square** or **Circle**. While a tool is on, clicking a view does not move the
   crosshair.
2. Press in a view and drag: the shape is drawn as you move. A square spans the two corners
   of the drag; a circle has the drag as its diameter.
3. Release the button: the ROI is set on the slice shown in that view, and the Timecourse
   window (open it with the **Value** button) shows the mean of the voxels inside the ROI for
   each frame. The title gives the shape and the voxel count.
4. **Esc** (with the pointer or focus on a view) or choosing **Off** removes the ROI; the plot
   returns to the voxel timecourse. With the tool off, clicking works as before.

Limits: one ROI at a time, in 2D on one slice of one view, never saved. It is cleared when you
change the slice on its axis (scrolling, the sliders, a click in another view), the scan,
reconstruction, hook or hook options, slicepack or flip. Changing the frame does not clear it.
A drag that is only a click sets nothing. Values that are not finite are left out of the mean.
Python access is described under [Viewer hooks](../dev/hooks.md) (provisional).

## Label painting

The **Paint** box next to the ROI buttons paints voxels of a label layer in the three views.
**Paint** / **Erase** and **Brush** are enabled only when an editable label layer is selected (`ui/tabs/viewer/paint_tool.py:79-81`);
**Undo** and **Save** follow their own state; **New label layer** is enabled once a scan is loaded.

1. Press **New label layer**. It adds an empty label layer ("Label 1", "Label 2", ...) on the
   shown scan's grid and selects it. It needs a loaded scan.
2. Choose **Paint** or **Erase** (**Off** is the default). While a tool is on, clicking a view
   does not move the crosshair, and the ROI tool is switched off (one tool at a time; choosing a
   ROI shape switches painting off).
3. Set the **Brush** size (1 to 99): it is the diameter in voxels of a disc, in the slice shown
   in that view. Press in a view and drag. **Paint** writes label 1 and **Erase** writes 0.
   Points outside the volume are ignored.
4. Release the button: the stroke is one undo step.

Undo and cancel:

- **Undo** (or **Ctrl+Z** with focus on a view; a press in a view gives it focus) reverts the last
  finished stroke. The undo history is kept in memory up to 64 MiB; the oldest steps drop first.
- **Esc** (with focus on a view) cancels the stroke in progress and restores the voxels it changed.
  It is not an undo step.

Saving: **Save label...** asks for a file name and writes the layer as `.nii.gz` (the extension is
added when missing) with the layer's affine; the data type is uint8, or uint16 when a label is
above 255. The layer stays editable. A painted layer lives in memory only until you save it; there is
no autosave. When a layer with unsaved edits is removed through the controller, a confirmation
asks first ("... has unsaved edits. Remove it anyway?"); the Viewer tab has no layer list yet, so
there is no remove button.

## Registry

Open the registry window from the toolbar to browse registered datasets, add or
remove entries, and load directly into the viewer. Use **Current session** in the
`+` menu to add whatever is currently loaded; it is disabled until a dataset is
open. The `+` menu can also add a study folder or an archive file.

## Known limitations

- One image volume is shown at a time. The layer core (grids, resampling, layer
  composition, ROI statistics) exists in `brkraw_viewer.core`. The Viewer tab has the
  temporary 2D ROI timecourse above and [Label painting](#label-painting), but no layer list
  yet. Painting always uses label id 1 (no label id choice), and a fast diagonal drag on an
  oblique layer grid can leave gaps (no gap filling there).
- Brightness is one range per frame as described under [Views](#views); there is no
  window/level control yet.
- Extensions cannot draw on the Viewer tab; they add a panel in the Extensions tab.
