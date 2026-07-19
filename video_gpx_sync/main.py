import shutil
import sys

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

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
