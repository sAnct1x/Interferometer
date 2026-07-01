"""Neon palette, translucency knobs, glow helpers, and global QSS."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor, QLinearGradient, QBrush

# ── Accent palette (hex) ───────────────────────────────────────────────────
NEON_CYAN = "#00f5ff"
NEON_BLUE = "#3b82ff"
NEON_PURPLE = "#a855f7"
NEON_PINK = "#f472b6"
NEON_MAGENTA = "#ec4899"

# ── Text palette (hex) — typography imports these ──────────────────────────
TEXT_PRIMARY = "#f0fbff"
TEXT_MUTED = "#94a3b8"
TEXT_HINT = "#64748b"
TEXT_TITLE = NEON_CYAN
TEXT_ON_ACCENT = "#ffffff"

# ── Surfaces ───────────────────────────────────────────────────────────────
BG_DEEP = "#120a22"
FIELD_BG = "rgba(20, 10, 40, 0.65)"
FIELD_BG_FOCUS = "rgba(15, 25, 55, 0.8)"
PANEL_BG = "rgba(12, 8, 28, 0.6)"
MENU_BG = "rgba(12, 8, 28, 0.95)"
SCROLLBAR_BG = "rgba(15, 10, 30, 0.5)"
RADIO_BG = "rgba(15, 10, 30, 0.7)"
SPLITTER_HANDLE = "rgba(168, 85, 247, 0.2)"
CHROME_MENU_HOVER = "rgba(168, 85, 247, 0.35)"
MENU_ITEM_HOVER = "rgba(168, 85, 247, 0.45)"
MENU_GRADIENT_START = "rgba(168,85,247,0.6)"
MENU_GRADIENT_END = "rgba(244,114,182,0.5)"
PURPLE_BORDER_55 = "rgba(168, 85, 247, 0.55)"
PINK_BORDER_45 = "rgba(244, 114, 182, 0.45)"
PINK_BORDER_60 = "rgba(244, 114, 182, 0.6)"

CHROME_TELEMETRY_GAP_PX = 3

# ── Surface translucency (alpha 0–255) ────────────────────────────────────
# Shared knobs for glass panels, workspace, chrome bars, viewports, rail.
GLASS_FILL_ALPHAS = (178, 168, 162)
CHROME_BAR_OVERLAY_ALPHA = 168
TILE_OVERLAY_ALPHA = 155
WORKSPACE_BACKDROP_ALPHAS = (212, 202, 206)
PANEL_HEADER_ALPHA = 220
VIEWPORT_FILL_ALPHA = 205
MINIMIZED_CHIP_OVERLAY_ALPHA = 160
RAIL_BASE_ALPHA = 206
RAIL_EDGE_PURPLE_ALPHAS = (76, 68, 58, 48, 38, 28, 18, 8, 0)

COLOR_CYAN = QColor(0, 245, 255)
COLOR_BLUE = QColor(59, 130, 255)
COLOR_PURPLE = QColor(168, 85, 247)
COLOR_PINK = QColor(244, 114, 182)
COLOR_MAGENTA = QColor(236, 72, 153)
COLOR_HOT = QColor(255, 0, 110)


def draw_multicolor_glow(
    painter: QPainter,
    path: QPainterPath,
    *,
    layers: list[tuple[QColor, int, int]] | None = None,
) -> None:
    """Stacked outer glow rings (pink, purple, cyan by default)."""
    if layers is None:
        layers = [
            (COLOR_HOT, 14, 18),
            (COLOR_MAGENTA, 10, 28),
            (COLOR_PURPLE, 7, 45),
            (COLOR_BLUE, 4, 70),
            (COLOR_CYAN, 2, 110),
        ]
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for color, width, alpha in layers:
        pen = QPen(QColor(color.red(), color.green(), color.blue(), alpha), width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)


def draw_neon_border(
    painter: QPainter,
    path: QPainterPath,
    *,
    width: int = 2,
) -> None:
    """Bright dual-tone edge stroke."""
    outer = QPen(COLOR_CYAN, width + 1)
    outer.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(outer)
    painter.drawPath(path)
    inner = QPen(COLOR_PINK, max(1, width - 1))
    inner.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(inner)
    painter.drawPath(path)


def glass_fill_gradient(rect, path: QPainterPath) -> QBrush:
    """Translucent violet→blue glass fill."""
    a0, a1, a2 = GLASS_FILL_ALPHAS
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(30, 15, 55, a0))
    grad.setColorAt(0.45, QColor(15, 25, 60, a1))
    grad.setColorAt(1.0, QColor(10, 35, 70, a2))
    return QBrush(grad)


def chrome_bar_dark_overlay() -> QColor:
    """Dark wash on title + telemetry bars (glass_fill alone is too see-through)."""
    return QColor(8, 14, 32, CHROME_BAR_OVERLAY_ALPHA)


def tile_dark_overlay() -> QColor:
    """Extra dark wash on hub tiles (glass_fill alone is too see-through)."""
    return QColor(8, 14, 32, TILE_OVERLAY_ALPHA)


def workspace_backdrop_brush(rect) -> QBrush:
    """Hub workspace + splash backdrop gradient (matches HoloBackground)."""
    if hasattr(rect, "topLeft"):
        tl, br = rect.topLeft(), rect.bottomRight()
    else:
        tl = rect
        br = rect
    a0, a1, a2 = WORKSPACE_BACKDROP_ALPHAS
    grad = QLinearGradient(tl, br)
    grad.setColorAt(0.0, QColor(18, 8, 42, a0))
    grad.setColorAt(0.45, QColor(12, 18, 52, a1))
    grad.setColorAt(1.0, QColor(8, 22, 58, a2))
    return QBrush(grad)


def chip_accent_color(index: int) -> QColor:
    """Rotate accent colors across telemetry chips."""
    palette = [COLOR_CYAN, COLOR_PINK, COLOR_PURPLE, COLOR_BLUE, COLOR_MAGENTA, COLOR_HOT]
    return palette[index % len(palette)]


def app_stylesheet() -> str:
    """Global QWidget QSS built from palette constants above."""
    return f"""
