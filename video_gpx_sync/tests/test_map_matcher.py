import datetime

import gpxpy.gpx
import pytest
import requests

from app.map_matcher import (
    MIN_REQUEST_INTERVAL_SEC,
    apply_matched_points,
    match_chunk,
    match_gpx_points,
    match_route,
)

UTC = datetime.timezone.utc


def _network_available() -> bool:
    try:
        requests.head("https://valhalla1.openstreetmap.de/", timeout=5)
        return True
    except requests.RequestException:
        return False


NETWORK_AVAILABLE = _network_available()


# ----------------------------------------------------------------
# apply_matched_points
# ----------------------------------------------------------------


def test_apply_matched_points_replaces_matched_and_interpolated_only() -> None:
    original = [(35.0, 135.0), (35.001, 135.001), (35.002, 135.002)]
    response = {
        "matched_points": [
            {"lat": 35.0001, "lon": 135.0001, "type": "matched"},
            {"type": "unmatched"},
            {"lat": 35.0021, "lon": 135.0021, "type": "interpolated"},
        ]
    }
    result = apply_matched_points(original, response)
    assert result[0] == (35.0001, 135.0001)
    assert result[1] == original[1]
    assert result[2] == (35.0021, 135.0021)


def test_apply_matched_points_missing_response_keeps_original() -> None:
    original = [(35.0, 135.0), (35.001, 135.001)]
    assert apply_matched_points(original, {}) == original


# ----------------------------------------------------------------
# match_route（match_chunk_implを注入した純粋ロジックテスト）
# ----------------------------------------------------------------


def test_match_route_single_chunk_success() -> None:
    points = [(35.0, 135.0), (35.001, 135.001)]

    def fake_match_chunk(chunk):
        return {
            "matched_points": [
                {"lat": lat + 0.0001, "lon": lon + 0.0001, "type": "matched"}
                for lat, lon in chunk
            ]
        }

    result = match_route(points, match_chunk_impl=fake_match_chunk)
    assert result.status == "完了"
    assert result.n_snapped == 2
    assert result.matched_points[0] == pytest.approx((35.0001, 135.0001))


def test_match_route_reports_progress_per_chunk() -> None:
    points = [(35.0, 135.0 + i * 0.0001) for i in range(120)]  # 3チャンク分

    def fake_match_chunk(chunk):
        return {
            "matched_points": [
                {"lat": lat + 0.001, "lon": lon, "type": "matched"} for lat, lon in chunk
            ]
        }

    progress_events = []
    match_route(
        points,
        on_progress=progress_events.append,
        match_chunk_impl=fake_match_chunk,
        sleep_impl=lambda _seconds: None,
    )

    # 各チャンク後の"running"通知(3件) + 完了後の最終ステータス通知(1件)
    assert len(progress_events) == 4
    assert [e.status for e in progress_events] == ["running", "running", "running", "完了"]
    assert progress_events[-1].chunk_idx == 3
    assert progress_events[-1].total_chunks == 3


def test_match_route_first_chunk_failure_cancels_everything() -> None:
    points = [(35.0, 135.0), (35.001, 135.001)] * 60  # 3チャンク分

    def failing_match_chunk(chunk):
        raise RuntimeError("boom")

    result = match_route(
        points, match_chunk_impl=failing_match_chunk, sleep_impl=lambda _seconds: None
    )
    assert result.status == "キャンセル"
    assert result.n_snapped == 0
    assert result.matched_points == points
    assert "1チャンク目タイムアウト" in result.error


def test_match_route_later_chunk_failure_continues_partial() -> None:
    points = [(35.0, 135.0 + i * 0.0001) for i in range(120)]  # 3チャンク

    call_count = {"n": 0}

    def flaky_match_chunk(chunk):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("chunk2 failed")
        return {"matched_points": [{"lat": lat + 0.001, "lon": lon, "type": "matched"} for lat, lon in chunk]}

    result = match_route(
        points, match_chunk_impl=flaky_match_chunk, sleep_impl=lambda _seconds: None
    )
    assert result.status == "完了"
    assert result.n_snapped == 70  # chunk0(50) + chunk2(20) がマッチ、chunk1(50)は元のまま
    assert "chunk 1" in result.error


