"""Live camera feed with ROI modes, coupling overlay, and snapshot actions."""

from __future__ import annotations

from enum import Enum

import numpy as np
from PySide6.QtCore import Qt, Signal, QPoint, QRectF
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QPixmap, QFont, QPainterPath
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QComboBox, QSizePolicy, QWidget,
    QLabel, QDoubleSpinBox, QLineEdit, QPushButton,
)

from gui.glass_panel import GlassPanel, PentagonButton, smooth_viewport_path
from gui.typography import body_pt, TEXT_MUTED, TEXT_PRIMARY, muted_style
from gui.ui_scale import get_scale, px
from gui.heatmap import colormap_rgb_at, intensity_centroid, intensity_to_rgb, padded_roi_crop
from gui.neon_theme import (
    draw_multicolor_glow,
    draw_neon_border,
    COLOR_CYAN,
    COLOR_PINK,
    COLOR_MAGENTA,
    COLOR_HOT,
    COLOR_VIOLET,
    NEON_CYAN,
    NEON_PURPLE,
    VIEWPORT_FILL_ALPHA,
)
from core.analytics.beam import to_grayscale

_VIEWPORT_CORNER_RADIUS = 8
_COLORBAR_WIDTH = 22


_FIELD_STYLE = (
    "QComboBox, QDoubleSpinBox {"
    "  min-height: 26px;"
    "  padding: 2px 6px;"
    "  background: rgba(18,8,40,0.85);"
    "  color: " + TEXT_PRIMARY + ";"
    "  border: 1px solid " + NEON_PURPLE + ";"
    "  border-radius: 4px;"
    "}"
    "QComboBox::drop-down { border: none; width: 20px; }"
    "QComboBox QAbstractItemView {"
    "  background: rgba(12,8,32,0.97);"
    "  color: " + TEXT_PRIMARY + ";"
    "  selection-background-color: rgba(168,85,247,0.45);"
    "}"
)

_EDIT_STYLE = (
    "QLineEdit {"
    "  min-height: 20px; padding: 1px 5px;"
    "  background: rgba(18,8,40,0.95); color: " + TEXT_PRIMARY + ";"
    "  border: 1px solid " + NEON_CYAN + "; border-radius: 3px;"
    "}"
)


class _EditableLabel(QWidget):
    """Camera slot label with inline ✎ rename."""

    label_changed = Signal(str)

    def __init__(self, text: str = "", serial_hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self._text = text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self._label = QLabel(text)
        self._label.setStyleSheet(
            "QLabel { font-weight: bold; color: " + TEXT_PRIMARY + "; font-size: 11px; }"
        )
        self._edit = QLineEdit(text)
        self._edit.setStyleSheet(_EDIT_STYLE)
        self._edit.setMaximumWidth(140)
        self._edit.hide()
        self._edit.returnPressed.connect(self._commit)
        self._edit.editingFinished.connect(self._commit)

        pen_btn = QPushButton("✎")
        pen_btn.setFixedSize(16, 16)
        pen_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: " + NEON_PURPLE + "; font-size: 10px; }"
            "QPushButton:hover { color: " + NEON_CYAN + "; }"
        )
        pen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pen_btn.clicked.connect(self._start_edit)

        layout.addWidget(self._label)
        layout.addWidget(self._edit)
        layout.addWidget(pen_btn)
        layout.addStretch()

        self.set_serial(serial_hint)

    def set_serial(self, serial: str) -> None:
        tip = f"Serial: {serial}" if serial else "Serial: (not yet assigned)"
        self._label.setToolTip(tip)

    def set_text(self, text: str) -> None:
        self._text = text
        self._label.setText(text)
        self._edit.setText(text)

    def text(self) -> str:
        return self._text

    def _start_edit(self) -> None:
        self._label.hide()
        self._edit.setText(self._text)
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _commit(self) -> None:
        if not self._edit.isVisible():
            return
        new = self._edit.text().strip() or self._text
        self._text = new
        self._label.setText(new)
        self._label.show()
        self._edit.hide()
        self.label_changed.emit(new)


class RoiMode(str, Enum):
    BEAM = "beam"
    FRINGE = "fringe"


