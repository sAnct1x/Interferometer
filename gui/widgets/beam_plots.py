"""Beam profile plots with 3D surface, Gaussian fit, and M2 proxy."""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from pyqtgraph.opengl import GLViewWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QWidget

from config import BEAM_WAIST_TARGET_UM, PIXEL_SIZE_UM
from gui.glass_panel import GlassPanel, PentagonButton
from gui.typography import callout_style, hint_style, style_neon_plot
from gui.heatmap import intensity_to_rgb
from gui.widgets.beam_surface_3d import BeamSurface3D


_VIZ_MIN_H = 118
_VIZ_MAX_H = 168
_PROFILE_MIN_H = 108


def _style_plot(plot: pg.PlotWidget, *, x_label: str, y_label: str) -> None:
    style_neon_plot(plot, x_label, y_label)


def _viz_size_policy(widget: QWidget) -> None:
    widget.setMinimumHeight(_VIZ_MIN_H)
    widget.setMaximumHeight(_VIZ_MAX_H)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class BeamPlotsPanel(GlassPanel):
    analyze_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="3D Beam Profile")
        self._has_surface = False
        self._gl = None
        self._surface3d: BeamSurface3D | None = None
        self._gl_error: str | None = None
        self._live_heatmap_last_t = 0.0

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        self._summary = QLabel("Start live feed (or snap a frame), then click Analyze Beam.")
        self._summary.setWordWrap(True)
        self._summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._summary.setMaximumHeight(56)
        self._summary.setStyleSheet(callout_style())
        header_row.addWidget(self._summary, stretch=1)

        self._analyze_btn = PentagonButton("⬡ Analyze Beam")
        self._analyze_btn.setToolTip("Capture the current live frame and run Gaussian beam fit")
        self._analyze_btn.clicked.connect(self.analyze_requested)
        header_row.addWidget(self._analyze_btn, stretch=0)
        layout.addLayout(header_row, stretch=0)

        viz_row = QHBoxLayout()
        viz_row.setSpacing(6)

        self._heatmap_plot = pg.PlotWidget(title="Beam intensity map (ROI)")
        _style_plot(self._heatmap_plot, x_label="x (µm)", y_label="y (µm)")
        _viz_size_policy(self._heatmap_plot)
        self._heatmap_img = pg.ImageItem()
        self._heatmap_plot.addItem(self._heatmap_img)
        self._heatmap_plot.invertY(True)
        viz_row.addWidget(self._heatmap_plot, stretch=1)

        self._gl_stack = QStackedWidget()
        _viz_size_policy(self._gl_stack)

        self._gl_placeholder = QLabel(
            "3D beam surface\nappears here after Analyze Beam\n(drag to rotate)"
        )
        self._gl_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gl_placeholder.setStyleSheet(
            hint_style()
            + " background: rgba(18,10,40,0.85); border: 1px dashed #a855f7; border-radius: 6px;"
        )
        self._gl_stack.addWidget(self._gl_placeholder)

        self._gl_host = QWidget()
        self._gl_layout = QVBoxLayout(self._gl_host)
        self._gl_layout.setContentsMargins(0, 0, 0, 0)
        self._gl_stack.addWidget(self._gl_host)
        self._gl_stack.setCurrentWidget(self._gl_placeholder)

        viz_row.addWidget(self._gl_stack, stretch=1)
        layout.addLayout(viz_row, stretch=3)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(6)
        self._x_plot = pg.PlotWidget(title="X profile + Gaussian fit")
        self._y_plot = pg.PlotWidget(title="Y profile + Gaussian fit")
        _style_plot(self._x_plot, x_label="x (µm)", y_label="intensity (a.u.)")
        _style_plot(self._y_plot, x_label="y (µm)", y_label="intensity (a.u.)")
        for p in (self._x_plot, self._y_plot):
            p.setMinimumHeight(_PROFILE_MIN_H)
            p.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._x_data = self._x_plot.plot(pen=pg.mkPen("#f472b6", width=2))
        self._x_fit = self._x_plot.plot(
            pen=pg.mkPen("#00f5ff", width=2, style=Qt.PenStyle.DashLine)
        )
        self._y_data = self._y_plot.plot(pen=pg.mkPen("#a855f7", width=2))
        self._y_fit = self._y_plot.plot(
            pen=pg.mkPen("#00f5ff", width=2, style=Qt.PenStyle.DashLine)
        )
        profile_row.addWidget(self._x_plot, stretch=1)
        profile_row.addWidget(self._y_plot, stretch=1)
        layout.addLayout(profile_row, stretch=3)

    def reset(self) -> None:
        self._has_surface = False
        self._summary.setText("Snap a frame or start live feed, then Analyze Beam.")
        self._heatmap_plot.clear()
        self._heatmap_plot.addItem(self._heatmap_img)
        self._heatmap_img.clear()
        self._x_data.setData([], [])
        self._x_fit.setData([], [])
        self._y_data.setData([], [])
        self._y_fit.setData([], [])
        self._gl_stack.setCurrentWidget(self._gl_placeholder)
        self._gl_placeholder.setText(
            "3D beam surface\nappears here after Analyze Beam\n(drag to rotate)"
        )
        if self._gl is not None:
            self._gl.clear()
        self._surface3d = None
        self._gl_error = None

    def update_analysis(self, result: dict, *, live: bool = False) -> None:
        w = result.get("one_over_e2_avg_um", float("nan"))
        fx = result.get("fwhm_x_um", float("nan"))
        fy = result.get("fwhm_y_um", float("nan"))
        m2 = result.get("m2", float("nan"))
        target = BEAM_WAIST_TARGET_UM[1]
        self._summary.setText(
            f"w₀ (1/e² avg): {w:.1f} µm  (target {target:.0f} µm)  |  "
            f"M² ≈ {m2:.2f}  |  FWHM X: {fx:.1f} µm  Y: {fy:.1f} µm"
        )
        warnings = result.get("quality_warnings") or []
        if warnings:
            self._summary.setText(self._summary.text() + f"\n⚠ {warnings[0]}")
            self._summary.setMaximumHeight(72)

        quality = result.get("beam_quality") or {}
        x_prof = result.get("x_profile")
        y_prof = result.get("y_profile")
        if x_prof is not None:
            x_um = np.arange(len(x_prof), dtype=float) * PIXEL_SIZE_UM
            self._x_data.setData(x_um, x_prof)
            x_fit = quality.get("x_fit", {})
            if x_fit.get("fit") is not None:
                self._x_fit.setData(x_fit["x_um"], x_fit["fit"])
            else:
                self._x_fit.setData([], [])
            if not live:
                self._x_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
        if y_prof is not None:
            y_um = np.arange(len(y_prof), dtype=float) * PIXEL_SIZE_UM
            self._y_data.setData(y_um, y_prof)
            y_fit = quality.get("y_fit", {})
            if y_fit.get("fit") is not None:
                self._y_fit.setData(y_fit["x_um"], y_fit["fit"])
            else:
                self._y_fit.setData([], [])
            if not live:
                self._y_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)

        img_bs = result.get("img_bs")
        if img_bs is not None:
            if live:
                now = time.time()
                if now - self._live_heatmap_last_t >= 1.0:
                    self._live_heatmap_last_t = now
                    self._update_heatmap(img_bs)
            else:
                self._update_heatmap(img_bs)
                self._update_surface(img_bs)

    def _update_heatmap(self, img_bs: np.ndarray) -> None:
        z = np.asarray(img_bs, dtype=np.float64)
        if z.size == 0:
            return
        rgb, _, _ = intensity_to_rgb(z)
        alpha = np.full(rgb.shape[:2], 255, dtype=np.uint8)
        rgba = np.dstack([rgb, alpha])
        self._heatmap_img.setImage(rgba, autoLevels=False)
        h, w = z.shape
        self._heatmap_img.setRect(0, 0, w * PIXEL_SIZE_UM, h * PIXEL_SIZE_UM)
        self._heatmap_plot.setXRange(0, w * PIXEL_SIZE_UM, padding=0.02)
        self._heatmap_plot.setYRange(0, h * PIXEL_SIZE_UM, padding=0.02)

    def _ensure_gl(self) -> None:
        if self._gl is not None:
            return
        try:
            self._gl = GLViewWidget()
            self._gl.setMinimumHeight(_VIZ_MIN_H)
            self._gl.opts["distance"] = 2.8
            self._gl.setBackgroundColor((12, 8, 28, 255))
            self._gl_layout.addWidget(self._gl)
            self._gl_error = None
        except Exception as exc:
            self._gl = None
            self._gl_error = str(exc)

    def _frame_3d_camera(self, x_max: float, y_max: float, z_max: float) -> None:
        if self._gl is None:
            return
        from pyqtgraph import Vector

        mid_y = y_max * 0.5
        mid_x = x_max * 0.5
        mid_z = z_max * 0.5
        self._gl.opts["center"] = Vector(mid_y, mid_x, mid_z)
        xy_span = max(x_max, y_max, 1.0)
        dist = max(xy_span * 2.4, z_max * 5.0, 120.0)
        self._gl.setCameraPosition(distance=dist, elevation=32, azimuth=-55)

    def _update_surface(self, img_bs: np.ndarray) -> None:
        self._ensure_gl()
        if self._gl is None:
            self._gl_stack.setCurrentWidget(self._gl_placeholder)
            self._gl_placeholder.setText(
                "3D view unavailable\n"
                + (self._gl_error or "OpenGL could not be initialized.")
            )
            return
        z = np.asarray(img_bs, dtype=float)
        if z.size == 0:
            return
        try:
            if self._surface3d is None:
                self._surface3d = BeamSurface3D(self._gl)
            x_max, y_max, z_max = self._surface3d.update(z)
            self._has_surface = True
            self._gl_error = None
            self._frame_3d_camera(y_max, x_max, z_max)
            self._gl_stack.setCurrentWidget(self._gl_host)
            self._gl_host.show()
            self._gl.show()
            self._gl.update()
        except Exception as exc:
            self._has_surface = False
            self._surface3d = None
            self._gl_error = str(exc)
            self._gl_stack.setCurrentWidget(self._gl_placeholder)
            hint = str(exc)
            if "OpenGL" in hint or "opengl" in hint.lower():
                hint += "\nInstall PyOpenGL: pip install PyOpenGL"
            self._gl_placeholder.setText(f"3D view unavailable\n{hint}")
