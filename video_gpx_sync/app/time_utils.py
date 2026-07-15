from __future__ import annotations


def playback_ms_to_real_ms(ms: int, time_scale: float) -> int:
    """動画の再生位置(ms)を実世界での経過時間(ms)に変換する。
    time_scale は再生1msあたりの実世界ms数（通常動画は1.0、
    タイムラプス動画は interval_sec * fps）。"""
    return round(ms * time_scale)


def real_ms_to_playback_ms(real_ms: int, time_scale: float) -> int:
    """playback_ms_to_real_ms()の逆変換。実世界での経過時間(ms)を、
    動画自身の圧縮された(ネイティブな)再生タイムライン上の位置(ms)に
    変換する。CAMMトラックのサンプルを動画の実尺内の正しい位置に
    配置するために使う（15章）。"""
    return round(real_ms / time_scale)