class OctagonalViewport(QWidget):
    """Camera display clipped to a smooth rounded rect with glow ring and targeting reticle."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pixmap: QPixmap | None = None
        self._idle_text = ""
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._full_size = (1440, 1080)
        self._coupling: dict | None = None

    def _viewport_path(self, rect: QRectF) -> QPainterPath:
        radius = px(_VIEWPORT_CORNER_RADIUS, get_scale())
        return smooth_viewport_path(rect, radius)

    def set_coupling_overlay(self, overlay: dict | None) -> None:
        self._coupling = overlay
        self.update()

    def set_idle(self, text: str) -> None:
        self._pixmap = None
        self._idle_text = text
        self._coupling = None
        self.update()

    def set_frame_pixmap(
        self,
        pixmap: QPixmap,
        *,
        scale: float,
        offset_x: int,
        offset_y: int,
        full_size: tuple[int, int],
    ) -> None:
        self._pixmap = pixmap
        self._idle_text = ""
        self._scale = scale
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._full_size = full_size
        self.update()

    def viewport_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def _to_display(self, sx: float, sy: float) -> tuple[int, int]:
        return int(self._offset_x + sx * self._scale), int(self._offset_y + sy * self._scale)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.viewport_rect()
        path = self._viewport_path(rect)

        draw_multicolor_glow(painter, path)
        painter.fillPath(path, QColor(12, 8, 32, VIEWPORT_FILL_ALPHA))

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.setClipPath(path)
            painter.drawPixmap(self._offset_x, self._offset_y, self._pixmap)
            painter.setClipping(False)

            if self._coupling is not None:
                self._paint_coupling_overlay(painter)

        if self._idle_text:
            painter.setPen(QColor(TEXT_MUTED))
            font = QFont("Segoe UI", max(8, int(body_pt())))
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._idle_text)

        draw_neon_border(painter, path)

    def _paint_coupling_overlay(self, painter: QPainter) -> None:
        c = self._coupling
        if not c:
            return
        tx, ty = c["target_center_px"]
        cx, cy = c["centroid_px"]
        r = c["target_radius_px"]
        dtx, dty = self._to_display(tx, ty)
        dcx, dcy = self._to_display(cx, cy)
        dr = max(4, int(r * self._scale))

        for ring_scale, color in ((1.0, COLOR_CYAN), (0.55, COLOR_PINK)):
            rr = int(dr * ring_scale)
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(dtx - rr, dty - rr, 2 * rr, 2 * rr)

        painter.setPen(QPen(QColor(255, 220, 80, 240), 2))
        painter.drawLine(dcx - 16, dcy, dcx + 16, dcy)
        painter.drawLine(dcx, dcy - 16, dcx, dcy + 16)

        painter.setPen(QPen(COLOR_HOT, 3))
        painter.drawLine(dtx, dty, dcx, dcy)
        err_um = c.get("error_um", 0.0)
        painter.setPen(COLOR_MAGENTA)
        painter.drawText(dcx + 8, dcy - 8, f"Δ {err_um:.1f} µm")


class SnapshotRoiViewport(QWidget):
    """Frozen frame with draggable ROI; rounded viewport matching live feed."""

    roi_changed = Signal(tuple)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._frame: np.ndarray | None = None
        self._roi: tuple[int, int, int, int] = (0, 0, 100, 100)
        self._mode = RoiMode.BEAM
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._full_size = (1440, 1080)
        self._dragging = False
        self._resizing = False
        self._drag_start = QPoint()
        self._roi_start = self._roi
        self._crop_origin = (0, 0)
        self._idle_text = "Snap a frame to set ROI here"

    def viewport_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def _viewport_path(self):
        radius = px(_VIEWPORT_CORNER_RADIUS, get_scale())
        return smooth_viewport_path(self.viewport_rect(), radius)

    def _point_in_viewport(self, pos: QPoint) -> bool:
        return self._viewport_path().contains(pos)

    def set_mode(self, mode: RoiMode) -> None:
        self._mode = mode
        self.update()

    def set_frame(self, frame: np.ndarray | None, roi: tuple[int, int, int, int]) -> None:
        self._frame = frame
        self._roi = roi
        if frame is not None:
            self._idle_text = ""
        self.update()

    def clear(self) -> None:
        self._frame = None
        self._idle_text = "Snap a frame to set ROI here"
        self.update()

    def current_roi(self) -> tuple[int, int, int, int]:
        return self._roi

    def _map_to_sensor(self, pos: QPoint) -> tuple[int, int]:
        local_x = int((pos.x() - self._offset_x) / max(self._scale, 1e-9))
        local_y = int((pos.y() - self._offset_y) / max(self._scale, 1e-9))
        ox, oy = self._crop_origin
        w, h = self._full_size
        x = ox + local_x
        y = oy + local_y
        return max(0, min(w - 1, x)), max(0, min(h - 1, y))

    def mousePressEvent(self, event) -> None:
        if self._frame is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if not self._point_in_viewport(pos):
            return
        self._dragging = True
        self._drag_start = event.position().toPoint()
        self._roi_start = self._roi
        x, y = self._map_to_sensor(self._drag_start)
        rx, ry, rw, rh = self._roi
        self._resizing = x > rx + rw - 15 and y > ry + rh - 15

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging or self._frame is None:
            return
        cur = event.position().toPoint()
        dx = int((cur.x() - self._drag_start.x()) / max(self._scale, 1e-9))
        dy = int((cur.y() - self._drag_start.y()) / max(self._scale, 1e-9))
        rx, ry, rw, rh = self._roi_start
        w_full, h_full = self._full_size
        if self._resizing:
            rw = max(20, min(w_full - rx, rw + dx))
            rh = max(20, min(h_full - ry, rh + dy))
        else:
            rx = max(0, min(w_full - rw, rx + dx))
            ry = max(0, min(h_full - rh, ry + dy))
        self._roi = (rx, ry, rw, rh)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.roi_changed.emit(self._roi)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.viewport_rect()
        path = self._viewport_path()

        draw_multicolor_glow(painter, path)
        painter.fillPath(path, QColor(12, 8, 32, VIEWPORT_FILL_ALPHA))

        if self._frame is None:
            painter.setPen(QColor(TEXT_MUTED))
            font = QFont("Segoe UI", max(8, int(body_pt())))
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._idle_text)
            draw_neon_border(painter, path)
            return

        painter.setClipPath(path)

        gray = to_grayscale(self._frame)
        full_h, full_w = gray.shape
        self._full_size = (full_w, full_h)

        crop_gray, crop_x0, crop_y0 = padded_roi_crop(gray, self._roi)
        self._crop_origin = (crop_x0, crop_y0)
        rgb, lo, hi = intensity_to_rgb(crop_gray)
        ch, cw = rgb.shape[:2]
        bytes_per_line = 3 * cw
        qimg = QImage(rgb.data, cw, ch, bytes_per_line, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())

        inner = rect.adjusted(10, 10, -(_COLORBAR_WIDTH + 14), -10)
        scaled = pix.scaled(
            int(inner.width()),
            int(inner.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        dx = int(inner.x() + (inner.width() - scaled.width()) // 2)
        dy = int(inner.y() + (inner.height() - scaled.height()) // 2)
        painter.drawPixmap(dx, dy, scaled)
        self._offset_x = dx
        self._offset_y = dy
        self._scale = scaled.width() / cw

        rx, ry, rw, rh = self._roi
        roi_lx = rx - crop_x0
        roi_ly = ry - crop_y0
        sx = int(self._offset_x + roi_lx * self._scale)
        sy = int(self._offset_y + roi_ly * self._scale)
        sw = int(rw * self._scale)
        sh = int(rh * self._scale)

        cx, cy = intensity_centroid(gray, self._roi)
        clx = cx - crop_x0
        cly = cy - crop_y0
        csx = int(self._offset_x + clx * self._scale)
        csy = int(self._offset_y + cly * self._scale)

        dash = QPen(QColor(255, 255, 255, 200), 1, Qt.PenStyle.DashLine)
        painter.setPen(dash)
        painter.drawLine(sx, csy, sx + sw, csy)
        painter.drawLine(csx, sy, csx, sy + sh)

        color = COLOR_CYAN if self._mode == RoiMode.BEAM else COLOR_VIOLET
        painter.setPen(QPen(color, 2))
        painter.drawRect(sx, sy, sw, sh)

        painter.setClipping(False)
        self._paint_colorbar(painter, rect, lo, hi)
        draw_neon_border(painter, path)

    def _paint_colorbar(
        self,
        painter: QPainter,
        outer: QRectF,
        lo: float,
        hi: float,
    ) -> None:
        bar = QRectF(
            outer.right() - _COLORBAR_WIDTH - 4,
            outer.y() + 8,
            _COLORBAR_WIDTH - 4,
            outer.height() - 16,
        )
        steps = max(16, int(bar.height()))
        for i in range(steps):
            t = 1.0 - i / max(steps - 1, 1)
            r, g, b = colormap_rgb_at(t)
            c = QColor(r, g, b)
            y = bar.y() + i * bar.height() / steps
            painter.fillRect(
                int(bar.x()),
                int(y),
                int(bar.width()),
                int(bar.height() / steps) + 1,
                c,
            )
        painter.setPen(QPen(QColor(TEXT_MUTED), 1))
        painter.drawRect(bar)
        painter.setPen(QColor(TEXT_PRIMARY))
        font = QFont("Consolas", max(8, int(body_pt())))
        painter.setFont(font)
        painter.drawText(int(bar.right() + 2), int(bar.y() + 10), f"{hi:.0f}")
        painter.drawText(int(bar.right() + 2), int(bar.bottom()), f"{lo:.0f}")


def render_frame_to_viewport(
    viewport: OctagonalViewport,
    frame: np.ndarray,
    *,
    roi: tuple[int, int, int, int] | None = None,
    roi_mode: "RoiMode" = RoiMode.BEAM,
) -> None:
    """Scale ``frame`` into ``viewport`` (optionally drawing the ROI box).

    Shared by the in-tile panes and the popped-out camera tiles so every
    surface renders a role identically.
    """
    pix, w, h = _frame_to_pixmap(frame)
    if roi is not None:
        painter = QPainter(pix)
        x, y, rw, rh = roi
        color = COLOR_CYAN if roi_mode == RoiMode.BEAM else COLOR_VIOLET
        painter.setPen(QPen(color, 2))
        painter.drawRect(x, y, rw, rh)
        painter.end()

    rect = viewport.viewport_rect()
    target = rect.adjusted(10, 10, -10, -10)
    scaled = pix.scaled(
        max(1, int(target.width())),
        max(1, int(target.height())),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    viewport.set_frame_pixmap(
        scaled,
        scale=scaled.width() / w,
        offset_x=int(target.x() + (target.width() - scaled.width()) / 2),
        offset_y=int(target.y() + (target.height() - scaled.height()) / 2),
        full_size=(w, h),
    )


_PANE_BTN_STYLE = (
    "QPushButton { background: rgba(18,8,40,0.7); border: 1px solid " + NEON_PURPLE + "; "
    "border-radius: 4px; color: #d9c9ff; font-size: 11px; padding: 1px 6px; }"
    "QPushButton:hover { border-color: " + NEON_CYAN + "; color: " + NEON_CYAN + "; }"
)


class RoleCameraPane(QWidget):
    """One camera role: editable label, viewport, promote + pop-out buttons.

    A single pane object is reused whether it sits in the primary slot, the
    thumbnail strip, or a popped-out tile, so frame routing never has to care
    where the pane currently lives.
    """

    promote_clicked = Signal(str)   # role value
    popout_clicked = Signal(str)    # role value
    camera_selection_changed = Signal(str, str)   # (role value, serial or "" for auto)

    def __init__(self, role, hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.role = role
        self._popped = False
        self._is_primary = True
        self._assigned_serial: str | None = None
        self._available_serials: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(4)
        self._label = _EditableLabel(role.label, "")
        head.addWidget(self._label)
        cam_lbl = QLabel("Cam:")
        cam_lbl.setStyleSheet(muted_style())
        head.addWidget(cam_lbl)
        self._cam_combo = QComboBox()
        self._cam_combo.setStyleSheet(_FIELD_STYLE)
        self._cam_combo.setMinimumWidth(88)
        self._cam_combo.setToolTip("Pick which physical camera feeds this role")
        self._cam_combo.currentIndexChanged.connect(self._on_cam_combo_changed)
        head.addWidget(self._cam_combo)
        head.addStretch()
        self._promote_btn = QPushButton("▣ view")
        self._promote_btn.setToolTip("Show this camera as the primary (large) view")
        self._promote_btn.setStyleSheet(_PANE_BTN_STYLE)
        self._promote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._promote_btn.clicked.connect(lambda: self.promote_clicked.emit(self.role.value))
        head.addWidget(self._promote_btn)
        self._popout_btn = QPushButton("⤢ pop out")
        self._popout_btn.setToolTip("Pull this camera into its own draggable tile")
        self._popout_btn.setStyleSheet(_PANE_BTN_STYLE)
        self._popout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._popout_btn.clicked.connect(lambda: self.popout_clicked.emit(self.role.value))
        head.addWidget(self._popout_btn)
        outer.addLayout(head)

        self._hint = QLabel(hint)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(muted_style())
        self._hint.setVisible(bool(hint))
        outer.addWidget(self._hint)

        self.viewport = OctagonalViewport()
        outer.addWidget(self.viewport, stretch=1)

        self._metric_label = QLabel("")
        self._metric_label.setStyleSheet(muted_style())
        self._metric_label.setVisible(False)
        outer.addWidget(self._metric_label)

    # -- appearance --------------------------------------------------------
    def set_primary(self, is_primary: bool) -> None:
        self._is_primary = is_primary
        self._hint.setVisible(is_primary and bool(self._hint.text()))
        self._metric_label.setVisible(is_primary and bool(self._metric_label.text()))
        self._promote_btn.setVisible(not is_primary and not self._popped)
        if is_primary:
            self.setMaximumHeight(16_777_215)
        else:
            self.setMaximumHeight(190)

    def set_popped(self, popped: bool) -> None:
        self._popped = popped
        self._popout_btn.setText("⤡ pop in" if popped else "⤢ pop out")
        self._popout_btn.setToolTip(
            "Return this camera to the Bench Cameras tile" if popped
            else "Pull this camera into its own draggable tile"
        )
        self._promote_btn.setVisible(not popped and not self._is_primary)

    def set_label(self, text: str) -> None:
        self._label.set_text(text)

    def set_serial(self, serial: str) -> None:
        self._label.set_serial(serial)
        self._assigned_serial = serial or None
        self._rebuild_cam_combo()

    # -- physical camera picker --------------------------------------------
    def set_available_cameras(self, serials: list[str]) -> None:
        self._available_serials = list(serials)
        self._rebuild_cam_combo()

    def disable_serial_in_combo(self, serial: str) -> None:
        """Grey out ``serial`` in this pane's picker (assigned to another role)."""
        idx = self._cam_combo.findData(serial)
        if idx >= 0 and idx != self._cam_combo.currentIndex():
            item = self._cam_combo.model().item(idx)
            if item is not None:
                item.setEnabled(False)

    def assigned_serial(self) -> str | None:
        return self._assigned_serial

    def _rebuild_cam_combo(self) -> None:
        self._cam_combo.blockSignals(True)
        self._cam_combo.clear()
        self._cam_combo.addItem("Auto (first found)", "")
        for s in self._available_serials:
            self._cam_combo.addItem(s, s)
        idx = 0
        if self._assigned_serial:
            found = self._cam_combo.findData(self._assigned_serial)
            if found < 0:
                self._cam_combo.addItem(self._assigned_serial, self._assigned_serial)
                found = self._cam_combo.count() - 1
            idx = found
        self._cam_combo.setCurrentIndex(idx)
        self._cam_combo.blockSignals(False)

    def _on_cam_combo_changed(self) -> None:
        serial = self._cam_combo.currentData() or ""
        self._assigned_serial = serial or None
        self.camera_selection_changed.emit(self.role.value, serial)

    def set_metric(self, text: str) -> None:
        self._metric_label.setText(text)
        self._metric_label.setVisible(bool(text) and self._is_primary)

    def label_widget(self) -> "_EditableLabel":
        return self._label


