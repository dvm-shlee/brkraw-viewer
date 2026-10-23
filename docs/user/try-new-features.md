# 새 기능 체험하기 / Try the new features

KO: 이 문서는 베타 v0.5.0b1(잠정 API 포함)을 설치해 새 기능(ROI 도구, 시계열 플롯, Python API, STYLE.md, 레이어 API)을 직접 확인하는 순서입니다. 릴리스 노트는 `RELEASE_NOTES.md`의 "Release v0.5.0b1 (beta)"이며 https://github.com/dvm-shlee/brkraw-viewer/blob/v0.5.0b1/RELEASE_NOTES.md 에서 볼 수 있습니다. 각 항목은 "절차 / 기대 결과 / 실패 시 확인할 곳" 순서입니다.

EN: This page walks through the beta v0.5.0b1 (provisional APIs) and trying each new feature (ROI tool, timecourse plot, Python API, STYLE.md, Layers API). The release notes are in `RELEASE_NOTES.md`, "Release v0.5.0b1 (beta)": https://github.com/dvm-shlee/brkraw-viewer/blob/v0.5.0b1/RELEASE_NOTES.md . Each item lists steps, expected result and where to look on failure.

데이터 경로 / Data path: `<YOUR_DATA>` (KO: 시간 축이 있는 스캔, 예: fMRI, 이 들어 있는 Bruker 스터디 폴더, zip 또는 PvDatasets 패키지로 바꾸세요. EN: replace with a Bruker study folder, zip or PvDatasets package that has a multi-frame scan.)

## 1. 설치 / Install

KO: 새 가상환경에 베타 `v0.5.0b1`을 설치합니다. 이 버전은 아직 PyPI에 없는 `brkraw>=0.6.1rc2`를 요구하므로 GitHub 태그를 먼저 설치합니다.
EN: Install the beta `v0.5.0b1` into a fresh virtual environment. It pins `brkraw>=0.6.1rc2`, which is not on PyPI yet, so install that tag from GitHub first (otherwise pip fails with "No matching distribution found for brkraw").

```bash
python -m venv try-viewer && source try-viewer/bin/activate
pip install "git+https://github.com/BrkRaw/brkraw@0.6.1rc2"
pip install "git+https://github.com/dvm-shlee/brkraw-viewer@v0.5.0b1"
```

KO: 최신 개발 상태를 보려면 마지막 줄 대신 `pip install "git+https://github.com/dvm-shlee/brkraw-viewer@main"`을 실행합니다.
EN: For the latest development state, run `pip install "git+https://github.com/dvm-shlee/brkraw-viewer@main"` instead of the last line.

- 기대 결과 / Expected: KO: `pip show brkraw-viewer`가 `Version: 0.5.0b1`을 보여주고 `brkraw --help`에 `viewer`가 나옵니다. EN: `pip show brkraw-viewer` shows `Version: 0.5.0b1`; `brkraw --help` lists `viewer`.
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

## 9. 레이어 API (Python, 잠정 / provisional) / Layers API from Python (provisional)

KO: 레이어 API(`app.layers_api`)는 잠정(provisional)이며 바뀔 수 있습니다. 전체 참조는 [`docs/dev/hooks.md`](../dev/hooks.md)의 Layers 항목을 보세요. 이 API는 Tk 메인 스레드에서만 호출할 수 있고, `app`은 viewer hook의 `build_tab(parent, app)`으로만 얻습니다(노트북이 다른 방법으로 `app`을 얻을 수 있는 것은 아닙니다). 설치 방법은 6번의 `try-roi-hook`과 같습니다(entry point `brkraw.viewer.hook`, 모듈 하나).
EN: The layers API (`app.layers_api`) is provisional and may change; the full reference is the Layers bullet in [`docs/dev/hooks.md`](../dev/hooks.md). It can only be called on the Tk main thread, and `app` is obtained only through a viewer hook's `build_tab(parent, app)` (a notebook has no other way to get `app`). Install the hook like `try-roi-hook` in section 6 (entry point `brkraw.viewer.hook`, one module).

### 9A. 메인 스레드의 hook 버튼 / Hook buttons on the main thread

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

```bash
pip install ./try-layers-hook
brkraw viewer   # KO: 터미널에서 실행해야 print 출력이 보입니다 / EN: run from a terminal to see the prints
```

KO: 1) `<YOUR_DATA>`를 열고 스캔을 고른 뒤 **Extensions** 탭에서 `try-layers`를 고릅니다. 2) **Add mask**, **Half alpha**, **Remove**를 차례로 누릅니다.
EN: 1) Open `<YOUR_DATA>`, select a scan, and pick `try-layers` in the **Extensions** tab. 2) Press **Add mask**, **Half alpha**, **Remove** in turn.

