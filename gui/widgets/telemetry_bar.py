"""Top telemetry strip with centered label/value chips."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QWidget

from config import LASER_WAVELENGTH_NM
from gui.glass_panel import panel_path
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

        self._waist = _GlowChip(
            "Beam width", "", accent_idx=0,
            help_text="Beam waist (w₀): the narrowest point of the focused laser beam.",
        )
        self._lambda = _GlowChip("Wavelength", f"{LASER_WAVELENGTH_NM:.0f} nm", accent_idx=1)
        self._eta = _GlowChip(
            "Efficiency", "", accent_idx=2,
            help_text="Coupling efficiency (η): how much light makes it through the fiber.",
        )
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
        path = panel_path(
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

    def __init__(self, title: str, value: str, *, accent_idx: int = 0, help_text: str = "") -> None:
        super().__init__()
        self._title = title
        self._value_text = value
        self._help_text = help_text
        self._accent = chip_accent_color(accent_idx)
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        current = f"{self._title}: {self._value_text or 'not measured yet'}"
        if self._help_text:
            self.setToolTip(f"{self._help_text}\n\n{current}")
        else:
            self.setToolTip(current)

    def set_value(self, text: str) -> None:
        self._value_text = text
        self._refresh_tooltip()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = panel_path(self.rect().adjusted(1, 1, -1, -1), chamfer=10)

        # A chip with nothing measured yet (no live feed / simulation running)
        # dims its border and glow so it visibly reads as "idle", not "broken".
        # Otherwise a bare em dash on a full-brightness chip looks like a gap.
        is_idle = not bool(self._value_text)
        glow_alpha = 18 if is_idle else 50
        fill_alpha = 12 if is_idle else 28
        edge_alpha = 110 if is_idle else 255

        glow_pen = QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), glow_alpha), 6)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        fill = QColor(self._accent.red(), self._accent.green(), self._accent.blue(), fill_alpha)
        painter.fillPath(path, fill)

        edge = QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), edge_alpha), 2)
        painter.setPen(edge)
        painter.drawPath(path)

        body = max(8.0, body_pt())
        label_font = QFont("Segoe UI", int(body))
        label_font.setBold(True)
        value_font = QFont("Consolas", int(body))
        value_font.setBold(True)

        label_text = f"{self._title}: "
        value_text = self._value_text or "—"

        rect = self.rect()
        available_w = max(10, rect.width() - 16)

        # Elide gracefully rather than overflow the chip's border if the label
        # or value is too long for the available width (narrow windows, long
        # plain-language labels, etc.). Full text is still on the tooltip.
        painter.setFont(label_font)
        label_fm = painter.fontMetrics()
        label_w = label_fm.horizontalAdvance(label_text)
        if label_w > available_w * 0.7:
            label_text = label_fm.elidedText(
                label_text, Qt.TextElideMode.ElideRight, int(available_w * 0.7)
            )
            label_w = label_fm.horizontalAdvance(label_text)

        painter.setFont(value_font)
        value_fm = painter.fontMetrics()
        value_room = max(10, available_w - label_w)
        value_text = value_fm.elidedText(value_text, Qt.TextElideMode.ElideRight, value_room)
        value_w = value_fm.horizontalAdvance(value_text)

        total_w = label_w + value_w
        x = rect.x() + max(8, (rect.width() - total_w) // 2)
        y = rect.center().y() + 5

        painter.setFont(label_font)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(x, y, label_text)

        painter.setFont(value_font)
        painter.setPen(QColor(TEXT_MUTED) if is_idle else QColor(TEXT_PRIMARY))
        painter.drawText(x + label_w, y, value_text)
