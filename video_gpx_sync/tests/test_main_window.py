import datetime
import os
import shutil

import pytest
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QLabel, QMessageBox

from app.camm_encoder import embed_gps_track
from app.main_window import MainWindow
from app.mapillary_validator import UploadResult, ValidationResult

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample.mp4")
SAMPLE_420P_MP4 = os.path.join(FIXTURES_DIR, "sample_420p.mp4")
SAMPLE_GPX = os.path.join(FIXTURES_DIR, "sample.gpx")

UTC = datetime.timezone.utc
MP4BOX_AVAILABLE = shutil.which("MP4Box") is not None


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path):
    """MainWindowのMapillaryユーザー名設定はQSettingsで永続化される
    （24章）。テストが実際のユーザーの~/Library/Preferences/を読み書き
    してしまわないよう、テストごとに一時ディレクトリへリダイレクトする。"""
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path)
    )
    yield


def _fake_match_chunk(chunk):
    """テストではマップマッチングAPIへの実通信を避けるため、座標を
    変更せず"matched"として返すダミー実装を注入する。"""
    return {
        "matched_points": [
            {"lat": lat, "lon": lon, "type": "matched"} for lat, lon in chunk
        ]
    }


@pytest.fixture
def window(qtbot):
    w = MainWindow(
        match_chunk_impl=_fake_match_chunk,
        is_mapillary_tools_available_impl=lambda: False,
    )
    # load_video()は毎回_prompt_timelapse_settings()（モーダルダイアログ）を
    # 呼ぶため、テストでは既定値（タイムラプス無効）を返すダミーに差し替えて
    # ブロッキングを避ける。個別テストで上書きすれば挙動を検証できる。
    w._prompt_timelapse_settings = lambda has_audio: (False, 0.5)
    qtbot.addWidget(w)
    yield w
    # QMediaPlayerの後片付け（Step5で判明したハング回避と同様の対処）
    w.video_widget.player.stop()
    w.video_widget.player.setSource(QUrl())
    qtbot.wait(200)


@pytest.fixture
def camm_embedded_video(tmp_path) -> str:
    """CAMM Type6のGPSトラックを埋め込んだ動画ファイル（22章）。
    sample_420p.mp4はMP4Boxでのnhml埋め込みに対応したフィクスチャ
    （test_camm_encoder.pyと共通）。"""
    output_path = str(tmp_path / "embedded.mp4")
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    points = [
        (0, 35.5000, 136.0000, 20.0, t0.timestamp()),
        (
            5000,
            35.5010,
            136.0010,
            21.0,
            (t0 + datetime.timedelta(seconds=5)).timestamp(),
        ),
    ]
    embed_gps_track(SAMPLE_420P_MP4, output_path, points)
    return output_path


def test_initial_state_disables_export_only(window: MainWindow) -> None:
    # 22章: 読み込み順序ルール撤廃により、動画読み込みはGPXの
    # 読み込み状況に関わらず常に可能。出力のみ両方揃うまで無効。
    assert window.open_video_action.isEnabled() is True
    assert window.export_button.isEnabled() is False


def test_initial_state_emphasizes_both_open_buttons(window: MainWindow) -> None:
    # 22章: GPX・動画のいずれも未読み込みの間は、両方とも独立に
    # 強調表示する（互いの読み込み状況に依存しない）。
    assert window.open_gpx_button.objectName() == "primaryButton"
    assert window.open_video_button.objectName() == "primaryButton"
    assert window.open_video_button.isEnabled() is True


def test_load_gpx_shifts_emphasis_to_open_video_button(window: MainWindow) -> None:
    window.load_gpx(SAMPLE_GPX)

    assert window.open_gpx_button.objectName() == ""
    assert window.open_video_button.objectName() == "primaryButton"
    assert window.open_video_button.isEnabled() is True


