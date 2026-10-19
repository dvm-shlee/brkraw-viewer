from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import json
from typing import Any, Dict, Mapping, Optional, get_args, get_origin, get_type_hints

import logging

import tkinter as tk
from tkinter import messagebox, ttk

from brkraw.specs import hook as converter_core

logger = logging.getLogger(__name__)

_PRESET_IGNORE_PARAMS = frozenset(
    {
        "self",
        "scan",
        "scan_id",
        "reco_id",
        "dataobj",
        "dataobjs",
        "affine",
        "affines",
        "format",
        "space",
        "override_header",
        "override_subject_type",
        "override_subject_pose",
        "flip_x",
        "xyz_units",
        "t_units",
        "decimals",
        "spec",
        "context_map",
        "return_spec",
        "hook_args_by_name",
    }
)


def _infer_hook_preset_from_module(module: object) -> Dict[str, Any]:
    for attr in ("HOOK_PRESET", "HOOK_ARGS", "HOOK_DEFAULTS"):
        value = getattr(module, attr, None)
        if isinstance(value, Mapping):
            return dict(value)
    build_options = getattr(module, "_build_options", None)
    if callable(build_options):
        try:
            options = build_options({})
        except Exception:
            return {}
        if dataclasses.is_dataclass(options):
            if not isinstance(options, type):
                return dict(dataclasses.asdict(options))
            defaults: Dict[str, Any] = {}
            for field in dataclasses.fields(options):
                if field.default is not dataclasses.MISSING:
                    defaults[field.name] = field.default
                    continue
                if field.default_factory is not dataclasses.MISSING:  # type: ignore[comparison-overlap]
                    try:
                        defaults[field.name] = field.default_factory()  # type: ignore[misc]
                    except Exception:
                        defaults[field.name] = None
                    continue
                defaults[field.name] = None
            return defaults
        if hasattr(options, "__dict__"):
            return dict(vars(options))
    return {}


def infer_hook_preset(entry: Mapping[str, Any]) -> Dict[str, Any]:
    preset: Dict[str, Any] = {}
    modules: list[object] = []

    for func in entry.values():
        if callable(func):
            mod_name = getattr(func, "__module__", None)
            if isinstance(mod_name, str) and mod_name:
                try:
                    modules.append(importlib.import_module(mod_name))
                except Exception:
                    pass

    for module in modules:
        module_preset = _infer_hook_preset_from_module(module)
        if module_preset:
            return dict(sorted(module_preset.items(), key=lambda item: item[0]))

    for func in entry.values():
        if not callable(func):
            continue
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            continue
        for param in sig.parameters.values():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            name = param.name
            if name in _PRESET_IGNORE_PARAMS:
                continue
            if name in preset:
                continue
            if param.default is inspect.Parameter.empty:
                preset[name] = None
            else:
                preset[name] = param.default
    return dict(sorted(preset.items(), key=lambda item: item[0]))


def infer_hook_option_hints(entry: Mapping[str, Any]) -> Dict[str, Any]:
    hints: Dict[str, Any] = {}
    modules: list[object] = []

    for func in entry.values():
        if callable(func):
            mod_name = getattr(func, "__module__", None)
            if isinstance(mod_name, str) and mod_name:
                try:
                    modules.append(importlib.import_module(mod_name))
                except Exception:
                    pass

    for module in modules:
        build_options = getattr(module, "_build_options", None)
        if callable(build_options):
            try:
                options = build_options({})
            except Exception:
                options = None
            if dataclasses.is_dataclass(options):
                for field in dataclasses.fields(options):
                    if field.name not in hints:
                        hints[field.name] = field.type

    for func in entry.values():
        if not callable(func):
            continue
        try:
            sig = inspect.signature(func)
            type_hints = get_type_hints(func)
        except (TypeError, ValueError):
            continue
        for param in sig.parameters.values():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            name = param.name
            if name in _PRESET_IGNORE_PARAMS or name in hints:
                continue
            annotation = type_hints.get(name, param.annotation)
            if annotation is inspect.Parameter.empty:
                continue
            hints[name] = annotation
    return hints


def format_hook_type(value: Any, hint: Any = None) -> str:
    if hint is not None:
        origin = get_origin(hint)
        if origin is not None and origin.__name__ == "Literal":
            return "Literal"
        if hint is bool:
            return "bool"
        if hint is int:
            return "int"
        if hint is float:
            return "float"
        if hint is str:
            return "str"
    if value is None:
        return "Any"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def coerce_hook_value(raw: str, default: Any) -> Any:
    text = raw.strip()
    if text == "":
        return default
    if isinstance(default, bool):
        return text.lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(text)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(text)
        except ValueError:
            return default
    if isinstance(default, (list, tuple, dict)):
        try:
            return ast.literal_eval(text)
        except Exception:
            try:
                return json.loads(text)
            except Exception:
                return default
    if default is None:
        try:
            return ast.literal_eval(text)
        except Exception:
            try:
                return json.loads(text)
            except Exception:
                return text
    return text


class HookOptionsDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        hook_name: str,
        hook_args: Optional[dict],
        on_apply,
    ) -> None:
        self._parent = parent
        self._hook_name = hook_name
        self._hook_args = hook_args or {}
        self._on_apply = on_apply
        self._window: Optional[tk.Toplevel] = None
        self._container: Optional[ttk.Frame] = None
        self._header_label: Optional[ttk.Label] = None
        self._vars: Dict[str, tk.StringVar] = {}
        self._defaults: Dict[str, Any] = {}
        self._choices: Dict[str, Dict[str, Any]] = {}
        self._preset: Optional[Dict[str, Any]] = None
        self._hints: Dict[str, Any] = {}

    def is_open(self) -> bool:
        """True while the window exists (shown or withdrawn); a destroyed window is not open."""
        win = self._window
        if win is None:
            return False
        try:
            return bool(win.winfo_exists())
        except Exception:
            return False

    def update(self, *, hook_name: str, hook_args: Optional[dict], on_apply) -> None:
        """Point an existing window at the current hook, applied values and apply callback (WI-0078)."""
        if hook_name != self._hook_name:
            self._defaults = {}
        self._hook_name = hook_name
        self._hook_args = hook_args or {}
        self._on_apply = on_apply
        # Show what is applied now, not what was typed and left unapplied earlier.
        self._vars = {}

    def refresh(self, *, hook_name: str, hook_args: Optional[dict]) -> None:
        """Show values applied elsewhere (the other tab) in this open window (WI-0104).

        Does nothing when the window is for another hook, when the values are the ones it
        already holds (its own Apply echoed back, so a typed value is not lost), or before it
        was ever shown. A hidden window stays hidden and shows the new values when opened.
        """
        new_args = dict(hook_args or {})
        if (hook_name or "").strip() != self._hook_name or new_args == (self._hook_args or {}):
            return
        self._hook_args = new_args
        self._vars = {}  # the form is rebuilt from the applied values
        if self._preset is not None and self.is_open():
            self._render_form(self._preset, self._hints)

    def show(self) -> Optional[str]:
        """Show the window. Returns None when shown, else the reason it cannot be shown (WI-0104)."""
        name = (self._hook_name or "").strip()
        if not name or name in ("None", "Disabled"):
            return "This scan has no converter hook, so there are no hook options."
        try:
            entry = converter_core.resolve_hook(name)
        except Exception as exc:
            logger.warning("Hook options: hook %s could not be loaded: %s", name, exc)
            return f"Hook '{name}' could not be loaded, so its options cannot be shown ({exc})."
        preset = infer_hook_preset(entry)
        if not preset:
            return f"Hook '{name}' has no options to edit."
        hints = infer_hook_option_hints(entry)
        self._preset, self._hints = preset, hints

        if self._window is None or not self._window.winfo_exists():
            win = tk.Toplevel(self._parent)
            win.title("Converter Hook Options")
            try:
                # Stay above the viewer window so a second press is not needed to find it.
                win.transient(self._parent.winfo_toplevel())
            except Exception:
                pass
            win.resizable(True, True)
            win.columnconfigure(0, weight=1)
            win.rowconfigure(0, weight=1)

            container = ttk.Frame(win, padding=(10, 10))
            container.grid(row=0, column=0, sticky="nsew")
            container.columnconfigure(0, weight=1)
            container.rowconfigure(1, weight=1)

            header = ttk.Frame(container)
            header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            header.columnconfigure(1, weight=1)
            ttk.Label(header, text="Hook").grid(row=0, column=0, sticky="w")
            self._header_label = ttk.Label(header, text=self._hook_name)
            self._header_label.grid(row=0, column=1, sticky="w")

            self._container = ttk.Frame(container)
            self._container.grid(row=1, column=0, sticky="nsew")
            self._container.columnconfigure(2, weight=1)

            actions = ttk.Frame(container)
            actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
            actions.columnconfigure(0, weight=1)

            ttk.Button(actions, text="Reset", command=self._reset).grid(row=0, column=0, sticky="w")
            ttk.Button(actions, text="Apply", command=self._apply).grid(row=0, column=1, sticky="e")
            ttk.Button(actions, text="Close", command=self._close).grid(row=0, column=2, sticky="e", padx=(8, 0))

            self._window = win

        if self._header_label is not None:
            try:
                self._header_label.configure(text=self._hook_name)
            except Exception:
                pass
        self._render_form(preset, hints)
        if self._window is not None:
            self._window.deiconify()
            self._window.lift()
        return None

    def _render_form(self, preset: Dict[str, Any], hints: Dict[str, Any]) -> None:
        container = self._container
        if container is None:
            return
        for child in container.winfo_children():
            child.destroy()
        self._choices = {}

        ttk.Label(container, text="Key").grid(row=0, column=0, sticky="w")
        ttk.Label(container, text="Type").grid(row=0, column=1, sticky="w")
        ttk.Label(container, text="Value").grid(row=0, column=2, sticky="w")

        row = 1
        for key, default in preset.items():
            value = self._hook_args.get(key, default)
            var = self._vars.get(key) or tk.StringVar(value="" if value is None else str(value))
            self._vars[key] = var
            self._defaults[key] = default

            hint = hints.get(key)
            type_label = format_hook_type(default, hint)

            ttk.Label(container, text=key).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(container, text=type_label).grid(row=row, column=1, sticky="w", padx=(0, 6), pady=2)

            widget: tk.Widget
            origin = get_origin(hint) if hint is not None else None
            if origin is not None and origin.__name__ == "Literal":
                choices = list(get_args(hint))
                if choices:
                    values = [str(choice) for choice in choices]
                    self._choices[key] = {str(choice): choice for choice in choices}
                    if var.get() not in values:
                        lower_map = {value.lower(): value for value in values}
                        matched = lower_map.get(var.get().lower())
                        var.set(matched if matched is not None else values[0])
                    widget = ttk.Combobox(container, textvariable=var, values=values, state="readonly")
                else:
                    widget = ttk.Entry(container, textvariable=var)
            elif hint is bool or isinstance(default, bool):
                values = ["True", "False"]
                if var.get().lower() in {"true", "false"}:
                    var.set("True" if var.get().lower() == "true" else "False")
                if var.get() not in values:
                    var.set("True" if default is True else "False")
                widget = ttk.Combobox(container, textvariable=var, values=values, state="readonly")
            else:
                widget = ttk.Entry(container, textvariable=var)
            widget.grid(row=row, column=2, sticky="ew", pady=2)
            row += 1

        container.columnconfigure(2, weight=1)

    def _reset(self) -> None:
        for key, var in self._vars.items():
            default = self._defaults.get(key)
            choices = self._choices.get(key)
            if choices:
                target = str(default) if default is not None else None
                if target is None or target not in choices:
                    target = next(iter(choices.keys()), "")
                var.set(target)
            else:
                var.set("" if default is None else str(default))

    def _apply(self) -> None:
        values: Dict[str, Any] = {}
        for key, var in self._vars.items():
            choices = self._choices.get(key)
            if choices is not None:
                raw = var.get()
                values[key] = choices.get(raw, raw)
                continue
            default = self._defaults.get(key)
            values[key] = coerce_hook_value(var.get(), default)
        self._hook_args = dict(values)
        if callable(self._on_apply):
            self._on_apply(values)

    def _close(self) -> None:
        if self._window is not None:
            try:
                self._window.withdraw()
            except Exception:
                pass


