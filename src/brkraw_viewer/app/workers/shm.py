from __future__ import annotations

import multiprocessing.shared_memory
from multiprocessing import resource_tracker
from typing import Optional, Tuple

import numpy as np


def create_shared_array(array: np.ndarray) -> str:
    shm = multiprocessing.shared_memory.SharedMemory(create=True, size=array.nbytes)
    view = np.ndarray(array.shape, dtype=array.dtype, buffer=shm.buf)
    view[:] = array
    name = shm.name
    try:
        shm.close()
    except Exception:
        pass
    try:
        resource_tracker.unregister(getattr(shm, "_name", name), "shared_memory")
    except Exception:
        pass
    return name


def read_shared_array(name: str, shape: Tuple[int, ...], dtype: str) -> Tuple[np.ndarray, multiprocessing.shared_memory.SharedMemory]:
    shm = multiprocessing.shared_memory.SharedMemory(name=name)
    arr = np.ndarray(shape, dtype=np.dtype(dtype), buffer=shm.buf)
    return arr, shm


def release_shared_array(name: Optional[str]) -> None:
    """Free a shared-memory block nobody will read (a stale or failed result). Never raises."""
    if not name:
        return
    try:
        shm = multiprocessing.shared_memory.SharedMemory(name=name)
    except Exception:
        return
    try:
        shm.close()
    except Exception:
        pass
    try:
        shm.unlink()
    except Exception:
        pass
