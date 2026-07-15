from __future__ import annotations

import datetime
from typing import Callable

from PyQt6.QtCore import QDateTime, QUrl, Qt
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import APP_VERSION
from app.exporter import Exporter
from app.gpx_handler import GPXHandler
from app.map_matcher import match_chunk
from app.map_matching_dialog import MapMatchingDialog
from app.map_matching_worker import MapMatchingWorker
from app.map_widget import MapWidget
from app.mapillary_validation_dialog import MapillaryValidationDialog
from app.mapillary_validation_worker import MapillaryValidationWorker
from app.mapillary_validator import ValidationResult, is_mapillary_tools_available
from app.offset_widget import OffsetWidget
from app.state import AppState
from app.time_utils import playback_ms_to_real_ms
from app.timelapse_widget import DEFAULT_INTERVAL_SEC, TimelapseWidget
from app.verification_window import VerificationWindow
from app.video_handler import FFmpegError, VideoHandler
from app.video_widget import VideoWidget, format_time

GPX_FILE_FILTER = "GPX Files (*.gpx)"
VIDEO_FILE_FILTER = "Video Files (*.mp4 *.mov *.avi *.mkv *.m4v);;All Files (*)"


class MainWindow(QMainWindow):
    def __init__(
        self,
        match_chunk_impl: Callable[[list[tuple[float, float]]], dict] = match_chunk,
        is_mapillary_tools_available_impl: Callable[[], bool] = is_mapillary_tools_available,
        validate_export_impl: Callable[..., ValidationResult | None] | None = None,
    ) -> None:
        super().__init__()
        self.state = AppState()
        self.gpx_handler: GPXHandler | None = None
        self.video_handler = VideoHandler()
        self.exporter = Exporter(video_handler=self.video_handler)
        self._verification_windows: list[VerificationWindow] = []
        self._match_chunk_impl = match_chunk_impl
        self._is_mapillary_tools_available_impl = is_mapillary_tools_available_impl
        self._validate_export_impl = validate_export_impl
        self._video_fps: float | None = None

        self.setWindowTitle(f"Video-GPX Sync Tool v{APP_VERSION}")
        self.resize(1280, 720)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._wire_signals()
        self._update_export_button_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        self.map_widget = MapWidget()
        self.offset_widget = OffsetWidget()
        left_layout.addWidget(self.map_widget, stretch=1)
        left_layout.addWidget(self.offset_widget)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        self.video_widget = VideoWidget()
        self.timelapse_widget = TimelapseWidget()
        right_layout.addWidget(self.video_widget, stretch=1)
        right_layout.addWidget(self.timelapse_widget)

        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setSizes([640, 640])

        main_layout.addWidget(splitter, stretch=1)

        button_layout = QHBoxLayout()
        self.play_button = QPushButton("▶ 再生")
        self.pause_button = QPushButton("⏸ 一時停止")
        self.current_time_label = QLabel(format_time(0))
        self.export_button = QPushButton("\U0001f4e4 Export & Test")
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.current_time_label)
        button_layout.addStretch(1)
        button_layout.addWidget(self.export_button)
        main_layout.addLayout(button_layout)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("ファイル")

        self.open_gpx_action = QAction("GPXを開く...", self)
        self.open_gpx_action.triggered.connect(self.open_gpx_dialog)
        menu.addAction(self.open_gpx_action)

        self.open_video_action = QAction("動画を開く...", self)
        self.open_video_action.triggered.connect(self.open_video_dialog)
        self.open_video_action.setEnabled(False)
        menu.addAction(self.open_video_action)

        tools_menu = self.menuBar().addMenu("ツール")
        self.open_verification_window_action = QAction("検証モードを開く...", self)
        self.open_verification_window_action.triggered.connect(
            self.open_verification_window
        )
        tools_menu.addAction(self.open_verification_window_action)

    def _wire_signals(self) -> None:
        self.play_button.clicked.connect(self.video_widget.play)
        self.pause_button.clicked.connect(self.on_pause_clicked)
        self.export_button.clicked.connect(self.on_export_clicked)

        self.video_widget.position_changed.connect(self.on_position_changed)
        self.video_widget.duration_changed.connect(self.on_duration_changed)
        self.video_widget.timeline.start_changed.connect(self.on_start_changed)
        self.video_widget.timeline.end_changed.connect(self.on_end_changed)

        self.offset_widget.offset_changed.connect(self.on_offset_changed)
        self.offset_widget.force_sync_button.clicked.connect(
            self.on_force_sync_clicked
        )
        self.timelapse_widget.timelapse_changed.connect(self.on_timelapse_changed)

    # ------------------------------------------------------------------
    # Drag & drop（GPX未読み込み時は動画ファイルのドロップを拒否する）
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".gpx"):
                event.acceptProposedAction()
                return
            if self.state.gpx_data is not None:
                event.acceptProposedAction()
                return

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".gpx"):
                self.load_gpx(path)
            elif self.state.gpx_data is not None:
                self.load_video(path)
            else:
                QMessageBox.warning(
                    self,
                    "エラー",
                    "先にGPXファイルを読み込んでください",
                )

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------
    def open_gpx_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "GPXファイルを開く", "", GPX_FILE_FILTER
        )
        if path:
            self.load_gpx(path)

    def open_video_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画ファイルを開く",
            "",
            VIDEO_FILE_FILTER,
        )
        if path:
            self.load_video(path)

    def open_verification_window(self) -> None:
        window = VerificationWindow()
        self._verification_windows.append(window)
        window.show()

    def load_gpx(self, path: str) -> None:
        try:
            handler = GPXHandler.load(path)
        except Exception as exc:  # noqa: BLE001 - ユーザーへの通知が目的
            QMessageBox.warning(self, "GPX読み込みエラー", str(exc))
            return

        points = handler.get_all_points()
        if not points:
            QMessageBox.warning(
                self,
                "GPX読み込みエラー",
                "時刻付きトラックポイントが見つかりません",
            )
            return

        matched_points = self._run_map_matching(points)
        handler.replace_points(matched_points)

        self.gpx_handler = handler
        self.state.gpx_path = path
        self.state.gpx_data = handler.gpx

        self.map_widget.load_gpx_route(
            [(p.latitude, p.longitude) for p in matched_points]
        )
        self.open_video_action.setEnabled(True)
        self._update_export_button_state()

    def _run_map_matching(self, points):
        """GPX読み込み時のマップマッチング（5-9節）。ワーカーをバックグラウンド
        実行しつつ進捗ダイアログをモーダル表示し、完了まで待つ。"""
        worker = MapMatchingWorker(points, match_chunk_impl=self._match_chunk_impl)
        dialog = MapMatchingDialog(worker, self)

        result_holder: dict = {}
        worker.finished_matching.connect(
            lambda result: result_holder.update(result=result)
        )

        worker.start()
        dialog.exec()
        worker.wait()

        return result_holder["result"].points

    def load_video(self, path: str) -> None:
        if self.state.gpx_data is None:
            QMessageBox.warning(
                self,
                "エラー",
                "先にGPXファイルを読み込んでください",
            )
            return

        try:
            creation_time_str = self.video_handler.get_creation_time(path)
            duration_ms = self.video_handler.get_duration_ms(path)
        except FFmpegError as exc:
            QMessageBox.warning(self, "動画読み込みエラー", str(exc))
            return

        if creation_time_str:
            creation_time = self._parse_iso_utc(creation_time_str)
        else:
            creation_time = self._prompt_creation_time()
            if creation_time is None:
                return

        self.state.video_path = path
        self.state.video_creation_time = creation_time
        self.state.video_duration_ms = duration_ms
        self.state.video_start_ms = 0
        self.state.video_end_ms = duration_ms
        self.state.video_time_scale = 1.0

        try:
            self._video_fps = self.video_handler.get_fps(path)
        except FFmpegError:
            self._video_fps = None

        # 動画差し替え時はタイムラプス設定を初期状態に戻す
        # （reset()が発火するtimelapse_changedシグナル経由でstate/再生レートも同期される）
        self.timelapse_widget.reset()

        try:
            has_audio = self.video_handler.has_audio_stream(path)
        except FFmpegError:
            has_audio = True  # 判定不能時はヒント表示を控える(fail-safe)

        timelapse_enabled, interval_sec = self._prompt_timelapse_settings(has_audio)
        if timelapse_enabled:
            self.timelapse_widget.checkbox.setChecked(True)
            self.timelapse_widget.interval_spinbox.setValue(interval_sec)

        self.video_widget.load(path)
        self._apply_playback_rate()
        self._update_export_button_state()

    @staticmethod
    def _parse_iso_utc(value: str) -> datetime.datetime:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    def _prompt_creation_time(self) -> datetime.datetime | None:
        assert self.gpx_handler is not None
        points = self.gpx_handler.get_all_points()
        if points:
            default_local = points[0].time.astimezone()
        else:
            default_local = datetime.datetime.now().astimezone()

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "動画の録画開始時刻を入力"
        )
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "動画に作成日時が見つかりませんでした。\n"
                "録画開始時刻（ローカル時刻）を入力してください。"
            )
        )
        dt_edit = QDateTimeEdit(QDateTime(default_local.replace(tzinfo=None)))
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        dt_edit.setCalendarPopup(True)
        layout.addWidget(dt_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        local_naive = dt_edit.dateTime().toPyDateTime()
        return local_naive.astimezone(datetime.timezone.utc)

    def _prompt_timelapse_settings(self, has_audio: bool) -> tuple[bool, float]:
        """動画読み込み時（メニュー・ドラッグ&ドロップ両方）に毎回表示する
        確認ダイアログ。タイムラプス設定（15章）を動画読み込みの
        タイミングで確実に目に入る場所に提示するためのもの。
        音声トラックが無い場合は、その旨のヒントをダイアログ内に含める。
        戻り値は(タイムラプスが有効か, 間隔秒)。キャンセル操作に相当する
        ものは無く（既定値のまま進めても実害が無いため）、常にOKボタン
        押下時点のウィジェット状態を返す。"""
        dialog = QDialog(self)
        dialog.setWindowTitle("動画の設定確認")
        layout = QVBoxLayout(dialog)

        if not has_audio:
            layout.addWidget(
                QLabel(
                    "この動画には音声トラックが検出されませんでした。\n"
                    "タイムラプス動画の可能性があります"
                    "（自動判定ではないため確証はありません）。"
                )
            )

        row = QHBoxLayout()
        checkbox = QCheckBox("タイムラプス動画")
        row.addWidget(checkbox)
        row.addWidget(QLabel("間隔(秒):"))
        interval_spinbox = QDoubleSpinBox()
        interval_spinbox.setRange(0.01, 3600.0)
        interval_spinbox.setDecimals(2)
        interval_spinbox.setSingleStep(0.5)
        interval_spinbox.setValue(DEFAULT_INTERVAL_SEC)
        interval_spinbox.setEnabled(False)
        checkbox.toggled.connect(interval_spinbox.setEnabled)
        row.addWidget(interval_spinbox)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

        return checkbox.isChecked(), interval_spinbox.value()

    # ------------------------------------------------------------------
    # Playback / map sync
    # ------------------------------------------------------------------
    def on_position_changed(self, ms: int) -> None:
        self.current_time_label.setText(format_time(ms))
        if self.gpx_handler is None or self.state.video_creation_time is None:
            return
        pos = self.gpx_handler.interpolate_position(
            ms,
            self.state.offset_seconds,
            self.state.video_creation_time,
            self.state.video_time_scale,
        )
        if pos is not None:
            self.map_widget.update_marker(*pos)
        else:
            self.map_widget.hide_marker()

    def on_timelapse_changed(self, enabled: bool, interval_sec: float) -> None:
        """タイムラプス設定（TimelapseWidget）変更時、再生位置→実世界時刻の
        変換倍率(video_time_scale)を更新し、プレビュー・再生レート・出力可否に
        反映する。"""
        if enabled and self._video_fps is not None:
            self.state.video_time_scale = interval_sec * self._video_fps
        else:
            self.state.video_time_scale = 1.0
        self._apply_playback_rate()
        self.on_position_changed(self.video_widget.timeline.position_ms())
        self._update_export_button_state()

    def _apply_playback_rate(self) -> None:
        """タイムラプス有効時は、動画の再生速度をvideo_time_scaleの逆数に
        設定し、見かけ上「実世界の経過時間通り」に再生されるようにする
        （例: 0.5秒間隔・29.97fps → 見かけ上2fps相当）。音声は無意味な
        速度になるためミュートする。"""
        if self.state.video_time_scale != 1.0:
            self.video_widget.player.setPlaybackRate(1.0 / self.state.video_time_scale)
            self.video_widget.audio_output.setMuted(True)
        else:
            self.video_widget.player.setPlaybackRate(1.0)
            self.video_widget.audio_output.setMuted(False)

    def on_duration_changed(self, ms: int) -> None:
        self.state.video_duration_ms = ms
        self.state.video_start_ms = self.video_widget.timeline.start_ms()
        self.state.video_end_ms = self.video_widget.timeline.end_ms()
        self._update_export_button_state()

    def on_start_changed(self, ms: int) -> None:
        self.state.video_start_ms = ms
        self._update_export_button_state()

    def on_end_changed(self, ms: int) -> None:
        self.state.video_end_ms = ms
        self._update_export_button_state()

    def on_offset_changed(self, seconds: float) -> None:
        self.state.offset_seconds = seconds
        self.on_position_changed(self.video_widget.timeline.position_ms())
        self._update_export_button_state()

    def on_force_sync_clicked(self) -> None:
        """GPXデータ先頭とタイムラインのStartマーカー位置の時刻を
        強制的に一致させるオフセットを計算し適用する（安全策ボタン）。"""
        if self.gpx_handler is None or self.state.video_creation_time is None:
            QMessageBox.warning(
                self,
                "エラー",
                "先に動画を読み込んでください",
            )
            return

        points = self.gpx_handler.get_all_points()
        gpx_start_time = points[0].time
        video_start_true_time = self.state.video_creation_time + datetime.timedelta(
            milliseconds=playback_ms_to_real_ms(
                self.state.video_start_ms, self.state.video_time_scale
            )
        )
        offset_sec = (gpx_start_time - video_start_true_time).total_seconds()
        self.offset_widget.set_offset(offset_sec)

    def on_pause_clicked(self) -> None:
        self.video_widget.pause()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _update_export_button_state(self) -> None:
        self.export_button.setEnabled(self.exporter.can_export(self.state))

    def on_export_clicked(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(
            self, "出力先を選択"
        )
        if not output_dir:
            return

        try:
            video_path, gpx_path = self.exporter.export(self.state, output_dir)
        except Exception as exc:  # noqa: BLE001 - ユーザーへの通知が目的
            QMessageBox.warning(self, "出力エラー", str(exc))
            return

        command = self.exporter.build_mapillary_tools_command(
            self.state, video_path, gpx_path
        )
        validation_message = self._validate_export_and_format_message(video_path)

        QMessageBox.information(
            self,
            "出力完了",
            f"出力が完了しました。\n\n"
            f"動画: {video_path}\nGPX: {gpx_path}\n\n"
            f"{validation_message}\n\n"
            f"Mapillaryへアップロードするには"
            f"以下のコマンドを実行してください:\n\n{command}",
        )

    def _validate_export_and_format_message(self, video_path: str) -> str:
        """出力後ローカル検証（5-10節）。mapillary_toolsが利用可能な場合のみ、
        バックグラウンドでvideo_processを実行し、結果メッセージを返す。"""
        if not self._is_mapillary_tools_available_impl():
            return "ローカル検証: mapillary_toolsが見つからないためスキップされました"

        video_start_time = self.exporter.get_video_start_time_str(self.state)

        worker_kwargs = {}
        if self._validate_export_impl is not None:
            worker_kwargs["validate_export_impl"] = self._validate_export_impl
        worker = MapillaryValidationWorker(video_path, video_start_time, **worker_kwargs)
        dialog = MapillaryValidationDialog(worker, self)

        result_holder: dict = {}
        worker.finished_validation.connect(
            lambda result: result_holder.update(result=result)
        )

        worker.start()
        dialog.exec()
        worker.wait()

        return self._format_validation_message(result_holder.get("result"))

    @staticmethod
    def _format_validation_message(result: ValidationResult | None) -> str:
        if result is None:
            return "ローカル検証: キャンセルされました"
        if result.ok:
            message = f"ローカル検証: OK（{result.n_images}件の画像相当データを検出）"
        else:
            message = "ローカル検証: 失敗\n" + "\n".join(result.errors)
        if result.warnings:
            message += f"\n警告 {len(result.warnings)}件"
        return message

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qtの命名規則に合わせる
        self.video_widget.player.stop()
        self.video_widget.player.setSource(QUrl())
        for window in self._verification_windows:
            window.close()
        super().closeEvent(event)
