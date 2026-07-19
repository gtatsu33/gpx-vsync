from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QThread, Signal

from app.mapillary_validator import ValidationResult, validate_export


class MapillaryValidationWorker(QThread):
    finished_validation = Signal(object)  # ValidationResult | None

    def __init__(
        self,
        video_path: str,
        video_start_time: str,
        parent=None,
        validate_export_impl: Callable[..., ValidationResult | None] = validate_export,
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._video_start_time = video_start_time
        self._validate_export_impl = validate_export_impl
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        result = self._validate_export_impl(
            self._video_path,
            self._video_start_time,
            should_cancel=self._cancel_event.is_set,
        )
        self.finished_validation.emit(result)
