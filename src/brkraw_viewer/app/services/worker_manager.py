from __future__ import annotations

import logging
import multiprocessing
from typing import Optional, Callable
import queue

from ..workers.convert_worker import run_worker
from ..workers.protocol import (
    ConvertRequest,
    ConvertResult,
    LoadVolumeRequest,
    LoadVolumeResult,
    TimecourseRequest,
    TimecourseResult,
    RegistryRequest,
    RegistryResult,
)

logger = logging.getLogger("brkraw.manager")


class WorkerManager:
    def __init__(
        self,
        *,
        on_convert_result: Optional[Callable[[ConvertResult], None]] = None,
        on_volume_result: Optional[Callable[[LoadVolumeResult], None]] = None,
        on_timecourse_result: Optional[Callable[[TimecourseResult], None]] = None,
        on_registry_result: Optional[Callable[[RegistryResult], None]] = None,
    ) -> None:
        self._input_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._output_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._log_queue: multiprocessing.Queue = multiprocessing.Queue()
        self._worker: Optional[multiprocessing.Process] = None
        self._running = False
        self._on_convert_result = on_convert_result
        self._on_volume_result = on_volume_result
        self._on_timecourse_result = on_timecourse_result
        self._on_registry_result = on_registry_result

    @property
    def log_queue(self) -> multiprocessing.Queue:
        return self._log_queue

    def is_alive(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = multiprocessing.Process(
            target=run_worker,
            args=(self._input_queue, self._output_queue, self._log_queue),
            daemon=True,
        )
        self._worker.start()
        self._running = True
        logger.info("Worker started.")

    def stop(self) -> None:
        if self._worker is None:
            return
        self._input_queue.put(None)
        self._worker.join(timeout=1.0)
        if self._worker.is_alive():
            self._worker.terminate()
        self._worker = None
        self._running = False
        logger.info("Worker stopped.")

    def submit(self, request: ConvertRequest | LoadVolumeRequest | TimecourseRequest | RegistryRequest) -> None:
        if not self._running:
            self.start()
        self._input_queue.put(request)

    def check_results(self) -> None:
        while True:
            try:
                result = self._output_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_result(result)

    def _handle_result(self, result: object) -> None:
        if isinstance(result, ConvertResult):
            if self._on_convert_result:
                self._on_convert_result(result)
            return
        if isinstance(result, LoadVolumeResult):
            if self._on_volume_result:
                self._on_volume_result(result)
            return
        if isinstance(result, TimecourseResult):
            if self._on_timecourse_result:
                self._on_timecourse_result(result)
            return
        if isinstance(result, RegistryResult):
            if self._on_registry_result:
                self._on_registry_result(result)
            return
