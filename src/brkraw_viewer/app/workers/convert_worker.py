from __future__ import annotations

import json
import logging
import logging.handlers
import multiprocessing
import sys
from typing import Optional, cast
from pathlib import Path

import numpy as np
import yaml
from brkraw import api as brkapi
from brkraw.api.types import ScanLoader

from .protocol import (
    ConvertRequest,
    ConvertResult,
    LoadVolumeRequest,
    LoadVolumeResult,
    TimecourseRequest,
    TimecourseResult,
    RegistryRequest,
    RegistryResult,
)
from ..services import registry as registry_service
from .shm import create_shared_array

logger = logging.getLogger("brkraw.worker")
_loader_cache: dict[str, brkapi.BrukerLoader] = {}

# Per-reco constants (frame-axis number, affine) are computed once and reused for every
# later frame (WI-0068: re-reading the JCAMP files cost ~0.52 s per frame).
_UNSET = object()
_meta_cache: dict[tuple, object] = {}
# (path, scan_id, reco_id) of recos this worker has loaded -> bytes it still holds for it
# (layer core C9, WI-0072). brkraw keeps a fully read reco in ``scan.image_info[reco]
# ["dataobj"]`` (one copy); a frame-wise partial read or a hook result is not kept (0).
_held_recos: dict[tuple, int] = {}
# The scan objects behind ``_held_recos``, so their data can be freed (C9).
_held_scans: dict[tuple, object] = {}


def _memo(key: tuple, compute):
    value = _meta_cache.get(key, _UNSET)
    if value is _UNSET:
        value = compute()
        _meta_cache[key] = value
    return value


def _hook_key(hook_name: Optional[str], hook_args: Optional[dict]) -> tuple:
    return (hook_name or "", json.dumps(hook_args or {}, sort_keys=True, default=repr))


class _StreamToLogger:
    def __init__(self, log: logging.Logger, level: int) -> None:
        self._log = log
        self._level = level

    def write(self, msg: str) -> None:
        text = msg.rstrip()
        if not text:
            return
        self._log.log(self._level, text)

    def flush(self) -> None:  # pragma: no cover - for stream interface
        return


def _get_loader(path: str) -> brkapi.BrukerLoader:
    loader = _loader_cache.get(path)
    if loader is None:
        loader = brkapi.BrukerLoader(path, disable_hook=True)
        _loader_cache[path] = loader
    return loader


def _ensure_hook_state(loader: brkapi.BrukerLoader, scan_id: int, *, enable_hook: bool) -> ScanLoader:
    scan = cast(ScanLoader, loader.get_scan(scan_id))
    # Track hook state locally. Some ScanLoader implementations may not define
    # `_hook_enabled_state` by default; always attempt to set it so that later
    # "disable" requests can reliably reset the converter.
    was_enabled = bool(getattr(scan, "_hook_enabled_state", False))
    was_resolved = bool(getattr(scan, "_hook_resolved", False))
    if enable_hook:
        try:
            if not getattr(scan, "_hook_resolved", False):
                brkapi.hook_resolver(
                    scan,
                    brkapi.config.resolve_root(None),
                    affine_decimals=brkapi.config.affine_decimals(root=None),
                )
        except Exception as exc:
            logger.warning("Hook resolve failed for scan %s: %s", scan_id, exc)
        try:
            setattr(scan, "_hook_enabled_state", True)
        except Exception:
            pass
    else:
        if was_enabled or was_resolved:
            try:
                loader.reset_converter(scan)
            except Exception:
                pass
            try:
                scan._hook_resolved = False
            except Exception:
                pass
        try:
            setattr(scan, "_hook_enabled_state", False)
        except Exception:
            pass
    return scan


