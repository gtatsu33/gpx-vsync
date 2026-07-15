from __future__ import annotations

import datetime
from dataclasses import dataclass

import gpxpy.gpx


@dataclass
class AppState:
    video_path: str | None = None
    gpx_path: str | None = None
    gpx_data: gpxpy.gpx.GPX | None = None
    video_creation_time: datetime.datetime | None = None
    offset_seconds: float = 0.0
    video_start_ms: int = 0
    video_end_ms: int = 0
    video_duration_ms: int = 0
    video_time_scale: float = 1.0
