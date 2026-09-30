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
The Registry reduces repeated filesystem navigation and lets you re-open the
current session with a single menu action.

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

For development and testing, install in editable mode:

    pip install -e .

---

## Usage

Launch the viewer via the BrkRaw CLI:

    brkraw viewer /path/to/bruker/study

Optional arguments allow opening a specific scan or slice:

    brkraw viewer /path/to/bruker/study \
        --scan 3 \
        --reco 1

Use an external registry file (instead of `~/.brkraw/config.yaml` registry path):

    brkraw viewer /path/to/bruker/study --registry ./shared-registry.jsonl

Write registry entries directly to an external JSONL file:

    brkraw viewer-registry add /path/to/bruker/study -t ./shared-registry

The viewer can also open `.zip` or Paravision-exported `.PvDatasets`
archives using `Load` (folder or archive file).

---

## Update

Recent updates:

- Open folders or archives (`.zip` / `.PvDatasets`)
- Viewer: `Space` (`raw/scanner/subject_ras`), nibabel RAS display, click-to-set `X/Y/Z`, optional crosshair + zoom,
  slicepack/frame sliders only when needed
- Info: rule + spec selection (installed or file), parameter search, lazy Viewer refresh on tab focus
- Registry: add the current session from the `+` menu when a dataset is loaded
- Convert: BrkRaw layout engine, template + suffix defaults from `~/.brkraw/config.yaml`, keys browser (click to add),
  optional config `layout_entries`
- Config: edit `~/.brkraw/config.yaml` in-app; basic focus/icon UX

This update keeps dependencies minimal and preserves compatibility with
the core BrkRaw rule/spec/hook system.

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