def run_worker(
    input_queue: multiprocessing.Queue,
    output_queue: multiprocessing.Queue,
    log_queue: Optional[multiprocessing.Queue] = None,
) -> None:
    if log_queue is not None:
        qh = logging.handlers.QueueHandler(log_queue)
        root = logging.getLogger()
        level = None
        try:
            cfg = brkapi.config.resolve_config(root=None)
            level = cfg.get("logging", {}).get("level", None) if isinstance(cfg, dict) else None
        except Exception:
            level = None
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        if not isinstance(level, int):
            level = logging.INFO
        root.setLevel(level)
        root.handlers = []
        root.addHandler(qh)
        sys.stdout = _StreamToLogger(root, logging.INFO)  # type: ignore[assignment]
        sys.stderr = _StreamToLogger(root, logging.ERROR)  # type: ignore[assignment]

    logger.info("Worker started.")

    while True:
        try:
            task = input_queue.get()
            if task is None:
                break
            if isinstance(task, ConvertRequest):
                _process_convert(task, output_queue)
                continue
            if isinstance(task, LoadVolumeRequest):
                _process_load_volume(task, output_queue)
                continue
            if isinstance(task, TimecourseRequest):
                _process_timecourse(task, output_queue)
                continue
            if isinstance(task, RegistryRequest):
                _process_registry(task, output_queue)
                continue
        except Exception as exc:
            logger.error("Worker loop exception: %s", exc, exc_info=True)
            output_queue.put(ConvertResult(job_id="", saved_paths=[], error=f"Worker loop error: {exc}"))
    logger.info("Worker stopped.")


def _process_convert(task: ConvertRequest, output_queue: multiprocessing.Queue) -> None:
    saved: list[str] = []
    try:
        logger.info("Processing scan %s, reco %s", task.scan_id, task.reco_id)
        logger.debug("Convert request: path=%s space=%s flip=%s hook=%s", task.path, task.space, task.flip, bool(task.hook_args))
        loader = _get_loader(task.path)
        enable_hook = bool(task.hook_args)
        _ensure_hook_state(loader, task.scan_id, enable_hook=enable_hook)

        nii = loader.convert(
            task.scan_id,
            reco_id=task.reco_id,
            space=task.space,
            override_subject_type=task.subject_type,
            override_subject_pose=task.subject_pose,
            hook_args_by_name=task.hook_args,
            flip_x=task.flip[0],
            flip_y=task.flip[1],
            flip_z=task.flip[2],
            enable_hook=enable_hook,
        )

        if nii is None:
            output_queue.put(ConvertResult(job_id=task.job_id, saved_paths=[], error="No output generated"))
            return

        images = list(nii) if isinstance(nii, tuple) else [nii]
        if len(images) != len(task.output_paths):
            logger.warning(
                "Output count mismatch: expected %d, got %d",
                len(task.output_paths),
                len(images),
            )

        for i, img in enumerate(images):
            if i >= len(task.output_paths):
                break
            dest = task.output_paths[i]
            logger.info("Saving output %d to %s", i + 1, dest)

            if hasattr(img, "to_filename"):
                img.to_filename(dest)
            elif callable(img):
                img(dest)
            else:
                logger.warning("Output %d (%s) does not support to_filename and is not callable.", i + 1, type(img))
                continue
            saved.append(dest)

        if task.sidecar_enabled:
            logger.info(
                "Writing metadata sidecars: format=%s spec=%s outputs=%d",
                task.sidecar_format,
                task.metadata_spec or "default",
                len(saved),
            )
            _write_sidecars(
                loader,
                scan_id=task.scan_id,
                reco_id=task.reco_id,
                output_paths=saved,
                sidecar_format=task.sidecar_format,
                metadata_spec=task.metadata_spec,
            )

        output_queue.put(ConvertResult(job_id=task.job_id, saved_paths=saved, error=None))
        logger.info("Task completed successfully.")

    except Exception as exc:
        logger.error("Task failed: %s", exc, exc_info=True)
        output_queue.put(ConvertResult(job_id=task.job_id, saved_paths=saved, error=str(exc)))


