# Examples

Runnable examples for the viewer's Python API. Each one is a small viewer hook: a package that registers a class under the
`brkraw.viewer.hook` entry point. The hook's `build_tab(parent, app)` receives the controller as `app`; see
[Hooks](../dev/hooks.md) for the full reference. These examples are executed by the test suite.

## ROI API from a hook

The ROI API is the controller's `set_roi`, `clear_roi` and `roi_timecourse`. The worker's answer arrives through the GUI
event loop, so the hook checks again with `parent.after(...)` instead of waiting in a sleep loop.

`try-roi-hook/pyproject.toml`:

```toml
[project]
name = "try-roi-hook"
version = "0.0.1"

[project.entry-points."brkraw.viewer.hook"]
try-roi = "try_roi_hook:TryRoiHook"
```

`try-roi-hook/try_roi_hook.py`:

```python
from tkinter import ttk


class TryRoiHook:
    name = "try-roi"

    def build_tab(self, parent, app):
        frame = ttk.Frame(parent)

        def poll(tries=50):                     # re-check every 200 ms; the GUI keeps running
            res = app.roi_timecourse()          # None until the worker has answered
            if res is not None:
                print(res["n_mask"], res["values"][:5])
            elif tries > 0:
                parent.after(200, poll, tries - 1)
            else:
                print("no answer (no ROI, or it was cleared)")

        def set_rect():
            app.set_roi("rect", (10, 20, 10, 20), axis=2)   # (u0, u1, v0, v1), inclusive pixels
            poll()

        def set_ellipse():
            app.set_roi("ellipse", (15, 15, 5, 5), axis=2)  # (cu, cv, ru, rv)
            poll()

        ttk.Button(frame, text="Set rect ROI", command=set_rect).pack(anchor="w")
        ttk.Button(frame, text="Set ellipse ROI", command=set_ellipse).pack(anchor="w")
        ttk.Button(frame, text="Print timecourse",
                   command=lambda: print(app.roi_timecourse())).pack(anchor="w")
        ttk.Button(frame, text="Clear ROI", command=app.clear_roi).pack(anchor="w")
        return frame
```

Install it into the same environment as the viewer and start the viewer from a terminal to see the printed output:

```bash
pip install ./try-roi-hook
brkraw viewer
```

Open a dataset, select a multi-frame scan in the Viewer tab, pick `try-roi` in the Extensions tab and press the buttons.
The ROI is drawn on the axial view and the Timecourse plot shows its mean.

### Timecourse of a label layer

`roi_timecourse` also reads a label layer. Pass the layer id (as returned by `add_overlay(..., kind="label")`) and the
call returns `{label: values}`, the mean per frame over each label value above 0. It is computed on the main thread from
the data in memory, so it answers at once and `wait` does not apply. `label=` narrows the result to one label value.

```python
layer_id = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")

all_labels = app.roi_timecourse(layer=layer_id)            # {1: [...], 2: [...]}
one_label = app.roi_timecourse(layer=layer_id, label=1)    # {1: [...]}
```

It raises `ValueError` without a loaded scan, for an unknown or non-label layer, or for `label` without `layer`.

## Layers API from a hook

The Layers API (`app.layers_api`) adds, changes and removes overlay layers. It can only be called on the Tk main thread.

### On the main thread

`try-layers-hook/pyproject.toml`:

```toml
[project]
name = "try-layers-hook"
version = "0.0.1"

[project.entry-points."brkraw.viewer.hook"]
try-layers = "try_layers_hook:TryLayersHook"
```

`try-layers-hook/try_layers_hook.py`:

```python
# example: checklist_layers_hook
import numpy as np
from tkinter import ttk


class TryLayersHook:
    name = "try-layers"

    def build_tab(self, parent, app):
        frame = ttk.Frame(parent)
        state = {}

        def add_mask():
            img, affine = app.layers_api.get_image()
            if img.ndim > 3:                       # a multi-frame scan: use the first frame
                img = img[..., 0]
            mask = (img > img.mean()).astype(np.uint8)
            state["id"] = app.layers_api.add_overlay(mask, affine, name="mask", kind="label")
            print([info.name for info in app.layers_api.list_layers()])  # base first, then "mask"

        def half_alpha():
            app.layers_api.set_overlay(state["id"], alpha=0.5)

        def remove():
            app.layers_api.remove_overlay(state.pop("id"))

        ttk.Button(frame, text="Add mask", command=add_mask).pack(anchor="w")
        ttk.Button(frame, text="Half alpha", command=half_alpha).pack(anchor="w")
        ttk.Button(frame, text="Remove", command=remove).pack(anchor="w")
        return frame
```

The buttons add a mask overlay, halve its alpha and remove it again.

### From another thread

A long computation can run on another thread. Calling `app.layers_api` directly from there raises `RuntimeError`, so the
hook reaches it through `app.call_on_main(...)`. Use the same package layout and replace the module with:

```python
# example: checklist_layers_thread
import threading

import numpy as np
from tkinter import ttk


class TryLayersHook:
    name = "try-layers"

    def build_tab(self, parent, app):
        frame = ttk.Frame(parent)
        state = {}
        self.errors = []
        self.threads = []

        def run(job):
            def target():
                try:
                    job()
                except BaseException as exc:      # report it; a thread's error is otherwise lost
                    self.errors.append(exc)
                    print("thread failed:", exc)
            th = threading.Thread(target=target)
            self.threads.append(th)
            th.start()

        def add_mask():
            img, affine = app.call_on_main(lambda: app.layers_api.get_image())
            if img.ndim > 3:
                img = img[..., 0]
            mask = (img > img.mean()).astype(np.uint8)    # the long computation, off the main thread
            state["id"] = app.call_on_main(
                lambda: app.layers_api.add_overlay(mask, affine, name="mask", kind="label"))
            print(app.call_on_main(lambda: [i.name for i in app.layers_api.list_layers()]))

        def half_alpha():
            app.call_on_main(lambda: app.layers_api.set_overlay(state["id"], alpha=0.5))

        def remove():
            app.call_on_main(lambda: app.layers_api.remove_overlay(state.pop("id")))

        ttk.Button(frame, text="Add mask (thread)", command=lambda: run(add_mask)).pack(anchor="w")
        ttk.Button(frame, text="Half alpha (thread)", command=lambda: run(half_alpha)).pack(anchor="w")
        ttk.Button(frame, text="Remove (thread)", command=lambda: run(remove)).pack(anchor="w")
        return frame
```

The buttons do the same three steps as above, each on its own thread.
