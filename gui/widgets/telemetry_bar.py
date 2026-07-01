"""Top telemetry strip with centered label/value chips."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QWidget

from config import LASER_WAVELENGTH_NM
from gui.glass_panel import octagon_path
from gui.neon_theme import (
    CHROME_TELEMETRY_GAP_PX,
    chip_accent_color,
    draw_multicolor_glow,
    draw_neon_border,
    glass_fill_gradient,
    chrome_bar_dark_overlay,
)
from gui.typography import body_pt, TEXT_MUTED, TEXT_PRIMARY


def _finite(value) -> bool:
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def fmt_um(value) -> str:
    return f"{float(value):.1f} µm" if _finite(value) else ""


def fmt_nm(value, *, fallback: float) -> str:
    if _finite(value):
        return f"{float(value):.1f} nm"
    return f"{fallback:.0f} nm"


def fmt_pct(value) -> str:
    return f"{float(value):.1f}%" if _finite(value) else ""


class TelemetryBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self._waist = _GlowChip("Waist", "", accent_idx=0)
        self._lambda = _GlowChip("λ", f"{LASER_WAVELENGTH_NM:.0f} nm", accent_idx=1)
        self._eta = _GlowChip("η", "", accent_idx=2)
        self._cpu = _GlowChip("CPU", "", accent_idx=3)
        self._laser = _GlowChip("Laser", "MANUAL", accent_idx=4)
        self._status = _GlowChip("Status", "Ready", accent_idx=5)

        for chip in (self._waist, self._lambda, self._eta, self._cpu, self._laser, self._status):
            layout.addWidget(chip, stretch=1)

    def apply_ui_scale(self, scale: float) -> None:
        from gui.ui_scale import px, telemetry_bar_height

        self.setMinimumHeight(telemetry_bar_height(scale))
        chip_h = px(44, scale)
        for chip in (self._waist, self._lambda, self._eta, self._cpu, self._laser, self._status):
            chip.setMinimumHeight(chip_h)
            chip.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = octagon_path(
            self.rect().adjusted(
                1,
                CHROME_TELEMETRY_GAP_PX + 1,
                -1,
                -1 - CHROME_TELEMETRY_GAP_PX,
            ),
            chamfer=16,
        )
        draw_multicolor_glow(painter, path)
        painter.fillPath(path, glass_fill_gradient(self.rect(), path))
        painter.fillPath(path, chrome_bar_dark_overlay())
        draw_neon_border(painter, path)

    def update_telemetry(self, data: dict) -> None:
        self._waist.set_value(fmt_um(data.get("beam_waist_um")))
        self._lambda.set_value(fmt_nm(data.get("wavelength_nm"), fallback=LASER_WAVELENGTH_NM))
        self._eta.set_value(fmt_pct(data.get("efficiency_pct")))
        cpu = data.get("cpu_pct")
        self._cpu.set_value(fmt_pct(cpu) if _finite(cpu) else "")
        laser = str(data.get("laser", "MANUAL")).upper()
        self._laser.set_value(laser)
        status = str(data.get("status", "Ready"))
        if len(status) > 36:
            status = status[:33] + "…"
        self._status.set_value(status)


class _GlowChip(QFrame):
    """Single centered line formatted as Label and Value."""

    def __init__(self, title: str, value: str, *, accent_idx: int = 0) -> None:
        super().__init__()
        self._title = title
        self._value_text = value
        self._accent = chip_accent_color(accent_idx)
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def set_value(self, text: str) -> None:
        self._value_text = text
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = octagon_path(self.rect().adjusted(1, 1, -1, -1), chamfer=10)

        glow_pen = QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 50), 6)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        fill = QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 28)
        painter.fillPath(path, fill)

        edge = QPen(self._accent, 2)
        painter.setPen(edge)
        painter.drawPath(path)

        body = max(8.0, body_pt())
        label_font = QFont("Segoe UI", int(body))
        label_font.setBold(True)
        value_font = QFont("Consolas", int(body))
        value_font.setBold(True)

        label_text = f"{self._title} — "
        value_text = self._value_text

        painter.setFont(label_font)
        label_w = painter.fontMetrics().horizontalAdvance(label_text)
        painter.setFont(value_font)
        value_w = painter.fontMetrics().horizontalAdvance(value_text)
        total_w = label_w + value_w

        rect = self.rect()
        x = rect.x() + max(8, (rect.width() - total_w) // 2)
        y = rect.center().y() + 5

        painter.setFont(label_font)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(x, y, label_text)

        painter.setFont(value_font)
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(x + label_w, y, value_text)
