# Release v0.5.0b1 (beta)

Date: 2026-10-23
Changes since 0.4.2

This is a beta for the lab's own testing (no tag, no GitHub release).

New features

- Layers: a new RGB layer kind for three-channel data (RGB layer in `brkraw_viewer.core.layers`, composited in `brkraw_viewer.core.composite`).
- Label painter: `LabelEditor` in `brkraw_viewer.core.painter` with brush strokes, undo and erase, a paint tool UI (undo, erase, Esc to cancel a stroke) and NIfTI save of the label layer (`save_label_nifti`).
- Temporary ROI tool: square and circle ROI drawn by dragging on the slice, with a timecourse plot (ROI mean per frame from the worker's held data); controller methods `set_roi`, `clear_roi` and `roi_timecourse`.
- `roi_timecourse(wait=True, timeout=...)` on `ViewerController` blocks (keeping the Tk event loop running) until the answer for the current ROI is in, and raises `ValueError` without a ROI or `TimeoutError` after the timeout.
- Layers API: `app.layers_api` (`brkraw_viewer.app.controller.layers_api.LayersAPI`) with `list_layers`, `get_image`, `add_overlay`, `set_overlay`, `get_overlay_array` and `remove_overlay`; `get_image` and `get_overlay_array` accept `copy=False` to return the stored array without a copy (`brkraw_viewer.core.layer_handle`).
- `app.call_on_main(fn, timeout)` on `ViewerController` runs a callable on the main (Tk) thread from a worker thread and returns its result.
- Provisional: the ROI API (`set_roi`, `clear_roi`, `roi_timecourse`) and the layers API are provisional and may change until they are tested in real use.

Fixes

- `brkraw_viewer.ui`: Tk variables and `PhotoImage`s are bound to their own Tk root; no implicit root is created, and hook option variables are bound to their window.
- Window icon is loaded from the package assets (`brkraw_viewer/assets`).
- Error messages in `brkraw_viewer.core` (RGB layer, Layer alpha, painter) follow the form `<field>: got ..., expected ...`.
- `ViewerController.call_on_main`: run-or-cancel is decided under the main lock, which fixes an admission race with window close.

Docs

- `docs/user/try-new-features.md`: checklist for the new features, including section 9 (Layers API, provisional) with example GUI tests; a real-data layers GUI test (`tests/test_mkj_wi0089_realdata_layers_gui.py`) covers the layers API.
- `docs/dev/hooks.md`: ROI timecourse, layers API (provisional) and `call_on_main` entries.
- `STYLE.md`: test file naming, layout, docstring, error style and GUI rules.
- `mkdocs build --strict` is clean (all pages are in the nav).

# Release v0.4.2

Date: 2026-02-02
Changes since 0.4.1

- chore: prepare release v0.4.2 (e33682c)
- Track docs/dev in gitignore (a40303b)
- Revamp viewer registry CLI (f5c20e0)
- refactor(ui): comprehensive rearrangement of viewer tab and registry window (ad7b19f)
- fix(ui): apply default sorting on registry window open (fa31212)
- feat(ui): center viewer controls and enforce window minsize (bcda4c4)
- feat(ui): enforce fixed widths for viewer top panel sections (11b6084)
- feat(ui): reduce widget widths for compact layout (741e270)
- feat(ui): reduce orientation section width to 2/3 (30bb30d)
- feat(ui): align space row and fix orientation width (141b987)
- feat(ui): align orientation controls and enforce min width (4fec866)
- feat(ui): refine viewer controls layout (81354ec)
- feat(ui): display 'Disabled' in viewer hook section when unavailable (65b3de2)
- feat(ui): rearrange viewer top panel layout (bb65cc4)
- feat(ui): group viewer orientation controls in a section (0989981)
- chore: ignore dev directory and remove from tracking (33b6770)
- feat(controller): improve parameter search and formatting (f3964d4)
- feat(ui): implement params sorting and fix layout issues (f8573f0)
- feat: add manual release dispatch inputs (16a4604)
- fix: make release workflow robust to multiline messages (5fa4dea)