def _write_sidecars(
    loader: brkapi.BrukerLoader,
    *,
    scan_id: int,
    reco_id: int,
    output_paths: list[str],
    sidecar_format: str,
    metadata_spec: Optional[str],
) -> None:
    if not output_paths:
        logger.warning("Sidecar requested but no outputs were saved.")
        return
    get_metadata = getattr(loader, "get_metadata", None)
    if not callable(get_metadata):
        logger.warning("Metadata sidecar unavailable: loader.get_metadata missing.")
        return
    try:
        meta = get_metadata(
            scan_id,
            reco_id=reco_id,
            spec=metadata_spec if metadata_spec else None,
        )
    except Exception as exc:
        logger.error("Sidecar metadata build failed: %s", exc, exc_info=True)
        return
    if meta is None:
        logger.warning("Sidecar metadata not available.")
        return
    if not isinstance(meta, dict):
        logger.warning("Sidecar metadata is not a mapping.")
        return
    for dest in output_paths:
        try:
            logger.debug("Writing sidecar for %s", dest)
            _write_sidecar(Path(dest), meta, sidecar_format=sidecar_format)
        except Exception as exc:
            logger.error("Sidecar write failed for %s: %s", dest, exc, exc_info=True)


def _write_sidecar(path: Path, meta: dict, *, sidecar_format: str) -> None:
    fmt = (sidecar_format or "json").lower()
    suffix = ".json" if fmt == "json" else ".yaml"
    sidecar = path.with_suffix(suffix)
    if path.name.endswith(".nii.gz"):
        sidecar = path.with_name(path.name[:-7] + suffix)
    if fmt == "json":
        sidecar.write_text(json.dumps(meta, indent=2, sort_keys=False), encoding="utf-8")
    else:
        sidecar.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def _frame_axis_number(scan: ScanLoader, reco_id: int) -> Optional[int]:
    """Data-axis number of the last axis when the reco has a frame axis (index >= 3), else None.

    The viewer reads one cycle volume at a time; the cycle axis is the last axis.
    brkraw 0.6 takes the axis as a name or as this number (``get_dataobj(axis=, frames=)``).
    """
    shape_info = brkapi.shape_resolver.resolve(scan, reco_id=reco_id)
    if not shape_info:
        return None
    _shape, shape_desc = brkapi.image_resolver.normalized_layout(shape_info)
    return len(shape_desc) - 1 if len(shape_desc) > 3 else None


def _read_frame_block(
    scan: ScanLoader,
    reco_id: int,
    frame_start: Optional[int],
    frame_count: Optional[int],
    *,
    frame_axis: object = _UNSET,
    **data_kwargs: object,
):
    """Read ``frame_count`` frames from ``frame_start`` of the last (cycle) axis (None = to the end).

    brkraw 0.6 selection: ``get_dataobj(axis=<last axis>, frames="start:stop")``. The
    slice keeps the axis (size ``frame_count``), as the 0.5 ``cycle_index/cycle_count``
    did. Returns None when the reco has no frame axis. ``frame_axis`` is the already
    resolved axis number (``None`` = no frame axis); omit it to resolve it here.
    """
    axis = _frame_axis_number(scan, reco_id) if frame_axis is _UNSET else frame_axis
    if axis is None:
        return None
    start = int(frame_start or 0)
    stop = "" if frame_count is None else str(start + int(frame_count))
    return scan.get_dataobj(reco_id, axis=axis, frames=f"{start}:{stop}", **data_kwargs)


