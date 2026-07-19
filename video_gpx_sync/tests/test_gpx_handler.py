import datetime

import gpxpy.gpx
import pytest

from app.gpx_handler import GPXHandler

UTC = datetime.timezone.utc


def _pt(dt: datetime.datetime, lat: float, lon: float) -> gpxpy.gpx.GPXTrackPoint:
    return gpxpy.gpx.GPXTrackPoint(latitude=lat, longitude=lon, time=dt)


@pytest.fixture
def handler() -> GPXHandler:
    """
    2トラックにまたがる4点。ファイル上の順序はわざと時刻順とずらしてあり、
    get_all_points() が時刻でソートし直すことを検証できるようにしている。

    01:00:00  (34.9990, 134.9990)
    01:00:02  (34.9995, 134.9995)
    01:00:04  (35.0000, 135.0000)
    01:00:06  (35.0010, 135.0010)
    """
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)

    gpx = gpxpy.gpx.GPX()

    track_a = gpxpy.gpx.GPXTrack()
    seg_a = gpxpy.gpx.GPXTrackSegment()
    seg_a.points = [
        _pt(t0 + datetime.timedelta(seconds=4), 35.0000, 135.0000),
        _pt(t0 + datetime.timedelta(seconds=6), 35.0010, 135.0010),
    ]
    track_a.segments.append(seg_a)

    track_b = gpxpy.gpx.GPXTrack()
    seg_b = gpxpy.gpx.GPXTrackSegment()
    seg_b.points = [
        _pt(t0, 34.9990, 134.9990),
        _pt(t0 + datetime.timedelta(seconds=2), 34.9995, 134.9995),
    ]
    track_b.segments.append(seg_b)

    # わざとAを先に追加（ファイル順と時刻順が一致しない状態を作る）
    gpx.tracks.append(track_a)
    gpx.tracks.append(track_b)

    return GPXHandler(gpx=gpx)


@pytest.fixture
def video_creation_time() -> datetime.datetime:
    return datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)


def test_get_all_points_sorted_across_tracks(handler: GPXHandler) -> None:
    points = handler.get_all_points()
    times = [p.time for p in points]
    assert times == sorted(times)
    assert points[0].latitude == pytest.approx(34.9990)
    assert points[-1].latitude == pytest.approx(35.0010)


def test_from_camm_points_builds_sorted_handler_with_epoch_times() -> None:
    # relative_msの順序はわざと崩し、epoch_time側でソートされることを検証する
    camm_points = [
        (2000, 35.0020, 135.0020, 12.0, 1783818004.0),
        (0, 35.0000, 135.0000, 10.0, 1783818000.0),
        (1000, 35.0010, 135.0010, 11.0, 1783818002.0),
    ]
    handler = GPXHandler.from_camm_points(camm_points)
    points = handler.get_all_points()

    assert len(points) == 3
    assert [p.time.timestamp() for p in points] == [
        1783818000.0,
        1783818002.0,
        1783818004.0,
    ]
    assert points[0].latitude == pytest.approx(35.0000)
    assert points[0].elevation == pytest.approx(10.0)
    assert points[0].time.tzinfo is not None


