from __future__ import annotations

import datetime
from dataclasses import dataclass

import gpxpy
import gpxpy.gpx

from app.time_utils import playback_ms_to_real_ms, real_ms_to_playback_ms


@dataclass
class GPXHandler:
    gpx: gpxpy.gpx.GPX

    @classmethod
    def load(cls, path: str) -> "GPXHandler":
        with open(path, "r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
        return cls(gpx=gpx)

    @classmethod
    def from_camm_points(
        cls, camm_points: list[tuple[int, float, float, float, float]]
    ) -> "GPXHandler":
        """動画に埋め込まれたCAMM GPSトラック
        （camm_encoder.extract_gps_track()の戻り値。(relative_ms,
        latitude, longitude, elevation, epoch_time)のリスト）から、
        実時刻付きのGPXHandlerを構築する（22章）。epoch_time（実際の
        撮影時刻）のみを使い、relative_ms（動画自身のタイムライン上の
        位置）は無視する。以降は通常のGPX読み込みと全く同じ
        GPXHandlerパイプライン（オフセット調整・マップ表示・出力）で
        扱える。"""
        points = [
            gpxpy.gpx.GPXTrackPoint(
                latitude=lat,
                longitude=lon,
                elevation=elevation,
                time=datetime.datetime.fromtimestamp(
                    epoch_time, tz=datetime.timezone.utc
                ),
            )
            for _relative_ms, lat, lon, elevation, epoch_time in camm_points
        ]
        points.sort(key=lambda p: p.time)

        gpx = gpxpy.gpx.GPX()
        track = gpxpy.gpx.GPXTrack()
        segment = gpxpy.gpx.GPXTrackSegment()
        segment.points = points
        track.segments.append(segment)
        gpx.tracks.append(track)
        return cls(gpx=gpx)

    def get_all_points(self) -> list[gpxpy.gpx.GPXTrackPoint]:
        """全トラック・全セグメントのポイントを時刻順に結合して返す。"""
        points = [
            point
            for track in self.gpx.tracks
            for segment in track.segments
            for point in segment.points
            if point.time is not None
        ]
        points.sort(key=lambda p: p.time)
        return points

    def interpolate_position(
        self,
        video_time_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> tuple[float, float] | None:
        """動画上の再生位置に対応する、GPX記録時刻軸上での緯度経度を返す。
        video_time_scale はタイムラプス動画向けの再生位置→実世界経過時間の
        倍率（通常動画は1.0のまま）。"""
        raw_time = (
            video_creation_time
            + datetime.timedelta(
                milliseconds=playback_ms_to_real_ms(video_time_ms, video_time_scale)
            )
            + datetime.timedelta(seconds=offset_sec)
        )
        return self._interpolate_at(raw_time)

    def _interpolate_at(
        self, raw_time: datetime.datetime
    ) -> tuple[float, float] | None:
        """GPXの生の記録時刻軸(raw_time)における緯度経度を線形補間で返す。"""
        points = self.get_all_points()
        if not points:
            return None
        if raw_time < points[0].time or raw_time > points[-1].time:
            return None

        # points は time でソート済みなので二分探索で前後の点を求める
        lo, hi = 0, len(points) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if points[mid].time < raw_time:
                lo = mid + 1
            else:
                hi = mid
        after = points[lo]
        if after.time == raw_time or lo == 0:
            return after.latitude, after.longitude
        before = points[lo - 1]

        span = (after.time - before.time).total_seconds()
        if span <= 0:
            return before.latitude, before.longitude
        ratio = (raw_time - before.time).total_seconds() / span
        lat = before.latitude + (after.latitude - before.latitude) * ratio
        lon = before.longitude + (after.longitude - before.longitude) * ratio
        return lat, lon

    def _raw_time_range(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> tuple[datetime.datetime, datetime.datetime]:
        """動画のStart/End位置を、GPXの生の記録時刻軸(raw_time)に変換する。"""
        raw_start = (
            video_creation_time
            + datetime.timedelta(
                milliseconds=playback_ms_to_real_ms(video_start_ms, video_time_scale)
            )
            + datetime.timedelta(seconds=offset_sec)
        )
        raw_end = (
            video_creation_time
            + datetime.timedelta(
                milliseconds=playback_ms_to_real_ms(video_end_ms, video_time_scale)
            )
            + datetime.timedelta(seconds=offset_sec)
        )
        return raw_start, raw_end

    def has_overlap(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> bool:
        points = self.get_all_points()
        if not points:
            return False
        raw_start, raw_end = self._raw_time_range(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )
        return raw_start <= points[-1].time and raw_end >= points[0].time

    def _raw_time_to_video_ms(
        self,
        raw_time: datetime.datetime,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float,
    ) -> int:
        """_raw_time_range()の逆変換。GPXの生の記録時刻軸上の時刻から、
        対応する動画再生位置(ms)を求める。"""
        real_ms = round(
            (
                raw_time - video_creation_time - datetime.timedelta(seconds=offset_sec)
            ).total_seconds()
            * 1000
        )
        return real_ms_to_playback_ms(real_ms, video_time_scale)

    def clip_to_gps_coverage(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> tuple[int, int]:
        """動画のStart/Endを、GPXが実際に記録している範囲でカバーされる
        区間にクロップした(video_start_ms, video_end_ms)を返す。
        Start-End全体が既にGPXの記録範囲内に収まっている場合は、元の値を
        そのまま返す（クロップ不要）。GPXに記録点が無い場合も元の値を
        そのまま返す（has_overlap()等で別途ガードされている前提）。
        GPS未記録区間の可視化には値の変化の有無を使う（MainWindow
        _confirm_and_apply_gps_coverage_crop()）。"""
        points = self.get_all_points()
        if not points:
            return video_start_ms, video_end_ms

        raw_start, raw_end = self._raw_time_range(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )

        new_start_ms = video_start_ms
        new_end_ms = video_end_ms

        if raw_start < points[0].time:
            new_start_ms = self._raw_time_to_video_ms(
                points[0].time, offset_sec, video_creation_time, video_time_scale
            )
        if raw_end > points[-1].time:
            new_end_ms = self._raw_time_to_video_ms(
                points[-1].time, offset_sec, video_creation_time, video_time_scale
            )

        return new_start_ms, new_end_ms

    def classify_points_in_range(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> list[bool]:
        """get_all_points()と同じ順序・点数で、各点が動画のStart/End出力
        範囲内（＝raw_time_range内）かどうかを返す。マップ上でのルート線の
        色分け表示（クロップされる領域の可視化）に使う。"""
        points = self.get_all_points()
        raw_start, raw_end = self._raw_time_range(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )
        return [raw_start <= p.time <= raw_end for p in points]

    def _build_output_points(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> list[tuple[datetime.datetime, float, float, float | None]]:
        """出力用の(true_time, latitude, longitude, elevation)点列を、
        区間境界の補間込みで構築する。export_trimmed / get_points_for_camm
        の共通ロジック。true_time は常に実世界の絶対時刻（video_time_scale
        適用済み）であり、動画自身の圧縮タイムライン上の位置ではない点に
        注意（コンテナ内配置への変換はget_points_for_camm側で行う）。"""
        true_start_time = video_creation_time + datetime.timedelta(
            milliseconds=playback_ms_to_real_ms(video_start_ms, video_time_scale)
        )
        true_end_time = video_creation_time + datetime.timedelta(
            milliseconds=playback_ms_to_real_ms(video_end_ms, video_time_scale)
        )
        raw_start, raw_end = self._raw_time_range(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )

        points = self.get_all_points()
        in_range = [p for p in points if raw_start <= p.time <= raw_end]

        out: list[tuple[datetime.datetime, float, float, float | None]] = []

        if not in_range or in_range[0].time != raw_start:
            start_latlon = self._interpolate_at(raw_start)
            if start_latlon is not None:
                lat, lon = start_latlon
                out.append((true_start_time, lat, lon, None))

        for p in in_range:
            out.append(
                (
                    p.time - datetime.timedelta(seconds=offset_sec),
                    p.latitude,
                    p.longitude,
                    p.elevation,
                )
            )

        if not in_range or in_range[-1].time != raw_end:
            end_latlon = self._interpolate_at(raw_end)
            if end_latlon is not None:
                lat, lon = end_latlon
                out.append((true_end_time, lat, lon, None))

        return out

    def export_trimmed(
        self,
        output_path: str,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> None:
        built_points = self._build_output_points(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )

        out_points = [
            gpxpy.gpx.GPXTrackPoint(
                latitude=lat, longitude=lon, elevation=elevation, time=t
            )
            for t, lat, lon, elevation in built_points
        ]

        out_gpx = gpxpy.gpx.GPX()
        out_track = gpxpy.gpx.GPXTrack()
        out_segment = gpxpy.gpx.GPXTrackSegment()
        out_segment.points = out_points
        out_track.segments.append(out_segment)
        out_gpx.tracks.append(out_track)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(out_gpx.to_xml(version="1.1"))

    def replace_points(self, points: list[gpxpy.gpx.GPXTrackPoint]) -> None:
        """self.gpxを単一トラック・単一セグメントの構造に作り直し、pointsで
        完全に置き換える（マップマッチング完了後にMainWindowから呼ばれる）。
        既存の複数トラック/セグメント構造は破棄されるが、get_all_points()は
        もともと全トラック・セグメントを時刻順に結合した1本の点列として扱う
        設計のため、他の全メソッドへの影響はない。"""
        new_gpx = gpxpy.gpx.GPX()
        new_track = gpxpy.gpx.GPXTrack()
        new_segment = gpxpy.gpx.GPXTrackSegment()
        new_segment.points = list(points)
        new_track.segments.append(new_segment)
        new_gpx.tracks.append(new_track)
        self.gpx = new_gpx

    def get_points_for_camm(
        self,
        video_start_ms: int,
        video_end_ms: int,
        offset_sec: float,
        video_creation_time: datetime.datetime,
        video_time_scale: float = 1.0,
    ) -> list[tuple[int, float, float, float, float]]:
        """CammEncoder.embed_gps_track() 用に、(relative_ms, latitude,
        longitude, elevation, epoch_time) の点列を返す（15章）。
        relative_ms は動画自身の圧縮されたネイティブな再生タイムライン上の
        位置（real_ms_to_playback_ms()で実世界時間から逆変換）、
        epoch_time は実際の撮影時刻をUnixエポック秒で表したもの。
        mapillary_toolsはCAMM Type 6のtime_gps_epochフィールドを検出できれば
        それを直接MAPCaptureTimeとして採用するため、relative_msが圧縮されて
        いても（＝動画自体のfpsと無関係に）epoch_time側で正しい実時刻が
        得られる。"""
        true_start_time = video_creation_time + datetime.timedelta(
            milliseconds=playback_ms_to_real_ms(video_start_ms, video_time_scale)
        )
        built_points = self._build_output_points(
            video_start_ms, video_end_ms, offset_sec, video_creation_time, video_time_scale
        )
        return [
            (
                real_ms_to_playback_ms(
                    round((t - true_start_time).total_seconds() * 1000),
                    video_time_scale,
                ),
                lat,
                lon,
                elevation if elevation is not None else 0.0,
                t.timestamp(),
            )
            for t, lat, lon, elevation in built_points
        ]
