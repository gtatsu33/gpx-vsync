import os
import shutil

import pytest

from app.camm_encoder import (
    CammTrackNotFoundError,
    embed_gps_track,
    extract_gps_track,
    interpolate_camm_points,
)

MP4BOX_AVAILABLE = shutil.which("MP4Box") is not None

pytestmark = pytest.mark.skipif(not MP4BOX_AVAILABLE, reason="MP4Box not installed")

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample_420p.mp4")

EMBED_POINTS = [
    (0, 35.0000, 135.0000, 10.0, 1783818000.0),
    (1500, 35.0010, 135.0010, 11.0, 1783818001.5),
    (3000, 35.0020, 135.0020, 12.0, 1783818003.0),
]
# extract_gps_track()はtime_gps_epoch等の付加情報を読み捨てるため、
# 比較対象は(relative_ms, lat, lon, elevation)の4要素のみ
SAMPLE_POINTS = [(ms, lat, lon, elev) for ms, lat, lon, elev, _epoch in EMBED_POINTS]


def test_embed_then_extract_round_trip(tmp_path) -> None:
    output_path = str(tmp_path / "embedded.mp4")
    embed_gps_track(SAMPLE_MP4, output_path, EMBED_POINTS)

    assert os.path.exists(output_path)

    extracted = extract_gps_track(output_path)
    assert extracted == SAMPLE_POINTS


def test_extract_raises_when_no_camm_track() -> None:
    with pytest.raises(CammTrackNotFoundError):
        extract_gps_track(SAMPLE_MP4)


def test_interpolate_camm_points_linear() -> None:
    pos = interpolate_camm_points(SAMPLE_POINTS, 2250)
    assert pos is not None
    lat, lon = pos
    assert lat == pytest.approx(35.0015)
    assert lon == pytest.approx(135.0015)


def test_interpolate_camm_points_out_of_range_returns_none() -> None:
    assert interpolate_camm_points(SAMPLE_POINTS, -100) is None
    assert interpolate_camm_points(SAMPLE_POINTS, 100_000) is None


def test_interpolate_camm_points_empty_returns_none() -> None:
    assert interpolate_camm_points([], 1000) is None
