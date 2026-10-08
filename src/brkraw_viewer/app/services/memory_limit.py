"""Memory limits of the viewer, from the installed memory (WI-0104 items 8 and 7, D-0169, D-0170).

``viewer.cache.memory_limit_mb`` missing or ``auto``: 16 % of the installed memory, at least
512 MB. A number is used as written (an old config keeps its number); 0 means never ask.
``viewer.cache.hook_memory_percent``: the share of the installed memory that a converter
hook's reconstruction peak may reach before the viewer asks (default 25 %, 0 = off).
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Tuple

logger = logging.getLogger("brkraw.viewer")

MB = 1024 * 1024
GB = 1024 * MB
AUTO_PERCENT = 16.0
FLOOR_BYTES = 512 * MB
ASSUMED_INSTALLED_BYTES = 4 * GB  # when the installed memory cannot be read
DEFAULT_HOOK_PERCENT = 25.0


@dataclass(frozen=True)
class MemoryLimit:
    """The limit the viewer asks above, and where it came from."""

    limit_bytes: int  # 0 = never ask
    mode: str  # "auto" | "config" | "off"
    installed_bytes: int
    installed_assumed: bool
    floor_applied: bool = False


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _read_installed_bytes() -> int:
    """Physical memory of this computer; raises when it cannot be read."""
    if sys.platform.startswith("win"):
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            raise OSError("GlobalMemoryStatusEx failed")
        return int(status.ullTotalPhys)
    return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))


def installed_memory() -> Tuple[int, bool]:
    """``(bytes, assumed)``: the installed memory, or 4 GB with ``assumed=True`` when unreadable."""
    try:
        value = int(_read_installed_bytes())
        if value > 0:
            return value, False
    except Exception as exc:
        logger.warning("Could not read the installed memory, assuming 4 GB: %s", exc)
    return ASSUMED_INSTALLED_BYTES, True


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def resolve_memory_limit(value: Any, installed: Tuple[int, bool]) -> MemoryLimit:
    """Limit from ``viewer.cache.memory_limit_mb`` (see the module doc)."""
    installed_bytes, assumed = installed
    if _number(value):
        limit = max(int(value * MB), 0)
        return MemoryLimit(limit, "config" if limit else "off", installed_bytes, assumed)
    auto = int(installed_bytes * AUTO_PERCENT / 100.0)
    floored = max(auto, FLOOR_BYTES)
    return MemoryLimit(floored, "auto", installed_bytes, assumed, floor_applied=floored != auto)


def resolve_hook_percent(value: Any) -> float:
    """Share (percent) for the hook's reconstruction peak; 0 = off, bad values use the default."""
    if value is None or not _number(value):
        return DEFAULT_HOOK_PERCENT
    return min(max(float(value), 0.0), 100.0)


def describe_limit(limit: MemoryLimit) -> str:
    """One paragraph for the notice: the number and why it is that number."""
    limit_mb = limit.limit_bytes / MB
    installed_mb = limit.installed_bytes / MB
    if limit.mode == "config":
        return f"Limit {limit_mb:,.0f} MB, as set in viewer.cache.memory_limit_mb."
    text = (
        f"Limit {limit_mb:,.0f} MB: {AUTO_PERCENT:.0f} % of the {installed_mb:,.0f} MB installed memory "
        "(automatic)."
    )
    if limit.installed_assumed:
        text = (
            f"Limit {limit_mb:,.0f} MB: {AUTO_PERCENT:.0f} % of {installed_mb:,.0f} MB, assumed because the "
            "installed memory could not be read (automatic)."
        )
    if limit.floor_applied:
        text += f" The minimum is {FLOOR_BYTES // MB} MB."
    return text + " Set viewer.cache.memory_limit_mb to a number to use your own limit (0 = never ask)."
