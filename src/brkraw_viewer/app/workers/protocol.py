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


@dataclass(frozen=True)
class TimecourseCacheRequest:
    job_id: str
    path: str
    scan_id: int
    reco_id: int
    cache_path: str
    slicepack_index: int = 0
    space: str = "scanner"
    subject_type: Optional[str] = None
    subject_pose: Optional[str] = None
    flip_x: bool = False
    flip_y: bool = False
    flip_z: bool = False


@dataclass(frozen=True)
class TimecourseCacheResult:
    job_id: str
    cache_path: Optional[str]
    shape: Tuple[int, ...]
    dtype: str
    frames: int = 1
    error: Optional[str] = None


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
