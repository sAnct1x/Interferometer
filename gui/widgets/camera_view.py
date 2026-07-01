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
    VIEWPORT_FILL_ALPHA,
)
from core.analytics.beam import to_grayscale

_VIEWPORT_CORNER_RADIUS = 8
_COLORBAR_WIDTH = 22


class LayoutMode(str, Enum):
    INPUT_ONLY = "input_only"
    OUTPUT_ONLY = "output_only"
    SIDE_BY_SIDE = "side_by_side"


_FIELD_STYLE = (
    "QComboBox, QDoubleSpinBox {"
    "  min-height: 26px;"
    "  padding: 2px 6px;"
    "  background: rgba(18,8,40,0.85);"
    "  color: " + TEXT_PRIMARY + ";"
    "  border: 1px solid #a855f7;"
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
    "  border: 1px solid #00e5ff; border-radius: 3px;"
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
            "color: #a855f7; font-size: 10px; }"
            "QPushButton:hover { color: #00e5ff; }"
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

        color = QColor("#00e5ff") if self._mode == RoiMode.BEAM else QColor("#a78bfa")
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


class CameraView(GlassPanel):
    snapshot_captured = Signal(object)
    snap_requested = Signal()
    live_feed_toggled = Signal(bool)
    camera_settings_changed = Signal(object)  # dict; includes "cam_idx": 0|1
    layout_mode_changed = Signal(str)          # LayoutMode value
    camera_label_changed = Signal(int, str)    # (cam_idx, new_label)

    _DEFAULT_CAM_STATE: dict = {
        "exposure_us": 10_000.0, "fps_auto": True, "fps_hz": 30.0,
        "exp_min_us": 10.0, "exp_max_us": 1_000_000.0,
        "fps_min": 1.0, "fps_max": 120.0, "measured_fps": None,
        "color_sensor": True, "wb_rgb": (1.0, 1.0, 1.0),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Live Camera")
        self._live_active = False
        self._simulation_feed = False
        self._frames: list[np.ndarray | None] = [None, None]
        self._rois: list[tuple[int, int, int, int]] = [
            (636, 534, 101, 101), (636, 534, 101, 101),
        ]
        self._modes: list[RoiMode] = [RoiMode.BEAM, RoiMode.BEAM]
        self._layout_mode = LayoutMode.INPUT_ONLY
        self._settings_cam = 0
        self._block_settings_signals = False
        self._cam_state: list[dict] = [
            dict(self._DEFAULT_CAM_STATE), dict(self._DEFAULT_CAM_STATE)
        ]

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(6)

        # ── Row 1: layout + ROI mode + start/snap ───────────────────────────
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        view_lbl = QLabel("View:")
        view_lbl.setStyleSheet(muted_style())
        r1.addWidget(view_lbl)
        self._layout_combo = QComboBox()
        self._layout_combo.setStyleSheet(_FIELD_STYLE)
        self._layout_combo.addItem("Input only", LayoutMode.INPUT_ONLY.value)
        self._layout_combo.addItem("Output only", LayoutMode.OUTPUT_ONLY.value)
        self._layout_combo.addItem("Side-by-Side", LayoutMode.SIDE_BY_SIDE.value)
        self._layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        r1.addWidget(self._layout_combo)

        self._mode_combo = QComboBox()  # backward-compat: dashboard connects to this directly
        self._mode_combo.addItem("Beam waist ROI", RoiMode.BEAM.value)
        self._mode_combo.addItem("Fringe ROI (λ scan)", RoiMode.FRINGE.value)
        self._mode_combo.setStyleSheet(_FIELD_STYLE)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        r1.addWidget(self._mode_combo)

        r1.addStretch()
        self._live_btn = PentagonButton("Start Live Feed", compact=True)
        self._live_btn.clicked.connect(self._on_live_clicked)
        r1.addWidget(self._live_btn)
        snap_btn = PentagonButton("Snap Frame", compact=True)
        snap_btn.clicked.connect(self._snap_frame)
        r1.addWidget(snap_btn)
        layout.addLayout(r1)

        # ── Row 2: settings cam selector + exposure / FPS ───────────────────
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        settings_lbl = QLabel("Settings:")
        settings_lbl.setStyleSheet(muted_style())
        r2.addWidget(settings_lbl)
        self._cam_a_btn = PentagonButton("A · Input", compact=True)
        self._cam_a_btn.clicked.connect(lambda: self._select_settings_cam(0))
        r2.addWidget(self._cam_a_btn)
        self._cam_b_btn = PentagonButton("B · Output", compact=True)
        self._cam_b_btn.clicked.connect(lambda: self._select_settings_cam(1))
        self._cam_b_btn.setEnabled(False)
        r2.addWidget(self._cam_b_btn)

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
        layout.addLayout(r2)

        # ── Row 3: white balance ─────────────────────────────────────────────
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
        layout.addWidget(self._wb_row_widget)

        # ── Viewport area (A + B side-by-side, B hidden in single modes) ────
        self._label_a = _EditableLabel("Input", "")
        self._label_a.label_changed.connect(lambda t: self.camera_label_changed.emit(0, t))
        self._label_b = _EditableLabel("Output", "")
        self._label_b.label_changed.connect(lambda t: self.camera_label_changed.emit(1, t))

        self._live_viewport = OctagonalViewport()   # Camera A — backward-compat name kept
        self._viewport_b = OctagonalViewport()       # Camera B

        self._pane_a = QWidget()
        pa = QVBoxLayout(self._pane_a)
        pa.setContentsMargins(0, 0, 0, 0)
        pa.setSpacing(2)
        pa.addWidget(self._label_a)
        pa.addWidget(self._live_viewport, stretch=1)

        self._pane_b = QWidget()
        pb = QVBoxLayout(self._pane_b)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(2)
        pb.addWidget(self._label_b)
        pb.addWidget(self._viewport_b, stretch=1)

        vp_layout = QHBoxLayout()
        vp_layout.setContentsMargins(0, 0, 0, 0)
        vp_layout.setSpacing(8)
        vp_layout.addWidget(self._pane_a)
        vp_layout.addWidget(self._pane_b)
        layout.addLayout(vp_layout, stretch=1)

        self._update_layout_visibility()
        self._select_settings_cam(0, _refresh_ui=False)
        self.show_idle()

    # ── Layout management ────────────────────────────────────────────────────

    def _on_layout_changed(self) -> None:
        mode = LayoutMode(self._layout_combo.currentData())
        self._layout_mode = mode
        self._update_layout_visibility()
        self.layout_mode_changed.emit(mode.value)

    def _update_layout_visibility(self) -> None:
        mode = self._layout_mode
        show_a = mode != LayoutMode.OUTPUT_ONLY
        show_b = mode != LayoutMode.INPUT_ONLY
        self._pane_a.setVisible(show_a)
        self._pane_b.setVisible(show_b)
        self._cam_b_btn.setEnabled(show_b)
        if mode == LayoutMode.OUTPUT_ONLY and self._settings_cam == 0:
            self._select_settings_cam(1, _refresh_ui=False)
        elif mode == LayoutMode.INPUT_ONLY and self._settings_cam == 1:
            self._select_settings_cam(0, _refresh_ui=False)

    def _select_settings_cam(self, cam_idx: int, *, _refresh_ui: bool = True) -> None:
        self._settings_cam = cam_idx
        active = "QPushButton { background: rgba(168,85,247,0.4); border: 1px solid #00e5ff; color: #00e5ff; }"
        idle = ""
        self._cam_a_btn.setStyleSheet(active if cam_idx == 0 else idle)
        self._cam_b_btn.setStyleSheet(active if cam_idx == 1 else idle)
        if _refresh_ui:
            s = self._cam_state[cam_idx]
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

    def current_layout(self) -> LayoutMode:
        return self._layout_mode

    def set_layout_mode(self, mode: LayoutMode) -> None:
        """Programmatically switch the layout combo (fires the normal change signal)."""
        for i in range(self._layout_combo.count()):
            if self._layout_combo.itemData(i) == mode.value:
                self._layout_combo.setCurrentIndex(i)
                return

    # ── Camera label + serial ────────────────────────────────────────────────

    def set_camera_label(self, cam_idx: int, label: str) -> None:
        if cam_idx == 0:
            self._label_a.set_text(label)
        else:
            self._label_b.set_text(label)

    def set_camera_serial(self, cam_idx: int, serial: str) -> None:
        if cam_idx == 0:
            self._label_a.set_serial(serial)
            self._cam_a_btn.setToolTip(f"Serial: {serial}")
        else:
            self._label_b.set_serial(serial)
            self._cam_b_btn.setToolTip(f"Serial: {serial}")

    # ── Live state ───────────────────────────────────────────────────────────

    def _on_live_clicked(self) -> None:
        self._live_active = not self._live_active
        self._live_btn.setText("Stop Live Feed" if self._live_active else "Start Live Feed")
        self.live_feed_toggled.emit(self._live_active)

    def set_live_active(self, active: bool, *, simulation: bool = False) -> None:
        self._live_active = active
        self._simulation_feed = simulation and active
        self._live_btn.setText("Stop Live Feed" if active else "Start Live Feed")

    def show_idle(self) -> None:
        self._frames = [None, None]
        self._live_viewport.set_idle("Live feed off\n\nStart live feed or snap a frame.")
        self._viewport_b.set_idle("Camera B (Output)\n\nNot active")

    # ── ROI / mode ───────────────────────────────────────────────────────────

    def set_roi(self, roi: tuple[int, int, int, int], mode: RoiMode | None = None) -> None:
        self._rois[0] = roi
        if mode is not None:
            self._modes[0] = mode
            idx = 0 if mode == RoiMode.BEAM else 1
            self._mode_combo.setCurrentIndex(idx)
        self._redraw_live(0)

    def set_roi_b(self, roi: tuple[int, int, int, int]) -> None:
        self._rois[1] = roi
        self._redraw_live(1)

    def current_roi(self) -> tuple[int, int, int, int]:
        return self._rois[0]

    def current_roi_b(self) -> tuple[int, int, int, int]:
        return self._rois[1]

    def current_mode(self) -> RoiMode:
        return self._modes[0]

    def _on_mode_changed(self) -> None:
        self._modes[0] = RoiMode(self._mode_combo.currentData())

    # ── Frame pipeline ───────────────────────────────────────────────────────

    def current_frame(self) -> np.ndarray | None:
        f = self._frames[0]
        return f.copy() if f is not None else None

    def current_frame_b(self) -> np.ndarray | None:
        f = self._frames[1]
        return f.copy() if f is not None else None

    def _snap_frame(self) -> None:
        frame = self._frames[self._settings_cam]
        if frame is None:
            self.snap_requested.emit()
            return
        self.snapshot_captured.emit(np.asarray(frame).copy())

    def update_frame(self, frame: np.ndarray, *, repaint: bool = True) -> None:
        self._frames[0] = frame
        if repaint:
            self._redraw_live(0)

    def store_frame(self, frame: np.ndarray) -> None:
        self._frames[0] = frame

    def update_frame_b(self, frame: np.ndarray, *, repaint: bool = True) -> None:
        self._frames[1] = frame
        if repaint:
            self._redraw_live(1)

    def store_frame_b(self, frame: np.ndarray) -> None:
        self._frames[1] = frame

    def _redraw_live(self, cam_idx: int = 0) -> None:
        frame = self._frames[cam_idx]
        if frame is None:
            return
        viewport = self._live_viewport if cam_idx == 0 else self._viewport_b
        roi = self._rois[cam_idx]
        mode = self._modes[cam_idx]

        pix, w, h = _frame_to_pixmap(frame)
        painter = QPainter(pix)
        x, y, rw, rh = roi
        color = QColor("#00e5ff") if mode == RoiMode.BEAM else QColor("#a78bfa")
        painter.setPen(QPen(color, 2))
        painter.drawRect(x, y, rw, rh)
        painter.end()

        rect = viewport.viewport_rect()
        target = rect.adjusted(10, 10, -10, -10)
        scaled = pix.scaled(
            int(target.width()),
            int(target.height()),
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

    def set_coupling_overlay(self, overlay: dict | None) -> None:
        self._live_viewport.set_coupling_overlay(overlay)

    def set_coupling_overlay_b(self, overlay: dict | None) -> None:
        self._viewport_b.set_coupling_overlay(overlay)

    # ── Camera settings (hardware readback + UI emit) ────────────────────────

    def set_camera_settings(self, settings: dict, cam_idx: int = 0) -> None:
        """Update stored settings for cam_idx; refresh controls if selected."""
        s = self._cam_state[cam_idx]
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
        if cam_idx == self._settings_cam:
            self._select_settings_cam(cam_idx, _refresh_ui=True)

    def _emit_exposure(self) -> None:
        if self._block_settings_signals:
            return
        val = self._exp_spin.value()
        self._cam_state[self._settings_cam]["exposure_us"] = val
        self.camera_settings_changed.emit({"cam_idx": self._settings_cam, "exposure_us": val})

    def _on_fps_mode_changed(self) -> None:
        fps_auto = bool(self._fps_mode.currentData())
        self._fps_spin.setEnabled(not fps_auto)
        if self._block_settings_signals:
            return
        self._cam_state[self._settings_cam]["fps_auto"] = fps_auto
        payload: dict = {"cam_idx": self._settings_cam, "fps_auto": fps_auto}
        if not fps_auto:
            payload["fps_hz"] = self._fps_spin.value()
            self._cam_state[self._settings_cam]["fps_hz"] = payload["fps_hz"]
        self.camera_settings_changed.emit(payload)

    def _emit_fps(self) -> None:
        if self._block_settings_signals or bool(self._fps_mode.currentData()):
            return
        val = self._fps_spin.value()
        self._cam_state[self._settings_cam]["fps_hz"] = val
        self.camera_settings_changed.emit(
            {"cam_idx": self._settings_cam, "fps_auto": False, "fps_hz": val}
        )

    def _emit_white_balance(self) -> None:
        s = self._cam_state[self._settings_cam]
        if self._block_settings_signals or not s["color_sensor"]:
            return
        rgb = tuple(sp.value() for sp in self._wb_spins)
        s["wb_rgb"] = rgb
        self.camera_settings_changed.emit({"cam_idx": self._settings_cam, "wb_rgb": rgb})

    def _reset_white_balance(self) -> None:
        if self._block_settings_signals:
            return
        self.camera_settings_changed.emit({"cam_idx": self._settings_cam, "wb_rgb": None})


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
            if 0 < peak < 220:  # noticeably dim — auto-brighten
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
