# Viewer Hook 개발 How-To

이 문서는 `brkraw-viewer`에서 hook/extension을 개발할 때,
특히 viewport에 overlay/colormap 같은 시각화 제어를 넣는 실전 방법을 정리합니다.

현재 구조 기준으로 가장 중요한 결론은 아래 2가지입니다.

1. 공식 인터페이스만으로 `Viewer` 탭의 기존 viewport를 직접 제어하는 API는 없습니다.
2. 안정적으로 개발하려면 `Extensions` 탭 안에서 자체 viewport(`ViewportCanvas`)를 만들고 제어하는 방식이 권장됩니다.

## 1) 현재 hook이 할 수 있는 범위

`brkraw.viewer.hook` entry point로 로드된 hook은 기본적으로 `build_tab(parent, app)`로
Extensions 탭에 UI를 추가합니다.

`app`은 런타임에서 `ViewerController` 인스턴스이며, 주로 아래 콜백/상태를 통해 연동합니다.

- `app.on_viewer_jump(x, y, z)`: 코어 Viewer 좌표 이동
- `app.on_viewer_space_change(value)`: space 변경
- `app.register_viewer_space_listener(cb)`: space 변경 구독
- `app.state.dataset.selected_scan_id`, `app.state.dataset.selected_reco_id`: 현재 선택 상태
- `app.dataset.get_scan(scan_id)`: scan 접근

참고 파일:

- `brkraw-viewer/src/brkraw_viewer/ui/tabs/extensions/window.py`
- `brkraw-viewer/src/brkraw_viewer/app/protocols.py`
- `brkraw-viewer/src/brkraw_viewer/app/controller/viewer.py`

## 2) 권장 패턴: Extensions 탭에서 자체 viewport 제어

overlay/colormap/색상바를 안정적으로 다루려면, extension UI 안에서 `ViewportCanvas`를 직접 사용하세요.

```python
import tkinter as tk
from tkinter import ttk
import numpy as np

from brkraw_viewer.ui.components.viewport import ViewportCanvas, OverlaySpec


def _make_lut_red_yellow() -> np.ndarray:
    lut = np.zeros((256, 3), dtype=np.uint8)
    lut[:, 0] = 255
    lut[:, 1] = np.arange(256, dtype=np.uint8)
    return lut


class MyExtensionPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._vp = ViewportCanvas(self)
        self._vp.grid(row=0, column=0, sticky="nsew")

    def render_demo(self):
        base = np.random.randn(128, 128).astype(np.float32)
        overlay_map = np.random.rand(128, 128).astype(np.float32)
        mask = overlay_map > 0.6

        ov = OverlaySpec(
            data=overlay_map,
            lut=_make_lut_red_yellow(),
            alpha=0.65,
            vmin=0.0,
            vmax=1.0,
            mask=mask,
        )

        self._vp.set_view(
            base=base,
            overlay=ov,
            title="My Overlay",
            show_colorbar=True,
            colorbar_ticks=[(0.0, "0"), (0.5, "0.5"), (1.0, "1.0")],
            colorbar_label="Activation",
        )
```

핵심 포인트:

- `OverlaySpec`로 LUT + alpha + mask + vmin/vmax 제어 가능
- `show_colorbar=True`로 우측 colorbar 표시 가능
- `set_overlay_rgba(...)`를 쓰면 parametric overlay와 별개로 RGBA 레이어를 위에 추가할 수 있음

관련 파일:

- `brkraw-viewer/src/brkraw_viewer/ui/components/viewport.py`
- `brkraw-viewer/src/brkraw_viewer/ui/components/label_painter.py`

## 3) 코어 Viewer 탭 viewport 직접 제어가 필요한 경우

### 3-1. 현실적인 대안 (권장)

코어 Viewer 자체를 건드리지 않고, 데이터 레벨에서 hook을 적용해 결과를 Viewer로 보여주는 방식입니다.

