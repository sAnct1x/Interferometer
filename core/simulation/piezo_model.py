"""Simulated PK2JA2P1 piezo axis: voltage in, mechanical tilt out.

Real stacks are not ideal: they lag a step command (finite response time), show
hysteresis (the displacement for a given voltage depends on whether you are
ramping up or down), and slowly creep under a held DC bias. These are modelled
here so the PID loop in Simulation #2 has something realistic to fight instead of
a perfect linear actuator.

Convention (from the Piezo Stack Report + user): the stack is DC-biased to
+4 µm, so 37.5 V (mid-range) is the operating baseline and each axis swings
-4..+4 µm about it. ``displacement_um`` is that signed deviation from baseline;
``expansion_um`` is the absolute 0..8 µm stack expansion. Two of these axes
(two stacks on the U100-A adjusters) give tip and tilt of Mirror 5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from config import PIEZO_MAX_V, PIEZO_PIVOT_ARM_MM, PIEZO_TRAVEL_UM

# Distance from the actuator push-point to the mirror pivot on the U100-A mount.
# Sets how much stack displacement (µm) becomes mechanical tilt: tilt = disp / arm.
MIRROR_LEVER_MM = PIEZO_PIVOT_ARM_MM


@dataclass
class PiezoModelParams:
    """Tunable behaviour of one simulated piezo axis."""

    v_max: float = PIEZO_MAX_V
    travel_um: float = PIEZO_TRAVEL_UM
    hysteresis_frac: float = 0.12   # fraction of travel the output lags behind
    tau_s: float = 0.05             # first-order response time constant
    lever_mm: float = MIRROR_LEVER_MM
    creep_frac: float = 0.0         # log-creep amplitude as a fraction of travel
    creep_tau_s: float = 20.0       # creep time constant (log drift under hold)

    @property
    def v_mid(self) -> float:
        return self.v_max / 2.0


class PiezoAxis:
    """One simulated actuator axis with lag + hysteresis."""

    def __init__(self, params: PiezoModelParams | None = None) -> None:
        self.params = params or PiezoModelParams()
        self._v_applied = self.params.v_mid   # actual (lagged) voltage on the stack
        self._v_commanded = self.params.v_mid
        self._direction = 0.0                 # +1 ramping up, -1 ramping down
        self._hold_time = 0.0                 # seconds the command has been held

    def reset(self) -> None:
        self._v_applied = self.params.v_mid
        self._v_commanded = self.params.v_mid
        self._direction = 0.0
        self._hold_time = 0.0

    def command(self, volts: float) -> None:
        """Set the target voltage (clamped to the safe range)."""
        clamped = min(max(volts, 0.0), self.params.v_max)
        if clamped > self._v_commanded + 1e-9:
            self._direction = 1.0
            self._hold_time = 0.0  # a fresh move resets the creep clock
        elif clamped < self._v_commanded - 1e-9:
            self._direction = -1.0
            self._hold_time = 0.0
        self._v_commanded = clamped

    def step(self, dt: float) -> None:
        """Advance the lagged voltage toward the command by ``dt`` seconds."""
        if dt <= 0 or self.params.tau_s <= 0:
            self._v_applied = self._v_commanded
        else:
            alpha = 1.0 - math.exp(-dt / self.params.tau_s)
            self._v_applied += alpha * (self._v_commanded - self._v_applied)
        self._hold_time += max(dt, 0.0)

    @property
    def voltage(self) -> float:
        """Actual voltage currently on the stack (after lag)."""
        return self._v_applied

    @property
    def displacement_um(self) -> float:
        """Signed displacement about the +4 µm baseline (-4..+4).

        Includes hysteresis (direction-dependent lag) and slow logarithmic creep
        under a held bias, per the Piezo Stack Report note about the stack
        drifting the longer a voltage is held. The PID has to keep correcting it.
        """
        p = self.params
        centered = (self._v_applied / p.v_max - 0.5) * p.travel_um
        hyst = 0.5 * p.hysteresis_frac * p.travel_um * self._direction
        creep = 0.0
        if p.creep_frac > 0 and self._hold_time > 0:
            mag = min(math.log1p(self._hold_time / max(p.creep_tau_s, 1e-3)), 3.0)
            creep = p.creep_frac * p.travel_um * math.copysign(1.0, centered) * mag
        return centered - hyst + creep

    @property
    def expansion_um(self) -> float:
        """Absolute stack expansion (0..8 µm) including the DC baseline bias."""
        return 0.5 * self.params.travel_um + self.displacement_um

    @property
    def tilt_urad(self) -> float:
        """Mechanical mirror tilt (microradians) implied by the displacement."""
        rad = (self.displacement_um / 1000.0) / self.params.lever_mm
        return rad * 1e6
