# Extensions

Extensions exist so the default viewer can stay lightweight while specialized
workflows (MRS, BIDS, etc.) live in their own packages. This keeps the GUI
small for scanner environments but still lets teams build richer interfaces.

BrkRaw Viewer supports optional extensions via the `brkraw.viewer.hook` entry
point. An extension adds a panel to the **Extensions** tab, and it can work
alongside converter hooks or CLI hooks because they share the same rule/spec
system.

## Installing extensions

Install the extension package in the same environment as `brkraw-viewer`:

```bash
pip install <extension-package>
```

In the BrkRaw family, `brkraw-mrs`, `brkraw-dti` and `brkraw-bids` declare a
`brkraw.viewer.hook` entry point in their `pyproject.toml`.

## Selecting an extension

Extensions are selected manually in the **Extensions** tab. The default value
is **None**, which keeps the core viewer active. The tab shows "No extensions
available." when no hook is installed, and the extension you selected last is
selected again when the tab is rebuilt in the same session.

An extension panel has its own widgets inside the Extensions tab. It does not draw
on the Viewer tab; see [Viewer Hooks](../dev/hooks.md) for what the host provides.
