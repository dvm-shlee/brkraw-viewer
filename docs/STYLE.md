# Style Notes

This page records conventions for contributing to brkraw-viewer so that
future work follows them consistently.

## Tests

- New test files are named `tests/test_mkj_wiNNNN_<topic>.py`, where `mkj` is
  the company prefix, `NNNN` is the four-digit work item id, and `<topic>` is
  a short snake_case description (for example `test_mkj_wi0008_example.py`).
- Tests written by the old team, named `tests/test_wiNNNN_*`, keep their names.
- This company's earlier tests `tests/test_wi0002_roi_tool.py` and
  `tests/test_wi0005_roi_timecourse.py` were renamed to
  `tests/test_mkj_wi0002_roi_tool.py` and
  `tests/test_mkj_wi0005_roi_timecourse.py` on 2026-10-16.

This rule was accepted by the Director on 2026-10-15.

## Layout

- Tk-free logic lives in `core/`; the thin Tk binding lives in `ui/`. UI
  modules are imported only after the headless early returns, so headless
  runs never import Tk. Example: `core/roi.py` computes masks and
  `ui/roi_tool.py` only wires widgets to it.

Adopted 2026-10-16 (office#7).

## Docstrings

- Module docstrings cite the work item and the contract ids they implement.
  Example: `"""ROI tool core (WI-0002, contract C-ROI-1)."""`

Adopted 2026-10-16 (office#7).

## Errors

- A `ValueError` message names the field, the offending value and the
  expected values. Example:
  `ValueError("mode: got 'blur', expected one of ['mean', 'max']")`.

Adopted 2026-10-16 (office#7).
