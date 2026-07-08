"""Translucent snap-preview shown while dragging the main window near a screen edge.

Mirrors the familiar Windows Aero Snap hint: drag the title bar to the top of a
monitor to maximize there, or to its left/right edge to dock into that half.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from gui.neon_theme import COLOR_CYAN


class SnapPreviewOverlay(QWidget):
    """Frameless, click-through rectangle hinting where the window will land."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.hide()

    def show_at(self, rect: QRect) -> None:
        self.setGeometry(rect)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(6, 6, -6, -6)
        fill = QColor(COLOR_CYAN.red(), COLOR_CYAN.green(), COLOR_CYAN.blue(), 55)
        border = QPen(QColor(COLOR_CYAN.red(), COLOR_CYAN.green(), COLOR_CYAN.blue(), 210), 2.5)
        painter.setBrush(fill)
        painter.setPen(border)
        painter.drawRoundedRect(r, 12, 12)
