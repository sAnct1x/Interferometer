"""Left hub rail: full-height Pleiad proximity point-cloud network."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from config import PANEL_CORNER_RADIUS_PX
from gui.pleiad_network import PleiadNetwork
from gui.ui_scale import get_scale, px


class HexRailOverlay(QWidget):
    """Fixed-width left rail; mouse-transparent so tiles stay interactive."""

    WIDTH = 120

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._network = PleiadNetwork(node_count=72)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)

    def _tick(self) -> None:
        self._network.step(dt=1.0, spin=0.003)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        margin = px(2, get_scale())
        radius = px(PANEL_CORNER_RADIUS_PX, get_scale())
        clip = QPainterPath()
        clip.addRoundedRect(
            QRectF(margin, margin, max(1.0, self.width() - 2 * margin), max(1.0, self.height() - 2 * margin)),
            radius,
            radius,
        )
        painter.setClipPath(clip)
        self._network.paint(painter, self.width(), self.height())

