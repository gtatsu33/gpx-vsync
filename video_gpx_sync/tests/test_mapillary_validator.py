import datetime
import os
import shutil

import pytest

from app.camm_encoder import embed_gps_track
from app.exporter import format_video_start_time
from app.gpx_handler import GPXHandler
from app.mapillary_validator import is_mapillary_tools_available, validate_export

MAPILLARY_TOOLS_AVAILABLE = shutil.which("mapillary_tools") is not None
MP4BOX_AVAILABLE = shutil.which("MP4Box") is not None

pytestmark = pytest.mark.skipif(
    not (MAPILLARY_TOOLS_AVAILABLE and MP4BOX_AVAILABLE),
    reason="mapillary_tools or MP4Box not installed",
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample_420p.mp4")

SAMPLE_POINTS = [
    (0, 35.0000, 135.0000, 10.0, 1783818000.0),
    (5000, 35.0010, 135.0010, 11.0, 1783818005.0),
    (10000, 35.0020, 135.0020, 12.0, 1783818010.0),
]  # sample_420p.mp4は10秒なので、CAMMトラックも全区間をカバーする


def test_is_mapillary_tools_available_returns_true_when_installed() -> None:
    assert is_mapillary_tools_available() is True


@pytest.fixture
def embedded_video(tmp_path) -> str:
    output_path = str(tmp_path / "embedded.mp4")
    embed_gps_track(SAMPLE_MP4, output_path, SAMPLE_POINTS)
    return output_path


def test_validate_export_succeeds_with_camm_embedded_video(embedded_video: str) -> None:
    result = validate_export(embedded_video, "2026_07_12_01_00_00_000")
    assert result is not None
    assert result.ok is True
    assert result.n_images > 0


def test_validate_export_fails_without_gps() -> None:
    result = validate_export(SAMPLE_MP4, "2026_07_12_01_00_00_000")
    assert result is not None
    assert result.ok is False
    assert result.n_images == 0
    assert len(result.errors) > 0


def test_validate_export_cancel_returns_none(embedded_video: str) -> None:
    result = validate_export(
        embedded_video, "2026_07_12_01_00_00_000", should_cancel=lambda: True
    )
    assert result is None


def test_validate_export_leaves_source_directory_untouched(
    embedded_video: str, tmp_path
) -> None:
    before = set(os.listdir(tmp_path))
    validate_export(embedded_video, "2026_07_12_01_00_00_000")
    after = set(os.listdir(tmp_path))
    assert before == after


def test_validate_export_succeeds_for_timelapse_video(tmp_path) -> None:
    """15章: 実世界0.5秒間隔・fps=30相当のタイムラプス(time_scale=15)を
    模したCAMM Type6トラックを実際にmapillary_tools video_processへ通し、
    time_gps_epochにより正しい実時刻・GPS位置が取り出せることを確認する
    （ネイティブ10秒の動画が実世界150秒分のデータを表す想定）。"""
    UTC = datetime.timezone.utc
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    gpx_content_points = "\n".join(
        f'<trkpt lat="{35.0000 + i * 0.0001}" lon="{135.0000 + i * 0.0001}">'
        f"<time>{(t0 + datetime.timedelta(seconds=i * 5)).isoformat().replace('+00:00', 'Z')}</time>"
        "</trkpt>"
        for i in range(31)  # 0, 5, 10, ..., 150秒 (実世界150秒をカバー)
    )
    gpx_content = (
        '<?xml version="1.0"?>\n'
        '<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"<trk><trkseg>{gpx_content_points}</trkseg></trk>\n"
        "</gpx>\n"
    )
    gpx_path = tmp_path / "timelapse.gpx"
    gpx_path.write_text(gpx_content, encoding="utf-8")

    handler = GPXHandler.load(str(gpx_path))
    camm_points = handler.get_points_for_camm(
        video_start_ms=0,
        video_end_ms=10000,
        offset_sec=0.0,
        video_creation_time=t0,
        video_time_scale=15.0,
    )
    assert len(camm_points) > 0
    # relative_msはネイティブ動画の実尺(0-10000ms)を超えない
    assert all(0 <= rel <= 10000 for rel, *_ in camm_points)

    output_path = str(tmp_path / "timelapse_embedded.mp4")
    embed_gps_track(SAMPLE_MP4, output_path, camm_points)

    result = validate_export(output_path, format_video_start_time(t0))
    assert result is not None
    assert result.ok is True
    assert result.n_images > 0
