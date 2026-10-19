from __future__ import annotations


from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import ttk


# ----------------------------
# Small, fast plotter component
# ----------------------------
#
# Philosophy:
# - This is a UI component only (rendering). Do not do heavy processing here.
# - Controllers/workers should compute y, x, hist bins, FFT, ROI time-series, etc.
# - PlotCanvas takes ready-to-draw arrays and renders them quickly on a Tk Canvas.
#
# Performance notes:
# - Redraws are coalesced via after() (throttle) so frequent updates do not freeze UI.
# - Line data is downsampled to approximately the canvas width.


@dataclass(frozen=True)
class LineStyle:
    color: str = "#6aa6ff"
    width: int = 2
    alpha: float = 1.0  # reserved for future use


@dataclass(frozen=True)
class PlotTheme:
    background: str = "#111111"
    grid: str = "#2a2a2a"
    axis: str = "#888888"
    text: str = "#dddddd"
    tick: str = "#bbbbbb"
    border: str = "#333333"


@dataclass
class PlotMeta:
    title: str = ""
    x_label: str = ""
    y_label: str = ""


class PlotCanvas(ttk.Frame):
    """Canvas-based plot widget.

    Modes:
    - lines: multi-trace line plot
    - hist: histogram
    - bars: bar chart
    - message: text only

    This widget is intended to be embedded in tabs/panels and updated by a controller.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: PlotTheme | None = None,
        throttle_ms: int = 16,
        max_points_factor: float = 2.0,
    ) -> None:
        super().__init__(master)
        self.theme = theme or PlotTheme()
        self.throttle_ms = int(throttle_ms)
        self.max_points_factor = float(max_points_factor)

        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            background=self.theme.background,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

        # State
        self._mode: str = "message"
        self._meta = PlotMeta()

        self._message: str = ""

        # Lines
        self._x: Optional[Sequence[float]] = None
        self._ys: list[Sequence[float]] = []
        self._line_styles: list[LineStyle] = []
        self._invert_x: bool = False
        self._xlim: Optional[Tuple[float, float]] = None
        self._ylim: Optional[Tuple[float, float]] = None

        # Hist
        self._hist_bins: Optional[Sequence[float]] = None  # bin edges
        self._hist_counts: Optional[Sequence[float]] = None

        # Bars
        self._bar_labels: list[str] = []
        self._bar_heights: Optional[Sequence[float]] = None
        self._vline_x: Optional[float] = None
        self._x_fmt: Optional[Callable[[float], str]] = None
        self._y_fmt: Optional[Callable[[float], str]] = None
        self._on_click: Optional[Callable[[float], None]] = None
        self._last_plot_bounds: Optional[Tuple[int, int, int, int]] = None
        self._last_x_bounds: Optional[Tuple[float, float]] = None
        self._capture_btn: Optional[tk.Widget] = None
        self._capture_icon: Optional[tk.PhotoImage] = None

        # Redraw coalescing
        self._redraw_job: Optional[str] = None
        self._dirty: bool = False

        # Bind resize
        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<Button-1>", self._on_click_event)

        # Initial
        self.set_message("No data")

    # -----------------
    # Public small API
    # -----------------

    def set_message(self, text: str) -> None:
        self._mode = "message"
        self._message = text
        self._last_plot_bounds = None
        self._last_x_bounds = None
        self._schedule_redraw()

    def set_vline(self, x: Optional[float]) -> None:
        self._vline_x = x
        self._schedule_redraw()

    def set_on_click(self, handler: Optional[Callable[[float], None]]) -> None:
        self._on_click = handler

    def enable_capture(self, command: Optional[Callable[[], None]]) -> None:
        if self._capture_btn is not None:
            try:
                self._capture_btn.destroy()
            except Exception:
                pass
            self._capture_btn = None
        if command is None:
            return
        try:
            from ..assets import load_icon
            from ..components.icon_button import IconButton

            self._capture_icon = load_icon("viewport-capture.png", size=(12, 12), invert=True, master=self)
            if self._capture_icon is not None:
                self._capture_btn = IconButton(
                    self._canvas,
                    image=self._capture_icon,
                    command=command,
                    bg=self.theme.background,
                )
        except Exception:
            self._capture_icon = None
            self._capture_btn = None
        if self._capture_btn is None:
            self._capture_btn = tk.Button(
                self._canvas,
                text="Save",
                width=4,
                height=1,
                font=("TkDefaultFont", 9),
                bg=self.theme.background,
                fg="#f6f6f6",
                activebackground="#3a3a3a",
                activeforeground="#ffff00",
                highlightthickness=0,
                borderwidth=0,
                command=command,
            )
        self._capture_btn.place(relx=1.0, rely=1.0, x=-4, y=-4, anchor="se")

    def capture_to_file(self, path: str) -> bool:
        try:
            self._canvas.update_idletasks()
            x = self._canvas.winfo_rootx()
            y = self._canvas.winfo_rooty()
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            from PIL import ImageGrab

            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.save(path)
            return True
        except Exception:
            pass
        try:
            import io
            from PIL import Image

            ps = self._canvas.postscript(colormode="color")
            img = Image.open(io.BytesIO(ps.encode("utf-8")))
            img.save(path)
            return True
        except Exception:
            return False
    def clear(self) -> None:
        self._mode = "message"
        self._message = ""
        self._x = None
        self._ys = []
        self._hist_bins = None
        self._hist_counts = None
        self._bar_labels = []
        self._bar_heights = None
        self._xlim = None
        self._ylim = None
        self._schedule_redraw()

    def set_lines(
        self,
        x: Sequence[float],
        ys: Sequence[Sequence[float]],
        *,
        styles: Optional[Sequence[LineStyle]] = None,
        meta: Optional[PlotMeta] = None,
        invert_x: bool = False,
        xlim: Optional[Tuple[float, float]] = None,
        ylim: Optional[Tuple[float, float]] = None,
        x_fmt: Callable[[float], str] | None = None,
        y_fmt: Callable[[float], str] | None = None,
    ) -> None:
        self._mode = "lines"
        self._x = x
        self._ys = [y for y in ys]
        self._invert_x = bool(invert_x)
        self._xlim = xlim
        self._ylim = ylim
        self._x_fmt = x_fmt
        self._y_fmt = y_fmt

        self._meta = meta or PlotMeta()

        self._line_styles = []
        if styles is None:
            # Simple default palette (distinct-ish)
            palette = [
                "#6aa6ff",
                "#ffcc66",
                "#7ee081",
                "#ff6a6a",
                "#c792ea",
                "#4dd0e1",
            ]
            for i in range(len(self._ys)):
                self._line_styles.append(LineStyle(color=palette[i % len(palette)], width=2))
        else:
            self._line_styles = [s for s in styles]
            # Extend if fewer styles than traces
            if len(self._line_styles) < len(self._ys):
                last = self._line_styles[-1] if self._line_styles else LineStyle()
                self._line_styles.extend([last] * (len(self._ys) - len(self._line_styles)))

        if not self._ys or not self._x:
            self.set_message("No data")
            return

        self._schedule_redraw()

    def set_hist(
        self,
        bin_edges: Sequence[float],
        counts: Sequence[float],
        *,
        meta: Optional[PlotMeta] = None,
    ) -> None:
        self._mode = "hist"
        self._hist_bins = bin_edges
        self._hist_counts = counts
        self._meta = meta or PlotMeta()
        if not bin_edges or not counts:
            self.set_message("No data")
            return
        self._schedule_redraw()

    def set_bars(
        self,
        labels: Sequence[str],
        heights: Sequence[float],
        *,
        meta: Optional[PlotMeta] = None,
    ) -> None:
        self._mode = "bars"
        self._bar_labels = [str(s) for s in labels]
        self._bar_heights = heights
        self._meta = meta or PlotMeta()
        if not labels or not heights:
            self.set_message("No data")
            return
        self._schedule_redraw()

    def set_viewport(
        self,
        *,
        xlim: Optional[Tuple[float, float]] = None,
        ylim: Optional[Tuple[float, float]] = None,
    ) -> None:
        self._xlim = xlim
        self._ylim = ylim
        self._schedule_redraw()

    # -----------------
    # Event + redraw
    # -----------------

    def _on_configure(self, _e: tk.Event) -> None:
        self._schedule_redraw()

    def _schedule_redraw(self) -> None:
        self._dirty = True
        if self._redraw_job is not None:
            return
        # Coalesce redraws
        self._redraw_job = self.after(self.throttle_ms, self._do_redraw)

    def _do_redraw(self) -> None:
        self._redraw_job = None
        if not self._dirty:
            return
        self._dirty = False

        c = self._canvas
        c.delete("all")

        w = int(c.winfo_width())
        h = int(c.winfo_height())
        if w <= 4 or h <= 4:
            return

        # Layout
        pad_l = 64
        pad_r = 16
        pad_t = 28 if self._meta.title else 16
        pad_b = 36

        plot_l = pad_l
        plot_t = pad_t
        plot_r = max(plot_l + 10, w - pad_r)
        plot_b = max(plot_t + 10, h - pad_b)

        # Border
        c.create_rectangle(
            plot_l,
            plot_t,
            plot_r,
            plot_b,
            outline=self.theme.border,
            width=1,
        )

        # Title and labels
        if self._meta.title:
            c.create_text(
                (plot_l + plot_r) // 2,
                6,
                text=self._meta.title,
                fill=self.theme.text,
                anchor="n",
            )

        if self._meta.x_label:
            c.create_text(
                (plot_l + plot_r) // 2,
                h - 4,
                text=self._meta.x_label,
                fill=self.theme.tick,
                anchor="s",
            )

        if self._meta.y_label:
            # rotated text is non-trivial in Tk; keep simple
            c.create_text(
                6,
                (plot_t + plot_b) // 2,
                text=self._meta.y_label,
                fill=self.theme.tick,
                anchor="w",
            )

        if self._mode == "message":
            self._draw_message(plot_l, plot_t, plot_r, plot_b)
        elif self._mode == "lines":
            self._draw_lines(plot_l, plot_t, plot_r, plot_b)
        elif self._mode == "hist":
            self._draw_hist(plot_l, plot_t, plot_r, plot_b)
        elif self._mode == "bars":
            self._draw_bars(plot_l, plot_t, plot_r, plot_b)
        else:
            self._draw_message(plot_l, plot_t, plot_r, plot_b)

    # -----------------
    # Drawing helpers
    # -----------------

    def _draw_message(self, l: int, t: int, r: int, b: int) -> None:
        msg = self._message or ""
        self._canvas.create_text(
            (l + r) // 2,
            (t + b) // 2,
            text=msg,
            fill=self.theme.text,
            anchor="center",
        )

    def _draw_grid(
        self,
        l: int,
        t: int,
        r: int,
        b: int,
        *,
        nx: int = 4,
        ny: int = 4,
    ) -> None:
        c = self._canvas
        # Vertical
        for i in range(1, nx):
            x = l + int((r - l) * i / nx)
            c.create_line(x, t, x, b, fill=self.theme.grid, width=1)
        # Horizontal
        for j in range(1, ny):
            y = t + int((b - t) * j / ny)
            c.create_line(l, y, r, y, fill=self.theme.grid, width=1)

    def _draw_ticks(
        self,
        l: int,
        t: int,
        r: int,
        b: int,
        *,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        nx: int = 4,
        ny: int = 4,
        x_fmt: Callable[[float], str] | None = None,
        y_fmt: Callable[[float], str] | None = None,
    ) -> None:
        c = self._canvas
        x_fmt = x_fmt or (lambda v: f"{v:g}")
        y_fmt = y_fmt or (lambda v: f"{v:g}")

        # x labels
        for i in range(nx + 1):
            x = l + int((r - l) * i / nx)
            v = x_min + (x_max - x_min) * i / nx
            c.create_text(x, b + 6, text=x_fmt(v), fill=self.theme.tick, anchor="n")

        # y labels
        for j in range(ny + 1):
            y = b - int((b - t) * j / ny)
            v = y_min + (y_max - y_min) * j / ny
            c.create_text(l - 6, y, text=y_fmt(v), fill=self.theme.tick, anchor="e")

    def _draw_lines(self, l: int, t: int, r: int, b: int) -> None:
        if self._x is None or not self._ys:
            self._draw_message(l, t, r, b)
            return

        self._draw_grid(l, t, r, b)

        x = self._x
        ys = self._ys

        n = min(len(x), *(len(y) for y in ys))
        if n <= 1:
            self._draw_message(l, t, r, b)
            return

        # Determine limits
        if self._xlim is not None:
            x_min, x_max = float(self._xlim[0]), float(self._xlim[1])
        else:
            x_min, x_max = float(min(x[:n])), float(max(x[:n]))

        if self._ylim is not None:
            y_min, y_max = float(self._ylim[0]), float(self._ylim[1])
        else:
            y_min = float(min(min(y[:n]) for y in ys))
            y_max = float(max(max(y[:n]) for y in ys))

        if x_max == x_min:
            x_max = x_min + 1.0
        if y_max == y_min:
            y_max = y_min + 1.0

        if self._invert_x:
            x_min, x_max = x_max, x_min
        self._last_plot_bounds = (l, t, r, b)
        self._last_x_bounds = (x_min, x_max)

        self._draw_ticks(
            l,
            t,
            r,
            b,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            x_fmt=self._x_fmt,
            y_fmt=self._y_fmt,
        )

        # Downsample
        plot_w = max(1, r - l)
        max_points = int(plot_w * self.max_points_factor)
        idx = _downsample_indices(n, max_points)

        # Precompute x pixel positions
        def x_to_px(v: float) -> int:
            return l + int((v - x_min) * (r - l) / (x_max - x_min))

        def y_to_py(v: float) -> int:
            return b - int((v - y_min) * (b - t) / (y_max - y_min))

        # Clip helper
        def in_xrange(v: float) -> bool:
            if not self._invert_x:
                return x_min <= v <= x_max
            return x_max <= v <= x_min

        c = self._canvas
        for trace_i, y in enumerate(ys):
            style = self._line_styles[trace_i] if trace_i < len(self._line_styles) else LineStyle()

            pts: list[int] = []
            for k in idx:
                xv = float(x[k])
                if not in_xrange(xv):
                    continue
                yv = float(y[k])
                pts.extend([x_to_px(xv), y_to_py(yv)])

            if len(pts) >= 4:
                c.create_line(*pts, fill=style.color, width=style.width, smooth=False)

        if self._vline_x is not None:
            xv = float(self._vline_x)
            if in_xrange(xv):
                px = x_to_px(xv)
                c.create_line(px, t, px, b, fill=self.theme.tick, dash=(2, 3), width=1)
        self._last_plot_bounds = (l, t, r, b)
        self._last_x_bounds = (x_min, x_max)

    def _draw_hist(self, l: int, t: int, r: int, b: int) -> None:
        self._last_plot_bounds = (l, t, r, b)
        self._last_x_bounds = None
        if self._hist_bins is None or self._hist_counts is None:
            self._draw_message(l, t, r, b)
            return

        edges = self._hist_bins
        counts = self._hist_counts
        nb = min(len(edges) - 1, len(counts))
        if nb <= 0:
            self._draw_message(l, t, r, b)
            return

        self._draw_grid(l, t, r, b)

        x_min = float(edges[0])
        x_max = float(edges[nb])
        y_min = 0.0
        y_max = float(max(counts[:nb])) if nb > 0 else 1.0
        if x_max == x_min:
            x_max = x_min + 1.0
        if y_max == y_min:
            y_max = y_min + 1.0

        self._draw_ticks(l, t, r, b, x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max)

        def x_to_px(v: float) -> int:
            return l + int((v - x_min) * (r - l) / (x_max - x_min))

        def y_to_py(v: float) -> int:
            return b - int((v - y_min) * (b - t) / (y_max - y_min))

        c = self._canvas
        for i in range(nb):
            x0 = float(edges[i])
            x1 = float(edges[i + 1])
            yv = float(counts[i])
            px0 = x_to_px(x0)
            px1 = x_to_px(x1)
            py1 = y_to_py(yv)
            c.create_rectangle(px0, py1, px1, b, outline="", fill="#6aa6ff")

    def _draw_bars(self, l: int, t: int, r: int, b: int) -> None:
        self._last_plot_bounds = (l, t, r, b)
        self._last_x_bounds = None
        if self._bar_heights is None or not self._bar_labels:
            self._draw_message(l, t, r, b)
            return
        heights = self._bar_heights
        n = min(len(self._bar_labels), len(heights))
        if n <= 0:
            self._draw_message(l, t, r, b)
            return

        self._draw_grid(l, t, r, b)

        y_min = 0.0
        y_max = float(max(float(v) for v in heights[:n]))
        if y_max == y_min:
            y_max = y_min + 1.0

        self._draw_ticks(l, t, r, b, x_min=0.0, x_max=float(n), y_min=y_min, y_max=y_max, x_fmt=lambda v: "")

        c = self._canvas
        bw = (r - l) / max(1, n)
        for i in range(n):
            v = float(heights[i])
            x0 = l + int(i * bw + 2)
            x1 = l + int((i + 1) * bw - 2)
            y1 = b - int((v - y_min) * (b - t) / (y_max - y_min))
            c.create_rectangle(x0, y1, x1, b, outline="", fill="#6aa6ff")

            # label (skip if too crowded)
            if bw >= 40:
                c.create_text((x0 + x1) // 2, b + 6, text=self._bar_labels[i], fill=self.theme.tick, anchor="n")

    def _on_click_event(self, event: tk.Event) -> None:
        if self._on_click is None or self._mode != "lines":
            return
        if self._last_plot_bounds is None or self._last_x_bounds is None:
            return
        l, t, r, b = self._last_plot_bounds
        if event.x < l or event.x > r or event.y < t or event.y > b:
            return
        x_min, x_max = self._last_x_bounds
        if x_max == x_min:
            return
        tnorm = (event.x - l) / max((r - l), 1)
        x_val = x_min + (x_max - x_min) * tnorm
        try:
            self._on_click(float(x_val))
        except Exception:
            return


def _downsample_indices(n: int, max_points: int) -> list[int]:
    """Return indices for downsampling to at most max_points.

    Uses simple stride sampling. For large signals, a min-max envelope sampler is better,
    but this is sufficient for MVP and matches the simplicity of existing fast plots.
    """

    if max_points <= 0:
        return list(range(n))
    if n <= max_points:
        return list(range(n))

    stride = max(1, int(n / max_points))
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return idx
