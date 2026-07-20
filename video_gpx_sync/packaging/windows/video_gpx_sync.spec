# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for gpx-vsync (Windows, onedir)
#
# 実行例:
#   pyinstaller packaging/windows/video_gpx_sync.spec --noconfirm
#
# 前提: packaging/windows/build_windows.py により
#   resources/win/bin/ に ffmpeg.exe / ffprobe.exe / MP4Box.exe (+依存DLL) が
#   配置済みであること。

import glob
import os

import PySide6

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
BUNDLED_BIN_DIR = os.path.join(ROOT, "resources", "win", "bin")

bundled_bin_datas = [
    (path, "bin")
    for path in glob.glob(os.path.join(BUNDLED_BIN_DIR, "*"))
    if os.path.isfile(path)
]

# QtLocationのPlugin{name: "osm"}は実行時に文字列名で動的ロードされるため
# PyInstallerの自動解析では検出されない。明示的に同梱する。
PYSIDE6_DIR = os.path.dirname(PySide6.__file__)
GEOSERVICES_DIR = os.path.join(PYSIDE6_DIR, "plugins", "geoservices")
geoservices_datas = [
    (path, "PySide6/plugins/geoservices")
    for path in glob.glob(os.path.join(GEOSERVICES_DIR, "*.dll"))
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
    icon=os.path.join(SPECPATH, "icon.ico"),
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
