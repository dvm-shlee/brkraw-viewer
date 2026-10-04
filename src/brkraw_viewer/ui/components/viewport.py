from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Dict, List

import numpy as np
from PIL import Image, ImageTk, ImageDraw

from ...core.composite import composite_over, window_to_index
from ...core.window import default_window, normalize_window
from ..assets import load_icon
from .icon_button import IconButton


ClickCallback = Callable[[int, int], None]
ZoomCallback = Callable[[float, Optional[Tuple[int, int]]], None]
ScrollCallback = Callable[[int], None]


@dataclass(frozen=True)
class OverlaySpec:
    data: np.ndarray                 # (H, W) float or uint
    lut: np.ndarray                  # (256, 3) uint8
    alpha: float = 0.6               # constant alpha
    alpha_map: Optional[np.ndarray] = None  # (H, W) float in [0,1]
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    mask: Optional[np.ndarray] = None       # (H, W) bool, True means draw
    # If you already normalized in controller, set vmin/vmax=None and provide data in [0,1].


class ColorbarWidget(ttk.Frame):
    def __init__(self, parent: tk.Misc, *, width: int = 14, height: int = 160) -> None:
        super().__init__(parent)
        self._bar_w = int(width)
        self._bar_h = int(height)

        self._canvas = tk.Canvas(self, highlightthickness=0, background="#111111")
        self._canvas.pack(fill="both", expand=True)

        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._img_id: Optional[int] = None
        self._text_ids: List[int] = []

        self._lut: Optional[np.ndarray] = None
        self._ticks: List[Tuple[float, str]] = []
        self._label: str = ""

        self._canvas.bind("<Configure>", self._on_resize)

    def set_colorbar(
        self,
        *,
        lut: np.ndarray,
        ticks: List[Tuple[float, str]],
        label: str = "",
    ) -> None:
        self._lut = np.asarray(lut, dtype=np.uint8)
        self._ticks = list(ticks)
        self._label = str(label)
        self._render()

    def clear(self) -> None:
        self._lut = None
        self._ticks = []
        self._label = ""
        self._canvas.delete("all")
        self._tk_img = None
        self._img_id = None
        self._text_ids = []

    def _on_resize(self, *_: object) -> None:
        self._render()

    def _render(self) -> None:
        self._canvas.delete("all")
        self._text_ids = []
        w = max(self._canvas.winfo_width(), 1)
        h = max(self._canvas.winfo_height(), 1)

        if self._lut is None:
            return

        bar_w = min(self._bar_w, w)
        bar_h = min(self._bar_h, h)
        x0 = 6
        y0 = 10
        x1 = x0 + bar_w
        y1 = y0 + bar_h

        # gradient image (top=max, bottom=min)
        grad = np.zeros((bar_h, bar_w, 3), dtype=np.uint8)
        ramp = np.linspace(255, 0, bar_h, dtype=np.int32)
        grad[:, :, :] = self._lut[ramp][:, None, :]

        pil = Image.fromarray(grad, mode="RGB")
        self._tk_img = ImageTk.PhotoImage(pil)
        self._img_id = self._canvas.create_image(x0, y0, anchor="nw", image=self._tk_img)

        # border
        self._canvas.create_rectangle(x0, y0, x1, y1, outline="#444444", width=1)

        # ticks: tick position expects 0..1 (normalized). controller can map values to 0..1.
        for t, txt in self._ticks:
            tt = float(t)
            tt = 0.0 if tt < 0.0 else 1.0 if tt > 1.0 else tt
            yy = y0 + int(round((1.0 - tt) * (bar_h - 1)))
            self._canvas.create_line(x1 + 2, yy, x1 + 8, yy, fill="#dddddd", width=1)
            tid = self._canvas.create_text(
                x1 + 10,
                yy,
                anchor="w",
                fill="#dddddd",
                text=str(txt),
                font=("TkDefaultFont", 9),
            )
            self._text_ids.append(tid)

        if self._label:
            self._canvas.create_text(
                x0,
                y1 + 8,
                anchor="nw",
                fill="#dddddd",
                text=self._label,
                font=("TkDefaultFont", 9, "bold"),
            )


