"""Closed-loop alignment controller with selectable error source.

Three modes, all driving the two piezo axes on Mirror 5:

* ``CENTROID``   - one PID per axis on the beam centroid error (well-posed: the
                   centroid gives an independent signal per axis).
* ``EFFICIENCY`` - extremum-seeking: the only signal is scalar coupling η, so
                   each axis is dithered at a distinct frequency and η is
                   demodulated to estimate the gradient and climb uphill. This is
                   how real single-detector fiber alignment works.
* ``WEIGHTED``   - convex blend of the two commanded-voltage vectors.

The controller only computes commanded voltages; the caller applies them to a
``PiezoDriver`` and steps the world. That keeps control logic hardware-agnostic.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from core.control.pid import PIDController, PIDGains, _clamp

# Sign of the extremum-seeking integrator: +1 climbs toward maximum eta when the
# dither is slow enough that loop phase lag stays well under a quarter cycle.
ES_ASCENT_SIGN = 1.0


class ControlMode(str, Enum):
    CENTROID = "centroid"
    EFFICIENCY = "efficiency"
    WEIGHTED = "weighted"

    @property
    def label(self) -> str:
        return {
            ControlMode.CENTROID: "Centroid",
            ControlMode.EFFICIENCY: "Efficiency (η)",
            ControlMode.WEIGHTED: "Weighted",
        }[self]


@dataclass
class ControlSample:
    """Measurements available to the controller at one tick."""

    time_s: float
    centroid_error_px: tuple[float, float] | None = None
    efficiency: float | None = None  # coupling fraction 0..1


@dataclass
class ControlOutput:
    """Commanded voltages plus diagnostics for plotting/logging."""

    voltages: tuple[float, float]
    error: tuple[float, float]
    integral: tuple[float, float]
    mode: ControlMode
    efficiency: float | None = None


@dataclass
class ESParams:
    """Extremum-seeking (efficiency mode) tuning."""

    freqs_hz: tuple[float, float] = (0.5, 0.8)
    dither_v: float = 1.5
    gain: float = 60.0
    filter_tau_s: float = 0.8


class _CentroidController:
    """One PID per axis on centroid error; output is an absolute voltage."""

    # Error is in pixels; positive centroid error needs a lower voltage to
    # cancel it (see BenchModel geometry), hence the negative actuator sign.
    ACTUATOR_SIGN = -1.0

    def __init__(self, v_mid: float, v_min: float, v_max: float, gains: PIDGains) -> None:
        self.v_mid = v_mid
        span = v_max - v_mid
        self._pid = [
            PIDController(PIDGains(gains.kp, gains.ki, gains.kd), out_min=-span, out_max=span),
            PIDController(PIDGains(gains.kp, gains.ki, gains.kd), out_min=-span, out_max=span),
        ]
        self._v_min, self._v_max = v_min, v_max

    def set_gains(self, gains: PIDGains) -> None:
        for pid in self._pid:
            pid.set_gains(PIDGains(gains.kp, gains.ki, gains.kd))

    def reset(self) -> None:
        for pid in self._pid:
            pid.reset()

    def update(self, error_px: tuple[float, float], dt: float) -> tuple[tuple[float, float], tuple[float, float]]:
        volts = []
        integ = []
        for i in range(2):
            u = self._pid[i].update(error_px[i], dt)
            volts.append(_clamp(self.v_mid + self.ACTUATOR_SIGN * u, self._v_min, self._v_max))
            integ.append(self._pid[i].integral)
        return (volts[0], volts[1]), (integ[0], integ[1])


class _EfficiencyController:
    """Extremum-seeking on scalar η via per-axis dither + demodulation."""

    def __init__(self, v_mid: float, v_min: float, v_max: float, params: ESParams) -> None:
        self.params = params
        self._v_min, self._v_max = v_min, v_max
        self._base = [v_mid, v_mid]
        self._grad = [0.0, 0.0]
        self._eta_lp: float | None = None

    def set_params(self, params: ESParams) -> None:
        self.params = params

    def reset(self, v_mid: float) -> None:
        self._base = [v_mid, v_mid]
        self._grad = [0.0, 0.0]
        self._eta_lp = None

    def update(self, eta: float | None, t: float, dt: float) -> tuple[tuple[float, float], tuple[float, float]]:
        p = self.params
        if eta is None or dt <= 0:
            volts = tuple(_clamp(b, self._v_min, self._v_max) for b in self._base)
            return volts, (self._grad[0], self._grad[1])  # type: ignore[return-value]

        # Washout high-pass: remove the DC of eta so only the dither ripple
        # survives. Keep the cutoff well below the dither frequency.
        alpha = 1.0 - math.exp(-dt / max(p.filter_tau_s, 1e-3))
        if self._eta_lp is None:
            self._eta_lp = eta
        self._eta_lp += alpha * (eta - self._eta_lp)
        hp = eta - self._eta_lp

        volts = []
        for i, f in enumerate(p.freqs_hz):
            phase = 2.0 * math.pi * f * t
            demod = hp * math.sin(phase)
            # Integrate the demodulated signal straight into the base estimate
            # (the integrator IS the averaging). Slow dither keeps loop phase lag
            # small, so ES_ASCENT_SIGN = +1 climbs toward maximum eta.
            self._base[i] = _clamp(
                self._base[i] + ES_ASCENT_SIGN * p.gain * demod * dt,
                self._v_min,
                self._v_max,
            )
            # Smoothed gradient estimate, exposed only for the live plots.
            self._grad[i] += alpha * (demod - self._grad[i])
            volts.append(_clamp(self._base[i] + p.dither_v * math.sin(phase), self._v_min, self._v_max))
        return (volts[0], volts[1]), (self._grad[0], self._grad[1])


@dataclass
class AlignmentController:
    """Dispatches to centroid / efficiency / weighted control and logs history."""

    v_min: float = 0.0
    v_max: float = 75.0
    mode: ControlMode = ControlMode.CENTROID
    gains: PIDGains = field(default_factory=PIDGains)
    es_params: ESParams = field(default_factory=ESParams)
    weight: float = 0.5  # centroid share in WEIGHTED mode (0..1)
    history_len: int = 2000

    def __post_init__(self) -> None:
        self._v_mid = (self.v_min + self.v_max) / 2.0
        self._centroid = _CentroidController(self._v_mid, self.v_min, self.v_max, self.gains)
        self._efficiency = _EfficiencyController(self._v_mid, self.v_min, self.v_max, self.es_params)
        self.history: deque[dict] = deque(maxlen=self.history_len)

    # -- configuration ------------------------------------------------------
    def set_mode(self, mode: ControlMode) -> None:
        self.mode = mode

    def set_gains(self, gains: PIDGains) -> None:
        self.gains = gains
        self._centroid.set_gains(gains)

    def set_weight(self, weight: float) -> None:
        self.weight = _clamp(weight, 0.0, 1.0)

    def reset(self) -> None:
        self._centroid.reset()
        self._efficiency.reset(self._v_mid)
        self.history.clear()

    # -- main loop ----------------------------------------------------------
    def update(self, sample: ControlSample, dt: float) -> ControlOutput:
        cerr = sample.centroid_error_px or (0.0, 0.0)

        if self.mode is ControlMode.CENTROID:
            volts, integ = self._centroid.update(cerr, dt)
            error = cerr
        elif self.mode is ControlMode.EFFICIENCY:
            volts, grad = self._efficiency.update(sample.efficiency, sample.time_s, dt)
            integ = grad
            error = grad
        else:  # WEIGHTED
            cv, cinteg = self._centroid.update(cerr, dt)
            ev, grad = self._efficiency.update(sample.efficiency, sample.time_s, dt)
            w = self.weight
            volts = (w * cv[0] + (1 - w) * ev[0], w * cv[1] + (1 - w) * ev[1])
            integ = cinteg
            error = cerr

        out = ControlOutput(
            voltages=(float(volts[0]), float(volts[1])),
            error=(float(error[0]), float(error[1])),
            integral=(float(integ[0]), float(integ[1])),
            mode=self.mode,
            efficiency=sample.efficiency,
        )
        self.history.append(
            {
                "t": sample.time_s,
                "mode": self.mode.value,
                "error": out.error,
                "integral": out.integral,
                "voltages": out.voltages,
                "efficiency": sample.efficiency,
                "centroid_error_px": sample.centroid_error_px,
            }
        )
        return out
