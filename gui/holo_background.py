"""Translucent hub backdrop where tiles sit; the hex rail is a separate overlay."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QRadialGradient, QPainter, QPen, QRegion, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from config import PANEL_CORNER_RADIUS_PX
from gui.glass_panel import hub_workspace_path
from gui.neon_theme import COLOR_CYAN, COLOR_PINK, COLOR_PURPLE, workspace_backdrop_brush
from gui.ui_scale import px
from gui.workspace_grid import (
    GRID_MAJOR_ALPHA,
    GRID_MAJOR_EVERY,
    GRID_MINOR_ALPHA,
    workspace_origin_x,
)


class HoloBackground(QWidget):
    """Semi-transparent gradient mesh; desktop subtly shows through the hub."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _workspace_bounds(self) -> QRectF:
        """Paintable workspace aligned with tile layout (right of hex rail)."""
        ox = workspace_origin_x()
        return QRectF(ox, 0, max(1.0, self.width() - ox), float(self.height()))

    def _workspace_path(self) -> QPainterPath:
        bounds = self._workspace_bounds()
        chamfer = px(PANEL_CORNER_RADIUS_PX)
        return hub_workspace_path(bounds, chamfer=chamfer)

    def _update_shape_mask(self) -> None:
        path = self._workspace_path()
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_shape_mask()

    def _paint_grid(self, painter: QPainter, bounds: QRectF) -> None:
        ox = int(bounds.x())
        w = int(bounds.x() + bounds.width())
        h = int(bounds.height())
        from gui.ui_scale import grid_cell_px

        cell = grid_cell_px()
        bw = int(bounds.width())

        for i in range(0, bw // cell + 2):
            x = ox + i * cell
            if x > w:
                break
            is_major = (i % GRID_MAJOR_EVERY) == 0
            alpha = GRID_MAJOR_ALPHA if is_major else GRID_MINOR_ALPHA
            painter.setPen(QPen(QColor(COLOR_CYAN.red(), COLOR_CYAN.green(), COLOR_CYAN.blue(), alpha), 1))
            painter.drawLine(x, 0, x, h)

        for j in range(0, h // cell + 2):
            y = j * cell
            if y > h:
                break
            is_major = (j % GRID_MAJOR_EVERY) == 0
            alpha = GRID_MAJOR_ALPHA if is_major else GRID_MINOR_ALPHA
            painter.setPen(QPen(QColor(COLOR_PINK.red(), COLOR_PINK.green(), COLOR_PINK.blue(), alpha), 1))
            painter.drawLine(ox, y, w, y)

        painter.setPen(
            QPen(QColor(COLOR_CYAN.red(), COLOR_CYAN.green(), COLOR_CYAN.blue(), GRID_MAJOR_ALPHA + 12), 1)
        )
        painter.drawLine(ox, 0, ox, h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bounds = self._workspace_bounds()
        path = self._workspace_path()
        painter.setClipPath(path)

        bx, by = bounds.x(), bounds.y()
        bw, bh = bounds.width(), bounds.height()

        painter.fillPath(path, workspace_backdrop_brush(bounds))

        bloom_r = max(180.0, min(bw, bh) * 0.38)
        for cx_frac, cy_frac, color in (
            (0.2, 0.25, COLOR_PURPLE),
            (0.8, 0.3, COLOR_PINK),
            (0.5, 0.75, COLOR_CYAN),
        ):
            bloom = QRadialGradient(bx + bw * cx_frac, by + bh * cy_frac, bloom_r)
            bloom.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 10))
            bloom.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.fillPath(path, QBrush(bloom))

        self._paint_grid(painter, bounds)
