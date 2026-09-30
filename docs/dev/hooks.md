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

The host currently uses `name` (falling back to `tab_title`) and
`build_tab(parent, app)`. The latter must return a Tk widget or `None`.

```python
class MyHook:
    name = "my-extension"
    def build_tab(self, parent, app):
        ...
```

Some existing extensions define `on_dataset_loaded` and `on_scan_selected`,
but the current host does not dispatch these callbacks. Do not rely on them
until host dispatch is implemented and covered by tests.
