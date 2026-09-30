from __future__ import annotations

import datetime as dt
import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Union, Callable, Sequence, cast

from .helper import (
    flatten_keys as _flatten_keys,
    filter_layout_keys as _filter_layout_keys,
    format_study_date as _format_study_date,
    lookup_nested as _lookup_nested,
    format_value as _format_value,
)

from .dataset import DatasetController
from ..protocols import ViewerView, TaskPopup
from ..state import AppState
from ..services.viewer_config import load_viewer_config
from ..services.worker_manager import WorkerManager
from ..services.registry import load_registry
from ..workers.shm import release_shared_array
from ..workers.protocol import (
    ConvertRequest,
    ConvertResult,
    LoadVolumeRequest,
    LoadVolumeResult,
    TimecourseCacheRequest,
    TimecourseCacheResult,
    RegistryRequest,
    RegistryResult,
)

from brkraw import api as brkapi
from brkraw.api.types import SubjectType, SubjectPose, AffineSpace
from brkraw_viewer.utils.orientation import reorient_to_ras
from brkraw.api.types import (
    SubjectType,
    SubjectPose,
    AffineSpace,
)
import hashlib

import numpy as np
import logging
logger = logging.getLogger(__name__)


DEFAULT_MEMORY_LIMIT_MB = 1024


def _memory_limit_bytes_from_config(cfg: dict) -> int:
    """``viewer.cache.memory_limit_mb`` in bytes; 0 = never ask; bad values use the default."""
    cache = cfg.get("cache", {}) if isinstance(cfg, dict) else {}
    value = cache.get("memory_limit_mb", DEFAULT_MEMORY_LIMIT_MB) if isinstance(cache, dict) else DEFAULT_MEMORY_LIMIT_MB
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = DEFAULT_MEMORY_LIMIT_MB
    return max(int(value * 1024 * 1024), 0)


def _stat_stamp(path: Path) -> str:
    st = path.stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def _source_stamp(path: Optional[Path], scan_id: Optional[int], reco_id: Optional[int]) -> str:
    """Change time and size of the data the timecourse cache was built from.

    Zip/archive: the file itself. Folder: the reco's 2dseq and visu_pars (falls back to
    the folder). Missing files give ``"none"`` so the key still works.
    """
    if path is None:
        return "none"
    p = Path(path)
    try:
        if p.is_file():
            return _stat_stamp(p)
        reco_dir = p / str(scan_id) / "pdata" / str(reco_id)
        parts = [_stat_stamp(f) for f in (reco_dir / "2dseq", reco_dir / "visu_pars") if f.exists()]
        return "|".join(parts) if parts else _stat_stamp(p)
    except OSError:
        return "none"


