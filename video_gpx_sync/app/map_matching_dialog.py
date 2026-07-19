from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app.map_matching_worker import MapMatchingWorker


class MapMatchingDialog(QDialog):
    """マップマッチングの進捗表示・キャンセル用モーダルダイアログ。
    workerの完了シグナルで自動的にaccept()する。"""

    def __init__(self, worker: MapMatchingWorker, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle("マップマッチング中")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("マップマッチング中..."))

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.worker.request_cancel)
        layout.addWidget(self.cancel_button)

        self.worker.progress.connect(self._on_progress)
        self.worker.finished_matching.connect(self._on_finished)

    def _on_progress(self, chunk_idx: int, total_chunks: int) -> None:
        percent = round((chunk_idx / total_chunks) * 100) if total_chunks else 0
        self.progress_bar.setValue(percent)

    def _on_finished(self, _result: object) -> None:
        self.accept()
