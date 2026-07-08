"""Shared synthetic world for Simulation #2.

One ``SimBench`` ties the two piezo axes to the optical bench and a clock. The
simulated piezo driver writes commanded voltages into it, the simulated camera
sources read rendered frames out of it, and the PID reads truth signals
(coupling, centroid error) from it. Everything sees the same state, so the loop
behaves like a real closed loop.
"""

from __future__ import annotations

from core.camera_roles import CameraRole
from core.simulation.bench_model import BenchModel, BenchScenario
from core.simulation.piezo_model import PiezoAxis, PiezoModelParams

import numpy as np


class SimBench:
    """Coordinator owning piezo axes, bench optics, and simulation time."""

    def __init__(
        self,
        scenario: BenchScenario | None = None,
        piezo_params: PiezoModelParams | None = None,
    ) -> None:
        self.model = BenchModel(scenario)
        self._axes = [PiezoAxis(piezo_params), PiezoAxis(piezo_params)]
        self._t = 0.0

    # -- clock --------------------------------------------------------------
    @property
    def time_s(self) -> float:
        return self._t

    def reset(self) -> None:
        for axis in self._axes:
            axis.reset()
        self.model.reset()
        self._t = 0.0

    def set_piezo_creep_frac(self, value: float) -> None:
        """Live-tune the log-creep amplitude shared by both simulated axes."""
        for axis in self._axes:
            axis.params.creep_frac = value

    @property
    def piezo_creep_frac(self) -> float:
        return self._axes[0].params.creep_frac if self._axes else 0.0

    def step(self, dt: float) -> None:
        """Advance the piezo response and the clock by ``dt`` seconds."""
        for axis in self._axes:
            axis.step(dt)
        self._t += max(dt, 0.0)

    # -- actuator -----------------------------------------------------------
    @property
    def n_axes(self) -> int:
        return len(self._axes)

    def command_voltage(self, axis: int, volts: float) -> None:
        self._axes[axis].command(volts)

    def voltages(self) -> tuple[float, ...]:
        return tuple(a.voltage for a in self._axes)

    def tilt_urad(self) -> tuple[float, float]:
        return (self._axes[0].tilt_urad, self._axes[1].tilt_urad)

    # -- truth signals for the PID -----------------------------------------
    def coupling_fraction(self) -> float:
        return self.model.coupling_fraction(self.tilt_urad(), self._t)

    def coupling_percent(self) -> float:
        return 100.0 * self.coupling_fraction()

    def centroid_error_px(self) -> tuple[float, float]:
        return self.model.centroid_error_px(self.tilt_urad(), self._t)

    def centroid_error_magnitude_px(self) -> float:
        dx, dy = self.centroid_error_px()
        return float(np.hypot(dx, dy))

    # -- camera frames ------------------------------------------------------
    def render(self, role: CameraRole, *, scale: float = 1.0) -> np.ndarray:
        return self.model.render(role, self.tilt_urad(), self._t, scale=scale)
