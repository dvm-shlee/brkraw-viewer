from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from typing import Optional, Sequence, Any, cast
from brkraw.api.types import AffineSpace, SubjectType, SubjectPose
from brkraw_viewer.app.protocols import MainCallbacks, ViewerView

from .top import TopBar
from .subject_bar import SubjectBar
from .sidebar import Sidebar
from .tabs import TabsArea
from .status import StatusBar
from brkraw_viewer.ui.windows.task_progress import TaskProgressWindow
from brkraw_viewer.ui.windows.worker_log import WorkerLogWindow
from brkraw_viewer.ui.windows.study_info import StudyInfoWindow
from brkraw_viewer.ui.windows.registry_window import RegistryWindow


class MainWindow(ttk.Frame):
    def __init__(self, master: tk.Tk, callbacks: MainCallbacks) -> None:
        super().__init__(master)
        self._cb = callbacks

        self._path_var = tk.StringVar(value="")
        self._status_var = tk.StringVar(value="Ready")

        self._study_id_var = tk.StringVar(value="None")
        self._subject_id_var = tk.StringVar(value="None")
        self._study_date_var = tk.StringVar(value="None")
        self._study_window: Optional[StudyInfoWindow] = None
        self._registry_window: Optional[RegistryWindow] = None
        self._task_window: Optional[TaskProgressWindow] = None
        self._worker_log_window: Optional[WorkerLogWindow] = None

        self._build()
        self.pack(fill="both", expand=True)
        self._finalize_geometry()
        self._bind_close()
        if hasattr(self._cb, "attach_view"):
            try:
                self._cb.attach_view(self)
            except Exception:
                pass

    def _build(self) -> None:
        # Top (load, refresh, registry, path)
        self.top = TopBar(
            self,
            path_var=self._path_var,
            on_open_folder=self._cb.on_open_folder,
            on_open_archive=self._cb.on_open_archive,
            on_refresh=self._cb.on_refresh,
            on_open_registry=self._cb.on_open_registry,
        )
        self.top.pack(side="top", fill="x")

        # Subject / Study summary row
        self.subject = SubjectBar(
            self,
            study_id_var=self._study_id_var,
            subject_id_var=self._subject_id_var,
            study_date_var=self._study_date_var,
            on_open_study_info=self._cb.on_open_study_info,
        )
        self.subject.pack(side="top", fill="x")

        # Body: left sidebar + right tabs
        body = ttk.Frame(self, padding=(10, 4, 10, 10))
        body.pack(side="top", fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(body, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")
        paned.columnconfigure(0, weight=1)
        paned.rowconfigure(0, weight=1)

        self.sidebar = Sidebar(
            paned,
            on_select_scan=self._cb.on_select_scan,
            on_select_reco=self._cb.on_select_reco,
        )
        self.tabs = TabsArea(paned, callbacks=self._cb)

        from brkraw_viewer.ui.tabs.registry import iter_tabs

        for title, builder in iter_tabs():
            self.tabs.register_tab(title, lambda parent, b=builder: b(parent, self._cb))
        self.tabs.build_tabs()

        paned.add(self.sidebar, weight=0)
        paned.add(self.tabs, weight=1)

        # Status bar
        self.status = StatusBar(self, status_var=self._status_var, on_open_worker_log=self._open_worker_log)
        self.status.pack(side="bottom", fill="x")

    def _bind_close(self) -> None:
        root = self.winfo_toplevel()
        try:
            root.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            pass

    def _on_close(self) -> None:
        try:
            if hasattr(self._cb, "on_close"):
                self._cb.on_close()
        except Exception:
            pass
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    def _finalize_geometry(self) -> None:
        # Ensure the initial toplevel size can accommodate all children,
        # so the status bar is not clipped on first show.
        root = self.winfo_toplevel()
        def _apply() -> None:
            try:
                root.update_idletasks()
            except Exception:
                return

            req_w = int(max(self.winfo_reqwidth(), root.winfo_reqwidth()))
            req_h = int(max(self.winfo_reqheight(), root.winfo_reqheight()))

            try:
                cur_w = int(root.winfo_width())
                cur_h = int(root.winfo_height())
            except Exception:
                cur_w, cur_h = req_w, req_h

            root.minsize(1050, 600)

            # Only adjust height to avoid clipping; don't lock width.
            if cur_h < req_h:
                new_h = max(cur_h, req_h)
                try:
                    x = int(root.winfo_x())
                    y = int(root.winfo_y())
                    root.geometry(f"{cur_w}x{new_h}+{x}+{y}")
                except Exception:
                    try:
                        root.geometry(f"{cur_w}x{new_h}")
                    except Exception:
                        pass

        try:
            self.after(0, _apply)
        except Exception:
            _apply()

    # ----- Methods controller can call (UI update API) -----
    def schedule_poll(self, callback, interval_ms: int) -> None:
        try:
            self.after(interval_ms, callback)
        except Exception:
            pass

    def open_worker_popup(self, log_queue: Any, title: str):
        # ViewerView expects this to be a UI side-effect. Keep the handle internally.
        try:
            if self._task_window is not None and self._task_window.winfo_exists():
                # One progress window: bring the open one forward and hand it back, so the
                # caller finishes the window that is on screen (WI-0104; a second window used
                # to be created and the first lost).
                try:
                    self._task_window.lift()
                except Exception:
                    pass
                return self._task_window
            self._task_window = TaskProgressWindow(self.winfo_toplevel(), log_queue, title=title)
            return self._task_window
        except Exception:
            self._task_window = None
        return None

    def _open_worker_log(self) -> None:
        queue = None
        try:
            queue = self._cb.get_worker_log_queue()
        except Exception:
            queue = None
        if queue is None:
            return
        if self._worker_log_window is not None and self._worker_log_window.winfo_exists():
            try:
                self._worker_log_window.lift()
            except Exception:
                pass
            return
        self._worker_log_window = WorkerLogWindow(self.winfo_toplevel(), queue)

    def close_worker_popup(self) -> None:
        try:
            if self._task_window is not None and self._task_window.winfo_exists():
                self._task_window.destroy()
        except Exception:
            pass
        self._task_window = None

    def open_study_info(self, info: dict) -> None:
        if self._study_window is not None and self._study_window.winfo_exists():
            self._study_window.update_info(info)
            self._study_window.lift()
            return
        self._study_window = StudyInfoWindow(self.winfo_toplevel(), info)

    def open_registry_window(self) -> None:
        if self._registry_window is not None and self._registry_window.winfo_exists():
            self._registry_window.refresh()
            self._registry_window.lift()
            return
        self._registry_window = RegistryWindow(
            self.winfo_toplevel(),
            list_entries=self._cb.registry_list,
            add_paths=self._cb.registry_add_paths,
            remove_paths=self._cb.registry_remove_paths,
            scan_paths=self._cb.registry_scan_paths,
            open_path=self._cb.registry_open_path,
            get_current_path=self._cb.registry_current_path,
        )

    def registry_refresh(self) -> None:
        if self._registry_window is not None and self._registry_window.winfo_exists():
            self._registry_window.refresh()

    def registry_set_status(self, text: str) -> None:
        if self._registry_window is not None and self._registry_window.winfo_exists():
            self._registry_window.set_status(text)

    def prompt_open_folder(self) -> Optional[Path]:
        path_str = filedialog.askdirectory(title="Select dataset folder")
        return Path(path_str) if path_str else None

    def prompt_open_archive(self) -> Optional[Path]:
        path_str = filedialog.askopenfilename(
            title="Select dataset archive",
            filetypes=[
                ("Bruker datasets", "*.zip *.PvDatasets"),
                ("ZIP", "*.zip"),
                ("All files", "*"),
            ],
        )
        return Path(path_str) if path_str else None

    def set_path(self, path: str) -> None:
        self._path_var.set(path)

    def set_dataset_path(self, path: Optional[Path]) -> None:
        self._path_var.set(str(path) if path else "")

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def set_subject_summary(self, *, study_id: str, subject_id: str, study_date: str) -> None:
        self._study_id_var.set(study_id)
        self._subject_id_var.set(subject_id)
        self._study_date_var.set(study_date)

    def set_scan_list(self, scan_ids: Sequence[tuple[int, str]]) -> None:
        self.sidebar.set_scan_list(list(scan_ids))

    def set_reco_list(self, reco_ids: Sequence[tuple[int, str]] | Sequence[int]) -> None:
        # Normalize to the exact list type expected by Sidebar.
        items = list(reco_ids)
        if not items:
            self.sidebar.set_reco_list([])
            return

        first = items[0]
        if isinstance(first, tuple):
            self.sidebar.set_reco_list(cast(list[tuple[int, str]], items))
        else:
            self.sidebar.set_reco_list(cast(list[int], items))

    def set_scan_selected(self, scan_id: Optional[int]) -> None:
        if scan_id is None:
            return
        self.sidebar.select_scan_id(scan_id)

    def set_reco_selected(self, reco_id: Optional[int]) -> None:
        if reco_id is None:
            return
        self.sidebar.select_reco_id(reco_id)

    def set_tabs_enabled(self, enabled: bool) -> None:
        self.tabs.set_tabs_enabled(enabled)

    def get_selected_tab(self) -> Optional[str]:
        return self.tabs.get_selected_title()

    def select_tab(self, title: str) -> None:
        self.tabs.select_tab(title)

    def set_params_summary(self, summary: dict) -> None:
        tab = self.tabs.get_tab("Params")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_summary"):
            target.set_summary(summary)

    def set_param_results(self, rows: list[dict], *, truncated: int = 0) -> None:
        tab = self.tabs.get_tab("Params")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_search_results"):
            target.set_search_results(rows, truncated=truncated)

    def set_viewer_views(
        self,
        views: dict,
        *,
        indices: tuple[int, int, int] | None = None,
        res: dict[str, tuple[float, float]] | None = None,
        crosshair: dict | None = None,
        show_crosshair: bool = False,
        lock_scale: bool = True,
        allow_overflow: bool = False,
        overflow_blend: float | None = None,
        zoom_scale: float | None = None,
        window: tuple[float, float] | None = None,
        layers: dict | None = None,
    ) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_views"):
            target.set_views(
                views,
                indices=indices,
                res=res,
                crosshair=crosshair,
                show_crosshair=show_crosshair,
                lock_scale=lock_scale,
                allow_overflow=allow_overflow,
                overflow_blend=overflow_blend,
                zoom_scale=zoom_scale,
                window=window,
                layers=layers,
            )

    def set_viewer_subject_enabled(self, enabled: bool) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_subject_enabled"):
            target.set_subject_enabled(enabled)

    def set_viewer_status(self, text: str) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_status"):
            target.set_status(text)

    def set_viewer_subject_values(self, subject_type: str, pose_primary: str, pose_secondary: str) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_subject_values"):
            target.set_subject_values(subject_type, pose_primary, pose_secondary)

    def set_viewer_rgb_state(self, *, enabled: bool, active: bool) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_rgb_state"):
            target.set_rgb_state(enabled=enabled, active=active)

    def set_viewer_zoom_value(self, value: float) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_zoom_value"):
            target.set_zoom_value(value)

    def set_viewer_controls_enabled(self, enabled: bool) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_controls_enabled"):
            target.set_controls_enabled(enabled)

    def set_viewer_hook_state(self, hook_name: str, enabled: bool, hook_args: Optional[dict], *, allow_toggle: bool = True) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_hook_state"):
            target.set_hook_state(hook_name, enabled, allow_toggle=allow_toggle)
        if target is not None and hasattr(target, "set_hook_args"):
            target.set_hook_args(hook_args)

    def set_convert_hook_state(self, hook_name: str, enabled: bool, hook_args: Optional[dict]) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_hook_state"):
            target.set_hook_state(hook_name, enabled, hook_args)

    def set_convert_orientation_fields(
        self,
        *,
        use_viewer: bool,
        space: str,
        subject_type: Optional[str],
        pose_primary: str,
        pose_secondary: str,
        flip: tuple[bool, bool, bool],
    ) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_orientation_fields"):
            target.set_orientation_fields(
                use_viewer=use_viewer,
                space=space,
                subject_type=subject_type,
                pose_primary=pose_primary,
                pose_secondary=pose_secondary,
                flip=flip,
            )

    def set_convert_layout_fields(
        self,
        *,
        rule: str,
        info_spec: str,
        metadata_spec: str,
        context_map: str,
        template: str,
        slicepack_suffix: str,
    ) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_layout_fields"):
            target.set_layout_fields(
                rule=rule,
                info_spec=info_spec,
                metadata_spec=metadata_spec,
                context_map=context_map,
                template=template,
                slicepack_suffix=slicepack_suffix,
            )

    def set_convert_layout_keys(self, keys: list[str]) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_layout_keys"):
            target.set_layout_keys(keys)

    def set_convert_preview_text(self, text: str) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_preview_text"):
            target.set_preview_text(text)

    def set_convert_settings_text(self, text: str) -> None:
        tab = self.tabs.get_tab("Convert")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_settings_text"):
            target.set_settings_text(text)

    def notify_task_result(self, title: str, message: str, success: bool) -> None:
        try:
            if success:
                messagebox.showinfo(title, message, parent=self.winfo_toplevel())
            else:
                messagebox.showerror(title, message, parent=self.winfo_toplevel())
        except Exception:
            pass

    def notify_warning(self, title: str, message: str) -> None:
        try:
            messagebox.showwarning(title, message, parent=self.winfo_toplevel())
        except Exception:
            pass

    def confirm_large_load(self, estimated_mb: float, limit_mb: float, message: str | None = None) -> bool:
        """Warn that the data held would go over the memory limit; Yes continues, No cancels.

        ``message`` is the full text from the controller (sizes, the limit and where it comes
        from, WI-0104 item 8); without it the short text of earlier versions is shown.
        """
        text = message or (
            f"With this scan the viewer would hold about {estimated_mb:,.0f} MB, over the "
            f"{limit_mb:,.0f} MB limit (viewer.cache.memory_limit_mb).\n\n"
            "Loading keeps the data in memory and needs somewhat more while loading. "
            "Load it anyway?"
        )
        try:
            return bool(messagebox.askyesno("Large data", text, icon="warning", parent=self.winfo_toplevel()))
        except Exception:
            return False

    def set_viewer_ranges(
        self,
        *,
        x: int,
        y: int,
        z: int,
        frames: int,
        slicepacks: int,
        indices: tuple[int, int, int],
        frame: int,
        slicepack: int,
        extra_dims: list[int] | None = None,
        extra_indices: list[int] | None = None,
    ) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "right"):
            try:
                target.right.set_ranges(x=x, y=y, z=z, frames=frames, slicepacks=slicepacks)
                target.right.set_indices(x=indices[0], y=indices[1], z=indices[2], frame=frame, slicepack=slicepack)
                target.right.set_extra_dims(extra_dims or [], extra_indices or [])
            except Exception:
                pass

    def set_viewer_value_display(self, value_text: str, *, plot_enabled: bool) -> None:
        tab = self.tabs.get_tab("Viewer")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "set_value_display"):
            target.set_value_display(value_text, plot_enabled=plot_enabled)

    def refresh_addons(self) -> None:
        tab = self.tabs.get_tab("Addons")
        target = getattr(tab, "_tab_instance", None)
        if target is not None and hasattr(target, "refresh_installed"):
            target.refresh_installed()
            if hasattr(target, "show_default_info_spec"):
                try:
                    target.show_default_info_spec()
                except Exception:
                    pass