def _expected_nbytes(scan: ScanLoader, reco_id: int) -> Optional[int]:
    """Size in bytes of the reco's 2dseq, from visu_pars only (no data read, ~0 ms).

    ``prod(VisuCoreSize) * VisuCoreFrameCount * itemsize``. Returns None when any
    of those cannot be read; the caller then does not ask.
    """
    try:
        from brkraw.resolver import datatype

        params = scan.avail[reco_id].file_visu_pars  # type: ignore[attr-defined]
        size = params.get("VisuCoreSize")
        frame_count = params.get("VisuCoreFrameCount")
        word = params.get("VisuCoreWordType")
        itemsize = np.dtype(datatype.WORDTYPE[word]).itemsize
        return int(np.prod(np.asarray(size, dtype=np.int64))) * int(frame_count) * int(itemsize)
    except Exception as exc:
        logger.debug("Expected size unavailable for reco %s: %s", reco_id, exc)
        return None


def _hook_output_nbytes(scan: ScanLoader, reco_id: int, data_kwargs: dict) -> Optional[int]:
    """Bytes a converter hook's ``get_dataobj`` will return, when the hook says (C9).

    A hook module that offers ``get_dataobj_info(scan, reco_id, **kwargs)`` (brkraw-sordino
    does, WI-0071) reports the size of its output without reading. None when the hook does
    not offer it or it fails; the caller then falls back to the 2dseq size.
    """
    hook = getattr(scan, "_converter_hook", None)
    func = hook.get("get_dataobj") if isinstance(hook, dict) or hasattr(hook, "get") else None
    if func is None:
        return None
    while hasattr(func, "func"):  # functools.partial
        func = getattr(func, "func")
    func = getattr(func, "__func__", func)  # bound method
    module = sys.modules.get(getattr(func, "__module__", "") or "")
    info_func = getattr(module, "get_dataobj_info", None) if module is not None else None
    if not callable(info_func):
        return None
    try:
        info = info_func(scan, reco_id, **data_kwargs)
        nbytes = info.get("nbytes") if isinstance(info, dict) else None
        return int(nbytes) if nbytes is not None else None
    except Exception as exc:
        logger.debug("Hook size unavailable for reco %s: %s", reco_id, exc)
        return None


def _kept_nbytes(scan: ScanLoader, reco_id: int) -> int:
    """Bytes brkraw keeps for this reco after a read (its cached ``dataobj``), else 0."""
    try:
        info = getattr(scan, "image_info", {}).get(reco_id)
        dataobj = info.get("dataobj") if isinstance(info, dict) else None
        return int(getattr(dataobj, "nbytes", 0) or 0)
    except Exception:
        return 0


def _release_reco(key: tuple) -> None:
    """Free the data the worker holds for one reco (C9). Never raises."""
    nbytes = _held_recos.pop(key, 0)
    scan = _held_scans.pop(key, None)
    if scan is None:
        return
    try:
        reco_id = key[2]
        info = getattr(scan, "image_info", {}).get(reco_id)
        if isinstance(info, dict) and info.get("dataobj") is not None:
            # brkraw reads the data again (load_data=True) when ``dataobj`` is None.
            freed = dict(info)
            freed["dataobj"] = None
            scan.image_info[reco_id] = freed  # type: ignore[index]
            logger.debug("Released reco %s (%s bytes)", key, nbytes)
    except Exception as exc:
        logger.debug("Release of reco %s failed: %s", key, exc)


def _release_others(keep: Optional[tuple], current: tuple) -> None:
    """Free every held reco that is neither ``current`` nor in ``keep`` (None = keep all)."""
    if keep is None:
        return
    wanted = {tuple(k) for k in keep} | {current}
    for key in [k for k in _held_recos if k not in wanted]:
        _release_reco(key)


