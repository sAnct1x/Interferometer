"""Octagonal clips, glow borders, and bracket-frame action buttons for the holographic UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QSize
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen, QColor, QFont, QLinearGradient, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget, QSizePolicy

from config import OCTAGON_CHAMFER_PX, PANEL_CORNER_RADIUS_PX
from gui.hex_geometry import tile_panel_path
from gui.typography import panel_title_stylesheet, body_pt, TEXT_PRIMARY
from gui.neon_theme import (
    COLOR_CYAN,
    COLOR_MAGENTA,
    COLOR_PINK,
    COLOR_PURPLE,
    draw_multicolor_glow,
    draw_neon_border,
    glass_fill_gradient,
    PANEL_HEADER_ALPHA,
    tile_dark_overlay,
    VIEWPORT_FILL_ALPHA,
    NEON_CYAN,
    NEON_PURPLE,
)


class PanelHeader(QWidget):
    """Inline title row with window controls (replaces OS or dock title bars)."""

    HEADER_HEIGHT = 32

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dock: QWidget | None = None
        self._window: QWidget | None = None
        self.setFixedHeight(self.HEADER_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        self._title_label = QLabel(title)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._title_label.setStyleSheet(panel_title_stylesheet(1.0))
        layout.addWidget(self._title_label)
        self._title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addStretch(1)

        btn_style = (
            "QPushButton {"
            "  background: rgba(168,85,247,0.2); color: " + TEXT_PRIMARY + ";"
            f"  border: 1px solid {NEON_PURPLE}; border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            f"  background: rgba(244,114,182,0.45); border: 1px solid {NEON_CYAN};"
            "}"
        )
        self._min_btn = QPushButton("—")
        self._max_btn = QPushButton("□")
        self._close_btn = QPushButton("✕")
        for btn in (self._min_btn, self._max_btn, self._close_btn):
            btn.setFixedSize(28, 22)
            btn.setStyleSheet(btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(btn)

        self._min_btn.clicked.connect(self._on_minimize)
        self._max_btn.clicked.connect(self._on_maximize)
        self._close_btn.clicked.connect(self._on_close)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._update_maximize_button(False)

    def set_title_stylesheet(self, css: str) -> None:
        self._title_label.setStyleSheet(css)

    def set_maximized_state(self, maximized: bool) -> None:
        self._update_maximize_button(maximized)

    def _update_maximize_button(self, maximized: bool) -> None:
        self._max_btn.setText("❐" if maximized else "□")
        self._max_btn.setToolTip("Restore" if maximized else "Maximize")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 14, 32, PANEL_HEADER_ALPHA))
        super().paintEvent(event)

    def bind_dock(self, dock: QWidget) -> None:
        self._dock = dock
        self._window = None

    def bind_window(self, window: QWidget) -> None:
        self._window = window
        self._dock = None

    def _on_close(self) -> None:
        if self._dock is not None:
            self._dock.close()
        elif self._window is not None:
            self._window.close()

    def _on_minimize(self) -> None:
        if self._dock is not None:
            if hasattr(self._dock, "minimize_to_bar"):
                self._dock.minimize_to_bar()
            else:
                self._dock.hide()
        elif self._window is not None:
            from gui.window_controls import minimize_window

            minimize_window(self._window)

    def _on_maximize(self) -> None:
        if self._dock is not None:
            if hasattr(self._dock, "toggle_maximize"):
                self._dock.toggle_maximize()
                return
            if getattr(self._dock, "_minimized", False) and hasattr(self._dock, "restore_from_bar"):
                self._dock.restore_from_bar()
                return
        elif self._window is not None:
            from gui.window_controls import is_maximized, toggle_maximize

            if is_maximized(self._window):
                toggle_maximize(self._window, getattr(self._window, "_pre_maximize_geometry", None))
                self._window._pre_maximize_geometry = None
            else:
                self._window._pre_maximize_geometry = self._window.geometry()
                toggle_maximize(self._window, None)
            self._update_maximize_button(is_maximized(self._window))


def octagon_path(rect, chamfer: int = OCTAGON_CHAMFER_PX) -> QPainterPath:
    """Rounded-rectangle silhouette. ``chamfer`` now sets the corner radius.

    Name and signature are preserved so existing chrome/telemetry/minimized-bar
    call sites keep working while rendering as clean curved panels.
    """
    r = QRectF(rect)
    corner = min(float(chamfer), r.width() / 4.0, r.height() / 4.0)
    path = QPainterPath()
    path.addRoundedRect(r, corner, corner)
    return path


def smooth_viewport_path(rect: QRectF, radius: float = 8.0) -> QPainterPath:
    """Rounded inner viewport clip (Atria chat / composer style)."""
    path = QPainterPath()
    r = min(radius, rect.width() / 4.0, rect.height() / 4.0)
    path.addRoundedRect(rect, r, r)
    return path


def hub_workspace_path(rect, chamfer: int = OCTAGON_CHAMFER_PX) -> QPainterPath:
    """Main hub workspace silhouette — fully rounded to match tile panels."""
    if hasattr(rect, "toRectF"):
        r = rect.toRectF()
    else:
        r = QRectF(rect)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    c = min(float(chamfer), w / 4.0, h / 4.0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), c, c)
    return path


def pentagon_path(rect) -> QPainterPath:
    path = QPainterPath()
    cx = rect.center().x()
    top = rect.top() + 4
    bottom = rect.bottom() - 4
    left = rect.left() + 8
    right = rect.right() - 8
    mid_y = (top + bottom) / 2
    path.moveTo(cx, top)
    path.lineTo(right, mid_y - 8)
    path.lineTo(right - 10, bottom)
    path.lineTo(left + 10, bottom)
    path.lineTo(left, mid_y - 8)
    path.closeSubpath()
    return path


def _bracket_corner_radius(rect: QRectF) -> float:
    return min(10.0, rect.width() / 6.0, rect.height() / 3.5)


def _draw_l_bracket(
    painter: QPainter,
    corner_x: float,
    corner_y: float,
    length: float,
    *,
    flip_x: bool,
    flip_y: bool,
    hover: bool,
) -> None:
    dx = -length if flip_x else length
    dy = -length if flip_y else length
    hx, hy = corner_x + dx, corner_y
    vx, vy = corner_x, corner_y + dy
    if hover:
        glow = QPen(QColor(COLOR_MAGENTA.red(), COLOR_MAGENTA.green(), COLOR_MAGENTA.blue(), 55), 5)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glow)
        painter.drawLine(int(corner_x), int(corner_y), int(hx), int(hy))
        painter.drawLine(int(corner_x), int(corner_y), int(vx), int(vy))
    pen = QPen(QColor(COLOR_PINK.red(), COLOR_PINK.green(), COLOR_PINK.blue(), 240), 2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(int(corner_x), int(corner_y), int(hx), int(hy))
    painter.drawLine(int(corner_x), int(corner_y), int(vx), int(vy))


def _draw_corner_dots(painter: QPainter, rect: QRectF, corner: str) -> None:
    spacing = 5.0
    dot = 2.2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(COLOR_MAGENTA.red(), COLOR_MAGENTA.green(), COLOR_MAGENTA.blue(), 120)))
    if corner == "tl":
        ox = rect.left() + 11
        oy = rect.top() + 10
    else:
        ox = rect.right() - 11 - 3 * spacing
        oy = rect.bottom() - 10 - dot
    for i in range(4):
        painter.drawEllipse(QRectF(ox + i * spacing, oy, dot, dot))


class BracketButton(QPushButton):
    """Glass action button with TL/BR corner brackets (reference HUD style)."""

    COMPACT_HEIGHT = 40
    NORMAL_HEIGHT = 44
    TEXT_INSET_X_COMPACT = 20
    TEXT_INSET_X_NORMAL = 22
    TEXT_INSET_Y = 9
    H_PAD_COMPACT = 32
    H_PAD_NORMAL = 36

    def __init__(self, text: str, parent=None, *, compact: bool = False) -> None:
        super().__init__(text, parent)
        self._compact = compact
        self.setFlat(True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: transparent; }"
            "QPushButton:hover { color: transparent; }"
            "QPushButton:pressed { color: transparent; }"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self._apply_sizing()

    def _button_font(self) -> QFont:
        font = self.font()
        font.setPointSizeF(body_pt())
        font.setBold(True)
        return font

    def _apply_sizing(self) -> None:
        from gui.ui_scale import get_scale, px

        scale = get_scale()
        fm = QFontMetrics(self._button_font())
        h_pad = px(self.H_PAD_COMPACT if self._compact else self.H_PAD_NORMAL, scale)
        min_w = fm.horizontalAdvance(self.text()) + h_pad * 2
        base_h = self.COMPACT_HEIGHT if self._compact else self.NORMAL_HEIGHT
        min_h = px(base_h, scale)
        self.setMinimumSize(min_w, min_h)

    def setText(self, text: str) -> None:
        super().setText(text)
        self._apply_sizing()

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def paintEvent(self, event) -> None:
        from gui.ui_scale import get_scale, px

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = get_scale()
        rect = QRectF(self.rect().adjusted(2, 2, -2, -2))
        radius = _bracket_corner_radius(rect)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(rect, radius, radius)

        hover = self.underMouse() and self.isEnabled()
        pressed = self.isDown()
        bracket_len = px(14, scale)
        label = self.text()

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if pressed:
            base.setColorAt(0.0, QColor(38, 12, 68, 195))
            base.setColorAt(0.55, QColor(24, 10, 48, 200))
            base.setColorAt(1.0, QColor(14, 6, 32, 205))
        elif hover:
            base.setColorAt(0.0, QColor(48, 16, 82, 188))
            base.setColorAt(0.55, QColor(30, 12, 58, 192))
            base.setColorAt(1.0, QColor(18, 8, 40, 198))
        else:
            base.setColorAt(0.0, QColor(40, 14, 70, 178))
            base.setColorAt(0.55, QColor(26, 10, 50, 182))
            base.setColorAt(1.0, QColor(16, 8, 36, 188))
        painter.fillPath(fill_path, base)

        sheen = QLinearGradient(rect.topRight(), rect.center())
        sheen.setColorAt(0.0, QColor(168, 85, 247, 36 if hover else 26))
        sheen.setColorAt(1.0, QColor(168, 85, 247, 0))
        painter.fillPath(fill_path, sheen)

        inner_r = rect.adjusted(3.5, 3.5, -3.5, -3.5)
        inner_rad = max(5.0, radius - 2.5)
        inner_path = QPainterPath()
        inner_path.addRoundedRect(inner_r, inner_rad, inner_rad)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(6, 4, 16, 160), 1))
        painter.drawPath(inner_path)

        outline = QPainterPath()
        outline.addRoundedRect(rect.adjusted(1.0, 1.0, -1.0, -1.0), radius - 1, radius - 1)
        ring_pen = QPen(QColor(COLOR_PURPLE.red(), COLOR_PURPLE.green(), COLOR_PURPLE.blue(), 200), 1.2)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(ring_pen)
        painter.drawPath(outline)

        tl_x = rect.left() + 5
        tl_y = rect.top() + 5
        br_x = rect.right() - 5
        br_y = rect.bottom() - 5
        _draw_l_bracket(painter, tl_x, tl_y, bracket_len, flip_x=False, flip_y=False, hover=hover)
        _draw_l_bracket(painter, br_x, br_y, bracket_len, flip_x=True, flip_y=True, hover=hover)
        _draw_corner_dots(painter, inner_r, "tl")
        _draw_corner_dots(painter, inner_r, "br")

        painter.setPen(QColor(TEXT_PRIMARY))
        font = self._button_font()
        painter.setFont(font)
        inset_x = px(
            self.TEXT_INSET_X_COMPACT if self._compact else self.TEXT_INSET_X_NORMAL,
            scale,
        )
        inset_y = px(self.TEXT_INSET_Y, scale)
        text_rect = self.rect().adjusted(inset_x, inset_y, -inset_x, -inset_y)
        painter.drawText(
            text_rect,
            Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignCenter,
            label,
        )


# Used across hub tiles (Start Live Feed, Save ROI, Calibrate, etc.).
PentagonButton = BracketButton


class GlassPanel(QWidget):
    """Translucent hex tile panel with pink/purple/cyan neon glow."""

    def __init__(self, parent=None, *, title: str = "", interlock_phase: int = 0, shape: str = "rounded") -> None:
        super().__init__(parent)
        self._title = title
        self._interlock_phase = interlock_phase
        self._shape = shape
        self._header: PanelHeader | None = PanelHeader(title, self) if title else None
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if self._header is not None:
            min_h = self._content_inset() * 2 + PanelHeader.HEADER_HEIGHT + 48
            self.setMinimumHeight(min_h)

    def _content_inset(self) -> int:
        """Scale-aware margin that clears the rounded panel border without octagon-era padding."""
        from gui.ui_scale import px

        return max(8, px(int(PANEL_CORNER_RADIUS_PX * 0.5 + 2)))

    def set_interlock_phase(self, phase: int) -> None:
        self._interlock_phase = phase % 2
        self.update()

    def set_tile_shape(self, shape: str) -> None:
        self._shape = shape
        self.update()

    def _panel_path(self, rect) -> QPainterPath:
        return tile_panel_path(
            QRectF(rect),
            shape=self._shape,
            phase=self._interlock_phase,
        )

    def header_widget(self) -> PanelHeader | None:
        return self._header

    def header_rect(self) -> QRect:
        if self._header is None:
            return QRect()
        return QRect(
            self._content_inset(),
            self._content_inset(),
            max(40, self.width() - 2 * self._content_inset()),
            PanelHeader.HEADER_HEIGHT,
        )

    def attach_hub_tile(self, tile: QWidget) -> None:
        if self._header is not None:
            self._header.bind_dock(tile)
            self._header.raise_()

    def attach_window(self, window: QWidget) -> None:
        if self._header is not None:
            self._header.bind_window(window)
            self._header.raise_()

    def content_margins(self) -> tuple[int, int, int, int]:
        title_space = PanelHeader.HEADER_HEIGHT if self._title else 0
        inset = self._content_inset()
        return (inset, inset + title_space, inset, inset)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._header is not None:
            inset = self._content_inset()
            width = max(self.width() - 2 * inset, 40)
            self._header.setGeometry(inset, inset, width, PanelHeader.HEADER_HEIGHT)
            self._header.show()
            self._header.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        path = self._panel_path(rect)

        draw_multicolor_glow(painter, path)
        painter.fillPath(path, glass_fill_gradient(rect, path))
        painter.fillPath(path, tile_dark_overlay())

        inner = self._panel_path(rect.adjusted(5, 5, -5, -5))
        shimmer = QPen(QColor(244, 114, 182, 55), 1)
        painter.setPen(shimmer)
        painter.drawPath(inner)

        draw_neon_border(painter, path, width=2)