def test_load_video_clears_open_video_button_emphasis(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.open_video_button.objectName() == ""


def test_load_gpx_shows_success_map_matching_status(window: MainWindow) -> None:
    window.load_gpx(SAMPLE_GPX)

    # ウィンドウ自体をshow()していないテストではisVisible()は常にFalseに
    # なるため、ウィジェット自身の明示的な非表示フラグを見るisHidden()を使う。
    assert window.map_matching_status_label.isHidden() is False
    assert window.map_matching_status_label.property("state") == "ok"
    assert "完了" in window.map_matching_status_label.text()


def test_load_gpx_shows_warn_status_on_partial_chunk_failure(
    window: MainWindow, monkeypatch
) -> None:
    # GPXフィクスチャは1チャンクに収まる点数のため、CHUNK_SIZEを1に
    # 下げて複数チャンクに分割させ、2チャンク目のみ失敗させる。
    monkeypatch.setattr("app.map_matcher.CHUNK_SIZE", 1)
    call_count = {"n": 0}

    def flaky_match_chunk(chunk):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("boom")
        return {
            "matched_points": [
                {"lat": lat, "lon": lon, "type": "matched"} for lat, lon in chunk
            ]
        }

    window._match_chunk_impl = flaky_match_chunk
    window.load_gpx(SAMPLE_GPX)

    assert window.map_matching_status_label.property("state") == "warn"
    assert "一部失敗" in window.map_matching_status_label.text()


def test_load_gpx_shows_error_status_when_first_chunk_times_out(
    window: MainWindow,
) -> None:
    def failing_match_chunk(chunk):
        raise RuntimeError("timeout")

    window._match_chunk_impl = failing_match_chunk
    window.load_gpx(SAMPLE_GPX)

    assert window.map_matching_status_label.property("state") == "error"
    assert "中断" in window.map_matching_status_label.text()


def test_load_video_without_gpx_succeeds(window: MainWindow, qtbot) -> None:
    # 22章: GPX先読み込みルールを撤廃したため、GPX未読み込みの状態でも
    # 動画は問題なく読み込める（CAMM埋め込みが無いsample.mp4のため
    # GPXデータは引き続きNoneのまま）。
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.state.video_path == SAMPLE_MP4
    assert window.state.gpx_data is None


@pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")
def test_load_video_with_embedded_gps_auto_populates_gpx_data(
    window: MainWindow, qtbot, camm_embedded_video: str
) -> None:
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(camm_embedded_video)

    assert window.state.gpx_data is not None
    assert window.gpx_handler is not None
    assert len(window.gpx_handler.get_all_points()) == 2
    assert window.state.gpx_path == camm_embedded_video
    assert window.map_matching_status_label.property("state") == "ok"
    assert "動画に埋め込まれたGPSデータを使用" in window.map_matching_status_label.text()


@pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")
def test_camm_video_creation_time_uses_embedded_epoch_not_corrupted_metadata(
    window: MainWindow, qtbot, camm_embedded_video: str
) -> None:
    # MP4BoxでCAMMトラックを追加すると、動画コンテナのcreation_time
    # メタデータが処理実行時刻（＝実機ではテスト実行時の現在時刻）で
    # 上書きされてしまうことが実機で判明した（4-8節「制約3」）。
    # ffprobe由来の値を信用すると、地図上のルートが全区間グレー表示
    # （範囲外）になり、マーカーも一切動かなくなる不具合が発生する。
    # CAMM自身のepoch_timeを真の開始時刻として採用することで回避
    # できていることを確認する（回帰テスト。23章）。
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(camm_embedded_video)

    assert window.state.video_creation_time == datetime.datetime(
        2026, 7, 12, 1, 0, 0, tzinfo=UTC
    )

    in_range = window.gpx_handler.classify_points_in_range(
        window.state.video_start_ms,
        window.state.video_end_ms,
        window.state.offset_seconds,
        window.state.video_creation_time,
        window.state.video_time_scale,
    )
    assert all(in_range)

    pos = window.gpx_handler.interpolate_position(
        2500,
        window.state.offset_seconds,
        window.state.video_creation_time,
        window.state.video_time_scale,
    )
    assert pos is not None


@pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")
def test_loading_video_without_camm_keeps_existing_gpx(
    window: MainWindow, qtbot
) -> None:
    # 最後勝ちルール（22章）: CAMM埋め込みが無い動画を読み込んでも
    # 既存のGPXデータは維持される（新しいGPS情報が無いため上書きしない）
    window.load_gpx(SAMPLE_GPX)
    original_gpx_data = window.state.gpx_data

    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)  # CAMM埋め込みなし

    assert window.state.gpx_data is original_gpx_data


@pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")
def test_camm_video_loaded_after_gpx_overrides_it(
    window: MainWindow, qtbot, camm_embedded_video: str
) -> None:
    # 最後勝ちルール（22章）: GPX読み込み後にCAMM埋め込み動画を読み込むと
    # そちらのGPSデータが優先される
    window.load_gpx(SAMPLE_GPX)
    gpx_point_count = len(window.gpx_handler.get_all_points())

    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(camm_embedded_video)

    assert len(window.gpx_handler.get_all_points()) == 2
    assert len(window.gpx_handler.get_all_points()) != gpx_point_count
    assert window.state.gpx_path == camm_embedded_video


@pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")
def test_gpx_loaded_after_camm_video_overrides_it(
    window: MainWindow, qtbot, camm_embedded_video: str
) -> None:
    # 最後勝ちルール（22章）: CAMM埋め込み動画読み込み後にGPXファイルを
    # 読み込むと、そちらが優先される（マップマッチングも通常通り適用）
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(camm_embedded_video)
    assert len(window.gpx_handler.get_all_points()) == 2

    window.load_gpx(SAMPLE_GPX)

    assert window.state.gpx_path == SAMPLE_GPX
    assert window.map_matching_status_label.property("state") == "ok"
    assert "完了" in window.map_matching_status_label.text()


def test_load_gpx_enables_video_loading(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)

    assert window.state.gpx_data is not None
    assert window.state.gpx_path == SAMPLE_GPX
    assert window.open_video_action.isEnabled() is True


def test_load_gpx_applies_map_matching_result(window: MainWindow) -> None:
    calls = []

    def offsetting_match_chunk(chunk):
        calls.append(chunk)
        return {
            "matched_points": [
                {"lat": lat + 0.0005, "lon": lon, "type": "matched"} for lat, lon in chunk
            ]
        }

    window._match_chunk_impl = offsetting_match_chunk
    window.load_gpx(SAMPLE_GPX)

    assert len(calls) >= 1
    assert window.gpx_handler is not None
    points = window.gpx_handler.get_all_points()
    assert points[0].latitude == pytest.approx(35.0 + 0.0005)