class CameraView(GlassPanel):
    """Role-aware bench camera tile: Far Field / Image / Output.

    Shows one primary (large) feed plus thumbnails of the rest; click a
    thumbnail's ``▣ view`` to promote it, or ``⤢ pop out`` to tear a camera
    into its own tile (the dashboard creates the tile and the home view
    reflows to the remaining feeds).
    """

    snapshot_captured = Signal(object)
    snap_requested = Signal()
    live_feed_toggled = Signal(bool)
    camera_settings_changed = Signal(object)   # dict; includes "role"
    camera_label_changed = Signal(str, str)    # (role value, new_label)
    primary_role_changed = Signal(str)         # role value
    popout_requested = Signal(str)             # role value
    popin_requested = Signal(str)              # role value
    camera_selection_changed = Signal(str, str)  # (role value, serial or "" for auto)
    refresh_cameras_requested = Signal()

    _DEFAULT_CAM_STATE: dict = {
        "exposure_us": 10_000.0, "fps_auto": True, "fps_hz": 30.0,
        "exp_min_us": 10.0, "exp_max_us": 1_000_000.0,
        "fps_min": 1.0, "fps_max": 120.0, "measured_fps": None,
        "color_sensor": True, "wb_rgb": (1.0, 1.0, 1.0),
    }

    _ROLE_HINTS: dict = {
        "far_field": "Wedge ghost · coupling reticle (450 µm fiber bore)",
        "image": "Ghost 2 imaging plane: pending mentor optics spec",
        "output": "Post-fiber camera · transmitted power for η",
    }

    def __init__(self, parent=None) -> None:
        from core.camera_roles import ACTIVE_ROLES, CameraRole

        super().__init__(parent, title="Bench Cameras")
        self._roles = list(ACTIVE_ROLES)
        self._CameraRole = CameraRole
        self._live_active = False
        self._simulation_feed = False
        self._frames: dict = {r: None for r in self._roles}
        self._rois: dict = {r: (636, 534, 101, 101) for r in self._roles}
        self._mode = RoiMode.BEAM
        self._primary_role = self._roles[0]
        self._settings_role = self._roles[0]
        self._popped: set = set()
        self._block_settings_signals = False
        self._cam_state: dict = {r: dict(self._DEFAULT_CAM_STATE) for r in self._roles}
        self._available_serials: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*self.content_margins())
        layout.setSpacing(6)

        layout.addLayout(self._build_top_row())
        layout.addLayout(self._build_settings_row())
        layout.addWidget(self._build_wb_row())

        # ── Panes (one stable pane per role) ─────────────────────────────
        self._panes: dict = {}
        for role in self._roles:
            pane = RoleCameraPane(role, self._ROLE_HINTS.get(role.value, ""))
            pane.promote_clicked.connect(self._on_promote_clicked)
            pane.popout_clicked.connect(self._on_popout_clicked)
            pane.label_widget().label_changed.connect(
                lambda t, rv=role.value: self.camera_label_changed.emit(rv, t)
            )
            pane.camera_selection_changed.connect(self._on_pane_camera_selection_changed)
            self._panes[role] = pane

        self._primary_holder = QWidget()
        self._primary_slot = QVBoxLayout(self._primary_holder)
        self._primary_slot.setContentsMargins(0, 0, 0, 0)
        self._thumb_holder = QWidget()
        self._thumb_row = QHBoxLayout(self._thumb_holder)
        self._thumb_row.setContentsMargins(0, 0, 0, 0)
        self._thumb_row.setSpacing(8)

        vp = QVBoxLayout()
        vp.setContentsMargins(0, 0, 0, 0)
        vp.setSpacing(6)
        vp.addWidget(self._primary_holder, stretch=1)
        vp.addWidget(self._thumb_holder)
        layout.addLayout(vp, stretch=1)

        self._sync_primary_combo()
        self._relayout_panes()
        self._select_settings_role(self._settings_role, _refresh_ui=False)
        self.show_idle()

    # ── UI construction ──────────────────────────────────────────────────
    def _build_top_row(self):
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        prim_lbl = QLabel("Primary:")
        prim_lbl.setStyleSheet(muted_style())
        r1.addWidget(prim_lbl)
        self._primary_combo = QComboBox()
        self._primary_combo.setToolTip("Choose which camera shows large in the primary view")
        self._primary_combo.setStyleSheet(_FIELD_STYLE)
        self._primary_combo.currentIndexChanged.connect(self._on_primary_combo_changed)
        r1.addWidget(self._primary_combo)

        # ROI mode combo. Dashboard connects to this directly (kept name).
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Beam waist ROI", RoiMode.BEAM.value)
        self._mode_combo.addItem("Fringe ROI (λ scan)", RoiMode.FRINGE.value)
        self._mode_combo.setToolTip(
            "Beam waist ROI: coupling/η analysis box.\nFringe ROI: legacy λ-scan box."
        )
        self._mode_combo.setStyleSheet(_FIELD_STYLE)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        r1.addWidget(self._mode_combo)

        r1.addStretch()
        self._refresh_cams_btn = PentagonButton("⟳ Cameras", compact=True)
        self._refresh_cams_btn.setToolTip("Rescan for connected cameras")
        self._refresh_cams_btn.clicked.connect(self.refresh_cameras_requested)
        r1.addWidget(self._refresh_cams_btn)
        self._live_btn = PentagonButton("Start Live Feed", compact=True)
        self._live_btn.clicked.connect(self._on_live_clicked)
        r1.addWidget(self._live_btn)
        snap_btn = PentagonButton("Snap Frame", compact=True)
        snap_btn.clicked.connect(self._snap_frame)
        r1.addWidget(snap_btn)
        return r1

    def _build_settings_row(self):
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        settings_lbl = QLabel("Settings:")
        settings_lbl.setStyleSheet(muted_style())
        r2.addWidget(settings_lbl)
        self._role_btns: dict = {}
        for role in self._roles:
            btn = PentagonButton(role.label, compact=True)
            btn.setToolTip(f"Edit exposure, FPS, and white balance for {role.label}")
            btn.clicked.connect(lambda _=False, rr=role: self._select_settings_role(rr))
            self._role_btns[role] = btn
            r2.addWidget(btn)

        exp_lbl = QLabel("Exp µs")
        exp_lbl.setStyleSheet(muted_style())
        r2.addWidget(exp_lbl)
        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setStyleSheet(_FIELD_STYLE)
        self._exp_spin.setRange(10.0, 1_000_000.0)
        self._exp_spin.setDecimals(0)
        self._exp_spin.setSingleStep(100.0)
        self._exp_spin.setValue(10_000.0)
        self._exp_spin.setFixedWidth(88)
        self._exp_spin.valueChanged.connect(self._emit_exposure)
        r2.addWidget(self._exp_spin)

        self._fps_mode = QComboBox()
        self._fps_mode.setStyleSheet(_FIELD_STYLE)
        self._fps_mode.addItem("Auto FPS", True)
        self._fps_mode.addItem("Fixed FPS", False)
        self._fps_mode.setFixedWidth(90)
        self._fps_mode.currentIndexChanged.connect(self._on_fps_mode_changed)
        r2.addWidget(self._fps_mode)
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setStyleSheet(_FIELD_STYLE)
        self._fps_spin.setRange(1.0, 120.0)
        self._fps_spin.setDecimals(1)
        self._fps_spin.setSingleStep(1.0)
        self._fps_spin.setValue(30.0)
        self._fps_spin.setFixedWidth(58)
        self._fps_spin.setEnabled(False)
        self._fps_spin.valueChanged.connect(self._emit_fps)
        r2.addWidget(self._fps_spin)
        self._fps_live = QLabel("— fps")
        self._fps_live.setStyleSheet(muted_style())
        r2.addWidget(self._fps_live)
        r2.addStretch()
        return r2

    def _build_wb_row(self):
        wb_row = QHBoxLayout()
        wb_row.setSpacing(5)
        wb_lbl = QLabel("WB")
        wb_lbl.setStyleSheet(muted_style())
        wb_row.addWidget(wb_lbl)
        self._wb_spins: list[QDoubleSpinBox] = []
        for ch_txt, default in zip(("R", "G", "B"), (1.0, 1.0, 1.0)):
            ch = QLabel(ch_txt)
            ch.setStyleSheet(muted_style())
            wb_row.addWidget(ch)
            sp = QDoubleSpinBox()
            sp.setStyleSheet(_FIELD_STYLE)
            sp.setRange(0.1, 4.0)
            sp.setDecimals(2)
            sp.setSingleStep(0.05)
            sp.setValue(default)
            sp.setFixedWidth(56)
            sp.valueChanged.connect(self._emit_white_balance)
            self._wb_spins.append(sp)
            wb_row.addWidget(sp)
        self._wb_reset = PentagonButton("Default", compact=True)
        self._wb_reset.clicked.connect(self._reset_white_balance)
        wb_row.addWidget(self._wb_reset)
        wb_row.addStretch()
        self._wb_row_widget = QWidget()
        self._wb_row_widget.setLayout(wb_row)
        return self._wb_row_widget

    # ── Pane layout / primary + thumbnails ────────────────────────────────
    def _docked_roles(self) -> list:
        return [r for r in self._roles if r not in self._popped]

    def _relayout_panes(self) -> None:
        for slot in (self._primary_slot, self._thumb_row):
            while slot.count():
                item = slot.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)

        docked = self._docked_roles()
        if not docked:
            self._thumb_holder.setVisible(False)
            return
        if self._primary_role not in docked:
            self._primary_role = docked[0]

        primary = self._panes[self._primary_role]
        primary.set_primary(True)
        primary.setParent(self._primary_holder)
        self._primary_slot.addWidget(primary)
        primary.show()

        thumbs = [r for r in docked if r != self._primary_role]
        for role in thumbs:
            pane = self._panes[role]
            pane.set_primary(False)
            pane.setParent(self._thumb_holder)
            self._thumb_row.addWidget(pane, stretch=1)
            pane.show()
        self._thumb_holder.setVisible(bool(thumbs))
        self._sync_primary_combo()
        for role in docked:
            self._redraw(role)

    def _sync_primary_combo(self) -> None:
        self._block_settings_signals = True
        try:
            self._primary_combo.clear()
            for role in self._docked_roles():
                self._primary_combo.addItem(role.label, role.value)
                if role == self._primary_role:
                    self._primary_combo.setCurrentIndex(self._primary_combo.count() - 1)
        finally:
            self._block_settings_signals = False

    def _on_primary_combo_changed(self) -> None:
        if self._block_settings_signals:
            return
        data = self._primary_combo.currentData()
        if data is None:
            return
        self.set_primary_role(self._CameraRole.coerce(data))

    def _on_promote_clicked(self, role_value: str) -> None:
        self.set_primary_role(self._CameraRole.coerce(role_value))

    def set_primary_role(self, role) -> None:
        if role in self._popped or role not in self._roles:
            return
        if role == self._primary_role:
            return
        self._primary_role = role
        self._relayout_panes()
        self.primary_role_changed.emit(role.value)

    # ── Pop-out (dashboard drives the tile creation) ─────────────────────
    def _on_popout_clicked(self, role_value: str) -> None:
        role = self._CameraRole.coerce(role_value)
        if role in self._popped:
            self.popin_requested.emit(role.value)
        else:
            self.popout_requested.emit(role.value)

    def detach_pane(self, role) -> QWidget | None:
        """Mark a role popped, remove its pane from the home view, return it."""
        pane = self._panes.get(role)
        if pane is None:
            return None
        self._popped.add(role)
        pane.set_popped(True)
        pane.set_primary(True)  # full-size inside its own tile
        self._relayout_panes()
        return pane

    def attach_pane(self, role) -> None:
        """Return a previously popped role's pane to the home view."""
        pane = self._panes.get(role)
        if pane is None:
            return
        self._popped.discard(role)
        pane.set_popped(False)
        self._relayout_panes()

    def is_popped(self, role) -> bool:
        return role in self._popped

    def pane_widget(self, role) -> QWidget | None:
        return self._panes.get(role)

    # ── Settings selector ────────────────────────────────────────────────
    def _select_settings_role(self, role, *, _refresh_ui: bool = True) -> None:
        self._settings_role = role
        active = ("QPushButton { background: rgba(168,85,247,0.4); "
                  "border: 1px solid " + NEON_CYAN + "; color: " + NEON_CYAN + "; }")
        for r, btn in self._role_btns.items():
            btn.setStyleSheet(active if r == role else "")
        if not _refresh_ui:
            return
        s = self._cam_state[role]
        self._block_settings_signals = True
        try:
            self._exp_spin.setRange(s.get("exp_min_us", 10.0), s.get("exp_max_us", 1_000_000.0))
            self._exp_spin.setValue(s["exposure_us"])
            fps_auto = s["fps_auto"]
            self._fps_mode.setCurrentIndex(0 if fps_auto else 1)
            self._fps_spin.setEnabled(not fps_auto)
            self._fps_spin.setRange(s.get("fps_min", 1.0), s.get("fps_max", 120.0))
            if not fps_auto:
                self._fps_spin.setValue(s["fps_hz"])
            measured = s.get("measured_fps")
            self._fps_live.setText(
                f"{measured:.1f} fps" if measured else ("auto" if fps_auto else "— fps")
            )
            color_ok = s["color_sensor"]
            self._wb_row_widget.setVisible(color_ok)
            if color_ok:
                for sp, v in zip(self._wb_spins, s["wb_rgb"]):
                    sp.setValue(v)
        finally:
            self._block_settings_signals = False

    # ── Camera label + serial ────────────────────────────────────────────
    def set_camera_label(self, role, label: str) -> None:
        pane = self._panes.get(self._CameraRole.coerce(role))
        if pane is not None:
            pane.set_label(label)

    def set_camera_serial(self, role, serial: str) -> None:
        role = self._CameraRole.coerce(role)
        pane = self._panes.get(role)
        if pane is not None:
            pane.set_serial(serial)
        btn = self._role_btns.get(role)
        if btn is not None:
            btn.setToolTip(f"Serial: {serial}")
        self._apply_cross_role_exclusivity()

    # ── Physical camera picker (which serial feeds each role) ────────────
    def set_available_cameras(self, serials: list[str]) -> None:
        """Refresh every role's device picker with the currently detected serials."""
        self._available_serials = list(serials)
        for pane in self._panes.values():
            pane.set_available_cameras(self._available_serials)
        self._apply_cross_role_exclusivity()

    def _apply_cross_role_exclusivity(self) -> None:
        """Grey out a serial in every pane's picker except the role it's assigned to."""
        for role, pane in self._panes.items():
            assigned = pane.assigned_serial()
            if not assigned:
                continue
            for other_role, other_pane in self._panes.items():
                if other_role != role:
                    other_pane.disable_serial_in_combo(assigned)

    def _on_pane_camera_selection_changed(self, role_value: str, serial: str) -> None:
        self._apply_cross_role_exclusivity()
        self.camera_selection_changed.emit(role_value, serial)

    # ── Live state ────────────────────────────────────────────────────────
    def _on_live_clicked(self) -> None:
        self._live_active = not self._live_active
        self._live_btn.setText("Stop Live Feed" if self._live_active else "Start Live Feed")
        self.live_feed_toggled.emit(self._live_active)

    def set_live_active(self, active: bool, *, simulation: bool = False) -> None:
        self._live_active = active
        self._simulation_feed = simulation and active
        self._live_btn.setText("Stop Live Feed" if active else "Start Live Feed")

    def show_idle(self) -> None:
        for role in self._roles:
            self._frames[role] = None
            pane = self._panes.get(role)
            if pane is None:
                continue
            if role.value == "image":
                pane.viewport.set_idle(
                    "Image (Ghost 2)\n\nWaiting for optical spec\n(plane, path length, dᵢ)"
                )
            elif role == self._primary_role:
                pane.viewport.set_idle(f"{role.label}\n\nStart live feed or snap a frame.")
            else:
                pane.viewport.set_idle(f"{role.label}\n\nNot active")

    # ── ROI / mode ─────────────────────────────────────────────────────────
    def set_roi(self, roi: tuple[int, int, int, int], mode: RoiMode | None = None) -> None:
        far = self._CameraRole.coerce("far_field")
        self._rois[far] = roi
        if mode is not None:
            self._mode = mode
            self._mode_combo.setCurrentIndex(0 if mode == RoiMode.BEAM else 1)
        self._redraw(far)

    def set_role_roi(self, role, roi: tuple[int, int, int, int]) -> None:
        self._rois[self._CameraRole.coerce(role)] = roi
        self._redraw(self._CameraRole.coerce(role))

    def current_roi(self) -> tuple[int, int, int, int]:
        return self._rois[self._CameraRole.coerce("far_field")]

    def current_mode(self) -> RoiMode:
        return self._mode

    def _on_mode_changed(self) -> None:
        self._mode = RoiMode(self._mode_combo.currentData())

    # ── Frame pipeline ──────────────────────────────────────────────────────
    def current_frame(self, role=None) -> np.ndarray | None:
        role = self._primary_role if role is None else self._CameraRole.coerce(role)
        f = self._frames.get(role)
        return f.copy() if f is not None else None

    def role_frame(self, role) -> np.ndarray | None:
        return self._frames.get(self._CameraRole.coerce(role))

    def _snap_frame(self) -> None:
        frame = self._frames.get(self._settings_role) or self._frames.get(self._primary_role)
        if frame is None:
            self.snap_requested.emit()
            return
        self.snapshot_captured.emit(np.asarray(frame).copy())

    def set_role_frame(self, role, frame: np.ndarray, *, repaint: bool = True) -> None:
        role = self._CameraRole.coerce(role)
        if role not in self._frames:
            return
        self._frames[role] = frame
        if repaint:
            self._redraw(role)

    # Back-compat single-feed helpers (route to the primary role) ------------
    def update_frame(self, frame: np.ndarray, *, repaint: bool = True) -> None:
        self.set_role_frame(self._primary_role, frame, repaint=repaint)

    def store_frame(self, frame: np.ndarray) -> None:
        self.set_role_frame(self._primary_role, frame, repaint=False)

    def _redraw(self, role) -> None:
        frame = self._frames.get(role)
        pane = self._panes.get(role)
        if frame is None or pane is None:
            return
        far = self._CameraRole.coerce("far_field")
        roi = self._rois.get(role) if role == far else None
        render_frame_to_viewport(pane.viewport, frame, roi=roi, roi_mode=self._mode)

    def set_coupling_overlay(self, overlay: dict | None, role=None) -> None:
        role = self._CameraRole.coerce("far_field") if role is None else self._CameraRole.coerce(role)
        pane = self._panes.get(role)
        if pane is not None:
            pane.viewport.set_coupling_overlay(overlay)

    def set_role_metric(self, role, text: str) -> None:
        pane = self._panes.get(self._CameraRole.coerce(role))
        if pane is not None:
            pane.set_metric(text)

    # ── Camera settings (hardware readback + UI emit) ────────────────────────
    def set_camera_settings(self, settings: dict, role=None) -> None:
        role = self._settings_role if role is None else self._CameraRole.coerce(role)
        s = self._cam_state.get(role)
        if s is None:
            return
        if "color_sensor" in settings:
            s["color_sensor"] = bool(settings["color_sensor"])
        if settings.get("exposure_us") is not None:
            s["exposure_us"] = float(settings["exposure_us"])
        if settings.get("exposure_min_us") is not None:
            s["exp_min_us"] = float(settings["exposure_min_us"])
        if settings.get("exposure_max_us") is not None:
            s["exp_max_us"] = float(settings["exposure_max_us"])
        if "fps_auto" in settings:
            s["fps_auto"] = bool(settings["fps_auto"])
        if settings.get("fps_hz") is not None:
            s["fps_hz"] = float(settings["fps_hz"])
        if settings.get("fps_min") is not None:
            s["fps_min"] = float(settings["fps_min"])
        if settings.get("fps_max") is not None:
            s["fps_max"] = float(settings["fps_max"])
        if settings.get("measured_fps") is not None:
            s["measured_fps"] = float(settings["measured_fps"])
        if settings.get("wb_rgb") is not None:
            s["wb_rgb"] = tuple(float(v) for v in settings["wb_rgb"][:3])
        if role == self._settings_role:
            self._select_settings_role(role, _refresh_ui=True)

    def _emit_exposure(self) -> None:
        if self._block_settings_signals:
            return
        val = self._exp_spin.value()
        self._cam_state[self._settings_role]["exposure_us"] = val
        self.camera_settings_changed.emit(
            {"role": self._settings_role.value, "exposure_us": val}
        )

    def _on_fps_mode_changed(self) -> None:
        fps_auto = bool(self._fps_mode.currentData())
        self._fps_spin.setEnabled(not fps_auto)
        if self._block_settings_signals:
            return
        self._cam_state[self._settings_role]["fps_auto"] = fps_auto
        payload: dict = {"role": self._settings_role.value, "fps_auto": fps_auto}
        if not fps_auto:
            payload["fps_hz"] = self._fps_spin.value()
            self._cam_state[self._settings_role]["fps_hz"] = payload["fps_hz"]
        self.camera_settings_changed.emit(payload)

    def _emit_fps(self) -> None:
        if self._block_settings_signals or bool(self._fps_mode.currentData()):
            return
        val = self._fps_spin.value()
        self._cam_state[self._settings_role]["fps_hz"] = val
        self.camera_settings_changed.emit(
            {"role": self._settings_role.value, "fps_auto": False, "fps_hz": val}
        )

    def _emit_white_balance(self) -> None:
        s = self._cam_state[self._settings_role]
        if self._block_settings_signals or not s["color_sensor"]:
            return
        rgb = tuple(sp.value() for sp in self._wb_spins)
        s["wb_rgb"] = rgb
        self.camera_settings_changed.emit({"role": self._settings_role.value, "wb_rgb": rgb})

    def _reset_white_balance(self) -> None:
        if self._block_settings_signals:
            return
        self.camera_settings_changed.emit({"role": self._settings_role.value, "wb_rgb": None})


