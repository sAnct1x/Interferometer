"""Shared workspace grid for background lines and tile snap spacing."""

from __future__ import annotations

from PySide6.QtCore import QRect

# Fine grid for alignment (more squares than the old 56 px spacing).
GRID_CELL_PX = 32
# Emphasize every N fine cells (major grid lines).
GRID_MAJOR_EVERY = 4

# Background line opacity (0–255).
GRID_MINOR_ALPHA = 26
GRID_MAJOR_ALPHA = 58


def workspace_origin_x() -> int:
    from gui.ui_scale import rail_width

    return rail_width()


def clamp_rect_to_bounds(
    rect: QRect,
    bounds: QRect,
    *,
    min_w: int,
    min_h: int,
) -> QRect:
    """Keep a rect inside workspace bounds without grid snapping."""
    width = max(min_w, min(rect.width(), bounds.width()))
    height = max(min_h, min(rect.height(), bounds.height()))
    max_x = bounds.right() - width + 1
    max_y = bounds.bottom() - height + 1
    x = max(bounds.left(), min(rect.x(), max_x))
    y = max(bounds.top(), min(rect.y(), max_y))
    if x + width > bounds.right() + 1:
        width = max(min_w, bounds.right() - x + 1)
    if y + height > bounds.bottom() + 1:
        height = max(min_h, bounds.bottom() - y + 1)
    return QRect(x, y, width, height)


def snap_rect_to_grid(
    rect: QRect,
    bounds: QRect,
    *,
    min_w: int,
    min_h: int,
    cell_px: int = GRID_CELL_PX,
) -> QRect:
    """Snap tile origin and size to grid cells inside workspace bounds."""
    cell = max(8, cell_px)
    ox = bounds.x()
    oy = bounds.y()

    rel_x = rect.x() - ox
    rel_y = rect.y() - oy
    snap_x = ox + round(rel_x / cell) * cell
    snap_y = oy + round(rel_y / cell) * cell

    w_cells = max(1, round(rect.width() / cell))
    h_cells = max(1, round(rect.height() / cell))
    width = max(min_w, w_cells * cell)
    height = max(min_h, h_cells * cell)

    max_x = bounds.right() - width + 1
    max_y = bounds.bottom() - height + 1
    x = max(bounds.left(), min(snap_x, max_x))
    y = max(bounds.top(), min(snap_y, max_y))

    if x + width > bounds.right() + 1:
        width = max(min_w, bounds.right() - x + 1)
    if y + height > bounds.bottom() + 1:
        height = max(min_h, bounds.bottom() - y + 1)

    return QRect(x, y, width, height)
