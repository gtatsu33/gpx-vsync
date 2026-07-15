import datetime
import os

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QLabel

from app.main_window import MainWindow
from app.mapillary_validator import ValidationResult

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample.mp4")
SAMPLE_GPX = os.path.join(FIXTURES_DIR, "sample.gpx")

UTC = datetime.timezone.utc


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


def test_initial_state_disables_video_loading_and_export(window: MainWindow) -> None:
    assert window.open_video_action.isEnabled() is False
    assert window.export_button.isEnabled() is False


def test_load_video_without_gpx_shows_warning_and_is_ignored(
    window: MainWindow, monkeypatch
) -> None:
    warned = {}
    monkeypatch.setattr(
        "app.main_window.QMessageBox.warning",
        lambda *a, **k: warned.setdefault("called", True),
    )
    window.load_video(SAMPLE_MP4)
    assert warned.get("called") is True
    assert window.state.video_path is None


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


def test_offset_change_updates_state_and_marker(
    window: MainWindow, qtbot, monkeypatch
) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    calls = []
    # 実ページ(Leaflet)のロード完了タイミングに依存しないよう、
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


def test_export_creates_output_files(window: MainWindow, qtbot, tmp_path) -> None:
    window.load_gpx(SAMPLE_GPX)
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.load_video(SAMPLE_MP4)

    assert window.export_button.isEnabled() is True

    video_path, gpx_path = window.exporter.export(window.state, str(tmp_path))

    assert os.path.exists(video_path)
    assert os.path.exists(gpx_path)


def test_export_button_label_is_export_and_test(window: MainWindow) -> None:
    assert window.export_button.text() == "\U0001f4e4 Export & Test"


def test_validate_export_skipped_when_mapillary_tools_unavailable(
    window: MainWindow,
) -> None:
    # windowフィクスチャは is_mapillary_tools_available_impl=lambda: False
    message = window._validate_export_and_format_message("dummy.mp4")
    assert "スキップ" in message


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
        message = w._validate_export_and_format_message("dummy.mp4")
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


def test_open_verification_window_creates_independent_window(
    window: MainWindow, qtbot
) -> None:
    window.load_gpx(SAMPLE_GPX)

    window.open_verification_window()

    assert len(window._verification_windows) == 1
    verification_window = window._verification_windows[0]
    qtbot.addWidget(verification_window)
    assert verification_window.isVisible()
    # MainWindowのステートには一切影響しない
    assert window.state.gpx_data is not None

    verification_window.video_widget.player.stop()
    verification_window.video_widget.player.setSource(QUrl())
    qtbot.wait(200)


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
