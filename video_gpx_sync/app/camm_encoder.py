from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

CAMM_GPS_TYPE6_STRUCT = struct.Struct("<HHdiddfffffff")
# reserved, type, time_gps_epoch, gps_fix_type, latitude, longitude, altitude,
# horizontal_accuracy, vertical_accuracy, velocity_east, velocity_north,
# velocity_up, speed_accuracy
CAMM_GPS_SAMPLE_TYPE = 6
CAMM_GPS_FIX_TYPE_3D = 3

_TRACK_HEADER_RE = re.compile(r"^# Track \d+ Info - ID (\d+)")


class CammEncodeError(Exception):
    """MP4Boxの実行に失敗した場合に送出する。"""


class CammTrackNotFoundError(Exception):
    """動画にCAMM形式のGPSトラックが見つからない場合に送出する。"""


def _require_mp4box() -> None:
    if shutil.which("MP4Box") is None:
        raise CammEncodeError(
            "MP4Box (GPAC) が見つかりません。brew install gpac でインストールしてください。"
        )


def embed_gps_track(
    video_path: str,
    output_path: str,
    points: list[tuple[int, float, float, float, float]],
) -> None:
    """points: (relative_ms, latitude, longitude, elevation, epoch_time) の
    リストをCAMM Type 6(GPS)トラックとしてvideo_pathに追加し、output_path に
    書き出す。relative_msは動画自身の(圧縮された)ネイティブな再生タイムライン
    上の位置、epoch_timeはUnixエポック秒での実際の撮影時刻(UTC)。
    mapillary_toolsはgeotag_source=exif/cammでこのepoch_timeを検出できれば
    それをそのままMAPCaptureTimeとして使うため、タイムラプス動画でも
    動画自体のfpsと無関係に正しい実時刻が得られる（15章）。
    """
    _require_mp4box()

    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_path = os.path.join(tmp_dir, "gps.raw")
        nhml_path = os.path.join(tmp_dir, "gps.nhml")

        offset = 0
        sample_lines = []
        with open(raw_path, "wb") as raw_f:
            for relative_ms, lat, lon, elevation, epoch_time in points:
                chunk = CAMM_GPS_TYPE6_STRUCT.pack(
                    0,
                    CAMM_GPS_SAMPLE_TYPE,
                    epoch_time,
                    CAMM_GPS_FIX_TYPE_3D,
                    lat,
                    lon,
                    elevation,
                    5.0,  # horizontal_accuracy (unknown、実機検証済みの無難な値)
                    5.0,  # vertical_accuracy (unknown、実機検証済みの無難な値)
                    0.0,  # velocity_east (unused)
                    0.0,  # velocity_north (unused)
                    0.0,  # velocity_up (unused)
                    1.0,  # speed_accuracy (unknown、実機検証済みの無難な値)
                )
                raw_f.write(chunk)
                sample_lines.append(
                    f'<NHNTSample DTS="{relative_ms}" '
                    f'dataLength="{len(chunk)}" mediaOffset="{offset}"/>'
                )
                offset += len(chunk)

        nhml_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<NHNTStream mediaType="meta" mediaSubType="camm" codecID="camm" '
            f'timeScale="1000" baseMediaFile="{raw_path}">\n'
            + "\n".join(sample_lines)
            + "\n</NHNTStream>\n"
        )
        with open(nhml_path, "w", encoding="utf-8") as f:
            f.write(nhml_content)

        result = subprocess.run(
            ["MP4Box", "-add", video_path, "-add", nhml_path, output_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise CammEncodeError(
                f"MP4BoxによるCAMMトラック埋め込みに失敗しました: {result.stderr}"
            )


def extract_gps_track(
    video_path: str,
) -> list[tuple[int, float, float, float, float]]:
    """embed_gps_track() の逆操作。戻り値は(relative_ms, latitude,
    longitude, elevation, epoch_time)で、embed_gps_track()の入力形式と
    対称になっている。CAMMトラックが見つからない場合は
    CammTrackNotFoundError を送出する。"""
    _require_mp4box()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # MP4Boxの -nhml は入力動画と同じディレクトリに出力ファイルを
        # 書き出すため、元ファイルのディレクトリを汚さないよう
        # 一時ディレクトリにコピーしてから処理する。
        copy_path = os.path.join(
            tmp_dir, "video" + os.path.splitext(video_path)[1]
        )
        shutil.copyfile(video_path, copy_path)

        info_result = subprocess.run(
            ["MP4Box", "-info", copy_path], capture_output=True, text=True
        )
        track_id = _find_camm_track_id(info_result.stderr)
        if track_id is None:
            raise CammTrackNotFoundError(
                "この動画にはCAMM形式のGPSトラックが埋め込まれていません"
            )

        nhml_result = subprocess.run(
            ["MP4Box", "-nhml", str(track_id), copy_path],
            capture_output=True,
            text=True,
        )
        if nhml_result.returncode != 0:
            raise CammEncodeError(
                f"MP4BoxによるCAMMトラック抽出に失敗しました: {nhml_result.stderr}"
            )

        base = os.path.splitext(copy_path)[0]
        nhml_path = f"{base}_track{track_id}.nhml"
        media_path = f"{base}_track{track_id}.media"

        return _parse_nhml_camm(nhml_path, media_path)


def _find_camm_track_id(info_output: str) -> int | None:
    current_track_id: int | None = None
    for line in info_output.splitlines():
        header_match = _TRACK_HEADER_RE.match(line)
        if header_match:
            current_track_id = int(header_match.group(1))
            continue
        if "Media Type: meta:camm" in line and current_track_id is not None:
            return current_track_id
    return None


def _parse_nhml_camm(
    nhml_path: str, media_path: str
) -> list[tuple[int, float, float, float, float]]:
    """embed_gps_track()で埋め込んだCAMM Type 6(GPS)サンプルを読み戻す。
    time_gps_epoch（実際の撮影時刻、UTC epoch秒）も含めて返す
    （22章。動画に埋め込まれたGPSデータをGPXデータ相当として
    取り込む際、実時刻付きのGPXTrackPointを構築するために必要）。"""
    tree = ET.parse(nhml_path)
    root = tree.getroot()

    with open(media_path, "rb") as f:
        media_data = f.read()

    points: list[tuple[int, float, float, float, float]] = []
    offset = 0
    for sample in root.findall("NHNTSample"):
        dts = int(sample.get("DTS"))
        data_length = int(sample.get("dataLength"))
        chunk = media_data[offset : offset + data_length]
        offset += data_length
        (
            _reserved,
            _type,
            time_gps_epoch,
            _gps_fix_type,
            lat,
            lon,
            elevation,
            _horizontal_accuracy,
            _vertical_accuracy,
            _velocity_east,
            _velocity_north,
            _velocity_up,
            _speed_accuracy,
        ) = CAMM_GPS_TYPE6_STRUCT.unpack(chunk)
        points.append((dts, lat, lon, elevation, time_gps_epoch))

    return points
