import os
import shutil
import sys

# QtMultimediaのデフォルト(ffmpeg)バックエンドはmacOSで1シークあたり約300ms
# かかり操作感が重いことを実測で確認したため、macOSではネイティブの
# darwinバックエンド(AVFoundation)に切り替える（実測で約4倍高速化、
# 約70ms/シーク）。QMediaPlayer等の初回使用より前に設定する必要が
# あるため、Qtのインポートより前に行う。Windows/Linuxは変更しない。
if sys.platform == "darwin":
    os.environ.setdefault("QT_MEDIA_BACKEND", "darwin")

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

APP_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app_icon.png")

# QWebEngineView と QVideoWidget を同一ウィンドウで併用するため、
# QApplication生成前にOpenGLコンテキスト共有を有効化しておく。
QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

from app.main_window import MainWindow  # noqa: E402 - 上記属性設定より後に読み込む必要がある
from app.theme import apply_theme  # noqa: E402


def check_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def check_mp4box_available() -> bool:
    return shutil.which("MP4Box") is not None


def show_ffmpeg_missing_dialog() -> None:
    QMessageBox.critical(
        None,
        "FFmpegが見つかりません",
        "動画の書き出しにはFFmpegが必要です。\n\n"
        "以下のコマンドでインストールしてください:\n"
        "  brew install ffmpeg\n\n"
        "インストール後、アプリを再起動してください。",
    )


def show_mp4box_missing_dialog() -> None:
    QMessageBox.critical(
        None,
        "MP4Box(GPAC)が見つかりません",
        "動画へのGPSトラック埋め込みにはMP4Box(GPAC)が必要です。\n\n"
        "以下のコマンドでインストールしてください:\n"
        "  brew install gpac\n\n"
        "インストール後、アプリを再起動してください。",
    )


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(APP_ICON_PATH))
    apply_theme(app)

    if not check_ffmpeg_available():
        show_ffmpeg_missing_dialog()
        return 1

    if not check_mp4box_available():
        show_mp4box_missing_dialog()
        return 1

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
