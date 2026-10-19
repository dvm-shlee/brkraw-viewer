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
    Without master the current default root is used; with none, the result is None. The
    default root is read, never created: ``tk._get_default_root()`` would open a hidden Tk
    root that later windows' Tk variables bind to (WI-0022).
    """
    try:
        if master is None:
            master = getattr(tk, "_default_root", None)
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


class _LoadIconCachedShim:
    """Compatibility shim for the old module-level _load_icon_cached lru_cache.

    Icons are now cached per Tk root (see load_icon); cache_clear drops the
    cache of the default root so callers that still invoke it keep working.
    With no default root it does nothing; it never creates one.
    """

    def cache_clear(self) -> None:
        root = getattr(tk, "_default_root", None)
        if root is not None:
            try:
                root.nametowidget(".").__dict__.pop("_brkraw_icon_cache", None)
            except Exception:
                pass


_load_icon_cached = _LoadIconCachedShim()


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
