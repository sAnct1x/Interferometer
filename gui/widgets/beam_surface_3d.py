"""Readable 3D beam intensity surface (OpenGL / pyqtgraph).

Design goals vs the prior cluttered view:
- Labels live *outside* the mesh volume (no on-surface "peak" / "BEAM WAIST").
- Sparse translucent wireframe + floor isolines instead of an opaque cyan block.
- Peak marked with a stem + offset billboard (leader), not stacked text on the summit.
- Default camera angle leaves axes clear; GLViewWidget still supports drag-rotate.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QFont
from pyqtgraph.opengl import (
    GLLinePlotItem,
    GLScatterPlotItem,
    GLSurfacePlotItem,
    GLTextItem,
)

from config import PIXEL_SIZE_UM
from gui.neon_theme import NEON_PINK, TEXT_MUTED

# Visual height of the peak relative to the XY span (keeps axes readable).
_SURFACE_HEIGHT_FRAC = 0.42
# Target mesh samples along the long side — lower = less wireframe clutter.
_MESH_TARGET = 36
# Wireframe RGBA (cyan, translucent so the far side remains visible).
_GRID_LINE = (0.0, 0.85, 0.95, 0.42)
_AXIS_LINE = (0.58, 0.45, 0.95, 0.75)
_FLOOR_LINE = (0.55, 0.35, 0.95, 0.35)
_CONTOUR_LINE = (0.0, 0.95, 1.0, 0.55)
_STEM_LINE = (1.0, 0.35, 0.65, 0.95)


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


def _nice_ticks(lo: float, hi: float, count: int = 3) -> list[float]:
    """Few, round tick values for axis annotations."""
    if hi <= lo:
        return [float(lo)]
    if count < 2:
        count = 2
    raw = np.linspace(lo, hi, count)
    span = hi - lo
    # Round to ~2 significant figures so labels stay short (e.g. 350 not 352.1).
    step = span / max(count - 1, 1)
    if step <= 0:
        return [float(lo), float(hi)]
    mag = 10 ** max(0, int(np.floor(np.log10(step))) - 1)
    rounded = [float(np.round(v / mag) * mag) for v in raw]
    # Always include endpoints for spatial context.
    rounded[0] = float(lo)
    rounded[-1] = float(hi)
    # Deduplicate after rounding.
    out: list[float] = []
    for v in rounded:
        if not out or abs(v - out[-1]) > span * 0.08:
            out.append(v)
    return out


def _floor_contours(
    y_um: np.ndarray,
    x_um: np.ndarray,
    z_raw: np.ndarray,
    peak: float,
    levels: tuple[float, ...] = (0.25, 0.5, 0.75),
) -> list[np.ndarray]:
    """Approximate isolines of intensity projected onto the floor (z=0).

    Uses marching-squares-lite on the downsampled grid so we avoid SciPy.
    Each returned array is Nx3 positions for a GL line strip (with NaN breaks).
    """
    if peak <= 0 or z_raw.size == 0:
        return []
    z = np.asarray(z_raw, dtype=np.float64)
    ny, nx = z.shape
    if ny < 2 or nx < 2:
        return []

    polylines: list[np.ndarray] = []
    yy = np.asarray(y_um, dtype=np.float64)
    xx = np.asarray(x_um, dtype=np.float64)

    for frac in levels:
        thr = peak * frac
        segs: list[list[tuple[float, float]]] = []
        for i in range(ny - 1):
            for j in range(nx - 1):
                corners = (
                    (yy[i], xx[j], z[i, j]),
                    (yy[i], xx[j + 1], z[i, j + 1]),
                    (yy[i + 1], xx[j + 1], z[i + 1, j + 1]),
                    (yy[i + 1], xx[j], z[i + 1, j]),
                )
                # Collect edge midpoints where the threshold crosses.
                pts: list[tuple[float, float]] = []
                for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                    y0, x0, v0 = corners[a]
                    y1, x1, v1 = corners[b]
                    if (v0 < thr) == (v1 < thr):
                        continue
                    if abs(v1 - v0) < 1e-12:
                        t = 0.5
                    else:
                        t = (thr - v0) / (v1 - v0)
                    t = float(np.clip(t, 0.0, 1.0))
                    pts.append((y0 + t * (y1 - y0), x0 + t * (x1 - x0)))
                if len(pts) >= 2:
                    segs.append(pts[:2])

        if not segs:
            continue
        # Flatten segments with NaN breaks so one GLLinePlotItem can draw them all.
        rows: list[list[float]] = []
        for (y0, x0), (y1, x1) in segs:
            rows.append([y0, x0, 0.0])
            rows.append([y1, x1, 0.0])
            rows.append([np.nan, np.nan, np.nan])
        polylines.append(np.asarray(rows, dtype=np.float32))
    return polylines


class BeamSurface3D:
    """Manages wireframe surface + sparse outer-frame labels inside a GLViewWidget."""

    def __init__(self, gl_view) -> None:
        self._gl = gl_view
        self._surface: GLSurfacePlotItem | None = None
        self._items: list = []
        self._texts: list[GLTextItem] = []
        self._peak_intensity = 0.0

    def clear(self) -> None:
        if self._surface is not None:
            self._gl.removeItem(self._surface)
            self._surface = None
        for item in self._items:
            self._gl.removeItem(item)
        self._items.clear()
        for item in self._texts:
            self._gl.removeItem(item)
        self._texts.clear()

    def update(self, img_bs: np.ndarray) -> tuple[float, float, float]:
        """Rebuild mesh from ROI intensity. Returns (x_um_max, y_um_max, z_disp_peak)."""
        self.clear()
        step = max(1, int(np.ceil(max(img_bs.shape) / _MESH_TARGET)))
        z = np.asarray(img_bs, dtype=np.float64)
        if step > 1:
            z = z[::step, ::step]
        y_um, x_um, z_disp, z_raw, peak, xy_span = _intensity_mesh(z, step)
        self._peak_intensity = peak

        # Sparse translucent wireframe — faces off (Windows z-fighting).
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
            lineWidth=1.15,
            lineAntialias=True,
            glOptions="translucent",
        )
        self._gl.addItem(self._surface)

        x_max = float(x_um[-1])
        y_max = float(y_um[-1])
        z_max = float(np.max(z_disp)) if z_disp.size else 0.0

        self._build_frame(x_max, y_max, z_max)
        self._build_floor_contours(y_um, x_um, z_raw, peak)
        self._build_peak_marker(y_um, x_um, z_disp, z_raw, peak, xy_span)
        self._build_labels(x_max, y_max, z_max, peak)
        return x_max, y_max, z_max

    def _add_lines(
        self,
        pos: np.ndarray,
        *,
        color: tuple[float, float, float, float],
        width: float = 1.0,
        mode: str = "line_strip",
    ) -> None:
        item = GLLinePlotItem(
            pos=np.asarray(pos, dtype=np.float32),
            color=color,
            width=width,
            antialias=True,
            mode=mode,
            glOptions="translucent",
        )
        self._gl.addItem(item)
        self._items.append(item)

    def _build_frame(self, x_max: float, y_max: float, z_max: float) -> None:
        """Bounding box on the floor + vertical intensity spine (label anchor)."""
        floor = np.array(
            [
                [0, 0, 0],
                [y_max, 0, 0],
                [y_max, x_max, 0],
                [0, x_max, 0],
                [0, 0, 0],
            ],
            dtype=np.float32,
        )
        self._add_lines(floor, color=_FLOOR_LINE, width=1.0)

        # Intensity spine at the far-left corner (away from the beam mound).
        spine = np.array([[0, 0, 0], [0, 0, max(z_max, 1.0)]], dtype=np.float32)
        self._add_lines(spine, color=_AXIS_LINE, width=1.4)

        # Short XY axis stubs so tick numbers have a clear edge.
        x_stub = np.array([[0, 0, 0], [0, x_max, 0]], dtype=np.float32)
        y_stub = np.array([[0, 0, 0], [y_max, 0, 0]], dtype=np.float32)
        self._add_lines(x_stub, color=_AXIS_LINE, width=1.2)
        self._add_lines(y_stub, color=_AXIS_LINE, width=1.2)

    def _build_floor_contours(
        self,
        y_um: np.ndarray,
        x_um: np.ndarray,
        z_raw: np.ndarray,
        peak: float,
    ) -> None:
        for poly in _floor_contours(y_um, x_um, z_raw, peak):
            self._add_lines(poly, color=_CONTOUR_LINE, width=1.2, mode="line_strip")

    def _build_peak_marker(
        self,
        y_um: np.ndarray,
        x_um: np.ndarray,
        z_disp: np.ndarray,
        z_raw: np.ndarray,
        peak: float,
        xy_span: float,
    ) -> None:
        """Stem + scatter + offset 'peak' label (never stacked on the summit)."""
        if z_raw.size == 0 or peak <= 0:
            return
        flat_idx = int(np.argmax(z_raw))
        row, col = np.unravel_index(flat_idx, z_raw.shape)
        py = float(y_um[row])
        px = float(x_um[col])
        pz = float(z_disp[row, col])

        stem = np.array([[py, px, 0.0], [py, px, pz]], dtype=np.float32)
        self._add_lines(stem, color=_STEM_LINE, width=1.6)

        scatter = GLScatterPlotItem(
            pos=np.array([[py, px, pz]], dtype=np.float32),
            size=9,
            color=_hex_rgba(NEON_PINK, 0.95),
            pxMode=True,
            glOptions="translucent",
        )
        self._gl.addItem(scatter)
        self._items.append(scatter)

        # Offset billboard: pull the label off the mesh along +Y / +Z.
        pad = xy_span * 0.12
        label_pos = (py + pad * 0.35, px + pad * 0.85, pz + pad * 0.55)
        leader = np.array([[py, px, pz], list(label_pos)], dtype=np.float32)
        self._add_lines(leader, color=_hex_rgba(NEON_PINK, 0.7), width=1.0)
        self._add_text(
            pos=label_pos,
            text=f"peak {peak:.0f}",
            font=QFont("Segoe UI", 8, QFont.Weight.DemiBold),
            color=QColor(NEON_PINK),
        )

    def _build_labels(
        self,
        x_max: float,
        y_max: float,
        z_max: float,
        peak: float,
    ) -> None:
        """Axis titles + 3 ticks, all outside the mesh volume."""
        axis_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        tick_font = QFont("Consolas", 7)
        label_color = QColor(TEXT_MUTED)
        tick_color = QColor("#b8c5d6")
        # Push labels clear of the wireframe (was ~0.14 — still colliding).
        pad = max(x_max, y_max) * 0.22

        # X ticks along GL Y (image x / columns) — outside +Y edge.
        for val in _nice_ticks(0, x_max, 3):
            self._add_text(
                pos=(-pad * 0.35, val, -pad * 0.12),
                text=f"{val:.0f}",
                font=tick_font,
                color=tick_color,
            )
        # Y ticks along GL X (image y / rows) — outside +X edge.
        for val in _nice_ticks(0, y_max, 3):
            self._add_text(
                pos=(val, -pad * 0.45, -pad * 0.12),
                text=f"{val:.0f}",
                font=tick_font,
                color=tick_color,
            )
        # Intensity ticks on the spine, left of the volume.
        if peak > 0 and z_max > 0:
            for val in _nice_ticks(0, peak, 3):
                z_tick = val * (z_max / peak)
                self._add_text(
                    pos=(-pad * 0.95, -pad * 0.15, z_tick),
                    text=f"{val:.0f}",
                    font=tick_font,
                    color=tick_color,
                )

        self._add_text(
            pos=(-pad * 0.15, x_max * 0.5, -pad * 0.55),
            text="x (µm)",
            font=axis_font,
            color=label_color,
        )
        self._add_text(
            pos=(y_max * 0.5, -pad * 0.95, -pad * 0.35),
            text="y (µm)",
            font=axis_font,
            color=label_color,
        )
        self._add_text(
            pos=(-pad * 1.35, -pad * 0.05, z_max * 0.55),
            text="I (a.u.)",
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


def _hex_rgba(hex_color: str, alpha: float) -> tuple[float, float, float, float]:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b, float(alpha))