def _affine_for_request(scan: ScanLoader, task: LoadVolumeRequest, hook_args: dict):
    """Affine (list) for this request, computed once per (reco, space, flips, hook, slicepack)."""
    key = (
        "affine",
        task.path,
        task.scan_id,
        task.reco_id,
        task.space,
        task.subject_type,
        task.subject_pose,
        bool(task.flip_x),
        bool(task.flip_y),
        bool(task.flip_z),
        int(task.slicepack_index or 0),
    ) + _hook_key(task.hook_name, hook_args)

    def compute():
        affine = _resolve_affine_for_space(
            scan,
            reco_id=task.reco_id,
            space=task.space,
            subject_type=task.subject_type,
            subject_pose=task.subject_pose,
            flip_x=task.flip_x,
            flip_y=task.flip_y,
            flip_z=task.flip_z,
            hook_args=hook_args,
        )
        if isinstance(affine, tuple):
            idx = int(task.slicepack_index or 0)
            if idx < 0 or idx >= len(affine):
                idx = 0
            affine = affine[idx]
        if affine is not None:
            try:
                affine = getattr(affine, "tolist", lambda: affine)()
            except Exception:
                pass
        return affine

    return _memo(key, compute)


def _process_load_volume(task: LoadVolumeRequest, output_queue: multiprocessing.Queue) -> None:
    try:
        loader = _get_loader(task.path)
        logger.debug(
            "Load volume: scan=%s reco=%s frame_start=%s frame_count=%s slicepack=%s space=%s",
            task.scan_id,
            task.reco_id,
            task.frame_start,
            task.frame_count,
            task.slicepack_index,
            task.space,
        )
        enable_hook = bool(task.hook_name)
        scan = _ensure_hook_state(loader, task.scan_id, enable_hook=enable_hook)
        hook_args = task.hook_args or {}
        reco_key = (task.path, task.scan_id, task.reco_id)
        # C9: first free what the layers no longer shown hold, then count what stays.
        _release_others(task.keep, reco_key)
        data_kwargs = _filter_hook_kwargs(scan.get_dataobj, hook_args)
        # flip_* are affine-only options; never pass them to get_dataobj.
        for key in ("flip_x", "flip_y", "flip_z"):
            data_kwargs.pop(key, None)
        if task.memory_limit_bytes > 0 and not task.memory_confirmed and reco_key not in _held_recos:

            def expected_size() -> Optional[int]:
                if enable_hook:
                    # a hook can change shape and dtype: ask the hook first (C9)
                    hooked = _hook_output_nbytes(scan, task.reco_id, data_kwargs)
                    if hooked is not None:
                        return hooked
                return _expected_nbytes(scan, task.reco_id)

            expected = _memo(("nbytes",) + reco_key + _hook_key(task.hook_name, hook_args), expected_size)
            held_other = int(sum(v for k, v in _held_recos.items() if k != reco_key))
            held_other += max(int(task.other_held_bytes or 0), 0)  # array layers held by main
            if isinstance(expected, int) and expected + held_other > task.memory_limit_bytes:
                logger.info(
                    "Load needs confirmation: %s bytes + %s held > limit %s",
                    expected,
                    held_other,
                    task.memory_limit_bytes,
                )
                output_queue.put(
                    LoadVolumeResult(
                        job_id=task.job_id,
                        shm_name=None,
                        shape=(),
                        dtype="",
                        needs_confirm=True,
                        estimated_bytes=expected,
                        limit_bytes=task.memory_limit_bytes,
                        held_bytes=held_other,
                    )
                )
                return
        if hook_args:
            logger.debug("Viewer hook args=%s filtered_data=%s", hook_args, data_kwargs)
        num_cycles = None
        allow_cycle_slice = False
        try:
            image_info = getattr(scan, "image_info", {}).get(task.reco_id)
        except Exception:
            image_info = None
        if isinstance(image_info, dict):
            if image_info.get("num_cycles") is not None:
                num_cycles = int(image_info.get("num_cycles") or 0)
            allow_cycle_slice = image_info.get("dataobj") is None
        if num_cycles is None:
            try:
                meta_info = brkapi.image_resolver.resolve(scan, task.reco_id, load_data=False)
                if isinstance(meta_info, dict) and meta_info.get("num_cycles") is not None:
                    num_cycles = int(meta_info.get("num_cycles") or 0)
                if isinstance(meta_info, dict) and meta_info.get("dataobj") is None:
                    allow_cycle_slice = True
            except Exception:
                pass
        if num_cycles is not None and num_cycles > 1:
            allow_cycle_slice = True
        data = None
        # frame_start and frame_count both None = all frames (what the viewer sends when a
        # converter hook is on, and the slider then only redraws, WI-0077). Never turn that
        # into one frame: a hook such as sordino honours ``frames=``.
        want_all_frames = task.frame_start is None and task.frame_count is None
        if num_cycles is not None and num_cycles > 1 and allow_cycle_slice and not want_all_frames:
            try:
                frame_axis = _memo(
                    ("axis",) + reco_key + _hook_key(task.hook_name, hook_args),
                    lambda: _frame_axis_number(scan, task.reco_id),
                )
                data = _read_frame_block(
                    scan,
                    task.reco_id,
                    task.frame_start,
                    task.frame_count,
                    frame_axis=frame_axis,
                    **data_kwargs,
                )
            except ValueError as exc:
                if "split:" not in str(exc) and "cycle" not in str(exc):
                    raise
                data = None
        if data is None:
            data = scan.get_dataobj(
                task.reco_id,
                **data_kwargs,
            )
        if data is None:
            output_queue.put(
                LoadVolumeResult(
                    job_id=task.job_id,
                    shm_name=None,
                    shape=(),
                    dtype="",
                    frames=1,
                    error="No data returned",
                )
            )
            return
        slicepacks = len(data) if isinstance(data, tuple) else 1
        if isinstance(data, tuple):
            idx = int(task.slicepack_index or 0)
            if idx < 0 or idx >= len(data):
                idx = 0
            data = data[idx]
        frames = 1
        try:
            if hasattr(data, "shape") and len(data.shape) >= 4:
                frames = int(data.shape[3])
            elif num_cycles is not None and num_cycles > 1:
                # Only use num_cycles when data has no explicit frame axis.
                frames = int(num_cycles)
        except Exception:
            frames = 1
        logger.debug(
            "Load volume meta: num_cycles=%s allow_cycle_slice=%s data_shape=%s frames=%s",
            num_cycles,
            allow_cycle_slice,
            getattr(data, "shape", None),
            frames,
        )
        logger.debug("Load volume result: shape=%s slicepacks=%s frames=%s", getattr(data, "shape", None), slicepacks, frames)
        affine = _affine_for_request(scan, task, hook_args)
        # C9: what brkraw keeps for this reco is the one copy the worker holds.
        _held_recos[reco_key] = _kept_nbytes(scan, task.reco_id)
        _held_scans[reco_key] = scan
        shm_name = create_shared_array(data)
        out_shape, out_dtype = tuple(cast(np.ndarray, data).shape), str(data.dtype)
        del data  # the block now has the values; keep no second reference in this frame
        output_queue.put(
            LoadVolumeResult(
                job_id=task.job_id,
                shm_name=shm_name,
                shape=out_shape,
                dtype=out_dtype,
                affine=affine,
                slicepacks=slicepacks,
                frames=frames,
                error=None,
            )
        )
    except Exception as exc:
        logger.error("Load volume failed: %s", exc, exc_info=True)
        output_queue.put(
            LoadVolumeResult(
                job_id=task.job_id,
                shm_name=None,
                shape=(),
                dtype="",
                affine=None,
                slicepacks=1,
                frames=1,
                error=str(exc),
            )
        )


