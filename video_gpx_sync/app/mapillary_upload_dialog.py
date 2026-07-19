from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app.mapillary_upload_worker import MapillaryUploadWorker


class MapillaryUploadDialog(QDialog):
    """Mapillaryへのアップロード（mapillary_tools video_process_and_upload）
    実行中のモーダルダイアログ。MapillaryValidationDialogと同じく、細かい
    進捗が取得できないため不定形（busy）プログレスバーを使う。workerの
    完了シグナルで自動的にaccept()する。キャンセルしても
    mapillary_tools側でアップロード再開可能なため、データが失われる
    心配はない旨を案内する。"""

    def __init__(self, worker: MapillaryUploadWorker, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle("Mapillaryへアップロード中")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("mapillary_toolsでMapillaryへアップロード中..."))
        layout.addWidget(
            QLabel("キャンセルしても中断した時点までは再開可能です。")
        )

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不定形（busy）表示
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.worker.request_cancel)
        layout.addWidget(self.cancel_button)

        self.worker.finished_upload.connect(self._on_finished)

    def _on_finished(self, _result: object) -> None:
        self.accept()
