"""Shared minimize, maximize, and restore helpers for frameless windows."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget


def primary_screen() -> QScreen | None:
    app = QGuiApplication.instance()
    if app is None:
        return None
    return app.primaryScreen()


def screen_identifier(screen: QScreen) -> str:
    """Stable-ish key for a monitor, used to remember which one a window was on.

    ``QScreen.name()`` (e.g. ``\\\\.\\DISPLAY1`` on Windows) is tied to the OS
    output/adapter, not the window session, so it survives an app restart as
    long as the monitor stays plugged into the same port.
    """
    return screen.name() or f"{screen.size().width()}x{screen.size().height()}"


def find_screen(name: str | None) -> QScreen | None:
    """Look up a currently-connected monitor by its saved ``screen_identifier``."""
    if not name:
        return None
    app = QGuiApplication.instance()
    if app is None:
        return None
    for screen in app.screens():
        if screen_identifier(screen) == name:
            return screen
    return None


def capture_window_state(widget: QWidget) -> tuple[str | None, tuple[int, int, int, int] | None, bool]:
    """Snapshot ``(screen_name, normal_geometry, maximized)`` for persistence on close."""
    screen = screen_for_widget(widget)
    screen_name = screen_identifier(screen) if screen is not None else None
    maximized = is_maximized(widget)
    geo = widget.normalGeometry() if maximized else widget.geometry()
    geometry = (geo.x(), geo.y(), geo.width(), geo.height()) if geo.isValid() else None
    return screen_name, geometry, maximized


def restore_window_state(
    widget: QWidget,
    *,
    screen_name: str | None,
    geometry: tuple[int, int, int, int] | None,
    maximized: bool,
) -> bool:
    """Reopen a window on the monitor/position it was last closed on.

    Returns False without touching the widget if that monitor is no longer
    connected (unplugged, docking station left at home, etc.), so callers can
    fall back to a sane default like maximizing on the primary monitor.
    """
    screen = find_screen(screen_name)
    if screen is None:
        return False
    if maximized:
        widget.setGeometry(screen.availableGeometry())
        widget.show()
        assign_to_screen(widget, screen)
        maximize_on_screen(widget, screen)
        return True
    if geometry is None:
        return False
    available = screen.availableGeometry()
    rect = QRect(*geometry)
    # The monitor may have been reconfigured to a different resolution since
    # this was saved, so clamp the remembered window rect back into bounds
    # rather than trusting it blindly.
    rect.setWidth(min(rect.width(), available.width()))
    rect.setHeight(min(rect.height(), available.height()))
    if rect.right() > available.right():
        rect.moveRight(available.right())
    if rect.bottom() > available.bottom():
        rect.moveBottom(available.bottom())
    if rect.left() < available.left():
        rect.moveLeft(available.left())
    if rect.top() < available.top():
        rect.moveTop(available.top())
    widget.setGeometry(rect)
    widget.show()
    assign_to_screen(widget, screen)
    return True


def screen_for_widget(widget: QWidget) -> QScreen | None:
    screen = widget.screen()
    if screen is not None:
        return screen
    handle = widget.windowHandle()
    if handle is not None and handle.screen() is not None:
        return handle.screen()
    parent = widget.parentWidget()
    while parent is not None:
        screen = parent.screen()
        if screen is not None:
            return screen
        parent = parent.parentWidget()
    return primary_screen()


def center_on_primary(widget: QWidget) -> None:
    """Center a sized window on the primary monitor."""
    screen = primary_screen()
    if screen is None:
        return
    center_on_screen(widget, screen)


def center_on_screen(widget: QWidget, screen: QScreen | None = None) -> None:
    """Center a sized window on the given (or widget's) monitor."""
    screen = screen or screen_for_widget(widget)
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = widget.frameGeometry()
    frame.moveCenter(available.center())
    widget.move(frame.topLeft())
    assign_to_screen(widget, screen)


def assign_to_screen(widget: QWidget, screen: QScreen) -> None:
    handle = widget.windowHandle()
    if handle is not None:
        handle.setScreen(screen)


def is_maximized(widget: QWidget) -> bool:
    return bool(widget.windowState() & Qt.WindowState.WindowMaximized)


def minimize_window(widget: QWidget) -> None:
    """Minimize frameless top-level windows reliably on Windows."""
    widget.setWindowState(widget.windowState() | Qt.WindowState.WindowMinimized)


def restore_window(widget: QWidget, geometry=None) -> None:
    widget.showNormal()
    widget.setWindowState(widget.windowState() & ~Qt.WindowState.WindowMaximized)
    if geometry is not None:
        widget.setGeometry(geometry)
    widget.raise_()
    widget.activateWindow()


def maximize_on_screen(widget: QWidget, screen: QScreen | None = None) -> None:
    """Maximize on the monitor that owns this window (or the given screen)."""
    screen = screen or screen_for_widget(widget)
    if screen is None:
        widget.showMaximized()
        return
    available = screen.availableGeometry()
    current = screen_for_widget(widget)
    geo = widget.geometry()
    if (
        is_maximized(widget)
        and current is not None
        and current == screen
        and abs(geo.width() - available.width()) <= 3
        and abs(geo.height() - available.height()) <= 3
        and abs(geo.x() - available.x()) <= 3
        and abs(geo.y() - available.y()) <= 3
    ):
        return
    widget.showNormal()
    assign_to_screen(widget, screen)
    widget.setGeometry(available)
    widget.setWindowState(widget.windowState() | Qt.WindowState.WindowMaximized)
    widget.raise_()
    widget.activateWindow()


def show_maximized_on_primary(widget: QWidget) -> None:
    """First launch: maximize on the system primary monitor."""
    screen = primary_screen()
    if screen is None:
        widget.showMaximized()
        return
    available = screen.availableGeometry()
    widget.setGeometry(available)
    widget.show()
    assign_to_screen(widget, screen)
    widget.setGeometry(available)
    maximize_on_screen(widget, screen)


def toggle_maximize(widget: QWidget, restore_geometry=None) -> None:
    """Toggle maximize, restoring to restore_geometry when un-maximizing."""
    if is_maximized(widget):
        restore_window(widget, restore_geometry)
    else:
        maximize_on_screen(widget)
