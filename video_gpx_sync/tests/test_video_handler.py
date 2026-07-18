import datetime
import os
import shutil

import pytest

from app.video_handler import VideoHandler

UTC = datetime.timezone.utc

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which(
    "ffprobe"
) is not None

pytestmark = pytest.mark.skipif(
    not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not installed"
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_MP4 = os.path.join(FIXTURES_DIR, "sample.mp4")


@pytest.fixture
def handler() -> VideoHandler:
    return VideoHandler()


def test_get_metadata(handler: VideoHandler) -> None:
    metadata = handler.get_metadata(SAMPLE_MP4)
    assert "format" in metadata
    assert float(metadata["format"]["duration"]) == pytest.approx(10.0, abs=0.1)


def test_get_duration_ms(handler: VideoHandler) -> None:
    duration_ms = handler.get_duration_ms(SAMPLE_MP4)
    assert duration_ms == pytest.approx(10000, abs=100)


def test_get_creation_time(handler: VideoHandler) -> None:
    creation_time = handler.get_creation_time(SAMPLE_MP4)
    assert creation_time == "2026-07-12T01:00:00.000000Z"


def test_get_fps(handler: VideoHandler) -> None:
    fps = handler.get_fps(SAMPLE_MP4)
    assert fps == pytest.approx(30.0)


def test_get_keyframe_timestamps(handler: VideoHandler) -> None:
    keyframes = handler.get_keyframe_timestamps(SAMPLE_MP4)
    # sample.mp4 は -g 60 (30fps) で2秒ごとにキーフレーム
    assert keyframes == pytest.approx([0.0, 2.0, 4.0, 6.0, 8.0], abs=0.01)


def test_export_trimmed_smart_cut_frame_accurate(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed.mp4"
    # 2.5s -> 7.3s: キーフレーム境界(4.0, 6.0)を含む、A/B/C 3分割になるケース
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=2500, end_ms=7300)

    assert output_path.exists()

    fps = handler.get_fps(SAMPLE_MP4)
    keyframes = handler.get_keyframe_timestamps(str(output_path))
    # フレーム総数が期待通りか確認（B-frame由来の余剰フレーム混入がないか）
    frame_count = handler._count_video_frames(str(output_path))
    expected_frames = round((7.3 - 2.5) * fps)
    assert frame_count == expected_frames


def test_export_trimmed_within_single_gop(handler: VideoHandler, tmp_path) -> None:
    output_path = tmp_path / "trimmed_single_gop.mp4"
    # 0.5s -> 1.5s: キーフレーム(0.0, 2.0)の間、単一GOP内に収まるケース
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=500, end_ms=1500)

    assert output_path.exists()
    duration_ms = handler.get_duration_ms(str(output_path))
    assert duration_ms == pytest.approx(1000, abs=100)


def test_export_trimmed_boundaries_exactly_on_keyframes(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed_exact_kf.mp4"
    # 2.0s -> 6.0s: 両端がちょうどキーフレームに一致するケース（区間A/Cが不要）
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=2000, end_ms=6000)

    assert output_path.exists()
    fps = handler.get_fps(SAMPLE_MP4)
    frame_count = handler._count_video_frames(str(output_path))
    expected_frames = round((6.0 - 2.0) * fps)
    assert frame_count == expected_frames


