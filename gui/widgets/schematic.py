"""Decorative optical bench wireframe schematic."""

from __future__ import annotations

from PySide6.QtGui import QPainter, QPen, QColor

from gui.glass_panel import GlassPanel


class SchematicPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Optical Bench")
        self.setMinimumHeight(120)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#00e5ff"))
        pen.setWidth(1)
        painter.setPen(pen)

        w, h = self.width(), self.height()
        y = h // 2 + 10
        painter.drawLine(40, y, 120, y)
        painter.drawEllipse(30, y - 8, 16, 16)
        painter.drawText(20, y - 20, "520 nm")

        painter.drawRect(130, y - 25, 30, 50)
        painter.drawLine(160, y, 220, y - 30)
        painter.drawLine(160, y, 220, y + 30)
        painter.drawRect(220, y - 35, 20, 70)

        painter.setPen(QPen(QColor("#a78bfa")))
        painter.drawLine(240, y, w - 80, y)
        painter.drawRect(w - 70, y - 30, 50, 60)
        painter.drawText(w - 65, y + 5, "Cam")

        painter.setPen(QPen(QColor("#64748b")))
        painter.drawText(130, y + 45, "Stage 1 · placeholder")
        painter.drawText(220, y + 50, "Stage 2 · placeholder")
