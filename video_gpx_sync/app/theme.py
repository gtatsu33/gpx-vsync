from __future__ import annotations

import os
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

CHECKMARK_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
    "icons",
    "check.svg",
)


@dataclass(frozen=True)
class Palette:
    accent: str
    accent_hover: str
    accent_bg: str
    accent_border: str
    bg: str
    card_bg: str
    border: str
    text: str
    text_subtle: str
    warn: str
    error: str


LIGHT = Palette(
    accent="#16a34a",
    accent_hover="#15803d",
    accent_bg="rgba(22, 163, 74, 0.10)",
    accent_border="rgba(22, 163, 74, 0.5)",
    bg="#ffffff",
    card_bg="#f7faf8",
    border="#e5e4e7",
    text="#08060d",
    text_subtle="#6b6375",
    warn="#d97706",
    error="#dc2626",
)

DARK = Palette(
    accent="#4ade80",
    accent_hover="#22c55e",
    accent_bg="rgba(74, 222, 128, 0.15)",
    accent_border="rgba(74, 222, 128, 0.5)",
    bg="#16171d",
    card_bg="#1c211d",
    border="#2e303a",
    text="#f3f4f6",
    text_subtle="#9ca3af",
    warn="#fbbf24",
    error="#f87171",
)


def build_stylesheet(p: Palette) -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {p.bg};
        color: {p.text};
        font-size: 13px;
    }}

    QFrame#card {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
        border-radius: 8px;
    }}

    QLabel[subtle="true"] {{
        color: {p.text_subtle};
    }}

    QLabel[state="ok"] {{
        color: {p.accent};
    }}

    QLabel[state="warn"] {{
        color: {p.warn};
    }}

    QLabel[state="error"] {{
        color: {p.error};
    }}

    QPushButton {{
        background-color: transparent;
        color: {p.text};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 6px 14px;
    }}

    QPushButton:hover {{
        background-color: {p.accent_bg};
        border-color: {p.accent_border};
    }}

    QPushButton:disabled {{
        color: {p.text_subtle};
        border-color: {p.border};
    }}

    QPushButton#primaryButton {{
        background-color: {p.accent};
        color: #ffffff;
        border: 1px solid {p.accent};
        font-weight: 600;
    }}

    QPushButton#primaryButton:hover {{
        background-color: {p.accent_hover};
        border-color: {p.accent_hover};
    }}

    QPushButton#primaryButton:disabled {{
        background-color: {p.border};
        border-color: {p.border};
        color: {p.text_subtle};
    }}

    QCheckBox {{
        spacing: 6px;
    }}

    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {p.border};
        border-radius: 3px;
        background-color: {p.bg};
    }}

    QCheckBox::indicator:checked {{
        background-color: {p.accent};
        border-color: {p.accent};
        image: url({CHECKMARK_ICON_PATH});
    }}

    QDoubleSpinBox, QDateTimeEdit, QLineEdit {{
        background-color: {p.bg};
        border: 1px solid {p.border};
        border-radius: 6px;
        padding: 3px 6px;
    }}

    QDoubleSpinBox:focus, QDateTimeEdit:focus, QLineEdit:focus {{
        border-color: {p.accent_border};
    }}

    QSplitter::handle {{
        background-color: transparent;
    }}

    QSplitter::handle:horizontal {{
        width: 12px;
    }}

    QMenuBar::item:selected {{
        background-color: {p.accent_bg};
    }}

    QMenu {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
    }}

    QMenu::item:selected {{
        background-color: {p.accent_bg};
    }}

    QDialogButtonBox QPushButton {{
        min-width: 72px;
    }}
    """


def resolve_palette(app: QApplication) -> Palette:
    """macOSのシステム外観(ライト/ダーク)に応じたパレットを返す。
    offscreenプラットフォーム（テスト実行時）ではQt.ColorScheme.Unknown
    が返るため、その場合はLightにフォールバックする。"""
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT


def apply_theme(app: QApplication) -> None:
    palette = resolve_palette(app)
    app.setStyleSheet(build_stylesheet(palette))
