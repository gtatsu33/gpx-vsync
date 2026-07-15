import os
import shutil

import pytest
from PyQt6.QtCore import QUrl

from app.camm_encoder import embed_gps_track
from app.verification_window import VerificationWindow

MP4BOX_AVAILABLE = shutil.which("MP4Box") is not None

pytestmark = pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample_420p.mp4")

EMBED_POINTS = [
    (0, 35.0000, 135.0000, 10.0, 1783818000.0),
    (2000, 35.0010, 135.0010, 11.0, 1783818002.0),
    (4000, 35.0020, 135.0020, 12.0, 1783818004.0),
]
# extract_gps_track()はepoch_timeを読み捨てるため、比較対象は4要素のみ
SAMPLE_POINTS = [(ms, lat, lon, elev) for ms, lat, lon, elev, _epoch in EMBED_POINTS]


@pytest.fixture
def embedded_video(tmp_path) -> str:
    output_path = str(tmp_path / "embedded.mp4")
    embed_gps_track(SAMPLE_MP4, output_path, EMBED_POINTS)
    return output_path


@pytest.fixture
def window(qtbot):
    w = VerificationWindow()
    qtbot.addWidget(w)
    yield w
    w.video_widget.player.stop()
    w.video_widget.player.setSource(QUrl())
    qtbot.wait(200)


def test_open_video_with_camm_loads_route_and_video(
    window: VerificationWindow, embedded_video: str, qtbot
) -> None:
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.open_video(embedded_video)

    assert window.camm_points == SAMPLE_POINTS


def test_open_video_without_camm_shows_warning(
    window: VerificationWindow, monkeypatch
) -> None:
    warned = {}
    monkeypatch.setattr(
        "app.verification_window.QMessageBox.warning",
        lambda *a, **k: warned.setdefault("called", True),
    )
    window.open_video(SAMPLE_MP4)
    assert warned.get("called") is True
    assert window.camm_points == []


def test_position_changed_updates_marker(
    window: VerificationWindow, embedded_video: str, qtbot, monkeypatch
) -> None:
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.open_video(embedded_video)

    calls = []
    monkeypatch.setattr(
        window.map_widget, "update_marker", lambda lat, lon: calls.append("update")
    )
    monkeypatch.setattr(
        window.map_widget, "hide_marker", lambda: calls.append("hide")
    )

    window.on_position_changed(2000)
    assert calls == ["update"]


def test_position_changed_out_of_camm_range_hides_marker(
    window: VerificationWindow, embedded_video: str, qtbot, monkeypatch
) -> None:
    with qtbot.waitSignal(window.video_widget.duration_changed, timeout=10000):
        window.open_video(embedded_video)

    calls = []
    monkeypatch.setattr(
        window.map_widget, "update_marker", lambda lat, lon: calls.append("update")
    )
    monkeypatch.setattr(
        window.map_widget, "hide_marker", lambda: calls.append("hide")
    )

    window.on_position_changed(999_999)
    assert calls == ["hide"]
