from __future__ import annotations

from PyQt6.QtCore import QPointF, QRect, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QVBoxLayout, QWidget

MIN_GAP_MS = 100
HANDLE_HIT_RADIUS_PX = 10
BAR_MARGIN_PX = 12
BAR_HEIGHT_PX = 10
BAR_TOP_OFFSET_PX = 32


def format_time(ms: int) -> str:
    total_seconds = max(ms, 0) // 1000
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


class CustomTimeline(QWidget):
    start_changed = pyqtSignal(int)
    end_changed = pyqtSignal(int)
    seek_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._duration_ms = 0
        self._start_ms = 0
        self._end_ms = 0
        self._position_ms = 0
        self._dragging: str | None = None
        self.setMinimumHeight(80)
        self.setMouseTracking(True)

    def duration_ms(self) -> int:
        return self._duration_ms

    def start_ms(self) -> int:
        return self._start_ms

    def end_ms(self) -> int:
        return self._end_ms

    def position_ms(self) -> int:
        return self._position_ms

    def set_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(duration_ms, 0)
        self._start_ms = 0
        self._end_ms = self._duration_ms
        self.update()

    def set_position(self, position_ms: int) -> None:
        self._position_ms = position_ms
        self.update()

    def set_start(self, ms: int) -> None:
        self._start_ms = self._clamp_start(ms)
        self.update()

    def set_end(self, ms: int) -> None:
        self._end_ms = self._clamp_end(ms)
        self.update()

    def _clamp_start(self, ms: int) -> int:
        ms = max(ms, 0)
        ms = min(ms, self._end_ms - MIN_GAP_MS)
        return max(ms, 0)

    def _clamp_end(self, ms: int) -> int:
        ms = min(ms, self._duration_ms)
        ms = max(ms, self._start_ms + MIN_GAP_MS)
        return min(ms, self._duration_ms)

    def _bar_rect(self) -> QRect:
        return QRect(
            BAR_MARGIN_PX,
            BAR_TOP_OFFSET_PX,
            max(self.width() - 2 * BAR_MARGIN_PX, 1),
            BAR_HEIGHT_PX,
        )

    def _ms_to_x(self, ms: int) -> float:
        rect = self._bar_rect()
        if self._duration_ms <= 0:
            return float(rect.left())
        ratio = ms / self._duration_ms
        ratio = min(max(ratio, 0.0), 1.0)
        return rect.left() + ratio * rect.width()

    def _x_to_ms(self, x: float) -> int:
        rect = self._bar_rect()
        if rect.width() <= 0:
            return 0
        ratio = (x - rect.left()) / rect.width()
        ratio = min(max(ratio, 0.0), 1.0)
        return round(ratio * self._duration_ms)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self._bar_rect()

        painter.fillRect(rect, QColor(200, 200, 200))

        start_x = self._ms_to_x(self._start_ms)
        end_x = self._ms_to_x(self._end_ms)
        highlight = QRect(
            int(start_x), rect.top(), max(int(end_x - start_x), 0), rect.height()
        )
        painter.fillRect(highlight, QColor(100, 150, 255))

        pos_x = self._ms_to_x(self._position_ms)
        painter.setPen(QPen(QColor(220, 0, 0), 2))
        painter.drawLine(int(pos_x), rect.top() - 6, int(pos_x), rect.bottom() + 6)

        self._draw_handle(painter, start_x, rect.top(), QColor(0, 160, 0))
        self._draw_handle(painter, end_x, rect.top(), QColor(200, 0, 0))

        painter.setPen(QPen(QColor(0, 0, 0)))
        painter.drawText(rect.left(), rect.bottom() + 24, format_time(self._position_ms))
        painter.drawText(rect.left(), rect.top() - 8, f"S: {format_time(self._start_ms)}")
        end_label = f"E: {format_time(self._end_ms)}"
        painter.drawText(rect.right() - 70, rect.top() - 8, end_label)

    def _draw_handle(
        self, painter: QPainter, x: float, top_y: int, color: QColor
    ) -> None:
        size = 7
        points = [
            QPointF(x - size, top_y - size),
            QPointF(x + size, top_y - size),
            QPointF(x, top_y),
        ]
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF(points))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        x = event.position().x()
        start_x = self._ms_to_x(self._start_ms)
        end_x = self._ms_to_x(self._end_ms)

        if abs(x - start_x) <= HANDLE_HIT_RADIUS_PX:
            self._dragging = "start"
            return
        if abs(x - end_x) <= HANDLE_HIT_RADIUS_PX:
            self._dragging = "end"
            return

        # ハンドル以外の場所（現在位置線を含むバー全体）はシーク用のドラッグ
        # 対象とする。押した瞬間に一度シークし、そのままドラッグを継続すると
        # mouseMoveEvent側で連続的にシークする（スクラブ操作）。
        self._dragging = "position"
        ms = self._x_to_ms(x)
        ms = min(max(ms, self._start_ms), self._end_ms)
        self.seek_requested.emit(ms)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging is None:
            return
        x = event.position().x()
        ms = self._x_to_ms(x)

        if self._dragging == "start":
            self._start_ms = self._clamp_start(ms)
            self.start_changed.emit(self._start_ms)
        elif self._dragging == "end":
            self._end_ms = self._clamp_end(ms)
            self.end_changed.emit(self._end_ms)
        elif self._dragging == "position":
            ms = min(max(ms, self._start_ms), self._end_ms)
            self.seek_requested.emit(ms)

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._dragging = None


class VideoWidget(QWidget):
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.video_output = QVideoWidget()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_output)

        self.timeline = CustomTimeline()

        layout = QVBoxLayout(self)
        layout.addWidget(self.video_output, stretch=1)
        layout.addWidget(self.timeline)
        self.setLayout(layout)

        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)

        self.timeline.seek_requested.connect(self.seek)
        self.timeline.start_changed.connect(self._on_start_changed)
        self.timeline.end_changed.connect(self._on_end_changed)

    def load(self, path: str) -> None:
        self.player.setSource(QUrl.fromLocalFile(path))

    def play(self) -> None:
        position = self.player.position()
        start_ms = self.timeline.start_ms()
        end_ms = self.timeline.end_ms()
        if position < start_ms or position >= end_ms:
            self.player.setPosition(start_ms)
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def seek(self, ms: int) -> None:
        ms = min(max(ms, self.timeline.start_ms()), self.timeline.end_ms())
        self.player.setPosition(ms)

    def _on_position_changed(self, ms: int) -> None:
        end_ms = self.timeline.end_ms()
        if ms >= end_ms:
            if ms != end_ms:
                self.player.setPosition(end_ms)
            self.player.pause()
            ms = end_ms
        self.timeline.set_position(ms)
        self.position_changed.emit(ms)

    def _on_duration_changed(self, ms: int) -> None:
        self.timeline.set_duration(ms)
        self.duration_changed.emit(ms)

    def _on_start_changed(self, ms: int) -> None:
        if self.player.position() < ms:
            self.player.setPosition(ms)

    def _on_end_changed(self, ms: int) -> None:
        if self.player.position() > ms:
            self.player.setPosition(ms)
