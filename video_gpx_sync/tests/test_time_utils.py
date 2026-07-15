import pytest

from app.time_utils import playback_ms_to_real_ms


def test_normal_speed_is_identity() -> None:
    assert playback_ms_to_real_ms(1000, 1.0) == 1000


def test_timelapse_scale_multiplies() -> None:
    # 0.5秒間隔・29.97fps相当のtime_scale
    time_scale = 0.5 * 29.97
    assert playback_ms_to_real_ms(1000, time_scale) == pytest.approx(
        14985, abs=1
    )


def test_rounds_to_nearest_int() -> None:
    assert playback_ms_to_real_ms(3, 1.4) == 4  # 4.2 -> 4
