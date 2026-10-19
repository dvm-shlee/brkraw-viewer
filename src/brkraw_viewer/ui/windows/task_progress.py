from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
import multiprocessing
import queue
import logging


class TaskProgressWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, log_queue: multiprocessing.Queue, title: str = "Task Progress") -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("600x400")
        self.log_queue = log_queue
        self._last_message = ""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.text = tk.Text(frame, wrap="word", state="disabled")
        self.text.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.progress.start(10)

        bottom = ttk.Frame(frame)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.close_var = tk.BooleanVar(master=self, value=True)
        ttk.Checkbutton(bottom, text="Close after task processed", variable=self.close_var).pack(side=tk.LEFT)

        self.close_button = ttk.Button(bottom, text="Close", command=self.destroy, state="disabled")
        self.close_button.pack(side=tk.RIGHT)

        self._polling = True
        self._poll_logs()

    def _poll_logs(self) -> None:
        if not self._polling:
            return
        try:
            while True:
                record = self.log_queue.get_nowait()
                msg = self._format_record(record)
                self.append_text(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_logs)

    def _format_record(self, record: logging.LogRecord) -> str:
        return f"[{record.levelname}] {record.getMessage()}\n"

    def append_text(self, text: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", text)
        self.text.see("end")
        self.text.configure(state="disabled")
        stripped = text.strip()
        if stripped:
            self._last_message = stripped

    def finish(self, success: bool = True) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.close_button.configure(state="normal")
        self._polling = False

        try:
            while True:
                record = self.log_queue.get_nowait()
                msg = self._format_record(record)
                self.append_text(msg)
        except queue.Empty:
            pass

        if success:
            self.append_text("\nTask completed successfully.\n")
            try:
                detail = self._last_message if self._last_message else "Task completed successfully."
                messagebox.showinfo(self.title(), detail)
            except Exception:
                pass
            if self.close_var.get():
                self.after(500, self.destroy)
        else:
            self.append_text("\nTask failed.\n")
            try:
                detail = self._last_message if self._last_message else "Task failed."
                messagebox.showerror(self.title(), detail)
            except Exception:
                pass
