# Addons & Params

The **Addons** tab lets you inspect and apply BrkRaw rule/spec assets inside the
viewer. It resolves selected info specs and context maps to show a readable
summary for the active scan/reco, and it surfaces the rule/spec status that was
applied.

The **Params** tab provides a searchable view of raw Bruker parameters plus a
scan summary panel for quick checks.

## Addons

- The **Info**, **Metadata** and **Hook** tabs each have a **Rule** section: the
  rule file and rule name, and a status line. With **Auto** checked the rule is
  selected from the scan; clear it to choose a file (**Browse**) and a name by
  hand. **New** and **Edit** create or edit a rule file in a text window. Each file
  (and each rule category) has one editor window: pressing **Edit** again brings the
  open window forward instead of opening another. A rule file is not open in the
  general text editor and in a rule-category editor at once (the later **Save** would
  undo the other): a message asks you to close the open one first. If **Save** fails, an
  error message names the file and the reason.
- The **Info** and **Metadata** tabs also have a **Spec** section: choose an
  installed spec or a file, optionally follow the spec chosen by the applied rule,
  and press **Apply Spec**. The **Hook** tab lists the available converter hook.
- **Transform** shows the location of the transform file used by the spec, with an
  **Edit** button.
- **Output** shows the resolved result for the active scan/reco; **Save As**
  writes it to a file and **Reset** clears the applied state.
- **Context Map**: open, create, edit and apply a context map. The Convert tab can
  take its layout template from it. Context maps must use the `brkraw` 0.6 syntax;
  maps written for `brkraw` 0.5 are refused.

## Params

- **Scan Info** summarizes the selected scan.
- Search the parameter files (`acqp`, `method`, `reco`, `visu_pars`, or all) with
  **Target** and **Query**; the table lists file, key, type and value, can be
  sorted by clicking a column heading, and **Value Detail** shows the full value
  of the selected row.

Addons and Params always reflect the currently selected scan and reconstruction.
