# 새 기능 체험하기 / Try the new features

KO: 이 문서는 mokoji-org/brkraw-viewer `main` 브랜치를 설치해 새 기능(ROI 도구, 시계열 플롯, Python API, STYLE.md)을 직접 확인하는 순서입니다. 각 항목은 "절차 / 기대 결과 / 실패 시 확인할 곳" 순서입니다.

EN: This page walks through installing mokoji-org/brkraw-viewer `main` and trying each new feature (ROI tool, timecourse plot, Python API, STYLE.md). Each item lists steps, expected result and where to look on failure.

데이터 경로 / Data path: `<YOUR_DATA>` (KO: 시간 축이 있는 스캔, 예: fMRI, 이 들어 있는 Bruker 스터디 폴더, zip 또는 PvDatasets 패키지로 바꾸세요. EN: replace with a Bruker study folder, zip or PvDatasets package that has a multi-frame scan.)

## 1. 설치 / Install

KO: 새 가상환경에 `main`을 설치합니다. `main`은 아직 PyPI에 없는 `brkraw>=0.6.1rc2`를 요구하므로 GitHub 태그를 먼저 설치합니다.
EN: Install `main` into a fresh virtual environment. `main` pins `brkraw>=0.6.1rc2`, which is not on PyPI yet, so install that tag from GitHub first (otherwise pip fails with "No matching distribution found for brkraw").

```bash
python -m venv try-viewer && source try-viewer/bin/activate
pip install "git+https://github.com/BrkRaw/brkraw@0.6.1rc2"
pip install "git+https://github.com/mokoji-org/brkraw-viewer@main"
```

- 기대 결과 / Expected: KO: `pip show brkraw-viewer`가 패키지를 보여주고 `brkraw --help`에 `viewer`가 나옵니다. EN: `pip show brkraw-viewer` prints the package; `brkraw --help` lists `viewer`.
- 실패 시 / On failure: KO: pip 오류(`brkraw` 0.6.1rc2를 못 찾으면 위 첫 `pip install` 줄을 먼저 실행; 네트워크, git 접근, `pyproject.toml`보다 낮은 Python 버전)를 확인하세요. `brkraw`가 없으면 가상환경이 활성화되지 않은 것입니다. Tk가 없는 Python은 창을 열 수 없습니다(`python -c "import tkinter"`). EN: check the pip error ("No matching distribution found for brkraw" means run the first `pip install` line above; network, git access, Python older than `pyproject.toml` requires); a missing `brkraw` means the venv is not activated; a Python without Tk cannot open the window.

## 2. 실행 / Launch

```bash
brkraw viewer
```

- 절차 / Steps: KO: **Load** 메뉴에서 `<YOUR_DATA>`를 엽니다. 첫 스캔이 자동 선택됩니다. EN: open `<YOUR_DATA>` from the **Load** menu; the first scan is selected automatically.
- 기대 결과 / Expected: KO: Viewer 탭에 axial, coronal, sagittal 뷰가 나타납니다. EN: the axial, coronal and sagittal views appear in the Viewer tab.
- 실패 시 / On failure: KO: 메인 상태 표시줄 오른쪽 아이콘으로 worker 로그를 열고, `docs/user/viewer.md`("Loading data")를 보세요. EN: open the worker log from the icon at the right of the main status bar; see `docs/user/viewer.md` ("Loading data").

## 3. ROI 도구 (Off / Square / Circle) / ROI tool (Off / Square / Circle)

KO: 뷰 위쪽의 **ROI** 버튼(Off, Square, Circle)으로 도구를 고릅니다.
EN: Pick the tool with the **ROI** buttons above the views.

1. KO: **Off**(기본)를 누르고 뷰를 클릭하면 십자선이 움직입니다. EN: **Off** (default): clicking a view moves the crosshair.
2. KO: **Square**를 누르고 뷰를 클릭하면 십자선이 움직이지 않습니다. EN: **Square**: clicking a view no longer moves the crosshair.
3. KO: **Circle**도 같고, 새 선택이 이전 선택을 대체합니다. EN: **Circle**: same; the new choice replaces the previous one.

