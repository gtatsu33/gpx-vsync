"""macOS向け再配布パッケージのビルドスクリプト。

video_gpx_sync のアプリコードは一切変更せず、以下を自動化する:
  1. ffmpeg / ffprobe (evermeet.cx の静的ビルド) をダウンロード
  2. GPAC (MP4Box + 依存dylib) のインストーラ(.pkg)をダウンロードし、
     pkgutilで展開
  3. resources/mac/bin/ にバイナリを配置
  4. PyInstaller で onedir + .app バンドルをビルド (packaging/mac/video_gpx_sync.spec)
  5. .app 全体にアドホックコード署名 (codesign --deep -s -) を行う
     （Apple Siliconでは無署名バイナリを実行できないため必須）
  6. dist フォルダを zip 化して配布パッケージを作成

前提:
  - macOS標準ツール（pkgutil, codesign, ditto）が使えること
    （追加インストールは不要）
  - `pip install -r requirements-dev.txt` 済みであること (pyinstaller を含む)

使い方:
  通常（resources/mac/bin/ に既にバイナリを配置済みの場合。デフォルト）:
    python packaging/mac/build_mac.py

  ffmpeg/GPACを再ダウンロードしたい場合:
    python packaging/mac/build_mac.py --download-binaries \
        --gpac-url <GPACインストーラ(.pkg)のURL>

  GPACインストーラのURLは https://gpac.io/downloads/gpac-nightly-builds/ から
  現在のmacOS向けインストーラ(.pkg)のリンクをコピーして指定すること
  (配布URLは頻繁に変わるため、このスクリプトには固定していない)。

  注記: ffmpeg/ffprobe・MP4Box(GPAC)ともmacOS公式配布はx86_64ビルドのみで
  arm64ネイティブ版が存在しない。Apple SiliconではRosetta 2経由で動作する
  (Rosetta未インストール環境では初回実行時にmacOSが自動インストールを促す)。
  アプリ本体(Python/PySide6)はビルドを実行したMacのアーキテクチャで
  ネイティブビルドされる。
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

BUNDLED_BIN_DIR = VIDEO_GPX_SYNC_ROOT / "resources" / "mac" / "bin"
BUILD_CACHE_DIR = VIDEO_GPX_SYNC_ROOT / ".build_cache" / "mac"
SPEC_FILE = Path(__file__).resolve().parent / "video_gpx_sync.spec"
DIST_DIR = VIDEO_GPX_SYNC_ROOT / "dist"
WORK_DIR = VIDEO_GPX_SYNC_ROOT / "build"
ICON_SOURCE_PNG = VIDEO_GPX_SYNC_ROOT.parent / "gpx-vsync_512x512.png"
ICON_ICNS_PATH = Path(__file__).resolve().parent / "icon.icns"

DEFAULT_FFMPEG_URL = "https://evermeet.cx/ffmpeg/getrelease/zip"
DEFAULT_FFPROBE_URL = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"

THIRD_PARTY_LICENSES = """\
このアプリケーションには以下のサードパーティ製ソフトウェアが同梱されています。

- FFmpeg (ffmpeg / ffprobe)
  https://ffmpeg.org/
  ライセンス: LGPL/GPL (ビルド構成により異なる。使用ビルドの LICENSE を参照)
  配布元: https://evermeet.cx/ffmpeg/

- GPAC / MP4Box
  https://gpac.io/
  ライセンス: GNU LGPL / GPL
  ソースコード: https://github.com/gpac/gpac
"""

README_MACOS = """\
gpx-vsync macOS版について
==========================

■ 初回起動時に「開発元が未確認のため開けません」と表示される場合
  このアプリはApple Developer IDでの正式署名・公証(notarize)を行って
  いません。Finderで GPX-VSync.app を右クリック（またはControl+クリック）
  し、「開く」を選択してください。確認ダイアログが出るので「開く」を
  選ぶと以降は通常どおり起動できます。

■ 同梱しているffmpeg / MP4Box(GPAC)について
  現時点でどちらもmacOS公式配布はIntel(x86_64)ビルドのみで、Apple
  Silicon(M1/M2/M3/M4等)ネイティブ版が提供されていません。Apple
  Silicon搭載Macでは、これらのツールの実行にRosetta 2が必要です。
  未インストールの場合、初回実行時にmacOSがインストールを促す
  ダイアログを表示します（要インターネット接続）。アプリ本体
  (gpx-vsync自体)はビルドを行ったMacのアーキテクチャでネイティブに
  動作します。
