"""Simulated piezo driver: the only working ``PiezoDriver`` until hardware exists.

Wraps a ``SimBench`` so voltage commands move the synthetic Mirror-5 tilt that
the simulated cameras see. Commands are logged (command/response) so the piezo
panel can show a tuning transcript, mirroring what the real serial link will do.
"""

from __future__ import annotations

import time
from collections import deque

from config import PIEZO_MAX_V
from core.hardware.piezo_driver import PiezoDriver, PiezoStatus
from core.simulation.sim_bench import SimBench


class SimPiezoDriver(PiezoDriver):
    """Two-axis actuator backed by the Simulation #2 world."""

    def __init__(self, bench: SimBench, *, v_max: float = PIEZO_MAX_V, log_len: int = 500) -> None:
        self._bench = bench
        self._v_max = v_max
        self._v_park = v_max / 2.0  # mid-range = neutral tilt
        self._connected = False
        self._clamped = False
        self._fault: str | None = None
        self.log: deque[tuple[float, str, str]] = deque(maxlen=log_len)

    # -- transport ----------------------------------------------------------
    def connect(self) -> None:
        self._connected = True
        self._fault = None
        self._record("CONNECT", "OK (simulated)")

    def disconnect(self) -> None:
        self._connected = False
        self._record("DISCONNECT", "OK")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- commands -----------------------------------------------------------
    def set_voltage(self, axis: int, volts: float) -> None:
        if not self._connected:
            self._record(f"SET {axis} {volts:.2f}", "ERR not connected")
            return
        if self._fault is not None:
            self._record(f"SET {axis} {volts:.2f}", f"ERR fault:{self._fault}")
            return
        clamped = min(max(volts, 0.0), self._v_max)
        self._clamped = clamped != volts
        self._bench.command_voltage(axis, clamped)
        note = " (clamped)" if self._clamped else ""
        self._record(f"SET {axis} {volts:.2f}", f"OK {clamped:.2f}{note}")

    def get_status(self) -> PiezoStatus:
        v = self._bench.voltages()
        tilt = self._bench.tilt_urad()
        return PiezoStatus(
            connected=self._connected,
            voltage_v=(float(v[0]), float(v[1])),
            tilt_urad=(float(tilt[0]), float(tilt[1])),
            clamped=self._clamped,
            fault=self._fault,
        )

    def emergency_stop(self) -> None:
        for axis in range(self._bench.n_axes):
            self._bench.command_voltage(axis, self._v_park)
        self._fault = "E-STOP"
        self._record("ESTOP", f"parked at {self._v_park:.1f} V")

    def clear_fault(self) -> None:
        """Release an e-stop latch so commands are accepted again."""
        self._fault = None
        self._record("CLEAR_FAULT", "OK")

    def _record(self, command: str, response: str) -> None:
        self.log.append((time.monotonic(), command, response))
