"""Weekend helper: convert DAC millivolts <-> NPC3 MOD <-> stack volts.

Examples (from the repo root):

    python scripts/npc3_volts.py
    python scripts/npc3_volts.py --piezo 37.5 --gain 4
    python scripts/npc3_volts.py --dac-mv 1000 --gain 1
    python scripts/npc3_volts.py --mod 3.833
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.hardware.npc3_map import (  # noqa: E402
    DAC_FS_V,
    clamp_stack_volts,
    dac_mv_from_piezo,
    max_piezo_from_dac,
    mod_from_piezo,
    piezo_from_dac_mv,
    piezo_from_mod,
    stack_safe_dac_mv,
)


def _print_table() -> None:
    print("NPC3 open loop:  V_piezo = -20 + 15 * V_mod")
    print("DAC today:       0 .. {:.1f} V  (SET millivolts are 1:1)".format(DAC_FS_V))
    print()
    print("Direct wire (gain=1) max stack = {:+.1f} V".format(max_piezo_from_dac(dac_gain=1)))
    print("After x4 scaler     max stack = {:+.1f} V".format(max_piezo_from_dac(dac_gain=4)))
    print()
    print(f"{'stack V':>10} {'MOD V':>10} {'DAC mV g=1':>12} {'DAC mV g=4':>12} {'PK2JA2P1':>10}")
    for v in (-20.0, 0.0, 10.0, 37.5, 75.0, 130.0):
        safe = "ok" if 0.0 <= v <= 75.0 else "NO"
        print(
            f"{v:10.1f} {mod_from_piezo(v):10.3f} "
            f"{dac_mv_from_piezo(v, dac_gain=1):12d} "
            f"{dac_mv_from_piezo(v, dac_gain=4):12d} {safe:>10}"
        )
    print()
    print("Park / STOP / CLR today = 0 mV DAC = -20 V on the NPC3. No stacks.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--piezo", type=float, help="stack volts in, print MOD + DAC")
    g.add_argument("--mod", type=float, help="MOD volts in, print stack + DAC")
    g.add_argument("--dac-mv", type=int, help="SET millivolts in, print MOD + stack")
    p.add_argument(
        "--gain",
        type=float,
        default=1.0,
        help="V_mod / V_dac (1 = direct wire, 4 = x4 scaler). Default 1.",
    )
    args = p.parse_args()

    if args.piezo is None and args.mod is None and args.dac_mv is None:
        _print_table()
        return 0

    if args.gain <= 0:
        print("gain must be positive", file=sys.stderr)
        return 2

    if args.piezo is not None:
        v = args.piezo
        print(f"stack     {v:.3f} V")
        print(f"MOD       {mod_from_piezo(v):.3f} V")
        print(f"DAC       {dac_mv_from_piezo(v, dac_gain=args.gain)} mV  (gain={args.gain:g})")
        clamped = clamp_stack_volts(v)
        if clamped != v:
            print(f"clamped   {clamped:.3f} V  (PK2JA2P1 window 0..75)")
            print(f"safe SET  {stack_safe_dac_mv(v, dac_gain=args.gain)} mV")
        return 0

    if args.mod is not None:
        v_mod = args.mod
        v = piezo_from_mod(v_mod)
        print(f"MOD       {v_mod:.3f} V")
        print(f"stack     {v:.3f} V")
        print(f"DAC       {dac_mv_from_piezo(v, dac_gain=args.gain)} mV  (gain={args.gain:g})")
        return 0

    mv = args.dac_mv
    v = piezo_from_dac_mv(mv, dac_gain=args.gain)
    print(f"DAC       {mv} mV  (gain={args.gain:g})")
    print(f"MOD       {(mv / 1000.0) * args.gain:.3f} V")
    print(f"stack     {v:.3f} V")
    if v < 0 or v > 75:
        print("warning   outside the 0..75 V PK2JA2P1 window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