- viewer hook 옵션(= `hook_args`)으로 `scan.get_dataobj(...)` 동작을 바꿔서 volume 값을 변환
- 필요하면 RGB 형태 데이터(마지막 축 3채널)를 반환해서 Viewer의 RGB 모드로 표시

주의:

- 이 방식은 "overlay 레이어를 따로 올리는 기능"이 아니라, 이미지를 변환/치환하는 방식입니다.

### 3-2. 내부 API 접근 (비권장, 깨지기 쉬움)

아래처럼 내부 위젯 트리를 타고 들어가면 코어 Viewer viewport 객체(`_xy`, `_xz`, `_zy`)를 가져올 수는 있습니다.
하지만 private 필드에 의존하므로 구조 변경 시 쉽게 깨집니다.

```python
def get_core_viewport(app, plane: str):
    view = getattr(app, "_view", None)
    if view is None:
        return None

    tab = view.tabs.get_tab("Viewer")
    tab_inst = getattr(tab, "_tab_instance", None)
    right = getattr(tab_inst, "right", None)
    if right is None:
        return None

    plane = plane.lower().strip()
    if plane == "xy":
        return getattr(right, "_xy", None)
    if plane == "xz":
        return getattr(right, "_xz", None)
    if plane == "zy":
        return getattr(right, "_zy", None)
    return None
```

실무 권장:

- 연구/내부 실험 단계에서만 사용
- 배포용 extension에서는 사용하지 않거나, 방어코드(`getattr`, `None` 체크) 필수

## 4) extension skeleton (최소 형태)

```python
from tkinter import ttk


class MyViewerHook:
    name = "my-extension"
    priority = 0

    def build_tab(self, parent, app):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        panel = MyExtensionPanel(frame, app)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.render_demo()
        return frame
```

`pyproject.toml`:

```toml
[project.entry-points."brkraw.viewer.hook"]
my-extension = "my_pkg.viewer_hook:MyViewerHook"
```

## 5) 팀 내 가이드 요약

1. 코어 Viewer 탭을 직접 제어하는 "공식 API"는 아직 없다.
2. overlay/colormap은 Extensions 탭의 `ViewportCanvas`에서 구현하는 것을 기본 전략으로 한다.
3. 코어 Viewer와 동기화가 필요하면 `app` 콜백(`on_viewer_jump`, space listener 등)으로 연결한다.
4. 부득이하게 내부 필드 접근 시, private API 의존임을 코드/문서에 명시한다.

## 6) 공식 API 추가 설계 제안 (Draft)

이 섹션은 `Viewer` 탭 viewport를 extension/hook에서 안전하게 제어할 수 있도록
"공식 API"를 추가하는 제안입니다.

### 6-1. 목표

1. extension이 private 필드(`_view`, `_xy`, `_xz`, `_zy`)에 의존하지 않게 한다.
2. overlay/colormap/annotation을 plane 단위(`xy`, `xz`, `zy`)로 제어할 수 있게 한다.
3. detached tab/refresh/reload 상황에서도 안정적으로 동작하도록 lifecycle을 명시한다.
4. 기존 extension이 깨지지 않도록 backward compatible하게 도입한다.

### 6-2. 비목표

1. 초기 버전에서 전체 viewport 구현을 plugin이 교체하도록 허용하지 않는다.
2. 초기 버전에서 렌더 파이프라인(zoom/fit/aspect) 자체를 외부에서 수정하게 하지 않는다.

### 6-3. 제안 API 표면

`ViewerController`에 "Viewer overlay service"를 노출한다.

- `app.viewer_api` (신규): extension에서 접근하는 공식 진입점
- `app.viewer_api`는 아래처럼 최소 기능부터 제공

