"""Single-axis PID controller with anti-windup and output clamping.

Kept deliberately generic: it maps an error signal to a bounded output. The
alignment layer (``core/control/alignment.py``) decides what the error means
(centroid pixels, efficiency gradient, or a blend) and wires one PID per piezo
axis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PIDGains:
    """Proportional / integral / derivative gains."""

    kp: float = 0.30
    ki: float = 0.80
    kd: float = 0.02


class PIDController:
    """Discrete PID with clamped integral (conditional anti-windup)."""

    def __init__(
        self,
        gains: PIDGains | None = None,
        *,
        out_min: float,
        out_max: float,
    ) -> None:
        self.gains = gains or PIDGains()
        self.out_min = out_min
        self.out_max = out_max
        self._integral = 0.0   # stored as the integral *term* value (ki already applied)
        self._prev_error: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = None

    @property
    def integral(self) -> float:
        return self._integral

    def set_gains(self, gains: PIDGains) -> None:
        self.gains = gains

    def update(self, error: float, dt: float) -> float:
        """Return the bounded control output for the current ``error``."""
        g = self.gains
        p_term = g.kp * error

        if dt > 0:
            self._integral += g.ki * error * dt
        # Clamp the integral term so it can never wind past the output limits.
        self._integral = _clamp(self._integral, self.out_min, self.out_max)

        d_term = 0.0
        if dt > 0 and self._prev_error is not None:
            d_term = g.kd * (error - self._prev_error) / dt
        self._prev_error = error

        return _clamp(p_term + self._integral + d_term, self.out_min, self.out_max)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
