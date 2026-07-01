"""Rounded-rectangle panel silhouettes for hub tiles (chat-bubble style)."""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath

from config import PANEL_CORNER_RADIUS_PX


def panel_corner_radius(rect: QRectF, *, scale: float = 1.0) -> float:
    """Corner radius for a tile, clamped so small tiles stay proportionate."""
    base = min(PANEL_CORNER_RADIUS_PX, rect.width() * 0.14, rect.height() * 0.18)
    return max(6.0, base) * scale


def tile_panel_path(
    rect: QRectF,
    *,
    shape: str = "rounded",
    phase: int = 0,
    interlock: float = 0.07,
) -> QPainterPath:
    """Rounded-rectangle tile outline.

    The ``shape``/``phase``/``interlock`` parameters are retained for backwards
    compatibility with existing callers; every tile now uses a single, consistent
    rounded silhouette so the UI reads as clean curved panels.
    """
    del phase, interlock
    scale = 0.7 if shape == "wide" else 1.0
    radius = panel_corner_radius(rect, scale=scale)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path