"""


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


def fetch_ffmpeg(ffmpeg_url: str, ffprobe_url: str) -> None:
    BUNDLED_BIN_DIR.mkdir(parents=True, exist_ok=True)

    for label, url, binary_name in (
        ("ffmpeg", ffmpeg_url, "ffmpeg"),
        ("ffprobe", ffprobe_url, "ffprobe"),
    ):
        zip_path = BUILD_CACHE_DIR / f"{label}.zip"
        if not zip_path.exists():
            download(url, zip_path)

        extract_dir = BUILD_CACHE_DIR / f"{label}_extracted"
        if not extract_dir.exists():
            print(f"{label} zipを展開中...")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(extract_dir)

        binary_path = extract_dir / binary_name
        if not binary_path.exists():
            raise SystemExit(
                f"エラー: 展開した{label} zip内に {binary_name} が見つかりません。"
                f" 展開先を確認してください: {extract_dir}"
            )

        dest = BUNDLED_BIN_DIR / binary_name
        shutil.copy2(binary_path, dest)
        dest.chmod(0o755)
        print(f"配置完了: {dest}")


def fetch_gpac(gpac_url: str) -> None:
    pkg_path = BUILD_CACHE_DIR / "gpac_installer.pkg"
    if not pkg_path.exists():
        download(gpac_url, pkg_path)

    extract_dir = BUILD_CACHE_DIR / "gpac_extracted"
    if not extract_dir.exists():
        print("GPACインストーラ(.pkg)をpkgutilで展開中...")
        subprocess.run(
            ["pkgutil", "--expand-full", str(pkg_path), str(extract_dir)],
            check=True,
        )

    app_bundle = next(extract_dir.glob("**/GPAC.app"), None)
    if app_bundle is None:
        raise SystemExit(
            "エラー: 展開したGPACインストーラ内に GPAC.app が見つかりません。"
            " インストーラの内部構成が想定と異なる可能性があります。"
            f" 展開先を確認してください: {extract_dir}"
        )

    macos_dir = app_bundle / "Contents" / "MacOS"
    mp4box_bin = macos_dir / "MP4Box"
    lib_dir = macos_dir / "lib"
    if not mp4box_bin.exists() or not lib_dir.is_dir():
        raise SystemExit(
            f"エラー: {app_bundle} 内に MP4Box または lib/ が見つかりません。"
        )

    BUNDLED_BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest_mp4box = BUNDLED_BIN_DIR / "MP4Box"
    shutil.copy2(mp4box_bin, dest_mp4box)
    dest_mp4box.chmod(0o755)

    dest_lib_dir = BUNDLED_BIN_DIR / "lib"
    dest_lib_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for dylib in lib_dir.glob("*.dylib"):
        dest = dest_lib_dir / dylib.name
        shutil.copy2(dylib, dest)
        copied.append(dest.name)
    print(f"配置完了: {dest_mp4box}, lib/ 配下に{len(copied)}個の.dylib")


def build_icon() -> None:
    from PIL import Image

    if not ICON_SOURCE_PNG.exists():
        raise SystemExit(f"エラー: アイコン元画像が見つかりません: {ICON_SOURCE_PNG}")

    print(f"アプリアイコンを生成中: {ICON_ICNS_PATH}")
    image = Image.open(ICON_SOURCE_PNG).convert("RGBA")
    image.save(ICON_ICNS_PATH)


def run_pyinstaller() -> None:
    if shutil.which("pyinstaller") is None:
        raise SystemExit(
            "エラー: `pyinstaller` が見つかりません。"
            "`pip install -r requirements-dev.txt` を実行してください。"
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


def codesign_app(app_path: Path) -> None:
    print(f"アドホックコード署名を実行中: {app_path}")
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app_path)],
        check=True,
    )


def make_zip_package(app_path: Path) -> Path:
    if not app_path.is_dir():
        raise SystemExit(f"エラー: PyInstallerの出力が見つかりません: {app_path}")

    package_path = DIST_DIR / f"gpx-vsync-mac-v{APP_VERSION}.zip"
    if package_path.exists():
        package_path.unlink()

    staging_dir = WORK_DIR / "mac_zip_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    # symlink等のmacOS固有の属性を保ったままコピーするためdittoを使う
    subprocess.run(
        ["ditto", str(app_path), str(staging_dir / app_path.name)],
        check=True,
    )
    (staging_dir / "THIRD_PARTY_LICENSES.txt").write_text(
        THIRD_PARTY_LICENSES, encoding="utf-8"
    )
    (staging_dir / "README_macOS.txt").write_text(README_MACOS, encoding="utf-8")

    print(f"配布パッケージを作成中: {package_path}")
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in staging_dir.rglob("*"):
            if file_path.is_file() or file_path.is_symlink():
                zf.write(file_path, file_path.relative_to(staging_dir))

    shutil.rmtree(staging_dir)
    return package_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg-url", default=DEFAULT_FFMPEG_URL)
    parser.add_argument("--ffprobe-url", default=DEFAULT_FFPROBE_URL)
    parser.add_argument(
        "--gpac-url",
        help="https://gpac.io/downloads/gpac-nightly-builds/ から取得したmacOS向け"
        "インストーラ(.pkg)のURL (--download-binaries指定時のみ必要)",
    )
    parser.add_argument(
        "--download-binaries",
        action="store_true",
        help="ffmpeg/GPACを再ダウンロードする。指定しない場合"
        "（デフォルト）はresources/mac/bin/に既にあるバイナリをそのまま使う",
    )
    args = parser.parse_args()

    if args.download_binaries:
        if not args.gpac_url:
            parser.error("--gpac-url is required when --download-binaries is given")
        BUILD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fetch_ffmpeg(args.ffmpeg_url, args.ffprobe_url)
        fetch_gpac(args.gpac_url)
    else:
        print("ダウンロードをスキップします（resources/mac/bin/ の既存バイナリを使用）。")

    build_icon()
    run_pyinstaller()

    app_path = DIST_DIR / "GPX-VSync.app"
    codesign_app(app_path)
    package_path = make_zip_package(app_path)
    print(f"\n完了: {package_path}")


if __name__ == "__main__":
    main()
