from __future__ import annotations

from pathlib import Path
from typing import Any, cast, Tuple

import tkinter as tk
from PIL import Image, ImageTk, ImageOps


def load_icon(
    name: str,
    size: tuple[int, int] | None = None,
    *,
    invert: bool = False,
    master: tk.Misc | None = None,
) -> tk.PhotoImage | None:
    """Load an icon bound to the Tk root of master, optionally resized.

    Icons are cached per root (on the root widget), so two roots never share a PhotoImage.
    """
    try:
        if master is None:
            master = tk._get_default_root()  # type: ignore[attr-defined]
        if master is None:
            return None
        root = master.nametowidget(".")
        cache: dict[Any, tk.PhotoImage] = root.__dict__.setdefault("_brkraw_icon_cache", {})
        key = (name, size, invert)
        if key not in cache:
            cache[key] = _build_icon(name, size, invert, root)
        return cache[key]
    except Exception:
        return None


def _build_icon(name: str, size: Tuple[int, int] | None, invert: bool, root: tk.Misc) -> tk.PhotoImage:
    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    icon_path = assets_dir / name
    img = Image.open(icon_path)
    if invert:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        alpha = img.getchannel("A") if img.mode == "RGBA" else None
        base = img.convert("RGB")
        base = ImageOps.invert(base)
        img = base.convert("RGBA")
        if alpha is not None:
            img.putalpha(alpha)
    if size is not None:
        resample = getattr(Image, "Resampling", Image)
        lanczos = getattr(resample, "LANCZOS", None)
        if lanczos is None:
            lanczos = getattr(Image, "LANCZOS", 1)
        img = img.resize(size, lanczos)
    return cast(tk.PhotoImage, ImageTk.PhotoImage(img, master=root))