class ViewportCanvas(ttk.Frame):
    """
    Fast viewport:
      - base: grayscale or RGB
      - overlay: optional parametric map with LUT + alpha
      - no matplotlib, uses numpy + PIL + ImageTk
    """

    def __init__(self, parent: tk.Misc, *, background: str = "#111111") -> None:
        super().__init__(parent)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(self, background=background, highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")

        # Optional colorbar on the right
        self._right = ttk.Frame(self)
        self._right.grid(row=0, column=1, sticky="ns")
        self._right.grid_remove()

        self._colorbar = ColorbarWidget(self._right)
        self._colorbar.pack(side="top", fill="y", expand=True, padx=(6, 6), pady=(6, 6))

        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._img_id: Optional[int] = None
        self._title_id: Optional[int] = None
        self._capture_icon: Optional[tk.PhotoImage] = None

        # Independent RGBA overlay layer (e.g., label painting)
        self._overlay_rgba: Optional[np.ndarray] = None  # (H, W, 4) uint8
        self._overlay_tk_img: Optional[ImageTk.PhotoImage] = None
        self._overlay_img_id: Optional[int] = None

        # Brush preview (shadow) drawn as a small RGBA image patch (pixel-accurate, NEAREST).
        self._brush_preview_tk_img: Optional[ImageTk.PhotoImage] = None
        self._brush_preview_img_id: Optional[int] = None

        self._click_cb: Optional[ClickCallback] = None
        self._zoom_cb: Optional[ZoomCallback] = None
        self._scroll_cb: Optional[ScrollCallback] = None
        self._capture_cb: Optional[Callable[[], None]] = None

        self._markers: List[int] = []
        self._boxes: List[int] = []
        self._marker_data: List[Tuple[int, int, str]] = []
        self._box_data: List[Tuple[int, int, int, int, str, int]] = []
        self._pan_offset = (0.0, 0.0)
        self._last_cursor: Optional[Tuple[int, int]] = None
        self._focus_rc: Optional[Tuple[int, int]] = None
        self._use_cursor_focus = False
        self._zoom_scale = 1.0
        self._zoom_changed = False

        # last render state: (img_h, img_w, offset_x, offset_y, target_w, target_h)
        self._render_state: Optional[Tuple[int, int, int, int, int, int]] = None
        self._resize_job: Optional[str] = None

        # cache
        self._last_base: Optional[np.ndarray] = None
        self._last_title: str = ""
        self._last_res: Tuple[float, float] = (1.0, 1.0)
        self._last_overlay: Optional[OverlaySpec] = None
        # Display window (vmin, vmax) of the base, computed by the caller once per frame
        # (layer core C5). None falls back to the slice's own 1-99 percentiles.
        self._last_window: Optional[Tuple[float, float]] = None
        # Layers drawn over the base, bottom to top: (rgb float (H, W, 3), alpha (H, W)) from
        # the layer core (C4), already sampled on this slice by the controller (C3).
        self._last_layers: List[Tuple[np.ndarray, np.ndarray]] = []
        self._show_crosshair: bool = False
        self._crosshair_rc: Optional[Tuple[int, int]] = None
        self._show_colorbar: bool = False
        self._allow_upsample: bool = True
        self._lock_mm_per_px: Optional[float] = None
        self._allow_overflow: bool = False

        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel)
        self._canvas.bind("<Button-5>", self._on_mousewheel)
        self._canvas.bind("<Shift-MouseWheel>", self._on_zoom_wheel)
        self._canvas.bind("<Shift-Button-4>", self._on_zoom_wheel)
        self._canvas.bind("<Shift-Button-5>", self._on_zoom_wheel)
        self._canvas.bind("<Motion>", self._on_motion)

        # capture button (bottom-right)
        self._capture_icon = load_icon("viewport-capture.png", size=(12, 12), invert=True)
        if self._capture_icon is not None:
            self._capture_btn = IconButton(
                self._canvas,
                image=self._capture_icon,
                command=self._on_capture,
                bg=background,
            )
        else:
            self._capture_btn = tk.Button(
                self._canvas,
                text="◉",
                width=1,
                height=1,
                font=("TkDefaultFont", 10),
                bg=background,
                fg="#f6f6f6",
                activebackground="#3a3a3a",
                activeforeground="#ffff00",
                highlightthickness=0,
                borderwidth=0,
                command=self._on_capture,
            )
        self._capture_btn.place(relx=1.0, rely=1.0, x=-3, y=-3, anchor="se")

    # -------- public API --------

    def set_click_callback(self, cb: Optional[ClickCallback]) -> None:
        self._click_cb = cb

    def set_zoom_callback(self, cb: Optional[ZoomCallback]) -> None:
        self._zoom_cb = cb

    def set_scroll_callback(self, cb: Optional[ScrollCallback]) -> None:
        self._scroll_cb = cb

    def set_capture_callback(self, cb: Optional[Callable[[], None]]) -> None:
        self._capture_cb = cb

    def capture_to_file(self, path: str | Path) -> bool:
        if self._last_base is None:
            return False
        base = np.asarray(self._last_base)
        if np.iscomplexobj(base):
            base = np.abs(base)

        base_rgb = self._base_to_rgb(base, self._last_window)
        base_rgb = self._composite_layers(base_rgb, self._last_layers)
        if self._last_overlay is not None:
            base_rgb = self._apply_overlay(base_rgb, self._last_overlay)

        rgba = self._overlay_rgba
        if rgba is not None:
            arr = np.asarray(rgba)
            if arr.shape[:2] == base_rgb.shape[:2] and arr.shape[2] == 4:
                alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
                over = arr[:, :, :3].astype(np.float32)
                base_rgb = (base_rgb.astype(np.float32) * (1.0 - alpha) + over * alpha).astype(np.uint8)

        pil_img = Image.fromarray(np.flipud(base_rgb), mode="RGB")
        out_path = Path(path)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            pil_img.save(out_path)
        except Exception:
            return False
        return True

    def bind_canvas(self, sequence: str, func: Callable, add: bool = True) -> str:
        # Helper for external components (eg painter) to bind to the drawing surface.
        return str(self._canvas.bind(sequence, func, add=add))

    def get_image_shape(self) -> Optional[Tuple[int, int]]:
        if self._last_base is None:
            return None
        b = np.asarray(self._last_base)
        if b.ndim < 2:
            return None
        return int(b.shape[0]), int(b.shape[1])

    def canvas_to_image(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        # Map canvas pixel coords to image (row, col) in image index space.
        # Uses normalized coords to avoid any integer-quantization artifacts.
        state = self._render_state
        if state is None:
            return None
        img_h, img_w, ox, oy, tw, th = state
        if img_h <= 0 or img_w <= 0:
            return None

        tw_f = float(max(int(tw), 1))
        th_f = float(max(int(th), 1))

        xx = float(int(x) - int(ox))
        yy = float(int(y) - int(oy))
        if xx < 0.0 or yy < 0.0 or xx >= tw_f or yy >= th_f:
            return None

        # Normalize to [0, 1) then scale to image indices.
        u = xx / tw_f
        v = yy / th_f

        col = int(np.floor(u * float(img_w)))
        disp_row = int(np.floor(v * float(img_h)))
        row = int(img_h - 1 - disp_row)

        # Clamp for safety at boundaries.
        if col < 0:
            col = 0
        elif col >= img_w:
            col = img_w - 1
        if row < 0:
            row = 0
        elif row >= img_h:
            row = img_h - 1

        return row, col

    def set_overlay_rgba(self, rgba: Optional[np.ndarray]) -> None:
        # Set an independent overlay in image space (H,W,4 uint8).
        if rgba is None:
            self._overlay_rgba = None
            self._overlay_tk_img = None
            if self._overlay_img_id is not None:
                try:
                    self._canvas.delete(self._overlay_img_id)
                except Exception:
                    pass
            self._overlay_img_id = None
            return

        arr = np.asarray(rgba)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError("overlay RGBA must be (H,W,4)")
        self._overlay_rgba = arr.astype(np.uint8, copy=False)
        # Only redraw overlay layer if we already rendered base once.
        if self._render_state is not None:
            self._render_overlay_layer()

    def clear_brush_preview(self) -> None:
        if self._brush_preview_img_id is not None:
            try:
                self._canvas.delete(self._brush_preview_img_id)
            except Exception:
                pass
        self._brush_preview_img_id = None
        self._brush_preview_tk_img = None

    def set_brush_preview(
        self,
        row: int,
        col: int,
        *,
        size: int = 1,
        shape: str = "square",
        color: str = "#ffcc00",
        show: bool = True,
    ) -> None:
        """Show a pixel-accurate brush preview aligned to the image voxel grid.

        The preview is rendered as a small RGBA image patch (NEAREST) so it matches
        the exact voxel mask footprint that would be painted.
        """
        if not show:
            self.clear_brush_preview()
            return

        state = self._render_state
        if state is None:
            return
        img_h, img_w, ox, oy, tw, th = state
        if img_h <= 0 or img_w <= 0:
            return

        r = int(row)
        c = int(col)
        if r < 0 or c < 0 or r >= img_h or c >= img_w:
            self.clear_brush_preview()
            return

        s = int(size)
        if s < 1:
            s = 1

        # Size semantics: size=N means NxN footprint centered at (r,c)
        half_lo = (s - 1) // 2
        half_hi = s // 2

        r0 = max(0, r - half_lo)
        r1 = min(img_h - 1, r + half_hi)
        c0 = max(0, c - half_lo)
        c1 = min(img_w - 1, c + half_hi)

        ph = int(r1 - r0 + 1)
        pw = int(c1 - c0 + 1)
        if ph <= 0 or pw <= 0:
            self.clear_brush_preview()
            return

        # Parse #RRGGBB
        col_str = str(color).strip()
        rr, gg, bb = 255, 204, 0
        if col_str.startswith("#") and len(col_str) == 7:
            try:
                rr = int(col_str[1:3], 16)
                gg = int(col_str[3:5], 16)
                bb = int(col_str[5:7], 16)
            except Exception:
                rr, gg, bb = 255, 204, 0

        shp = str(shape or "square").lower().strip()
        if shp not in ("square", "circle"):
            shp = "square"

        # Build voxelized mask in patch coords
        mask = np.ones((ph, pw), dtype=bool)
        if shp == "circle" and s > 1:
            eff_r = min(half_lo, half_hi)
            yy, xx = np.ogrid[0:ph, 0:pw]
            cy = int(r - r0)
            cx = int(c - c0)
            mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= int(eff_r) * int(eff_r)

        # RGBA patch (shadow)
        alpha = 96
        patch = np.zeros((ph, pw, 4), dtype=np.uint8)
        patch[mask, 0] = np.uint8(rr)
        patch[mask, 1] = np.uint8(gg)
        patch[mask, 2] = np.uint8(bb)
        patch[mask, 3] = np.uint8(alpha)

        # Convert patch bounds to display space (y flipped vs image row)
        disp_r0 = img_h - 1 - r1
        disp_r1 = img_h - 1 - r0

        x0 = float(ox) + float(c0) * float(tw) / float(img_w)
        x1 = float(ox) + float(c1 + 1) * float(tw) / float(img_w)
        y0 = float(oy) + float(disp_r0) * float(th) / float(img_h)
        y1 = float(oy) + float(disp_r1 + 1) * float(th) / float(img_h)

        dw = max(int(round(x1 - x0)), 1)
        dh = max(int(round(y1 - y0)), 1)

        pil = Image.fromarray(np.flipud(patch), mode="RGBA")
        resampling = getattr(Image, "Resampling", Image)
        resample = getattr(resampling, "NEAREST")
        pil = pil.resize((int(dw), int(dh)), resample)

        self._brush_preview_tk_img = ImageTk.PhotoImage(pil)

        # id might be stale if canvas was cleared
        if self._brush_preview_img_id is not None:
            try:
                if not self._canvas.type(self._brush_preview_img_id):
                    self._brush_preview_img_id = None
            except Exception:
                self._brush_preview_img_id = None

        if self._brush_preview_img_id is None:
            self._brush_preview_img_id = self._canvas.create_image(
                int(round(x0)), int(round(y0)),
                anchor="nw",
                image=self._brush_preview_tk_img,
            )
        else:
            try:
                self._canvas.itemconfigure(self._brush_preview_img_id, image=self._brush_preview_tk_img)
                self._canvas.coords(self._brush_preview_img_id, int(round(x0)), int(round(y0)))
            except Exception:
                try:
                    self._canvas.delete(self._brush_preview_img_id)
                except Exception:
                    pass
                self._brush_preview_img_id = self._canvas.create_image(
                    int(round(x0)), int(round(y0)),
                    anchor="nw",
                    image=self._brush_preview_tk_img,
                )

        try:
            self._canvas.tag_raise(self._brush_preview_img_id)
        except Exception:
            pass

    def set_view(
        self,
        *,
        base: np.ndarray,
        title: str = "",
        res: Tuple[float, float] = (1.0, 1.0),
        overlay: Optional[OverlaySpec] = None,
        crosshair: Optional[Tuple[int, int]] = None,
        focus_rc: Optional[Tuple[int, int]] = None,
        use_cursor_focus: bool = False,
        show_crosshair: bool = False,
        show_colorbar: bool = False,
        colorbar_ticks: Optional[List[Tuple[float, str]]] = None,  # normalized 0..1 ticks
        colorbar_label: str = "",
        allow_upsample: bool = True,
        mm_per_px: Optional[float] = None,
        allow_overflow: bool = False,
        zoom_scale: Optional[float] = None,
        window: Optional[Tuple[float, float]] = None,
        layers: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None,
    ) -> None:
        self._last_base = np.asarray(base)
        self._last_title = str(title)
        self._last_res = (float(res[0]), float(res[1]))
        self._last_overlay = overlay
        self._last_window = normalize_window(window)
        self._last_layers = list(layers or [])
        self._crosshair_rc = crosshair
        self._focus_rc = focus_rc
        self._use_cursor_focus = bool(use_cursor_focus)
        self._show_crosshair = bool(show_crosshair)
        self._show_colorbar = bool(show_colorbar)
        self._allow_upsample = bool(allow_upsample)
        self._lock_mm_per_px = None if mm_per_px is None else float(mm_per_px)
        self._allow_overflow = bool(allow_overflow)
        prev_zoom = self._zoom_scale
        if zoom_scale is None:
            self._zoom_scale = 1.0
        else:
            try:
                self._zoom_scale = max(float(zoom_scale), 0.01)
            except Exception:
                self._zoom_scale = 1.0
        self._zoom_changed = abs(self._zoom_scale - prev_zoom) > 1e-6

        if show_colorbar and overlay is not None:
            self._right.grid()
            ticks = colorbar_ticks or [(0.0, "min"), (0.5, "mid"), (1.0, "max")]
            self._colorbar.set_colorbar(lut=overlay.lut, ticks=ticks, label=colorbar_label)
        else:
            self._right.grid_remove()
            self._colorbar.clear()

        self._render()

    def clear(self) -> None:
        self._last_base = None
        self._last_overlay = None
        self._last_layers = []
        self._canvas.delete("all")
        self._tk_img = None
        self._img_id = None
        self._title_id = None
        self._render_state = None
        self._overlay_rgba = None
        self._overlay_tk_img = None
        self._overlay_img_id = None
        self._brush_preview_img_id = None
        self._brush_preview_tk_img = None

    def get_canvas_size(self) -> Tuple[int, int]:
        try:
            return (int(self._canvas.winfo_width()), int(self._canvas.winfo_height()))
        except Exception:
            return (0, 0)

    def add_marker(self, row: int, col: int, color: str) -> None:
        state = self._render_state
        if state is None:
            return
        img_h, img_w, ox, oy, tw, th = state
        if img_h <= 0 or img_w <= 0:
            return
        disp_row = img_h - 1 - int(row)
        x = ox + (int(col) + 0.5) * tw / img_w
        y = oy + (disp_row + 0.5) * th / img_h
        r = 4
        mid = self._canvas.create_oval(x - r, y - r, x + r, y + r, outline=color, width=2)
        self._markers.append(mid)
        self._marker_data.append((int(row), int(col), str(color)))

    def add_box(self, row0: int, col0: int, row1: int, col1: int, *, color: str, width: int = 2) -> None:
        state = self._render_state
        if state is None:
            return
        img_h, img_w, ox, oy, tw, th = state
        if img_h <= 0 or img_w <= 0:
            return
        r0 = max(0, min(int(row0), img_h - 1))
        r1 = max(0, min(int(row1), img_h - 1))
        c0 = max(0, min(int(col0), img_w - 1))
        c1 = max(0, min(int(col1), img_w - 1))
        row_min, row_max = sorted((r0, r1))
        col_min, col_max = sorted((c0, c1))
        disp_row_min = img_h - 1 - row_max
        disp_row_max = img_h - 1 - row_min
        x0 = ox + col_min * tw / img_w
        x1 = ox + (col_max + 1) * tw / img_w
        y0 = oy + disp_row_min * th / img_h
        y1 = oy + (disp_row_max + 1) * th / img_h
        bid = self._canvas.create_rectangle(x0, y0, x1, y1, outline=color, width=int(width))
        self._boxes.append(bid)
        self._box_data.append((int(row0), int(col0), int(row1), int(col1), str(color), int(width)))

    def clear_overlays(self) -> None:
        self._last_overlay = None
        self._render()

    # -------- internal rendering --------

    def _on_resize(self, *_: object) -> None:
        if self._last_base is None:
            return

        # Invalidate mapping while geometry is changing so painters don't stamp with stale state.
        self._render_state = None

        # Debounce resize to avoid excessive full renders.
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None

        # Schedule a render on the next idle tick (slightly delayed to coalesce rapid resizes).
        self._resize_job = self.after(16, self._render)

    def _on_click(self, event: tk.Event) -> None:
        if self._click_cb is None:
            return
        rc = self.canvas_to_image(int(event.x), int(event.y))
        if rc is None:
            return
        r, c = rc
        self._click_cb(int(r), int(c))

    def _on_motion(self, event: tk.Event) -> None:
        try:
            self._last_cursor = (int(event.x), int(event.y))
        except Exception:
            pass

    def _on_mousewheel(self, event: tk.Event) -> Optional[str]:
        direction = 0
        delta = getattr(event, "delta", 0)
        if isinstance(delta, (int, float)) and delta != 0:
            direction = 1 if delta > 0 else -1
        else:
            num = getattr(event, "num", None)
            if num == 4:
                direction = 1
            elif num == 5:
                direction = -1
        if direction == 0:
            return None

        state = int(getattr(event, "state", 0))
        shift_down = bool(state & 0x0001)
        if shift_down and self._zoom_cb is not None:
            try:
                if isinstance(delta, (int, float)) and delta != 0:
                    zoom_delta = float(delta)
                    if abs(zoom_delta) < 4.0:
                        zoom_delta *= 120.0
                else:
                    zoom_delta = float(direction) * 120.0
                rc = self.canvas_to_image(int(event.x), int(event.y))
                self._zoom_cb(zoom_delta, rc)
            except Exception:
                pass
            return "break"
        if self._scroll_cb is not None:
            try:
                self._scroll_cb(direction)
            except Exception:
                pass
            return "break"
        return None

    def _on_zoom_wheel(self, event: tk.Event) -> Optional[str]:
        if self._zoom_cb is None:
            return None
        direction = 0
        delta = getattr(event, "delta", 0)
        if isinstance(delta, (int, float)) and delta != 0:
            direction = 1 if delta > 0 else -1
        else:
            num = getattr(event, "num", None)
            if num == 4:
                direction = 1
            elif num == 5:
                direction = -1
        if direction == 0:
            return None
        try:
            if isinstance(delta, (int, float)) and delta != 0:
                zoom_delta = float(delta)
                if abs(zoom_delta) < 4.0:
                    zoom_delta *= 120.0
            else:
                zoom_delta = float(direction) * 120.0
            rc = self.canvas_to_image(int(event.x), int(event.y))
            self._zoom_cb(zoom_delta, rc)
        except Exception:
            pass
        return "break"

    def _on_capture(self) -> None:
        if self._capture_cb is None:
            return
        try:
            self._capture_cb()
        except Exception:
            pass

    def _render(self) -> None:
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None

        prev_state = self._render_state
        # During live resize (especially on macOS), the canvas can report transient 1px sizes.
        # If we clear/redraw in that moment, the image can appear to disappear and not recover.
        cw = int(self._canvas.winfo_width())
        ch = int(self._canvas.winfo_height())
        if cw < 8 or ch < 8:
            self._render_state = None
            self._resize_job = self.after(16, self._render)
            return

        self._canvas.delete("all")
        # After delete("all"), all canvas items are gone - reset stored ids so layers recreate.
        self._img_id = None
        self._title_id = None
        self._overlay_img_id = None
        self._brush_preview_img_id = None
        self._brush_preview_tk_img = None
        self._markers = []
        self._boxes = []

        if self._last_base is None:
            return

        base = np.asarray(self._last_base)
        if np.iscomplexobj(base):
            base = np.abs(base)

        # Render base -> RGB uint8, then the layers over it (C4)
        base_rgb = self._base_to_rgb(base, self._last_window)
        base_rgb = self._composite_layers(base_rgb, self._last_layers)

        # Apply overlay if present -> RGB uint8
        if self._last_overlay is not None:
            base_rgb = self._apply_overlay(base_rgb, self._last_overlay)

        pil_img = Image.fromarray(np.flipud(base_rgb), mode="RGB")

        # cw/ch already computed at the start of _render()
        cw = max(int(cw), 1)
        ch = max(int(ch), 1)

        # aspect from physical resolution if meaningful
        res_row, res_col = self._last_res
        width_mm = float(base.shape[1]) * res_col if base.ndim >= 2 else float(pil_img.width)
        height_mm = float(base.shape[0]) * res_row if base.ndim >= 2 else float(pil_img.height)
        lock_mm_per_px = self._lock_mm_per_px
        if lock_mm_per_px is not None and width_mm > 0 and height_mm > 0:
            mm_per_px = max(float(lock_mm_per_px), 1e-6)
            tw = max(int(round(width_mm / mm_per_px)), 1)
            th = max(int(round(height_mm / mm_per_px)), 1)
        else:
            if width_mm > 0 and height_mm > 0:
                aspect = width_mm / height_mm
            else:
                aspect = pil_img.width / max(pil_img.height, 1)

            canvas_aspect = cw / max(ch, 1)
            if canvas_aspect >= aspect:
                th = ch
                tw = max(int(th * aspect), 1)
            else:
                tw = cw
                th = max(int(tw / aspect), 1)

        # Pixel-perfect mode: do not enlarge beyond native pixel size.
        if not self._allow_upsample:
            tw = min(int(tw), int(pil_img.width))
            th = min(int(th), int(pil_img.height))
            tw = max(int(tw), 1)
            th = max(int(th), 1)

        base_ox = (cw - tw) // 2
        base_oy = (ch - th) // 2

        # Keep the focus point (cursor or crosshair) anchored while zooming.
        pan_x, pan_y = self._pan_offset
        if self._zoom_scale <= 1.0:
            pan_x, pan_y = (0.0, 0.0)
        elif self._zoom_changed and prev_state is not None:
            prev_h, prev_w, prev_ox, prev_oy, prev_tw, prev_th = prev_state
            if prev_tw > 0 and prev_th > 0:
                target = None
                if self._use_cursor_focus and self._last_cursor is not None:
                    cx, cy = self._last_cursor
                    u = (float(cx) - float(prev_ox)) / float(prev_tw)
                    v = (float(cy) - float(prev_oy)) / float(prev_th)
                    if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0:
                        target = (float(cx), float(cy), u, v)
                if target is None and self._focus_rc is not None and prev_w > 0 and prev_h > 0:
                    fr, fc = self._focus_rc
                    u = (float(fc) + 0.5) / float(prev_w)
                    v = (float(prev_h - 1 - int(fr)) + 0.5) / float(prev_h)
                    target_x = float(prev_ox) + u * float(prev_tw)
                    target_y = float(prev_oy) + v * float(prev_th)
                    target = (target_x, target_y, u, v)
                if target is not None:
                    tx, ty, u, v = target
                    pan_x = float(tx) - float(base_ox) - (u * float(tw))
                    pan_y = float(ty) - float(base_oy) - (v * float(th))
        self._pan_offset = (pan_x, pan_y)

        resampling = getattr(Image, "Resampling", Image)
        resample = getattr(resampling, "NEAREST")
        pil_img = pil_img.resize((tw, th), resample)

        self._tk_img = ImageTk.PhotoImage(pil_img)
        ox = base_ox
        oy = base_oy
        ox = int(round(float(ox) + self._pan_offset[0]))
        oy = int(round(float(oy) + self._pan_offset[1]))
        self._render_state = (int(base.shape[0]), int(base.shape[1]), int(ox), int(oy), int(tw), int(th))

        self._img_id = self._canvas.create_image(ox, oy, anchor="nw", image=self._tk_img)

        # Draw independent RGBA overlay layer (eg label painting) on top of base
        if self._overlay_rgba is not None:
            self._render_overlay_layer()

        if self._last_title:
            self._title_id = self._canvas.create_text(
                10, 10, anchor="nw", fill="#dddddd", text=self._last_title, font=("TkDefaultFont", 10, "bold")
            )

        if self._show_crosshair and self._crosshair_rc is not None:
            self._draw_crosshair(self._crosshair_rc[0], self._crosshair_rc[1])

        self._zoom_changed = False

        # redraw marker/box overlays from stored data
        for r, c, color in self._marker_data:
            self.add_marker(r, c, color)
        for r0, c0, r1, c1, color, width in self._box_data:
            self.add_box(r0, c0, r1, c1, color=color, width=width)

    def _render_overlay_layer(self) -> None:
        if self._overlay_rgba is None:
            return
        state = self._render_state
        if state is None:
            return
        img_h, img_w, ox, oy, tw, th = state

        arr = np.asarray(self._overlay_rgba)
        if arr.shape[0] != img_h or arr.shape[1] != img_w or arr.shape[2] != 4:
            return

        pil = Image.fromarray(np.flipud(arr), mode="RGBA")
        resampling = getattr(Image, "Resampling", Image)
        resample = getattr(resampling, "NEAREST")
        pil = pil.resize((int(tw), int(th)), resample)

        self._overlay_tk_img = ImageTk.PhotoImage(pil)

        # If the canvas was cleared (delete("all")), the stored id may refer to a non-existent item.
        if self._overlay_img_id is not None:
            try:
                if not self._canvas.type(self._overlay_img_id):
                    self._overlay_img_id = None
            except Exception:
                self._overlay_img_id = None

        if self._overlay_img_id is None:
            self._overlay_img_id = self._canvas.create_image(int(ox), int(oy), anchor="nw", image=self._overlay_tk_img)
        else:
            try:
                self._canvas.itemconfigure(self._overlay_img_id, image=self._overlay_tk_img)
                self._canvas.coords(self._overlay_img_id, int(ox), int(oy))
            except Exception:
                try:
                    self._canvas.delete(self._overlay_img_id)
                except Exception:
                    pass
                self._overlay_img_id = self._canvas.create_image(int(ox), int(oy), anchor="nw", image=self._overlay_tk_img)

        # Keep overlay above base image
        if self._img_id is not None and self._overlay_img_id is not None:
            try:
                self._canvas.tag_raise(self._overlay_img_id, self._img_id)
            except Exception:
                pass

    @staticmethod
    def _base_to_rgb(base: np.ndarray, window: Optional[Tuple[float, float]] = None) -> np.ndarray:
        if base.ndim == 3 and base.shape[2] == 3:
            arr = np.asarray(base)
            if arr.dtype != np.uint8:
                # accept 0..1 float or any numeric
                if np.issubdtype(arr.dtype, np.floating):
                    arr = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
                else:
                    arr = np.clip(arr, 0, 255).astype(np.uint8)
            return arr

        img = np.asarray(base)
        if np.iscomplexobj(img):
            img = np.abs(img)
        # C5: the caller's frame-wide window; without one (older callers) the slice's own.
        win = normalize_window(window)
        if win is None:
            win = default_window(img)
        u8 = window_to_index(img, win[0], win[1])
        return np.stack([u8, u8, u8], axis=2)

    @staticmethod
    def _composite_layers(base_rgb: np.ndarray, layers: List[Tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
        """Straight-alpha "over" of the layers on the base (C4); a layer whose shape does not
        match this slice is skipped rather than drawn misaligned."""
        h, w = base_rgb.shape[0], base_rgb.shape[1]
        usable = [(rgb, a) for rgb, a in layers if np.shape(rgb) == (h, w, 3) and np.shape(a) == (h, w)]
        if not usable:
            return base_rgb
        return composite_over(base_rgb, usable)

    def _apply_overlay(self, base_rgb: np.ndarray, ov: OverlaySpec) -> np.ndarray:
        h, w = base_rgb.shape[0], base_rgb.shape[1]
        data = np.asarray(ov.data)

        if data.shape[0] != h or data.shape[1] != w:
            # UI component assumes overlay already sliced/resampled in controller.
            # If you want, you can add nearest resize here, but it costs CPU.
            return base_rgb

        mask = np.ones((h, w), dtype=bool)
        if ov.mask is not None:
            m = np.asarray(ov.mask).astype(bool, copy=False)
            if m.shape == (h, w):
                mask &= m

        # normalize to 0..1
        if ov.vmin is None and ov.vmax is None and np.issubdtype(data.dtype, np.floating):
            # assume already normalized 0..1 if within range
            dmin = float(np.nanmin(data)) if np.size(data) else 0.0
            dmax = float(np.nanmax(data)) if np.size(data) else 1.0
            if dmin >= 0.0 and dmax <= 1.0:
                norm = np.clip(data, 0.0, 1.0)
            else:
                vmin, vmax = float(np.nanpercentile(data, 1.0)), float(np.nanpercentile(data, 99.0))
                if np.isclose(vmin, vmax):
                    vmax = vmin + 1.0
                norm = np.clip((data - vmin) / (vmax - vmin), 0.0, 1.0)
        else:
            vmin = float(ov.vmin) if ov.vmin is not None else float(np.nanpercentile(data, 1.0))
            vmax = float(ov.vmax) if ov.vmax is not None else float(np.nanpercentile(data, 99.0))
            if np.isclose(vmin, vmax):
                vmax = vmin + 1.0
            norm = np.clip((data - vmin) / (vmax - vmin), 0.0, 1.0)

        idx = (norm * 255.0).astype(np.uint8)
        lut = np.asarray(ov.lut, dtype=np.uint8)
        if lut.shape != (256, 3):
            return base_rgb

        rgba = lut[idx]  # (H, W, 3)
        out = base_rgb.copy()

        alpha = float(ov.alpha)
        if ov.alpha_map is not None:
            a = np.asarray(ov.alpha_map)
            if a.shape == (h, w):
                a = np.clip(a, 0.0, 1.0).astype(np.float32, copy=False)
                # broadcast to 3 channels
                a3 = a[:, :, None]
                m3 = mask[:, :, None]
                out[m3] = (out[m3].astype(np.float32) * (1.0 - a3[m3]) + rgba[m3].astype(np.float32) * a3[m3]).astype(np.uint8)
                return out

        # constant alpha
        if alpha <= 0.0:
            return out
        if alpha >= 1.0:
            out[mask] = rgba[mask]
            return out

        m = mask
        out[m] = (out[m].astype(np.float32) * (1.0 - alpha) + rgba[m].astype(np.float32) * alpha).astype(np.uint8)
        return out

    def _draw_crosshair(self, row: int, col: int) -> None:
        state = self._render_state
        if state is None:
            return
        img_h, img_w, ox, oy, tw, th = state
        if row < 0 or col < 0 or row >= img_h or col >= img_w:
            return
        disp_row = img_h - 1 - int(row)
        x = ox + (int(col) + 0.5) * tw / img_w
        y = oy + (disp_row + 0.5) * th / img_h
        x0, x1 = ox, ox + tw
        y0, y1 = oy, oy + th
        dash = (2, 4)
        self._canvas.create_line(x0, y, x1, y, fill="#ffffff", width=1, dash=dash)
        self._canvas.create_line(x, y0, x, y1, fill="#ffffff", width=1, dash=dash)
