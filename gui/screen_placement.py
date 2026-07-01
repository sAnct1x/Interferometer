"""Convenience re-exports for placing top-level windows on the primary monitor."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from gui.window_controls import center_on_primary, primary_screen, show_maximized_on_primary

# Re-export for existing imports.
__all__ = ["center_on_primary", "primary_screen", "show_maximized_on_primary"]
