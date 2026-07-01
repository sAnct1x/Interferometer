"""Wireframe 3D beam intensity surface with labeled axes (OpenGL / pyqtgraph)."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QFont
from pyqtgraph.opengl import (
    GLLinePlotItem,
    GLSurfacePlotItem,
    GLTextItem,
)

from config import PIXEL_SIZE_UM
from gui.typography import TEXT_MUTED

_SURFACE_HEIGHT_FRAC = 0.38
_GRID_LINE = (0.0, 0.98, 1.0, 0.95)


def _intensity_mesh(z: np.ndarray, step: int) -> tuple[np.ndarray, ...]:
    """Build µm axes and display-height Z from background-subtracted ROI intensity."""
    z = np.asarray(z, dtype=np.float64)
    if z.size == 0:
        raise ValueError("empty beam ROI")
    h, w = z.shape
    y_um = np.linspace(0.0, h * PIXEL_SIZE_UM * step, h, dtype=np.float64)
    x_um = np.linspace(0.0, w * PIXEL_SIZE_UM * step, w, dtype=np.float64)
    xy_span = max(float(x_um[-1]), float(y_um[-1]), 1.0)
    peak = float(np.max(z))
    if peak <= 0:
        z_disp = np.zeros_like(z)
    else:
        z_disp = z * (xy_span * _SURFACE_HEIGHT_FRAC / peak)
    return y_um, x_um, z_disp, z, peak, xy_span


def _tick_values(lo: float, hi: float, count: int = 4) -> np.ndarray:
    if hi <= lo:
        return np.array([lo])
    return np.linspace(lo, hi, count)


class BeamSurface3D:
    """Manages wireframe surface + axis guides inside a GLViewWidget."""

    def __init__(self, gl_view) -> None:
        self._gl = gl_view
        self._surface: GLSurfacePlotItem | None = None
        self._box: GLLinePlotItem | None = None
        self._texts: list[GLTextItem] = []
        self._peak_intensity = 0.0

    def clear(self) -> None:
        if self._surface is not None:
            self._gl.removeItem(self._surface)
            self._surface = None
        if self._box is not None:
            self._gl.removeItem(self._box)
            self._box = None
        for item in self._texts:
            self._gl.removeItem(item)
        self._texts.clear()

    def update(self, img_bs: np.ndarray) -> tuple[float, float, float]:
        """Rebuild mesh from ROI intensity. Returns (x_um_max, y_um_max, z_disp_peak)."""
        self.clear()
        step = max(1, int(np.ceil(max(img_bs.shape) / 64)))
        z = np.asarray(img_bs, dtype=np.float64)
        if step > 1:
            z = z[::step, ::step]
        y_um, x_um, z_disp, z_raw, peak, _xy_span = _intensity_mesh(z, step)
        self._peak_intensity = peak

        # Wireframe only — shaded faces cause z-fighting / grey triangle artifacts on Windows.
        self._surface = GLSurfacePlotItem(
            x=y_um,
            y=x_um,
            z=z_disp,
            shader=None,
            smooth=False,
            computeNormals=False,
            drawFaces=False,
            drawEdges=False,
            showGrid=True,
            lineColor=_GRID_LINE,
            lineWidth=1.55,
            lineAntialias=True,
            glOptions="translucent",
        )
        self._gl.addItem(self._surface)

        x_max = float(x_um[-1])
        y_max = float(y_um[-1])
        z_max = float(np.max(z_disp))
        self._build_base_box(x_max, y_max)
        self._build_labels(x_um, y_um, z_disp, z_raw, peak, x_max, y_max, z_max)
        return x_max, y_max, z_max

    def _build_base_box(self, x_max: float, y_max: float) -> None:
        corners = np.array(
            [
                [0, 0, 0],
                [y_max, 0, 0],
                [y_max, x_max, 0],
                [0, x_max, 0],
                [0, 0, 0],
            ],
            dtype=np.float32,
        )
        self._box = GLLinePlotItem(
            pos=corners,
            color=(0.55, 0.35, 0.95, 0.45),
            width=1.0,
            antialias=True,
            mode="line_strip",
            glOptions="translucent",
        )
        self._gl.addItem(self._box)

    def _build_labels(
        self,
        x_um: np.ndarray,
        y_um: np.ndarray,
        z_disp: np.ndarray,
        z_raw: np.ndarray,
        peak: float,
        x_max: float,
        y_max: float,
        z_max: float,
    ) -> None:
        axis_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        tick_font = QFont("Consolas", 8)
        label_color = QColor(TEXT_MUTED)
        tick_color = QColor(TEXT_MUTED)
        pad = max(x_max, y_max) * 0.14

        for val in _tick_values(0, x_max, 4):
            self._add_text(
                pos=(y_max + pad * 0.55, val, -pad * 0.05),
                text=f"{val:.0f}",
                font=tick_font,
                color=tick_color,
            )
        for val in _tick_values(0, y_max, 4):
            self._add_text(
                pos=(val, -pad * 0.55, -pad * 0.05),
                text=f"{val:.0f}",
                font=tick_font,
                color=tick_color,
            )
        for val in _tick_values(0, self._peak_intensity, 4):
            z_tick = val * (z_max / self._peak_intensity) if self._peak_intensity > 0 else 0.0
            self._add_text(
                pos=(-pad * 0.75, -pad * 0.75, z_tick),
                text=f"{val:.0f}",
                font=tick_font,
                color=tick_color,
            )

        self._add_text(
            pos=(y_max * 0.35, x_max + pad, -pad * 0.08),
            text="x (µm)",
            font=axis_font,
            color=label_color,
        )
        self._add_text(
            pos=(y_max + pad, x_max * 0.35, -pad * 0.08),
            text="y (µm)",
            font=axis_font,
            color=label_color,
        )
        self._add_text(
            pos=(-pad * 1.1, -pad * 0.35, z_max * 0.55),
            text="intensity (a.u.)",
            font=axis_font,
            color=label_color,
        )
        self._add_text(
            pos=(y_max + pad * 0.15, x_max * 0.05, z_max + pad * 0.35),
            text="BEAM WAIST",
            font=axis_font,
            color=label_color,
        )

        flat_idx = int(np.argmax(z_raw))
        row, col = np.unravel_index(flat_idx, z_raw.shape)
        peak_pos = (
            float(y_um[row]) + pad * 0.08,
            float(x_um[col]),
            float(z_disp[row, col]) + pad * 0.25,
        )
        self._add_text(
            pos=peak_pos,
            text="peak",
            font=axis_font,
            color=label_color,
        )

    def _add_text(
        self,
        *,
        pos: tuple[float, float, float],
        text: str,
        font: QFont,
        color: QColor,
    ) -> None:
        item = GLTextItem(
            pos=np.array(pos, dtype=np.float64),
            text=text,
            font=font,
            color=color,
            glOptions="translucent",
        )
        self._gl.addItem(item)
        self._texts.append(item)
