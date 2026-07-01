"""Frameless hub title bar with menus and window controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from config import APP_BADGE, APP_TITLE
from gui.glass_panel import octagon_path
from gui.window_controls import is_maximized, minimize_window, toggle_maximize
from gui.neon_theme import (
    CHROME_TELEMETRY_GAP_PX,
    NEON_CYAN,
    NEON_PINK,
    NEON_PURPLE,
    draw_multicolor_glow,
    draw_neon_border,
    glass_fill_gradient,
    chrome_bar_dark_overlay,
)

from gui.typography import body_px, primary_style, TEXT_PRIMARY, title_px


def hub_menubar_stylesheet(scale: float) -> str:
    from gui.ui_scale import px

    font_px = max(11, body_px(scale))
    pad_y = max(2, px(4, scale))
    pad_x = max(6, px(10, scale))
    menu_pad = px(6, scale)
    item_pad_y = px(8, scale)
    item_pad_x = px(16, scale)
    item_margin_x = px(8, scale)
    sep_margin = px(14, scale)

    return (
        f"QMenuBar {{ background: transparent; color: {NEON_CYAN}; spacing: 6px; "
        f"padding: 0px; margin: 0px; border: none; font-size: {font_px}px; }}"
        f"QMenuBar::item {{ background: transparent; padding: {pad_y}px {pad_x}px; "
        f"margin: 0px; font-size: {font_px}px; }}"
        f"QMenuBar::item:selected {{ background: rgba(168,85,247,0.35); border-radius: 4px; }}"
        f"QMenu {{ background: rgba(12,8,32,0.97); color: {TEXT_PRIMARY}; "
        f"border: 1px solid {NEON_PINK}; border-radius: 6px; "
        f"padding: {menu_pad}px 0px; min-width: 320px; font-size: {font_px}px; }}"
        f"QMenu::item {{ padding: {item_pad_y}px 36px {item_pad_y}px {item_pad_x}px; "
        f"margin: 2px {item_margin_x}px; border-radius: 4px; }}"
        f"QMenu::item:selected {{ background: rgba(168,85,247,0.45); }}"
        f"QMenu::indicator {{ width: 14px; height: 14px; margin-right: 10px; "
        f"subcontrol-position: right center; subcontrol-origin: padding; }}"
        f"QMenu::separator {{ height: 1px; background: rgba(168,85,247,0.35); "
        f"margin: 5px {sep_margin}px; }}"
    )


# Default before dashboard applies live workspace scale.
HUB_MENUBAR_STYLESHEET = hub_menubar_stylesheet(1.0)


class HubChromeBar(QWidget):
    """Custom top chrome: drag to move, no native title bar."""

    def __init__(self, parent_window) -> None:
        super().__init__()
        self._window = parent_window
        self._drag_pos: QPoint | None = None
        self._max_btn: QPushButton | None = None
        self._win_btns: list[QPushButton] = []
        self._title_label: QLabel | None = None
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 6, 10, 6)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel(f" {APP_BADGE} ")
        badge.setStyleSheet(
            f"color: {NEON_CYAN}; font-weight: bold; font-size: {title_px()}px; "
            f"background: rgba(168,85,247,0.25); "
            f"border: 1px solid {NEON_PINK}; padding: 4px 10px;"
        )
        self._layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(APP_TITLE)
        self._title_label = title
        title.setStyleSheet(
            primary_style() + f" font-size: {title_px()}px; font-weight: bold; background: transparent;"
        )
        self._layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._menu = QMenuBar()
        self._menu.setNativeMenuBar(False)
        self._menu.setFixedHeight(30)
        self._menu.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._menu.setStyleSheet(HUB_MENUBAR_STYLESHEET)
        self._layout.addWidget(self._menu, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)

        btn_style = (
            "QPushButton {"
            "  background: rgba(168,85,247,0.2); color: " + TEXT_PRIMARY + ";"
            f"  border: 1px solid {NEON_PURPLE}; border-radius: 4px;"
            "}"
            "QPushButton:hover {"
            f"  background: rgba(244,114,182,0.45); border: 1px solid {NEON_CYAN};"
            "}"
        )
        for label, slot in (("—", "minimize"), ("□", "maximize"), ("✕", "close")):
            btn = QPushButton(label)
            btn.setFixedSize(34, 28)
            btn.setStyleSheet(btn_style)
            if slot == "minimize":
                btn.clicked.connect(lambda: minimize_window(self._window))
            elif slot == "maximize":
                self._max_btn = btn
                btn.clicked.connect(self._toggle_max)
            else:
                btn.clicked.connect(self._window.close)
            self._win_btns.append(btn)
            self._layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def apply_ui_scale(self, scale: float) -> None:
        from gui.ui_scale import chrome_bar_height, menubar_height, px

        self.setFixedHeight(chrome_bar_height(scale))
        self._menu.setFixedHeight(menubar_height(scale))
        self._menu.setStyleSheet(hub_menubar_stylesheet(scale))
        margin_y = max(4, px(6, scale))
        self._layout.setContentsMargins(
            max(6, px(14, scale)),
            margin_y,
            max(6, px(10, scale)),
            margin_y,
        )
        self._layout.setSpacing(max(4, px(10, scale)))
        if self._title_label is not None:
            self._title_label.setVisible(scale >= 0.55)
        badge_font = title_px(scale)
        title_font = title_px(scale)
        for child in self.findChildren(QLabel):
            if child.text().strip() == APP_BADGE.strip():
                child.setStyleSheet(
                    f"color: {NEON_CYAN}; font-weight: bold; font-size: {badge_font}px; "
                    f"background: rgba(168,85,247,0.25); "
                    f"border: 1px solid {NEON_PINK}; padding: 2px 6px;"
                )
            elif child.text() == APP_TITLE:
                child.setStyleSheet(
                    primary_style() + f" font-size: {title_font}px; font-weight: bold; background: transparent;"
                )
        for btn in self._win_btns:
            btn.setFixedSize(max(24, px(34, scale)), max(20, px(28, scale)))
        self._menu.updateGeometry()

    def hub_menu(self) -> QMenuBar:
        return self._menu

    def set_maximized_state(self, maximized: bool) -> None:
        self._update_maximize_button(maximized)

    def _update_maximize_button(self, maximized: bool) -> None:
        if self._max_btn is not None:
            self._max_btn.setText("❐" if maximized else "□")
            self._max_btn.setToolTip("Restore" if maximized else "Maximize")

    def _toggle_max(self) -> None:
        if is_maximized(self._window):
            toggle_maximize(self._window, getattr(self._window, "_pre_maximize_geometry", None))
            self._window._pre_maximize_geometry = None
        else:
            self._window._pre_maximize_geometry = self._window.geometry()
            toggle_maximize(self._window, None)
        self.set_maximized_state(is_maximized(self._window))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = octagon_path(
            self.rect().adjusted(0, 0, -1, -1 - CHROME_TELEMETRY_GAP_PX),
            chamfer=12,
        )
        draw_multicolor_glow(painter, path)
        painter.fillPath(path, glass_fill_gradient(self.rect(), path))
        painter.fillPath(path, chrome_bar_dark_overlay())
        draw_neon_border(painter, path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            self._window._main_drag_active = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if is_maximized(self._window):
                from gui.window_controls import restore_window, screen_for_widget

                # Prefer a saved windowed geometry; fall back to a sensible 70 × 80 % window
                # instead of the full-screen "normal" size Qt would otherwise restore.
                pre_geo = getattr(self._window, "_pre_maximize_geometry", None)
                if pre_geo is None:
                    from PySide6.QtCore import QRect
                    from PySide6.QtGui import QGuiApplication
                    screen = screen_for_widget(self._window)
                    if screen is not None:
                        avail = screen.availableGeometry()
                        w = int(avail.width() * 0.70)
                        h = int(avail.height() * 0.80)
                        cx = event.globalPosition().toPoint().x()
                        x = max(avail.left(), min(cx - w // 2, avail.right() - w))
                        pre_geo = QRect(x, avail.top() + 20, w, h)
                restore_window(self._window, pre_geo)
                self._window._pre_maximize_geometry = None
                self.set_maximized_state(False)
                self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        self._window._main_drag_active = False
        # Trigger one deferred screen check so scale + tiles update after the drag lands.
        if hasattr(self._window, "_schedule_display_refresh"):
            self._window._schedule_display_refresh(delay_ms=120)