def _timecourse_view(scan: ScanLoader, task: TimecourseRequest) -> np.ndarray:
    """The held reco as a view on the displayed (RAS-reoriented) grid; nothing is copied.

    brkraw keeps a fully read reco in ``image_info`` (the one copy the worker holds, C9);
    the reorientation is flips and a transpose, so the result is a view of that array.
    """
    data = scan.get_dataobj(task.reco_id)
    if data is None:
        raise ValueError("No data returned")
    if isinstance(data, tuple):
        idx = int(task.slicepack_index or 0)
        data = data[idx if 0 <= idx < len(data) else 0]
    key = (
        "tc-affine",
        task.path,
        task.scan_id,
        task.reco_id,
        task.space,
        task.subject_type,
        task.subject_pose,
        bool(task.flip_x),
        bool(task.flip_y),
        bool(task.flip_z),
        int(task.slicepack_index or 0),
    )

    def compute():
        affine = _resolve_affine_for_space(
            scan,
            reco_id=task.reco_id,
            space=task.space,
            subject_type=task.subject_type,
            subject_pose=task.subject_pose,
            flip_x=task.flip_x,
            flip_y=task.flip_y,
            flip_z=task.flip_z,
            hook_args={},
        )
        if isinstance(affine, tuple):
            idx = int(task.slicepack_index or 0)
            affine = affine[idx if 0 <= idx < len(affine) else 0]
        return None if affine is None else np.asarray(affine, dtype=float)

    affine = _memo(key, compute)
    arr = np.asarray(data)
    if affine is None:
        return arr
    from brkraw_viewer.utils.orientation import reorient_to_ras

    view, _ = reorient_to_ras(arr, affine)
    return view


