from __future__ import annotations

import datetime
import time
from typing import Callable

from PyQt6.QtCore import QDateTime, QSettings, QUrl, Qt
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import APP_VERSION
from app.camm_encoder import CammEncodeError, CammTrackNotFoundError, extract_gps_track
from app.exporter import Exporter
from app.gpx_handler import GPXHandler
from app.map_matcher import GpxMatchResult, match_chunk
from app.map_matching_dialog import MapMatchingDialog
from app.map_matching_worker import MapMatchingWorker
from app.map_widget import MapWidget
from app.mapillary_upload_dialog import MapillaryUploadDialog
from app.mapillary_upload_worker import MapillaryUploadWorker
from app.mapillary_validation_dialog import MapillaryValidationDialog
from app.mapillary_validation_worker import MapillaryValidationWorker
from app.mapillary_validator import (
    UploadResult,
    ValidationResult,
    is_mapillary_tools_available,
)
from app.offset_widget import OffsetWidget
from app.state import AppState
from app.time_utils import playback_ms_to_real_ms
from app.timelapse_widget import DEFAULT_INTERVAL_SEC, TimelapseWidget
from app.video_handler import FFmpegError, VideoHandler
from app.video_widget import VideoWidget, format_time

GPX_FILE_FILTER = "GPX Files (*.gpx)"
VIDEO_FILE_FILTER = "Video Files (*.mp4 *.mov *.avi *.mkv *.m4v);;All Files (*)"
REVERSE_INITIAL_STEP_MS = 40

SETTINGS_ORG = "gpx_vsync"
SETTINGS_APP = "VideoGpxSyncTool"
MAPILLARY_USERNAME_SETTINGS_KEY = "mapillary/user_name"


