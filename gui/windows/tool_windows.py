"""Phase 3 auxiliary analysis panels as hub tiles (not separate OS windows)."""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QVBoxLayout

from gui.glass_panel import GlassPanel, PentagonButton
from gui.typography import hint_style, muted_style, primary_style, style_neon_plot, TEXT_PRIMARY


class _ToolPanel(GlassPanel):
    def __init__(
        self,
        title: str,
        description: str,
        bullets: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent, title=title)
        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(primary_style())
        layout.addWidget(desc)

        for line in bullets:
            item = QLabel(f"• {line}")
            item.setWordWrap(True)
            item.setStyleSheet(muted_style())
            layout.addWidget(item)

        layout.addStretch()


class PiezoOptimizerPanel(_ToolPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(
            "Piezo Alignment Optimizer",
            "Manual piezo voltage stepping with live centroid shift mapping for closed-loop calibration.",
            [
                "Piezo hardware is not connected in this build — use Stage Control for K-Cube jog.",
                "When a piezo driver is added, voltage steps will map to centroid shifts here.",
                "Beam centroid from the live feed still updates coupling overlay on Live Camera.",
            ],
            parent=parent,
        )


def _style_fft_plot(plot: pg.PlotWidget) -> None:
    style_neon_plot(plot, "frequency (Hz)", "power (a.u.)")


class FftDiagnosticsPanel(GlassPanel):
    monitor_toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Coupling Efficiency FFT")
        self._monitoring = False
        self._peak_line: pg.InfiniteLine | None = None

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        hint = QLabel(
            "Live FFT of fringe ROI mean intensity — exposes mains, fan tones, and bench vibration."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_style())
        layout.addWidget(hint)

        self._plot = pg.PlotWidget(title="Power spectrum")
        _style_fft_plot(self._plot)
        self._curve = self._plot.plot(pen=pg.mkPen("#00f5ff", width=2))
        layout.addWidget(self._plot, stretch=1)

        self._status = QLabel("Idle — start live feed, then monitor.")
        self._status.setStyleSheet(hint_style())
        layout.addWidget(self._status)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._start_btn = PentagonButton("Start monitor", compact=True)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn = PentagonButton("Stop monitor", compact=True)
        self._stop_btn.clicked.connect(self._stop)
        row.addWidget(self._start_btn)
        row.addWidget(self._stop_btn)
        row.addStretch()
        layout.addLayout(row)

    def _start(self) -> None:
        if not self._monitoring:
            self._monitoring = True
            self.monitor_toggled.emit(True)
            self._status.setText("Monitoring fringe ROI intensity…")

    def _stop(self) -> None:
        if self._monitoring:
            self._monitoring = False
            self.monitor_toggled.emit(False)
            self._status.setText("Monitor stopped.")

    def is_monitoring(self) -> bool:
        return self._monitoring

    def set_monitoring(self, active: bool, *, emit: bool = True) -> None:
        if active:
            if not self._monitoring:
                self._monitoring = True
                if emit:
                    self.monitor_toggled.emit(True)
                self._status.setText("Monitoring fringe ROI intensity…")
        else:
            if self._monitoring:
                self._monitoring = False
                if emit:
                    self.monitor_toggled.emit(False)
                self._status.setText("Monitor stopped.")

    def reset(self) -> None:
        self._curve.setData([], [])
        if self._peak_line is not None:
            self._plot.removeItem(self._peak_line)
            self._peak_line = None
        self._status.setText("Idle — start live feed, then monitor.")

    def update_spectrum(
        self,
        freqs_hz: np.ndarray,
        magnitudes: np.ndarray,
        *,
        peak_hz: float | None = None,
        sample_rate_hz: float | None = None,
    ) -> None:
        self._curve.setData(freqs_hz, magnitudes)
        if peak_hz is not None and peak_hz > 0:
            if self._peak_line is None:
                self._peak_line = pg.InfiniteLine(
                    pos=peak_hz,
                    angle=90,
                    pen=pg.mkPen("#f472b6", width=1, style=Qt.PenStyle.DashLine),
                )
                self._plot.addItem(self._peak_line)
            else:
                self._peak_line.setPos(peak_hz)
            rate_txt = f"{sample_rate_hz:.1f} Hz" if sample_rate_hz else "—"
            self._status.setText(
                f"Peak tone: {peak_hz:.2f} Hz · sample rate {rate_txt}"
            )


class TaskManagerPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Atria Task Manager")
        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        hint = QLabel("Bench actions performed by buttons or Atria are logged here for traceability.")
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_style())
        layout.addWidget(hint)

        self._log = QListWidget()
        self._log.setStyleSheet(
            f"background: rgba(18,8,40,0.55); color: {TEXT_PRIMARY}; "
            "border: 1px solid #a855f7; border-radius: 6px; padding: 4px;"
        )
        layout.addWidget(self._log, stretch=1)

    def log_event(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.insertItem(0, f"[{stamp}] {message}")
        if self._log.count() > 200:
            self._log.takeItem(self._log.count() - 1)
