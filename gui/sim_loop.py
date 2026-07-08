"""Qt-driven closed-loop engine for Simulation #2.

Owns one ``SimBench`` (with drift + creep), a ``SimPiezoDriver``, and an
``AlignmentController``. A fast timer runs the control loop; a slower timer
renders the three camera frames for display. Both the Piezo tile and the
hub's Simulation #2 mode drive their UI from the signals this emits, so what
you see on screen is the actual loop making decisions.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from config import PIXEL_SIZE_UM
from core.analytics.coupling import beam_centroid_px, fiber_target_radius_px
from core.camera_roles import ACTIVE_ROLES, CameraRole
from core.control.alignment import AlignmentController, ControlMode, ControlSample
from core.control.pid import PIDGains
from core.hardware.sim_piezo_driver import SimPiezoDriver
from core.simulation.bench_model import BenchScenario
from core.simulation.piezo_model import PiezoModelParams
from core.simulation.sim_bench import SimBench

_CONTROL_HZ = 30.0
_RENDER_HZ = 12.0
_RENDER_SCALE = 0.4  # downscaled frames keep the GUI smooth

# Single source of truth for the two disturbance presets, shared by the
# ClosedLoopSimulation constructor and the Piezo tile's "Calm bench" /
# "Realistic" preset buttons (gui/windows/tool_windows.py).
REALISTIC_DISTURBANCE: dict = {
    "drift_amp_px": (11.0, 8.0),
    "drift_period_s": 38.0,
    "noise_px": 1.2,
    "creep_frac": 0.03,
}
CALM_DISTURBANCE: dict = {
    "drift_amp_px": (0.0, 0.0),
    "drift_period_s": 40.0,
    "noise_px": 1.2,
    "creep_frac": 0.0,
}


def _realistic_scenario() -> BenchScenario:
    """Bench with bounded thermal sway so the loop must keep correcting."""
    d = REALISTIC_DISTURBANCE
    return BenchScenario(drift_amp_px=d["drift_amp_px"], drift_period_s=d["drift_period_s"])


def _realistic_piezo() -> PiezoModelParams:
    """Piezo with hysteresis + slow creep enabled (see PDF creep note)."""
    return PiezoModelParams(creep_frac=REALISTIC_DISTURBANCE["creep_frac"])


class ClosedLoopSimulation(QObject):
    """Simulated 3-camera bench + piezo + PID, tick-driven for the UI."""

    control_tick = Signal(dict)     # {t, eta_pct, err_px, voltages, tilt_urad, mode, fault}
    frames_ready = Signal(dict)     # {role: {"frame": ndarray, "overlay": dict|None}}
    status_changed = Signal(str)

    def __init__(self, parent=None, *, disturbances: bool = True) -> None:
        super().__init__(parent)
        self._disturbances = disturbances
        self._bench = SimBench(
            _realistic_scenario() if disturbances else BenchScenario(),
            _realistic_piezo() if disturbances else PiezoModelParams(),
        )
        self._driver = SimPiezoDriver(self._bench)
        self._controller = AlignmentController(
            v_min=0.0, v_max=self._driver_v_max(), mode=ControlMode.CENTROID
        )
        self._auto = False
        self._last_t: float | None = None

        self._control_timer = QTimer(self)
        self._control_timer.setInterval(int(1000 / _CONTROL_HZ))
        self._control_timer.timeout.connect(self._on_control)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(int(1000 / _RENDER_HZ))
        self._render_timer.timeout.connect(self._on_render)

    # -- accessors ----------------------------------------------------------
    def _driver_v_max(self) -> float:
        from config import PIEZO_MAX_V

        return PIEZO_MAX_V

    @property
    def controller(self) -> AlignmentController:
        return self._controller

    @property
    def driver(self) -> SimPiezoDriver:
        return self._driver

    @property
    def is_connected(self) -> bool:
        return self._driver.is_connected

    @property
    def is_auto(self) -> bool:
        return self._auto

    def far_field_frame_full_res(self) -> np.ndarray:
        """Render Far Field at full sensor resolution, for analytics (not display).

        The live display frames from ``frames_ready`` are downscaled
        (``_RENDER_SCALE``) for smooth rendering; beam-fit analytics need the
        real sensor pixel scale, so this renders on demand at ``scale=1.0``.
        """
        return self._bench.render(CameraRole.FAR_FIELD, scale=1.0)

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Begin evolving the world and rendering (loop stays manual until armed)."""
        self._last_t = time.monotonic()
        self._control_timer.start()
        self._render_timer.start()
        self.status_changed.emit("Simulation running")

    def stop(self) -> None:
        self._control_timer.stop()
        self._render_timer.stop()
        self.status_changed.emit("Simulation stopped")

    def reset(self) -> None:
        self._bench.reset()
        self._controller.reset()
        self._last_t = time.monotonic()
        self.status_changed.emit("Simulation reset")

    # -- driver / loop controls --------------------------------------------
    def connect_driver(self) -> None:
        self._driver.connect()
        self.status_changed.emit("Piezo connected (simulated)")

    def disconnect_driver(self) -> None:
        self.set_auto(False)
        self._driver.disconnect()
        self.status_changed.emit("Piezo disconnected")

    def set_auto(self, enabled: bool) -> None:
        if enabled and not self._driver.is_connected:
            self.connect_driver()
        self._auto = enabled
        self.status_changed.emit("Closed loop ON" if enabled else "Closed loop OFF (manual)")

    def emergency_stop(self) -> None:
        self._auto = False
        self._driver.emergency_stop()
        self.status_changed.emit("E-STOP: parked at baseline")

    def clear_fault(self) -> None:
        self._driver.clear_fault()
        self.status_changed.emit("Fault cleared")

    def set_mode(self, mode: ControlMode) -> None:
        self._controller.set_mode(mode)

    def set_gains(self, gains: PIDGains) -> None:
        self._controller.set_gains(gains)

    def set_weight(self, weight: float) -> None:
        self._controller.set_weight(weight)

    def set_disturbance_params(
        self,
        *,
        drift_amp_px: tuple[float, float] | None = None,
        drift_period_s: float | None = None,
        noise_px: float | None = None,
        creep_frac: float | None = None,
    ) -> None:
        """Live-tune thermal sway / centroid noise / piezo creep.

        Safe to call anytime: the bench model and piezo axes are plain
        mutable dataclasses, stepped only from this object's own QTimers on
        the GUI thread, so there is no cross-thread mutation to guard against.
        """
        scenario = self._bench.model.scenario
        if drift_amp_px is not None:
            scenario.drift_amp_px = (float(drift_amp_px[0]), float(drift_amp_px[1]))
        if drift_period_s is not None:
            scenario.drift_period_s = max(float(drift_period_s), 1e-3)
        if noise_px is not None:
            scenario.noise_px = max(float(noise_px), 0.0)
        if creep_frac is not None:
            self._bench.set_piezo_creep_frac(max(float(creep_frac), 0.0))

    def disturbance_snapshot(self) -> dict:
        """Current drift/noise/creep settings, for the tuning UI and reports."""
        scenario = self._bench.model.scenario
        return {
            "drift_amp_px": tuple(scenario.drift_amp_px),
            "drift_period_s": scenario.drift_period_s,
            "noise_px": scenario.noise_px,
            "creep_frac": self._bench.piezo_creep_frac,
        }

    def jog(self, axis: int, dv: float) -> None:
        """Nudge one axis by dv volts (manual commissioning)."""
        if not self._driver.is_connected:
            self.connect_driver()
        current = self._bench.voltages()[axis]
        self._driver.set_voltage(axis, current + dv)

    # -- timers -------------------------------------------------------------
    def _on_control(self) -> None:
        now = time.monotonic()
        dt = 0.0 if self._last_t is None else min(max(now - self._last_t, 0.0), 0.1)
        self._last_t = now

        status = self._driver.get_status()
        sample = ControlSample(
            time_s=self._bench.time_s,
            centroid_error_px=self._bench.centroid_error_px(),
            efficiency=self._bench.coupling_fraction(),
        )
        if self._auto and status.connected and status.fault is None:
            out = self._controller.update(sample, dt)
            self._driver.set_voltages(out.voltages)

        self._bench.step(dt)

        v = self._bench.voltages()
        tilt = self._bench.tilt_urad()
        self.control_tick.emit(
            {
                "t": self._bench.time_s,
                "eta_pct": self._bench.coupling_percent(),
                "err_px": self._bench.centroid_error_magnitude_px(),
                "voltages": (float(v[0]), float(v[1])),
                "tilt_urad": (float(tilt[0]), float(tilt[1])),
                "mode": self._controller.mode.value,
                "auto": self._auto,
                "fault": status.fault,
            }
        )

    def _on_render(self) -> None:
        out: dict[CameraRole, dict] = {}
        for role in ACTIVE_ROLES:
            frame = self._bench.render(role, scale=_RENDER_SCALE)
            overlay = self._far_field_overlay(frame) if role is CameraRole.FAR_FIELD else None
            out[role] = {"frame": frame, "overlay": overlay}
        self.frames_ready.emit(out)

    def _far_field_overlay(self, frame) -> dict:
        h, w = frame.shape[:2]
        tx, ty = w / 2.0, h / 2.0
        cx, cy = beam_centroid_px(frame)
        radius = fiber_target_radius_px() * _RENDER_SCALE
        err_um = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5 * (PIXEL_SIZE_UM / _RENDER_SCALE)
        return {
            "target_center_px": (tx, ty),
            "target_radius_px": radius,
            "centroid_px": (cx, cy),
            "error_um": err_um,
        }