- 기대 결과 / Expected: KO: Square/Circle에서는 십자선이 고정되고 Off에서는 움직입니다. EN: with Square or Circle the crosshair stays put; with Off it moves.
- 실패 시 / On failure: KO: 도구 목록은 `src/brkraw_viewer/core/roi.py`(`ROI_TOOLS = ("off", "square", "circle")`), 버튼은 `src/brkraw_viewer/ui/tabs/viewer/`, 테스트는 `tests/test_mkj_wi0002_roi_tool.py`를 보세요. EN: tool list in `src/brkraw_viewer/core/roi.py` (`ROI_TOOLS`), buttons in `src/brkraw_viewer/ui/tabs/viewer/`, test in `tests/test_mkj_wi0002_roi_tool.py`.

## 4. 드래그로 ROI 그리기 / Drag to draw an ROI

1. KO: **Square**를 고르고 뷰에서 누른 채 드래그한 뒤 놓습니다. EN: choose **Square**, press in a view, drag, release.
2. KO: **Circle**로 반복합니다. 드래그가 원의 지름이고, 사각형은 드래그의 두 모서리를 잇습니다. EN: repeat with **Circle**; the drag is the circle's diameter, a square spans the two corners.
3. KO: 뷰 위에서 **Esc**를 누르거나 **Off**를 고릅니다. EN: press **Esc** (pointer over a view) or choose **Off**.
4. KO: 드래그 없이 클릭합니다. EN: click without dragging.

- 기대 결과 / Expected: KO: 드래그 중 도형이 그려지고 놓은 뒤에도 슬라이스에 남습니다. ROI는 한 번에 하나, Esc/Off로 지워지고, 단순 클릭은 아무것도 설정하지 않습니다. 그 축의 다른 슬라이스로 스크롤하거나 스캔/재구성을 바꾸면 지워지며, 프레임 변경은 지우지 않습니다. EN: the shape is drawn while dragging and stays after release; one ROI at a time; Esc/Off removes it; a plain click sets nothing; scrolling to another slice on that axis or changing scan/reconstruction clears it, changing the frame does not.
- 실패 시 / On failure: KO: 드래그와 Esc 키 바인딩은 `src/brkraw_viewer/ui/tabs/viewer/right_panel.py`, 도형 계산은 `src/brkraw_viewer/core/roi.py`(`drag_geometry`, `RoiDrag`)를 보세요. EN: drag and Esc key bindings in `src/brkraw_viewer/ui/tabs/viewer/right_panel.py`; shape geometry in `src/brkraw_viewer/core/roi.py` (`drag_geometry`, `RoiDrag`).

## 5. 시계열 플롯 / Timecourse plot

1. KO: ROI가 있는 상태에서 **Value** 버튼으로 Timecourse 창을 엽니다. EN: with a ROI set, click **Value** to open the Timecourse window.
2. KO: ROI를 지우고(Esc) 플롯을 다시 봅니다. EN: remove the ROI (Esc) and look at the plot again.

- 기대 결과 / Expected: KO: 프레임별 ROI 내 유한(finite) 복셀의 평균이 표시되고 제목에 shape와 복셀 수가 나옵니다. ROI를 지우면 단일 복셀 시계열로 돌아갑니다. EN: the mean of the finite voxels in the ROI per frame; the title gives shape and voxel count; after removal it returns to the single-voxel timecourse.
- 실패 시 / On failure: KO: worker 로그(상태 표시줄 아이콘), `app/workers/convert_worker.py`(`_roi_timecourse`), `tests/test_mkj_wi0005_roi_timecourse.py`. 단일 프레임 스캔은 시계열이 의미 없습니다. EN: worker log; the files above; a single-frame scan has no meaningful timecourse.

## 6. Python API (잠정 / provisional)

