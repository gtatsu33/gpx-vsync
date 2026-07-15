from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.camm_encoder import (
    CammEncodeError,
    CammTrackNotFoundError,
    extract_gps_track,
    interpolate_camm_points,
)
from app.map_widget import MapWidget
from app.video_widget import VideoWidget

VIDEO_FILE_FILTER = "Video Files (*.mp4 *.mov *.m4v);;All Files (*)"


class VerificationWindow(QMainWindow):
    """出力済みMP4に埋め込まれたCAMM GPSトラックを、動画再生に同期させて
    目視確認するための独立ウィンドウ。MainWindowのステートには依存しない。"""

    def __init__(self) -> None:
        super().__init__()
        self.camm_points: list[tuple[int, float, float, float]] = []

        self.setWindowTitle("検証モード - GPS埋め込み確認")
        self.resize(1280, 720)

        self._build_ui()
        self._build_menu()
        self._wire_signals()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.map_widget = MapWidget()
        self.video_widget = VideoWidget()
        splitter.addWidget(self.map_widget)
        splitter.addWidget(self.video_widget)
        splitter.setSizes([640, 640])

        main_layout.addWidget(splitter, stretch=1)

        button_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ 再生")
        self.stop_button = QPushButton("⏹ 停止")
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addStretch(1)
        main_layout.addLayout(button_layout)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("ファイル")
        self.open_video_action = QAction("動画を開く...", self)
        self.open_video_action.triggered.connect(self.open_video_dialog)
        menu.addAction(self.open_video_action)

    def _wire_signals(self) -> None:
        self.play_button.clicked.connect(self.video_widget.play)
        self.stop_button.clicked.connect(self.on_stop_clicked)
        self.video_widget.position_changed.connect(self.on_position_changed)

    # ------------------------------------------------------------------
    def open_video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "検証する動画を開く", "", VIDEO_FILE_FILTER
        )
        if path:
            self.open_video(path)

    def open_video(self, path: str) -> None:
        try:
            points = extract_gps_track(path)
        except (CammTrackNotFoundError, CammEncodeError) as exc:
            QMessageBox.warning(self, "GPS埋め込みの確認エラー", str(exc))
            return

        self.camm_points = points
        self.map_widget.load_gpx_route([(lat, lon) for _, lat, lon, _ in points])
        self.video_widget.load(path)

    # ------------------------------------------------------------------
    def on_position_changed(self, ms: int) -> None:
        pos = interpolate_camm_points(self.camm_points, ms)
        if pos is not None:
            self.map_widget.update_marker(*pos)
        else:
            self.map_widget.hide_marker()

    def on_stop_clicked(self) -> None:
        self.video_widget.pause()
        self.video_widget.seek(self.video_widget.timeline.start_ms())

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qtの命名規則に合わせる
        self.video_widget.player.stop()
        self.video_widget.player.setSource(QUrl())
        super().closeEvent(event)
