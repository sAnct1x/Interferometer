"""Interface for the tip/tilt piezo actuator on Mirror 5.

Signal chain: GUI -> serial -> Teensy 4.1 -> DAC8562 -> HV amp -> PK2JA2P1.
Teensy + DAC8562 are on the bench; the HV amp is not. The GUI and PID only
see this interface, so SimPiezoDriver and SerialPiezoDriver stay interchangeable.

Two channels model the two tilt axes of the stack. Voltages are clamped to
``[0, PIEZO_MAX_V]`` by the concrete driver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PiezoStatus:
    """Snapshot of the actuator state reported back to the UI/PID."""

    connected: bool
    voltage_v: tuple[float, float]  # (axis 0, axis 1)
    tilt_urad: tuple[float, float]  # optical tilt implied by the voltages
    clamped: bool = False           # True if the last command hit a voltage limit
    fault: str | None = None        # populated on e-stop / driver error


class PiezoDriver(ABC):
    """Two-axis piezo actuator abstraction (tip/tilt on Mirror 5)."""

    #: Number of independently driven axes.
    n_axes: int = 2

    @abstractmethod
    def connect(self) -> None:
        """Open the transport (serial port, or no-op for the simulator)."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the transport and release resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the driver currently holds an open connection."""

    @abstractmethod
    def set_voltage(self, axis: int, volts: float) -> None:
        """Command one axis to ``volts`` (clamped to safe limits by the driver)."""

    @abstractmethod
    def get_status(self) -> PiezoStatus:
        """Return the latest actuator status."""

    @abstractmethod
    def emergency_stop(self) -> None:
        """Drive all axes to a safe parked voltage and latch a fault."""

    def set_voltages(self, volts: tuple[float, ...]) -> None:
        """Convenience: command every axis at once."""
        for axis, value in enumerate(volts):
            self.set_voltage(axis, value)
