"""Dynamic proximity point cloud for the left hub rail (Pleiad network)."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QRadialGradient, QPainterPath

from gui.neon_theme import COLOR_CYAN, COLOR_MAGENTA, COLOR_PURPLE, RAIL_BASE_ALPHA, RAIL_EDGE_PURPLE_ALPHAS

_TAU = math.tau


class _Node:
    __slots__ = ("x", "y", "z", "vx", "vy", "vz", "pulse", "hue")

    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z
        self.vx = random.uniform(-0.014, 0.014)
        self.vy = random.uniform(-0.011, 0.011)
        self.vz = random.uniform(-0.012, 0.012)
        self.pulse = random.uniform(0.0, _TAU)
        self.hue = random.uniform(0.0, 1.0)


class PleiadNetwork:
    """Particle field + proximity links inside a unit cube [-1, 1]."""

    def __init__(self, node_count: int = 96) -> None:
        self._nodes = [
            _Node(
                random.uniform(-0.98, 0.98),
                random.uniform(-0.98, 0.98),
                random.uniform(-0.98, 0.98),
            )
            for _ in range(node_count)
        ]
        self._link_dist = 0.68
        self._yaw = 0.0
        self._x_rot = 0.0

    def step(self, dt: float = 1.0, spin: float = 0.003) -> None:
        self._yaw = (self._yaw + spin * dt) % _TAU
        self._x_rot = (self._x_rot + 0.0018 * dt) % _TAU
        for n in self._nodes:
            n.x += n.vx * dt
            n.y += n.vy * dt
            n.z += n.vz * dt
            n.pulse = (n.pulse + 0.065 * dt) % _TAU
            if n.x > 0.98:
                n.x = 0.98
                n.vx *= -1.0
            elif n.x < -0.98:
                n.x = -0.98
                n.vx *= -1.0
            if n.y > 0.98:
                n.y = 0.98
                n.vy *= -1.0
            elif n.y < -0.98:
                n.y = -0.98
                n.vy *= -1.0
            if n.z > 0.98:
                n.z = 0.98
                n.vz *= -1.0
            elif n.z < -0.98:
                n.z = -0.98
                n.vz *= -1.0

    def _project(
        self,
        x: float,
        y: float,
        z: float,
        cx: float,
        cy: float,
        scale_x: float,
        scale_y: float,
        pitch: float,
    ) -> tuple[float, float, float]:
        cos_y = math.cos(self._yaw)
        sin_y = math.sin(self._yaw)
        xr = x * cos_y + z * sin_y
        zr = -x * sin_y + z * cos_y
        cos_p = math.cos(pitch)
        sin_p = math.sin(pitch)
        yr = y * cos_p - zr * sin_p
        zr2 = y * sin_p + zr * cos_p
        depth = 0.5 + zr2 * 0.5
        sx = cx + xr * scale_x * depth
        sy = cy - yr * scale_y
        return sx, sy, depth

    @staticmethod
    def _neon_at_t(t: float, alpha: int) -> QColor:
        """Magenta/violet at top → cyan at bottom (reference gradient)."""
        t = max(0.0, min(1.0, t))
        if t < 0.5:
            u = t * 2.0
            r = int(COLOR_MAGENTA.red() * (1 - u) + COLOR_PURPLE.red() * u)
            g = int(COLOR_MAGENTA.green() * (1 - u) + COLOR_PURPLE.green() * u)
            b = int(COLOR_MAGENTA.blue() * (1 - u) + COLOR_PURPLE.blue() * u)
        else:
            u = (t - 0.5) * 2.0
            r = int(COLOR_PURPLE.red() * (1 - u) + COLOR_CYAN.red() * u)
            g = int(COLOR_PURPLE.green() * (1 - u) + COLOR_CYAN.green() * u)
            b = int(COLOR_PURPLE.blue() * (1 - u) + COLOR_CYAN.blue() * u)
        return QColor(r, g, b, alpha)

    def _draw_node(
        self,
        painter: QPainter,
        sx: float,
        sy: float,
        grad_t: float,
        pulse: float,
        depth: float,
    ) -> None:
        """Radial neon sprite — bright core, soft falloff to transparent edge."""
        core_r = 1.35 + pulse * 0.65 + depth * 0.3
        glow_r = core_r * 3.8 + pulse * 1.4
        neon = self._neon_at_t(grad_t, 255)

        outer = QRadialGradient(sx, sy, glow_r)
        outer.setColorAt(0.0, QColor(neon.red(), neon.green(), neon.blue(), int(200 + 55 * pulse)))
        outer.setColorAt(0.22, QColor(neon.red(), neon.green(), neon.blue(), int(120 + 50 * pulse)))
        outer.setColorAt(0.55, QColor(neon.red(), neon.green(), neon.blue(), int(35 + 25 * pulse)))
        outer.setColorAt(1.0, QColor(neon.red(), neon.green(), neon.blue(), 0))

        inner = QRadialGradient(sx, sy, core_r * 1.6)
        inner.setColorAt(0.0, QColor(255, 255, 255, int(230 + 25 * pulse)))
        inner.setColorAt(0.35, QColor(neon.red(), neon.green(), neon.blue(), int(210 + 45 * pulse)))
        inner.setColorAt(1.0, QColor(neon.red(), neon.green(), neon.blue(), 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(outer))
        painter.drawEllipse(QRectF(sx - glow_r, sy - glow_r, glow_r * 2, glow_r * 2))
        painter.setBrush(QBrush(inner))
        ir = core_r * 1.6
        painter.drawEllipse(QRectF(sx - ir, sy - ir, ir * 2, ir * 2))

    def _thin_pen(self, color: QColor, width: float) -> QPen:
        pen = QPen(color, width)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def paint(self, painter: QPainter, bounds_w: int, bounds_h: int) -> None:
        margin = 2
        frame = QRectF(
            margin,
            margin,
            max(1.0, bounds_w - 2 * margin),
            max(1.0, bounds_h - 2 * margin),
        )
        radius = min(frame.width() * 0.22, frame.height() * 0.018, 18.0)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(frame, radius, radius)
        painter.setClipPath(bg_path)
        cx = frame.center().x()
        cy = frame.center().y()
        # Map unit cube ±1 to frame edges (depth on X only for parallax).
        scale_x = frame.width() * 0.49
        pitch = 0.14 * math.sin(self._x_rot) + 0.06 * math.sin(self._x_rot * 0.43 + 0.8)
        max_yr = abs(math.cos(pitch)) + abs(math.sin(pitch))
        scale_y = (frame.height() * 0.5) / max(1.0, max_yr)

        edge_bg = QLinearGradient(0, 0, bounds_w, 0)
        edge_positions = (0.0, 0.28, 0.48, 0.62, 0.74, 0.84, 0.93, 1.0)
        edge_colors = (
            (168, 85, 247),
            (155, 72, 238),
            (130, 58, 215),
            (100, 42, 175),
            (70, 30, 120),
            (42, 20, 72),
            (18, 10, 32),
            (6, 10, 22),
        )
        for pos, (r, g, b), alpha in zip(edge_positions, edge_colors, RAIL_EDGE_PURPLE_ALPHAS):
            edge_bg.setColorAt(pos, QColor(r, g, b, alpha))
        painter.fillPath(bg_path, QColor(8, 14, 32, RAIL_BASE_ALPHA))
        painter.fillPath(bg_path, QBrush(edge_bg))

        projected = [
            (self._project(n.x, n.y, n.z, cx, cy, scale_x, scale_y, pitch), n)
            for n in self._nodes
        ]

        for i in range(len(projected)):
            (x1, y1, _), n1 = projected[i]
            for j in range(i + 1, len(projected)):
                (x2, y2, _), n2 = projected[j]
                dx = n1.x - n2.x
                dy = n1.y - n2.y
                dz = n1.z - n2.z
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                if dist >= self._link_dist:
                    continue
                t_dist = dist / self._link_dist
                mid_y = (y1 + y2) * 0.5
                grad_t = mid_y / max(1.0, bounds_h)
                fade = (1.0 - t_dist) ** 1.4
                glow_col = self._neon_at_t(grad_t, int(28 * fade + 12))
                core_col = self._neon_at_t(grad_t, int(110 * fade + 45))
                painter.setPen(self._thin_pen(glow_col, 0.85 * fade + 0.35))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                painter.setPen(self._thin_pen(core_col, 0.55 * fade + 0.25))
                painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        for (sx, sy, depth), node in projected:
            pulse = 0.55 + 0.45 * math.sin(node.pulse)
            grad_t = sy / max(1.0, bounds_h)
            self._draw_node(painter, sx, sy, grad_t, pulse, depth)