class PopoutCameraPanel(GlassPanel):
    """Tile body that hosts a single popped-out camera pane (reparented in)."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent, title=title)
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(*self.content_margins())
        self._body.setSpacing(4)
        self._pane: QWidget | None = None

    def set_pane(self, pane: QWidget) -> None:
        self.take_pane()
        self._pane = pane
        pane.setParent(self)
        self._body.addWidget(pane)
        pane.show()

    def take_pane(self) -> QWidget | None:
        pane = self._pane
        if pane is not None:
            self._body.removeWidget(pane)
            pane.setParent(None)
            self._pane = None
        return pane

    def has_pane(self) -> bool:
        return self._pane is not None


def _normalize_u8(gray: np.ndarray) -> np.ndarray:
    # float32 is sufficient for display normalization and half the memory of float64
    arr = gray.astype(np.float32)
    lo, hi = np.percentile(arr, 1), np.percentile(arr, 99.5)
    if hi <= lo:
        hi = lo + 1
    arr = np.clip((arr - lo) / (hi - lo), 0, 1)
    return (255 * arr).astype(np.uint8)


def _frame_to_pixmap(frame: np.ndarray) -> tuple[QPixmap, int, int]:
    """Build a display pixmap from a mono or color frame; returns (pixmap, w, h).

    Color frames are shown in true RGB. A single brightness gain (shared across all
    three channels) maps the frame into 8-bit display range without altering hue, so
    dim beams stay visible and high-bit-depth data is scaled down faithfully.
    Uses float32 (not float64) to halve allocation cost on megapixel frames.
    """
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        rgb = arr[..., :3]
        if rgb.dtype != np.uint8:
            # High-bit-depth (e.g. uint16): rescale to uint8 via float32
            rgb32 = rgb.astype(np.float32)
            peak = float(rgb32.max())
            gain = 255.0 / peak if peak > 0 else 0.0
            rgb = np.clip(rgb32 * gain, 0, 255).astype(np.uint8)
        else:
            # Already uint8: scale only if needed, avoid full copy otherwise
            peak = int(rgb.max())
            if 0 < peak < 220:  # noticeably dim, auto-brighten
                rgb = np.clip(
                    (rgb.astype(np.float32) * (255.0 / peak)), 0, 255
                ).astype(np.uint8)
            else:
                rgb = np.ascontiguousarray(rgb)
        disp = np.ascontiguousarray(rgb)
        h, w = disp.shape[:2]
        qimg = QImage(disp.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimg.copy()), w, h

    disp = _normalize_u8(to_grayscale(arr))
    h, w = disp.shape
    qimg = QImage(disp.data, w, h, w, QImage.Format.Format_Grayscale8)
    return QPixmap.fromImage(qimg.copy()), w, h
