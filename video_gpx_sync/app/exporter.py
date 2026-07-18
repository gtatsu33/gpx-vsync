from __future__ import annotations

import datetime
import os
import tempfile
from dataclasses import dataclass, field

from app.camm_encoder import embed_gps_track
from app.gpx_handler import GPXHandler
from app.state import AppState
from app.time_utils import playback_ms_to_real_ms
from app.video_handler import VideoHandler

MAPILLARY_TOOLS_COMMAND_TEMPLATE = (
    "mapillary_tools video_process_and_upload {video_path} \\\n"
    "    --geotag_source exif \\\n"
    "    --video_start_time {video_start_time} \\\n"
    "    --video_sample_distance 3 \\\n"
    "    --video_sample_interval -1 \\\n"
    "    --filetypes image"
)


def format_video_start_time(dt: datetime.datetime) -> str:
    """mapillary_toolsの --video_start_time 形式(YYYY_MM_DD_HH_MM_SS_sss, UTC)に変換する。"""
    dt_utc = dt.astimezone(datetime.timezone.utc)
    millis = dt_utc.microsecond // 1000
    return dt_utc.strftime("%Y_%m_%d_%H_%M_%S") + f"_{millis:03d}"


@dataclass
class Exporter:
    video_handler: VideoHandler = field(default_factory=VideoHandler)

    def can_export(self, state: AppState) -> bool:
        if (
            state.video_path is None
            or state.gpx_data is None
            or state.video_creation_time is None
        ):
            return False
        gpx_handler = GPXHandler(gpx=state.gpx_data)
        return gpx_handler.has_overlap(
            state.video_start_ms,
            state.video_end_ms,
            state.offset_seconds,
            state.video_creation_time,
            state.video_time_scale,
        )

    def generate_output_path(
        self, output_dir: str, source_path: str, output_ext: str
    ) -> str:
        base = os.path.splitext(os.path.basename(source_path))[0]
        candidate = f"{base}_synced{output_ext}"
        candidate_path = os.path.join(output_dir, candidate)
        counter = 2
        while os.path.exists(candidate_path):
            candidate = f"{base}_synced_{counter}{output_ext}"
            candidate_path = os.path.join(output_dir, candidate)
            counter += 1
        return candidate_path

    def default_video_filename(self, state: AppState) -> str:
        """保存ダイアログ（QFileDialog.getSaveFileName）に初期表示する
        動画ファイル名。generate_output_path()と同じ命名規則（重複時の
        連番は付与しない。保存ダイアログ自体がOS標準の上書き確認を
        行うため）。"""
        assert state.video_path is not None
        base = os.path.splitext(os.path.basename(state.video_path))[0]
        return f"{base}_synced.mp4"

    def export(self, state: AppState, video_output_path: str) -> tuple[str, str]:
        """video_output_path: 動画の保存先フルパス（拡張子込み。
        保存ダイアログでユーザーが指定した値をそのまま使う）。
        GPXファイルは、動画と同じディレクトリに従来通り
        generate_output_path()で自動生成した名前で出力する。"""
        if not self.can_export(state):
            raise ValueError(
                "GPXとオフセット適用後の時刻範囲が動画Start〜Endと重複しないため出力できません"
            )

        assert state.video_path is not None
        assert state.gpx_path is not None
        assert state.gpx_data is not None
        assert state.video_creation_time is not None

        output_dir = os.path.dirname(video_output_path)
        gpx_output_path = self.generate_output_path(
            output_dir, state.gpx_path, ".gpx"
        )

        gpx_handler = GPXHandler(gpx=state.gpx_data)

        with tempfile.TemporaryDirectory() as tmp_dir:
            smart_cut_path = os.path.join(tmp_dir, "smart_cut.mp4")
            self.video_handler.export_trimmed(
                state.video_path,
                smart_cut_path,
                state.video_start_ms,
                state.video_end_ms,
                video_creation_time=state.video_creation_time,
            )

            camm_points = gpx_handler.get_points_for_camm(
                state.video_start_ms,
                state.video_end_ms,
                state.offset_seconds,
                state.video_creation_time,
                state.video_time_scale,
            )
            # CAMMトラック埋め込みはffmpeg処理が全て完了した後の最後の工程で
            # 実行する必要がある（implement.txt 4-8節: ffmpegは未知コーデック
            # トラックをパススルーできないため）。
            embed_gps_track(smart_cut_path, video_output_path, camm_points)

        gpx_handler.export_trimmed(
            gpx_output_path,
            state.video_start_ms,
            state.video_end_ms,
            state.offset_seconds,
            state.video_creation_time,
            state.video_time_scale,
        )

        return video_output_path, gpx_output_path

    def get_video_start_time_str(self, state: AppState) -> str:
        """トリミング後の動画の実際の録画開始時刻を、mapillary_toolsの
        --video_start_time 形式で返す（build_mapillary_tools_commandと
        出力後ローカル検証(MapillaryValidator)の両方から使う共通値）。"""
        assert state.video_creation_time is not None
        synced_start_time = state.video_creation_time + datetime.timedelta(
            milliseconds=playback_ms_to_real_ms(
                state.video_start_ms, state.video_time_scale
            )
        )
        return format_video_start_time(synced_start_time)

    def build_mapillary_tools_command(
        self,
        state: AppState,
        video_output_path: str,
        gpx_output_path: str,
        user_name: str | None = None,
    ) -> str:
        command = MAPILLARY_TOOLS_COMMAND_TEMPLATE.format(
            video_path=video_output_path,
            video_start_time=self.get_video_start_time_str(state),
        )
        if user_name:
            command += f" \\\n    --user_name {user_name}"
        return command
