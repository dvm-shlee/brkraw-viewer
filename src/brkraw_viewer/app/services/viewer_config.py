from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from brkraw.core import config as config_core
from brkraw.core.config import resolve_root

logger = logging.getLogger("brkraw.viewer")
REGISTRY_PATH_ENV = "BRKRAW_VIEWER_REGISTRY_PATH"


def _default_registry_columns() -> List[Dict[str, Any]]:
    return [
        {"key": "basename", "title": "Name", "width": 180},
        {"key": "Study.ID", "title": "Study ID", "width": 120},
        {"key": "Study.Date", "title": "Study Date", "width": 120},
        {"key": "Study.Number", "title": "Study Number", "width": 120},
        {"key": "Study.Operator", "title": "Study Operator", "width": 140},
        {"key": "num_scans", "title": "Scans", "width": 70},
        {"key": "path", "title": "Path", "width": 360},
    ]


def default_viewer_config() -> Dict[str, Any]:
    return {
        "cache": {
            # Ask before loading a scan whose 2dseq is larger than this many MB; 0 = never ask.
            # Default 600 MB (WI-0069, D-0094): an 8 GB laptop opens a 500 MB 2dseq without asking
            # and is asked before a 1 GB one.
            "memory_limit_mb": 600,
        },
        "registry": {
            "path": "viewer/registry.jsonl",
            "columns": _default_registry_columns(),
        },
        "worker": {
            "popup": True,
        },
    }


def resolve_cache_dir() -> Path:
    """Folder named by ``viewer.cache.path``; ``cache`` in the config folder when empty.

    Relative paths are taken from the BrkRaw config folder. The exit prompt and the
    Timecourse temporary files both use this one folder (WI-0076).
    """
    root = resolve_root(None)
    try:
        data = config_core.load_config(root=None) or {}
        value = (data.get("viewer") or {}).get("cache", {}).get("path")
    except Exception as exc:
        logger.warning("Could not read viewer.cache.path: %s", exc)
        value = None
    if isinstance(value, str) and value.strip():
        path = Path(value.strip()).expanduser()
        return path if path.is_absolute() else root / path
    return root / "cache"


def _deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config(root: Optional[Path]) -> Dict[str, Any]:
    data = config_core.load_config(root=root)
    if data is None:
        data = config_core.default_config()
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a YAML mapping at the top level.")
    return data


def load_viewer_config(root: Optional[Path] = None) -> Dict[str, Any]:
    config = _load_config(root)
    viewer = config.get("viewer", {})
    if not isinstance(viewer, dict):
        viewer = {}
    return _deep_merge(default_viewer_config(), viewer)


def ensure_viewer_config(root: Optional[Path] = None) -> Dict[str, Any]:
    config = _load_config(root)
    viewer = config.get("viewer", {})
    if not isinstance(viewer, dict):
        viewer = {}
    merged = _deep_merge(default_viewer_config(), viewer)
    config["viewer"] = merged
    config_core.write_config(config, root=root)
    return merged


def save_viewer_config(viewer: Dict[str, Any], root: Optional[Path] = None) -> None:
    config = _load_config(root)
    config["viewer"] = viewer
    config_core.write_config(config, root=root)


def _normalize_external_registry_path(path_like: str | Path) -> Path:
    path = Path(path_like).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.resolve()
    except Exception:
        return path


def registry_path(root: Optional[Path] = None, registry_file: Optional[str | Path] = None) -> Path:
    override = registry_file if registry_file is not None else os.environ.get(REGISTRY_PATH_ENV)
    if isinstance(override, str):
        override = override.strip()
        if not override:
            override = None
    if override is not None:
        return _normalize_external_registry_path(override)

    viewer = load_viewer_config(root)
    registry = viewer.get("registry", {})
    rel = registry.get("path", "viewer/registry.jsonl")
    if isinstance(rel, str):
        rel_path = Path(rel)
    else:
        rel_path = Path("viewer/registry.jsonl")
    if rel_path.is_absolute():
        return rel_path
    return resolve_root(root) / rel_path


def registry_columns(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    viewer = load_viewer_config(root)
    registry = viewer.get("registry", {})
    columns = registry.get("columns", [])
    if isinstance(columns, list):
        return [col for col in columns if isinstance(col, dict)]
    return _default_registry_columns()
