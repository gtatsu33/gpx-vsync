from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

_ERROR_RE = re.compile(r"-\s*ERROR\s*-")
_WARNING_RE = re.compile(r"-\s*WARNING\s*-")

POLL_INTERVAL_SEC = 0.2


def is_mapillary_tools_available() -> bool:
    return shutil.which("mapillary_tools") is not None


@dataclass
class ValidationResult:
    ok: bool
    n_images: int
    errors: list[str]
    warnings: list[str]


def validate_export(
    video_path: str,
    video_start_time: str,
    should_cancel: Callable[[], bool] | None = None,
) -> ValidationResult | None:
    """mapillary_tools video_process をアップロードなしで実行し、
    生成された動画から位置情報付き画像相当データが取り出せるかを検証する。
    ネットワーク送信は一切行わない（ローカル処理のみ）。
    should_cancel()がTrueを返した場合はプロセスを中断してNoneを返す。"""
    should_cancel = should_cancel or (lambda: False)

    with tempfile.TemporaryDirectory() as tmp_dir:
        samples_dir = os.path.join(tmp_dir, "samples")
        desc_path = os.path.join(tmp_dir, "desc.json")
        stderr_path = os.path.join(tmp_dir, "stderr.log")

        with open(stderr_path, "wb") as stderr_file:
            process = subprocess.Popen(
                [
                    "mapillary_tools",
                    "video_process",
                    video_path,
                    samples_dir,
                    "--geotag_source",
                    "exif",
                    "--video_start_time",
                    video_start_time,
                    "--video_sample_distance",
                    "3",
                    "--video_sample_interval",
                    "-1",
                    "--filetypes",
                    "image",
                    "--desc_path",
                    desc_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )

            while process.poll() is None:
                if should_cancel():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return None
                time.sleep(POLL_INTERVAL_SEC)

        with open(stderr_path, "r", encoding="utf-8", errors="replace") as f:
            stderr_lines = f.read().splitlines()

        errors = [line for line in stderr_lines if _ERROR_RE.search(line)]
        warnings = [line for line in stderr_lines if _WARNING_RE.search(line)]

        if process.returncode != 0 or not os.path.exists(desc_path):
            if not errors:
                errors = [stderr_lines[-1]] if stderr_lines else ["不明なエラー"]
            return ValidationResult(
                ok=False, n_images=0, errors=errors, warnings=warnings
            )

        with open(desc_path, "r", encoding="utf-8") as f:
            entries = json.load(f)

        return ValidationResult(
            ok=len(entries) > 0,
            n_images=len(entries),
            errors=errors,
            warnings=warnings,
        )


@dataclass
class UploadResult:
    ok: bool
    errors: list[str]
    warnings: list[str]


def upload_export(
    video_path: str,
    video_start_time: str,
    user_name: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    dry_run: bool = False,
) -> UploadResult | None:
    """mapillary_tools video_process_and_upload を実行し、Mapillaryへ
    アップロードする。validate_export()と同じくキャンセル可能な
    ポーリングループ・stderrからのERROR/WARNING行抽出を行う。
    should_cancel()がTrueを返した場合はプロセスを中断してNoneを返す。
    dry_run=Trueの場合、mapillary_tools自身の--dry_runにより実際には
    Mapillaryへ送信せずローカルの一時ディレクトリへのシミュレーションに
    留める（テスト用。本番のアップロードでは使わない）。
    --filetypes imageは、動画からサンプリングした画像だけを処理・
    アップロード対象にする指定（mapillary_tools自身が付けるよう
    警告するため付与。2026-07-18実機確認）。無いと動画ファイル自体も
    別のアップロード対象として扱われる可能性がある。"""
    should_cancel = should_cancel or (lambda: False)

    command = [
        "mapillary_tools",
        "video_process_and_upload",
        video_path,
        "--geotag_source",
        "exif",
        "--video_start_time",
        video_start_time,
        "--video_sample_distance",
        "3",
        "--video_sample_interval",
        "-1",
        "--filetypes",
        "image",
    ]
    if user_name:
        command.extend(["--user_name", user_name])
    if dry_run:
        command.append("--dry_run")

    with tempfile.TemporaryDirectory() as tmp_dir:
        stderr_path = os.path.join(tmp_dir, "stderr.log")

        with open(stderr_path, "wb") as stderr_file:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
            )

            while process.poll() is None:
                if should_cancel():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return None
                time.sleep(POLL_INTERVAL_SEC)

        with open(stderr_path, "r", encoding="utf-8", errors="replace") as f:
            stderr_lines = f.read().splitlines()

    errors = [line for line in stderr_lines if _ERROR_RE.search(line)]
    warnings = [line for line in stderr_lines if _WARNING_RE.search(line)]

    if process.returncode != 0:
        if not errors:
            errors = [stderr_lines[-1]] if stderr_lines else ["不明なエラー"]
        return UploadResult(ok=False, errors=errors, warnings=warnings)

    return UploadResult(ok=True, errors=errors, warnings=warnings)
