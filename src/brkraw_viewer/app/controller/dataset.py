import logging
import re
from pathlib import Path
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, Optional, List, Dict, Tuple

from brkraw.core import layout as layout_core
from brkraw import api as brkapi
from brkraw.specs import context_map as context_map_core
from brkraw.specs import remapper as remapper_core
from brkraw.specs.context_map import output as context_map_output
from .helper import format_value as _format_value

if TYPE_CHECKING:
    from brkraw.api.types import (
        ScanLoader
    )

logger = logging.getLogger(__name__)


def _flatten_values(values: dict, prefix: str = "") -> Dict[str, object]:
    """{"bids": {"sub": "01"}} -> {"bids.sub": "01"} (nested mappings only)."""
    flat: Dict[str, object] = {}
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten_values(value, f"{name}."))
        else:
            flat[name] = value
    return flat


@dataclass(frozen=True)
class DatasetSummary:
    path: Path
    scan_ids: List[int]


class DatasetController:
    def __init__(self) -> None:
        self._summary: Optional[DatasetSummary] = None
        self._loader: Optional[brkapi.BrukerLoader] = None
        self._study_info: Dict = {}
        self._scans: Dict[int, ScanLoader] = {}
        self._scan_info: Optional[Dict] = {}
        self._scan_info_cache: Dict[int, Dict] = {}
        self._hook_name_cache: Dict[int, Optional[str]] = {}
        self._rules_cache: Optional[Dict[str, list]] = None
        self._spec_cache: Dict[tuple[int, str], Optional[str]] = {}
        self._rule_file_cache: Dict[tuple[int, str], tuple[Optional[str], Optional[str]]] = {}

    @property
    def summary(self) -> Optional[DatasetSummary]:
        return self._summary

    def open_dataset(self, path: Path) -> DatasetSummary:
        loader = brkapi.BrukerLoader(path, disable_hook=True)
        self._loader = loader
        self._study_info = loader.subject or {}
        self._scan_info = self._loader.info(scope="scan", as_dict=True)
        scan_ids = list(loader.avail.keys())
        self._summary = DatasetSummary(path=path, scan_ids=scan_ids)
        self._scan_info_cache.clear()
        self._hook_name_cache.clear()
        self._rules_cache = None
        self._spec_cache.clear()
        self._rule_file_cache.clear()
        return self._summary

    def close_dataset(self) -> None:
        self._summary = None
        self._loader = None
        self._study_info = {}
        self._scans.clear()
        self._scan_info = None
        self._scan_info_cache.clear()
        self._hook_name_cache.clear()
        self._rules_cache = None
        self._spec_cache.clear()
        self._rule_file_cache.clear()

    def list_scans(self) -> List[int]:
        if self._summary is None:
            return []
        return list(self._summary.scan_ids)

    def scan_entries(self) -> list[tuple[int, str]]:
        if self._loader is None or self._scan_info is None:
            return []
        entries: list[tuple[int, str]] = []
        logger.debug("Build scan entries")
        for scan_id, info in self._scan_info.items():
            scan_id = int(scan_id)
            protocol = _format_value(info.get("Protocol", "N/A"))
            method = _format_value(info.get("Method", "")).strip()
            entries.append((scan_id, f"E{scan_id:03d} - {protocol} ({method})"))
        return entries

    def reco_entries(self, scan_id: int) -> list[tuple[int, str]]:
        entries: List[Tuple[int, str]] = []
        if self._loader is None or self._scan_info is None:
            return entries
        try:
            scan_info = self._scan_info[scan_id]
        except Exception:
            return entries

        recos = cast(dict, scan_info.get("Reco(s)", {}))
        for reco_id, reco_info in recos.items():
            label = "N/A"
            if isinstance(recos, dict):
                label = _format_value(cast(dict, reco_info).get("Type", "N/A"))
            entries.append((int(reco_id), f"{reco_id:03d} :: {label}"))
        return entries

    def get_scan(self, scan_id: int):
        if self._loader is None:
            return None
        if scan_id not in self._scans.keys():
            try:
                self._scans[scan_id] = self._loader.get_scan(scan_id)
            except Exception:
                return None
        return self._scans[scan_id]

    def get_converter_hook_name(self, scan_id: int) -> Optional[str]:
        if scan_id in self._hook_name_cache:
            return self._hook_name_cache[scan_id]
        scan = self.get_scan(scan_id)
        if scan is None:
            self._hook_name_cache[scan_id] = None
            return None
        rules = self._load_rules()
        try:
            base = brkapi.config.resolve_root(None)
        except Exception:
            base = brkapi.config.resolve_root()
        hook_name = None
        if isinstance(rules, dict):
            try:
                hook_name = brkapi.rules.select_rule_use(
                    scan,
                    rules.get("converter_hook", []),
                    base=base,
                    resolve_paths=False,
                )
            except Exception:
                hook_name = None
        if isinstance(hook_name, str) and hook_name.strip():
            hook_name = hook_name.strip()
        else:
            hook_name = None
        self._hook_name_cache[scan_id] = hook_name
        return hook_name

    def is_converter_hook_attached(self, scan_id: int) -> bool:
        scan = self.get_scan(scan_id)
        if scan is None:
            return False
        return getattr(scan, "_converter_hook", None) is not None

    def materialize_scan(self, scan_id: int) -> None:
        self.get_scan(scan_id)

    def loader(self) -> Optional[brkapi.BrukerLoader]:
        return self._loader

    def _layout_parts(
        self,
        scan_id: int,
        reco_id: Optional[int],
        *,
        info_spec: Optional[str] = None,
        metadata_spec: Optional[str] = None,
    ) -> Tuple[dict, dict]:
        """Original (never remapped) info and metadata of a scan (brkraw 0.6 layout)."""
        return layout_core.load_layout_info_parts(
            self._loader,
            scan_id,
            root=None,
            reco_id=reco_id,
            override_info_spec=info_spec or None,
            override_metadata_spec=metadata_spec or None,
        )

    @staticmethod
    def context_map_meta(context_map: Optional[str]) -> dict:
        """``__meta__`` of a context map file (0.6 format), or ``{}`` when there is none."""
        if not context_map:
            return {}
        data = context_map_core.load_context_map(context_map)
        meta = data.get("__meta__") if isinstance(data, dict) else None
        return dict(meta) if isinstance(meta, dict) else {}

    def _context_map_namespaces(
        self,
        info: dict,
        scan_id: int,
        reco_id: Optional[int],
        context_map: Optional[str],
    ) -> dict:
        """Namespace values (``{"bids": {"sub": ...}}``) a 0.6 context map defines for one scan."""
        if not context_map:
            return {}
        map_data = context_map_core.load_context_map(context_map)
        plan = context_map_core.plan_scan(info, map_data, scan_id=scan_id, reco_id=reco_id)
        return plan.namespaces

    def layout_info(
        self,
        scan_id: int,
        reco_id: Optional[int],
        *,
        context_map: Optional[str],
        info_spec: Optional[str],
        metadata_spec: Optional[str],
    ) -> dict:
        if self._loader is None:
            return {}
        info, metadata = self._layout_parts(scan_id, reco_id, info_spec=info_spec, metadata_spec=metadata_spec)
        merged = dict(info)
        merged.update(metadata)
        merged.update(self._context_map_namespaces(info, scan_id, reco_id, context_map))
        return merged

    def render_layout(
        self,
        scan_id: int,
        reco_id: int,
        *,
        layout_entries: Optional[list],
        layout_template: Optional[str],
        context_map: Optional[str],
        base_name: Optional[str] = None,
    ) -> str:
        if self._loader is None:
            return ""
        template = base_name.strip() if isinstance(base_name, str) and base_name.strip() else layout_template
        namespaces: dict = {}
        if context_map:
            info, _ = self._layout_parts(scan_id, reco_id)
            namespaces = self._context_map_namespaces(info, scan_id, reco_id, context_map)
            map_template = self.context_map_meta(context_map).get("layout_template")
            if isinstance(map_template, str) and map_template.strip() and (template or "") == map_template.strip():
                return self._render_map_template(map_template.strip(), info, namespaces, scan_id, reco_id)
        return layout_core.render_layout(
            self._loader,
            scan_id,
            layout_entries=layout_entries,
            layout_template=template or None,
            root=None,
            reco_id=reco_id,
            extra=namespaces or None,
        )

    @staticmethod
    def _render_map_template(template: str, info: dict, namespaces: dict, scan_id: int, reco_id: Optional[int]) -> str:
        """Render a context map ``layout_template`` (``[ ]`` groups, ``utils.*`` tags) to a flat file name."""
        values = _flatten_values(info)
        values.setdefault("ScanID", scan_id)
        values.setdefault("RecoID", reco_id)
        values.update(_flatten_values(namespaces))
        values.update(context_map_output.utils_values(counter=1))
        text, _notes = context_map_output.render_template(template, values)
        # the viewer writes flat files: path separators become underscores
        return re.sub(r"[\\/]+", "_", text.strip())

    def render_slicepack_suffixes(self, info: dict, *, count: int, template: str) -> list[str]:
        return layout_core.render_slicepack_suffixes(info, count=count, template=template)

    def resolve_addon_rule_file(self, scan_id: int, category: str) -> tuple[Optional[str], Optional[str]]:
        cache_key = (scan_id, category)
        if cache_key in self._rule_file_cache:
            return self._rule_file_cache[cache_key]
        scan = self.get_scan(scan_id)
        if scan is None:
            result = (None, None)
            self._rule_file_cache[cache_key] = result
            return result
        rules = self._load_rules()
        try:
            base = brkapi.config.resolve_root(None)
        except Exception:
            base = brkapi.config.resolve_root()
        matched_rule = None
        for rule in rules.get(category, []) if isinstance(rules, dict) else []:
            if not isinstance(rule, dict):
                continue
            try:
                if brkapi.rules.rule_matches(scan, rule, base=base):
                    matched_rule = rule
            except Exception:
                continue
        if matched_rule is None:
            result = (None, None)
            self._rule_file_cache[cache_key] = result
            return result
        name = matched_rule.get("name")
        use = matched_rule.get("use")
        try:
            installed = brkapi.addon_manager.list_installed(root=None)
        except Exception:
            installed = {}
        entries = installed.get("rules", []) if isinstance(installed, dict) else []
        paths = brkapi.config.paths(root=None)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if name and entry.get("name") != name:
                continue
            if entry.get("category") != category:
                continue
            if use and entry.get("use") != use:
                continue
            relpath = entry.get("file")
            if relpath:
                result = (str((paths.rules_dir / relpath).resolve()), str(name) if name else None)
                self._rule_file_cache[cache_key] = result
                return result
        result = (None, str(name) if name else None)
        self._rule_file_cache[cache_key] = result
        return result

    def resolve_addon_spec(self, scan_id: int, category: str) -> Optional[str]:
        cache_key = (scan_id, category)
        if cache_key in self._spec_cache:
            return self._spec_cache[cache_key]
        scan = self.get_scan(scan_id)
        if scan is None:
            self._spec_cache[cache_key] = None
            return None
        rules = self._load_rules()
        try:
            base = brkapi.config.resolve_root(None)
        except Exception:
            base = brkapi.config.resolve_root()
        matched_rule = None
        for rule in rules.get(category, []) if isinstance(rules, dict) else []:
            if not isinstance(rule, dict):
                continue
            try:
                if brkapi.rules.rule_matches(scan, rule, base=base):
                    matched_rule = rule
            except Exception:
                continue
        if matched_rule is None:
            self._spec_cache[cache_key] = None
            return None
        use = matched_rule.get("use")
        if isinstance(use, str):
            try:
                resolved = str(brkapi.addon_manager.resolve_spec_reference(use, category=category, root=None))
                self._spec_cache[cache_key] = resolved
                return resolved
            except Exception:
                self._spec_cache[cache_key] = None
                return None
        self._spec_cache[cache_key] = None
        return None

    def invalidate_rule_cache(self) -> None:
        self._rules_cache = None
        self._spec_cache.clear()
        self._rule_file_cache.clear()
        self._hook_name_cache.clear()

    def _load_rules(self) -> Dict[str, list]:
        if self._rules_cache is not None:
            return self._rules_cache
        try:
            self._rules_cache = brkapi.rules.load_rules(root=None, validate=False)
        except Exception:
            self._rules_cache = {}
        return self._rules_cache

    def study_info(self) -> dict:
        return dict(self._study_info or {})

    def params_summary(self, scan_id: int) -> dict:
        scan = self.get_scan(scan_id)
        if scan is None:
            return {}
        try:
            return brkapi.info_resolver.scan(scan)
        except Exception:
            return {}

    def search_params(self, scan_id: int, reco_id: int, scope: str, query: str, *, limit: int = 500) -> dict:
        """Search parameters through `BrukerLoader.search_params` and adapt for the UI.

        UI `scope` is mapped to loader's `file` argument.

        Scope mapping:
        - "all": file=["method","acqp","visu_pars","reco"]
        - "method"/"acqp"/"visu_pars"/"reco": file=scope
        """
        if self._loader is None:
            return {"rows": [], "truncated": 0}

        query = (query or "").strip()
        # if not query:
        #    return {"rows": [], "truncated": 0}

        scope_norm = (scope or "all").strip().lower()
        if scope_norm == "all":
            file_arg = ["method", "acqp", "visu_pars", "reco"]
        elif scope_norm in {"method", "acqp", "visu_pars", "reco"}:
            file_arg = scope_norm
        else:
            file_arg = ["method", "acqp", "visu_pars", "reco"]

        try:
            result = self._loader.search_params(
                query,
                file=file_arg,
                scan_id=scan_id,
                reco_id=reco_id,
            )
        except Exception:
            return {"rows": [], "truncated": 0}

        if not isinstance(result, dict):
            return {"rows": [], "truncated": 0}

        rows: list[dict] = []
        total = 0

        def _fmt_val_full(val: object) -> str:
            # Full representation for detail view
            if hasattr(val, "tolist"):
                try:
                    return str(getattr(val, "tolist")())
                except Exception:
                    pass
            return str(val)

        def _fmt_val_display(val: object) -> str:
            # Short representation for tree view
            # Handle numpy arrays (duck typing)
            if hasattr(val, "shape"):
                try:
                    shape = val.shape  # type: ignore
                    if hasattr(shape, "__iter__"):
                        shape_str = "x".join(str(d) for d in shape)
                        return f"Array of {shape_str}"
                except Exception:
                    pass

            s = str(val)
            s = s.replace("\n", " ").replace("\r", "")
            if len(s) > 30:
                s = s[:30] + " ..."
            return s

        def _emit(src: str, key_path: str, value: object) -> None:
            nonlocal total
            total += 1
            if len(rows) < limit:
                rows.append(
                    {
                        "file": src,
                        "key": key_path,
                        "type": type(value).__name__,
                        "value": _fmt_val_display(value),
                        "full_value": _fmt_val_full(value),
                    }
                )

        def _walk(src: str, prefix: str, obj: object) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    k_str = str(k)
                    new_prefix = f"{prefix}.{k_str}" if prefix else k_str
                    if isinstance(v, dict):
                        _walk(src, new_prefix, v)
                    else:
                        _emit(src, new_prefix, v)
            else:
                _emit(src, prefix or "", obj)

        for src, hits in result.items():
            _walk(str(src), "", hits)

        return {"rows": rows, "truncated": max(total - len(rows), 0)}

    def apply_addon_spec(self, scan_id: int, reco_id: Optional[int], spec_path: str, category: str) -> object:
        scan = self.get_scan(scan_id)
        if scan is None:
            return {"error": "No scan loaded"}
        try:
            if category == "info_spec":
                # Default info spec uses brkraw's scan.yaml (no spec_source).
                base = brkapi.info_resolver.scan(scan, spec_source=None, validate=False)
                if spec_path:
                    spec, transforms = remapper_core.load_spec(spec_path, validate=False)
                    context = {"scan_id": scan_id, "reco_id": reco_id}
                    override = remapper_core.map_parameters(scan, spec, transforms, context=context)
                    if isinstance(base, dict) and isinstance(override, dict):
                        merged = dict(base)
                        merged.update(override)
                        return merged
                    return override
                return base

            # Prefer scan.get_metadata for metadata specs when available.
            get_metadata = getattr(scan, "get_metadata", None)
            if callable(get_metadata):
                variants = [
                    {"reco_id": reco_id, "spec_source": spec_path},
                    {"reco_id": reco_id, "metadata_spec_source": spec_path},
                    {"reco_id": reco_id, "metadata_spec": spec_path},
                    {"reco_id": reco_id, "spec": spec_path},
                    {"reco_id": reco_id},
                    {"spec_source": spec_path},
                    {"metadata_spec_source": spec_path},
                    {"metadata_spec": spec_path},
                    {"spec": spec_path},
                    {},
                ]
                last_exc: Optional[Exception] = None
                for kwargs in variants:
                    try:
                        result = get_metadata(**kwargs)
                        if isinstance(result, dict):
                            return result
                        return {"error": "get_metadata returned non-dict", "category": category, "kwargs": kwargs}
                    except TypeError as exc:
                        last_exc = exc
                        continue
                    except Exception as exc:
                        return {"error": str(exc), "category": category, "kwargs": kwargs}
                return {"error": f"get_metadata signature mismatch: {last_exc}", "category": category}

            # Fallback: best-effort mapping.
            spec, transforms = remapper_core.load_spec(spec_path, validate=False)
            context = {"scan_id": scan_id, "reco_id": reco_id}
            return remapper_core.map_parameters(scan, spec, transforms, context=context)
        except Exception as exc:
            return {"error": str(exc), "category": category}
