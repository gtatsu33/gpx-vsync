from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

STEP_DEFINITIONS: list[tuple[float, str]] = [
    (-600.0, "-10分"),
    (-60.0, "-1分"),
    (-10.0, "-10秒"),
    (-1.0, "-1秒"),
    (1.0, "+1秒"),
    (10.0, "+10秒"),
    (60.0, "+1分"),
    (600.0, "+10分"),
]


def format_offset(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    total = abs(round(seconds))
    minutes, secs = divmod(total, 60)
    return f"{sign}{minutes:02d}:{secs:02d}"


class OffsetWidget(QWidget):
    offset_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._offset_seconds = 0.0

        layout = QVBoxLayout(self)

        self.step_buttons: dict[float, QPushButton] = {}
        button_layout = QHBoxLayout()
        for step, label in STEP_DEFINITIONS:
            button = QPushButton(label)
            button.clicked.connect(self._make_adjust_handler(step))
            button_layout.addWidget(button)
            self.step_buttons[step] = button
        layout.addLayout(button_layout)

        self.offset_label = QLabel(format_offset(0.0))
        layout.addWidget(self.offset_label)

        reset_row = QHBoxLayout()
        self.reset_button = QPushButton("リセット")
        self.reset_button.clicked.connect(self.reset)
        reset_row.addWidget(self.reset_button)

        self.force_sync_button = QPushButton("強制同期")
        reset_row.addWidget(self.force_sync_button)
        layout.addLayout(reset_row)

    def _make_adjust_handler(self, step_seconds: float):
        def handler(_checked: bool = False) -> None:
            self._adjust(step_seconds)

        return handler

    def offset_seconds(self) -> float:
        return self._offset_seconds

    def _adjust(self, delta_seconds: float) -> None:
        self._offset_seconds += delta_seconds
        self._update_label()
        self.offset_changed.emit(self._offset_seconds)

    def reset(self) -> None:
        self._offset_seconds = 0.0
        self._update_label()
        self.offset_changed.emit(self._offset_seconds)

    def set_offset(self, seconds: float) -> None:
        """現在値に関わらずoffsetを直接上書きする（強制同期ボタン用）。"""
        self._offset_seconds = seconds
        self._update_label()
        self.offset_changed.emit(self._offset_seconds)

    def _update_label(self) -> None:
        self.offset_label.setText(format_offset(self._offset_seconds))
