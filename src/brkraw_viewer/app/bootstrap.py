from __future__ import annotations

import sys
import tkinter as tk
import os
from pathlib import Path

from brkraw.core import config as config_core
from brkraw_viewer.app.services.viewer_config import REGISTRY_PATH_ENV

_ICON_REF: tk.PhotoImage | None = None

WINDOW_WIDTH = 1350
WINDOW_HEIGHT = 640
MIN_WIDTH = 800
MIN_HEIGHT = 600


SCREEN_MARGIN = 8
# Space kept free where the platform does not report a work area (menu bar and dock on macOS,
# panels on X11).
NON_WINDOWS_RESERVED_HEIGHT = 80

Area = tuple[int, int, int, int]  # x, y, width, height


def fit_geometry(
    request: tuple[int, int],
    minimum: tuple[int, int],
    area: Area,
    *,
    margin: int = SCREEN_MARGIN,
) -> tuple[int, int, int, int, int, int]:
    """Fit a window into the usable screen area.

    Returns ``(width, height, x, y, min_width, min_height)``. The size is the request capped by
    the area minus ``margin`` on every side, the minimum size is capped the same way, and the
    window is centred in the area and never leaves it.
    """
    ax, ay, aw, ah = (int(v) for v in area)
    max_w = max(aw - 2 * margin, 1)
    max_h = max(ah - 2 * margin, 1)
    width = max(1, min(int(request[0]), max_w))
    height = max(1, min(int(request[1]), max_h))
    min_w = min(int(minimum[0]), max_w, width)
    min_h = min(int(minimum[1]), max_h, height)
    x = ax + (aw - width) // 2
    y = ay + (ah - height) // 2
    x = min(max(x, ax + margin), ax + aw - margin - width)
    y = min(max(y, ay + margin), ay + ah - margin - height)
    return width, height, x, y, min_w, min_h


def geometry_string(width: int, height: int, x: int, y: int) -> str:
    """Tk geometry string with an absolute position; a negative coordinate is written as "+-N"."""
    return f"{int(width)}x{int(height)}+{int(x)}+{int(y)}"


def usable_area(root: tk.Tk) -> Area:
    """Usable screen area (x, y, width, height) of the monitor under the pointer."""
    root.update_idletasks()
    px = root.winfo_pointerx()
    py = root.winfo_pointery()

    screen_x = 0
    screen_y = 0
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    work_area_found = False

    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

            MonitorFromPoint = user32.MonitorFromPoint
            MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            MonitorFromPoint.restype = wintypes.HMONITOR

            GetMonitorInfoW = user32.GetMonitorInfoW
            GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            GetMonitorInfoW.restype = wintypes.BOOL

            pt = wintypes.POINT(px, py)
            MONITOR_DEFAULTTONEAREST = 2
            hmon = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcWork  # use work area (excludes taskbar)
                screen_x = int(r.left)
                screen_y = int(r.top)
                screen_w = int(r.right - r.left)
                screen_h = int(r.bottom - r.top)
                work_area_found = True
        except Exception:
            pass

    if not work_area_found:
        screen_h = max(screen_h - NON_WINDOWS_RESERVED_HEIGHT, 1)
    return screen_x, screen_y, int(screen_w), int(screen_h)


def center_on_current_monitor(
        root: tk.Tk, *,
        width: int | None = None,
        height: int | None = None,
        area: Area | None = None,
    ) -> None:
    # Make sure geometry info is available
    root.update_idletasks()

    w = int(width or root.winfo_width() or root.winfo_reqwidth())
    h = int(height or root.winfo_height() or root.winfo_reqheight())
    if area is None:
        area = usable_area(root)

    min_w, min_h = root.minsize()
    w, h, x, y, min_w, min_h = fit_geometry((w, h), (min_w, min_h), area)
    root.minsize(min_w, min_h)
    root.geometry(geometry_string(w, h, x, y))


def bring_to_front_once(root: "tk.Tk") -> None:
    def _try() -> None:
        try:
            root.deiconify()
        except Exception:
            pass
        try:
            root.lift()
        except Exception:
            pass

        try:
            root.attributes("-topmost", True)
            root.after(80, lambda: root.attributes("-topmost", False))
        except Exception:
            pass

        try:
            root.focus_force()
        except Exception:
            pass

    root.after(0, _try)
    root.after(250, _try)


def _icon_paths() -> tuple[Path, Path]:
    here = Path(__file__).resolve()
    assets = here.parents[1] / "assets"
    return assets / "icon.png", assets / "icon.ico"


def _set_app_icon(root: tk.Tk) -> None:
    try:
        png, ico = _icon_paths()
    except Exception:
        return

    if png.exists():
        try:
            global _ICON_REF
            img = tk.PhotoImage(master=root, file=str(png))
            root.iconphoto(True, img)
            _ICON_REF = img  # prevent GC (module-level ref)
        except Exception:
            pass

    if ico.exists():
        try:
            root.iconbitmap(default=str(ico))
        except Exception:
            pass


def run_app(
    *,
    path: str | Path | None = None,
    scan_id: int | None = None,
    reco_id: int | None = None,
    info_spec: str | Path | None = None,
    registry: str | Path | None = None,
) -> None:
    from brkraw_viewer.app.controller import ViewerController
    from brkraw_viewer.ui.main import MainWindow

    root = tk.Tk()

    # ---- window metadata ----
    root.title("BrkRaw Viewer")
    root.minsize(MIN_WIDTH, MIN_HEIGHT)
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    # ---- icon ----
    _set_app_icon(root)

    try:
        config_core.configure_logging(root=None, stream=sys.stdout)
    except Exception:
        pass
    if registry:
        registry_path = Path(registry).expanduser()
        if not registry_path.is_absolute():
            registry_path = Path.cwd() / registry_path
        try:
            registry_path = registry_path.resolve()
        except Exception:
            pass
        os.environ[REGISTRY_PATH_ENV] = str(registry_path)
    controller = ViewerController()
    MainWindow(root, controller)

    # Defer centering until layout stabilizes to avoid snapping to a corner.
    root.after(50, lambda: center_on_current_monitor(root))
    bring_to_front_once(root)
    if path:
        try:
            controller.action_open_dataset(Path(path))
        except Exception:
            pass
        if scan_id is not None:
            try:
                controller.action_select_scan(int(scan_id))
            except Exception:
                pass
        if reco_id is not None:
            try:
                controller.action_select_reco(int(reco_id))
            except Exception:
                pass
        if info_spec:
            try:
                controller.on_apply_addon_spec("info_spec", str(info_spec))
            except Exception:
                pass
    root.mainloop()
