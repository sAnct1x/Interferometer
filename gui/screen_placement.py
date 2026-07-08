"""Convenience re-exports for placing top-level windows, including remembering
which monitor and position a window was last closed on."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from gui.window_controls import (
    capture_window_state,
    center_on_primary,
    primary_screen,
    restore_window_state,
    show_maximized_on_primary,
)

# Re-export for existing imports.
__all__ = [
    "capture_window_state",
    "center_on_primary",
    "primary_screen",
    "restore_window_state",
    "show_maximized_on_primary",
]
