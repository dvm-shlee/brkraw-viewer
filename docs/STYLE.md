# Style Notes

This page records conventions for contributing to brkraw-viewer so that
future work follows them consistently.

## Tests

- New test files are named `tests/test_mkj_wiNNNN_<topic>.py`, where `mkj` is
  the company prefix, `NNNN` is the four-digit work item id, and `<topic>` is
  a short snake_case description (for example `test_mkj_wi0008_example.py`).
- Tests written by the old team, named `tests/test_wiNNNN_*`, keep their names.
- This company's earlier tests `tests/test_wi0002_roi_tool.py` and
  `tests/test_wi0005_roi_timecourse.py` are renamed to the new pattern when
  they are next changed.

This rule was accepted by the Director on 2026-10-15.