class MainWindow(QMainWindow):
    def __init__(
        self,
        match_chunk_impl: Callable[[list[tuple[float, float]]], dict] = match_chunk,
        is_mapillary_tools_available_impl: Callable[[], bool] = is_mapillary_tools_available,
        validate_export_impl: Callable[..., ValidationResult | None] | None = None,
        upload_export_impl: Callable[..., UploadResult | None] | None = None,
    ) -> None:
        super().__init__()
        self.state = AppState()
        self.gpx_handler: GPXHandler | None = None
        self.video_handler = VideoHandler()
        self.exporter = Exporter(video_handler=self.video_handler)
        self._match_chunk_impl = match_chunk_impl
        self._is_mapillary_tools_available_impl = is_mapillary_tools_available_impl
        self._validate_export_impl = validate_export_impl
        self._upload_export_impl = upload_export_impl
        self._video_fps: float | None = None
        self._reverse_active = False
        self._reverse_last_step_time: float | None = None

        self.setWindowTitle(f"Video-GPX Sync Tool v{APP_VERSION}")
        self.resize(1280, 720)
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menu()
        self._wire_signals()
        self._update_export_button_state()
        self._update_open_button_emphasis()
        self._update_frame_step_buttons_enabled()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_pane = QFrame()
        left_pane.setObjectName("card")
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        left_header = QHBoxLayout()
        left_title = QLabel("マップ")
        left_title.setProperty("subtle", True)
        self.open_gpx_button = QPushButton("GPXを開く")
        left_header.addWidget(left_title)
        left_header.addStretch(1)
        left_header.addWidget(self.open_gpx_button)
        left_layout.addLayout(left_header)

        self.map_matching_status_label = QLabel("")
        self.map_matching_status_label.setVisible(False)
        left_layout.addWidget(self.map_matching_status_label)

        self.map_widget = MapWidget()
        self.offset_widget = OffsetWidget()
        left_layout.addWidget(self.map_widget, stretch=1)
        left_layout.addWidget(self.offset_widget)

        right_pane = QFrame()
        right_pane.setObjectName("card")
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(10)

        right_header = QHBoxLayout()
        right_title = QLabel("動画")
        right_title.setProperty("subtle", True)
        self.open_video_button = QPushButton("動画を開く")
        right_header.addWidget(right_title)
        right_header.addStretch(1)
        right_header.addWidget(self.open_video_button)
        right_layout.addLayout(right_header)

        self.video_info_label = QLabel("")
        self.video_info_label.setVisible(False)
        right_layout.addWidget(self.video_info_label)

        self.video_widget = VideoWidget()
        right_layout.addWidget(self.video_widget, stretch=1)

        transport_layout = QHBoxLayout()
        transport_layout.setSpacing(8)
        self.reverse_button = QPushButton("◀ 逆再生")
        self.step_back_button = QPushButton("⏮ コマ戻り")
        self.pause_button = QPushButton("⏸ 一時停止")
        self.step_forward_button = QPushButton("⏭ コマ送り")
        self.play_button = QPushButton("▶ 再生")
        self.current_time_label = QLabel(format_time(0))
        transport_layout.addWidget(self.reverse_button)
        transport_layout.addWidget(self.step_back_button)
        transport_layout.addWidget(self.pause_button)
        transport_layout.addWidget(self.step_forward_button)
        transport_layout.addWidget(self.play_button)
        transport_layout.addStretch(1)
        transport_layout.addWidget(self.current_time_label)
        right_layout.addLayout(transport_layout)

        self.timelapse_widget = TimelapseWidget()
        right_layout.addWidget(self.timelapse_widget)

        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setSizes([640, 640])

        main_layout.addWidget(splitter, stretch=1)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        self.export_button = QPushButton("\U0001f4e4 Export && Test")
        self.export_button.setObjectName("primaryButton")
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
        menu.addAction(self.open_video_action)

        menu.addSeparator()

        self.mapillary_username_action = QAction("Mapillaryユーザー名...", self)
        self.mapillary_username_action.triggered.connect(
            self.on_edit_mapillary_username_clicked
        )
        menu.addAction(self.mapillary_username_action)

    @staticmethod
    def _mapillary_settings() -> QSettings:
        # IniFormatを明示することで、QSettings.setPath()によるテスト時の
        # 保存先リダイレクトが効くようにする（macOSのNativeFormat＝plistは
        # setPath()の対象外で、素の QSettings(org, app) だと常に実際の
        # ~/Library/Preferences/ を読み書きしてしまいテストを汚染する）。
        return QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            SETTINGS_ORG,
            SETTINGS_APP,
        )

    def _get_mapillary_user_name(self) -> str:
        """事前に`mapillary_tools authenticate`で認証済みのユーザー名
        （--user_name用）。QSettingsでOS標準の設定ストレージに保存され、
        アプリを再起動しても保持される（24章）。"""
        return self._mapillary_settings().value(
            MAPILLARY_USERNAME_SETTINGS_KEY, "", type=str
        )

    def _set_mapillary_user_name(self, value: str) -> None:
        self._mapillary_settings().setValue(MAPILLARY_USERNAME_SETTINGS_KEY, value)

    def on_edit_mapillary_username_clicked(self) -> None:
        current = self._get_mapillary_user_name()
        text, ok = QInputDialog.getText(
            self,
            "Mapillaryユーザー名",
            "mapillary_tools authenticateで認証済みのユーザー名を"
            "入力してください（空欄にすると--user_name指定なしに戻ります）:",
            text=current,
        )
        if not ok:
            return
        self._set_mapillary_user_name(text.strip())

    def _wire_signals(self) -> None:
        self.open_gpx_button.clicked.connect(self.open_gpx_dialog)
        self.open_video_button.clicked.connect(self.open_video_dialog)

        self.play_button.clicked.connect(self.on_play_clicked)
        self.pause_button.clicked.connect(self.on_pause_clicked)
        self.reverse_button.clicked.connect(self.on_reverse_clicked)
        self.step_back_button.clicked.connect(self.on_step_back_clicked)
        self.step_forward_button.clicked.connect(self.on_step_forward_clicked)
        self.export_button.clicked.connect(self.on_export_clicked)

        self.video_widget.position_changed.connect(self.on_position_changed)
        self.video_widget.duration_changed.connect(self.on_duration_changed)
        self.video_widget.seek_settled.connect(self._on_seek_settled)
        self.video_widget.timeline.start_changed.connect(self.on_start_changed)
        self.video_widget.timeline.end_changed.connect(self.on_end_changed)

        self.offset_widget.offset_changed.connect(self.on_offset_changed)
        self.offset_widget.force_sync_button.clicked.connect(
            self.on_force_sync_clicked
        )
        self.timelapse_widget.timelapse_changed.connect(self.on_timelapse_changed)

    # ------------------------------------------------------------------
    # Drag & drop（GPX・動画とも読み込み順序を問わず受け付ける。22章）
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not event.mimeData().hasUrls():
            return
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".gpx"):
                self.load_gpx(path)
            else:
                self.load_video(path)

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

        result = self._run_map_matching(points)
        handler.replace_points(result.points)

        self._apply_gps_source(handler, gpx_path=path)
        self._update_map_matching_status(result, total_points=len(points))

    def _apply_gps_source(self, handler: GPXHandler, gpx_path: str) -> None:
        """GPXデータを内部状態に反映する共通処理（22章）。GPXファイルの
        明示読み込み・動画に埋め込まれたCAMM GPSトラックの抽出、
        いずれの経路でも呼ばれる。最後に読み込んだGPS付きファイルが
        常に優先される（最後勝ちルール）。"""
        self.gpx_handler = handler
        self.state.gpx_path = gpx_path
        self.state.gpx_data = handler.gpx

        self.map_widget.load_gpx_route(
            [(p.latitude, p.longitude) for p in handler.get_all_points()]
        )
        self._update_export_button_state()
        self._update_open_button_emphasis()
        self._update_route_range_highlight()

        # GPSデータソースが切り替わった以上、直前のセッションで調整した
        # オフセットは新しいデータに対してはもはや正しくない（2026-07-18
        # 実機で発生した不具合の修正）。特に、本ツール自身がExportした
        # 「synced」動画は埋め込みGPSに既にオフセット適用済みの実時刻が
        # 焼き込まれているため、そのまま古いオフセットが生き残ると
        # 二重にオフセットがかかり同期がズレる。offset_widget.reset()は
        # 内部状態のリセットに加えoffset_changedシグナルを発行するため、
        # state.offset_seconds・マップの現在地マーカー・出力ボタンの
        # 有効状態・ルート塗り分けも連動して更新される。
        self.offset_widget.reset()

    def _run_map_matching(self, points) -> GpxMatchResult:
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

        return result_holder["result"]

    def _update_map_matching_status(self, result: GpxMatchResult, total_points: int) -> None:
        """マップマッチング結果（16章）を左カードに常設表示する。タイムアウト等で
        一部/全部の点が未処理のまま終わっていないかを一目で確認できるようにする。
        match_route()のstatusは「エラー」でも実際にはチャンク処理自体は全て
        成功し単にスナップ対象が無かっただけ、というケースがあるため（n_snapped==0
        で確定するstatus文言）、成否の判定は result.error の有無を優先する。"""
        if result.error is None:
            state = "ok"
            text = f"✓ マップマッチング完了（{total_points}点中{result.n_snapped}点をスナップ）"
        elif result.status == "キャンセル":
            state = "error"
            text = "✗ マップマッチング中断（タイムアウトのため元座標のまま使用）"
        else:
            state = "warn"
            text = (
                f"⚠ マップマッチング一部失敗"
                f"（{total_points}点中{result.n_snapped}点をスナップ）"
            )

        self._set_map_matching_status_label(text, state, tooltip=result.error or "")

    def _update_gps_source_status_for_camm(self, point_count: int) -> None:
        """動画に埋め込まれたCAMM GPSトラックをGPXデータとして採用した
        際のステータス表示（22章）。マップマッチングは適用していない
        （既に処理済みの実走行データのため）ため、
        _update_map_matching_status()とは異なる文言で表示する。"""
        text = f"✓ 動画に埋め込まれたGPSデータを使用（{point_count}点）"
        self._set_map_matching_status_label(text, "ok")

    def _set_map_matching_status_label(
        self, text: str, state: str, tooltip: str = ""
    ) -> None:
        self.map_matching_status_label.setText(text)
        self.map_matching_status_label.setToolTip(tooltip)
        self.map_matching_status_label.setProperty("state", state)
        self.map_matching_status_label.style().unpolish(self.map_matching_status_label)
        self.map_matching_status_label.style().polish(self.map_matching_status_label)
        self.map_matching_status_label.setVisible(True)

    def _set_button_emphasis(self, button: QPushButton, emphasize: bool) -> None:
        """未読み込み状態のOpenボタンをprimaryButton化して目立たせる
        （17章）。objectName変更後はunpolish/polishでQSSを再適用する
        必要があることを実機検証済み。"""
        button.setObjectName("primaryButton" if emphasize else "")
        button.style().unpolish(button)
        button.style().polish(button)

    def _update_open_button_emphasis(self) -> None:
        """22章: GPX・動画は読み込み順序を問わないため、それぞれ独立に
        「まだ読み込んでいなければ強調」を判定する（互いの読み込み状況
        に依存しない）。"""
        self._set_button_emphasis(self.open_gpx_button, self.state.gpx_data is None)
        self._set_button_emphasis(
            self.open_video_button, self.state.video_path is None
        )

    def load_video(self, path: str) -> None:
        self._stop_reverse()

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
        self._update_frame_step_buttons_enabled()

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

        self._try_load_embedded_gps(path)

        self.video_widget.load(path)
        self._apply_playback_rate()
        self._update_export_button_state()
        self._update_open_button_emphasis()

    def _try_load_embedded_gps(self, path: str) -> None:
        """動画にCAMM形式のGPSトラックが埋め込まれている場合、それを
        GPXデータとして採用する（23章。最後に読み込んだGPS付きファイル
        が常に優先されるルール）。埋め込みが無い動画の場合は何もせず、
        既存のGPXデータ（あれば）をそのまま維持する。マップマッチングは
        適用しない（既に処理済みの実走行データのため）。"""
        try:
            camm_points = extract_gps_track(path)
        except (CammTrackNotFoundError, CammEncodeError):
            return
        if not camm_points:
            return

        # MP4BoxでCAMMトラックを追加すると、動画コンテナのcreation_time
        # メタデータが処理実行時刻で上書きされてしまうことが実機で判明
        # している（4-8節「制約3」）。そのためffprobe由来の
        # video_creation_timeは信用できず、CAMM自身の先頭サンプル
        # （relative_msが最小、通常は0）のepoch_timeを真の動画開始
        # 時刻として採用する（実機で発生した不具合の対応。23章）。
        first_point = min(camm_points, key=lambda p: p[0])
        self.state.video_creation_time = datetime.datetime.fromtimestamp(
            first_point[4], tz=datetime.timezone.utc
        )

        handler = GPXHandler.from_camm_points(camm_points)
        self._apply_gps_source(handler, gpx_path=path)
        self._update_gps_source_status_for_camm(len(camm_points))

    @staticmethod
    def _parse_iso_utc(value: str) -> datetime.datetime:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    def _prompt_creation_time(self) -> datetime.datetime | None:
        # 22章: GPXが動画より先に読み込まれているとは限らないため、
        # gpx_handler未読み込みの場合は現在時刻をデフォルト値にする。
        points = self.gpx_handler.get_all_points() if self.gpx_handler else []
        if points:
            default_local = points[0].time.astimezone()
        else:
            default_local = datetime.datetime.now().astimezone()

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "動画の録画開始時刻を入力"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
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
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

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
        self._update_video_info_label(interval_sec)
        self._update_route_range_highlight()

    def _update_video_info_label(self, interval_sec: float) -> None:
        """動画の素性（fps・タイムラプス設定）を右カードのヘッダー直下に
        表示する（17章）。左カードのmap_matching_status_labelと同じ
        位置に配置することで、左右カードの上下位置を揃えている。
        文字色も左カードと同じstateプロパティ方式で統一する
        （2026-07-18、既定の黒文字だったのをアクセントカラーに変更）。"""
        if self.state.video_path is None:
            self.video_info_label.setVisible(False)
            return

        if self._video_fps is None:
            text = "fps不明"
            state = "warn"
        else:
            text = f"{self._video_fps:.2f}fps"
            if self.state.video_time_scale != 1.0:
                text += f"（{interval_sec:g}sタイムラプス）"
            state = "ok"

        self.video_info_label.setText(text)
        self.video_info_label.setProperty("state", state)
        self.video_info_label.style().unpolish(self.video_info_label)
        self.video_info_label.style().polish(self.video_info_label)
        self.video_info_label.setVisible(True)

    def _current_playback_rate(self) -> float:
        """タイムラプス設定を反映した順再生の速度倍率。_apply_playback_rate()
        （QMediaPlayer.setPlaybackRate()向け）と_reverse_step()
        （疑似逆再生の1ステップあたりの移動量計算向け）で共通利用する。"""
        if self.state.video_time_scale == 1.0:
            return 1.0
        return 1.0 / self.state.video_time_scale

    def _apply_playback_rate(self) -> None:
        """タイムラプス有効時は、動画の再生速度をvideo_time_scaleの逆数に
        設定し、見かけ上「実世界の経過時間通り」に再生されるようにする
        （例: 0.5秒間隔・29.97fps → 見かけ上2fps相当）。音声は無意味な
        速度になるためミュートする。"""
        if self.state.video_time_scale != 1.0:
            self.video_widget.player.setPlaybackRate(self._current_playback_rate())
            self.video_widget.audio_output.setMuted(True)
        else:
            self.video_widget.player.setPlaybackRate(1.0)
            self.video_widget.audio_output.setMuted(False)

    def on_duration_changed(self, ms: int) -> None:
        self.state.video_duration_ms = ms
        self.state.video_start_ms = self.video_widget.timeline.start_ms()
        self.state.video_end_ms = self.video_widget.timeline.end_ms()
        self._update_export_button_state()
        self._update_route_range_highlight()

    def on_start_changed(self, ms: int) -> None:
        self.state.video_start_ms = ms
        self._update_export_button_state()
        self._update_route_range_highlight()

    def on_end_changed(self, ms: int) -> None:
        self.state.video_end_ms = ms
        self._update_export_button_state()
        self._update_route_range_highlight()

    def on_offset_changed(self, seconds: float) -> None:
        self.state.offset_seconds = seconds
        self.on_position_changed(self.video_widget.timeline.position_ms())
        self._update_export_button_state()
        self._update_route_range_highlight()

    def _update_route_range_highlight(self) -> None:
        """マップ上のGPXルート線を、動画のStart/End出力範囲に応じて
        2色に塗り分ける（クロップされる領域の可視化）。GPX・動画の
        いずれかが未読み込みの場合は何もしない（loadRoute()実行前は
        マップ側にルートが存在しないため）。"""
        if self.gpx_handler is None or self.state.video_creation_time is None:
            return
        in_range = self.gpx_handler.classify_points_in_range(
            self.state.video_start_ms,
            self.state.video_end_ms,
            self.state.offset_seconds,
            self.state.video_creation_time,
            self.state.video_time_scale,
        )
        self.map_widget.update_route_ranges(in_range)

    def on_force_sync_clicked(self) -> None:
        """GPXデータ先頭とタイムラインのStartマーカー位置の時刻を
        強制的に一致させるオフセットを計算し適用する（安全策ボタン）。"""
        if self.gpx_handler is None or self.state.video_creation_time is None:
            QMessageBox.warning(
                self,
                "エラー",
                "先にGPXファイルと動画の両方を読み込んでください",
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

    def on_play_clicked(self) -> None:
        self._stop_reverse()
        self.video_widget.play()

    def on_pause_clicked(self) -> None:
        self._stop_reverse()
        self.video_widget.pause()

    def on_reverse_clicked(self) -> None:
        """逆再生（18章）。QMediaPlayer.setPlaybackRate()は負値を受け付けず
        実機で0倍速に丸められてしまう（実機検証済み）ため、ネイティブな
        逆再生機能は使わず、再生位置を少しずつ巻き戻すことで疑似的に
        実現する。ただし固定間隔で連投すると、どのシークも映像フレームの
        描画が完了しないまま次のシークに上書きされ続けてしまう
        （2026-07-18実機検証で判明。シークバーのドラッグ操作でも同様の
        現象を確認）。そのため、直前のシークの描画完了
        （video_widget.seek_settled）を待ってから次のステップへ進む。"""
        self.video_widget.pause()
        self._reverse_active = True
        # 初回は比較対象の実測値がないため、REVERSE_INITIAL_STEP_MS分
        # 前の時刻を基準にする（1ステップ目だけ旧来の固定値相当になる）
        self._reverse_last_step_time = time.monotonic() - REVERSE_INITIAL_STEP_MS / 1000.0
        self._reverse_step()

    def _stop_reverse(self) -> None:
        self._reverse_active = False

    def _on_seek_settled(self) -> None:
        if self._reverse_active:
            self._reverse_step()

    def _reverse_step(self) -> None:
        """1ステップで戻す量は、キーフレームからのデコードし直しに
        かかる実際の所要時間に応じて動的に決める。GOP（キーフレーム
        間隔）に対して戻す距離が小さすぎると、ほぼ同じ区間を毎回
        デコードし直すだけで進む距離がごくわずか、という非効率な
        状態になり「2〜3秒に1コマしか進まない」不具合につながって
        いた（2026-07-18実機検証で判明）。直前のステップに実際に
        かかった時間を測り、それに比例した距離だけ戻すことで、
        遅ければ遅いなりに大きく戻るようになり、スクラブ操作と同様に
        実時間に見合った速度に収束する。"""
        now = time.monotonic()
        elapsed_ms = (now - self._reverse_last_step_time) * 1000.0
        self._reverse_last_step_time = now
        step_ms = max(round(elapsed_ms * self._current_playback_rate()), 1)
        start_ms = self.video_widget.timeline.start_ms()
        new_pos = self.video_widget.player.position() - step_ms
        if new_pos <= start_ms:
            self._stop_reverse()
            self.video_widget.seek(start_ms)
        else:
            self.video_widget.seek(new_pos)

    def on_step_back_clicked(self) -> None:
        self._step_frame(-1)

    def on_step_forward_clicked(self) -> None:
        self._step_frame(1)

    def _step_frame(self, direction: int) -> None:
        """コマ送り・コマ戻り（18章）。1フレーム分のミリ秒数は動画自身の
        fpsから算出する（video_time_scaleによらず、常にネイティブな
        動画ファイル上の1フレーム分移動する）。"""
        if self._video_fps is None or self._video_fps <= 0:
            return
        self._stop_reverse()
        self.video_widget.pause()
        frame_ms = round(1000 / self._video_fps)
        self.video_widget.seek(self.video_widget.player.position() + direction * frame_ms)

    def _update_frame_step_buttons_enabled(self) -> None:
        enabled = self._video_fps is not None and self._video_fps > 0
        self.step_back_button.setEnabled(enabled)
        self.step_forward_button.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _update_export_button_state(self) -> None:
        self.export_button.setEnabled(self.exporter.can_export(self.state))

    def _confirm_and_apply_gps_coverage_crop(self) -> bool:
        """出力直前、GPXの記録範囲がStart-End全体を完全にカバーして
        いるか確認する。カバーされていない区間がある場合（20章の
        ルート塗り分けでグレー表示される区間に相当）、そのまま出力すると
        一部フレームがGPSデータ無しになる（mapillary_tools側で外挿で
        補われるが実測ではない）ため、確認ダイアログを表示する。
        OKされた場合はStart/EndをGPXの記録範囲にクロップしてから
        Trueを返す。キャンセルされた場合はFalseを返し、呼び出し元
        （on_export_clicked）で出力処理自体を中断させる。"""
        if self.gpx_handler is None or self.state.video_creation_time is None:
            return True

        clipped_start, clipped_end = self.gpx_handler.clip_to_gps_coverage(
            self.state.video_start_ms,
            self.state.video_end_ms,
            self.state.offset_seconds,
            self.state.video_creation_time,
            self.state.video_time_scale,
        )
        if (
            clipped_start == self.state.video_start_ms
            and clipped_end == self.state.video_end_ms
        ):
            return True

        reply = QMessageBox.question(
            self,
            "GPSデータの範囲確認",
            "GPSデータのない動画フレームが存在するため、"
            "動画をクロップします。よろしいですか？",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return False

        self.video_widget.timeline.set_start(clipped_start)
        self.on_start_changed(clipped_start)
        self.video_widget.timeline.set_end(clipped_end)
        self.on_end_changed(clipped_end)
        self.video_widget.seek(self.video_widget.player.position())
        return True

    def on_export_clicked(self) -> None:
        if not self._confirm_and_apply_gps_coverage_crop():
            return

        video_output_path, _ = QFileDialog.getSaveFileName(
            self,
            "動画の保存先を選択",
            self.exporter.default_video_filename(self.state),
            "MP4 Files (*.mp4)",
        )
        if not video_output_path:
            return

        try:
            video_path, gpx_path = self.exporter.export(self.state, video_output_path)
        except Exception as exc:  # noqa: BLE001 - ユーザーへの通知が目的
            QMessageBox.warning(self, "出力エラー", str(exc))
            return

        user_name = self._get_mapillary_user_name() or None
        command = self.exporter.build_mapillary_tools_command(
            self.state, video_path, gpx_path, user_name=user_name
        )

        if self._is_mapillary_tools_available_impl():
            validation_result = self._run_local_validation(video_path)
            validation_message = self._format_validation_message(validation_result)
        else:
            validation_result = None
            validation_message = (
                "ローカル検証: mapillary_toolsが見つからないためスキップされました"
            )
        # Uploadボタンはローカル検証がOKだった場合のみ有効化する（24章）。
        # 検証が失敗している時点でアップロードもほぼ確実に同じ理由で
        # 失敗するため、無駄なアップロード試行を避ける。
        can_upload = validation_result is not None and validation_result.ok

        self._show_export_complete_dialog(
            video_path, gpx_path, command, validation_message, can_upload
        )

    def _show_export_complete_dialog(
        self,
        video_path: str,
        gpx_path: str,
        command: str,
        validation_message: str,
        can_upload: bool,
    ) -> None:
        """出力完了ダイアログ（24章）。「Mapillaryへアップロード」ボタンを
        追加したため、標準のQMessageBox.information()ではなくインスタンスを
        直接構築してカスタムボタン（ActionRole）を追加する。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("出力完了")
        box.setText(
            f"出力が完了しました。\n\n"
            f"動画: {video_path}\nGPX: {gpx_path}\n\n"
            f"{validation_message}\n\n"
            f"Mapillaryへアップロードするには、下の「Mapillaryへ"
            f"アップロード」ボタンを押すか、以下のコマンドを"
            f"手動で実行してください:\n\n{command}"
        )
        box.addButton(QMessageBox.StandardButton.Ok)
        upload_button = box.addButton(
            "Mapillaryへアップロード", QMessageBox.ButtonRole.ActionRole
        )
        upload_button.setEnabled(can_upload)

        box.exec()
        if box.clickedButton() is upload_button:
            self._start_mapillary_upload(video_path)

    def _run_local_validation(self, video_path: str) -> ValidationResult | None:
        """出力後ローカル検証（5-10節）。呼び出し前提として
        is_mapillary_tools_available_impl()がTrueであること
        （呼び出し元のon_export_clicked()側で判定済み）。バックグラウンドで
        video_processを実行し、結果を返す。"""
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

        return result_holder.get("result")

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

    def _start_mapillary_upload(self, video_path: str) -> None:
        """Mapillaryへの実アップロード（24章）。外部サービスへの公開的な
        アップロードという不可逆かつ他者に影響する操作のため、実行前に
        確認ダイアログを挟む（デフォルトボタンはCancel）。"""
        reply = QMessageBox.question(
            self,
            "Mapillaryへアップロード",
            "Mapillaryへアップロードします。アップロードした画像は"
            "Mapillary上で公開されます。よろしいですか？\n\n"
            "（キャンセルしても、mapillary_tools側で中断した時点までの"
            "アップロードは保持され、次回再開できます）",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Ok:
            return

        video_start_time = self.exporter.get_video_start_time_str(self.state)
        user_name = self._get_mapillary_user_name() or None

        worker_kwargs = {}
        if self._upload_export_impl is not None:
            worker_kwargs["upload_export_impl"] = self._upload_export_impl
        worker = MapillaryUploadWorker(
            video_path, video_start_time, user_name=user_name, **worker_kwargs
        )
        dialog = MapillaryUploadDialog(worker, self)

        result_holder: dict = {}
        worker.finished_upload.connect(
            lambda result: result_holder.update(result=result)
        )

        worker.start()
        dialog.exec()
        worker.wait()

        self._show_upload_result(result_holder.get("result"))

    def _show_upload_result(self, result: UploadResult | None) -> None:
        if result is None:
            QMessageBox.information(
                self, "アップロード", "アップロードをキャンセルしました。"
            )
            return
        if result.ok:
            message = "Mapillaryへのアップロードが完了しました。"
            if result.warnings:
                message += f"\n警告 {len(result.warnings)}件"
            QMessageBox.information(self, "アップロード完了", message)
        else:
            message = "Mapillaryへのアップロードに失敗しました。\n" + "\n".join(
                result.errors
            )
            QMessageBox.warning(self, "アップロードエラー", message)

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qtの命名規則に合わせる
        self._stop_reverse()
        self.video_widget.player.stop()
        self.video_widget.player.setSource(QUrl())
        super().closeEvent(event)
