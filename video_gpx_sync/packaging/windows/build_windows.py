"""Windows向け再配布パッケージのビルドスクリプト。

video_gpx_sync のアプリコードは一切変更せず、以下を自動化する:
  1. ffmpeg (ffmpeg.exe / ffprobe.exe) をダウンロード
  2. GPAC (MP4Box.exe + 依存DLL) のインストーラをダウンロードし、7-Zipで展開
  3. resources/win/bin/ にバイナリを配置
  4. PyInstaller で onedir 形式のアプリをビルド (packaging/windows/video_gpx_sync.spec)
  5. dist フォルダを zip 化して配布パッケージを作成

前提:
  - 7-Zip (`7z` コマンド) がインストール済みでPATHが通っていること
    https://www.7-zip.org/
  - `pip install -r requirements-dev.txt` 済みであること (pyinstaller を含む)

使い方:
  通常（resources/win/bin/ に既にバイナリを配置済みの場合。デフォルト）:
    python packaging/windows/build_windows.py

  ffmpeg/GPACを再ダウンロードしたい場合:
    python packaging/windows/build_windows.py --download-binaries \
        --gpac-url <GPACインストーラのURL>

  GPACインストーラのURLは https://gpac.io/downloads/gpac-nightly-builds/ から
  現在の安定版Windowsインストーラのリンクをコピーして指定すること
  (配布URLは頻繁に変わるため、このスクリプトには固定していない)。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VIDEO_GPX_SYNC_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(VIDEO_GPX_SYNC_ROOT))
from app import APP_VERSION  # noqa: E402

BUNDLED_BIN_DIR = VIDEO_GPX_SYNC_ROOT / "resources" / "win" / "bin"
BUILD_CACHE_DIR = VIDEO_GPX_SYNC_ROOT / ".build_cache" / "win"
SPEC_FILE = Path(__file__).resolve().parent / "video_gpx_sync.spec"
DIST_DIR = VIDEO_GPX_SYNC_ROOT / "dist"
WORK_DIR = VIDEO_GPX_SYNC_ROOT / "build"
ICON_SOURCE_PNG = VIDEO_GPX_SYNC_ROOT.parent / "gpx-vsync_512x512.png"
ICON_ICO_PATH = Path(__file__).resolve().parent / "icon.ico"

DEFAULT_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

THIRD_PARTY_LICENSES = """\
このアプリケーションには以下のサードパーティ製ソフトウェアが同梱されています。

- FFmpeg (ffmpeg.exe / ffprobe.exe)
  https://ffmpeg.org/
  ライセンス: LGPL/GPL (ビルド構成により異なる。使用ビルドの LICENSE を参照)

- GPAC / MP4Box
  https://gpac.io/
  ライセンス: GNU LGPL / GPL
  ソースコード: https://github.com/gpac/gpac
