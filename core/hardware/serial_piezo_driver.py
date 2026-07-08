"""STUB: real piezo driver over USB serial to a Teensy 4.1.

No hardware exists yet, so this is not functional. It documents a proposed
serial protocol and implements the ``PiezoDriver`` interface so a real driver
can be dropped in with ``pyserial`` without touching the GUI or PID.

Proposed line protocol (ASCII, newline-terminated, 115200 baud):

    Host -> Teensy                 Teensy -> Host
    -------------------------      --------------------------
    SET <axis> <millivolts>\n      OK <axis> <applied_mv>\n
    GET\n                          STATUS <mv0> <mv1> <flags>\n
    STOP\n                         OK STOP\n
    CLR\n                          OK CLR\n
    PING\n                         PONG <fw_version>\n

Voltages are sent in millivolts to avoid float parsing on the MCU. The Teensy
maps mV to DAC8562 counts, the amplifier scales to the 0..75 V stack range, and
``flags`` is a bitfield (bit0 = clamped, bit1 = fault). Confirm exact framing
with firmware once it exists (see docs/MENTOR_QUESTIONS.md question 14).
"""

from __future__ import annotations

from config import PIEZO_MAX_V
from core.hardware.piezo_driver import PiezoDriver, PiezoStatus

DEFAULT_BAUD = 115200


class SerialPiezoDriver(PiezoDriver):
    """Placeholder serial driver. Raises until firmware + wiring are defined."""

    def __init__(self, port: str, *, baud: int = DEFAULT_BAUD, v_max: float = PIEZO_MAX_V) -> None:
        self.port = port
        self.baud = baud
        self._v_max = v_max
        self._serial = None  # will hold a pyserial.Serial once implemented

    def _not_ready(self) -> NotImplementedError:
        return NotImplementedError(
            "SerialPiezoDriver is a stub, no Teensy firmware or hardware yet. "
            "Use SimPiezoDriver for Simulation #2."
        )

    def connect(self) -> None:
        raise self._not_ready()

    def disconnect(self) -> None:
        if self._serial is not None:  # pragma: no cover - no hardware
            self._serial.close()
            self._serial = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None

    def set_voltage(self, axis: int, volts: float) -> None:
        raise self._not_ready()

    def get_status(self) -> PiezoStatus:
        raise self._not_ready()

    def emergency_stop(self) -> None:
        raise self._not_ready()
