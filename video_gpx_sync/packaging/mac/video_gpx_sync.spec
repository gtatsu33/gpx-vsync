# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for gpx-vsync (macOS, onedir + .app bundle)
#
# 実行例:
#   pyinstaller packaging/mac/video_gpx_sync.spec --noconfirm
#
# 前提: packaging/mac/build_mac.py により
#   resources/mac/bin/ に ffmpeg / ffprobe / MP4Box (+lib/*.dylib) が
#   配置済み、packaging/mac/icon.icns が生成済みであること。

import glob
import os
import sys

import PySide6

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
sys.path.insert(0, ROOT)
from app import APP_VERSION  # noqa: E402
BUNDLED_BIN_DIR = os.path.join(ROOT, "resources", "mac", "bin")

bundled_bin_datas = [
    (path, "bin")
    for path in glob.glob(os.path.join(BUNDLED_BIN_DIR, "*"))
    if os.path.isfile(path)
]
bundled_bin_datas += [
    (path, "bin/lib")
    for path in glob.glob(os.path.join(BUNDLED_BIN_DIR, "lib", "*"))
    if os.path.isfile(path)
]

# QtLocationのPlugin{name: "osm"}は実行時に文字列名で動的ロードされるため
# PyInstallerの自動解析では検出されない。明示的に同梱する
# (macOS版PySide6 wheelはWindows版と異なりQt/plugins配下にプラグインを持つ)。
PYSIDE6_DIR = os.path.dirname(PySide6.__file__)
GEOSERVICES_DIR = os.path.join(PYSIDE6_DIR, "Qt", "plugins", "geoservices")
geoservices_datas = [
    (path, "PySide6/Qt/plugins/geoservices")
    for path in glob.glob(os.path.join(GEOSERVICES_DIR, "*.dylib"))
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=bundled_bin_datas + geoservices_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, "runtime_hook.py")],
    excludes=[],
    noarchive=False,
)

a.datas += Tree(os.path.join(ROOT, "assets"), prefix="assets")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="gpx-vsync",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="gpx-vsync",
)

app = BUNDLE(
    coll,
    name="GPX-VSync.app",
    icon=os.path.join(SPECPATH, "icon.icns"),
    bundle_identifier="com.gtatsu33.gpx-vsync",
    version=APP_VERSION,
    info_plist={
        "CFBundleDisplayName": "gpx-vsync",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