def test_export_trimmed_smart_cut_has_no_audio_track(
    handler: VideoHandler, tmp_path
) -> None:
    """出力にmapillary_tools向けには不要な音声を含めない（2026-07-18）。
    音声トラックだけ映像より僅かに長く残り、コンテナ全体の長さが
    映像・GPSデータの実長より長くなる不具合の原因でもあった。"""
    output_path = tmp_path / "trimmed_no_audio.mp4"
    # SAMPLE_MP4(sample.mp4)は音声トラック有り。3分割スマートカットの
    # 経路（区間B: _copy_segment_by_frames）でも音声が混入しないことを
    # 確認する
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=2500, end_ms=7300)

    codec_types = [
        stream["codec_type"] for stream in handler.get_metadata(str(output_path))["streams"]
    ]
    assert "audio" not in codec_types
    assert "video" in codec_types

    # 音声が無ければ、コンテナ全体の長さ(format.duration)は映像の
    # 長さと一致するはず（音声由来の水増しが起きない）
    video_stream_duration_ms = round(
        float(
            next(
                s
                for s in handler.get_metadata(str(output_path))["streams"]
                if s["codec_type"] == "video"
            )["duration"]
        )
        * 1000
    )
    assert handler.get_duration_ms(str(output_path)) == pytest.approx(
        video_stream_duration_ms, abs=5
    )


def test_export_trimmed_single_gop_has_no_audio_track(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed_single_gop_no_audio.mp4"
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=500, end_ms=1500)

    codec_types = [
        stream["codec_type"] for stream in handler.get_metadata(str(output_path))["streams"]
    ]
    assert "audio" not in codec_types
    assert "video" in codec_types


def test_has_audio_stream_true(handler: VideoHandler) -> None:
    assert handler.has_audio_stream(SAMPLE_MP4) is True


def test_has_audio_stream_false_when_no_audio_track(
    handler: VideoHandler, tmp_path
) -> None:
    import subprocess

    no_audio_path = tmp_path / "no_audio.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            SAMPLE_MP4,
            "-an",
            "-c:v",
            "copy",
            str(no_audio_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    assert handler.has_audio_stream(str(no_audio_path)) is False


def test_get_metadata_raises_on_missing_file(handler: VideoHandler) -> None:
    from app.video_handler import FFmpegError

    with pytest.raises(FFmpegError):
        handler.get_metadata("/nonexistent/path/does_not_exist.mp4")


def test_export_trimmed_embeds_creation_time_smart_cut(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed_with_meta.mp4"
    video_creation_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    # 2.5s -> 7.3s: A/B/C 3分割になるケース（concat経由）
    handler.export_trimmed(
        SAMPLE_MP4,
        str(output_path),
        start_ms=2500,
        end_ms=7300,
        video_creation_time=video_creation_time,
    )

    creation_time_str = handler.get_creation_time(str(output_path))
    assert creation_time_str is not None
    # MP4のcreation_timeタグは秒未満の精度が保持されないため秒単位で比較
    parsed = datetime.datetime.fromisoformat(
        creation_time_str.replace("Z", "+00:00")
    )
    expected = video_creation_time + datetime.timedelta(milliseconds=2500)
    assert parsed.replace(microsecond=0) == expected.replace(microsecond=0)


def test_export_trimmed_embeds_creation_time_single_gop(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed_single_gop_meta.mp4"
    video_creation_time = datetime.datetime(2026, 7, 12, 1, 0, 0, tzinfo=UTC)
    # 0.5s -> 1.5s: 単一GOP内、分割不要ケース
    handler.export_trimmed(
        SAMPLE_MP4,
        str(output_path),
        start_ms=500,
        end_ms=1500,
        video_creation_time=video_creation_time,
    )

    creation_time_str = handler.get_creation_time(str(output_path))
    assert creation_time_str is not None
    parsed = datetime.datetime.fromisoformat(
        creation_time_str.replace("Z", "+00:00")
    )
    expected = video_creation_time + datetime.timedelta(milliseconds=500)
    assert parsed.replace(microsecond=0) == expected.replace(microsecond=0)


def test_export_trimmed_without_creation_time_arg_has_no_metadata(
    handler: VideoHandler, tmp_path
) -> None:
    output_path = tmp_path / "trimmed_no_meta.mp4"
    handler.export_trimmed(SAMPLE_MP4, str(output_path), start_ms=2500, end_ms=7300)
    assert handler.get_creation_time(str(output_path)) is None
