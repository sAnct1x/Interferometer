"""Shared minimize, maximize, and restore helpers for frameless windows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QWidget


def primary_screen() -> QScreen | None:
    app = QGuiApplication.instance()
    if app is None:
        return None
    return app.primaryScreen()


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
