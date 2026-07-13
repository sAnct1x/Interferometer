"""Frameless hub title bar with menus and window controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QEvent, QPoint, QRect
from PySide6.QtGui import QGuiApplication, QPainter, QScreen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from config import APP_BADGE, APP_TITLE
from gui.glass_panel import panel_path
from gui.window_controls import (
    looks_maximized,
    minimize_window,
    restore_window,
    toggle_maximize,
)
from gui.neon_theme import (
    ACCENT_SYSTEM,
    CHROME_TELEMETRY_GAP_PX,
    NEON_CYAN,
    NEON_PINK,
    NEON_PURPLE,
    draw_corner_ticks,
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

# How close the cursor needs to get to a monitor's edge, in real screen pixels,
# before a drag counts as an Aero-Snap-style dock request.
SNAP_HOT_ZONE_PX = 6


class HubChromeBar(QWidget):
    """Custom top chrome: drag to move, no native title bar."""

    def __init__(self, parent_window) -> None:
        super().__init__()
        self._window = parent_window
        self._drag_pos: QPoint | None = None
        self._did_drag = False
        self._snap_zone: str | None = None
        self._snap_overlay = None
        self._max_btn: QPushButton | None = None
        self._win_btns: list[QPushButton] = []
        self._title_label: QLabel | None = None
        # Must exist before any child installEventFilter — layout/addWidget can
        # deliver events into eventFilter during construction.
        self._menu: QMenuBar | None = None
        self._drag_grip: QWidget | None = None
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 6, 10, 6)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel(f" {APP_BADGE} ")
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge.setStyleSheet(
            f"color: {NEON_CYAN}; font-weight: bold; font-size: {title_px()}px; "
            f"background: rgba(168,85,247,0.25); "
            f"border: 1px solid {NEON_PINK}; padding: 4px 10px;"
        )
        self._layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(APP_TITLE)
        self._title_label = title
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title.setStyleSheet(
            primary_style() + f" font-size: {title_px()}px; font-weight: bold; background: transparent;"
        )
        self._layout.addWidget(title, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._menu = QMenuBar()
        self._menu.setNativeMenuBar(False)
        self._menu.setFixedHeight(30)
        self._menu.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._menu.setStyleSheet(HUB_MENUBAR_STYLESHEET)
        self._layout.addWidget(self._menu, stretch=0, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Extra empty grab zone so the window can be dragged even when menus
        # cover most of the chrome (frameless windows have no OS title bar).
        self._drag_grip = QWidget()
        self._drag_grip.setMinimumWidth(48)
        self._drag_grip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._drag_grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self._layout.addWidget(self._drag_grip, stretch=1)

        # Install filters only after both targets exist (see eventFilter).
        self._menu.installEventFilter(self)
        self._drag_grip.installEventFilter(self)

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
        if looks_maximized(self._window):
            pre = getattr(self._window, "_pre_maximize_geometry", None)
            restore_window(self._window, pre)
            self._window._pre_maximize_geometry = None
        else:
            self._window._pre_maximize_geometry = self._window.geometry()
            toggle_maximize(self._window, None)
        self.set_maximized_state(looks_maximized(self._window))

    def eventFilter(self, obj, event):
        """Forward empty chrome / menubar presses so the whole title strip can drag."""
        grip = self._drag_grip
        menu = self._menu
        if grip is None or menu is None:
            return super().eventFilter(obj, event)
        et = event.type()
        if obj is grip:
            if et == QEvent.Type.MouseButtonPress:
                self.mousePressEvent(event)
                return True
            if et == QEvent.Type.MouseMove:
                self.mouseMoveEvent(event)
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
        if obj is menu and et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and menu.actionAt(event.pos()) is None:
                self.mousePressEvent(event)
                return True
        if obj is menu and self._drag_pos is not None:
            if et == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                self.mouseMoveEvent(event)
                return True
            if et == QEvent.Type.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = panel_path(
            self.rect().adjusted(0, 0, -1, -1 - CHROME_TELEMETRY_GAP_PX),
            chamfer=12,
        )
        draw_multicolor_glow(painter, path)
        painter.fillPath(path, glass_fill_gradient(self.rect(), path))
        painter.fillPath(path, chrome_bar_dark_overlay())
        draw_neon_border(painter, path)
        draw_corner_ticks(painter, path.boundingRect(), ACCENT_SYSTEM, length=8.0, inset=5.0)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            self._did_drag = False
            self._window._main_drag_active = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._did_drag = True
            if looks_maximized(self._window):
                pre_geo = getattr(self._window, "_pre_maximize_geometry", None)
                cursor = event.globalPosition().toPoint()
                restore_window(self._window, pre_geo, cursor_global=cursor)
                self._window._pre_maximize_geometry = None
                self.set_maximized_state(False)
                # Keep the cursor over the chrome while the window shrinks under it.
                geo = self._window.frameGeometry()
                self._drag_pos = QPoint(
                    max(24, min(cursor.x() - geo.left(), geo.width() - 24)),
                    max(8, min(cursor.y() - geo.top(), 40)),
                )
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
            self._update_snap_preview(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        zone = self._detect_snap_zone(event.globalPosition().toPoint()) if self._did_drag else None
        self._drag_pos = None
        self._did_drag = False
        self._window._main_drag_active = False
        self._hide_snap_preview()
        if zone is not None:
            self._apply_snap(*zone)
        # Trigger one deferred screen check so scale + tiles update after the drag lands.
        if hasattr(self._window, "_schedule_display_refresh"):
            self._window._schedule_display_refresh(delay_ms=120)
        self.set_maximized_state(looks_maximized(self._window))
        event.accept()

    def _half_snap_fits(self, screen: QScreen) -> bool:
        """False when half this monitor is narrower than the app's own min width.

        Snapping to a half-width the app can't actually shrink to would just have
        Qt silently clamp wider than the preview showed, on a narrow laptop
        display it's clearer to skip the half-snap offer entirely than to show a
        docked-half preview and land on something else.
        """
        return screen.availableGeometry().width() // 2 >= self._window.minimumWidth()

    def _detect_snap_zone(self, global_pos: QPoint) -> tuple[str, QScreen] | None:
        """Which edge (if any) the cursor is currently hovering during a drag."""
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            return None
        avail = screen.availableGeometry()
        if global_pos.y() <= avail.top() + SNAP_HOT_ZONE_PX:
            return "top", screen
        if not self._half_snap_fits(screen):
            return None
        if global_pos.x() <= avail.left() + SNAP_HOT_ZONE_PX:
            return "left", screen
        if global_pos.x() >= avail.right() - SNAP_HOT_ZONE_PX:
            return "right", screen
        return None

    @staticmethod
    def _snap_rect(zone: str, screen: QScreen) -> QRect:
        avail = screen.availableGeometry()
        if zone == "top":
            return avail
        half_w = avail.width() // 2
        if zone == "left":
            return QRect(avail.left(), avail.top(), half_w, avail.height())
        return QRect(avail.left() + half_w, avail.top(), avail.width() - half_w, avail.height())

    def _update_snap_preview(self, global_pos: QPoint) -> None:
        hit = self._detect_snap_zone(global_pos)
        zone = hit[0] if hit is not None else None
        if zone == self._snap_zone:
            return
        self._snap_zone = zone
        if hit is None:
            self._hide_snap_preview()
            return
        if self._snap_overlay is None:
            from gui.snap_overlay import SnapPreviewOverlay

            self._snap_overlay = SnapPreviewOverlay()
        self._snap_overlay.show_at(self._snap_rect(*hit))

    def _hide_snap_preview(self) -> None:
        self._snap_zone = None
        if self._snap_overlay is not None:
            self._snap_overlay.hide()

    def _apply_snap(self, zone: str, screen: QScreen) -> None:
        from gui.window_controls import assign_to_screen, maximize_on_screen

        if zone == "top":
            self._window._pre_maximize_geometry = self._window.geometry()
            maximize_on_screen(self._window, screen)
            self.set_maximized_state(True)
            return
        assign_to_screen(self._window, screen)
        self._window.setGeometry(self._snap_rect(zone, screen))