def test_interpolate_position_linear(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # video_time_ms=3000 -> raw_time = 01:00:03, 01:00:02と01:00:04の中間
    pos = handler.interpolate_position(3000, 0.0, video_creation_time)
    assert pos is not None
    lat, lon = pos
    assert lat == pytest.approx(34.99975)
    assert lon == pytest.approx(134.99975)


def test_interpolate_position_out_of_range_returns_none(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    assert handler.interpolate_position(-5000, 0.0, video_creation_time) is None
    assert handler.interpolate_position(100_000, 0.0, video_creation_time) is None


def test_interpolate_position_respects_offset(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # offset_sec=+2: raw_time = video_creation_time + 1s + 2s = 01:00:03
    pos_via_offset = handler.interpolate_position(1000, 2.0, video_creation_time)
    pos_direct = handler.interpolate_position(3000, 0.0, video_creation_time)
    assert pos_via_offset == pos_direct


def test_interpolate_position_with_time_scale(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # time_scale=2.0: 再生位置1500msは実世界3000ms相当 -> 01:00:03
    pos_scaled = handler.interpolate_position(
        1500, 0.0, video_creation_time, video_time_scale=2.0
    )
    pos_direct = handler.interpolate_position(3000, 0.0, video_creation_time)
    assert pos_scaled == pos_direct


def test_interpolate_position_default_time_scale_is_identity(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    pos_default = handler.interpolate_position(3000, 0.0, video_creation_time)
    pos_explicit = handler.interpolate_position(
        3000, 0.0, video_creation_time, video_time_scale=1.0
    )
    assert pos_default == pos_explicit


def test_has_overlap(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    assert handler.has_overlap(1000, 5000, 0.0, video_creation_time) is True
    # 記録範囲(01:00:00-01:00:06)よりずっと後ろにオフセットでずらすと重複しない
    assert handler.has_overlap(1000, 5000, 100.0, video_creation_time) is False


def test_classify_points_in_range(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # 記録範囲: 01:00:00, 01:00:02, 01:00:04, 01:00:06
    # video_start_ms=1000/video_end_ms=5000 -> raw_time_range = 01:00:01〜01:00:05
    in_range = handler.classify_points_in_range(1000, 5000, 0.0, video_creation_time)
    assert in_range == [False, True, True, False]


def test_classify_points_in_range_respects_offset_and_time_scale(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # offset_sec=+2: raw_time_range = (0+2)〜(4000ms+2s) = 01:00:02〜01:00:06
    in_range = handler.classify_points_in_range(
        0, 4000, 2.0, video_creation_time
    )
    assert in_range == [False, True, True, True]

    # time_scale=2.0: video_start_ms=0(実世界0s)〜video_end_ms=2000(実世界4s)
    # -> raw_time_range = 01:00:00〜01:00:04
    in_range_scaled = handler.classify_points_in_range(
        0, 2000, 0.0, video_creation_time, video_time_scale=2.0
    )
    assert in_range_scaled == [True, True, True, False]


def test_clip_to_gps_coverage_no_change_when_fully_covered(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # 記録範囲(01:00:00-01:00:06)に完全に収まっている
    start_ms, end_ms = handler.clip_to_gps_coverage(2000, 4000, 0.0, video_creation_time)
    assert (start_ms, end_ms) == (2000, 4000)


def test_clip_to_gps_coverage_clips_start_only(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # video_start_ms=-3000 -> raw_start=00:59:57、記録開始(01:00:00)より前
    start_ms, end_ms = handler.clip_to_gps_coverage(-3000, 4000, 0.0, video_creation_time)
    assert start_ms == 0  # 記録開始時刻(01:00:00)に対応するms
    assert end_ms == 4000  # endは記録範囲内なので変化しない


def test_clip_to_gps_coverage_clips_end_only(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # video_end_ms=9000 -> raw_end=01:00:09、記録終了(01:00:06)より後
    start_ms, end_ms = handler.clip_to_gps_coverage(2000, 9000, 0.0, video_creation_time)
    assert start_ms == 2000
    assert end_ms == 6000  # 記録終了時刻(01:00:06)に対応するms


def test_clip_to_gps_coverage_clips_both_ends(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    start_ms, end_ms = handler.clip_to_gps_coverage(-3000, 9000, 0.0, video_creation_time)
    assert (start_ms, end_ms) == (0, 6000)


def test_clip_to_gps_coverage_respects_offset(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # 動画がGPX記録開始の3秒後から始まっている(video_creation_time=t0+3s)状態で
    # offset=-5秒をかけると、video_start_ms=0の時点のraw_timeは
    # (t0+3s)+0-5s=t0-2s となり、記録開始(t0)より前になる
    later_creation_time = video_creation_time + datetime.timedelta(seconds=3)
    start_ms, end_ms = handler.clip_to_gps_coverage(
        0, 6000, -5.0, later_creation_time
    )
    # クロップ後のstart_msに対応するraw_timeがちょうど記録開始(t0)になるはず
    # raw_time = later_creation_time + start_ms(real) - 5s = t0
    # -> start_ms(real) = t0 - later_creation_time + 5s = -3s + 5s = 2s = 2000ms
    assert start_ms == 2000
    assert end_ms == 6000


def test_get_points_for_camm_relative_ms_and_boundaries(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    points = handler.get_points_for_camm(
        video_start_ms=1000,
        video_end_ms=5000,
        offset_sec=0.0,
        video_creation_time=video_creation_time,
    )

    assert len(points) == 4

    # Start境界: true_start_time=01:00:01 -> relative_ms=0
    rel0, lat0, lon0, elev0, epoch0 = points[0]
    assert rel0 == 0
    assert lat0 == pytest.approx(34.99925)
    assert elev0 == 0.0
    assert epoch0 == pytest.approx(
        (video_creation_time + datetime.timedelta(seconds=1)).timestamp()
    )

    # 中間点: 01:00:02 -> relative_ms=1000, 01:00:04 -> relative_ms=3000
    rel1, lat1, _, _, _ = points[1]
    assert rel1 == 1000
    assert lat1 == pytest.approx(34.9995)

    rel2, lat2, _, _, _ = points[2]
    assert rel2 == 3000
    assert lat2 == pytest.approx(35.0000)

    # End境界: true_end_time=01:00:05 -> relative_ms=4000
    rel3, lat3, _, _, epoch3 = points[3]
    assert rel3 == 4000
    assert lat3 == pytest.approx(35.0005)
    assert epoch3 == pytest.approx(
        (video_creation_time + datetime.timedelta(seconds=5)).timestamp()
    )


def test_get_points_for_camm_native_relative_ms_with_time_scale(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    # time_scale=2.0: 再生1msが実世界2msに相当するタイムラプス動画を想定。
    # video_start_ms=500(実世界01:00:01) 〜 video_end_ms=2500(実世界01:00:05)
    points = handler.get_points_for_camm(
        video_start_ms=500,
        video_end_ms=2500,
        offset_sec=0.0,
        video_creation_time=video_creation_time,
        video_time_scale=2.0,
    )

    assert len(points) == 4

    # Start境界: true_start_time=01:00:01 -> relative_ms=0 (ネイティブ位置は不変)
    rel0, _, _, _, epoch0 = points[0]
    assert rel0 == 0
    assert epoch0 == pytest.approx(
        (video_creation_time + datetime.timedelta(seconds=1)).timestamp()
    )

    # 01:00:02 -> 実世界での経過1000ms -> ネイティブ位置は1000/2.0=500ms
    rel1, _, _, _, epoch1 = points[1]
    assert rel1 == 500
    assert epoch1 == pytest.approx(
        (video_creation_time + datetime.timedelta(seconds=2)).timestamp()
    )

    # End境界: 01:00:05 -> 実世界での経過4000ms -> ネイティブ位置は4000/2.0=2000ms
    rel3, _, _, _, epoch3 = points[3]
    assert rel3 == 2000
    assert epoch3 == pytest.approx(
        (video_creation_time + datetime.timedelta(seconds=5)).timestamp()
    )


def test_replace_points_rebuilds_single_track_and_preserves_existing_behavior(
    handler: GPXHandler, video_creation_time: datetime.datetime
) -> None:
    original_points = handler.get_all_points()
    # 座標だけ少しずらした新しい点列に置き換える（時刻・標高はそのまま）
    new_points = [
        gpxpy.gpx.GPXTrackPoint(
            latitude=p.latitude + 0.001,
            longitude=p.longitude + 0.001,
            elevation=p.elevation,
            time=p.time,
        )
        for p in original_points
    ]

    handler.replace_points(new_points)

    assert len(handler.gpx.tracks) == 1
    assert len(handler.gpx.tracks[0].segments) == 1

    result_points = handler.get_all_points()
    assert len(result_points) == len(original_points)
    assert result_points[0].latitude == pytest.approx(original_points[0].latitude + 0.001)
    assert result_points[0].time == original_points[0].time

    # 既存メソッド(has_overlap等)が置き換え後も正しく動作する（回帰確認）
    assert handler.has_overlap(1000, 5000, 0.0, video_creation_time) is True


def test_load_parses_file(tmp_path) -> None:
    gpx_content = """<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
<trk><name>t</name><trkseg>
<trkpt lat="35.0" lon="135.0"><time>2026-07-12T01:00:00Z</time></trkpt>
<trkpt lat="35.001" lon="135.001"><time>2026-07-12T01:00:02Z</time></trkpt>
</trkseg></trk>
</gpx>
"""
    gpx_path = tmp_path / "sample.gpx"
    gpx_path.write_text(gpx_content, encoding="utf-8")

    handler = GPXHandler.load(str(gpx_path))
    points = handler.get_all_points()
    assert len(points) == 2
    assert points[0].latitude == pytest.approx(35.0)