def show_hook_options(owner: Any, parent: tk.Misc, *, hook_name: str, hook_args: Optional[dict], on_apply) -> HookOptionsDialog:
    """Open the hook options window for ``owner`` (a tab or panel), never a second one.

    The window is kept on ``owner._hook_options_dialog``. Pressing the button again brings the
    existing window forward (or shows it again after Close); a window closed with the window
    button is created anew. WI-0078: each press used to create a new window.
    """
    dialog = getattr(owner, "_hook_options_dialog", None)
    if dialog is not None and dialog.is_open():
        dialog.update(hook_name=hook_name, hook_args=hook_args, on_apply=on_apply)
    else:
        dialog = HookOptionsDialog(parent, hook_name=hook_name, hook_args=hook_args, on_apply=on_apply)
        owner._hook_options_dialog = dialog
    reason = dialog.show()
    if reason:
        notify(parent, reason)
    return dialog


def refresh_open_dialog(owner: Any, hook_name: str, hook_args: Optional[dict]) -> None:
    """Pass options applied elsewhere on to the options window ``owner`` has open, if any."""
    dialog = getattr(owner, "_hook_options_dialog", None)
    if dialog is None or not dialog.is_open():
        return
    try:
        dialog.refresh(hook_name=hook_name, hook_args=hook_args)
    except Exception:
        logger.debug("Hook options window refresh failed", exc_info=True)


def notify(parent: Any, text: str) -> None:
    """Tell the user why the options window did not open; never raises (WI-0104)."""
    try:
        messagebox.showinfo("Hook Options", text, parent=parent.winfo_toplevel())
    except Exception:
        try:
            messagebox.showinfo("Hook Options", text)
        except Exception:
            pass
