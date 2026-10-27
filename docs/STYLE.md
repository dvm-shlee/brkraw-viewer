# Style Notes

This page records conventions for contributing to brkraw-viewer so that
future work follows them consistently.

## Tests

- New test files are named `tests/test_<topic>.py` (a short snake_case topic).
- Tests that need the real dataset carry the `realdata` marker. The default run
  deselects them (`-m "not realdata"` in `addopts`); deselection by marker is
  not a skip: they never skip, and an explicit `-m realdata` run without the
  data fails. Every pre-push or release sweep runs `-m realdata` with the data
  variables set and reports how many ran.

## Layout

- Tk-free logic lives in `core/`; the thin Tk binding lives in `ui/`. UI
  modules are imported only after the headless early returns, so headless
  runs never import Tk. Example: `core/roi.py` computes masks and
  `ui/roi_tool.py` only wires widgets to it.

## Docstrings

- Module docstrings say what the module does; no internal ticket or decision ids.
  Example: `"""ROI masks and statistics on one display slice."""`

## Errors

- A `ValueError` message names the field, the offending value and the
  expected values. Example:
  `ValueError("mode: got 'blur', expected one of ['mean', 'max']")`.

## GUI code and tests

- Every Tk variable and `PhotoImage` gets an explicit `master` (its own
  widget or root); never rely on the default root. Example:
  `tk.StringVar(master=self.frame, value="")`.
- GUI tests destroy their Tk root in teardown (a fixture with `try/finally`
  or `yield`), so the next test cannot bind to a dead root. Example:
  `root = tk.Tk(); yield root; root.destroy()`.
- Mouse-wheel handling binds `<MouseWheel>`: Tk 9 delivers wheel scrolls
  there; `Button-4`/`Button-5` only on old X11 Tk. Example:
  `canvas.bind("<MouseWheel>", self._on_wheel)`.
- GUI tests run in a real Tk window under a virtual display (Xvfb) with
  `BRKRAW_VIEWER_SMOKE=1`; see [Running the GUI tests](dev/gui.md).
  Example: `BRKRAW_VIEWER_SMOKE=1 xvfb-run -a <test command>`.
