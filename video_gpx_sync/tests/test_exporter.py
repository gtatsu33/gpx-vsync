import datetime
from unittest.mock import MagicMock, patch

import gpxpy
import gpxpy.gpx
import pytest

from app.exporter import Exporter
from app.state import AppState

UTC = datetime.timezone.utc


def _pt(dt: datetime.datetime, lat: float, lon: float) -> gpxpy.gpx.GPXTrackPoint:
    return gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon, time=dt)


def _make_gpx(t0: datetime.datetime) -> gpxpy.gpx.GPX:
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points = [
        _pt(t0, 35.0000, 135.0000),
        _pt(t0 + datetime.timedelta(seconds=10), 35.0010, 135.0010),
    ]
    track.segments.append(segment)
    gpx.tracks.append(track)
    return gpx


@pytest.fixture
def base_state(tmp_path) -> AppState:
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    video_path = tmp_path / "ride01.mp4"
    video_path.write_bytes(b"dummy")
    gpx_path = tmp_path / "ride01.gpx"
    gpx_path.write_text("dummy", encoding="utf-8")

    return AppState(
        video_path=str(video_path),
        gpx_path=str(gpx_path),
        gpx_data=_make_gpx(t0),
        video_creation_time=t0,
        offset_seconds=0.0,
        video_start_ms=1000,
        video_end_ms=5000,
        video_duration_ms=10000,
    )


@pytest.fixture
def exporter() -> Exporter:
    return Exporter(video_handler=MagicMock())


def test_can_export_true_when_overlap(exporter: Exporter, base_state: AppState) -> None:
    assert exporter.can_export(base_state) is True


def test_can_export_false_when_no_overlap(
    exporter: Exporter, base_state: AppState
) -> None:
    base_state.offset_seconds = 1000.0  # 記録範囲外まで大きくずらす
    assert exporter.can_export(base_state) is False


def test_can_export_false_when_state_incomplete(exporter: Exporter) -> None:
    assert exporter.can_export(AppState()) is False


def test_generate_output_path_no_collision(exporter: Exporter, tmp_path) -> None:
    source = tmp_path / "ride01.mp4"
    source.write_bytes(b"x")
    result = exporter.generate_output_path(str(tmp_path), str(source), ".mp4")
    assert result == str(tmp_path / "ride01_synced.mp4")


def test_generate_output_path_with_collision_gets_sequence_number(
    exporter: Exporter, tmp_path
) -> None:
    source = tmp_path / "ride01.mp4"
    source.write_bytes(b"x")
    (tmp_path / "ride01_synced.mp4").write_bytes(b"existing")

    result = exporter.generate_output_path(str(tmp_path), str(source), ".mp4")
    assert result == str(tmp_path / "ride01_synced_2.mp4")

    (tmp_path / "ride01_synced_2.mp4").write_bytes(b"existing2")
    result2 = exporter.generate_output_path(str(tmp_path), str(source), ".mp4")
    assert result2 == str(tmp_path / "ride01_synced_3.mp4")


def test_default_video_filename(exporter: Exporter, base_state: AppState) -> None:
    assert exporter.default_video_filename(base_state) == "ride01_synced.mp4"


def test_export_raises_when_cannot_export(
    exporter: Exporter, base_state: AppState, tmp_path
) -> None:
    base_state.offset_seconds = 1000.0
    with pytest.raises(ValueError):
        exporter.export(base_state, str(tmp_path / "out.mp4"))


def test_export_calls_video_handler_and_embeds_camm_and_writes_gpx(
    exporter: Exporter, base_state: AppState, tmp_path
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    video_output_path_arg = str(output_dir / "my_custom_name.mp4")

    with patch("app.exporter.embed_gps_track") as mock_embed:
        video_output_path, gpx_output_path = exporter.export(
            base_state, video_output_path_arg
        )

    # 動画側は保存ダイアログで指定されたパスをそのまま使う（連番付与なし）
    assert video_output_path == video_output_path_arg
    # GPX側は従来通りgpx_pathベースで自動生成される
    assert gpx_output_path == str(output_dir / "ride01_synced.gpx")

    # VideoHandler.export_trimmed は一時パスにSmart Cut出力を書き出す
    exporter.video_handler.export_trimmed.assert_called_once()
    call = exporter.video_handler.export_trimmed.call_args
    assert call.args[0] == base_state.video_path
    assert call.args[2] == base_state.video_start_ms
    assert call.args[3] == base_state.video_end_ms
    assert call.kwargs["video_creation_time"] == base_state.video_creation_time

    # embed_gps_track はSmart Cut出力(一時パス)からvideo_output_pathへCAMM埋め込み
    mock_embed.assert_called_once()
    embed_call = mock_embed.call_args
    assert embed_call.args[1] == video_output_path
    camm_points = embed_call.args[2]
    assert len(camm_points) > 0

    with open(gpx_output_path, "r", encoding="utf-8") as f:
        result_gpx = gpxpy.parse(f)
    assert len(result_gpx.tracks[0].segments[0].points) > 0


def test_build_mapillary_tools_command(
    exporter: Exporter, base_state: AppState
) -> None:
    cmd = exporter.build_mapillary_tools_command(base_state, "out.mp4", "out.gpx")
    assert "mapillary_tools video_process_and_upload out.mp4" in cmd
    assert "--geotag_source exif" in cmd
    assert "--geotag_source_path" not in cmd
    assert "--video_sample_distance 3" in cmd
    assert "--video_sample_interval -1" in cmd
    # video_start_ms=1000 なので creation_time(01:00:00) + 1s = 01:00:01
    assert "--video_start_time 2026_07_12_01_00_01_000" in cmd


def test_get_video_start_time_str_applies_time_scale(
    exporter: Exporter, base_state: AppState
) -> None:
    # video_start_ms=1000, time_scale=15.0 -> 実世界では15秒後
    base_state.video_time_scale = 15.0
    result = exporter.get_video_start_time_str(base_state)
    assert result == "2026_07_12_01_00_15_000"


def test_export_camm_points_reflect_time_scale(
    exporter: Exporter, base_state: AppState, tmp_path
) -> None:
    base_state.video_time_scale = 5.0
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with patch("app.exporter.embed_gps_track") as mock_embed:
        exporter.export(base_state, str(output_dir / "out.mp4"))

    camm_points = mock_embed.call_args.args[2]
    assert len(camm_points) > 0
    native_span_ms = base_state.video_end_ms - base_state.video_start_ms
    for relative_ms, _lat, _lon, _elev, epoch_time in camm_points:
        # relative_msは動画自身の(圧縮された)ネイティブな再生位置なので、
        # トリミング区間の長さ(video_end_ms - video_start_ms)を超えない
        assert 0 <= relative_ms <= native_span_ms
        assert epoch_time > 0
