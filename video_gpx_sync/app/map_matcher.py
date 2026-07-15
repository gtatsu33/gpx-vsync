from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

import gpxpy.gpx
import requests

VALHALLA_URL = "https://valhalla1.openstreetmap.de/trace_attributes"

CHUNK_SIZE = 50
# FOSSGIS e.V.運営の公開Valhallaデモサーバーのfair-useポリシー
# （1リクエスト/秒/ユーザー）を守るため、チャンク送信の最小間隔を設ける。
MIN_REQUEST_INTERVAL_SEC = 1.0


def match_chunk(
    chunk: list[tuple[float, float]],
    search_radius: float = 50,
    timeout: float = 30,
) -> dict:
    """Valhalla trace_attributes で1チャンクをスナップする（bicycle固定）。
    失敗時（タイムアウト含む）は例外を投げる（呼び出し側=match_route()が
    チャンク処理ロジックとして継続/中断を判断する）。"""
    response = requests.post(
        VALHALLA_URL,
        json={
            "shape": [{"lat": lat, "lon": lon} for lat, lon in chunk],
            "costing": "bicycle",
            "shape_match": "map_snap",
            "search_radius": search_radius,
            "filters": {
                "attributes": ["matched.point", "matched.type"],
                "action": "include",
            },
        },
        headers={"Content-Type": "application/json", "X-Client-Id": "gpx-vsync"},
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"Valhalla request failed: {response.status_code}")
    return response.json()


def apply_matched_points(
    original_chunk: list[tuple[float, float]], match_response: dict
) -> list[tuple[float, float]]:
    """matchChunkのレスポンスから、matched/interpolatedの点だけを座標に反映する。
    それ以外（unmatched等）は元座標を保持する。"""
    matched_points = match_response.get("matched_points") or []
    result = []
    for i, pt in enumerate(original_chunk):
        mp = matched_points[i] if i < len(matched_points) else None
        if mp and mp.get("type") in ("matched", "interpolated"):
            result.append((mp["lat"], mp["lon"]))
        else:
            result.append(pt)
    return result


@dataclass
class MatchProgress:
    chunk_idx: int
    total_chunks: int
    n_snapped: int
    status: str
    error: str | None


@dataclass
class MatchResult:
    matched_points: list[tuple[float, float]]
    n_snapped: int
    status: str  # "完了" | "エラー" | "キャンセル"
    error: str | None = None


def match_route(
    points: list[tuple[float, float]],
    on_progress: Callable[[MatchProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    match_chunk_impl: Callable[[list[tuple[float, float]]], dict] = match_chunk,
    sleep_impl: Callable[[float], None] = time.sleep,
) -> MatchResult:
    """マップマッチングのチャンク処理ロジック。50点チャンクずつ順次実行し、
    進捗をon_progressで通知する。should_cancel()がTrueを返した時点で
    キャンセル扱いにする。
    チャンク送信の開始時刻同士がMIN_REQUEST_INTERVAL_SEC未満の間隔に
    ならないよう、必要な分だけ待機してからリクエストを送る
    （fair-use対応。sleep_impl()にかかった時間はレスポンス待ちを含む
    処理時間から差し引かれるため、無駄な待ちは発生しない）。"""
    on_progress = on_progress or (lambda _progress: None)
    should_cancel = should_cancel or (lambda: False)

    total_chunks = max(1, math.ceil(len(points) / CHUNK_SIZE))
    matched = list(points)
    n_snapped = 0
    errors: list[str] = []
    last_request_start: float | None = None

    for c in range(total_chunks):
        if should_cancel():
            error = "キャンセルされました" + (
                "; " + "; ".join(errors) if errors else ""
            )
            on_progress(
                MatchProgress(c, total_chunks, n_snapped, "キャンセル", error)
            )
            return MatchResult(matched, n_snapped, "キャンセル", error)

        start = c * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(points))
        chunk = points[start:end]

        if last_request_start is not None:
            remaining = MIN_REQUEST_INTERVAL_SEC - (
                time.monotonic() - last_request_start
            )
            if remaining > 0:
                sleep_impl(remaining)
        last_request_start = time.monotonic()

        try:
            response = match_chunk_impl(chunk)
            applied = apply_matched_points(chunk, response)
            for i, pt in enumerate(applied):
                if pt != chunk[i]:
                    matched[start + i] = pt
                    n_snapped += 1
        except Exception as exc:  # noqa: BLE001 - チャンク処理の継続判断に使う
            if c == 0:
                error = "1チャンク目タイムアウトにより自動キャンセル"
                on_progress(MatchProgress(0, total_chunks, 0, "キャンセル", error))
                return MatchResult(list(points), 0, "キャンセル", error)
            errors.append(f"chunk {c}: {exc}")

        on_progress(
            MatchProgress(c + 1, total_chunks, n_snapped, "running", None)
        )

    final_status = "完了" if n_snapped > 0 else "エラー"
    error = "; ".join(errors) if errors else None
    on_progress(
        MatchProgress(total_chunks, total_chunks, n_snapped, final_status, error)
    )
    return MatchResult(matched, n_snapped, final_status, error)


# ----------------------------------------------------------------
# gpxpy連携アダプタ（時刻・標高を保持する層。gpx-vsync固有）
# ----------------------------------------------------------------


@dataclass
class GpxMatchResult:
    points: list[gpxpy.gpx.GPXTrackPoint]
    n_snapped: int
    status: str
    error: str | None = None


def match_gpx_points(
    points: list[gpxpy.gpx.GPXTrackPoint],
    on_progress: Callable[[MatchProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    match_chunk_impl: Callable[[list[tuple[float, float]]], dict] = match_chunk,
    sleep_impl: Callable[[float], None] = time.sleep,
) -> GpxMatchResult:
    """points（時刻付きGPXTrackPoint列）を間引かずに全点マップマッチングし、
    各点の時刻・標高は元のまま、座標のみスナップ済みの新しいGPXTrackPoint列
    を返す。トラックポイントの記録間隔がそもそも粗い（0.5秒以上）場合、
    間引きは動画フレームとの時刻補間の分解能を不必要に犠牲にするため
    行わない（15章参照）。全点を送るためチャンク数が増える分は
    match_route()側のfair-use対応レート制限で吸収する。"""
    coords = [(p.latitude, p.longitude) for p in points]

    result = match_route(
        coords,
        on_progress=on_progress,
        should_cancel=should_cancel,
        match_chunk_impl=match_chunk_impl,
        sleep_impl=sleep_impl,
    )

    matched_points = [
        gpxpy.gpx.GPXTrackPoint(
            latitude=lat,
            longitude=lon,
            elevation=orig.elevation,
            time=orig.time,
        )
        for orig, (lat, lon) in zip(points, result.matched_points)
    ]

    return GpxMatchResult(
        points=matched_points,
        n_snapped=result.n_snapped,
        status=result.status,
        error=result.error,
    )
