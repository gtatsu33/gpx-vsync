import os

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt, QUrl
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtMultimedia import QMediaPlayer

from app.video_widget import CustomTimeline, VideoWidget, format_time

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample.mp4")


def _mouse_event(event_type: QEvent.Type, x: float, y: float = 38.0) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.fixture
def timeline(qtbot):
    w = CustomTimeline()
    qtbot.addWidget(w)
    w.resize(400, 80)
    w.set_duration(10000)
    return w


def test_format_time() -> None:
    assert format_time(0) == "00:00:00"
    assert format_time(61_000) == "00:01:01"
    assert format_time(3_661_000) == "01:01:01"


def test_set_duration_resets_start_and_end(timeline: CustomTimeline) -> None:
    assert timeline.start_ms() == 0
    assert timeline.end_ms() == 10000


def test_click_on_bar_emits_seek_requested_clamped(
    timeline: CustomTimeline, qtbot
) -> None:
    with qtbot.waitSignal(timeline.seek_requested, timeout=1000) as blocker:
        timeline.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, 150))
    seek_ms = blocker.args[0]
    assert 0 <= seek_ms <= 10000


def test_drag_on_bar_scrubs_continuously(timeline: CustomTimeline, qtbot) -> None:
    # ハンドル以外の場所（現在位置線を含むバー全体）を押した後ドラッグすると、
    # mouseMoveEventのたびに連続してseek_requestedが発火する（スクラブ操作）
    with qtbot.waitSignal(timeline.seek_requested, timeout=1000) as first:
        timeline.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, 100))
    first_ms = first.args[0]

    with qtbot.waitSignal(timeline.seek_requested, timeout=1000) as second:
        timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 300))
    second_ms = second.args[0]

    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 300))

    assert second_ms > first_ms

    # リリース後はドラッグが終了し、これ以上シークは発火しない
    received = []
    timeline.seek_requested.connect(lambda ms: received.append(ms))
    timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 350))
    assert received == []


HANDLE_Y = 28.0  # バー上端(top=32)より上、上部三角マークの領域内のY座標


def test_drag_end_handle_updates_end_and_emits_signal(
    timeline: CustomTimeline, qtbot
) -> None:
    end_x = timeline._ms_to_x(timeline.end_ms())  # ~388 (right edge)

    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, end_x, HANDLE_Y)
    )
    with qtbot.waitSignal(timeline.end_changed, timeout=1000) as blocker:
        timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 200))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 200))

    assert timeline.end_ms() == blocker.args[0]
    assert 4000 <= timeline.end_ms() <= 6000
    assert timeline.start_ms() == 0  # start is untouched


def test_drag_end_handle_cannot_cross_start_below_min_gap(
    timeline: CustomTimeline
) -> None:
    end_x = timeline._ms_to_x(timeline.end_ms())
    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, end_x, HANDLE_Y)
    )
    timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 0))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 0))

    # start=0 なので end は最低でも MIN_GAP_MS(=100) 以上離れる
    assert timeline.end_ms() >= 100
    assert timeline.end_ms() > timeline.start_ms()


def test_drag_start_handle_updates_start_and_emits_signal(
    timeline: CustomTimeline, qtbot
) -> None:
    # 現在地より後ろにStartを動かせない制約(2026-07-15追加)の影響を
    # 受けないよう、ドラッグ先より後ろに現在地を設定しておく
    timeline.set_position(10000)
    start_x = timeline._ms_to_x(timeline.start_ms())  # ~12 (left edge)

    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, start_x, HANDLE_Y)
    )
    with qtbot.waitSignal(timeline.start_changed, timeout=1000) as blocker:
        timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 200))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 200))

    assert timeline.start_ms() == blocker.args[0]
    assert 4000 <= timeline.start_ms() <= 6000
    assert timeline.end_ms() == 10000  # end is untouched


def test_drag_start_handle_cannot_pass_current_position(
    timeline: CustomTimeline, qtbot
) -> None:
    # 現在地(position_ms)より後ろにはStartを動かせない
    timeline.set_position(3000)
    start_x = timeline._ms_to_x(timeline.start_ms())

    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, start_x, HANDLE_Y)
    )
    # 現在地(3000)を大きく超える位置までドラッグしようとする
    timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 200))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 200))

    assert timeline.start_ms() == 3000


def test_drag_end_handle_cannot_pass_current_position(
    timeline: CustomTimeline, qtbot
) -> None:
    # 現在地(position_ms)より前にはEndを動かせない
    timeline.set_position(7000)
    end_x = timeline._ms_to_x(timeline.end_ms())

    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, end_x, HANDLE_Y)
    )
    # 現在地(7000)を大きく下回る位置までドラッグしようとする
    timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 200))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 200))

    assert timeline.end_ms() == 7000


