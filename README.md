<h1 align="left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brkraw-viewer-logo-dark.svg">
    <img alt="BrkRaw Viewer" src="docs/assets/brkraw-viewer-logo-light.svg" width="410">
  </picture>
</h1>

BrkRaw Viewer is an interactive dataset viewer implemented as a
separate CLI plugin for the `brkraw` command.

The viewer is intentionally maintained outside the BrkRaw core to
enable independent development and community contributions around
user-facing interfaces.

---

## Scope and intent

BrkRaw Viewer is the application plugin responsible for visualization of
Bruker Paravision datasets across the BrkRaw ecosystem. Its default interface
focuses on quick exploration and validation; specialized visualization is
provided by optional Viewer hooks.

The goal is to provide practical, researcher-focused features that are
useful in everyday workflows, such as quick dataset triage, metadata
checks, and lightweight visual QC.

Typical use cases include:

- Browsing studies, scans, and reconstructions
- Verifying scan and reconstruction IDs
- Inspecting acquisition metadata before conversion
- Lightweight visual sanity checks

The Convert tab invokes BrkRaw conversion APIs. The conversion engine and
reproducible workflow logic are owned by the BrkRaw core and its converter
hooks.

---

## Why these features exist

**Viewer**
The Viewer tab makes it easy to confirm the right scan and orientation before
running a larger workflow.

**Registry**
The Registry reduces repeated filesystem navigation. It keeps a list of
datasets (a JSONL file) that you can open again from one window, and you can
add the dataset that is currently open from its `+` menu.

**Extensions/hooks**
Extensions allow modality-specific panels (MRS, BIDS, etc.) to live outside the
core viewer so the default install stays lightweight.

---

## Design goal: shared extensibility

brkraw-viewer keeps the BrkRaw design philosophy: extend the ecosystem
without changing core logic. The viewer uses the same rules/spec/layout
system as the CLI and Python API, and it exposes UI extensions via the
`brkraw.viewer.hook` entry point so new tabs can be added with standalone
packages. Viewer hooks can coexist with converter hooks and CLI hooks,
so modality-specific logic can flow from conversion into UI without
patching the viewer itself.

---

## UI direction

The default viewer targets a **tkinter-based** implementation.

This choice is intentional: we want a lightweight tool that can be
used directly on scanner consoles or constrained environments with
minimal dependencies.

More modern GUI frameworks are welcome, but should be developed as
separate CLI extensions to keep the default viewer small and easy to
install.

---

## Viewer hooks

Viewer extensions are implemented as hooks discovered through
`brkraw.viewer.hook`. Each hook can provide a tab in the Extensions panel,
enabling feature panels to live outside the Viewer host while staying
compatible with BrkRaw rules, specs, and converter hooks. The current host
calls `build_tab` when a panel is selected; see `docs/dev/hooks.md` for the
implemented interface and entry point setup.

---

## Installation

The viewer needs Python 3.9 or newer and `brkraw` 0.6.0rc2 or newer (the
`brkraw` 0.6 API; older `brkraw` releases are not supported by this version).
For development and testing, install in editable mode:

    pip install -e .

The repository includes a `uv.lock`; `uv sync --locked --extra dev` creates a
development environment and `uv run --locked --extra dev pytest` runs the tests.

---

## Usage

Launch the viewer via the BrkRaw CLI:

    brkraw viewer /path/to/bruker/study

Optional arguments select the initial scan and reconstruction, or an info spec
for the Addons tab:

    brkraw viewer /path/to/bruker/study \
        --scan 3 \
        --reco 1 \
        --info-spec ./my-info-spec.yaml

When no path, scan or reco is given, the environment variables `BRKRAW_PATH`,
`BRKRAW_SCAN_ID` and `BRKRAW_RECO_ID` are used if they are set.

Use an external registry file (instead of `~/.brkraw/config.yaml` registry path):

    brkraw viewer /path/to/bruker/study --registry ./shared-registry.jsonl

Write registry entries directly to an external JSONL file:

    brkraw viewer-registry add /path/to/bruker/study -t ./shared-registry

`brkraw viewer-registry` also accepts `init`, `rm`, `scan` (find datasets under a
folder), `list` and `clear`. The environment variable
`BRKRAW_VIEWER_REGISTRY_PATH` overrides the registry file as well.

The viewer can also open `.zip` or Paravision-exported `.PvDatasets`
archives using `Load` (folder or archive file).

---

## Current features

- Load a study folder, a `.zip` archive or a Paravision-exported `.PvDatasets`
  archive; browse scans and reconstructions in the left list; open the Study
  Info window.
- Viewer tab: three orthogonal views (X-Z, X-Y, Z-Y) with click-to-set position,
  mouse-wheel slicing, `Shift`+wheel zoom (1x to 4x), optional crosshair, PNG
  capture, `Space` selection (`raw`, `scanner`, `subject_ras`) with subject
  type/pose and per-axis flips, frame, slicepack and extra-dimension sliders
  that appear only when the data has them, an RGB mode for three-channel data,
  a voxel value box that opens a timecourse plot for multi-frame data, and an
  `Apply` switch for the converter hook that the rules select for the scan.
- Addons tab: rule, spec and context map selection (installed or from a file)
  for info, metadata and converter hook, with resolved output.
- Params tab: summary of the selected scan and a searchable table of `acqp`,
  `method`, `reco` and `visu_pars` parameters.
- Convert tab: NIfTI export with the BrkRaw layout engine (GUI template, context
  map or config template), a layout key browser, optional JSON/YAML metadata
  sidecar, converter hook options, and an option to reuse the Viewer
  orientation. Work runs in a separate worker process.
- Registry window: add the current session, a folder or an archive; remove
  entries; open an entry.
- Extensions tab: pick a viewer hook found through `brkraw.viewer.hook`.
- Config tab: edit, back up and reset the BrkRaw `config.yaml` in the app.
- Memory notice: before the Viewer tab loads a scan, the viewer estimates the
  size of its `2dseq` from `visu_pars` and asks first when it is larger than
  `viewer.cache.memory_limit_mb` (default 600 MB). See `docs/user/config.md`.

## Known limitations

- The Viewer tab shows a single image volume. Layer composition, ROI statistics
  and label editing are planned and are not available in this version.
- Brightness is scaled for each displayed slice (1st to 99th percentile of that
  slice), so brightness changes when you move through slices, and there is no
  window/level control.
- The worker process keeps the whole `2dseq` of the selected scan in memory so
  that changing the frame is fast. It also keeps the loader of every dataset
  opened earlier until the viewer is closed.
- Viewer hooks add a panel in the Extensions tab; there is no supported way for a
  hook to draw on the Viewer tab (see `docs/dev/hooks.md`).

---

## Contributing

We welcome contributions related to:

- New viewer hooks that add modality-specific panels or workflows
- Alternative UI implementations delivered as separate CLI extensions
- fMRI/MRS/BIDS-focused visualization or QC helpers built on hooks
- Multi-dataset session management and registry enhancements
- Performance and memory improvements for large datasets

Contributions should prefer designs where new hooks extend the viewer
implicitly through shared BrkRaw abstractions, and where richer UIs are
provided as optional CLI extensions rather than increasing the default
dependency footprint.

If you are interested in contributing, please start a discussion or
open an issue describing your use case and goals.
