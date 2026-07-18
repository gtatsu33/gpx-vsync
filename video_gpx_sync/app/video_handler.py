from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass


class FFmpegError(RuntimeError):
    pass


@dataclass
class VideoHandler:
    def get_metadata(self, path: str) -> dict:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}: {result.stderr}")
        return json.loads(result.stdout)

    def get_duration_ms(self, path: str) -> int:
        metadata = self.get_metadata(path)
        duration_sec = float(metadata["format"]["duration"])
        return round(duration_sec * 1000)

    def get_creation_time(self, path: str) -> str | None:
        metadata = self.get_metadata(path)
        tags = metadata.get("format", {}).get("tags", {})
        return tags.get("creation_time")

    def get_fps(self, path: str) -> float:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}: {result.stderr}")
        raw = result.stdout.strip()
        if "/" in raw:
            num, den = raw.split("/")
            return float(num) / float(den)
        return float(raw)

    def has_audio_stream(self, path: str) -> bool:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}: {result.stderr}")
        return bool(result.stdout.strip())

    def _count_video_frames(self, path: str) -> int:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "v:0",
                "-show_entries",
                "frame=pts_time",
                "-of",
                "csv=print_section=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}: {result.stderr}")
        return sum(1 for line in result.stdout.splitlines() if line.strip())

    def get_keyframe_timestamps(self, path: str) -> list[float]:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "v:0",
                "-skip_frame",
                "nokey",
                "-show_entries",
                "frame=pts_time",
                "-of",
                "csv=print_section=0",
                path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}: {result.stderr}")

        timestamps: list[float] = []
        for line in result.stdout.splitlines():
            token = line.strip().split(",")[0]
            if token:
                timestamps.append(float(token))
        return timestamps

    def export_trimmed(
        self,
        input_path: str,
        output_path: str,
        start_ms: int,
        end_ms: int,
        video_creation_time: datetime.datetime | None = None,
    ) -> None:
        """出力はmapillary_tools向けであり音声は不要なため、
        _reencode_segment()/_copy_segment_by_frames()いずれも-anで
        音声トラックを出力に含めない（2026-07-18追加）。副次効果として、
        音声トラックのフレーム境界非整合により映像より僅かに長い
        音声だけが残り、コンテナ全体の長さ（ffprobeのformat.duration）
        が映像・GPSデータの実長より長くなる不具合も併せて解消される
        （実機で発生。動画のStart〜End全区間がGPSでカバーされている
        にもかかわらず、再読み込み時に末尾わずかがクロップ対象と
        誤検出される原因だった）。"""
        start_sec = start_ms / 1000
        end_sec = end_ms / 1000

        new_creation_time = None
        if video_creation_time is not None:
            new_creation_time = video_creation_time + datetime.timedelta(
                milliseconds=start_ms
            )

        keyframes = self.get_keyframe_timestamps(input_path)
        kf_after_start = next((k for k in keyframes if k >= start_sec), None)
        kf_before_end = max(
            (k for k in keyframes if k <= end_sec), default=None
        )

        with tempfile.TemporaryDirectory(prefix="gpx_vsync_smartcut_") as tmp_dir:
            if (
                kf_after_start is None
                or kf_before_end is None
                or kf_after_start >= kf_before_end
            ):
                # Start/Endが同一GOP内に収まる場合は分割不要
                self._reencode_segment(
                    input_path,
                    output_path,
                    start_sec,
                    end_sec,
                    creation_time=new_creation_time,
                )
                return

            parts: list[str] = []

            if kf_after_start > start_sec:
                part_a = os.path.join(tmp_dir, "part_a.mp4")
                self._reencode_segment(
                    input_path, part_a, start_sec, kf_after_start
                )
                parts.append(part_a)

            fps = self.get_fps(input_path)
            frame_count = round((kf_before_end - kf_after_start) * fps)
            part_b = os.path.join(tmp_dir, "part_b.mp4")
            self._copy_segment_by_frames(
                input_path, part_b, kf_after_start, frame_count
            )
            parts.append(part_b)

            if end_sec > kf_before_end:
                part_c = os.path.join(tmp_dir, "part_c.mp4")
                self._reencode_segment(
                    input_path, part_c, kf_before_end, end_sec
                )
                parts.append(part_c)

            if len(parts) == 1:
                if new_creation_time is not None:
                    self._set_creation_time(parts[0], output_path, new_creation_time)
                else:
                    os.replace(parts[0], output_path)
                return

            concat_list_path = os.path.join(tmp_dir, "concat_list.txt")
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for part in parts:
                    escaped = part.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            command = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_path,
                "-c",
                "copy",
            ]
            command.extend(self._metadata_args(new_creation_time))
            command.append(output_path)

            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise FFmpegError(f"ffmpeg concat failed: {result.stderr}")

    @staticmethod
    def _metadata_args(creation_time: datetime.datetime | None) -> list[str]:
        if creation_time is None:
            return []
        iso = creation_time.astimezone(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        return ["-metadata", f"creation_time={iso}"]

    def _set_creation_time(
        self, input_path: str, output_path: str, creation_time: datetime.datetime
    ) -> None:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-c",
                "copy",
                *self._metadata_args(creation_time),
                output_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffmpeg metadata write failed: {result.stderr}")

    def _reencode_segment(
        self,
        input_path: str,
        output_path: str,
        start_sec: float,
        end_sec: float,
        creation_time: datetime.datetime | None = None,
    ) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_sec),
            "-to",
            str(end_sec),
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-an",
        ]
        command.extend(self._metadata_args(creation_time))
        command.append(output_path)

        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise FFmpegError(f"ffmpeg re-encode failed: {result.stderr}")

    def _copy_segment_by_frames(
        self, input_path: str, output_path: str, start_sec: float, frame_count: int
    ) -> None:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_sec),
                "-i",
                input_path,
                "-frames:v",
                str(frame_count),
                "-c",
                "copy",
                "-an",
                output_path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffmpeg stream copy failed: {result.stderr}")
