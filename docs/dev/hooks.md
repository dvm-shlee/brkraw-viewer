# Viewer Hooks

Viewer hooks are discovered through the `brkraw.viewer.hook` entry point group.
Each hook can provide a tab UI. The current host only calls `build_tab` when
the extension is selected.

Hooks keep modality-specific visualization in extension packages while the
Viewer owns common display behavior. Viewer hooks can coexist with
converter hooks and CLI hooks, so UI features can build on the same conversion
logic without patching the viewer itself.

## Entry point

Add an entry point in your `pyproject.toml`:

```toml
[project.entry-points."brkraw.viewer.hook"]
brkraw-mrs = "brkraw_mrs.viewer_hook:MRSViewerHook"
```

## Hook interface

The host currently uses `name` (falling back to `tab_title`, then `"Extension"`)
and `build_tab(parent, app)`. `build_tab` must return a Tk widget or `None`;
any other return value is refused with a warning. An exception raised by
`build_tab` is logged as a warning and does not stop the viewer, and an entry
point that fails to import is skipped with a warning. An entry point that is a
class is instantiated without arguments; if that raises, the host logs a warning
with the hook name and the reason, skips that hook only, and still loads the others
and the Extensions tab. Other attributes, for example `priority`,
are not read, and hooks are listed in the Extensions tab sorted by name.

```python
class MyHook:
    name = "my-extension"
    def build_tab(self, parent, app):
        ...
```

`app` is the viewer's controller object. These members exist today and are used
by extensions; they are not a versioned API:

- `app.on_viewer_jump(x, y, z)`: move the Viewer tab position
- `app.on_viewer_space_change(value)` and `app.register_viewer_space_listener(cb)`:
  change or follow the Space selection
- `app.state.dataset.selected_scan_id` and `app.state.dataset.selected_reco_id`:
  the current selection
- `app.dataset.get_scan(scan_id)`: the BrkRaw scan object

Hooks are loaded when the Extensions tab is built, and the panel is built again
when you select it from the list or re-attach the tab. The selection is
remembered for the session. A hook gets no call when a dataset or scan changes:
read the state when you build the panel, or follow Space through
`register_viewer_space_listener`. There is no supported way to draw on the Viewer
tab; the Viewer tab's **Hook** box applies the scan's *converter* hook, which is
a different mechanism.

Some existing extensions define `on_dataset_loaded`, `on_scan_selected` and
`can_handle`, but the current host does not call them. Do not rely on them
until host dispatch is implemented and covered by tests.