KO: ROI API는 컨트롤러 메서드 `set_roi`, `clear_roi`, `roi_timecourse`(`app/controller/viewer.py`)이며, viewer hook의 `build_tab(parent, app)`이 받는 `app`으로 호출합니다(`docs/dev/hooks.md`). worker의 답은 GUI 이벤트 루프를 통해 들어오므로 `sleep` 루프로 기다리면 안 됩니다(GUI가 멈추고 답이 오지 않습니다). 아래처럼 버튼으로 확인하거나 `parent.after(200, poll)`로 다시 확인합니다.
EN: The ROI API is the controller's `set_roi`, `clear_roi` and `roi_timecourse` (`app/controller/viewer.py`), reached through the `app` a viewer hook's `build_tab(parent, app)` receives (`docs/dev/hooks.md`). The worker's answer arrives through the GUI event loop, so never wait in a sleep loop (it freezes the GUI and the answer never arrives); check with a button, or again later with `parent.after(200, poll)`.

KO: 1) 아래 두 파일로 작은 hook 패키지를 만들고 같은 가상환경에 설치합니다. EN: 1) Create a small hook package from the two files below and install it into the same venv.

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

```bash
pip install ./try-roi-hook
brkraw viewer   # KO: 터미널에서 실행해야 print 출력이 보입니다 / EN: run from a terminal to see the prints
```

KO: 2) `<YOUR_DATA>`를 열고 Viewer 탭에서 시간 축이 있는 스캔을 고른 뒤, **Extensions** 탭의 목록에서 `try-roi`를 고릅니다. 3) **Set rect ROI**, **Print timecourse**, **Set ellipse ROI**, **Clear ROI**, **Print timecourse**를 차례로 누릅니다.
EN: 2) Open `<YOUR_DATA>`, select a multi-frame scan in the Viewer tab, then pick `try-roi` from the list in the **Extensions** tab. 3) Press **Set rect ROI**, **Print timecourse**, **Set ellipse ROI**, **Clear ROI**, **Print timecourse** in turn.

- 기대 결과 / Expected: KO: Set 버튼을 누르면 잠시 뒤 터미널에 ROI 복셀 수와 처음 다섯 프레임 값이 찍히고, Viewer 탭의 axial 뷰(axis 2)에 ROI가 그려지며 Timecourse 플롯이 ROI 평균을 보입니다. `roi_timecourse()`는 `values`, `n_mask`, `n_per_frame`, `shape`, `axis`, `index`를 가진 dict이고, ROI가 없거나 worker 응답 전이면 `None`입니다. **Clear ROI** 뒤의 **Print timecourse**는 `None`을 찍습니다. EN: shortly after a Set button the terminal prints the ROI voxel count and the first five frame values, the ROI is drawn on the axial view (axis 2) and the Timecourse plot shows the ROI mean; `roi_timecourse()` is a dict with those keys, `None` without a ROI or before the worker answers; **Print timecourse** after **Clear ROI** prints `None`.
- 실패 시 / On failure: KO: `try-roi`가 목록에 없으면 같은 가상환경에 설치됐는지(`pip show try-roi-hook`)와 터미널의 "Failed to load viewer hook" 경고를 확인하세요. 버튼을 눌러 터미널에 `ValueError`가 나오면 이미지가 로드되지 않았거나 geometry/axis/index가 잘못된 것입니다(`app/controller/viewer.py`의 `set_roi` docstring). 오류 메시지는 STYLE.md의 "Errors" 규칙(필드, 값, 기대 값)을 따릅니다. 계속 "no answer"면 worker 로그(상태 표시줄 아이콘)를 보세요. EN: if `try-roi` is not listed, check it is installed in the same venv (`pip show try-roi-hook`) and look for a "Failed to load viewer hook" warning in the terminal; a `ValueError` in the terminal means no image is loaded or a bad geometry/axis/index (see the `set_roi` docstring), with messages following the STYLE.md "Errors" rule; a repeated "no answer" means checking the worker log (status bar icon).

## 7. 스타일 가이드 STYLE.md / STYLE.md style guide