QMainWindow {{ background: transparent; }}

QWidget {{
    background: transparent;
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "Consolas", sans-serif;
}}

QComboBox, QLineEdit, QDoubleSpinBox, QSpinBox {{
    background: {FIELD_BG};
    border: 1px solid {PURPLE_BORDER_55};
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT_PRIMARY};
    selection-background-color: {NEON_MAGENTA};
    selection-color: {TEXT_ON_ACCENT};
}}

QComboBox:focus, QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border: 1px solid {NEON_CYAN};
    background: {FIELD_BG_FOCUS};
}}

QComboBox::drop-down {{ border: none; width: 18px; }}

QRadioButton {{ color: {TEXT_MUTED}; spacing: 8px; }}

QRadioButton::indicator {{
    width: 14px; height: 14px; border-radius: 7px;
    border: 1px solid {PINK_BORDER_60};
    background: {RADIO_BG};
}}

QRadioButton::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {NEON_PURPLE}, stop:1 {NEON_PINK});
    border: 1px solid {NEON_CYAN};
}}

QCheckBox {{ color: {NEON_PINK}; }}

QCheckBox::indicator:checked {{
    background: {NEON_PURPLE};
    border: 1px solid {NEON_CYAN};
}}

QScrollBar:vertical {{
    background: {SCROLLBAR_BG};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {NEON_PINK}, stop:1 {NEON_BLUE});
    border-radius: 4px;
    min-height: 24px;
}}

QMessageBox {{
    background-color: {BG_DEEP};
    color: {TEXT_PRIMARY};
}}

QSplitter::handle {{ background: {SPLITTER_HANDLE}; width: 5px; height: 5px; }}

QSplitter::handle:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {NEON_PINK}, stop:0.5 {NEON_PURPLE}, stop:1 {NEON_CYAN});
}}

QLabel {{ color: {TEXT_MUTED}; }}

QTextEdit, QPlainTextEdit {{
    background: {PANEL_BG};
    border: 1px solid {PINK_BORDER_45};
    border-radius: 6px;
    color: {TEXT_PRIMARY};
    padding: 6px;
}}

QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {NEON_CYAN}; }}

QMenuBar {{ background: transparent; color: {TEXT_MUTED}; }}

QMenuBar::item:selected {{
    background: {CHROME_MENU_HOVER};
    color: {NEON_CYAN};
}}

QMenu {{
    background: {MENU_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {NEON_PINK};
}}

QMenu::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {MENU_GRADIENT_START}, stop:1 {MENU_GRADIENT_END});
}}
"""
