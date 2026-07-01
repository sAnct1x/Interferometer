"""Async splash screen shown while the app loads hardware and config."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QColor, QPainter, QPen, QPainterPath, QRegion
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from config import APP_BADGE, APP_TITLE, ICONS_DIR
from gui.glass_panel import smooth_viewport_path
from gui.neon_theme import (
    NEON_CYAN,
    NEON_PINK,
    chrome_bar_dark_overlay,
    draw_multicolor_glow,
    draw_neon_border,
    glass_fill_gradient,
    tile_dark_overlay,
    workspace_backdrop_brush,
)
from gui.typography import body_px, hint_style, primary_style, TEXT_MUTED, TEXT_PRIMARY, TEXT_TITLE, title_px


_CORNER_RADIUS = 18.0
_CONTENT_MARGIN = 40


def _progress_stylesheet() -> str:
    return (
        f"QProgressBar {{"
        f"  background: rgba(8,14,32,0.72);"
        f"  border: 1px solid rgba(148,163,184,0.35);"
        f"  border-radius: 6px;"
        f"  min-height: {max(8, body_px() - 2)}px;"
        f"  max-height: {max(8, body_px() - 2)}px;"
        "  text-align: center;"
        f"  color: {TEXT_MUTED};"
        f"  font-size: {body_px()}px;"
        "  font-family: Consolas;"
        "}"
        "QProgressBar::chunk {"
        f"  background: qlineargradient("
        "x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {NEON_PINK}, stop:0.55 #a855f7, stop:1 {NEON_CYAN});"
        "  border-radius: 5px;"
        "}"
    )

class SplashScreen(QWidget):
    finished = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setFixedSize(520, 320)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_CONTENT_MARGIN, _CONTENT_MARGIN, _CONTENT_MARGIN, _CONTENT_MARGIN)
        layout.setSpacing(10)

        self._badge = QLabel(APP_BADGE)
        self._badge.setAlignment(Qt.AlignCenter)
        badge_px = max(28, title_px() * 2)
        self._badge.setFont(QFont("Consolas", badge_px, QFont.Weight.Bold))
        self._badge.setStyleSheet(
            f"color: {TEXT_TITLE}; font-weight: bold; "
            "background: rgba(168,85,247,0.25); "
            f"border: 1px solid {NEON_PINK}; "
            "border-radius: 8px; padding: 6px 18px;"
        )

        self._title = QLabel(APP_TITLE)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setFont(QFont("Segoe UI", title_px(), QFont.Weight.Bold))
        self._title.setStyleSheet(primary_style() + " font-weight: bold; background: transparent;")

        self._status = QLabel("Launching…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(hint_style() + " background: transparent;")

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("%p%")
        self._bar.setStyleSheet(_progress_stylesheet())

        layout.addStretch(1)
        layout.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._title)
        layout.addSpacing(4)
        layout.addWidget(self._status)
        layout.addSpacing(8)
        layout.addWidget(self._bar)
        layout.addStretch(2)

        icon_path = ICONS_DIR / "app_icon.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._apply_shape_mask()

    def _shape_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)

    def _shape_path(self) -> QPainterPath:
        return smooth_viewport_path(self._shape_rect(), _CORNER_RADIUS)

    def _apply_shape_mask(self) -> None:
        self.setMask(QRegion(self._shape_path().toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_shape_mask()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self._shape_rect()
        path = self._shape_path()

        # Clip all fills to rounded shape — avoids the sharp rectangular halo.
        painter.setClipPath(path)
        painter.fillPath(path, workspace_backdrop_brush(rect))
        painter.fillPath(path, glass_fill_gradient(rect, path))
        painter.fillPath(path, tile_dark_overlay())
        painter.fillPath(path, chrome_bar_dark_overlay())
        painter.setClipping(False)

        draw_multicolor_glow(painter, path)
        inner = smooth_viewport_path(rect.adjusted(5, 5, -5, -5), _CORNER_RADIUS - 4)
        painter.setPen(QPen(QColor(244, 114, 182, 55), 1))
        painter.drawPath(inner)
        draw_neon_border(painter, path, width=2)

    def set_progress(self, text: str, percent: int) -> None:
        pct = max(0, min(100, int(percent)))
        self._status.setText(text)
        self._bar.setValue(pct)

    def complete(self, ok: bool, message: str = "") -> None:
        self.set_progress(message or ("Ready" if ok else "Started with warnings"), 100)
        QTimer.singleShot(400, lambda: self.finished.emit(ok, message))