def test_load_video_after_gpx_sets_state_and_enables_export(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.state.video_path == SAMPLE_MP4
    assert window.state.video_creation_time == datetime.datetime(
        2026, 7, 12, 1, 0, 0, tzinfo=UTC
    )
    assert window.state.video_duration_ms == pytest.approx(10000, abs=200)
    # GPXの記録範囲(0-10s)と動画全体(0-10s)が重複するのでexportは有効になる
    assert window.export_button.isEnabled() is True


def test_load_video_shows_fps_in_video_info_label(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    # sample.mp4はffprobeでr_frame_rate=30/1と確認済み
    assert window.video_info_label.isHidden() is False
    assert window.video_info_label.text() == "30.00fps"
    assert "タイムラプス" not in window.video_info_label.text()


def test_load_video_with_timelapse_shows_interval_in_video_info_label(
    window: MainWindow, qtbot
) -> None:
    window._prompt_timelapse_settings = lambda has_audio: (True, 0.5)
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.video_info_label.text() == "30.00fps（0.5sタイムラプス）"


def test_toggling_persistent_timelapse_widget_updates_video_info_label(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)
    assert window.video_info_label.text() == "30.00fps"

    window.timelapse_widget.checkbox.setChecked(True)
    window.timelapse_widget.interval_spinbox.setValue(1.0)

    assert window.video_info_label.text() == "30.00fps（1sタイムラプス）"


def test_offset_change_updates_state_and_marker(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    calls = []
    # 実際のQML地図のロード完了タイミングに依存しないよう、
    # MapWidgetのPythonメソッド自体をモック化して呼び出しのみ検証する。
    monkeypatch.setattr(
        window.map_widget, "update_marker", lambda lat, lon: calls.append("update")
    )
    monkeypatch.setattr(
        window.map_widget, "hide_marker", lambda: calls.append("hide")
    )

    window.offset_widget.step_buttons[10.0].click()

    assert window.state.offset_seconds == 10.0
    assert calls == ["update"]


def test_end_change_updates_route_range_highlight(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    calls = []
    monkeypatch.setattr(
        window.map_widget,
        "update_route_ranges",
        lambda in_range: calls.append(in_range),
    )

    # sample.gpxの記録点: 01:00:00, 01:00:05, 01:00:10
    # video_creation_time=01:00:00なので、end=6000ms(01:00:06)にすると
    # 3点目(01:00:10)だけが範囲外になる
    # on_end_changed()はCustomTimeline.end_changedシグナル経由で呼ばれる
    # メソッドのため、ここでは直接呼んでハンドラの挙動を検証する。
    window.on_end_changed(6000)

    assert calls[-1] == [True, True, False]


def test_pause_button_pauses_without_seeking(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.video_widget.timeline.set_start(2000)
    window.video_widget.player.setPosition(5000)

    window.on_pause_clicked()

    # 停止(旧仕様)ではなく一時停止のため、位置は動かない
    assert window.video_widget.player.position() == 5000
    assert (
        window.video_widget.player.playbackState()
        != window.video_widget.player.PlaybackState.PlayingState
    )


def test_step_forward_moves_by_exactly_one_frame(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    # sample.mp4はffprobeでfps=30と確認済み -> 1フレーム = 約33ms
    assert window._video_fps == pytest.approx(30.0, abs=0.5)
    window.video_widget.player.setPosition(5000)

    window.on_step_forward_clicked()

    assert window.video_widget.player.position() == 5000 + round(1000 / window._video_fps)


def test_step_back_moves_by_exactly_one_frame(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.video_widget.player.setPosition(5000)

    window.on_step_back_clicked()

    assert window.video_widget.player.position() == 5000 - round(1000 / window._video_fps)


def test_step_forward_clamps_to_end_marker(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.video_widget.timeline.set_end(6000)
    window.video_widget.player.setPosition(5990)

    window.on_step_forward_clicked()

    assert window.video_widget.player.position() == 6000


def test_frame_step_buttons_disabled_when_fps_unknown(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    from app.video_handler import FFmpegError

    monkeypatch.setattr(
        window.video_handler,
        "get_fps",
        lambda path: (_ for _ in ()).throw(FFmpegError("fps unknown")),
    )

    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window._video_fps is None
    assert window.step_back_button.isEnabled() is False
    assert window.step_forward_button.isEnabled() is False


def test_reverse_playback_decrements_position_and_stops_at_start(
    window: MainWindow, qtbot
) -> None:
    """逆再生は各ステップの映像フレーム描画完了（video_widget.seek_settled）
    を待ってから次のステップに進む非同期処理のため、実イベントループを
    回しながら収束を待つ（qtbot.waitUntil）。同期的に複数回呼び出す形の
    検証はできない（そもそも旧実装のその方式が、実機で映像が描画され
    ない不具合を見逃す一因だった）。"""
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.video_widget.timeline.set_start(1000)
    window.video_widget.player.setPosition(1150)

    window.on_reverse_clicked()
    assert window._reverse_active is True

    qtbot.waitUntil(lambda: window._reverse_active is False, timeout=5000)

    assert window.video_widget.player.position() == 1000


def test_play_and_pause_stop_reverse(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window._reverse_active = True
    window.on_pause_clicked()
    assert window._reverse_active is False

    window._reverse_active = True
    window.on_play_clicked()
    assert window._reverse_active is False


def test_export_button_disabled_when_ranges_do_not_overlap(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.export_button.isEnabled() is True

    # GPXの記録範囲外までオフセットを大きくずらす
    window.on_offset_changed(1000.0)
    assert window.export_button.isEnabled() is False


def test_export_confirm_not_shown_when_gps_fully_covers_range(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    called = {"n": 0}
    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **k: called.update(n=called["n"] + 1),
    )

    assert window._confirm_and_apply_gps_coverage_crop() is True
    assert called["n"] == 0
    assert window.state.video_start_ms == 0
    assert window.state.video_end_ms == 10000


def test_export_confirm_crops_start_when_accepted(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    # sample.gpxの記録開始(01:00:00)より前にraw_startがずれるようにする
    window.on_offset_changed(-3.0)

    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Ok,
    )

    assert window._confirm_and_apply_gps_coverage_crop() is True
    assert window.state.video_start_ms == 3000
    assert window.state.video_end_ms == 10000
    assert window.video_widget.timeline.start_ms() == 3000


def test_export_confirm_cancelled_leaves_state_unchanged(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.on_offset_changed(-3.0)

    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )

    assert window._confirm_and_apply_gps_coverage_crop() is False
    assert window.state.video_start_ms == 0
    assert window.state.video_end_ms == 10000


def test_export_creates_output_file(window: MainWindow, qtbot, tmp_path) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.export_button.isEnabled() is True

    video_output_path = str(tmp_path / window.exporter.default_video_filename(window.state))
    video_path = window.exporter.export(window.state, video_output_path)

    assert os.path.exists(video_path)


def test_reloading_own_exported_synced_video_resets_stale_offset(
    window: MainWindow, qtbot, tmp_path
) -> None:
    """2026-07-18実機で発生した不具合の回帰テスト。GPX・動画を別々に
    読み込みオフセット調整してExportした直後、同一セッション内で
    そのExport済み（埋め込みGPSに既にオフセット適用済みの）動画を
    再読み込みすると、直前のオフセットが生き残って二重に適用され、
    同期がズレていた。"""
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.on_offset_changed(2.0)
    assert window.state.offset_seconds == 2.0

    video_output_path = str(tmp_path / window.exporter.default_video_filename(window.state))
    video_path = window.exporter.export(window.state, video_output_path)

    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(video_path)

    assert window.state.offset_seconds == 0.0
    assert window.offset_widget.offset_seconds() == 0.0

    # sample.gpxの記録点(01:00:00, 01:00:05, 01:00:10)のうち、
    # offset=2.0でExportした場合、動画位置0msには
    # 01:00:00+2s=01:00:02に対応する補間位置
    # (35.0000, 135.0000)-(35.0010, 135.0010)間の2/5点、つまり
    # (35.0004, 135.0004)が正しく焼き込まれているはず
    pos = window.gpx_handler.interpolate_position(
        0,
        window.state.offset_seconds,
        window.state.video_creation_time,
        window.state.video_time_scale,
    )
    assert pos == pytest.approx((35.0004, 135.0004), abs=1e-6)


def test_on_export_clicked_shows_save_dialog_with_default_filename(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    save_dialog_calls = []

    def fake_get_save_file_name(parent, caption, default_name, filter_str):
        save_dialog_calls.append((caption, default_name, filter_str))
        return "", ""  # ユーザーがキャンセルした状態を模す

    monkeypatch.setattr(
        "app.main_window.QFileDialog.getSaveFileName", fake_get_save_file_name
    )

    window.on_export_clicked()

    assert len(save_dialog_calls) == 1
    _caption, default_name, filter_str = save_dialog_calls[0]
    assert default_name == window.exporter.default_video_filename(window.state)
    assert "*.mp4" in filter_str


def test_export_button_label_is_export_and_test(window: MainWindow) -> None:
    # QPushButtonのtext()は生の文字列("&&")を返す（表示上は"&"1文字になる）。
    # "&"を単体で含めるとQtがニーモニック記号として解釈してしまうため、
    # ボタン生成時は"&&"でエスケープしている（app/main_window.py参照）。
    assert window.export_button.text() == "\U0001f4e4 Export && Test"


def test_validate_export_skipped_when_mapillary_tools_unavailable(
    window: MainWindow,
) -> None:
    # windowフィクスチャは is_mapillary_tools_available_impl=lambda: False
    assert window._is_mapillary_tools_available_impl() is False


def test_validate_export_runs_worker_when_available(qtbot) -> None:
    def fake_validate_export(video_path, video_start_time, should_cancel=None):
        return ValidationResult(ok=True, n_images=3, errors=[], warnings=[])

    w = MainWindow(
        match_chunk_impl=_fake_match_chunk,
        is_mapillary_tools_available_impl=lambda: True,
        validate_export_impl=fake_validate_export,
    )
    qtbot.addWidget(w)
    w.state.video_creation_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    w.state.video_start_ms = 0
    try:
        result = w._run_local_validation("dummy.mp4")
        message = w._format_validation_message(result)
        assert "OK" in message
        assert "3件" in message
    finally:
        w.video_widget.player.stop()
        w.video_widget.player.setSource(QUrl())
        qtbot.wait(200)


def test_format_validation_message_variants(window: MainWindow) -> None:
    assert "キャンセル" in window._format_validation_message(None)

    ok_result = ValidationResult(ok=True, n_images=5, errors=[], warnings=[])
    assert "OK" in window._format_validation_message(ok_result)
    assert "5件" in window._format_validation_message(ok_result)

    fail_result = ValidationResult(
        ok=False, n_images=0, errors=["GPSデータが見つかりません"], warnings=[]
    )
    fail_message = window._format_validation_message(fail_result)
    assert "失敗" in fail_message
    assert "GPSデータが見つかりません" in fail_message

    warn_result = ValidationResult(ok=True, n_images=2, errors=[], warnings=["w1", "w2"])
    warn_message = window._format_validation_message(warn_result)
    assert "警告 2件" in warn_message


def test_mapillary_user_name_defaults_to_empty(window: MainWindow) -> None:
    assert window._get_mapillary_user_name() == ""


def test_mapillary_user_name_round_trips_via_qsettings(window: MainWindow) -> None:
    window._set_mapillary_user_name("alice")
    assert window._get_mapillary_user_name() == "alice"


def test_mapillary_user_name_persists_across_new_window_instance(
    window: MainWindow, qtbot
) -> None:
    """QSettingsによる永続化（24章）。同じ設定ストレージ（isolated_qsettings
    フィクスチャでリダイレクトされた一時ディレクトリ）を参照する新しい
    MainWindowインスタンスでも値が引き継がれることを確認する。"""
    window._set_mapillary_user_name("bob")

    other = MainWindow(match_chunk_impl=_fake_match_chunk)
    qtbot.addWidget(other)
    try:
        assert other._get_mapillary_user_name() == "bob"
    finally:
        other.video_widget.player.stop()
        other.video_widget.player.setSource(QUrl())
        qtbot.wait(200)


def test_edit_mapillary_username_saves_on_ok(
    window: MainWindow, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.main_window.QInputDialog.getText",
        lambda *a, **k: ("carol", True),
    )
    window.on_edit_mapillary_username_clicked()
    assert window._get_mapillary_user_name() == "carol"


def test_edit_mapillary_username_does_nothing_on_cancel(
    window: MainWindow, monkeypatch
) -> None:
    window._set_mapillary_user_name("existing")
    monkeypatch.setattr(
        "app.main_window.QInputDialog.getText",
        lambda *a, **k: ("ignored", False),
    )
    window.on_edit_mapillary_username_clicked()
    assert window._get_mapillary_user_name() == "existing"


def test_export_complete_dialog_upload_button_enabled_state(
    window: MainWindow, monkeypatch
) -> None:
    captured: dict = {}

    def fake_exec(self):
        button = next(
            b for b in self.buttons() if b.text() == "Mapillaryへアップロード"
        )
        captured["enabled"] = button.isEnabled()
        return None

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    window._show_export_complete_dialog("v.mp4", "cmd", "msg", can_upload=False)
    assert captured["enabled"] is False

    window._show_export_complete_dialog("v.mp4", "cmd", "msg", can_upload=True)
    assert captured["enabled"] is True


def test_export_complete_dialog_clicking_upload_starts_upload_flow(
    window: MainWindow, monkeypatch
) -> None:
    def fake_exec(self):
        button = next(
            b for b in self.buttons() if b.text() == "Mapillaryへアップロード"
        )
        button.click()
        return None

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    called = []
    monkeypatch.setattr(
        window, "_start_mapillary_upload", lambda video_path: called.append(video_path)
    )

    window._show_export_complete_dialog("v.mp4", "cmd", "msg", can_upload=True)
    assert called == ["v.mp4"]


def test_start_mapillary_upload_does_nothing_when_confirmation_cancelled(
    window: MainWindow, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    started = []
    monkeypatch.setattr(
        "app.main_window.MapillaryUploadWorker.start", lambda self: started.append(True)
    )

    window.state.video_creation_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    window.state.video_start_ms = 0
    window._start_mapillary_upload("v.mp4")

    assert started == []


def test_start_mapillary_upload_runs_worker_and_shows_result_on_confirm(
    window: MainWindow, monkeypatch, qtbot
) -> None:
    monkeypatch.setattr(
        "app.main_window.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Ok,
    )

    received_messages = []
    monkeypatch.setattr(
        "app.main_window.QMessageBox.information",
        lambda *a, **k: received_messages.append(a[2] if len(a) > 2 else k.get("text")),
    )

    window.state.video_creation_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    window.state.video_start_ms = 0
    window._set_mapillary_user_name("dave")

    received_kwargs = {}

    def fake_upload_export(video_path, video_start_time, user_name=None, should_cancel=None):
        received_kwargs["video_path"] = video_path
        received_kwargs["user_name"] = user_name
        return UploadResult(ok=True, errors=[], warnings=[])

    window._upload_export_impl = fake_upload_export

    window._start_mapillary_upload("v.mp4")

    assert received_kwargs["video_path"] == "v.mp4"
    assert received_kwargs["user_name"] == "dave"
    assert any("完了" in m for m in received_messages)


def test_force_sync_computes_offset_from_gpx_start_to_video_start_marker(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    # 動画のcreation_timeがGPXと大きくずれているケースをシミュレート
    window.state.video_creation_time = datetime.datetime(
        2026, 7, 10, 0, 0, 0, tzinfo=UTC
    )
    window.state.video_start_ms = 2000

    window.on_force_sync_clicked()

    video_start_true_time = window.state.video_creation_time + datetime.timedelta(
        milliseconds=2000
    )
    gpx_start_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    expected_offset = (gpx_start_time - video_start_true_time).total_seconds()

    assert window.state.offset_seconds == pytest.approx(expected_offset)
    assert window.offset_widget.offset_seconds() == pytest.approx(expected_offset)


def test_force_sync_without_video_shows_warning(
    window: MainWindow, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)

    warned = {}
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        lambda *a, **k: warned.setdefault("called", True),
    )
    window.on_force_sync_clicked()
    assert warned.get("called") is True
    assert window.state.offset_seconds == 0.0


def test_load_video_caches_fps_and_defaults_time_scale_to_one(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window._video_fps == pytest.approx(30.0)
    assert window.state.video_time_scale == pytest.approx(1.0)
    assert window.video_widget.player.playbackRate() == pytest.approx(1.0)
    assert window.video_widget.audio_output.isMuted() is False


def test_enabling_timelapse_scales_state_and_playback_rate(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.export_button.isEnabled() is True

    window.timelapse_widget.checkbox.setChecked(True)
    window.timelapse_widget.interval_spinbox.setValue(0.5)

    # fps=30, interval=0.5s -> time_scale=15.0
    assert window.state.video_time_scale == pytest.approx(15.0)
    assert window.video_widget.player.playbackRate() == pytest.approx(1.0 / 15.0)
    assert window.video_widget.audio_output.isMuted() is True
    # フェーズ2: CAMM Type6のtime_gps_epoch対応により、タイムラプス設定
    # 有効時でも出力自体は引き続き可能（GPXとの時刻重複があれば）
    assert window.export_button.isEnabled() is True

    window.timelapse_widget.checkbox.setChecked(False)

    assert window.state.video_time_scale == pytest.approx(1.0)
    assert window.video_widget.player.playbackRate() == pytest.approx(1.0)
    assert window.video_widget.audio_output.isMuted() is False
    assert window.export_button.isEnabled() is True


def test_force_sync_respects_video_time_scale(window: MainWindow, qtbot) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    window.state.video_creation_time = datetime.datetime(
        2026, 7, 10, 0, 0, 0, tzinfo=UTC
    )
    window.state.video_start_ms = 2000
    window.state.video_time_scale = 15.0

    window.on_force_sync_clicked()

    video_start_true_time = window.state.video_creation_time + datetime.timedelta(
        milliseconds=2000 * 15.0
    )
    gpx_start_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    expected_offset = (gpx_start_time - video_start_true_time).total_seconds()

    assert window.state.offset_seconds == pytest.approx(expected_offset)


def test_load_video_passes_has_audio_false_to_timelapse_prompt(
    window: MainWindow, qtbot, tmp_path
) -> None:
    import subprocess

    no_audio_path = tmp_path / "no_audio.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            SAMPLE_MP4,
            "-an",
            "-c:v",
            "copy",
            "-map_metadata",
            "0",
            str(no_audio_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    window.load_gpx(SAMPLE_GPX)

    captured = {}

    def fake_prompt(has_audio: bool) -> tuple[bool, float]:
        captured["has_audio"] = has_audio
        return False, 0.5

    window._prompt_timelapse_settings = fake_prompt
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(str(no_audio_path))

    assert captured["has_audio"] is False


def test_load_video_passes_has_audio_true_when_audio_present(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)

    captured = {}

    def fake_prompt(has_audio: bool) -> tuple[bool, float]:
        captured["has_audio"] = has_audio
        return False, 0.5

    window._prompt_timelapse_settings = fake_prompt
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert captured["has_audio"] is True


def test_load_video_applies_timelapse_settings_returned_by_prompt(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)
    window._prompt_timelapse_settings = lambda has_audio: (True, 2.0)

    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.timelapse_widget.checkbox.isChecked() is True
    assert window.timelapse_widget.interval_seconds() == pytest.approx(2.0)
    # fps=30 (SAMPLE_MP4), interval=2.0s -> time_scale=60.0
    assert window.state.video_time_scale == pytest.approx(60.0)


def test_prompt_timelapse_settings_returns_checkbox_and_interval_state(
    window: MainWindow, monkeypatch
) -> None:
    # windowフィクスチャがインスタンス属性として差し替えているダミー実装を
    # 削除し、MainWindow本来のメソッド（実際のダイアログ）を呼び出す
    del window._prompt_timelapse_settings

    def fake_exec(self: QDialog) -> QDialog.DialogCode:
        self.findChild(QCheckBox).setChecked(True)
        self.findChild(QDoubleSpinBox).setValue(3.0)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    enabled, interval = window._prompt_timelapse_settings(has_audio=True)

    assert enabled is True
    assert interval == pytest.approx(3.0)


def test_prompt_timelapse_settings_default_when_untouched(
    window: MainWindow, monkeypatch
) -> None:
    del window._prompt_timelapse_settings
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    enabled, interval = window._prompt_timelapse_settings(has_audio=False)

    assert enabled is False
    assert interval == pytest.approx(0.5)


def test_prompt_timelapse_settings_includes_hint_when_no_audio(
    window: MainWindow, monkeypatch
) -> None:
    del window._prompt_timelapse_settings
    captured = {}

    def fake_exec(self: QDialog) -> QDialog.DialogCode:
        captured["dialog"] = self
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    window._prompt_timelapse_settings(has_audio=False)

    labels = captured["dialog"].findChildren(QLabel)
    assert any("音声トラック" in label.text() for label in labels)


def test_prompt_timelapse_settings_no_hint_when_audio_present(
    window: MainWindow, monkeypatch
) -> None:
    del window._prompt_timelapse_settings
    captured = {}

    def fake_exec(self: QDialog) -> QDialog.DialogCode:
        captured["dialog"] = self
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    window._prompt_timelapse_settings(has_audio=True)

    labels = captured["dialog"].findChildren(QLabel)
    assert not any("音声トラック" in label.text() for label in labels)


def test_prompt_creation_time_prefills_from_gpx_start_local_time(
    window: MainWindow, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    result = window._prompt_creation_time()

    assert result is not None
    assert result.astimezone(UTC) == datetime.datetime(
        2026, 7, 12, 1, 0, 0, tzinfo=UTC
    )
