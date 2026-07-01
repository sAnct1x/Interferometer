"""In-window hub tiles: draggable panels inside the workspace, not separate OS windows."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint, QRect, QEvent
from PySide6.QtGui import QMouseEvent, QCursor
from PySide6.QtWidgets import (
    QPushButton,
    QWidget,
    QSizePolicy,
    QLineEdit,
    QCheckBox,
    QTextEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QLabel,
)

from gui.glass_panel import GlassPanel, PanelHeader

TILE_INTERLOCK: dict[str, int] = {
    "beam": 0,
    "camera": 1,
    "roi_snapshot": 1,
    "efficiency": 0,
    "status": 1,
    "trends": 0,
    "stage": 1,
    "atria": 0,
    "workspace": 0,
    "piezo": 1,
    "fft": 0,
    "tasks": 0,
}

TILE_SHAPES: dict[str, str] = {
    "beam": "rounded",
    "camera": "rounded",
    "roi_snapshot": "rounded",
    "efficiency": "rounded",
    "status": "rounded",
    "trends": "rounded",
    "stage": "rounded",
    "atria": "rounded",
    "workspace": "rounded",
    "piezo": "rounded",
    "fft": "rounded",
    "tasks": "rounded",
}

TILE_MIN_SIZES: dict[str, tuple[int, int]] = {
    "camera": (240, 360),
    "roi_snapshot": (240, 360),
    "beam": (240, 220),
    "atria": (280, 260),
    "trends": (240, 160),
    "efficiency": (180, 200),
    "status": (180, 200),
    "stage": (220, 320),
    "workspace": (320, 280),
    "piezo": (260, 220),
    "fft": (260, 220),
    "tasks": (260, 220),
}
DEFAULT_MIN_SIZE = (160, 140)

NON_SNAPPING_TILES = frozenset({"workspace"})

RESIZE_MARGIN = 10


class HubTile(QWidget):
    """Draggable, resizable panel inside the IA workspace."""

    tile_closed = Signal(str)
    tile_drag_released = Signal(str)
    tile_double_clicked = Signal(str)
    tile_resized = Signal(str)
    tile_visibility_changed = Signal(str, bool)  # (tile_id, is_visible)

    def __init__(
        self,
        tile_id: str,
        title: str,
        content: QWidget,
        dashboard=None,
        workspace: QWidget | None = None,
    ) -> None:
        super().__init__(workspace)
        self.tile_id = tile_id
        self._dashboard = dashboard
        self._workspace = workspace
        self._content = content
        from gui.ui_scale import tile_min_size

        min_w, min_h = tile_min_size(tile_id)
        self.setMinimumSize(min_w, min_h)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(content)

        self._drag_pos: QPoint | None = None
        self._dragging = False
        self._resizing = False
        self._resize_edge: str | None = None
        self._resize_start: QRect | None = None
        self._resize_origin: QPoint | None = None
        self._app_shutdown = False
        self._minimized = False
        self._saved_geometry: QRect | None = None
        self._drag_start_geometry: QRect | None = None
        self._free_drag_placement = False
        self._pre_maximize_geometry: QRect | None = None
        self._workspace_maximized = False

        if isinstance(content, GlassPanel):
            content.set_interlock_phase(TILE_INTERLOCK.get(tile_id, 0))
            content.set_tile_shape(TILE_SHAPES.get(tile_id, "rounded"))
            content.attach_hub_tile(self)
            self._relax_content_minimums(content)
            content.setMouseTracking(True)
            content.installEventFilter(self)
            self._install_child_filters(content)
            header = content.header_widget()
            if header is not None:
                header.installEventFilter(self)

    def content_panel(self) -> GlassPanel | None:
        return self._content if isinstance(self._content, GlassPanel) else None

    def min_size(self) -> tuple[int, int]:
        return TILE_MIN_SIZES.get(self.tile_id, DEFAULT_MIN_SIZE)

    def _panel(self) -> GlassPanel | None:
        return self.content_panel()

    def _header(self):
        panel = self._panel()
        return panel.header_widget() if panel else None

    def _workspace_bounds(self) -> QRect:
        if self._dashboard is not None and hasattr(self._dashboard, "_tile_layout"):
            return self._dashboard._tile_layout.workspace_rect()
        parent = self.parentWidget()
        return parent.rect() if parent is not None else self.rect()

    def _clamp_rect(self, rect: QRect) -> QRect:
        bounds = self._workspace_bounds()
        min_w, min_h = self.min_size()
        width = max(min_w, min(rect.width(), bounds.width()))
        height = max(min_h, min(rect.height(), bounds.height()))
        max_x = bounds.right() - width + 1
        max_y = bounds.bottom() - height + 1
        x = max(bounds.left(), min(rect.x(), max_x))
        y = max(bounds.top(), min(rect.y(), max_y))
        return QRect(x, y, width, height)

    def _install_child_filters(self, widget: QWidget) -> None:
        header = self._header()
        for child in widget.findChildren(QWidget):
            if child is header:
                continue
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def _event_on_tile(self, obj) -> bool:
        panel = self._panel()
        header = self._header()
        if panel is None:
            return False
        if obj is self or obj is panel or obj is header:
            return True
        return panel.isAncestorOf(obj)

    def _mouse_event_tile_pos(self, obj, event: QMouseEvent) -> QPoint:
        global_pos = obj.mapToGlobal(event.position().toPoint())
        return self.mapFromGlobal(global_pos)

    def _header_drag_zone(self, header, pos: QPoint) -> bool:
        child = header.childAt(pos)
        if isinstance(child, QPushButton):
            return False
        return header.rect().contains(pos)

    def _header_zone_in_tile(self, tile_pos: QPoint) -> bool:
        header = self._header()
        if header is None:
            return False
        header_top_left = header.mapTo(self, QPoint(0, 0))
        header_rect = QRect(header_top_left, header.size())
        return header_rect.contains(tile_pos)

    def _hit_test_resize(self, pos: QPoint) -> str | None:
        if self._header_zone_in_tile(pos):
            return None
        w, h = self.width(), self.height()
        m = RESIZE_MARGIN
        on_l = pos.x() <= m
        on_r = pos.x() >= w - m
        on_t = pos.y() <= m
        on_b = pos.y() >= h - m
        if not (on_l or on_r or on_t or on_b):
            return None
        if on_t and on_l:
            return "nw"
        if on_t and on_r:
            return "ne"
        if on_b and on_l:
            return "sw"
        if on_b and on_r:
            return "se"
        if on_t:
            return "n"
        if on_b:
            return "s"
        if on_l:
            return "w"
        return "e"

    def _cursor_for_edge(self, edge: str | None) -> Qt.CursorShape:
        mapping = {
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
        }
        return mapping.get(edge or "", Qt.CursorShape.ArrowCursor)

    def _apply_resize(self, global_pos: QPoint) -> None:
        if self._resize_edge is None or self._resize_start is None or self._resize_origin is None:
            return
        delta = global_pos - self._resize_origin
        rect = QRect(self._resize_start)
        edge = self._resize_edge
        min_w, min_h = self.min_size()

        if "e" in edge:
            rect.setWidth(max(min_w, rect.width() + delta.x()))
        if "s" in edge:
            rect.setHeight(max(min_h, rect.height() + delta.y()))
        if "w" in edge:
            new_w = max(min_w, rect.width() - delta.x())
            rect.setX(rect.x() + rect.width() - new_w)
            rect.setWidth(new_w)
        if "n" in edge:
            new_h = max(min_h, rect.height() - delta.y())
            rect.setY(rect.y() + rect.height() - new_h)
            rect.setHeight(new_h)

        self.setGeometry(self._clamp_rect(rect))

    def _relax_content_minimums(self, widget: QWidget) -> None:
        header = self._header()
        if header is not None:
            header.setMinimumHeight(PanelHeader.HEADER_HEIGHT)
            header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for child in widget.findChildren(QWidget):
            if self._is_in_header_tree(child, header):
                continue
            if getattr(child, "_subsection_header", False):
                continue
            if getattr(child, "_chat_message", False) or getattr(child, "_chat_scroll", False):
                continue
            if isinstance(child, (QLineEdit, QPushButton, QCheckBox, QTextEdit, QPlainTextEdit, QLabel)):
                continue
            composer_footer = getattr(widget, "_composer_footer", None)
            if composer_footer is not None and (
                child is composer_footer or composer_footer.isAncestorOf(child)
            ):
                continue
            child.setMinimumSize(0, 0)
            child.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    @staticmethod
    def _is_in_header_tree(widget: QWidget, header: QWidget | None) -> bool:
        if header is None:
            return False
        node: QWidget | None = widget
        while node is not None:
            if node is header:
                return True
            node = node.parentWidget()
        return False

    def _header_has_button(self, header, event: QMouseEvent) -> bool:
        if header is None:
            return False
        child = header.childAt(event.position().toPoint())
        return isinstance(child, QPushButton)

    def _move_to_global_top_left(self, global_top_left: QPoint) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        local = parent.mapFromGlobal(global_top_left)
        self.setGeometry(self._clamp_rect(QRect(local, self.size())))
        if (
            not self._free_drag_placement
            and self.tile_id not in NON_SNAPPING_TILES
            and self._dashboard is not None
            and hasattr(self._dashboard, "snap_tile_to_grid")
        ):
            self._dashboard.snap_tile_to_grid(self.tile_id)

    def eventFilter(self, obj, event) -> bool:
        if not self._event_on_tile(obj):
            return super().eventFilter(obj, event)

        panel = self._panel()
        header = self._header()
        is_header = header is not None and obj is header

        if is_header and isinstance(event, QMouseEvent) and self._header_has_button(header, event):
            return False

        et = event.type()
        if et == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            tile_pos = self._mouse_event_tile_pos(obj, event)
            if not self._dragging and not self._resizing:
                edge = self._hit_test_resize(tile_pos)
                cursor = self._cursor_for_edge(edge)
                if panel is not None:
                    panel.setCursor(QCursor(cursor))
                obj.setCursor(QCursor(cursor))
            if self._resizing and event.buttons() & Qt.MouseButton.LeftButton:
                self._apply_resize(event.globalPosition().toPoint())
                return True
            if is_header and event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
                self._workspace_maximized = False
                self._move_to_global_top_left(event.globalPosition().toPoint() - self._drag_pos)
                self._dragging = True
                return True

        if et == QEvent.Type.MouseButtonDblClick and isinstance(event, QMouseEvent):
            if (
                is_header
                and event.button() == Qt.MouseButton.LeftButton
                and self._header_drag_zone(header, event.position().toPoint())
            ):
                self.notify_double_clicked()
                return True

        if et not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ) or not isinstance(event, QMouseEvent):
            return super().eventFilter(obj, event)

        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            tile_pos = self._mouse_event_tile_pos(obj, event)
            edge = self._hit_test_resize(tile_pos)
            if edge is not None and not is_header:
                self._workspace_maximized = False
                self._resizing = True
                self._resize_edge = edge
                self._resize_start = self.geometry()
                self._resize_origin = event.globalPosition().toPoint()
                obj.grabMouse()
                self.raise_()
                return True

            if is_header and self._header_drag_zone(header, event.position().toPoint()):
                if self._workspace_maximized:
                    self.toggle_maximize()
                self._drag_start_geometry = self.geometry()
                # Shift disables grid snap for this drag; dashboard reads the flag on release.
                self._free_drag_placement = bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                )
                self._drag_pos = event.globalPosition().toPoint() - self.mapToGlobal(QPoint(0, 0))
                self._dragging = False
                header.grabMouse()
                self.raise_()
                return True

            return super().eventFilter(obj, event)

        if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            handled = False
            if obj.mouseGrabber() is obj:
                obj.releaseMouse()
            if self._resizing:
                self._resizing = False
                self._resize_edge = None
                self._resize_start = None
                self._resize_origin = None
                self.tile_resized.emit(self.tile_id)
                handled = True
            elif self._dragging:
                self.notify_drag_released()
                handled = True
            self._drag_pos = None
            self._dragging = False
            return handled

        return super().eventFilter(obj, event)

    def minimize_to_bar(self) -> None:
        dash = self._dashboard
        if dash is not None and hasattr(dash, "minimize_tile"):
            dash.minimize_tile(self.tile_id)

    def restore_from_bar(self) -> None:
        dash = self._dashboard
        if dash is not None and hasattr(dash, "restore_tile_from_bar"):
            dash.restore_tile_from_bar(self.tile_id)

    def toggle_maximize(self) -> None:
        if getattr(self, "_minimized", False):
            self.restore_from_bar()
            return

        panel_header = self._header()
        bounds = self._workspace_bounds()

        if self._workspace_maximized:
            if self._pre_maximize_geometry is not None:
                self.setGeometry(self._clamp_rect(self._pre_maximize_geometry))
            self._workspace_maximized = False
            self._pre_maximize_geometry = None
        else:
            self._pre_maximize_geometry = self.geometry()
            self.setGeometry(bounds)
            self._workspace_maximized = True

        if panel_header is not None:
            panel_header.set_maximized_state(self._workspace_maximized)
        self.raise_()

    def _hub_shutting_down(self) -> bool:
        return bool(getattr(self._dashboard, "_shutting_down", False))

    def shutdown(self) -> None:
        self._app_shutdown = True
        self.hide()

    def notify_drag_released(self) -> None:
        self.tile_drag_released.emit(self.tile_id)

    def notify_double_clicked(self) -> None:
        self.tile_double_clicked.emit(self.tile_id)

    def closeEvent(self, event) -> None:
        if self._app_shutdown or self._hub_shutting_down():
            event.accept()
            return
        self.tile_closed.emit(self.tile_id)
        self.hide()
        event.ignore()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not (self._app_shutdown or self._hub_shutting_down()):
            self.tile_visibility_changed.emit(self.tile_id, True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not (self._app_shutdown or self._hub_shutting_down()):
            self.tile_visibility_changed.emit(self.tile_id, False)
