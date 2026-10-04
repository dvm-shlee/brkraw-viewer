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


def map_shared_array(name: str, shape: Tuple[int, ...], dtype: str) -> np.ndarray:
    """The block as an array that uses the shared memory itself, not a copy (layer core C9).

    The block's name is removed at once, so nothing is left behind if the program stops;
    the memory stays mapped for as long as the returned array (or any view of it) lives
    and is freed with it. Before this, the main process copied the block, so for a moment
    it held the frame twice (WI-0010 contract C9).

    This hands the mapping from ``SharedMemory`` to the array. If this Python's
    ``SharedMemory`` does not have the expected parts, it falls back to one copy (the old
    behaviour) and still removes the block.
    """
    dt = np.dtype(dtype)
    count = int(np.prod(shape, dtype=np.int64)) if len(shape) else 1
    shm = multiprocessing.shared_memory.SharedMemory(name=name)
    try:
        mm = getattr(shm, "_mmap", None)
        buf = getattr(shm, "_buf", None)
        if mm is None or buf is None or not hasattr(shm, "_fd"):
            raise AttributeError("SharedMemory internals not available")
        arr = np.frombuffer(mm, dtype=dt, count=count).reshape(shape)
        # Let go of SharedMemory's own view and handle without unmapping: the array now
        # holds the mapping, which is unmapped when the last array using it is freed.
        buf.release()
        shm._buf = None  # type: ignore[attr-defined]
        shm._mmap = None  # type: ignore[attr-defined]
        fd = getattr(shm, "_fd", -1)
        if isinstance(fd, int) and fd >= 0:
            import os

            os.close(fd)
            shm._fd = -1  # type: ignore[attr-defined]
    except Exception:
        arr = np.ndarray(shape, dtype=dt, buffer=shm.buf).copy()
        try:
            shm.close()
        except Exception:
            pass
    try:
        shm.unlink()
    except Exception:
        pass
    return arr


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
