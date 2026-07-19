from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget

MAP_QML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "map.qml",
)


class MapWidget(QQuickWidget):
    map_ready = Signal()

    def __init__(self, parent=None, qml_path: str = MAP_QML_PATH):
        super().__init__(parent)
        self._is_ready = False
        self._pending_calls: list[tuple[str, tuple]] = []

        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.statusChanged.connect(self._on_status_changed)
        self.setSource(QUrl.fromLocalFile(qml_path))

    def _on_status_changed(self, status: QQuickWidget.Status) -> None:
        if status != QQuickWidget.Status.Ready:
            return
        self._is_ready = True
        root = self.rootObject()
        for name, args in self._pending_calls:
            getattr(root, name)(*args)
        self._pending_calls.clear()
        self.map_ready.emit()

    def _call_qml(self, name: str, *args) -> None:
        if self._is_ready:
            getattr(self.rootObject(), name)(*args)
        else:
            self._pending_calls.append((name, args))

    def load_gpx_route(self, points: list[tuple[float, float]]) -> None:
        latlngs = [[lat, lon] for lat, lon in points]
        self._call_qml("loadRoute", latlngs)

    def update_route_ranges(self, in_range: list[bool]) -> None:
        """load_gpx_route()で描画済みのルートを、動画のStart/End出力範囲
        （in_range）に応じて2色に塗り分ける（クロップされる領域の可視化）。"""
        self._call_qml("updateRouteRanges", in_range)

    def update_marker(self, lat: float, lon: float) -> None:
        self._call_qml("updateMarker", lat, lon)

    def hide_marker(self) -> None:
        self._call_qml("hideMarker")

    def clear(self) -> None:
        self._call_qml("clearMap")
