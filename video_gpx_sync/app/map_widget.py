from __future__ import annotations

import json
import os

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

MAP_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "map_template.html",
)


class MapWidget(QWebEngineView):
    map_ready = pyqtSignal()

    def __init__(self, parent=None, template_path: str = MAP_TEMPLATE_PATH):
        super().__init__(parent)
        self._is_ready = False
        self._pending_calls: list[str] = []

        # file:// で読み込んだHTMLはデフォルトでリモートURL（Leaflet CDN）に
        # アクセスできないため、明示的に許可する。
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        self.loadFinished.connect(self._on_load_finished)
        self.load(QUrl.fromLocalFile(template_path))

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            return
        self._is_ready = True
        for script in self._pending_calls:
            self.page().runJavaScript(script)
        self._pending_calls.clear()
        self.map_ready.emit()

    def _run_js(self, script: str) -> None:
        if self._is_ready:
            self.page().runJavaScript(script)
        else:
            self._pending_calls.append(script)

    def load_gpx_route(self, points: list[tuple[float, float]]) -> None:
        latlngs = [[lat, lon] for lat, lon in points]
        self._run_js(f"loadRoute({json.dumps(latlngs)});")

    def update_route_ranges(self, in_range: list[bool]) -> None:
        """load_gpx_route()で描画済みのルートを、動画のStart/End出力範囲
        （in_range）に応じて2色に塗り分ける（クロップされる領域の可視化）。"""
        self._run_js(f"updateRouteRanges({json.dumps(in_range)});")

    def update_marker(self, lat: float, lon: float) -> None:
        self._run_js(f"updateMarker({lat}, {lon});")

    def hide_marker(self) -> None:
        self._run_js("hideMarker();")

    def clear(self) -> None:
        self._run_js("clearMap();")
