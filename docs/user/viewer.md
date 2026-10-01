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

Each view is scaled for display between the 1st and 99th percentile of the slice
that is shown. The brightness range is therefore recomputed whenever you move to
another slice, and there is no window/level control (see
[Known limitations](#known-limitations)).

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
  changes them for both.

The status line under the views shows space, hook, zoom, RGB, crosshair and slicepack.
Tabs can be detached into their own window and re-attached from the right-click menu on
the tab title. The icon at the right of the main status bar opens the worker log.

## Registry

Open the registry window from the toolbar to browse registered datasets, add or
remove entries, and load directly into the viewer. Use **Current session** in the
`+` menu to add whatever is currently loaded; it is disabled until a dataset is
open. The `+` menu can also add a study folder or an archive file.

## Known limitations

- One image volume is shown at a time. Layer composition, ROI statistics and label
  editing are planned and are not available.
- Brightness is scaled per slice as described under [Views](#views).
- Extensions cannot draw on the Viewer tab; they add a panel in the Extensions tab.
