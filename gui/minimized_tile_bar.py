"""Bottom dock for minimized tiles as compact title chips in order."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.neon_theme import (
    NEON_PINK,
    NEON_PURPLE,
    glass_fill_gradient,
    MINIMIZED_CHIP_OVERLAY_ALPHA,
    draw_neon_border,
)
from gui.glass_panel import octagon_path
from gui.typography import primary_style, TEXT_PRIMARY


class MinimizedTileChip(QWidget):
    """Semi-rectangular minimized tile tab: title on top, window controls along the bottom edge."""

    restore_clicked = Signal(str)
    close_clicked = Signal(str)

    def __init__(self, tile_id: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self.tile_id = tile_id
        self.setFixedSize(156, 46)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 8, 4)
        layout.setSpacing(2)

        label = QLabel(title)
        label.setStyleSheet(primary_style() + " font-weight: bold; background: transparent;")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_style = (
            "QPushButton {"
            "  background: rgba(168,85,247,0.25); color: " + TEXT_PRIMARY + ";"
            f"  border: 1px solid {NEON_PURPLE}; border-radius: 3px;"
            "  padding: 0px;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(244,114,182,0.45); border: 1px solid #00f5ff;"
            "}"
        )
        min_btn = QPushButton("—")
        restore = QPushButton("□")
        close = QPushButton("✕")
        for btn in (min_btn, restore, close):
            btn.setFixedSize(22, 18)
            btn.setStyleSheet(btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        restore.clicked.connect(lambda: self.restore_clicked.emit(self.tile_id))
        close.clicked.connect(lambda: self.close_clicked.emit(self.tile_id))
        min_btn.setEnabled(False)
        min_btn.setToolTip("Minimized")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = octagon_path(rect, chamfer=10)
        painter.fillPath(path, glass_fill_gradient(rect, path))
        painter.fillPath(path, QColor(8, 14, 32, MINIMIZED_CHIP_OVERLAY_ALPHA))
        draw_neon_border(painter, path, width=1)


class MinimizedTileBar(QWidget):
    """Horizontal strip anchored to the bottom of the hub."""

    restore_requested = Signal(str)
    close_requested = Signal(str)

    BAR_HEIGHT = 52

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(self.BAR_HEIGHT)
        self._order: list[str] = []
        self._chips: dict[str, MinimizedTileChip] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 2)
        outer.setSpacing(6)
        self._layout = QHBoxLayout()
        self._layout.setSpacing(6)
        self._layout.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._layout)
        outer.addStretch()

    def add_tile(self, tile_id: str, title: str) -> None:
        if tile_id in self._chips:
            return
        self._order.append(tile_id)
        chip = MinimizedTileChip(tile_id, title, self)
        chip.restore_clicked.connect(self.restore_requested)
        chip.close_clicked.connect(self.close_requested)
        self._chips[tile_id] = chip
        self._rebuild()

    def remove_tile(self, tile_id: str) -> None:
        if tile_id not in self._chips:
            return
        chip = self._chips.pop(tile_id)
        chip.deleteLater()
        if tile_id in self._order:
            self._order.remove(tile_id)
        self._rebuild()
        if not self._order:
            self.hide()

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for tile_id in self._order:
            self._layout.addWidget(self._chips[tile_id])
        self.show()