def test_match_route_cancel_before_start_returns_original() -> None:
    points = [(35.0, 135.0), (35.001, 135.001)]

    def fake_match_chunk(chunk):
        return {"matched_points": [{"lat": lat, "lon": lon, "type": "matched"} for lat, lon in chunk]}

    result = match_route(points, should_cancel=lambda: True, match_chunk_impl=fake_match_chunk)
    assert result.status == "キャンセル"
    assert result.matched_points == points


def test_match_route_paces_requests_at_least_min_interval() -> None:
    # fair-use対応: チャンク間でmatch_chunk_implがほぼ即時応答しても、
    # 次のチャンク送信前にMIN_REQUEST_INTERVAL_SEC相当を待機するはず
    points = [(35.0, 135.0 + i * 0.0001) for i in range(120)]  # 3チャンク

    def fake_match_chunk(chunk):
        return {"matched_points": [{"lat": lat, "lon": lon, "type": "matched"} for lat, lon in chunk]}

    sleep_calls: list[float] = []
    match_route(
        points,
        match_chunk_impl=fake_match_chunk,
        sleep_impl=sleep_calls.append,
    )

    # チャンク間(3チャンクなら2回)だけ待機が発生し、1チャンク目の前には発生しない
    assert len(sleep_calls) == 2
    for seconds in sleep_calls:
        assert seconds == pytest.approx(MIN_REQUEST_INTERVAL_SEC, abs=0.05)


def test_match_route_single_chunk_does_not_sleep() -> None:
    points = [(35.0, 135.0), (35.001, 135.001)]

    def fake_match_chunk(chunk):
        return {"matched_points": [{"lat": lat, "lon": lon, "type": "matched"} for lat, lon in chunk]}

    sleep_calls: list[float] = []
    match_route(points, match_chunk_impl=fake_match_chunk, sleep_impl=sleep_calls.append)

    assert sleep_calls == []


# ----------------------------------------------------------------
# match_gpx_points（gpxpy連携。時刻・標高保持の確認）
# ----------------------------------------------------------------


def test_match_gpx_points_preserves_time_and_elevation() -> None:
    t0 = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    points = [
        gpxpy.gpx.GPXTrackPoint(
            latitude=35.0, longitude=135.0 + i * 0.00001, elevation=10.0 + i,
            time=t0 + datetime.timedelta(seconds=i),
        )
        for i in range(5)
    ]  # ほぼ直線だが、間引きを行わないため全点が対象になるはず

    def fake_match_chunk(chunk):
        return {
            "matched_points": [
                {"lat": lat + 0.0005, "lon": lon, "type": "matched"} for lat, lon in chunk
            ]
        }

    result = match_gpx_points(points, match_chunk_impl=fake_match_chunk)

    assert result.status == "完了"
    # 間引きを行わないため、元の点数がそのまま維持される
    assert len(result.points) == len(points)
    for original, matched in zip(points, result.points):
        assert matched.time == original.time
        assert matched.elevation == original.elevation
        assert matched.latitude == pytest.approx(original.latitude + 0.0005)
        assert matched.longitude == pytest.approx(original.longitude)


# ----------------------------------------------------------------
# match_chunk（実際のValhalla APIへの疎通確認。ネットワーク不通ならスキップ）
# ----------------------------------------------------------------


@pytest.mark.skipif(not NETWORK_AVAILABLE, reason="network unavailable")
def test_match_chunk_real_api_smoke_test() -> None:
    # 実在の道路に近い座標（東京駅付近、事前にOverpassで確認済みの道沿い）
    chunk = [
        (35.684286, 139.767683),
        (35.684137, 139.767629),
        (35.683188, 139.767135),
        (35.683026, 139.767014),
        (35.682650, 139.766245),
        (35.682617, 139.765888),
    ]
    response = match_chunk(chunk)
    assert "matched_points" in response
    assert len(response["matched_points"]) == len(chunk)
    types = {mp.get("type") for mp in response["matched_points"]}
    assert types & {"matched", "interpolated"}
