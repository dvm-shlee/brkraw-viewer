# Try the new features / 새 기능 체험하기

KO: 이 문서는 mokoji-org/brkraw-viewer `main` 브랜치를 설치해서 새 기능(ROI 도구, 시계열 플롯,
Python API, STYLE.md)을 직접 확인하는 순서입니다. 각 항목은 "절차 / 기대 결과 / 실패 시 확인할 곳" 순서입니다.

EN: This page walks through installing mokoji-org/brkraw-viewer `main` and trying each new
feature (ROI tool, timecourse plot, Python API, STYLE.md). Each item lists steps, expected
result and where to look on failure.

Data path / 데이터 경로: `<YOUR_DATA>` (replace with a Bruker study folder, zip or PvDatasets
package that has a multi-frame scan, e.g. fMRI / 시간 축이 있는 스캔).

## 1. Install / 설치

KO: 새 가상환경에서 `main`을 설치합니다.
EN: Install `main` into a fresh virtual environment.

```bash
python -m venv try-viewer && source try-viewer/bin/activate
pip install "git+https://github.com/mokoji-org/brkraw-viewer@main"
```

- Expected / 기대 결과: `pip show brkraw-viewer` prints the package; `brkraw --help` lists `viewer`.
- On failure / 실패 시: check the pip error (network, git access, a Python version below the
  one in `pyproject.toml`); `brkraw` missing means the venv is not activated. A Python without
  Tk cannot open the window (`python -c "import tkinter"`).

## 2. Launch / 실행

```bash
brkraw viewer
```

- Steps / 절차: use the **Load** menu to open `<YOUR_DATA>`; the first scan is selected
  automatically (첫 스캔이 자동 선택됩니다).
- Expected / 기대 결과: the views (axial, coronal, sagittal slices) appear in the Viewer tab.
- On failure / 실패 시: the icon at the right of the main status bar opens the worker log;
  see also `docs/user/viewer.md` ("Loading data").

## 3. ROI tool: Off / Square / Circle

KO: 뷰 위쪽의 **ROI** 버튼(Off, Square, Circle)으로 도구를 고릅니다.
EN: Pick the tool with the **ROI** buttons above the views.

1. Click **Off** (default): clicking a view moves the crosshair as before.
2. Click **Square**: clicking a view no longer moves the crosshair.
3. Click **Circle**: same; the new choice replaces the previous one.

- Expected / 기대 결과: with Square or Circle on, the crosshair stays put; with Off it moves.
- On failure / 실패 시: `src/brkraw_viewer/core/roi.py` (`ROI_TOOLS = ("off", "square", "circle")`),
  the Viewer tab code under `src/brkraw_viewer/ui/tabs/viewer/`; test
  `tests/test_mkj_wi0002_roi_tool.py`.

## 4. Drag to draw an ROI / 드래그로 ROI 그리기

1. Choose **Square**, press in a view, drag, then release.
2. Choose **Circle** and repeat. The drag is the circle's diameter; a square spans the two
   corners of the drag.
3. Press **Esc** (pointer over a view) or choose **Off**.
4. Click without dragging.

- Expected / 기대 결과: the shape is drawn while you drag and stays on the slice after release;
  one ROI at a time. Esc/Off removes it. A plain click sets nothing. Scrolling to another slice
  on that axis, or changing scan/reconstruction, clears it; changing the frame does not.
- On failure / 실패 시: `src/brkraw_viewer/ui/tabs/viewer/right_panel.py` (drag and Esc binds),
  `core/roi.py` (`drag_geometry`, `RoiDrag`).

## 5. Timecourse plot / 시계열 플롯

1. With a ROI set, click the **Value** button to open the Timecourse window.
2. Remove the ROI (Esc) and look at the plot again.

- Expected / 기대 결과: the window shows the mean of the finite voxels in the ROI per frame; the
  title gives the shape and voxel count. After removal it returns to the single-voxel timecourse.
- On failure / 실패 시: worker log (status bar icon); `app/workers/convert_worker.py`
  (`_roi_timecourse`); test `tests/test_mkj_wi0005_roi_timecourse.py`. A single-frame scan has
  no meaningful timecourse.

## 6. Python API (provisional / 잠정 API)

KO: 컨트롤러 메서드 `set_roi`, `clear_roi`, `roi_timecourse` (`app/controller/viewer.py`).
`<YOUR_DATA>`를 불러온 `ViewerController` 인스턴스 `ctl`이 있는 상태에서 실행합니다.
EN: Run with a `ViewerController` instance `ctl` that has `<YOUR_DATA>` loaded.

```python
ctl.set_roi("rect", (10, 20, 10, 20), axis=2)   # (u0, u1, v0, v1), inclusive pixels
res = ctl.roi_timecourse()                      # None while the worker is still computing
print(res["n_mask"], res["values"][:5])
ctl.set_roi("ellipse", (15, 15, 5, 5), axis=2)  # (cu, cv, ru, rv)
ctl.clear_roi()
```

- Expected / 기대 결과: `roi_timecourse()` returns a dict with `values`, `n_mask`,
  `n_per_frame`, `shape`, `axis`, `index`; it returns `None` without a ROI or before the
  worker answers (call again after a moment).
- On failure / 실패 시: see the docstring of `set_roi` in `app/controller/viewer.py`; error
  messages follow the STYLE.md "Errors" rule (field, value, expected values).

## 7. STYLE.md

KO: `docs/STYLE.md`를 열어 규칙을 확인합니다. EN: Open `docs/STYLE.md`.

- Expected / 기대 결과: sections Tests (`tests/test_mkj_wiNNNN_<topic>.py`), Layout (Tk-free
  logic in `core/`, thin Tk binding in `ui/`), Docstrings (cite WI and contract ids), Errors.
- On failure / 실패 시: if the file is missing, you are not on `main`; reinstall from `main`.
