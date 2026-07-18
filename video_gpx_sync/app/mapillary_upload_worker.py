from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

from app.mapillary_validator import UploadResult, upload_export


class MapillaryUploadWorker(QThread):
    finished_upload = pyqtSignal(object)  # UploadResult | None

    def __init__(
        self,
        video_path: str,
        video_start_time: str,
        user_name: str | None = None,
        parent=None,
        upload_export_impl: Callable[..., UploadResult | None] = upload_export,
    ) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._video_start_time = video_start_time
        self._user_name = user_name
        self._upload_export_impl = upload_export_impl
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        result = self._upload_export_impl(
            self._video_path,
            self._video_start_time,
            user_name=self._user_name,
            should_cancel=self._cancel_event.is_set,
        )
        self.finished_upload.emit(result)
