"""PyInstaller runtime hook: 同梱したffmpeg/MP4Boxをアプリコードから
`shutil.which("ffmpeg")` 等でそのまま発見できるように、起動直後に
バンドル内binフォルダをPATHの先頭へ追加する。

このファイルはビルド専用であり、video_gpx_syncのアプリ本体コードには
一切依存・変更を加えない。
"""

import os
import sys


def _prepend_bundled_bin_to_path() -> None:
    if not getattr(sys, "frozen", False):
        return

    bundle_dir = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    bin_dir = os.path.join(bundle_dir, "bin")

    if os.path.isdir(bin_dir):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


_prepend_bundled_bin_to_path()