class ViewerController:
    def __init__(self, *, dataset: Optional[DatasetController] = None) -> None:
        self.state = AppState()
        self.dataset = dataset or DatasetController()
        self._view: Optional[ViewerView] = None
        cfg = load_viewer_config()
        self.state.settings.worker_popup = bool(cfg.get("worker", {}).get("popup", True))
        self._worker = WorkerManager(
            on_convert_result=self._on_convert_result,
            on_volume_result=self._on_volume_result,
            on_timecourse_cache_result=self._on_timecourse_cache_result,
            on_registry_result=self._on_registry_result,
        )
        self._popups: dict[str, TaskPopup] = {}
        self._memory_limit_bytes = _memory_limit_bytes_from_config(cfg)
        # (path, scan, reco) the user chose to load / not to load although over the limit.
        self._memory_confirmed: set[tuple] = set()
        self._memory_declined: set[tuple] = set()
        self._registry_jobs: dict[str, str] = {}
        self._viewer_volume: Optional[object] = None
        self._viewer_raw_volume: Optional[object] = None
        self._viewer_raw_affine: Optional[object] = None
        self._viewer_shape: Optional[tuple[int, ...]] = None
        self._viewer_res: tuple[float, float, float] = (1.0, 1.0, 1.0)
        self._viewer_fov: Optional[tuple[float, float, float]] = None
        self._viewer_job_id: Optional[str] = None
        self._viewer_hook_enabled = False
        self._viewer_hook_name: Optional[str] = None
        self._viewer_hook_args: Optional[dict] = None
        self._viewer_hook_locked: bool = False
        self._hook_args_by_name: dict[str, dict] = {}
        self._timecourse_window = None
        self._timecourse_plot = None
        self._timecourse_cache_path: Optional[str] = None
        self._viewer_space_listeners: list[Callable[[str], None]] = []
        self._timecourse_cache_data: Optional[np.ndarray] = None
        self._timecourse_cache_job_id: Optional[str] = None
        self._frame_cache: "OrderedDict[int, dict]" = OrderedDict()
        self._frame_cache_limit = 8
        self._pending_frame_requests: dict[str, int] = {}
        self._frame_request_after_id: Optional[str] = None
        self._convert_hook_enabled: bool = True
        self._viewer_slicepacks = 1
        self._viewer_frames = 1
        self._convert_layout_source = "Config"
        self._convert_layout_auto = True
        self._convert_layout_template = ""
        self._convert_output_dir: Path = Path.cwd()
        self._context_map_path: Optional[str] = None
        self._convert_layout_cache_key: Optional[tuple] = None
        self._convert_use_viewer_orientation: bool = True

    def attach_view(self, view: ViewerView) -> None:
        self._view = view
        logger.debug("Attach view")
        self._sync_view()
        self._update_subject_summary()
        self._view.set_viewer_subject_enabled(self.state.viewer.space == "subject_ras")
        self._sync_convert_orientation_from_viewer()
        self._schedule_worker_poll()

    def _schedule_worker_poll(self) -> None:
        if self._view is None:
            return
        self._worker.check_results()
        self._view.schedule_poll(self._schedule_worker_poll, 200)

    def get_worker_log_queue(self):
        return self._worker.log_queue

    def _on_convert_result(self, result: ConvertResult) -> None:
        popup = self._popups.pop(result.job_id, None)
        if popup is not None and hasattr(popup, "finish"):
            try:
                popup.finish(success=result.error is None)
            except Exception:
                pass
        if popup is None and self._view is not None:
            message = (
                f"Convert completed: {len(result.saved_paths)} file(s)"
                if result.error is None
                else f"Convert failed: {result.error}"
            )
            try:
                self._view.notify_task_result("Convert", message, result.error is None)
            except Exception:
                pass
        if result.error:
            if self._view is not None:
                self._view.set_status(f"Convert failed: {result.error}")
        else:
            if self._view is not None:
                self._view.set_status(f"Convert completed: {len(result.saved_paths)} file(s)")

    def _on_volume_result(self, result: LoadVolumeResult) -> None:
        logger.debug(
            "Volume result: job=%s error=%s shape=%s slicepacks=%s frames=%s",
            result.job_id,
            result.error,
            result.shape,
            result.slicepacks,
            result.frames,
        )
        popup = self._popups.pop(result.job_id, None)
        if popup is not None and hasattr(popup, "finish"):
            try:
                popup.finish(success=result.error is None)
            except Exception:
                pass
        if result.error:
            if self._view is not None:
                self._view.set_status(f"Load failed: {result.error}")
            return
        if result.needs_confirm:
            self._on_large_load_notice(result)
            return
        if self._viewer_job_id and result.job_id != self._viewer_job_id:
            # Nobody will read this result: free its shared memory (WI-0068).
            release_shared_array(result.shm_name)
            return
        if result.shm_name is None:
            if self._view is not None:
                self._view.set_status("Load failed: empty result")
            return
        try:
            from ..workers.shm import read_shared_array

            arr, shm = read_shared_array(result.shm_name, result.shape, result.dtype)
            data = arr.copy()
            shm.close()
            try:
                shm.unlink()
            except Exception:
                pass
        except Exception as exc:
            release_shared_array(result.shm_name)
            if self._view is not None:
                self._view.set_status(f"Load failed: {exc}")
            return
        self._viewer_raw_volume = data
        self._viewer_raw_affine = result.affine
        data = self._reorient_viewer_volume()
        prev_shape = self._viewer_shape
        prev_frame = self.state.viewer.frame_index
        prev_frames = self._viewer_frames
        prev_slicepacks = self._viewer_slicepacks
        self._viewer_slicepacks = max(int(result.slicepacks or 1), 1)
        self._viewer_frames = max(int(result.frames or 1), 1)
        if self._viewer_frames <= 1:
            cycle_frames = self._resolve_cycle_frames()
            if (
                cycle_frames > self._viewer_frames
                and not (
                    cycle_frames == self._viewer_slicepacks
                    and (getattr(data, "ndim", 0) < 4 or getattr(data, "shape", (0, 0, 0, 0))[3] <= 1)
                )
            ):
                logger.debug("Override frames from cycle metadata: %s -> %s", self._viewer_frames, cycle_frames)
                self._viewer_frames = cycle_frames
        if self.state.viewer.slicepack_index >= self._viewer_slicepacks:
            self.state.viewer.slicepack_index = 0
        prev_empty = self._viewer_volume is None

        data = cast(np.ndarray, data)
        self._viewer_volume = data
        self._viewer_shape = data.shape if hasattr(data, "shape") else None
        if prev_empty or prev_shape != data.shape:
            self._reset_viewer_indices_from_shape(center=True)
        else:
            self._update_viewer_indices_from_shape()
        logger.debug(
            "Viewer index update: prev_shape=%s new_shape=%s prev_frames=%s new_frames=%s prev_slicepacks=%s new_slicepacks=%s frame=%s->%s",
            prev_shape,
            data.shape,
            prev_frames,
            self._viewer_frames,
            prev_slicepacks,
            self._viewer_slicepacks,
            prev_frame,
            self.state.viewer.frame_index,
        )
        frame_key = self._pending_frame_requests.pop(result.job_id, None)
        if frame_key is not None:
            self._frame_cache[frame_key] = {
                "volume": self._viewer_volume,
                "raw": self._viewer_raw_volume,
                "affine": self._viewer_raw_affine,
                "shape": self._viewer_shape,
                "frames": self._viewer_frames,
                "slicepacks": self._viewer_slicepacks,
                "res": self._viewer_res,
            }
            while len(self._frame_cache) > self._frame_cache_limit:
                self._frame_cache.popitem(last=False)
        else:
            self._frame_cache.clear()
        self._render_viewer_views()
        if self._view is not None:
            self._view.set_viewer_controls_enabled(True)
            self._view.set_status("Volume loaded.")

    def _memory_key(self) -> tuple:
        return (
            str(self.state.dataset.path),
            self.state.dataset.selected_scan_id,
            self.state.dataset.selected_reco_id,
        )

    def _forget_memory_choices(self) -> None:
        self._memory_confirmed.clear()
        self._memory_declined.clear()

    def _on_large_load_notice(self, result: LoadVolumeResult) -> None:
        """The worker did not load: the expected size is over the limit. Ask, then go on or stop."""
        if self._viewer_job_id and result.job_id != self._viewer_job_id:
            return
        estimated_mb = float(result.estimated_bytes or 0) / (1024 * 1024)
        limit_mb = float(result.limit_bytes or 0) / (1024 * 1024)
        key = self._memory_key()
        ask = getattr(self._view, "confirm_large_load", None)
        proceed = False
        if callable(ask):
            try:
                proceed = bool(ask(estimated_mb, limit_mb))
            except Exception:
                proceed = False
        if proceed:
            self._memory_confirmed.add(key)
            self._memory_declined.discard(key)
            self._request_viewer_volume()
            return
        self._memory_declined.add(key)
        if self._view is not None:
            self._view.set_status(
                f"Load cancelled: about {estimated_mb:.0f} MB is over the {limit_mb:.0f} MB limit "
                "(select the scan again to be asked again)."
            )

    def _memory_request_fields(self) -> dict:
        return {
            "memory_limit_bytes": self._memory_limit_bytes,
            "memory_confirmed": self._memory_key() in self._memory_confirmed,
        }

    def _on_timecourse_cache_result(self, result: TimecourseCacheResult) -> None:
        if self._timecourse_cache_job_id and result.job_id != self._timecourse_cache_job_id:
            return
        self._timecourse_cache_job_id = None
        logger.debug(
            "Timecourse cache result: job=%s error=%s path=%s shape=%s frames=%s",
            result.job_id,
            result.error,
            result.cache_path,
            result.shape,
            result.frames,
        )
        if result.error:
            if self._timecourse_plot is not None:
                self._timecourse_plot.set_message(f"Cache failed: {result.error}")
            if self._view is not None:
                self._view.set_status(f"Timecourse cache failed: {result.error}")
            return
        if not result.cache_path:
            if self._timecourse_plot is not None:
                self._timecourse_plot.set_message("Cache failed.")
            if self._view is not None:
                self._view.set_status("Timecourse cache failed.")
            return
        self._timecourse_cache_path = result.cache_path
        try:
            self._timecourse_cache_data = np.load(result.cache_path, mmap_mode="r")
        except Exception:
            self._timecourse_cache_data = None
            if self._timecourse_plot is not None:
                self._timecourse_plot.set_message("Cache load failed.")
            if self._view is not None:
                self._view.set_status("Timecourse cache failed.")
            return
        self._update_timecourse_plot()
        if self._view is not None:
            self._view.set_status("Timecourse cached.")
            try:
                current = self._view.get_selected_tab()
            except Exception:
                current = None
            if not current:
                self._view.select_tab("Viewer")

    def _resolve_cycle_frames(self) -> int:
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return 1
        scan = self.dataset.get_scan(int(sid))
        if scan is None:
            return 1
        try:
            image_info = getattr(scan, "image_info", {}).get(int(rid))
            if isinstance(image_info, dict) and image_info.get("num_cycles") is not None:
                return max(int(image_info.get("num_cycles") or 1), 1)
        except Exception:
            pass
        try:
            meta_info = brkapi.image_resolver.resolve(scan, int(rid), load_data=False)
            if isinstance(meta_info, dict) and meta_info.get("num_cycles") is not None:
                return max(int(meta_info.get("num_cycles") or 1), 1)
        except Exception:
            pass
        return 1

    def _on_registry_result(self, result: RegistryResult) -> None:
        action = self._registry_jobs.pop(result.job_id, result.action)
        if self._view is None:
            return
        if result.error:
            self._view.registry_set_status(f"{action} failed: {result.error}")
        else:
            if action == "remove":
                self._view.registry_set_status(f"Removed {result.removed}")
            elif action == "add":
                self._view.registry_set_status(f"Added {result.added}, skipped {result.skipped}")
            elif action == "scan":
                self._view.registry_set_status(f"Added {result.added}, skipped {result.skipped}")
            else:
                self._view.registry_set_status("Registry updated")
        self._view.registry_refresh()

    def start_convert(self, request: ConvertRequest) -> None:
        self._worker.submit(request)

    def _update_params_summary(self) -> None:
        if self._view is None:
            return
        sid = self.state.dataset.selected_scan_id
        if sid is None:
            self._viewer_fov = None
            self._view.set_params_summary({})
            return
        summary = self.dataset.params_summary(sid)
        self._view.set_params_summary(summary)
        self._viewer_fov = _parse_fov(summary.get("FOV (mm)") if isinstance(summary, dict) else None)

    def _update_viewer_indices_from_shape(self) -> None:
        shape = self._viewer_shape
        if not shape or len(shape) < 3:
            return
        x, y, z = shape[:3]
        st = self.state.viewer
        st.x_index = min(max(st.x_index, 0), max(x - 1, 0))
        st.y_index = min(max(st.y_index, 0), max(y - 1, 0))
        st.z_index = min(max(st.z_index, 0), max(z - 1, 0))
        if self._viewer_frames > 1:
            st.frame_index = min(max(st.frame_index, 0), max(self._viewer_frames - 1, 0))
        elif len(shape) >= 4:
            st.frame_index = min(max(st.frame_index, 0), max(shape[3] - 1, 0))
        extra_dims = list(shape[4:]) if len(shape) > 4 else []
        if not extra_dims:
            st.extra_indices = []
            return
        if len(st.extra_indices) != len(extra_dims):
            st.extra_indices = [0 for _ in extra_dims]
        for idx, size in enumerate(extra_dims):
            st.extra_indices[idx] = min(max(st.extra_indices[idx], 0), max(int(size) - 1, 0))

    def _reset_viewer_indices_from_shape(self, *, center: bool = False) -> None:
        shape = self._viewer_shape
        if not shape or len(shape) < 3:
            return
        x, y, z = shape[:3]
        st = self.state.viewer
        if center:
            st.x_index = max(x // 2, 0)
            st.y_index = max(y // 2, 0)
            st.z_index = max(z // 2, 0)
            if self._viewer_frames > 1:
                st.frame_index = min(max(st.frame_index, 0), max(self._viewer_frames - 1, 0))
            else:
                st.frame_index = 0
        else:
            st.x_index = min(max(st.x_index, 0), max(x - 1, 0))
            st.y_index = min(max(st.y_index, 0), max(y - 1, 0))
            st.z_index = min(max(st.z_index, 0), max(z - 1, 0))
        if self._viewer_frames > 1:
            st.frame_index = min(max(st.frame_index, 0), max(self._viewer_frames - 1, 0))
        elif len(shape) >= 4:
            st.frame_index = min(max(st.frame_index, 0), max(int(shape[3]) - 1, 0))
        extra_dims = list(shape[4:]) if len(shape) > 4 else []
        if extra_dims:
            st.extra_indices = [0 for _ in extra_dims]
        else:
            st.extra_indices = []

    def _render_viewer_views(self) -> None:
        if self._view is None:
            return
        import numpy as np

        vol = self._viewer_volume
        if vol is None:
            self._view.set_viewer_views({})
            self._view.set_viewer_value_display("[ - ]", plot_enabled=False)
            return
        logger.debug(
            "Render views: shape=%s frame=%s slicepack=%s",
            getattr(vol, "shape", None),
            self.state.viewer.frame_index,
            self.state.viewer.slicepack_index,
        )
        data = np.asarray(vol)
        rgb_candidate = bool(data.ndim == 4 and data.shape[3] == 3)
        extra_dims = list(data.shape[4:]) if data.ndim > 4 else []
        if data.ndim >= 4 and not (rgb_candidate and self.state.viewer.rgb_mode):
            frame_idx = min(max(self.state.viewer.frame_index, 0), data.shape[3] - 1)
            slices: list[slice | int] = [slice(None)] * data.ndim
            slices[3] = frame_idx
            if extra_dims:
                extra_indices = self.state.viewer.extra_indices or []
                for i, size in enumerate(extra_dims):
                    idx = extra_indices[i] if i < len(extra_indices) else 0
                    slices[4 + i] = min(max(int(idx), 0), max(int(size) - 1, 0))
            data = data[tuple(slices)]
        rgb_eligible = bool(rgb_candidate)
        if not rgb_eligible and self.state.viewer.rgb_mode:
            self.state.viewer.rgb_mode = False
        if self._view is not None:
            self._view.set_viewer_rgb_state(enabled=rgb_eligible, active=self.state.viewer.rgb_mode)
        if data.ndim < 3:
            return
        x, y, z = data.shape[:3]
        xi = min(max(self.state.viewer.x_index, 0), x - 1)
        yi = min(max(self.state.viewer.y_index, 0), y - 1)
        zi = min(max(self.state.viewer.z_index, 0), z - 1)
        frames = self._viewer_frames
        if rgb_eligible and self.state.viewer.rgb_mode:
            frames = 1
        slicepacks = self._viewer_slicepacks
        self._view.set_viewer_ranges(
            x=x,
            y=y,
            z=z,
            frames=frames,
            slicepacks=slicepacks,
            indices=(xi, yi, zi),
            frame=self.state.viewer.frame_index,
            slicepack=self.state.viewer.slicepack_index,
            extra_dims=extra_dims,
            extra_indices=self.state.viewer.extra_indices,
        )
        if data.ndim == 4 and data.shape[3] == 3 and self.state.viewer.rgb_mode:
            img_zy = data[xi, :, :, :]              # (y, z, 3)
            img_xy = data[:, :, zi, :].transpose(1, 0, 2)  # (y, x, 3)
            img_xz = data[:, yi, :, :].transpose(1, 0, 2)  # (z, x, 3)
        else:
            img_zy = data[xi, :, :]                 # (y, z)
            img_xy = data[:, :, zi].T               # (y, x)
            img_xz = data[:, yi, :].T               # (z, x)
        zoom = max(1.0, float(self.state.viewer.zoom))
        views = {
            "xy": img_xy,
            "xz": img_xz,
            "zy": img_zy,
        }
        # Voxel spacing in RAS order to keep viewport aspect aligned with affine.
        res_x, res_y, res_z = self._viewer_res
        # NOTE: FOV is kept for reference only; render scale uses affine-based spacing.
        # Viewport expects (row_res, col_res) to match the 2D image layout.
        # img_xy shape: (y, x), img_xz: (z, x), img_zy: (y, z)
        view_res = {
            "xy": (res_y, res_x),
            "xz": (res_z, res_x),
            "zy": (res_y, res_z),
        }
        crosshair = {
            "xy": (yi, xi),
            "xz": (zi, xi),
            "zy": (yi, zi),
        }
        # Blend fit->fill by zoom while damping overflow for highly anisotropic volumes.
        overflow_blend = 0.0
        if zoom > 1.0:
            try:
                axis_mm = (
                    float(x) * float(res_x),
                    float(y) * float(res_y),
                    float(z) * float(res_z),
                )
                max_axis = max(axis_mm)
                min_axis = min(axis_mm)
                ratio_scale = 0.0
                if max_axis > 0:
                    ratio_scale = max(0.0, min(1.0, (min_axis / max_axis) / 0.5))
                base_blend = max(0.0, min((zoom - 1.0) / 3.0, 1.0))
                overflow_blend = base_blend * ratio_scale
            except Exception:
                overflow_blend = 0.0
        self._view.set_viewer_views(
            views,
            indices=(xi, yi, zi),
            res=view_res,
            crosshair=crosshair,
            show_crosshair=self.state.viewer.show_crosshair,
            lock_scale=True,
            allow_overflow=overflow_blend > 0.0,
            overflow_blend=overflow_blend if overflow_blend > 0.0 else None,
            zoom_scale=zoom,
        )
        value_text, plot_enabled = _resolve_value_display(
            vol=np.asarray(self._viewer_volume),
            indices=(xi, yi, zi),
            frame=self.state.viewer.frame_index,
            extra_indices=self.state.viewer.extra_indices,
            rgb_mode=self.state.viewer.rgb_mode,
        )
        self._view.set_viewer_value_display(value_text, plot_enabled=plot_enabled)
        self._update_timecourse_plot(indices=(xi, yi, zi))
        if self._view is not None:
            space = self.state.viewer.space
            if space == "subject_ras":
                space_str = "Subject RAS"
            elif space == "scanner":
                space_str = "Scanner"
            else:
                space_str = space.title()
            
            hook_str = "Applied" if self._viewer_hook_enabled else "None"
            zoom_str = f"{zoom:.2f}x"
            rgb_str = "On" if self.state.viewer.rgb_mode else "Off"
            cross_str = "On" if self.state.viewer.show_crosshair else "Off"
            
            status = f"Space: {space_str} | Hook: {hook_str} | Zoom: {zoom_str} | RGB: {rgb_str} | Crosshair: {cross_str}"
            label = f"Slicepack {self.state.viewer.slicepack_index + 1}/{slicepacks}"
            self._view.set_viewer_status(f"{status} | {label}")

    def _clear_viewer_volume(self, *, status: Optional[str] = None) -> None:
        self._viewer_volume = None
        self._viewer_raw_volume = None
        self._viewer_raw_affine = None
        self._viewer_shape = None
        self._viewer_res = (1.0, 1.0, 1.0)
        self._viewer_fov = None
        self._clear_frame_cache()
        if self._view is None:
            return
        self._view.set_viewer_views({})
        self._view.set_viewer_value_display("[ - ]", plot_enabled=False)
        self._view.set_viewer_controls_enabled(False)
        if status:
            self._view.set_viewer_status(status)

    def _request_viewer_volume(self) -> None:
        if self.state.dataset.path is None:
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return
        if self._memory_key() in self._memory_declined:
            return
        job_id = f"viewer-load-{dt.datetime.now().timestamp()}"
        self._viewer_job_id = job_id
        logger.debug(
            "Request viewer volume: scan=%s reco=%s frame=%s slicepack=%s space=%s hook=%s",
            sid,
            rid,
            self.state.viewer.frame_index,
            self.state.viewer.slicepack_index,
            self.state.viewer.space,
            bool(self._viewer_hook_enabled),
        )
        frame_start = max(self.state.viewer.frame_index, 0)
        frame_count: Optional[int] = 1
        if self._viewer_hook_enabled:
            frame_start = None
            frame_count = None
        else:
            cycle_frames = self._resolve_cycle_frames()
            if cycle_frames <= 1 or (
                cycle_frames == self._viewer_slicepacks and self._viewer_frames <= 1
            ):
                frame_start = None
                frame_count = None
        self._pending_frame_requests = {}
        if frame_start is not None and frame_count == 1 and not self._viewer_hook_enabled:
            try:
                self._pending_frame_requests[job_id] = int(frame_start)
            except Exception:
                pass
        req = LoadVolumeRequest(
            job_id=job_id,
            path=str(self.state.dataset.path),
            scan_id=int(sid),
            reco_id=int(rid),
            frame_start=frame_start,
            frame_count=frame_count,
            hook_name=self._viewer_hook_name if self._viewer_hook_enabled else None,
            hook_args=self._viewer_hook_args if self._viewer_hook_enabled else None,
            slicepack_index=self.state.viewer.slicepack_index,
            space=self.state.viewer.space,
            subject_type=self.state.viewer.subject_type if self.state.viewer.space == "subject_ras" else None,
            subject_pose=self.state.viewer.subject_pose if self.state.viewer.space == "subject_ras" else None,
            flip_x=self.state.viewer.flip_x,
            flip_y=self.state.viewer.flip_y,
            flip_z=self.state.viewer.flip_z,
            **self._memory_request_fields(),
        )
        self._worker.submit(req)
        if self._view is not None:
            self._view.set_status("Loading volume...")

    def _request_timecourse_cache(self) -> None:
        if self.state.dataset.path is None:
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return
        if self._timecourse_cache_job_id is not None:
            if self._view is not None:
                self._view.set_status("Caching timecourse volume...")
            return
        cache_path = self._resolve_timecourse_cache_path()
        if self._timecourse_cache_path and self._timecourse_cache_path != cache_path:
            self._clear_timecourse_cache()
        self._timecourse_cache_path = cache_path
        job_id = f"timecourse-cache-{dt.datetime.now().timestamp()}"
        self._timecourse_cache_job_id = job_id
        req = TimecourseCacheRequest(
            job_id=job_id,
            path=str(self.state.dataset.path),
            scan_id=int(sid),
            reco_id=int(rid),
            cache_path=cache_path,
            slicepack_index=self.state.viewer.slicepack_index,
            space=self.state.viewer.space,
            subject_type=self.state.viewer.subject_type if self.state.viewer.space == "subject_ras" else None,
            subject_pose=self.state.viewer.subject_pose if self.state.viewer.space == "subject_ras" else None,
            flip_x=self.state.viewer.flip_x,
            flip_y=self.state.viewer.flip_y,
            flip_z=self.state.viewer.flip_z,
        )
        logger.debug(
            "Timecourse cache request: scan=%s reco=%s slicepack=%s space=%s path=%s",
            sid,
            rid,
            self.state.viewer.slicepack_index,
            self.state.viewer.space,
            cache_path,
        )
        self._worker.submit(req)
        if self._view is not None:
            self._view.set_status("Caching timecourse volume...")

    def _request_full_viewer_volume(self) -> None:
        if self.state.dataset.path is None:
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return
        if self._memory_key() in self._memory_declined:
            return
        job_id = f"viewer-full-{dt.datetime.now().timestamp()}"
        self._viewer_job_id = job_id
        req = LoadVolumeRequest(
            job_id=job_id,
            path=str(self.state.dataset.path),
            scan_id=int(sid),
            reco_id=int(rid),
            frame_start=None,
            frame_count=None,
            hook_name=None,
            hook_args=None,
            slicepack_index=self.state.viewer.slicepack_index,
            space=self.state.viewer.space,
            subject_type=self.state.viewer.subject_type if self.state.viewer.space == "subject_ras" else None,
            subject_pose=self.state.viewer.subject_pose if self.state.viewer.space == "subject_ras" else None,
            flip_x=self.state.viewer.flip_x,
            flip_y=self.state.viewer.flip_y,
            flip_z=self.state.viewer.flip_z,
            **self._memory_request_fields(),
        )
        self._worker.submit(req)
        if self._view is not None:
            self._view.set_status("Loading full volume...")

    def _update_subject_summary(self) -> None:
        if self._view is None:
            return
        info = self.dataset.study_info()
        study_id = _lookup_nested(info, ("Study", "ID"))
        subject_id = _lookup_nested(info, ("Subject", "ID"))
        study_date = _lookup_nested(info, ("Study", "Date"))
        summary_study_id = _format_value(study_id) if study_id not in (None, "") else "None"
        summary_subject_id = _format_value(subject_id) if subject_id not in (None, "") else "None"
        summary_study_date = _format_study_date(study_date) or "None"
        self._view.set_subject_summary(
            study_id=summary_study_id,
            subject_id=summary_subject_id,
            study_date=summary_study_date,
        )

    def _reset_viewer_hook_state(self) -> None:
        self._viewer_hook_locked = False
        self.state.viewer.hook_locked = False
        self._viewer_hook_enabled = False
        if self._view is not None:
            self._view.set_viewer_hook_state(
                self._viewer_hook_name or "None",
                self._viewer_hook_enabled,
                self._viewer_hook_args,
                allow_toggle=True,
            )

    def _resolve_timecourse_cache_path(self) -> str:
        base = Path.home() / ".brkraw" / "cache" / "viewer"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        parts = [
            "timecourse",
            "full",
            str(self.state.dataset.path or ""),
            str(self.state.dataset.selected_scan_id or ""),
            str(self.state.dataset.selected_reco_id or ""),
            str(self.state.viewer.space or ""),
            str(self.state.viewer.subject_type or ""),
            str(self.state.viewer.subject_pose or ""),
            str(int(self.state.viewer.flip_x)),
            str(int(self.state.viewer.flip_y)),
            str(int(self.state.viewer.flip_z)),
            str(int(self.state.viewer.slicepack_index)),
            # a changed source file must not reuse an old cache file (WI-0068)
            _source_stamp(
                self.state.dataset.path,
                self.state.dataset.selected_scan_id,
                self.state.dataset.selected_reco_id,
            ),
        ]
        key = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
        return str(base / f"{key}.npy")

    def _clear_timecourse_cache(self) -> None:
        if self._timecourse_cache_path:
            try:
                Path(self._timecourse_cache_path).unlink(missing_ok=True)
            except Exception:
                pass
        self._timecourse_cache_path = None
        self._timecourse_cache_data = None
        self._timecourse_cache_job_id = None

    def _clear_frame_cache(self) -> None:
        self._frame_cache.clear()
        self._pending_frame_requests = {}
        if self._view is not None and self._frame_request_after_id:
            try:
                _after_cancel = getattr(self._view, "after_cancel", None)
                if _after_cancel:
                    _after_cancel(self._frame_request_after_id)
            except Exception:
                pass
        self._frame_request_after_id = None

    def _schedule_frame_request(self) -> None:
        if self._view is None:
            self._request_viewer_volume()
            return
        if self._frame_request_after_id:
            try:
                _after_cancel = getattr(self._view, "after_cancel", None)
                if _after_cancel:
                    _after_cancel(self._frame_request_after_id)
            except Exception:
                pass
        _after = getattr(self._view, "after", None)
        if _after is None:
            return
        self._frame_request_after_id = _after(120, self._flush_frame_request)

    def _flush_frame_request(self) -> None:
        self._frame_request_after_id = None
        self._request_viewer_volume()

    def _apply_cached_frame(self, frame_index: int) -> bool:
        if frame_index not in self._frame_cache:
            return False
        entry = self._frame_cache.pop(frame_index)
        self._frame_cache[frame_index] = entry
        self._viewer_volume = entry.get("volume")
        self._viewer_raw_volume = entry.get("raw")
        self._viewer_raw_affine = entry.get("affine")
        self._viewer_shape = entry.get("shape")
        self._viewer_frames = entry.get("frames", self._viewer_frames)
        self._viewer_slicepacks = entry.get("slicepacks", self._viewer_slicepacks)
        self._viewer_res = entry.get("res", self._viewer_res)
        self._update_viewer_indices_from_shape()
        self._render_viewer_views()
        return True

    def _refresh_hook_state_for_scan(self, scan_id: int) -> None:
        hook_name = self.dataset.get_converter_hook_name(scan_id)
        logger.debug("Hook state for scan %s: name=%s", scan_id, hook_name)
        if hook_name:
            self._viewer_hook_name = hook_name
        else:
            self._viewer_hook_name = None
        self._viewer_hook_enabled = False
        self._viewer_hook_args = self._hook_args_by_name.get(self._viewer_hook_name or "", None)
        if self._view is not None:
            self._view.set_viewer_hook_state(
                self._viewer_hook_name or "None",
                self._viewer_hook_enabled,
                self._viewer_hook_args,
                allow_toggle=not self._viewer_hook_locked,
            )
            convert_enabled = self._convert_hook_enabled and bool(self._viewer_hook_name)
            self._view.set_convert_hook_state(self._viewer_hook_name or "None", convert_enabled, self._viewer_hook_args)
            self._view.refresh_addons()

    def _refresh_convert_layout(self) -> None:
        if self._view is None:
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or self.state.dataset.path is None:
            self._convert_layout_cache_key = None
            self._view.set_convert_layout_fields(
                rule="",
                info_spec="",
                metadata_spec="",
                context_map="",
                template="",
                slicepack_suffix=brkapi.config.output_slicepack_suffix(root=None),
            )
            self._view.set_convert_layout_keys([])
            return
        template, _, context_map = self._resolve_layout_sources(
            layout_source=self._convert_layout_source,
            layout_auto=self._convert_layout_auto,
            layout_template=self._convert_layout_template,
        )
        base_key = (
            int(sid),
            int(rid) if rid is not None else None,
            self._convert_layout_source,
            bool(self._convert_layout_auto),
            self._convert_layout_template,
            context_map,
        )
        if self._convert_layout_cache_key == base_key:
            return
        slicepack_suffix = brkapi.config.output_slicepack_suffix(root=None)
        rule_path, rule_name = self.resolve_addon_rule_file("info_spec")
        info_spec_path = self.resolve_addon_spec("info_spec")
        metadata_spec_path = self.resolve_addon_spec("metadata_spec")
        self._convert_layout_cache_key = base_key
        rule_label = rule_name or ""
        info_label = self._display_spec_path(info_spec_path, default_label="Default")
        meta_label = self._display_spec_path(metadata_spec_path, default_label="")
        context_label = self._display_context_map_path(context_map)
        self._view.set_convert_layout_fields(
            rule=rule_label,
            info_spec=info_label,
            metadata_spec=meta_label,
            context_map=context_label,
            template=template,
            slicepack_suffix=slicepack_suffix,
        )
        keys: list[str] = []
        try:
            info = self.dataset.layout_info(
                int(sid),
                int(rid) if rid is not None else None,
                context_map=context_map,
                info_spec=info_spec_path or None,
                metadata_spec=metadata_spec_path or None,
            )
            if info:
                base_keys = set(_flatten_keys(info))
                base_keys |= {"scan_id", "reco_id", "Counter"}
                keys = sorted(_filter_layout_keys(base_keys))
        except Exception:
            keys = []
        self._view.set_convert_layout_keys(keys)

    def _display_spec_path(self, path: Optional[str], *, default_label: str) -> str:
        if not path:
            return default_label
        try:
            installed = brkapi.addon_manager.list_installed(root=None)
        except Exception:
            installed = {}
        specs = installed.get("specs", []) if isinstance(installed, dict) else []
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            file_name = str(spec.get("file") or "").strip()
            name = str(spec.get("name") or "").strip()
            kind = str(spec.get("category") or spec.get("kind") or "").strip()
            spec_path = None
            if file_name:
                spec_path = brkapi.addon_manager.resolve_spec_reference(file_name, category=kind or None, root=None)
            if spec_path is None and name:
                spec_path = brkapi.addon_manager.resolve_spec_reference(name, category=kind or None, root=None)
            if spec_path and str(spec_path) == str(path):
                return file_name or Path(spec_path).name
        return Path(path).name

    def _display_context_map_path(self, path: Optional[str]) -> str:
        if not path:
            return ""
        try:
            return Path(path).name
        except Exception:
            return str(path)

    def _resolve_layout_sources(
        self,
        *,
        layout_source: str,
        layout_auto: bool,
        layout_template: str,
        context_map: Optional[str] = None,
    ) -> tuple[str, Optional[list], Optional[str]]:
        layout_source = (layout_source or "").strip()
        layout_template = (layout_template or "").strip()
        config_template = brkapi.config.layout_template(root=None) or ""
        config_entries = brkapi.config.layout_entries(root=None)
        context_map = context_map or self._context_map_path
        template = ""
        entries = None

        def _resolve_context_layout() -> tuple[str, Optional[list]]:
            # brkraw 0.6 context maps carry only __meta__.layout_template (no layout_entries)
            if not context_map:
                return "", None
            try:
                meta = self.dataset.context_map_meta(context_map)
            except Exception:
                return "", None
            map_template = meta.get("layout_template")
            if isinstance(map_template, str) and map_template.strip():
                return map_template.strip(), None
            return "", None

        if layout_auto:
            if context_map:
                template, entries = _resolve_context_layout()
            if not template and not entries:
                template = config_template
                entries = config_entries if not template else None
        else:
            if layout_source == "GUI template":
                template = layout_template
                entries = None
                context_map = None
            elif layout_source == "Context map":
                template, entries = _resolve_context_layout()
                if not template and not entries:
                    template = config_template
                    entries = config_entries if not template else None
                    context_map = None
            else:
                template = config_template
                entries = config_entries if not template else None
                context_map = None

        return template or "", entries, context_map

    def on_convert_layout_change(self, layout_source: str, layout_auto: bool, layout_template: str) -> None:
        self._convert_layout_source = (layout_source or "").strip() or "Config"
        self._convert_layout_auto = bool(layout_auto)
        self._convert_layout_template = layout_template or ""
        self._refresh_convert_layout()

    def _sync_view(self) -> None:
        if self._view is None:
            return

        logger.debug("Sync view (selected scan=%s reco=%s)", self.state.dataset.selected_scan_id, self.state.dataset.selected_reco_id)
        self._view.set_dataset_path(self.state.dataset.path)
        self._view.set_scan_list(self.dataset.scan_entries())

        if self.state.dataset.selected_scan_id is None:
            self._view.set_reco_list([])
        else:
            self._view.set_reco_list(self.dataset.reco_entries(self.state.dataset.selected_scan_id))

        self._view.set_scan_selected(self.state.dataset.selected_scan_id)
        self._view.set_reco_selected(self.state.dataset.selected_reco_id)

        if self.state.dataset.is_open and self.state.dataset.path:
            self._view.set_status(f"Dataset open: {self.state.dataset.path}")
        else:
            self._view.set_status("No dataset open.")
        self._view.set_tabs_enabled(bool(self.state.dataset.is_open and self.state.dataset.path))

        # Avoid refreshing hook state here; selection handlers take care of it.

    # ----- UI actions -----

    def action_open_dataset(self, path: Path) -> None:
        logger.debug("Open dataset: %s", path)
        summary = self.dataset.open_dataset(path)
        self._forget_memory_choices()
        self._reset_viewer_hook_state()
        self._clear_timecourse_cache()
        self._clear_frame_cache()
        self._convert_layout_cache_key = None
        self.state.dataset.path = summary.path
        self.state.dataset.is_open = True
        self.state.dataset.selected_scan_id = None
        self.state.dataset.selected_reco_id = None

        if self._view is not None:
            self._view.set_status(f"Opened: {summary.path}")
        self._sync_view()
        self._update_params_summary()
        self._update_subject_summary()
        scan_entries = self.dataset.scan_entries()
        if scan_entries:
            self.action_select_scan(scan_entries[0][0])
        else:
            self._clear_viewer_volume(status="No image loaded.")

    def action_close_dataset(self) -> None:
        self.dataset.close_dataset()
        self._convert_layout_cache_key = None
        self.state.dataset.path = None
        self.state.dataset.is_open = False
        self.state.dataset.selected_scan_id = None
        self.state.dataset.selected_reco_id = None
        self._viewer_hook_enabled = False
        self._viewer_hook_name = None
        self._viewer_hook_args = None
        self._viewer_hook_locked = False
        self.state.viewer.hook_locked = False
        self._clear_timecourse_cache()
        self._clear_viewer_volume(status="No dataset open.")
        self._sync_view()
        self._update_params_summary()
        self._update_subject_summary()
        if self._view is not None:
            self._view.set_viewer_hook_state("None", False, None, allow_toggle=True)
            self._view.set_convert_hook_state("None", False, None)

    def action_select_scan(self, scan_id: int) -> None:
        logger.debug("Select scan: %s", scan_id)
        self.state.dataset.selected_scan_id = int(scan_id)
        self.state.dataset.selected_reco_id = None
        self._memory_declined.clear()
        self._reset_viewer_hook_state()
        self._clear_timecourse_cache()
        self._clear_viewer_volume(status="No image loaded.")
        self.dataset.materialize_scan(int(scan_id))
        if self._view is not None:
            self._view.set_status(f"Selected scan: {scan_id}")
        # Avoid full _sync_view to prevent redundant scan list rebuilds.
        if self._view is not None:
            self._view.set_reco_list(self.dataset.reco_entries(int(scan_id)))
            self._view.set_scan_selected(int(scan_id))
            self._view.set_reco_selected(None)
        self._update_params_summary()
        self._update_subject_summary()
        self._refresh_hook_state_for_scan(int(scan_id))
        self._refresh_convert_layout()
        reco_entries = self.dataset.reco_entries(int(scan_id))
        if reco_entries:
            self.action_select_reco(reco_entries[0][0])

    def action_select_reco(self, reco_id: int) -> None:
        logger.debug("Select reco: %s", reco_id)
        self.state.dataset.selected_reco_id = int(reco_id)
        self._memory_declined.clear()
        self._reset_viewer_hook_state()
        self._clear_timecourse_cache()
        self._clear_frame_cache()
        if self._view is not None:
            sid = self.state.dataset.selected_scan_id
            self._view.set_status(f"Selected scan {sid} reco {reco_id}")
        self._apply_subject_defaults_from_reco()
        if self._view is not None:
            self._view.set_reco_selected(int(reco_id))
        self._update_params_summary()
        self._update_subject_summary()
        self._refresh_convert_layout()
        self._request_viewer_volume()

    # ----- MainWindow callback handlers -----

    def on_select_scan(self, scan_id: int) -> None:
        self.action_select_scan(scan_id)

    def on_select_reco(self, reco_id: int) -> None:
        self.action_select_reco(reco_id)

    def on_open_folder(self) -> None:
        if self._view is None:
            return
        path = self._view.prompt_open_folder()
        if path:
            self.action_open_dataset(path)

    def on_open_archive(self) -> None:
        if self._view is None:
            return
        path = self._view.prompt_open_archive()
        if path:
            self.action_open_dataset(path)

    def on_refresh(self) -> None:
        current_tab = None
        if self._view is not None:
            try:
                current_tab = self._view.get_selected_tab()
            except Exception:
                current_tab = None
        current_path = self.state.dataset.path
        current_scan = self.state.dataset.selected_scan_id
        current_reco = self.state.dataset.selected_reco_id

        cfg = load_viewer_config()
        self.state.settings.worker_popup = bool(cfg.get("worker", {}).get("popup", True))
        self._memory_limit_bytes = _memory_limit_bytes_from_config(cfg)

        if current_path:
            try:
                summary = self.dataset.open_dataset(current_path)
                self.state.dataset.path = summary.path
                self.state.dataset.is_open = True
            except Exception as exc:
                if self._view is not None:
                    self._view.set_status(f"Refresh failed: {exc}")
                return
        self._convert_layout_cache_key = None
        self._sync_view()
        if self._view is not None:
            self._view.refresh_addons()
        if current_path and current_scan is not None:
            try:
                self.action_select_scan(int(current_scan))
                if current_reco is not None:
                    self.action_select_reco(int(current_reco))
            except Exception:
                pass
        if self._view is not None and current_tab:
            try:
                self._view.select_tab(current_tab)
            except Exception:
                pass
        if self._view is not None:
            self._view.set_status("Refreshed.")

    def on_close(self) -> None:
        self._check_disk_cache_on_exit()

    def _check_disk_cache_on_exit(self) -> None:
        try:
            import tkinter as tk
            from pathlib import Path
            from tkinter import messagebox

            from brkraw.core import cache as cache_core

            config = brkapi.config.load_config(root=None) or {}
            cache_cfg = config.get("viewer", {}).get("cache", {})
            cache_path_str = cache_cfg.get("path")

            cache_path = None
            if isinstance(cache_path_str, str) and cache_path_str.strip():
                cache_path = Path(cache_path_str)
                if not cache_path.is_absolute():
                    cache_path = brkapi.config.resolve_root(None) / cache_path

            if cache_path is None:
                cache_path = brkapi.config.resolve_root(None) / "cache"

            info = cache_core.get_info(path=cache_path)
            total_size = info.get("size", 0) or 0
            count = info.get("count", 0) or 0
            if total_size <= 0:
                return

            unit = "B"
            size_val = float(total_size)
            for u in ["B", "KB", "MB", "GB", "TB"]:
                unit = u
                if size_val < 1024:
                    break
                size_val /= 1024
            size_str = f"{size_val:.2f} {unit}"

            parent = None
            try:
                if self._view is not None and hasattr(self._view, "winfo_toplevel"):
                    parent = self._view.winfo_toplevel()
            except Exception:
                parent = None
            parent = cast(tk.Misc, parent)
            if messagebox.askyesno(
                "Clear Cache",
                f"Disk cache at:\n{cache_path}\n\nSize: {size_str} ({count} files)\n\nClear this cache?",
                parent= parent,
            ):
                cache_core.clear(path=cache_path)
                messagebox.showinfo("Cache Cleared", f"Cleared cache at {cache_path}", parent=parent)

        except Exception as exc:
            logger.warning("Failed to check/clear disk cache: %s", exc)

    def on_tab_built(self, title: str) -> None:
        if title != "Viewer":
            return
        if self._viewer_volume is not None:
            self._schedule_viewer_render(0)
            self._schedule_viewer_render(120)
            return
        if (
            self.state.dataset.path is not None
            and self.state.dataset.selected_scan_id is not None
            and self.state.dataset.selected_reco_id is not None
        ):
            self._request_viewer_volume()

    def on_tab_detached(self, title: str) -> None:
        if title != "Viewer":
            return
        if self._viewer_volume is not None:
            self._schedule_viewer_render(0)
            self._schedule_viewer_render(120)

    def _schedule_viewer_render(self, delay_ms: int) -> None:
        if self._view is None:
            return
        try:
            delay = max(int(delay_ms), 0)
        except Exception:
            delay = 0
        self._view.schedule_poll(self._render_viewer_views, delay)

    def on_open_registry(self) -> None:
        if self._view is not None:
            self._view.open_registry_window()

    def on_open_study_info(self) -> None:
        if self._view is not None:
            self._view.open_study_info(self.dataset.study_info())

    def on_param_search(self, scope: str, query: str) -> dict:
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return {"rows": [], "truncated": 0}
        return self.dataset.search_params(sid, rid, scope, query)

    def on_apply_addon_spec(self, category: str, spec_path: str) -> object:
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None:
            return {"error": "No scan selected", "category": category}
        if category != "info_spec" and rid is None:
            return {"error": "No reco selected", "category": category}
        result = self.dataset.apply_addon_spec(sid, rid, spec_path, category)
        if category in ("info_spec", "metadata_spec"):
            self.dataset.invalidate_rule_cache()
            self._convert_layout_cache_key = None
            self._refresh_convert_layout()
        return result

    def on_addon_context_map_change(self, path: Optional[str]) -> None:
        self._context_map_path = str(path) if path else None
        self._convert_layout_cache_key = None
        self._refresh_convert_layout()

    def resolve_addon_rule_file(self, category: str) -> tuple[Optional[str], Optional[str]]:
        sid = self.state.dataset.selected_scan_id
        if sid is None:
            return (None, None)
        return self.dataset.resolve_addon_rule_file(sid, category)

    def resolve_addon_spec(self, category: str) -> Optional[str]:
        sid = self.state.dataset.selected_scan_id
        if sid is None:
            return None
        return self.dataset.resolve_addon_spec(sid, category)

    def on_viewer_axis_change(self, axis: str, value: int) -> None:
        st = self.state.viewer
        if axis == "x":
            st.x_index = int(value)
        elif axis == "y":
            st.y_index = int(value)
        elif axis == "z":
            st.z_index = int(value)
        self._render_viewer_views()

    def on_viewer_frame_change(self, value: int) -> None:
        self.state.viewer.frame_index = int(value)
        if self._timecourse_plot is not None:
            try:
                self._timecourse_plot.set_vline(float(self.state.viewer.frame_index))
            except Exception:
                pass
        if self._viewer_hook_enabled:
            self._render_viewer_views()
        else:
            if self._apply_cached_frame(self.state.viewer.frame_index):
                return
            self._schedule_frame_request()

    def on_viewer_hook_toggle(self, enabled: bool, hook_name: Optional[str]) -> None:
        logger.debug("Viewer hook toggle: enabled=%s name=%s", enabled, hook_name)
        sid = self.state.dataset.selected_scan_id
        if sid is None:
            return
        name = hook_name or self._viewer_hook_name
        self._viewer_hook_name = name or None
        if not self._viewer_hook_name:
            self._viewer_hook_enabled = False
            if self._view is not None:
                self._view.set_viewer_hook_state("None", False, None, allow_toggle=not self._viewer_hook_locked)
            return
        if bool(enabled):
            try:
                brkapi.hook.resolve_hook(self._viewer_hook_name)
                self._viewer_hook_enabled = True
            except Exception as exc:
                logger.warning("Viewer hook resolve failed: %s", exc)
                self._viewer_hook_enabled = False
        else:
            self._viewer_hook_enabled = False
        if self._view is not None:
            self._view.set_viewer_hook_state(
                self._viewer_hook_name or "None",
                self._viewer_hook_enabled,
                self._viewer_hook_args,
                allow_toggle=not self._viewer_hook_locked,
            )
        self._clear_frame_cache()
        self._request_viewer_volume()

    def on_viewer_flip_change(self, axis: str, enabled: bool) -> None:
        logger.debug("Viewer flip change: %s=%s", axis, enabled)
        st = self.state.viewer
        axis_norm = (axis or "").lower()
        if axis_norm == "x":
            st.flip_x = bool(enabled)
        elif axis_norm == "y":
            st.flip_y = bool(enabled)
        elif axis_norm == "z":
            st.flip_z = bool(enabled)
        self._clear_frame_cache()
        if self._viewer_raw_volume is not None:
            affine = None
            sid = self.state.dataset.selected_scan_id
            rid = self.state.dataset.selected_reco_id
            if sid is not None and rid is not None:
                scan = self.dataset.get_scan(int(sid))
                if scan is not None:
                    selected_space = (self.state.viewer.space or "scanner").strip()
                    if selected_space not in {"raw", "scanner", "subject_ras"}:
                        selected_space = "scanner"
                    subject_type = self.state.viewer.subject_type if selected_space == "subject_ras" else None
                    subject_pose = self.state.viewer.subject_pose if selected_space == "subject_ras" else None
                    try:
                        affine = scan.get_affine(
                            int(rid),
                            space=cast(AffineSpace, selected_space),
                            override_subject_type=cast(SubjectType, subject_type),
                            override_subject_pose=cast(SubjectPose, subject_pose),
                            flip_x=bool(self.state.viewer.flip_x),
                            flip_y=bool(self.state.viewer.flip_y),
                            flip_z=bool(self.state.viewer.flip_z),
                        )
                    except Exception:
                        affine = None
            if isinstance(affine, tuple):
                idx = int(self.state.viewer.slicepack_index or 0)
                if idx < 0 or idx >= len(affine):
                    idx = 0
                affine = affine[idx]
            if affine is None:
                affine = self._viewer_raw_affine
            data = self._reorient_viewer_volume(affine=affine)
            data = cast(np.ndarray, data)
            if data is not None:
                self._viewer_volume = data
                self._viewer_shape = data.shape if hasattr(data, "shape") else None
                self._update_viewer_indices_from_shape()
                self._render_viewer_views()
                if self._convert_use_viewer_orientation:
                    self._sync_convert_orientation_from_viewer()
                return
        self._request_viewer_volume()

    def on_viewer_slicepack_change(self, value: int) -> None:
        self.state.viewer.slicepack_index = int(value)
        self._clear_frame_cache()
        self._request_viewer_volume()

    def on_viewer_extra_dim_change(self, index: int, value: int) -> None:
        st = self.state.viewer
        if index < 0:
            return
        if len(st.extra_indices) <= index:
            st.extra_indices.extend([0] * (index + 1 - len(st.extra_indices)))
        st.extra_indices[index] = int(value)
        self._render_viewer_views()

    def on_viewer_jump(self, x: int, y: int, z: int) -> None:
        st = self.state.viewer
        st.x_index = int(x)
        st.y_index = int(y)
        st.z_index = int(z)
        self._render_viewer_views()

    def on_viewer_crosshair_toggle(self, enabled: bool) -> None:
        self.state.viewer.show_crosshair = bool(enabled)
        self._render_viewer_views()

    def on_viewer_rgb_toggle(self, enabled: bool) -> None:
        self.state.viewer.rgb_mode = bool(enabled)
        self._render_viewer_views()

    def on_viewer_zoom_change(self, value: float) -> None:
        try:
            self.state.viewer.zoom = max(1.0, min(4.0, float(value)))
        except Exception:
            self.state.viewer.zoom = 1.0
        if self._view is not None:
            self._view.set_viewer_zoom_value(self.state.viewer.zoom)
        self._render_viewer_views()

    def on_viewer_zoom_step(self, delta: float, plane: Optional[str] = None, rc: Optional[tuple[int, int]] = None) -> None:
        try:
            current = float(self.state.viewer.zoom)
            steps = float(delta) / 120.0
            if steps == 0.0:
                return
            factor = 1.2 ** steps
            new_zoom = current * factor
        except Exception:
            new_zoom = 1.0
        if plane and rc is not None:
            row, col = rc
            try:
                # Move crosshair to the hovered voxel in the active plane.
                if plane == "xy":
                    self.state.viewer.y_index = int(row)
                    self.state.viewer.x_index = int(col)
                elif plane == "xz":
                    self.state.viewer.z_index = int(row)
                    self.state.viewer.x_index = int(col)
                elif plane == "zy":
                    self.state.viewer.y_index = int(row)
                    self.state.viewer.z_index = int(col)
            except Exception:
                pass
        new_zoom = max(1.0, min(4.0, float(new_zoom)))
        self.state.viewer.zoom = new_zoom
        if self._view is not None:
            self._view.set_viewer_zoom_value(new_zoom)
        self._render_viewer_views()

    def on_viewer_resize(self) -> None:
        self._render_viewer_views()

    def on_viewer_timecourse_toggle(self) -> None:
        if self._view is None:
            return
        win = self._ensure_timecourse_window()
        if win is None:
            return
        try:
            win.lift()
        except Exception:
            pass
        if self._viewer_volume is None:
            if self._timecourse_plot is not None:
                self._timecourse_plot.set_message("Load image first.")
            return
        cache_path = self._resolve_timecourse_cache_path()
        if self._timecourse_cache_path == cache_path:
            if self._timecourse_cache_data is None and Path(cache_path).exists():
                try:
                    self._timecourse_cache_data = np.load(cache_path, mmap_mode="r")
                except Exception:
                    self._timecourse_cache_data = None
            if self._timecourse_cache_data is not None:
                self._update_timecourse_plot()
                return
        vol = self._viewer_volume
        need_full = True
        if vol is not None:
            try:
                arr = np.asarray(vol)
                need_full = not (arr.ndim >= 4 and int(arr.shape[3]) > 1)
            except Exception:
                need_full = True
        if need_full:
            if self._timecourse_plot is not None:
                self._timecourse_plot.set_message("Loading full volume...")
            self._request_timecourse_cache()
        else:
            self._update_timecourse_plot()

    def on_viewer_space_change(self, value: str) -> None:
        logger.debug("Viewer space change: %s", value)
        self.state.viewer.space = str(value)
        self._clear_frame_cache()
        if self._view is not None:
            self._view.set_viewer_subject_enabled(self.state.viewer.space == "subject_ras")
        if self._convert_use_viewer_orientation:
            self._sync_convert_orientation_from_viewer()
        for cb in list(self._viewer_space_listeners):
            try:
                cb(self.state.viewer.space)
            except Exception:
                pass
        self._request_viewer_volume()

    def register_viewer_space_listener(self, cb: Callable[[str], None]) -> None:
        if not callable(cb):
            return
        self._viewer_space_listeners.append(cb)

    def _ensure_timecourse_window(self):
        if self._timecourse_window is not None and self._timecourse_window.winfo_exists():
            return self._timecourse_window
        try:
            import tkinter as tk
            from brkraw_viewer.ui.components.plotter import PlotCanvas, PlotMeta
        except Exception:
            return None
        parent = self._view.winfo_toplevel() if self._view is not None else None
        if parent is None:
            return None
        win = tk.Toplevel(cast(tk.Misc, parent))
        win.title("Timecourse")
        win.geometry("520x260")
        plot = PlotCanvas(win)
        plot.pack(fill="both", expand=True)
        plot.set_message("No data")
        plot.set_on_click(self._on_timecourse_click)
        plot.enable_capture(self._on_timecourse_capture)
        self._timecourse_window = win
        self._timecourse_plot = plot
        _center_window(win, parent)

        def _on_close() -> None:
            try:
                win.destroy()
            except Exception:
                pass
            self._timecourse_window = None
            self._timecourse_plot = None
            self._clear_timecourse_cache()

        win.protocol("WM_DELETE_WINDOW", _on_close)
        return win

    def _on_timecourse_click(self, x_value: float) -> None:
        try:
            idx = int(round(x_value))
        except Exception:
            return
        total_frames = self._viewer_frames
        data = self._timecourse_cache_data
        if data is not None:
            try:
                if data.ndim >= 4:
                    total_frames = int(data.shape[3])
            except Exception:
                pass
        if total_frames <= 0:
            return
        if idx < 0:
            idx = 0
        elif idx >= total_frames:
            idx = total_frames - 1
        self.on_viewer_frame_change(idx)

    def _on_timecourse_capture(self) -> None:
        if self._timecourse_plot is None:
            return
        if self.state.dataset.path is None:
            if self._view is not None:
                self._view.set_status("No dataset open.")
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            if self._view is not None:
                self._view.set_status("Select scan/reco first.")
            return
        output_dir = self._convert_output_dir or Path.cwd()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        prefix = self._capture_output_prefix(scan_id=int(sid), reco_id=int(rid))
        x = int(self.state.viewer.x_index)
        y = int(self.state.viewer.y_index)
        z = int(self.state.viewer.z_index)
        path = _capture_output_path(output_dir, prefix, x=x, y=y, z=z, plane="timecourse")
        try:
            from tkinter import messagebox

            ok = messagebox.askyesno("Timecourse Capture", f"Save capture to:\n{path}")
        except Exception:
            ok = True
        if not ok:
            return
        if not self._timecourse_plot.capture_to_file(str(path)):
            if self._view is not None:
                self._view.set_status("Timecourse capture failed.")

    def _update_timecourse_plot(self, *, indices: Optional[tuple[int, int, int]] = None) -> None:
        if self._timecourse_plot is None or self._timecourse_window is None:
            return
        try:
            from brkraw_viewer.ui.components.plotter import PlotMeta
        except Exception:
            PlotMeta = None
        vol = self._viewer_volume
        data = self._timecourse_cache_data
        if data is None:
            vol = self._viewer_volume
            if vol is None:
                self._timecourse_plot.set_message("No data")
                return
            data = np.asarray(vol)
        if data.ndim < 4:
            self._timecourse_plot.set_message("Timecourse requires 4D data.")
            return
        if indices is None:
            indices = (
                int(self.state.viewer.x_index),
                int(self.state.viewer.y_index),
                int(self.state.viewer.z_index),
            )
        xi, yi, zi = indices
        extra_indices = self.state.viewer.extra_indices or []
        slicer: list[slice | int] = [xi, yi, zi, slice(None)]
        if data.ndim > 4:
            for i in range(4, data.ndim):
                idx = extra_indices[i - 4] if (i - 4) < len(extra_indices) else 0
                slicer.append(int(idx))
        try:
            series = data[tuple(slicer)]
        except Exception:
            self._timecourse_plot.set_message("Timecourse unavailable.")
            return
        try:
            y = np.asarray(series).astype(float)
        except Exception:
            self._timecourse_plot.set_message("Timecourse unavailable.")
            return
        if y.ndim != 1:
            y = y.reshape(-1)
        x = list(range(len(y)))
        meta = PlotMeta(title="Voxel timecourse", x_label="Frame", y_label="") if PlotMeta else None
        self._timecourse_plot.set_lines(
            x=x,
            ys=cast("Sequence[Sequence[float]]", [y]),
            meta=meta,
            y_fmt=lambda v: f"{v:.1E}",
        )
        self._timecourse_plot.set_vline(float(self.state.viewer.frame_index))

    def on_viewer_subject_reset(self) -> None:
        self._apply_subject_defaults_from_reco()
        if self._convert_use_viewer_orientation:
            self._sync_convert_orientation_from_viewer()
        self._request_viewer_volume()

    def on_viewer_subject_change(self, subject_type: str, pose_primary: str, pose_secondary: str) -> None:
        self.state.viewer.subject_type = subject_type or None
        if pose_primary and pose_secondary:
            self.state.viewer.subject_pose = f"{pose_primary}_{pose_secondary}"
        else:
            self.state.viewer.subject_pose = None
        if self._convert_use_viewer_orientation:
            self._sync_convert_orientation_from_viewer()
        if self.state.viewer.space == "subject_ras":
            self._request_viewer_volume()

    def on_viewer_hook_args_change(self, hook_args: Optional[dict]) -> None:
        logger.debug("Viewer hook args change: %s", bool(hook_args))
        self._viewer_hook_args = hook_args
        if self._viewer_hook_name:
            if hook_args is None:
                self._hook_args_by_name.pop(self._viewer_hook_name, None)
            else:
                self._hook_args_by_name[self._viewer_hook_name] = dict(hook_args)
        if self._view is not None:
            self._view.set_viewer_hook_state(
                self._viewer_hook_name or "None",
                self._viewer_hook_enabled,
                self._viewer_hook_args,
                allow_toggle=not self._viewer_hook_locked,
            )
            convert_enabled = self._convert_hook_enabled and bool(self._viewer_hook_name)
            self._view.set_convert_hook_state(self._viewer_hook_name or "None", convert_enabled, self._viewer_hook_args)
        if self._viewer_hook_enabled:
            self._request_viewer_volume()

    def on_hook_options_apply(self, hook_name: str, hook_args: Optional[dict]) -> None:
        name = (hook_name or "").strip()
        if not name:
            return
        logger.debug("Hook options apply: %s", name)
        self._hook_args_by_name[name] = dict(hook_args or {})
        if self._viewer_hook_name == name:
            self._viewer_hook_args = self._hook_args_by_name.get(name)
            if self._view is not None:
                self._view.set_viewer_hook_state(
                    self._viewer_hook_name or "None",
                    self._viewer_hook_enabled,
                    self._viewer_hook_args,
                    allow_toggle=not self._viewer_hook_locked,
                )
        convert_enabled = self._convert_hook_enabled and bool(self._viewer_hook_name)
        if self._view is not None:
            self._view.set_convert_hook_state(self._viewer_hook_name or "None", convert_enabled, self._hook_args_by_name.get(name))
        if self._viewer_hook_enabled and self._viewer_hook_name == name:
            self._request_viewer_volume()

    def on_convert_hook_options_apply(self, hook_name: str, hook_args: Optional[dict]) -> None:
        name = (hook_name or "").strip()
        if not name:
            return
        logger.debug("Convert hook options apply: %s", name)
        self._hook_args_by_name[name] = dict(hook_args or {})
        convert_enabled = self._convert_hook_enabled and bool(self._viewer_hook_name)
        if self._view is not None:
            self._view.set_convert_hook_state(self._viewer_hook_name or "None", convert_enabled, self._hook_args_by_name.get(name))

    def on_viewer_hook_lock(self, locked: bool) -> None:
        self._viewer_hook_locked = bool(locked)
        self.state.viewer.hook_locked = bool(locked)
        if self._view is not None:
            self._view.set_viewer_hook_state(
                self._viewer_hook_name or "None",
                self._viewer_hook_enabled,
                self._viewer_hook_args,
                allow_toggle=not self._viewer_hook_locked,
            )

    def _apply_subject_defaults_from_reco(self) -> None:
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            return
        scan = self.dataset.get_scan(sid)
        if scan is None:
            return
        
        reco = scan.avail.get(rid)
        visu_pars = getattr(reco, "visu_pars", None) if reco else None
        if visu_pars is None:
            return
        subj_type, subj_pose = brkapi.affine_resolver.get_subject_type_and_position(visu_pars)
        subj_type = subj_type or "Biped"
        if subj_pose and "_" in subj_pose:
            primary, secondary = subj_pose.split("_", 1)
        else:
            primary, secondary = "Head", "Supine"
        self.state.viewer.subject_type = subj_type
        self.state.viewer.subject_pose = f"{primary}_{secondary}"
        if self._view is not None:
            self._view.set_viewer_subject_values(subj_type, primary, secondary)
        if self._convert_use_viewer_orientation:
            self._sync_convert_orientation_from_viewer()

    def on_convert_submit(
        self,
        *,
        output_dir: str,
        base_name: str,
        space: AffineSpace,
        subject_type: Optional[SubjectType],
        subject_pose: Optional[SubjectPose],
        flip: tuple[bool, bool, bool],
        hook_enabled: bool,
        hook_name: str,
        hook_args: Optional[dict],
        sidecar_enabled: bool,
        sidecar_format: str,
        use_viewer_orientation: bool = False,
    ) -> None:
        if self.state.dataset.path is None:
            if self._view is not None:
                self._view.set_status("No dataset open.")
            return
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            if self._view is not None:
                self._view.set_status("Select scan/reco first.")
            return
        if use_viewer_orientation:
            space = cast(AffineSpace, self.state.viewer.space)
            flip = (bool(self.state.viewer.flip_x), bool(self.state.viewer.flip_y), bool(self.state.viewer.flip_z))
            if space == "subject_ras":
                subject_type = cast(Optional[SubjectType], self.state.viewer.subject_type)
                subject_pose = cast(Optional[SubjectPose], self.state.viewer.subject_pose)
            else:
                subject_type = None
                subject_pose = None

        out_dir = Path(output_dir) if output_dir else Path.cwd()
        self._convert_output_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        base = base_name.strip()
        if not base:
            base = ""
        output_paths = self._plan_output_paths(
            output_dir=out_dir,
            base_name=base,
            scan_id=int(sid),
            reco_id=int(rid),
            slicepack_suffix=brkapi.config.output_slicepack_suffix(root=None),
            layout_source=self._convert_layout_source,
            layout_auto=self._convert_layout_auto,
            layout_template=self._convert_layout_template,
            context_map=self._context_map_path,
        )
        if not output_paths:
            output_paths = [str(out_dir / f"scan{sid:03d}_reco{rid:03d}.nii.gz")]
        hook_args_by_name = None
        if hook_enabled and hook_name:
            hook_args_by_name = {hook_name: hook_args or {}}
        if space != "subject_ras":
            subject_type = None
            subject_pose = None
        metadata_spec_path = self.resolve_addon_spec("metadata_spec")
        req = ConvertRequest(
            job_id=f"convert-{dt.datetime.now().timestamp()}",
            path=str(self.state.dataset.path),
            scan_id=int(sid),
            reco_id=int(rid),
            space=space,
            subject_type=subject_type or None,
            subject_pose=subject_pose or None,
            flip=flip,
            hook_args=hook_args_by_name,
            output_paths=output_paths,
            sidecar_enabled=bool(sidecar_enabled),
            sidecar_format=sidecar_format or "json",
            metadata_spec=metadata_spec_path,
        )
        self.start_convert(req)

    def _plan_output_paths(
        self,
        *,
        output_dir: Path,
        base_name: str,
        scan_id: int,
        reco_id: int,
        slicepack_suffix: Optional[str] = None,
        layout_source: Optional[str] = None,
        layout_auto: Optional[bool] = None,
        layout_template: Optional[str] = None,
        context_map: Optional[str] = None,
    ) -> list[str]:
        if self.dataset.loader() is None:
            return []
        if layout_source is None:
            layout_source = self._convert_layout_source
        if layout_auto is None:
            layout_auto = self._convert_layout_auto
        if layout_template is None:
            layout_template = self._convert_layout_template
        template, entries, resolved_map = self._resolve_layout_sources(
            layout_source=layout_source or "Config",
            layout_auto=bool(layout_auto),
            layout_template=layout_template or "",
            context_map=context_map,
        )
        if base_name:
            template = base_name.strip()
        try:
            base = self.dataset.render_layout(
                scan_id,
                reco_id,
                layout_entries=entries,
                layout_template=template or None,
                context_map=resolved_map,
            )
        except Exception as exc:
            logger.debug("Layout render failed: %s", exc)
            base = ""
        if not base:
            base = f"scan{scan_id:03d}_reco{reco_id:03d}"
        suffix_template = slicepack_suffix or brkapi.config.output_slicepack_suffix(root=None)
        slicepacks = max(int(self._viewer_slicepacks or 1), 1)
        if slicepacks <= 1:
            return [str(output_dir / f"{base}.nii.gz")]
        try:
            info = self.dataset.layout_info(
                scan_id,
                reco_id,
                context_map=resolved_map,
                info_spec=None,
                metadata_spec=None,
            )
        except Exception:
            info = {}
        suffixes = self.dataset.render_slicepack_suffixes(
            info,
            count=slicepacks,
            template=suffix_template,
        )
        return [str(output_dir / f"{base}{suffix}.nii.gz") for suffix in suffixes]

    def on_convert_preview(
        self,
        *,
        output_dir: Union[str, Path],
        layout_source: str,
        layout_auto: bool,
        layout_template: str,
        slicepack_suffix: str,
        sidecar_enabled: bool,
        sidecar_format: str,
    ) -> None:
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None or self._view is None:
            return
        logger.debug(
            "Convert preview: source=%s auto=%s template=%s",
            layout_source,
            layout_auto,
            bool(layout_template),
        )
        output_dir = Path(output_dir) if output_dir else Path.cwd()
        self._convert_output_dir = output_dir
        planned = self._plan_output_paths(
            output_dir=output_dir,
            base_name=layout_template.strip() if layout_template else "",
            scan_id=int(sid),
            reco_id=int(rid),
            slicepack_suffix=slicepack_suffix,
            layout_source=layout_source,
            layout_auto=layout_auto,
            layout_template=layout_template,
            context_map=self._context_map_path,
        )
        preview_list = list(planned)
        if sidecar_enabled:
            preview_list.extend(self._planned_sidecar_paths(preview_list, sidecar_format=sidecar_format))
        preview_text = "\n".join(preview_list[:50]) if preview_list else "No outputs planned."
        settings = f"Layout source: {layout_source}\nAuto: {layout_auto}\nTemplate: {layout_template or '(config)'}\n"
        self._view.set_convert_preview_text(preview_text)
        self._view.set_convert_settings_text(settings)

    def on_convert_output_dir_change(self, output_dir: str) -> None:
        self._convert_output_dir = Path(output_dir) if output_dir else Path.cwd()

    def on_viewer_capture(self, plane: str, indices: tuple[int, int, int]) -> Optional[str]:
        if self.state.dataset.path is None:
            if self._view is not None:
                self._view.set_status("No dataset open.")
            return None
        sid = self.state.dataset.selected_scan_id
        rid = self.state.dataset.selected_reco_id
        if sid is None or rid is None:
            if self._view is not None:
                self._view.set_status("Select scan/reco first.")
            return None
        output_dir = self._convert_output_dir or Path.cwd()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        prefix = self._capture_output_prefix(scan_id=int(sid), reco_id=int(rid))
        x, y, z = indices
        plane_name = str(plane).lower().strip()
        if plane_name not in {"xy", "xz", "zy"}:
            plane_name = "xy"
        return str(_capture_output_path(output_dir, prefix, x=x, y=y, z=z, plane=plane_name))

    @staticmethod
    def _planned_sidecar_paths(planned: list[str], *, sidecar_format: str) -> list[str]:
        suffix = ".json" if sidecar_format == "json" else ".yaml"
        sidecars: list[str] = []
        for item in planned:
            path = Path(item)
            sidecar = path.with_suffix(suffix)
            if path.name.endswith(".nii.gz"):
                sidecar = path.with_name(path.name[:-7] + suffix)
            sidecars.append(str(sidecar))
        return sidecars

    def _capture_output_prefix(self, *, scan_id: int, reco_id: int) -> str:
        template, entries, resolved_map = self._resolve_layout_sources(
            layout_source=self._convert_layout_source,
            layout_auto=self._convert_layout_auto,
            layout_template=self._convert_layout_template,
            context_map=self._context_map_path,
        )
        if self._convert_layout_template:
            template = self._convert_layout_template
        try:
            base = self.dataset.render_layout(
                scan_id,
                reco_id,
                layout_entries=entries,
                layout_template=template or None,
                context_map=resolved_map,
            )
        except Exception:
            base = ""
        if not base:
            base = f"scan{scan_id:03d}_reco{reco_id:03d}"

        slicepacks = max(int(self._viewer_slicepacks or 1), 1)
        if slicepacks <= 1:
            return base
        try:
            info = self.dataset.layout_info(
                scan_id,
                reco_id,
                context_map=resolved_map,
                info_spec=None,
                metadata_spec=None,
            )
        except Exception:
            info = {}
        suffix_template = brkapi.config.output_slicepack_suffix(root=None)
        suffixes = self.dataset.render_slicepack_suffixes(info, count=slicepacks, template=suffix_template)
        idx = min(max(int(self.state.viewer.slicepack_index), 0), len(suffixes) - 1) if suffixes else 0
        suffix = suffixes[idx] if suffixes and idx >= 0 else ""
        return f"{base}{suffix}"

    def on_convert_hook_toggle(self, enabled: bool) -> None:
        self._convert_hook_enabled = bool(enabled)
        if self._view is not None:
            self._view.set_convert_hook_state(
                self._viewer_hook_name or "None",
                self._convert_hook_enabled and bool(self._viewer_hook_name),
                self._viewer_hook_args,
            )

    def on_convert_use_viewer_orientation_change(self, use_viewer: bool) -> None:
        self._convert_use_viewer_orientation = bool(use_viewer)
        self._sync_convert_orientation_from_viewer()

    def registry_list(self) -> list[dict]:
        return load_registry()

    def registry_add_paths(self, paths: list[Path]) -> tuple[int, int]:
        job_id = f"registry-add-{dt.datetime.now().timestamp()}"
        self._registry_jobs[job_id] = "add"
        self._worker.submit(RegistryRequest(job_id=job_id, action="add", paths=[str(p) for p in paths]))
        if self._view is not None:
            self._view.registry_set_status("Adding...")
        return (0, 0)

    def registry_remove_paths(self, paths: list[Path]) -> int:
        job_id = f"registry-remove-{dt.datetime.now().timestamp()}"
        self._registry_jobs[job_id] = "remove"
        self._worker.submit(RegistryRequest(job_id=job_id, action="remove", paths=[str(p) for p in paths]))
        if self._view is not None:
            self._view.registry_set_status("Removing...")
        return 0

    def registry_scan_paths(self, paths: list[Path]) -> tuple[int, int]:
        job_id = f"registry-scan-{dt.datetime.now().timestamp()}"
        self._registry_jobs[job_id] = "scan"
        self._worker.submit(RegistryRequest(job_id=job_id, action="scan", paths=[str(p) for p in paths]))
        if self._view is not None:
            self._view.registry_set_status("Scanning...")
        return (0, 0)

    def registry_open_path(self, path: Path) -> None:
        self.action_open_dataset(path)

    def registry_current_path(self) -> Optional[Path]:
        return self.state.dataset.path

    def get_study_info(self) -> dict:
        return self.dataset.study_info()

    def _sync_convert_orientation_from_viewer(self) -> None:
        if self._view is None:
            return
        if not self._convert_use_viewer_orientation:
            self._view.set_convert_orientation_fields(
                use_viewer=False,
                space="",
                subject_type=None,
                pose_primary="",
                pose_secondary="",
                flip=(False, False, False),
            )
            return
        space = str(self.state.viewer.space or "scanner")
        pose_primary = ""
        pose_secondary = ""
        subject_type = self.state.viewer.subject_type
        if isinstance(self.state.viewer.subject_pose, str) and "_" in self.state.viewer.subject_pose:
            pose_primary, pose_secondary = self.state.viewer.subject_pose.split("_", 1)
        self._view.set_convert_orientation_fields(
            use_viewer=True,
            space=space,
            subject_type=subject_type,
            pose_primary=pose_primary,
            pose_secondary=pose_secondary,
            flip=(bool(self.state.viewer.flip_x), bool(self.state.viewer.flip_y), bool(self.state.viewer.flip_z)),
        )

    def _reorient_viewer_volume(self, *, affine: Optional[object] = None) -> Optional[object]:
        raw = self._viewer_raw_volume
        if raw is None:
            return None
        affine_obj = affine if affine is not None else self._viewer_raw_affine
        if affine_obj is None:
            self._viewer_res = (1.0, 1.0, 1.0)
            return np.asarray(raw)
        try:
            affine_arr = np.asarray(affine_obj, dtype=float)
        except Exception:
            self._viewer_res = (1.0, 1.0, 1.0)
            return np.asarray(raw)
        try:
            data, new_affine = reorient_to_ras(np.asarray(raw), affine_arr)
            self._viewer_res = _affine_to_resolution(new_affine)
            return data
        except Exception:
            self._viewer_res = _affine_to_resolution(affine_arr)
            return np.asarray(raw)


def _affine_to_resolution(affine: np.ndarray) -> tuple[float, float, float]:
    if affine.ndim != 2 or affine.shape[0] < 3 or affine.shape[1] < 3:
        return (1.0, 1.0, 1.0)
    axes = affine[:3, :3]
    try:
        res = np.linalg.norm(axes, axis=0)
    except Exception:
        return (1.0, 1.0, 1.0)
    out: list[float] = []
    for val in res.tolist():
        try:
            fval = float(val)
        except Exception:
            fval = 1.0
        if not np.isfinite(fval) or fval <= 0.0:
            fval = 1.0
        out.append(fval)
    while len(out) < 3:
        out.append(1.0)
    return (out[0], out[1], out[2])


def _center_window(win, parent) -> None:
    try:
        win.update_idletasks()
    except Exception:
        return
    try:
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
    except Exception:
        return
    try:
        ww = win.winfo_reqwidth()
        wh = win.winfo_reqheight()
    except Exception:
        return
    x = px + max(int((pw - ww) / 2), 0)
    y = py + max(int((ph - wh) / 2), 0)
    try:
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def _resolve_value_display(
    *,
    vol: np.ndarray,
    indices: tuple[int, int, int],
    frame: int,
    extra_indices: list[int] | None,
    rgb_mode: bool,
) -> tuple[str, bool]:
    plot_enabled = bool(vol.ndim >= 4)
    xi, yi, zi = indices
    if vol.ndim < 3:
        return ("[ - ]", plot_enabled)
    try:
        if vol.ndim == 4 and vol.shape[3] == 3 and rgb_mode:
            rgb = vol[xi, yi, zi, :]
            rgb = np.asarray(rgb).reshape(-1)
            if len(rgb) >= 3:
                return (f"[ {rgb[0]:.3f}, {rgb[1]:.3f}, {rgb[2]:.3f} ]", plot_enabled)
        slicer: list[slice | int] = [xi, yi, zi]
        if vol.ndim >= 4:
            slicer.append(min(max(int(frame), 0), int(vol.shape[3]) - 1))
        if vol.ndim > 4:
            extra_indices = extra_indices or []
            for i in range(4, vol.ndim):
                idx = extra_indices[i - 4] if (i - 4) < len(extra_indices) else 0
                slicer.append(min(max(int(idx), 0), int(vol.shape[i]) - 1))
        value = float(vol[tuple(slicer)])
        return (f"[ {value:.3f} ]", plot_enabled)
    except Exception:
        return ("[ - ]", plot_enabled)


def _parse_fov(value: object) -> Optional[tuple[float, float, float]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        items = list(value)
    else:
        text = str(value)
        nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
        items = nums
    if len(items) < 3:
        return None
    out: list[float] = []
    for val in items[:3]:
        try:
            fval = float(val)
        except Exception:
            return None
        if not np.isfinite(fval) or fval <= 0.0:
            return None
        out.append(fval)
    return (out[0], out[1], out[2])


def _capture_output_path(
    output_dir: Path,
    prefix: str,
    *,
    x: int,
    y: int,
    z: int,
    plane: str,
) -> Path:
    base_path = Path(prefix)
    if base_path.is_absolute():
        base_path = Path(base_path.name)
    target_dir = output_dir / base_path.parent
    stem = base_path.name if base_path.name else "capture"
    filename = f"{stem}_{x}_{y}_{z}_plane-{plane}.png"
    return target_dir / filename
