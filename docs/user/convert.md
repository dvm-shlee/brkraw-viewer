# Convert

The Convert tab exists to **bridge inspection and export**: after confirming the
right scan in the Viewer, you can write a quick NIfTI export using the same
layout rules as the brkraw CLI. It converts the scan and reconstruction that are
selected in the left lists. The work runs in the worker process, and a message
reports how many files were saved, or the error.

## Key options

- **Layout source**: where the output name comes from. **GUI template** uses the
  template typed in the **Template** box, **Context map** uses the layout template
  of the context map applied in the Addons tab, and **Config** uses the layout
  settings of `config.yaml`. With **Auto** checked, the viewer uses the context map
  when it provides a layout template and the config layout otherwise.
- **Rule / Info spec / Metadata spec / Context map**: the assets currently applied
  in the Addons tab (read only here).
- **Keys**: the keys that can be used in a template; double-click one or select it
  and press **+** to add it to the template, **-** to remove it.
- **Slicepack suffix**: suffix template for scans with several slicepacks (from
  the BrkRaw settings, read only here).
- **Output folder**: where converted data is written. Files are written as
  `.nii.gz`.
- **Metadata Sidecar**: also write a JSON or YAML sidecar for each output, using
  the metadata spec applied in the Addons tab.
- **Use Viewer orientation**: apply the Space, subject type/pose and flips that are
  set in the Viewer tab; when it is off, the Space, Subject Type, Pose and Flip
  X/Y/Z controls here are used.
- **Converter hook**: when a hook is selected for the scan by the rules, a checkbox
  switches it on for the conversion and **Edit Options** edits its options.

**Preview Outputs** shows the output paths before conversion runs; **Convert** runs it.
The memory notice of the Viewer tab does not apply to Convert.
