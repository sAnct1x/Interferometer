"""Alignment trend graphs for efficiency and waist stability over time."""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout

from gui.glass_panel import GlassPanel
from gui.typography import style_neon_plot


def _style(plot: pg.PlotWidget, x_label: str, y_label: str) -> None:
    style_neon_plot(plot, x_label, y_label)


class TrendPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Alignment Trends")
        self._t0 = time.time()
        self._eta_t: list[float] = []
        self._eta_v: list[float] = []
        self._w0_t: list[float] = []
        self._w0_v: list[float] = []
        self._autorange_last_t: float = 0.0

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)

        row = QHBoxLayout()
        self._eta_plot = pg.PlotWidget(title="Coupling η vs time")
        self._w0_plot = pg.PlotWidget(title="w₀ stability vs time")
        _style(self._eta_plot, "time (s)", "η (%)")
        _style(self._w0_plot, "time (s)", "1/e² width (µm)")
        self._eta_plot.setMinimumHeight(0)
        self._w0_plot.setMinimumHeight(0)
        self._eta_curve = self._eta_plot.plot(
            pen=pg.mkPen("#00f5ff", width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush="#f472b6",
        )
        self._w0_curve = self._w0_plot.plot(
            pen=pg.mkPen("#f472b6", width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush="#a855f7",
        )
        row.addWidget(self._eta_plot)
        row.addWidget(self._w0_plot)
        layout.addLayout(row)

    def reset(self) -> None:
        self._t0 = time.time()
        self._eta_t.clear()
        self._eta_v.clear()
        self._w0_t.clear()
        self._w0_v.clear()
        self._eta_curve.setData([], [])
        self._w0_curve.setData([], [])

    def append_sample(self, *, eta_pct: float | None = None, w0_um: float | None = None) -> None:
        t = time.time() - self._t0
        if eta_pct is not None and eta_pct == eta_pct:
            self._eta_t.append(t)
            self._eta_v.append(float(eta_pct))
            if len(self._eta_t) > 400:
                self._eta_t = self._eta_t[-400:]
                self._eta_v = self._eta_v[-400:]
            self._eta_curve.setData(np.asarray(self._eta_t), np.asarray(self._eta_v))

        if w0_um is not None and w0_um == w0_um:
            self._w0_t.append(t)
            self._w0_v.append(float(w0_um))
            if len(self._w0_t) > 400:
                self._w0_t = self._w0_t[-400:]
                self._w0_v = self._w0_v[-400:]
            self._w0_curve.setData(np.asarray(self._w0_t), np.asarray(self._w0_v))

        if (eta_pct is not None and eta_pct == eta_pct) or (w0_um is not None and w0_um == w0_um):
            now = time.time()
            if now - self._autorange_last_t >= 0.5:
                self._autorange_last_t = now
                if self._eta_t:
                    self._eta_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)
                if self._w0_t:
                    self._w0_plot.enableAutoRange(axis=pg.ViewBox.XYAxes, enable=True)

    def summary(self) -> dict:
        """Aggregate η and w₀ samples for post-simulation reporting."""
        duration_s = 0.0
        if self._eta_t or self._w0_t:
            duration_s = max(
                self._eta_t[-1] if self._eta_t else 0.0,
                self._w0_t[-1] if self._w0_t else 0.0,
            )

        def _stats(values: list[float]) -> dict | None:
            if not values:
                return None
            arr = np.asarray(values, dtype=np.float64)
            return {
                "mean": float(np.mean(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "last": float(arr[-1]),
                "n": int(arr.size),
            }

        return {
            "duration_s": duration_s,
            "eta": _stats(self._eta_v),
            "w0": _stats(self._w0_v),
        }
