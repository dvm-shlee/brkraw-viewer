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
no real dataset); it deselects the real-data tests (marker `realdata`; see the
[rule](../STYLE.md#tests)). The GUI smoke test runs only with `BRKRAW_VIEWER_SMOKE=1` and a
display, and the installed-ecosystem test only with `BRKRAW_ECOSYSTEM_CONTRACT=1`.

### Running the GUI tests

The Tk tests are skipped unless `BRKRAW_VIEWER_SMOKE=1` is set and a display exists
(`DISPLAY` or `WAYLAND_DISPLAY`).

- With a display: `BRKRAW_VIEWER_SMOKE=1 uv run --locked --extra dev pytest tests/test_checklist_gui.py`.
- Headless: wrap the same command in `xvfb-run -a ...`, or start `Xvfb -displayfd <fd>` yourself
  and export the printed display number as `DISPLAY`.
- `tests/test_checklist_gui.py` drives the real Tk windows (checklist sections,
  including the ROI tool box and zoom).
- `tests/test_roi_tool_box_gui.py` drives the ROI tool box (placement, modes, mouse buttons,
  colour). To write the screenshot of the user guide, run it under Xvfb with
  `BRKRAW_VIEWER_SHOT=docs/user/img/roi-tool-box.png`.
- With the Tk 9 wheel, send `<MouseWheel>` events (not Button-4/5) when simulating scrolling.
- Always destroy the Tk root at the end of a test (fixture with try/finally), or later tests
  hang or fail on a leaked root.
- Run these through the scheduler, not in an interactive session.

### Running the real-data tests

Two test files run on a real Bruker dataset in a real Tk window:
`tests/test_realdata_gui.py` (ROI tool and timecourse, scan 11) and
`tests/test_realdata_layers_gui.py` (layers API, scan 11).

- Dataset: the public ParaVision 5.1 in vivo rat BOLD-EPI dataset `PV5.1/UNC_PV5.1_BOLD-EPI_TurboRARE.zip`
  from <https://github.com/BrkRaw/brkraw-dataset> (Git LFS object, CC BY 4.0); the tests name it
  `BrkRaw/brkraw-dataset PV5.1 BOLD-EPI` (`tests/test_realdata_gui.py:3`) and the source is
  listed in [Public Bruker 4D datasets](../references/public-bruker-4d-datasets.md). Unpack the zip first.
- `BRKRAW_VIEWER_REALDATA` must be the path of the unpacked PV5.1 BOLD-EPI study folder; it must exist
  (`tests/test_realdata_gui.py:44-50`). The layers test reuses this check
  (`tests/test_realdata_layers_gui.py:46`).
- `BRKRAW_VIEWER_SMOKE=1` and a display (`DISPLAY` or `WAYLAND_DISPLAY`, except on Windows and macOS) are
  also required (`tests/test_realdata_gui.py:165-171`,
  `tests/test_realdata_layers_gui.py:46-52`).
- With a display: `BRKRAW_VIEWER_REALDATA=<study folder> BRKRAW_VIEWER_SMOKE=1 uv run --locked --extra dev pytest -m realdata tests/test_realdata_gui.py tests/test_realdata_layers_gui.py`.
- Headless: `BRKRAW_VIEWER_REALDATA=<study folder> BRKRAW_VIEWER_SMOKE=1 xvfb-run -a uv run --locked --extra dev pytest -m realdata tests/test_realdata_gui.py tests/test_realdata_layers_gui.py`.
- These tests carry the `realdata` marker; see the rule in [STYLE.md](../STYLE.md#tests).

### Manual look: ROI tool

The Tk parts of the ROI tool are covered by the GUI checklist test above
(`tests/test_checklist_gui.py`); the drag logic, plane mapping and controller wiring
also have synthetic tests (`tests/test_roi_tool.py`). Check by hand with a 4D scan:

- The ROI tool box (Crosshair / Selection / Drawing) sits in the top row; Crosshair by default,
  and clicking a view moves the crosshair.
- In Selection (Square or Circle), a click does not move the crosshair; dragging draws the outline in
  that view only, and it follows the pointer; zoom (Shift + wheel) keeps it on the same pixels.
- Release: the mode returns to Crosshair, outline stays, the Timecourse window shows "ROI mean (shape, N voxels)".
- Scroll the slice of that view: outline and ROI disappear. Other views keep their slice.
- Esc over a view removes the outline and restores the voxel timecourse; choosing Crosshair keeps it.
- Check all three views (X-Z, X-Y, Z-Y): the voxels counted match the outlined pixels.