def _roi_timecourse(task: TimecourseRequest, view: np.ndarray) -> TimecourseResult:
    """Per-frame mean over a 2D mask on one display slice (C6 4D statistics, C9 in the worker).

    Reads only the masked voxels of that slice (mask voxels x frames), never the volume.
    NaN or infinite values are left out per frame; a frame with none left gives NaN.
    """
    axis = int(task.roi_axis if task.roi_axis is not None else 2)
    if axis not in (0, 1, 2):
        raise ValueError(f"roi_axis must be 0, 1 or 2, got {axis}")
    index = int(task.roi_index)
    if not 0 <= index < view.shape[axis]:
        raise ValueError(f"roi_index {index} is outside the data {view.shape[:3]}")
    mask = np.asarray(task.roi_mask, dtype=bool)
    cut: list = [slice(None)] * view.ndim
    cut[axis] = index
    plane = view[tuple(cut)]  # (a, b, frames); basic slicing is a view (np.take would copy)
    if mask.shape != plane.shape[:2]:
        raise ValueError(f"roi_mask shape {mask.shape} does not match the slice {plane.shape[:2]}")
    picked = np.asarray(plane[mask], dtype=np.float64)  # (n_mask, frames): only the ROI
    finite = np.isfinite(picked)
    counts = finite.sum(axis=0)
    sums = np.where(finite, picked, 0.0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return TimecourseResult(
        job_id=task.job_id,
        values=[float(v) for v in means],
        index=tuple(task.index),
        frames=int(view.shape[3]),
        error=None,
        n_mask=int(mask.sum()),
        n_per_frame=[int(c) for c in counts],
    )


def _process_timecourse(task: TimecourseRequest, output_queue: multiprocessing.Queue) -> None:
    """One voxel's values over the frames, from the held array (C9: no file, no full copy)."""
    try:
        loader = _get_loader(task.path)
        scan = _ensure_hook_state(loader, task.scan_id, enable_hook=False)
        view = _timecourse_view(scan, task)
        reco_key = (task.path, task.scan_id, task.reco_id)
        _held_recos[reco_key] = max(_held_recos.get(reco_key, 0), _kept_nbytes(scan, task.reco_id))
        _held_scans[reco_key] = scan
        if view.ndim < 4:
            raise ValueError("Timecourse requires 4D data.")
        while view.ndim > 4:  # axes after the 4th: the requested index, as for a voxel
            extra = task.extra_indices[view.ndim - 5] if (view.ndim - 5) < len(task.extra_indices) else 0
            view = view[..., min(max(int(extra), 0), view.shape[-1] - 1)]
        if task.roi_mask is not None:
            output_queue.put(_roi_timecourse(task, view))
            return
        xi, yi, zi = (int(v) for v in task.index)
        for axis, value in enumerate((xi, yi, zi)):
            if not 0 <= value < view.shape[axis]:
                raise ValueError(f"index {task.index} is outside the data {view.shape[:3]}")
        slicer: list = [xi, yi, zi, slice(None)]
        for i in range(4, view.ndim):
            extra = task.extra_indices[i - 4] if (i - 4) < len(task.extra_indices) else 0
            slicer.append(min(max(int(extra), 0), view.shape[i] - 1))
        series = np.asarray(view[tuple(slicer)], dtype=np.float64).reshape(-1)
        output_queue.put(
            TimecourseResult(
                job_id=task.job_id,
                values=series.tolist(),
                index=(xi, yi, zi),
                frames=int(view.shape[3]),
                error=None,
            )
        )
    except Exception as exc:
        logger.error("Timecourse failed: %s", exc, exc_info=True)
        output_queue.put(
            TimecourseResult(job_id=task.job_id, values=None, index=tuple(task.index), frames=1, error=str(exc))
        )


def _filter_hook_kwargs(func, hook_kwargs: dict) -> dict:
    if not hook_kwargs:
        return {}
    try:
        import inspect

        sig = inspect.signature(func)
    except Exception:
        return {}
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return dict(hook_kwargs)
    allowed = {param.name for param in sig.parameters.values()}
    return {k: v for k, v in hook_kwargs.items() if k in allowed}


def _resolve_affine_for_space(
    scan,
    *,
    reco_id: int,
    space: str,
    subject_type: Optional[str],
    subject_pose: Optional[str],
    flip_x: bool,
    flip_y: bool,
    flip_z: bool,
    hook_args: dict,
):
    affine_kwargs = _filter_hook_kwargs(scan.get_affine, hook_args or {})
    affine_kwargs["flip_x"] = flip_x
    affine_kwargs["flip_y"] = flip_y
    affine_kwargs["flip_z"] = flip_z
    selected_space = (space or "scanner").strip()
    if selected_space not in {"raw", "scanner", "subject_ras"}:
        selected_space = "scanner"

    space_candidates = [selected_space]
    if selected_space == "subject_ras":
        space_candidates.extend(["subject", "scanner"])

    for space_candidate in space_candidates:
        try:
            affine = scan.get_affine(
                reco_id,
                space=space_candidate,
                override_subject_type=subject_type,
                override_subject_pose=subject_pose,
                **affine_kwargs,
            )
            if affine is not None:
                return affine
        except Exception:
            continue

    try:
        return scan.get_affine(
            reco_id,
            space="raw",
            override_subject_type=None,
            override_subject_pose=None,
            **affine_kwargs,
        )
    except Exception:
        return None


def _process_registry(task: RegistryRequest, output_queue: multiprocessing.Queue) -> None:
    try:
        if task.action == "add":
            added, skipped = registry_service.register_paths([Path(p) for p in task.paths])
            output_queue.put(RegistryResult(job_id=task.job_id, action=task.action, added=added, skipped=skipped))
            return
        if task.action == "remove":
            removed = registry_service.unregister_paths([Path(p) for p in task.paths])
            output_queue.put(RegistryResult(job_id=task.job_id, action=task.action, removed=removed))
            return
        if task.action == "scan":
            added, skipped = registry_service.scan_registry([Path(p) for p in task.paths])
            output_queue.put(RegistryResult(job_id=task.job_id, action=task.action, added=added, skipped=skipped))
            return
        output_queue.put(
            RegistryResult(job_id=task.job_id, action=task.action, error=f"Unknown action: {task.action}")
        )
    except Exception as exc:
        output_queue.put(RegistryResult(job_id=task.job_id, action=task.action, error=str(exc)))
