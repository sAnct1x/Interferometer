"""Tile home positions, grid snap, focus mode, and layout persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QPoint

from core.tile_layout_store import (
    COMPACT_HIDDEN_TILES,
    COMPACT_TILE_LAYOUT,
    DEFAULT_TILE_LAYOUT,
    STARTUP_HIDDEN_TILES,
    load_tile_layout_with_keys,
    reset_tile_layout_file,
    save_tile_layout,
)
from gui.hub_tile import NON_SNAPPING_TILES
from gui.ui_scale import ABS_MIN_TILE_H, ABS_MIN_TILE_W, grid_cell_px, tile_min_size
from gui.workspace_grid import clamp_rect_to_bounds, snap_rect_to_grid

if TYPE_CHECKING:
    from gui.dashboard import Dashboard

SNAP_HOME_PX = 96
SNAP_EDGE_PX = 28
OVERLAP_REJECT = 0.85
MIN_EDGE_OVERLAP = 0.28


@dataclass
class LayoutSnapshot:
    focus_tile: str | None = None
    homes: dict[str, dict[str, float]] = field(default_factory=dict)
    float_rects: dict[str, QRect] = field(default_factory=dict)


def _tile_rect(tile) -> QRect:
    return QRect(tile.pos(), tile.size())


def _overlap_ratio(a: QRect, b: QRect) -> float:
    inter = a.intersected(b)
    if inter.isEmpty() or a.isEmpty():
        return 0.0
    return inter.width() * inter.height() / float(a.width() * a.height())


def _center_dist(a: QRect, b: QRect) -> float:
    ac = a.center()
    bc = b.center()
    return float(((ac.x() - bc.x()) ** 2 + (ac.y() - bc.y()) ** 2) ** 0.5)


class TileLayoutController:
    """Place tiles at recorded homes inside the hub workspace."""

    def __init__(self, dashboard: Dashboard) -> None:
        self._dash = dashboard
        self._homes, self._saved_home_keys = load_tile_layout_with_keys()
        self._session_custom_homes: set[str] = set()
        self._focus_tile: str | None = None
        self._pre_focus: LayoutSnapshot | None = None
        self._last_layout_ws: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._layout_suspended = False

    def has_custom_home(self, tile_id: str) -> bool:
        if tile_id != "workspace":
            return True
        return (
            tile_id in self._saved_home_keys
            or tile_id in self._session_custom_homes
            or tile_id in self._homes
        )

    def mark_home_custom(self, tile_id: str) -> None:
        self._session_custom_homes.add(tile_id)

    @property
    def focus_tile(self) -> str | None:
        return self._focus_tile

    @property
    def homes(self) -> dict[str, dict[str, float]]:
        return self._homes

    def workspace_rect(self) -> QRect:
        """Tile layout bounds in central-widget coordinates."""
        from gui.wireframe_rail import HexRailOverlay

        cw = self._dash.centralWidget()
        if cw is None:
            return QRect(0, 0, 200, 200)

        bar_reserve = 0
        if hasattr(self._dash, "_min_tile_bar") and self._dash._min_tile_bar.isVisible():
            from gui.minimized_tile_bar import MinimizedTileBar

            bar_reserve = MinimizedTileBar.BAR_HEIGHT + 6

        from gui.ui_scale import rail_width

        left = rail_width()
        return QRect(
            left,
            0,
            max(200, cw.width() - left),
            max(200, cw.height() - bar_reserve),
        )

    def rect_from_norm(
        self,
        norm: dict[str, float],
        tile_id: str | None = None,
        *,
        strict: bool = False,
    ) -> QRect:
        ws = self.workspace_rect()
        if ws.width() <= 0 or ws.height() <= 0:
            return QRect(ws.x(), ws.y(), 200, 200)
        width = max(ABS_MIN_TILE_W, int(norm["w"] * ws.width()))
        height = max(ABS_MIN_TILE_H, int(norm["h"] * ws.height()))
        if not strict:
            min_w, min_h = tile_min_size(
                tile_id or "",
                workspace_width=ws.width(),
                workspace_height=ws.height(),
            )
            width = max(min_w, width)
            height = max(min_h, height)
        width = min(width, ws.width())
        height = min(height, ws.height())
        return QRect(
            ws.x() + int(norm["x"] * ws.width()),
            ws.y() + int(norm["y"] * ws.height()),
            width,
            height,
        )

    def norm_from_rect(self, rect: QRect) -> dict[str, float]:
        ws = self.workspace_rect()
        if ws.width() <= 0 or ws.height() <= 0:
            return {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}
        return {
            "x": max(0.0, min(1.0, (rect.x() - ws.x()) / ws.width())),
            "y": max(0.0, min(1.0, (rect.y() - ws.y()) / ws.height())),
            "w": max(0.08, min(1.0, rect.width() / ws.width())),
            "h": max(0.08, min(1.0, rect.height() / ws.height())),
        }

    def _snap_tile_rect(self, rect: QRect, tile_id: str) -> QRect:
        bounds = self.workspace_rect()
        min_w, min_h = tile_min_size(
            tile_id,
            workspace_width=bounds.width(),
            workspace_height=bounds.height(),
        )
        if tile_id in NON_SNAPPING_TILES:
            return clamp_rect_to_bounds(rect, bounds, min_w=min_w, min_h=min_h)
        return snap_rect_to_grid(
            rect,
            bounds,
            min_w=min_w,
            min_h=min_h,
            cell_px=grid_cell_px(),
        )

    def home_rect(self, tile_id: str, *, strict: bool = False) -> QRect | None:
        norm = self._homes.get(tile_id) or DEFAULT_TILE_LAYOUT.get(tile_id)
        if norm is None:
            return None
        return self.rect_from_norm(norm, tile_id, strict=strict)

    def apply_startup_layout(self) -> None:
        for tile_id in STARTUP_HIDDEN_TILES:
            tile = self._dash.tiles.get(tile_id)
            if tile is not None:
                tile.hide()
        for tile_id, tile in self._dash.tiles.items():
            if not tile.isVisible():
                continue
            self.place_at_home(tile_id, from_saved=True)

    def apply_compact_layout(self) -> None:
        """Hide optional tiles and place camera, beam, and Atria for small displays."""
        for tile_id in COMPACT_HIDDEN_TILES:
            tile = self._dash.tiles.get(tile_id)
            if tile is not None:
                tile.hide()
        for tile_id, norm in COMPACT_TILE_LAYOUT.items():
            self._homes[tile_id] = dict(norm)
            self.mark_home_custom(tile_id)
            tile = self._dash.tiles.get(tile_id)
            if tile is None:
                continue
            if tile._minimized:
                self._dash.restore_tile_from_bar(tile_id)
            if not tile.isFloating():
                tile.setFloating(True)
            self.place_at_home(tile_id)

    def place_at_home(self, tile_id: str, *, from_saved: bool = False) -> None:
        tile = self._dash.tiles.get(tile_id)
        rect = self.home_rect(tile_id, strict=from_saved)
        if tile is None or rect is None:
            return
        tile._workspace_maximized = False
        header = tile.content_panel()
        if header is not None and header.header_widget() is not None:
            header.header_widget().set_maximized_state(False)

        bounds = self.workspace_rect()
        design_min_w, design_min_h = tile_min_size(
            tile_id,
            workspace_width=bounds.width(),
            workspace_height=bounds.height(),
        )
        if from_saved:
            # Honor saved fractions, then nudge to the fixed workspace grid so tiles
            # stay aligned with HoloBackground lines after resolution / scale changes.
            tile.setMinimumSize(
                min(design_min_w, rect.width()),
                min(design_min_h, rect.height()),
            )
            final = clamp_rect_to_bounds(
                rect,
                bounds,
                min_w=rect.width(),
                min_h=rect.height(),
            )
            if tile_id not in NON_SNAPPING_TILES:
                final = snap_rect_to_grid(
                    final,
                    bounds,
                    min_w=min(final.width(), design_min_w),
                    min_h=min(final.height(), design_min_h),
                    cell_px=grid_cell_px(),
                )
        else:
            final = self._snap_tile_rect(rect, tile_id)

        tile.setGeometry(final)
        tile.setMinimumSize(
            min(design_min_w, final.width()),
            min(design_min_h, final.height()),
        )
        tile.show()
        tile.raise_()

    def show_tile_centered(
        self,
        tile_id: str,
        *,
        width_frac: float = 0.52,
        height_frac: float = 0.68,
    ) -> None:
        """Show a tile centered in the hub workspace (no grid nudge)."""
        tile = self._dash.tiles.get(tile_id)
        if tile is None:
            return
        if self._focus_tile is not None:
            self.exit_focus()
        ws = self.workspace_rect()

        min_w, min_h = tile_min_size(
            tile_id,
            workspace_width=ws.width(),
            workspace_height=ws.height(),
        )
        width = max(min_w, int(ws.width() * width_frac))
        height = max(min_h, int(ws.height() * height_frac))
        x = ws.x() + max(0, (ws.width() - width) // 2)
        y = ws.y() + max(0, (ws.height() - height) // 2)
        rect = QRect(x, y, width, height)

        tile._workspace_maximized = False
        header = tile.content_panel()
        if header is not None and header.header_widget() is not None:
            header.header_widget().set_maximized_state(False)
        tile.setGeometry(rect)
        tile.show()
        tile.raise_()
        self._homes[tile_id] = self.norm_from_rect(rect)
        self.mark_home_custom(tile_id)

    def apply_all_homes(self) -> None:
        for tile_id, tile in self._dash.tiles.items():
            if tile.isVisible() and not getattr(tile, "_minimized", False):
                if getattr(tile, "_workspace_maximized", False):
                    tile._workspace_maximized = False
                    if tile.content_panel() and tile.content_panel().header_widget():
                        tile.content_panel().header_widget().set_maximized_state(False)
                self.place_at_home(tile_id, from_saved=True)

    def capture_current_as_homes(self, *, note: str = "user save") -> str:
        captured: dict[str, dict[str, float]] = {}
        for tile_id, tile in self._dash.tiles.items():
            if not tile.isVisible() or getattr(tile, "_minimized", False):
                continue
            captured[tile_id] = self.norm_from_rect(_tile_rect(tile))
        self._homes.update(captured)
        path = save_tile_layout(captured, note=note)
        self._saved_home_keys = set(captured.keys())
        return str(path)

    def handle_drop(self, tile_id: str, *, free_placement: bool = False) -> None:
        """Finalize tile position after drag. Updates in-memory homes (save to persist)."""
        if self._focus_tile is not None:
            return
        tile = self._dash.tiles.get(tile_id)
        if tile is None:
            return

        rect = _tile_rect(tile)
        tile._drag_start_geometry = None

        if tile_id in NON_SNAPPING_TILES or free_placement:
            self._homes[tile_id] = self.norm_from_rect(rect)
            self.mark_home_custom(tile_id)
            return

        nudged = self._nudge_to_neighbor_edge(rect)
        if nudged is not None:
            rect = nudged

        rect = self._snap_tile_rect(rect, tile_id)
        tile.setGeometry(rect)
        self._homes[tile_id] = self.norm_from_rect(rect)
        self.mark_home_custom(tile_id)

    def handle_resize(self, tile_id: str) -> None:
        """Remember tile size after user resize."""
        if self._focus_tile is not None:
            return
        tile = self._dash.tiles.get(tile_id)
        if tile is None or not tile.isVisible() or getattr(tile, "_minimized", False):
            return
        rect = self._snap_tile_rect(_tile_rect(tile), tile_id)
        tile.setGeometry(rect)
        self._homes[tile_id] = self.norm_from_rect(rect)
        self.mark_home_custom(tile_id)

    def restore_home(self, tile_id: str) -> None:
        if self._focus_tile is not None:
            self.exit_focus()
        self.place_at_home(tile_id, from_saved=True)

    def restore_all_homes(self) -> None:
        if self._focus_tile is not None:
            self.exit_focus()
        self._homes = dict(DEFAULT_TILE_LAYOUT)
        self._homes.pop("workspace", None)
        self._saved_home_keys = set()
        self._session_custom_homes.clear()
        reset_tile_layout_file()
        self.apply_all_homes()

    def reload_saved_homes(self) -> None:
        if self._focus_tile is not None:
            self.exit_focus()
        self._homes, self._saved_home_keys = load_tile_layout_with_keys()
        self._session_custom_homes.clear()
        self.apply_all_homes()

    def toggle_focus(self, tile_id: str) -> None:
        tile = self._dash.tiles.get(tile_id)
        if tile is None or not tile.isVisible():
            return
        if self._focus_tile == tile_id:
            self.exit_focus()
            return
        self.enter_focus(tile_id)

    def enter_focus(self, tile_id: str) -> None:
        self._pre_focus = self._snapshot()
        self._focus_tile = tile_id
        ws = self.workspace_rect()

        focus = self._dash.tiles[tile_id]
        fw = int(ws.width() * 0.50)
        fh = int(ws.height() * 0.50)
        fx = ws.x() + (ws.width() - fw) // 2
        fy = ws.y() + (ws.height() - fh) // 2
        focus.setGeometry(fx, fy, fw, fh)
        focus.show()
        focus.raise_()

        thumb_w = max(200, int(ws.width() * 0.15))
        thumb_h = max(120, int(ws.height() * 0.14))
        margin = 8
        slots = self._perimeter_slots(ws, thumb_w, thumb_h, margin)
        idx = 0
        for other_id, other in self._dash.tiles.items():
            if other_id == tile_id or not other.isVisible():
                continue
            if idx >= len(slots):
                break
            other.setGeometry(slots[idx])
            other.show()
            other.lower()
            idx += 1
        focus.raise_()

    def exit_focus(self) -> None:
        self._focus_tile = None
        self._pre_focus = None
        self.apply_all_homes()

    def suspend_layout(self, suspended: bool) -> None:
        self._layout_suspended = suspended

    def reset_layout_tracking(self) -> None:
        """Force the next resize pass to re-apply homes (e.g. after monitor change)."""
        self._last_layout_ws = (0, 0, 0, 0)

    def on_window_resized(self) -> None:
        if self._layout_suspended or self._focus_tile is not None:
            return
        ws = self.workspace_rect()
        key = (ws.x(), ws.y(), ws.width(), ws.height())
        if key == self._last_layout_ws:
            return
        self._last_layout_ws = key
        self.apply_all_homes()

    def _snapshot(self) -> LayoutSnapshot:
        snap = LayoutSnapshot(focus_tile=self._focus_tile, homes=dict(self._homes))
        for tile_id, tile in self._dash.tiles.items():
            if tile.isVisible():
                snap.float_rects[tile_id] = _tile_rect(tile)
        return snap

    def _nudge_to_neighbor_edge(self, rect: QRect) -> QRect | None:
        """Light edge magnet: nudge from drop position, never jump to a distant align slot."""
        best = QRect(rect)
        best_score = float(SNAP_EDGE_PX) + 1.0

        for other_id, other in self._dash.tiles.items():
            if not other.isVisible():
                continue
            target = _tile_rect(other)
            if target == rect:
                continue
            for candidate in self._edge_nudges(rect, target):
                if _overlap_ratio(candidate, target) >= OVERLAP_REJECT:
                    continue
                score = self._edge_score(candidate, target)
                if score <= SNAP_EDGE_PX and score < best_score:
                    best_score = score
                    best = candidate

        if best_score <= SNAP_EDGE_PX:
            return best
        return None

    @staticmethod
    def _edge_nudges(moving: QRect, target: QRect) -> list[QRect]:
        """Small translations from the user's drop position toward a neighbor edge."""
        gap = 6
        w, h = moving.width(), moving.height()
        nudges: list[QRect] = []

        dx_right = target.right() + gap - moving.left()
        if abs(dx_right) <= SNAP_EDGE_PX:
            nudges.append(QRect(moving.left() + dx_right, moving.top(), w, h))

        dx_left = target.left() - gap - w - moving.left()
        if abs(dx_left) <= SNAP_EDGE_PX:
            nudges.append(QRect(moving.left() + dx_left, moving.top(), w, h))

        dy_below = target.bottom() + gap - moving.top()
        if abs(dy_below) <= SNAP_EDGE_PX:
            nudges.append(QRect(moving.left(), moving.top() + dy_below, w, h))

        dy_above = target.top() - gap - h - moving.top()
        if abs(dy_above) <= SNAP_EDGE_PX:
            nudges.append(QRect(moving.left(), moving.top() + dy_above, w, h))

        return nudges

    @staticmethod
    def _edge_score(a: QRect, b: QRect) -> float:
        dx = min(abs(a.left() - b.right()), abs(a.right() - b.left()))
        dy = min(abs(a.top() - b.bottom()), abs(a.bottom() - b.top()))
        parallel = 0.0
        if dx <= SNAP_EDGE_PX:
            parallel = max(
                parallel,
                (min(a.bottom(), b.bottom()) - max(a.top(), b.top()))
                / max(1, min(a.height(), b.height())),
            )
        if dy <= SNAP_EDGE_PX:
            parallel = max(
                parallel,
                (min(a.right(), b.right()) - max(a.left(), b.left()))
                / max(1, min(a.width(), b.width())),
            )
        if parallel < MIN_EDGE_OVERLAP:
            return 10_000.0
        return float(dx + dy)

    @staticmethod
    def _perimeter_slots(ws: QRect, tw: int, th: int, margin: int) -> list[QRect]:
        return [
            QRect(ws.x() + margin, ws.y() + margin, tw, th),
            QRect(ws.right() - tw - margin, ws.y() + margin, tw, th),
            QRect(ws.x() + margin, ws.bottom() - th - margin, tw, th),
            QRect(ws.right() - tw - margin, ws.bottom() - th - margin, tw, th),
            QRect(ws.x() + margin, ws.y() + (ws.height() - th) // 2, tw, th),
            QRect(ws.right() - tw - margin, ws.y() + (ws.height() - th) // 2, tw, th),
        ]