"""


def check_tool_available(command: str, hint: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"エラー: `{command}` が見つかりません。{hint}")


def download(url: str, dest: Path) -> Path:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"ダウンロード中: {url}")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def fetch_ffmpeg(ffmpeg_url: str) -> None:
    zip_path = BUILD_CACHE_DIR / "ffmpeg.zip"
    if not zip_path.exists():
        download(ffmpeg_url, zip_path)

    extract_dir = BUILD_CACHE_DIR / "ffmpeg_extracted"
    if not extract_dir.exists():
        print("ffmpeg zipを展開中...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

    ffmpeg_exe = next(extract_dir.glob("**/bin/ffmpeg.exe"), None)
    ffprobe_exe = next(extract_dir.glob("**/bin/ffprobe.exe"), None)
    if ffmpeg_exe is None or ffprobe_exe is None:
        raise SystemExit(
            "エラー: 展開したffmpeg zip内に ffmpeg.exe / ffprobe.exe が見つかりません。"
            " --ffmpeg-url で指定したビルドの構成を確認してください。"
        )

    BUNDLED_BIN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ffmpeg_exe, BUNDLED_BIN_DIR / "ffmpeg.exe")
    shutil.copy2(ffprobe_exe, BUNDLED_BIN_DIR / "ffprobe.exe")
    print(f"配置完了: {BUNDLED_BIN_DIR / 'ffmpeg.exe'}, {BUNDLED_BIN_DIR / 'ffprobe.exe'}")


def fetch_gpac(gpac_url: str) -> None:
    check_tool_available("7z", "https://www.7-zip.org/ からインストールしてください。")

    installer_path = BUILD_CACHE_DIR / "gpac_installer.exe"
    if not installer_path.exists():
        download(gpac_url, installer_path)

    extract_dir = BUILD_CACHE_DIR / "gpac_extracted"
    if not extract_dir.exists():
        print("GPACインストーラを7-Zipで展開中...")
        extract_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["7z", "x", str(installer_path), f"-o{extract_dir}", "-y"],
            check=True,
        )

    mp4box_exe = next(extract_dir.glob("**/MP4Box.exe"), None)
    if mp4box_exe is None:
        raise SystemExit(
            "エラー: 展開したGPACインストーラ内に MP4Box.exe が見つかりません。"
            " インストーラの内部構成が想定と異なる可能性があります。"
            f" 展開先を確認してください: {extract_dir}"
        )

    BUNDLED_BIN_DIR.mkdir(parents=True, exist_ok=True)
    mp4box_dir = mp4box_exe.parent
    copied = []
    for pattern in ("MP4Box.exe", "*.dll"):
        for src in mp4box_dir.glob(pattern):
            dest = BUNDLED_BIN_DIR / src.name
            shutil.copy2(src, dest)
            copied.append(dest.name)
    print(f"配置完了 ({mp4box_dir} から): {', '.join(sorted(copied))}")


def build_icon() -> None:
    from PIL import Image

    if not ICON_SOURCE_PNG.exists():
        raise SystemExit(f"エラー: アイコン元画像が見つかりません: {ICON_SOURCE_PNG}")

    print(f"exeアイコンを生成中: {ICON_ICO_PATH}")
    image = Image.open(ICON_SOURCE_PNG).convert("RGBA")
    image.save(
        ICON_ICO_PATH,
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def run_pyinstaller() -> None:
    check_tool_available(
        "pyinstaller", "`pip install -r requirements-dev.txt` を実行してください。"
    )
    print("PyInstallerでビルド中...")
    subprocess.run(
        [
            "pyinstaller",
            str(SPEC_FILE),
            "--noconfirm",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(WORK_DIR),
        ],
        check=True,
        cwd=VIDEO_GPX_SYNC_ROOT,
    )


def make_zip_package() -> Path:
    app_dist_dir = DIST_DIR / "gpx-vsync"
    if not app_dist_dir.is_dir():
        raise SystemExit(f"エラー: PyInstallerの出力が見つかりません: {app_dist_dir}")

    (app_dist_dir / "THIRD_PARTY_LICENSES.txt").write_text(
        THIRD_PARTY_LICENSES, encoding="utf-8"
    )

    package_path = DIST_DIR / f"gpx-vsync-win-x64-v{APP_VERSION}.zip"
    if package_path.exists():
        package_path.unlink()

    print(f"配布パッケージを作成中: {package_path}")
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in app_dist_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(app_dist_dir.parent))

    return package_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-url", default=DEFAULT_FFMPEG_URL)
    parser.add_argument(
        "--gpac-url",
        help="https://gpac.io/downloads/gpac-nightly-builds/ から取得したインストーラURL"
        " (--download-binaries指定時のみ必要)",
    )
    parser.add_argument(
        "--download-binaries",
        action="store_true",
        help="ffmpeg/GPACを再ダウンロードする。指定しない場合"
        "（デフォルト）はresources/win/bin/に既にあるバイナリをそのまま使う",
    )
    args = parser.parse_args()

    if args.download_binaries:
        if not args.gpac_url:
            parser.error("--gpac-url is required when --download-binaries is given")
        BUILD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fetch_ffmpeg(args.ffmpeg_url)
        fetch_gpac(args.gpac_url)
    else:
        print("ダウンロードをスキップします（resources/win/bin/ の既存バイナリを使用）。")

    build_icon()
    run_pyinstaller()
    package_path = make_zip_package()
    print(f"\n完了: {package_path}")


if __name__ == "__main__":
    main()
