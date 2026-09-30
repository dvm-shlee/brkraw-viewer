# Viewer

The default Viewer tab provides **visual QC and orientation checks** without
committing to a conversion. The Viewer application also hosts specialized
visualization panels supplied by optional extensions.

This fits the brkraw philosophy by keeping the viewer lightweight while leaning
on the same BrkRaw loaders and orientation logic used by the CLI.

## Loading data

Use the Load button to open:

- Study folders
- Zip archives
- PvDatasets packages

The selected scan and reconstruction control what is shown in the viewport.

For a shared or external registry file, launch with:

`brkraw viewer --registry /path/to/registry.jsonl`

## Controls

- **Space**: raw, scanner, or subject RAS
- **Subject type / pose**: manual orientation selection when viewing subject RAS
- **Flip**: per-axis visual flip for quick inspection
- **Crosshair**: toggle center crosshair
- **Zoom**: scale the view

## Registry

Open the registry window from the toolbar to browse registered datasets, add or
remove entries, and load directly into the viewer. Use **Current session** in the
`+` menu to add whatever is currently loaded; it is disabled until a dataset is
open.
