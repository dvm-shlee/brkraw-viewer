from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from brkraw.api.types import AffineSpace, SubjectType, SubjectPose


@dataclass(frozen=True)
class ConvertRequest:
    job_id: str
    path: str
    scan_id: int
    reco_id: int
    space: AffineSpace
    subject_type: Optional[SubjectType]
    subject_pose: Optional[SubjectPose]
    flip: Tuple[bool, bool, bool]  # x, y, z
    hook_args: Optional[Dict[str, Any]]
    output_paths: List[str]
    sidecar_enabled: bool = False
    sidecar_format: str = "json"
    metadata_spec: Optional[str] = None


@dataclass(frozen=True)
class ConvertResult:
    job_id: str
    saved_paths: List[str]
    error: Optional[str] = None


@dataclass(frozen=True)
class LoadVolumeRequest:
    job_id: str
    path: str
    scan_id: int
    reco_id: int
    frame_start: Optional[int] = None
    frame_count: Optional[int] = None
    hook_name: Optional[str] = None
    hook_args: Optional[Dict[str, Any]] = None
    slicepack_index: int = 0
    space: str = "scanner"
    subject_type: Optional[str] = None
    subject_pose: Optional[str] = None
    flip_x: bool = False
    flip_y: bool = False
    flip_z: bool = False
    # Ask before a load that would make the data the worker holds larger than this
    # (0 = never ask). Since WI-0072 (C9) the limit is for the total held by all layers.
    memory_limit_bytes: int = 0
    # The user already chose "continue" for this reco.
    memory_confirmed: bool = False
    # (path, scan_id, reco_id) of the layers still shown. The worker frees the data it holds
    # for any other reco before loading (C9). None keeps everything (the old behaviour).
    keep: Optional[Tuple[Tuple[str, int, int], ...]] = None
    # Bytes the main process holds for layers it owns (arrays given in main, C2 "array");
    # counted in the same total as what the worker holds (C9).
    other_held_bytes: int = 0
    # With a converter hook on: ask when the hook's reconstruction peak (``peak_nbytes``, plus
    # what is held for other data) is over this many bytes (a share of the installed memory,
    # WI-0104 item 7, D-0170). 0 = do not ask for the peak.
    peak_limit_bytes: int = 0


@dataclass(frozen=True)
class LoadVolumeResult:
    job_id: str
    shm_name: Optional[str]
    shape: Tuple[int, ...]
    dtype: str
    affine: Optional[list] = None
    slicepacks: int = 1
    frames: int = 1
    error: Optional[str] = None
    # Nothing was loaded: the expected size is over the limit and the user must choose.
    needs_confirm: bool = False
    # This load's expected bytes, and the bytes the worker already holds for the layers
    # that stay (C9); the notice compares their sum with limit_bytes.
    estimated_bytes: Optional[int] = None
    limit_bytes: int = 0
    held_bytes: int = 0
    # Why it asked: "size" (the data held would pass limit_bytes), "peak" (the hook's
    # reconstruction peak, peak_bytes, would pass peak_limit_bytes) or "both". One question.
    reason: str = ""
    peak_bytes: Optional[int] = None
    peak_limit_bytes: int = 0


@dataclass(frozen=True)
class TimecourseRequest:
    """One voxel's values over all frames, answered by the worker from the data it holds
    (layer core C9, WI-0072; replaces the full-volume .npy file of WI-0068)."""

    job_id: str
    path: str
    scan_id: int
    reco_id: int
    # Voxel index on the displayed (RAS-reoriented) grid, and indices of axes after the 4th.
    index: Tuple[int, int, int] = (0, 0, 0)
    extra_indices: Tuple[int, ...] = ()
    slicepack_index: int = 0
    space: str = "scanner"
    subject_type: Optional[str] = None
    subject_pose: Optional[str] = None
    flip_x: bool = False
    flip_y: bool = False
    flip_z: bool = False
    # ROI over time (contract C6/C9): when roi_mask is given, the answer is the per-frame
    # mean of the finite values inside this 2D mask on display slice roi_index of roi_axis
    # (mask laid out like np.take(volume, roi_index, roi_axis)); ``index`` is then unused.
    roi_axis: Optional[int] = None
    roi_index: int = 0
    roi_mask: Optional[Any] = None


@dataclass(frozen=True)
class TimecourseResult:
    job_id: str
    values: Optional[List[float]]
    index: Tuple[int, int, int] = (0, 0, 0)
    frames: int = 1
    error: Optional[str] = None
    # ROI answers: voxels in the mask, and per frame how many of them were finite.
    n_mask: int = 0
    n_per_frame: Optional[List[int]] = None


@dataclass(frozen=True)
class RegistryRequest:
    job_id: str
    action: str  # "add" | "remove" | "scan"
    paths: List[str]


@dataclass(frozen=True)
class RegistryResult:
    job_id: str
    action: str
    added: int = 0
    removed: int = 0
    skipped: int = 0
    error: Optional[str] = None
