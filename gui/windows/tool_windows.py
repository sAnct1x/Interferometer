"""Phase 3 auxiliary analysis panels as hub tiles (not separate OS windows)."""

from __future__ import annotations

import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from core.control.alignment import ControlMode
from core.control.pid import PIDGains
from gui.glass_panel import GlassPanel, PentagonButton
from gui.neon_theme import NEON_CYAN, NEON_PINK, NEON_PURPLE, NEON_VIOLET
from gui.typography import hint_style, muted_style, primary_style, style_neon_plot, TEXT_PRIMARY

_CTRL_FIELD_STYLE = (
    "QComboBox, QDoubleSpinBox {"
    "  min-height: 24px; padding: 2px 6px;"
    "  background: rgba(18,8,40,0.85); color: " + TEXT_PRIMARY + ";"
    "  border: 1px solid " + NEON_PURPLE + "; border-radius: 4px;"
    "}"
    "QComboBox::drop-down { border: none; width: 18px; }"
    "QComboBox QAbstractItemView {"
    "  background: rgba(12,8,32,0.97); color: " + TEXT_PRIMARY + ";"
    "  selection-background-color: rgba(168,85,247,0.45);"
    "}"
)


class PiezoControlPanel(GlassPanel):
    """Functional piezo control: connect, tune PID, jog, e-stop, watch live plots.

    Drives a ``ClosedLoopSimulation`` (simulated PK2JA2P1 on Mirror 5). If none is
    injected it owns its own loop so the tile is a self-contained demo; the hub's
    Simulation #2 mode passes a shared loop so the same piezo drives the cameras.
    """

    _AXIS_LABELS = ("Tip (θx)", "Tilt (θy)")

    def __init__(self, parent=None, *, sim=None) -> None:
        super().__init__(parent, title="Piezo Alignment: Mirror 5 (simulated)")
        if sim is None:
            from gui.sim_loop import ClosedLoopSimulation

            self._sim = ClosedLoopSimulation(self, disturbances=True)
            self._owns_sim = True
        else:
            self._sim = sim
            self._owns_sim = False

        self._t: deque[float] = deque(maxlen=600)
        self._eta: deque[float] = deque(maxlen=600)
        self._err: deque[float] = deque(maxlen=600)
        self._v0: deque[float] = deque(maxlen=600)
        self._v1: deque[float] = deque(maxlen=600)
        self._plot_decim = 0
        self._block_disturbance_signals = False

        root = QVBoxLayout(self)
        root.setContentsMargins(*self.content_margins())
        root.setSpacing(6)

        hint = QLabel(
            "Two PK2JA2P1 stacks on a U100-A mount (tip/tilt). PID minimizes error, "
            "no open-loop hill climbing. Simulated hardware; +4 µm baseline, 0–75 V."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_style())
        root.addWidget(hint)

        root.addLayout(self._build_connection_row())
        root.addLayout(self._build_mode_gain_grid())
        root.addLayout(self._build_jog_row())
        root.addLayout(self._build_disturbance_row())
        root.addWidget(self._build_plots(), stretch=1)

        self._status = QLabel("Idle: press Connect, then Arm loop.")
        self._status.setStyleSheet(hint_style())
        root.addWidget(self._status)

        self._sim.control_tick.connect(self._on_tick)
        self._sim.status_changed.connect(self._status.setText)
        self._push_gains()
        self._sync_disturbance_ui()

    # -- UI construction ----------------------------------------------------
    def _build_connection_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._connect_btn = PentagonButton("Connect", compact=True)
        self._connect_btn.clicked.connect(self._toggle_connect)
        self._arm_btn = PentagonButton("Arm loop", compact=True)
        self._arm_btn.clicked.connect(self._toggle_arm)
        self._estop_btn = PentagonButton("E-STOP", compact=True)
        self._estop_btn.clicked.connect(self._sim.emergency_stop)
        self._clear_btn = PentagonButton("Clear fault", compact=True)
        self._clear_btn.clicked.connect(self._sim.clear_fault)
        for b in (self._connect_btn, self._arm_btn, self._estop_btn, self._clear_btn):
            row.addWidget(b)
        row.addStretch()
        self._readout = QLabel("η — · err — · V —")
        self._readout.setStyleSheet(primary_style())
        row.addWidget(self._readout)
        return row

    def _build_mode_gain_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        mode_lbl = QLabel("Error source:")
        mode_lbl.setStyleSheet(muted_style())
        grid.addWidget(mode_lbl, 0, 0)
        self._mode_combo = QComboBox()
        self._mode_combo.setStyleSheet(_CTRL_FIELD_STYLE)
        self._mode_combo.addItem("Centroid (PID)", ControlMode.CENTROID.value)
        self._mode_combo.addItem("Efficiency η (experimental)", ControlMode.EFFICIENCY.value)
        self._mode_combo.addItem("Weighted", ControlMode.WEIGHTED.value)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        grid.addWidget(self._mode_combo, 0, 1, 1, 3)

        self._gain_spins: dict[str, QDoubleSpinBox] = {}
        for col, (name, default, step) in enumerate(
            (("Kp", 0.30, 0.05), ("Ki", 0.80, 0.05), ("Kd", 0.02, 0.01))
        ):
            lbl = QLabel(name)
            lbl.setStyleSheet(muted_style())
            grid.addWidget(lbl, 1, col * 2)
            sp = QDoubleSpinBox()
            sp.setStyleSheet(_CTRL_FIELD_STYLE)
            sp.setRange(0.0, 20.0)
            sp.setDecimals(3)
            sp.setSingleStep(step)
            sp.setValue(default)
            sp.valueChanged.connect(self._push_gains)
            grid.addWidget(sp, 1, col * 2 + 1)
            self._gain_spins[name] = sp

        wlbl = QLabel("Weight (centroid share)")
        wlbl.setStyleSheet(muted_style())
        grid.addWidget(wlbl, 2, 0, 1, 2)
        self._weight_spin = QDoubleSpinBox()
        self._weight_spin.setStyleSheet(_CTRL_FIELD_STYLE)
        self._weight_spin.setRange(0.0, 1.0)
        self._weight_spin.setDecimals(2)
        self._weight_spin.setSingleStep(0.05)
        self._weight_spin.setValue(0.5)
        self._weight_spin.valueChanged.connect(lambda v: self._sim.set_weight(float(v)))
        grid.addWidget(self._weight_spin, 2, 2)
        return grid

    def _build_jog_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        jog_lbl = QLabel("Manual jog:")
        jog_lbl.setStyleSheet(muted_style())
        row.addWidget(jog_lbl)
        self._jog_step = QDoubleSpinBox()
        self._jog_step.setStyleSheet(_CTRL_FIELD_STYLE)
        self._jog_step.setRange(0.05, 10.0)
        self._jog_step.setDecimals(2)
        self._jog_step.setSingleStep(0.25)
        self._jog_step.setValue(0.5)
        self._jog_step.setSuffix(" V")
        row.addWidget(self._jog_step)
        for axis, name in enumerate(self._AXIS_LABELS):
            minus = PentagonButton(f"{name} −", compact=True)
            plus = PentagonButton(f"{name} +", compact=True)
            minus.clicked.connect(lambda _=False, a=axis: self._sim.jog(a, -self._jog_step.value()))
            plus.clicked.connect(lambda _=False, a=axis: self._sim.jog(a, self._jog_step.value()))
            row.addWidget(minus)
            row.addWidget(plus)
        row.addStretch()
        return row

    def _build_disturbance_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        lbl = QLabel("Disturbance:")
        lbl.setStyleSheet(muted_style())
        row.addWidget(lbl)

        self._drift_amp_spins: list[QDoubleSpinBox] = []
        for axis_lbl in ("X", "Y"):
            a_lbl = QLabel(f"amp {axis_lbl}")
            a_lbl.setStyleSheet(muted_style())
            row.addWidget(a_lbl)
            sp = QDoubleSpinBox()
            sp.setStyleSheet(_CTRL_FIELD_STYLE)
            sp.setRange(0.0, 60.0)
            sp.setDecimals(1)
            sp.setSingleStep(1.0)
            sp.setSuffix(" px")
            sp.setFixedWidth(72)
            sp.valueChanged.connect(self._push_disturbance)
            row.addWidget(sp)
            self._drift_amp_spins.append(sp)

        period_lbl = QLabel("period")
        period_lbl.setStyleSheet(muted_style())
        row.addWidget(period_lbl)
        self._drift_period_spin = QDoubleSpinBox()
        self._drift_period_spin.setStyleSheet(_CTRL_FIELD_STYLE)
        self._drift_period_spin.setRange(2.0, 300.0)
        self._drift_period_spin.setDecimals(0)
        self._drift_period_spin.setSingleStep(1.0)
        self._drift_period_spin.setSuffix(" s")
        self._drift_period_spin.setFixedWidth(72)
        self._drift_period_spin.valueChanged.connect(self._push_disturbance)
        row.addWidget(self._drift_period_spin)

        noise_lbl = QLabel("noise")
        noise_lbl.setStyleSheet(muted_style())
        row.addWidget(noise_lbl)
        self._noise_spin = QDoubleSpinBox()
        self._noise_spin.setStyleSheet(_CTRL_FIELD_STYLE)
        self._noise_spin.setRange(0.0, 10.0)
        self._noise_spin.setDecimals(2)
        self._noise_spin.setSingleStep(0.1)
        self._noise_spin.setSuffix(" px")
        self._noise_spin.setFixedWidth(72)
        self._noise_spin.valueChanged.connect(self._push_disturbance)
        row.addWidget(self._noise_spin)

        self._calm_btn = PentagonButton("Calm bench", compact=True)
        self._calm_btn.setToolTip("Zero out thermal sway (keeps a little centroid noise)")
        self._calm_btn.clicked.connect(lambda: self._apply_disturbance_preset(calm=True))
        row.addWidget(self._calm_btn)
        self._realistic_btn = PentagonButton("Realistic", compact=True)
        self._realistic_btn.setToolTip("Restore the default thermal sway + piezo creep")
        self._realistic_btn.clicked.connect(lambda: self._apply_disturbance_preset(calm=False))
        row.addWidget(self._realistic_btn)
        row.addStretch()
        return row

    def _build_plots(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._eta_plot = pg.PlotWidget()
        style_neon_plot(self._eta_plot, "time (s)", "η % / error px")
        self._eta_curve = self._eta_plot.plot(pen=pg.mkPen(NEON_CYAN, width=2), name="η%")
        self._err_curve = self._eta_plot.plot(pen=pg.mkPen("#ff5db1", width=2), name="err px")
        lay.addWidget(self._eta_plot, stretch=1)

        self._v_plot = pg.PlotWidget()
        style_neon_plot(self._v_plot, "time (s)", "command V")
        self._v0_curve = self._v_plot.plot(pen=pg.mkPen(NEON_VIOLET, width=2))
        self._v1_curve = self._v_plot.plot(pen=pg.mkPen("#ffd24a", width=2))
        lay.addWidget(self._v_plot, stretch=1)
        return wrap

    # -- control callbacks --------------------------------------------------
    def _toggle_connect(self) -> None:
        if self._sim.is_connected:
            self._sim.disconnect_driver()
            self._connect_btn.setText("Connect")
            self._arm_btn.setText("Arm loop")
        else:
            self._sim.connect_driver()
            self._connect_btn.setText("Disconnect")

    def _toggle_arm(self) -> None:
        new_state = not self._sim.is_auto
        self._sim.set_auto(new_state)
        self._arm_btn.setText("Disarm loop" if new_state else "Arm loop")
        if new_state and not self._sim.is_connected:
            self._connect_btn.setText("Disconnect")

    def sync_buttons(self) -> None:
        """Refresh Connect/Arm button labels from the loop state.

        Used when the loop is driven programmatically (e.g. dashboard starts
        Simulation #2) so the tile buttons reflect the real connect/arm state.
        """
        self._connect_btn.setText("Disconnect" if self._sim.is_connected else "Connect")
        self._arm_btn.setText("Disarm loop" if self._sim.is_auto else "Arm loop")

    def _on_mode_changed(self) -> None:
        self._sim.set_mode(ControlMode(self._mode_combo.currentData()))

    def _push_gains(self, *_args) -> None:
        self._sim.set_gains(
            PIDGains(
                kp=self._gain_spins["Kp"].value(),
                ki=self._gain_spins["Ki"].value(),
                kd=self._gain_spins["Kd"].value(),
            )
        )

    def _push_disturbance(self, *_args) -> None:
        if self._block_disturbance_signals:
            return
        self._sim.set_disturbance_params(
            drift_amp_px=(self._drift_amp_spins[0].value(), self._drift_amp_spins[1].value()),
            drift_period_s=self._drift_period_spin.value(),
            noise_px=self._noise_spin.value(),
        )

    def _apply_disturbance_preset(self, *, calm: bool) -> None:
        from gui.sim_loop import CALM_DISTURBANCE, REALISTIC_DISTURBANCE

        preset = CALM_DISTURBANCE if calm else REALISTIC_DISTURBANCE
        self._sim.set_disturbance_params(**preset)
        self._sync_disturbance_ui()

    def _sync_disturbance_ui(self) -> None:
        """Reflect the loop's current disturbance settings in the spinboxes."""
        snap = self._sim.disturbance_snapshot()
        self._block_disturbance_signals = True
        try:
            ax, ay = snap["drift_amp_px"]
            self._drift_amp_spins[0].setValue(ax)
            self._drift_amp_spins[1].setValue(ay)
            self._drift_period_spin.setValue(snap["drift_period_s"])
            self._noise_spin.setValue(snap["noise_px"])
        finally:
            self._block_disturbance_signals = False

    def _on_tick(self, rec: dict) -> None:
        v = rec["voltages"]
        self._t.append(rec["t"])
        self._eta.append(rec["eta_pct"])
        self._err.append(rec["err_px"])
        self._v0.append(v[0])
        self._v1.append(v[1])
        self._readout.setText(
            f"η {rec['eta_pct']:.1f}% · err {rec['err_px']:.1f}px · "
            f"V ({v[0]:.1f}, {v[1]:.1f})" + ("  ⛔FAULT" if rec.get("fault") else "")
        )
        # Throttle the (relatively expensive) plot redraw to ~10 Hz.
        self._plot_decim = (self._plot_decim + 1) % 3
        if self._plot_decim == 0:
            xs = list(self._t)
            self._eta_curve.setData(xs, list(self._eta))
            self._err_curve.setData(xs, list(self._err))
            self._v0_curve.setData(xs, list(self._v0))
            self._v1_curve.setData(xs, list(self._v1))

    # -- lifecycle (only when we own the loop) ------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._owns_sim:
            self._sim.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._owns_sim:
            self._sim.stop()


# Backwards-compatible name used by the dashboard tile registry.
PiezoOptimizerPanel = PiezoControlPanel


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
            "Live FFT of fringe ROI mean intensity. Shows up mains hum, fan tones, and bench vibration."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(muted_style())
        layout.addWidget(hint)

        self._plot = pg.PlotWidget(title="Power spectrum")
        _style_fft_plot(self._plot)
        self._curve = self._plot.plot(pen=pg.mkPen(NEON_CYAN, width=2))
        layout.addWidget(self._plot, stretch=1)

        self._status = QLabel("Idle: start live feed, then monitor.")
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
        self._status.setText("Idle: start live feed, then monitor.")

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
                    pen=pg.mkPen(NEON_PINK, width=1, style=Qt.PenStyle.DashLine),
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
            f"border: 1px solid {NEON_PURPLE}; border-radius: 6px; padding: 4px;"
        )
        layout.addWidget(self._log, stretch=1)

    def log_event(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.insertItem(0, f"[{stamp}] {message}")
        if self._log.count() > 200:
            self._log.takeItem(self._log.count() - 1)
