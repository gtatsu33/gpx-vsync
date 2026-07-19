from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app.mapillary_validation_worker import MapillaryValidationWorker


class MapillaryValidationDialog(QDialog):
    """出力後ローカル検証（mapillary_tools video_process）の実行中
    モーダルダイアログ。細かい進捗が取得できないため不定形（busy）
    プログレスバーを使う。workerの完了シグナルで自動的にaccept()する。"""

    def __init__(self, worker: MapillaryValidationWorker, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle("ローカル検証中")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("mapillary_toolsでローカル検証中..."))

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不定形（busy）表示
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.worker.request_cancel)
        layout.addWidget(self.cancel_button)

        self.worker.finished_validation.connect(self._on_finished)

    def _on_finished(self, _result: object) -> None:
        self.accept()
