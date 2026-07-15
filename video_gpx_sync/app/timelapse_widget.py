from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

DEFAULT_INTERVAL_SEC = 0.5


class TimelapseWidget(QWidget):
    timelapse_changed = pyqtSignal(bool, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        self.checkbox = QCheckBox("タイムラプス動画")
        layout.addWidget(self.checkbox)

        layout.addWidget(QLabel("間隔(秒):"))
        self.interval_spinbox = QDoubleSpinBox()
        self.interval_spinbox.setRange(0.01, 3600.0)
        self.interval_spinbox.setDecimals(2)
        self.interval_spinbox.setSingleStep(0.5)
        self.interval_spinbox.setValue(DEFAULT_INTERVAL_SEC)
        self.interval_spinbox.setEnabled(False)
        layout.addWidget(self.interval_spinbox)
        layout.addStretch(1)

        self.checkbox.toggled.connect(self._on_toggled)
        self.interval_spinbox.valueChanged.connect(self._on_value_changed)

    def _on_toggled(self, checked: bool) -> None:
        self.interval_spinbox.setEnabled(checked)
        self.timelapse_changed.emit(checked, self.interval_spinbox.value())

    def _on_value_changed(self, value: float) -> None:
        if self.checkbox.isChecked():
            self.timelapse_changed.emit(True, value)

    def timelapse_enabled(self) -> bool:
        return self.checkbox.isChecked()

    def interval_seconds(self) -> float:
        return self.interval_spinbox.value()

    def reset(self) -> None:
        """動画差し替え時に呼び出し、タイムラプス設定を初期状態(無効)に戻す。
        チェックボックスと間隔入力を個別に更新すると中間状態のシグナルが
        余分に発火するため、シグナルを一時的に止めてから最終状態を1回だけ
        通知する。"""
        self.checkbox.blockSignals(True)
        self.interval_spinbox.blockSignals(True)
        try:
            self.checkbox.setChecked(False)
            self.interval_spinbox.setValue(DEFAULT_INTERVAL_SEC)
            self.interval_spinbox.setEnabled(False)
        finally:
            self.checkbox.blockSignals(False)
            self.interval_spinbox.blockSignals(False)
        self.timelapse_changed.emit(False, DEFAULT_INTERVAL_SEC)