```python
class ViewerOverlayAPI(Protocol):
    def set_param_overlay(
        self,
        plane: str,                  # "xy" | "xz" | "zy"
        data: np.ndarray,            # (H, W)
        *,
        lut: np.ndarray,             # (256, 3) uint8
        alpha: float = 0.6,
        alpha_map: np.ndarray | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        mask: np.ndarray | None = None,
        show_colorbar: bool = False,
        colorbar_ticks: list[tuple[float, str]] | None = None,
        colorbar_label: str = "",
        owner: str = "default",      # extension namespace
    ) -> None: ...

    def set_rgba_overlay(
        self,
        plane: str,
        rgba: np.ndarray | None,     # (H, W, 4) uint8; None이면 제거
        *,
        owner: str = "default",
    ) -> None: ...

    def clear_overlay(
        self,
        plane: str | None = None,    # None이면 전체 plane
        *,
        owner: str | None = None,    # None이면 전체 owner
    ) -> None: ...

    def get_view_shape(self, plane: str) -> tuple[int, int] | None: ...
    def request_redraw(self) -> None: ...
```

핵심 설계:

- `owner` 개념으로 extension별 overlay 충돌을 분리
- 컨트롤러가 owner별 state를 관리하고 최종 합성은 UI 레이어에서 수행
- 동일 owner가 재호출하면 replace, 다른 owner는 stacking 정책으로 병합

### 6-4. 상태 관리 모델

컨트롤러 내부에 다음 상태를 추가한다.

- `_viewer_plane_overlays: dict[str, dict[str, OverlayState]]`
  - 1차 key: plane (`xy`, `xz`, `zy`)
  - 2차 key: owner (`mrs`, `seg`, ...)
  - value: `param_overlay`, `rgba_overlay`, `zindex`, `updated_at`

초기 병합 정책:

1. `param_overlay`는 owner당 1개 (마지막 호출 wins)
2. `rgba_overlay`는 owner당 1개 (마지막 호출 wins)
3. owner 간에는 등록 순서(or `zindex`) 기준으로 상단 합성

### 6-5. lifecycle 훅 (권장 추가)

`brkraw.viewer.hook` 프로토콜 확장 제안:

```python
class ViewerHook(Protocol):
    ...
    def on_viewer_ready(self, app: Any) -> None: ...
    def on_viewer_invalidated(self, app: Any, reason: str) -> None: ...
```

의도:

- `on_viewer_ready`: Viewer 탭 attach/detach/rebuild 이후 overlay 재등록 타이밍 제공
- `on_viewer_invalidated`: dataset close, scan/reco 변경, tab rebuild 등에서 상태 정리

### 6-6. 에러/검증 정책

1. shape mismatch는 `ValueError` 대신 warning + no-op 모드 선택 가능
2. plane 문자열/array dtype은 API 진입점에서 강제 검증
3. 실패 시 앱 전체 렌더를 막지 않고 해당 owner overlay만 drop

권장 기본:

- 개발 모드: strict (`raise`)
- 배포 모드: tolerant (`warn + skip`)

### 6-7. 단계별 도입 계획

1. Phase 1 (최소 API)
   - `viewer_api.set_param_overlay`, `set_rgba_overlay`, `clear_overlay`
   - 내부 owner/plane state 저장 및 합성
   - 문서 + 샘플 extension 추가

2. Phase 2 (lifecycle)
   - `on_viewer_ready`, `on_viewer_invalidated` 도입
   - detach/attach/refresh 시 재등록 예제 제공

3. Phase 3 (고급)
   - `zindex`, blending mode 확장
   - 성능 옵션(throttle, partial update) 제공

### 6-8. 호환성 전략

1. 기존 extension에는 영향 없음 (`viewer_api`는 optional capability)
2. 공식 API가 없는 구버전 대응:
   - extension에서 `hasattr(app, "viewer_api")` 체크 후 fallback
3. private 접근 방식은 deprecate 경고만 두고 즉시 제거하지 않음

### 6-9. 수용 기준 (Acceptance Criteria)

1. extension에서 private 필드 접근 없이 코어 Viewer overlay 표시 가능
2. 탭 detach/attach 후 overlay 자동 복구
3. dataset 변경 시 stale overlay 잔상 없음
4. 서로 다른 extension 2개가 동시에 overlay를 등록해도 충돌 없이 표시
5. overlay API 실패가 코어 Viewer 렌더/조작을 중단시키지 않음