- 기대 결과 / Expected: KO: **Add mask** 뒤 Viewer 탭의 세 뷰에 마스크 오버레이가 보이고 터미널에 이름 목록이 base, `mask` 순서로 찍힙니다. **Half alpha** 뒤 오버레이가 더 투명해지고, **Remove** 뒤 오버레이가 모두 사라집니다. EN: after **Add mask** the overlay shows in the Viewer tab's views and the terminal prints the names, base first, then `mask`; after **Half alpha** the overlay is visibly more transparent; after **Remove** no overlay is left.
- 실패 시 / On failure: KO: 레이어 동작은 `src/brkraw_viewer/app/controller/layers_api.py`를 보세요. 터미널의 오류는 `<field>: got ..., expected ...` 형식입니다(예: `shape: got ..., expected ...`는 마스크가 스캔 격자와 다르다는 뜻, `image: got no loaded scan, ...`는 스캔을 먼저 고르라는 뜻). 예제가 `app.call_on_main`을 쓰는 부분(예: 5초 안에 답이 없을 때)은 `src/brkraw_viewer/app/controller/viewer.py`의 `call_on_main`을 보세요. 목록에 `try-layers`가 없으면 `pip show try-layers-hook`과 "Failed to load viewer hook" 경고를 확인하세요. EN: layer behaviour is in `src/brkraw_viewer/app/controller/layers_api.py`; terminal errors read `<field>: got ..., expected ...` (for example `shape: got ..., expected ...` means the mask does not match the scan grid, `image: got no loaded scan, ...` means select a scan first); calls through `app.call_on_main` (for example no answer within 5 s) are in `call_on_main` in `src/brkraw_viewer/app/controller/viewer.py`; if `try-layers` is not listed, check `pip show try-layers-hook` and the "Failed to load viewer hook" warning.

### 9B. 다른 스레드에서 / From another thread

KO: 긴 계산이나 노트북처럼 다른 스레드에서 같은 일을 하는 방법입니다. 그 스레드에서 `app.layers_api`를 직접 부르면 `RuntimeError`가 납니다. 배열은 `app.call_on_main(...)`으로 받고, 오버레이 추가와 제거는 `app.call_on_main(lambda: ...)`로만 합니다. 앞의 `try-layers-hook`과 같은 패키지 형식이며, 모듈 `try_layers_hook.py`를 아래 코드로 바꾸세요(노트북도 hook을 통해서만 `app`을 얻습니다).
EN: This is how a long computation or a notebook would do the same work from another thread. Calling `app.layers_api` directly from that thread raises `RuntimeError`. Get the arrays through `app.call_on_main(...)`, and add and remove the overlay only through `app.call_on_main(lambda: ...)`. Use the same package layout as `try-layers-hook` and replace the module `try_layers_hook.py` with the code below (a notebook also gets `app` only through a hook).

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

KO: 같은 순서로 **Add mask (thread)**, **Half alpha (thread)**, **Remove (thread)**를 누릅니다.
EN: Press **Add mask (thread)**, **Half alpha (thread)**, **Remove (thread)** in the same order.

- 기대 결과 / Expected: KO: 9A와 같습니다. 오버레이가 뷰에 보이고, 이름이 base, `mask` 순서로 찍히며, 알파가 바뀌고, 제거하면 사라집니다. 터미널에 `thread failed:`가 없습니다. EN: same as 9A: the overlay shows in the views, the names print base first then `mask`, the alpha changes and Remove clears it; no `thread failed:` line appears.
- 실패 시 / On failure: KO: `thread failed: thread: got ..., expected the Tk main thread`는 `app.layers_api`를 스레드에서 직접 부른 것입니다(`layers_api.py`의 `_main_thread`). `TimeoutError`나 `app: got a closed viewer ...`는 `src/brkraw_viewer/app/controller/viewer.py`의 `call_on_main`을 보세요(메인 스레드가 5초 안에 답하지 못했거나 창이 닫힘). 그 밖의 `<field>: got ..., expected ...` 메시지는 9A와 같습니다. EN: `thread failed: thread: got ..., expected the Tk main thread` means `app.layers_api` was called directly from the thread (`_main_thread` in `layers_api.py`); `TimeoutError` or `app: got a closed viewer ...` points at `call_on_main` in `src/brkraw_viewer/app/controller/viewer.py` (the main thread did not answer within 5 s, or the window closed); other `<field>: got ..., expected ...` messages are as in 9A.
