"""Serial piezo driver over USB to a Teensy 4.1.

Firmware lives in ``firmware/teensy41_piezo`` and speaks this protocol today.
This Python class is still a stub — wire it to COM5 next session. SET
millivolts are DAC output (0..2500 mV, full scale 2.5 V), not stack volts.
Park/boot is 0 V; mid-bias after the HV amp is 1.25 V -> 37.5 V.
See docs/BENCH_CONSTANTS.md.

    Host -> Teensy                 Teensy -> Host
    -------------------------      --------------------------
    SET <axis> <millivolts>        OK <axis> <applied_mv>
    GET                           STATUS <mv0> <mv1> <flags>
    STOP                          OK STOP
    CLR                           OK CLR
    PING                          PONG <fw_version>
    TEST                          OK TEST 1000 2000

``flags`` bit0 = clamped.
"""

from __future__ import annotations

from config import PIEZO_MAX_V
from core.hardware.piezo_driver import PiezoDriver, PiezoStatus

DEFAULT_BAUD = 115200


class SerialPiezoDriver(PiezoDriver):
    """Host side of the Teensy serial link. Not wired to pyserial yet."""

    def __init__(self, port: str, *, baud: int = DEFAULT_BAUD, v_max: float = PIEZO_MAX_V) -> None:
        self.port = port
        self.baud = baud
        self._v_max = v_max
        self._serial = None  # pyserial.Serial once implemented

    def _not_ready(self) -> NotImplementedError:
        return NotImplementedError(
            "SerialPiezoDriver is not wired yet. Firmware is on the Teensy "
            "(firmware/teensy41_piezo); use SimPiezoDriver for Simulation #2."
        )

    def connect(self) -> None:
        raise self._not_ready()

    def disconnect(self) -> None:
        if self._serial is not None:  # pragma: no cover - no host wiring
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