KO: pip 설치에는 `docs/STYLE.md`가 포함되지 않습니다. 저장소에서 확인하세요: https://github.com/mokoji-org/brkraw-viewer/blob/main/docs/STYLE.md (또는 저장소를 clone한 뒤 `docs/STYLE.md`를 엽니다).
EN: The pip install does not ship `docs/STYLE.md`; read it in the repository at the URL above (or clone the repository and open `docs/STYLE.md`).

- 기대 결과 / Expected: KO: Tests(`tests/test_mkj_wiNNNN_<topic>.py`), Layout(Tk 무관 로직은 `core/`, 얇은 Tk 바인딩은 `ui/`), Docstrings(WI와 계약 id 인용), Errors 절이 있습니다. EN: sections Tests, Layout, Docstrings, Errors as listed.
- 실패 시 / On failure: KO: 파일이 `main`에 없다면 알려 주세요. EN: if the file is missing on `main`, report it.

## 8. 라벨 페인팅 / Label painting

KO: 데이터를 연 상태에서 Viewer 탭의 **Paint** 상자를 사용합니다. 자세한 설명은 `docs/user/viewer.md`("Label painting").
EN: With a scan open, use the **Paint** box in the Viewer tab; details in `docs/user/viewer.md` ("Label painting").

1. KO: 라벨 레이어가 없는 동안 **Paint/Erase**와 **Brush**가 비활성인지 확인합니다. EN: while no label layer exists, **Paint**/**Erase** and **Brush** are disabled.
2. KO: **New label layer**를 누릅니다. EN: press **New label layer**.
3. KO: **Paint**를 고르고 **Brush**를 5로 설정한 뒤 뷰에서 드래그합니다. 십자선은 움직이지 않습니다. EN: choose **Paint**, set **Brush** to 5, drag in a view; the crosshair does not move.
4. KO: 두 번째 획을 그린 뒤 **Undo**(또는 뷰에서 **Ctrl+Z**)를 누릅니다. EN: draw a second stroke, then press **Undo** (or **Ctrl+Z** over a view).
5. KO: **Erase**를 고르고 칠한 부분 위를 드래그합니다. EN: choose **Erase** and drag over painted voxels.
6. KO: 칠하는 드래그 중에 **Esc**를 누릅니다. EN: press **Esc** during a paint drag.
7. KO: **ROI** 버튼 중 **Square**를 누릅니다. EN: press **Square** among the **ROI** buttons.
8. KO: **Save label...**로 `label.nii.gz`를 저장합니다. EN: press **Save label...** and save `label.nii.gz`.

- 기대 결과 / Expected: KO: 3) 칠한 부분이 뷰에 겹쳐 보입니다. 4) 마지막 획만 사라집니다. 5) 칠한 부분이 지워집니다. 6) 진행 중이던 획이 사라지고 이전 획은 남습니다. 7) Paint가 Off로 바뀝니다. 8) `.nii.gz` 파일이 생기고 같은 스캔의 격자와 맞습니다(값은 0과 1). EN: 3) the paint shows over the views; 4) only the last stroke disappears; 5) painted voxels are erased; 6) the stroke in progress vanishes, earlier strokes stay; 7) Paint switches to Off; 8) a `.nii.gz` file is written on the same grid as the scan (values 0 and 1).
- 실패 시 / On failure: KO: 버튼 연결은 `src/brkraw_viewer/ui/tabs/viewer/paint_tool.py`, 획과 undo는 `src/brkraw_viewer/core/painter.py`, 저장은 `src/brkraw_viewer/core/labelio.py`, 컨트롤러 연결은 `app/controller/viewer.py`(`on_viewer_paint_press`)를 보세요. 오류 창이 뜨면 메시지를 확인하세요. EN: buttons in `paint_tool.py`, strokes and undo in `core/painter.py`, saving in `core/labelio.py`, controller glue in `on_viewer_paint_press` of `app/controller/viewer.py`; an error dialog shows the message.