def test_drag_start_handle_cannot_cross_end_below_min_gap(
    timeline: CustomTimeline,
) -> None:
    start_x = timeline._ms_to_x(timeline.start_ms())
    timeline.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, start_x, HANDLE_Y)
    )
    # 右端(end=10000ms)を超えるくらい大きく動かそうとする
    timeline.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, 500))
    timeline.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, 500))

    assert timeline.start_ms() <= timeline.end_ms() - 100


def test_click_near_start_x_but_on_bottom_marker_area_seeks_instead(
    timeline: CustomTimeline, qtbot
) -> None:
    # Start/EndハンドルのX座標に近くても、Y座標がバー下部（現在地の
    # 下向き三角マークの領域）であれば、Start/Endではなくposition
    # （シーク）として扱われるべき（2026-07-15修正）。
    start_x = timeline._ms_to_x(timeline.start_ms())
    bottom_y = 45.0  # rect.bottom()付近（バー下端より下）

    with qtbot.waitSignal(timeline.seek_requested, timeout=1000):
        timeline.mousePressEvent(
            _mouse_event(QEvent.Type.MouseButtonPress, start_x, bottom_y)
        )

    assert timeline.start_ms() == 0  # startは動いていない


@pytest.fixture
def video_widget(qtbot):
    w = VideoWidget()
    qtbot.addWidget(w)
    yield w
    # QMediaPlayerがソースを保持したままウィジェットが破棄されると、
    # AVFoundationバックエンドの後片付けがQtイベントループの外で
    # ブロックし、テストプロセスがハングすることを実機で確認した。
    # 明示的に停止・ソース解除してからイベントを処理させる。
    w.player.stop()
    w.player.setSource(QUrl())
    qtbot.wait(200)


def test_video_widget_load_sets_duration(video_widget: VideoWidget, qtbot) -> None:
    with qtbot.waitSignal(video_widget.duration_changed, timeout=10000):
        video_widget.load(SAMPLE_MP4)

    assert video_widget.timeline.duration_ms() == pytest.approx(10000, abs=200)


def test_load_primes_first_frame_and_stays_paused_at_zero(
    video_widget: VideoWidget, qtbot
) -> None:
    # 読み込み直後、再生ボタンを押さなくても先頭フレームが表示される
    # ようにplay()->pause()->setPosition(0)しているため、最終的には
    # 一時停止・位置0の状態になっているはず（2026-07-15追加）。
    with qtbot.waitSignal(video_widget.duration_changed, timeout=10000):
        video_widget.load(SAMPLE_MP4)

    assert (
        video_widget.player.playbackState()
        != QMediaPlayer.PlaybackState.PlayingState
    )
    assert video_widget.player.position() == 0


def test_seek_clamps_to_start_end_range(video_widget: VideoWidget, qtbot) -> None:
    with qtbot.waitSignal(video_widget.duration_changed, timeout=10000):
        video_widget.load(SAMPLE_MP4)

    video_widget.timeline.set_start(2000)
    video_widget.timeline.set_end(6000)

    video_widget.seek(500)  # start(2000)より前 -> クランプされる
    assert video_widget.player.position() == 2000

    video_widget.seek(9000)  # end(6000)より後 -> クランプされる
    assert video_widget.player.position() == 6000


def test_play_from_outside_range_jumps_to_start(
    video_widget: VideoWidget, qtbot
) -> None:
    with qtbot.waitSignal(video_widget.duration_changed, timeout=10000):
        video_widget.load(SAMPLE_MP4)

    video_widget.timeline.set_start(3000)
    video_widget.timeline.set_end(9000)
    video_widget.player.setPosition(0)  # start(3000)より前

    video_widget.play()

    qtbot.waitUntil(lambda: video_widget.player.position() >= 3000, timeout=3000)
    video_widget.pause()


def test_position_reaching_end_pauses_and_clamps(
    video_widget: VideoWidget, qtbot
) -> None:
    with qtbot.waitSignal(video_widget.duration_changed, timeout=10000):
        video_widget.load(SAMPLE_MP4)

    video_widget.timeline.set_start(0)
    video_widget.timeline.set_end(500)  # 短い区間にしてすぐEndに到達させる
    video_widget.player.setPosition(0)

    video_widget.play()

    qtbot.waitUntil(
        lambda: video_widget.player.playbackState()
        == QMediaPlayer.PlaybackState.PausedState,
        timeout=5000,
    )

    assert video_widget.player.position() == 500
    assert video_widget.timeline.position_ms() == 500
