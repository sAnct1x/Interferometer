"""Newport NPC3 open-loop voltage map (analog MOD and DAC millivolts).

NPC3 analog input is 0..10 V. In open loop (this bench unit, S/N E-707744):

    V_piezo = -20 + 15 * V_mod

The Zonrt DAC8562 on the bench is 0..2.5 V at gain = 1 (SET millivolts are
1:1 with OUTA/OUTB). A ``dac_gain`` of 4 models a 0..2.5 V -> 0..10 V scaler
in front of MOD; 1 is a direct DAC-to-MOD lead (max stack voltage 17.5 V).

PK2JA2P1 stacks must stay in ``[0, PIEZO_MAX_V]``. DAC park = 0 V maps to
-20 V on the NPC3 — do not connect stacks at that park. See
``docs/WEEKEND_NPC3_GUIDE.md`` and ``docs/NPC3_DAC_HOOKUP.md``.
"""

from __future__ import annotations

from config import DAC_FS_V, NPC3_MOD_FS, NPC3_V_MAX, NPC3_V_MIN, PIEZO_MAX_V

# V_piezo = NPC3_V_MIN + (NPC3_V_MAX - NPC3_V_MIN) * (V_mod / NPC3_MOD_FS)
_NPC3_SLOPE = (NPC3_V_MAX - NPC3_V_MIN) / NPC3_MOD_FS  # 15 V/V


def piezo_from_mod(v_mod: float) -> float:
    """NPC3 stack volts from a 0..10 V modulation voltage."""
    return NPC3_V_MIN + _NPC3_SLOPE * v_mod


def mod_from_piezo(v_piezo: float) -> float:
    """Modulation volts that produce ``v_piezo`` on the NPC3 (open loop)."""
    return (v_piezo - NPC3_V_MIN) / _NPC3_SLOPE


def dac_volts_from_piezo(v_piezo: float, *, dac_gain: float = 1.0) -> float:
    """DAC output volts (before ``dac_gain``) for a desired stack voltage.

    ``dac_gain`` is V_mod / V_dac. Direct wire = 1; ×4 scaler = 4.
    """
    if dac_gain <= 0:
        raise ValueError("dac_gain must be positive")
    return mod_from_piezo(v_piezo) / dac_gain


def dac_mv_from_piezo(v_piezo: float, *, dac_gain: float = 1.0) -> int:
    """Nearest SET millivolt for ``v_piezo`` at the given scaler gain."""
    return int(round(dac_volts_from_piezo(v_piezo, dac_gain=dac_gain) * 1000.0))


def piezo_from_dac_mv(mv: int, *, dac_gain: float = 1.0) -> float:
    """Stack volts implied by a SET millivolt command."""
    return piezo_from_mod((mv / 1000.0) * dac_gain)


def clamp_stack_volts(v_piezo: float, *, v_max: float = PIEZO_MAX_V) -> float:
    """Keep a PK2JA2P1 in [0, v_max]. Negative NPC3 swing is rejected."""
    return min(max(v_piezo, 0.0), v_max)


def stack_safe_dac_mv(v_piezo: float, *, dac_gain: float = 4.0, v_max: float = PIEZO_MAX_V) -> int:
    """SET millivolts for a stack voltage, clamped to the PK2JA2P1 window."""
    return dac_mv_from_piezo(clamp_stack_volts(v_piezo, v_max=v_max), dac_gain=dac_gain)


def max_piezo_from_dac(*, dac_gain: float = 1.0) -> float:
    """Highest NPC3 output the DAC can command at ``DAC_FS_V``."""
    return piezo_from_mod(DAC_FS_V * dac_gain)
