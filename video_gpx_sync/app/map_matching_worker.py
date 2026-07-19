from __future__ import annotations

import threading
from typing import Callable

import gpxpy.gpx
from PySide6.QtCore import QThread, Signal

from app.map_matcher import GpxMatchResult, MatchProgress, match_chunk, match_gpx_points


class MapMatchingWorker(QThread):
    progress = Signal(int, int)  # chunk_idx, total_chunks
    finished_matching = Signal(object)  # GpxMatchResult

    def __init__(
        self,
        points: list[gpxpy.gpx.GPXTrackPoint],
        parent=None,
        match_chunk_impl: Callable[[list[tuple[float, float]]], dict] = match_chunk,
    ) -> None:
        super().__init__(parent)
        self._points = points
        self._match_chunk_impl = match_chunk_impl
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        def on_progress(p: MatchProgress) -> None:
            self.progress.emit(p.chunk_idx, p.total_chunks)

        result: GpxMatchResult = match_gpx_points(
            self._points,
            on_progress=on_progress,
            should_cancel=self._cancel_event.is_set,
            match_chunk_impl=self._match_chunk_impl,
        )
        self.finished_matching.emit(result)
