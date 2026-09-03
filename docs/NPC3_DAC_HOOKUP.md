# Connecting the DAC8562 to Newport NPC3 (S/N E-707744)

The bench HV amp is the **Newport NPC3** (open-loop, 3-channel, −20…+130 V,
40 mA/ch, 24 V DC / 2.5 A). It replaces the KPZ101 / Apex PA94 / PDL200 options
from the Piezo Stack Report. This unit is labeled **MIKE CHINI UCF** — treat it
as a loaner.

Firmware and host still speak **DAC millivolts** (0…2500). The NPC3 does **not**.
Do not plug the Zonrt OUTA/OUTB pads into a `PIEZO` port, and do not connect a
PK2JA2P1 until the mapping and park voltage below are measured.

Official manual (Rev A, 2017-02-16):
https://api.p1.mks.com/medias/sys_master/images/images/hca/hd1/9037536755742/User-Manual-NPC-NPCSG-Series-20170216-RevA.pdf

Voltage helpers live in `core/hardware/npc3_map.py`.

---

## What is on the bench (from the photos)

| Item | Role |
|------|------|
| Teensy 4.1 on breadboard, USB on the right, microSD on the left | SPI master + USB serial (`COM5`, board `20022040`) |
| Zonrt / ZONRT DAC8562 module (`JEE98 94V-0`) | Dual 16-bit DAC, unpopulated **OUTA** / **OUTB** pads |
| NPC3 rear: `PIEZO 1/2/3` (DA-15), `MOD / MON` (DB-25 F), `RS 232`, `UB` 24 V, `USB` B, `NETZ` | HV amp + analog/digital command |
| NPC3 front: Axis1 / Axis2 / Axis3 knobs + TFT | Manual offset (adds to analog MOD) |
| Gold SMA PCB jack | Intended analog takeoff from OUTA/OUTB |
| Grey Belden cable + DA-15 | **Actuator** cable candidate — not the DAC path |
| Thorlabs **PK2JA2P1** box (75 V, 8 µm, 3.0×3.0×10.0 mm) | Stack for Mirror 5; still disconnected |
| NPC3 underside label | name NPC3, 24 V DC, max 2.5 A, S/N **E-707744**, Made in Germany |

Leave the existing Teensy ↔ DAC SPI wiring up (see `docs/BENCH_CONSTANTS.md`).

---

## Signal chain

```
GUI / SerialPiezoDriver
        │  USB serial, SET <axis> <mV>
        ▼
   Teensy 4.1  ──SPI──►  DAC8562  OUTA / OUTB   (0 … 2.5 V today)
                                │
                    (needs 0 … 10 V — see gap below)
                                ▼
                 NPC3 MOD / MON  (DB-25, 10 kΩ)
                                │   ×15, offset −20 V
                                ▼
                 NPC3 PIEZO 1 / 2  (DA-15, −20 … +130 V)
                                │
                                ▼
                      PK2JA2P1 red (+) / black (GND)
```

Two **independent** ways to command the NPC3:

1. **Analog (this doc).** DAC → `MOD / MON`. Front knobs **add** to the analog
   voltage. Remote mode (`setk`) **disables** analog — leave remote off.
2. **Digital.** USB or RS-232 (`19200 8N1`, XON/XOFF). `setk,<ch>,1` then
   `set,<ch>,<volts>` writes stack volts directly. Better clamp, no 2.5 V vs
   10 V problem. Knobs and MOD are ignored while remote is on.

Use analog if you want the Teensy/DAC path you already brought up. Use digital
if you want a safe 0…75 V command this week without a scaler.

---

## The voltage gap (do not skip)

NPC3 open-loop analog map (`core/hardware/npc3_map.py`):

```
V_piezo = −20 + 15 × V_mod
V_mod   = (V_piezo + 20) / 15
```

| Stack goal | NPC3 MOD | DAC at gain=1 (0–2.5 V, no scaler) | DAC after ×4 scaler |
|------------|----------|------------------------------------|---------------------|
| **−20 V** (NPC3 floor — **destroys** a 75 V stack) | 0.000 V | 0 mV (today's park / STOP / CLR) | 0 mV |
| **0 V** (safe park with stacks) | 1.333 V | 1333 mV | 333 mV |
| **37.5 V** (mid-bias, +4 µm) | 3.833 V | **unreachable** | 958 mV |
| **75 V** (PK2JA2P1 full scale) | 6.333 V | **unreachable** | 1583 mV |
| **130 V** (NPC3 ceiling) | 10.000 V | — | 2500 mV |

Bench bring-up already proved OUTA/OUTB are **1:1 with SET millivolts** at gain
= 1 (TEST = 1.00 V / 2.00 V). Direct-wiring that into MOD gives a **maximum
stack voltage of 17.5 V** and, at today's 0 V park, **−20 V on the stack**.

DAC8562 gain = 2 raises the DAC to 0…5 V (55 V stack max) — still short of
75 V, and still −20 V at 0 V park.

**Do not connect the stacks** until one of these is true:

- analog path has a **×4** (or better) 0–2.5 V → 0–10 V stage **and** firmware
  parks at the 0 V-stack code, not 0 V DAC, **and** SET is clamped to ≤75 V
  stack (1583 mV DAC with ×4), or
- the host talks to the NPC3 **digitally** and clamps `set` to 0…75 V.

---

## Analog hookup: DAC → MOD / MON

`MOD / MON` is the **DB-25 female** on the rear, not `PIEZO 1/2/3`.

| Function | DB-25 pin | Use |
|----------|-----------|-----|
| MOD channel 1 (`PIEZO 1`) | 1 | OUTA (tip) after the scaler |
| MON channel 1 | 2 | DMM / scope to confirm stack volts (0–10 V ≡ −20…+130 V) |
| MOD channel 2 (`PIEZO 2`) | 5 | OUTB (tilt) after the scaler |
| MON channel 2 | 6 | same, second axis |
| MOD channel 3 (`PIEZO 3`) | 9 | unused (third stack later) |
| Ground | 14, 15, 16, 18, 19, 20, 22, 23, 24 | DAC analog GND **and** scaler GND |

Input impedance is 10 kΩ. The DAC8562 can drive that; a scaler op-amp should
too.

The manual ships a BNC-to-DB-25 adapter for this port. If that cable is missing,
build a **DB-25 male** pigtail. Do not reuse the grey DA-15 Belden cable here —
wrong connector and wrong port.

### SMA on OUTA / OUTB

The Zonrt board has two unpopulated through-hole clusters labeled **OUTA** and
**OUTB**. That is the analog takeoff.

1. Confirm the pad pattern before soldering. A 4-ground + center SMA footprint
   is fine; a 2×3 header footprint is not — use a 0.1" header and a short coax
   pigtail instead.
2. SMA center = signal, SMA shield = analog GND (same net as DAC GND / Teensy
   GND).
3. Run SMA → BNC (or SMA → the DB-25 pigtail) **only** to MOD pins 1 and 5.
4. Keep the analog return short. Do not share it with the 24 V `UB` return
   except at the NPC3 chassis / MOD grounds.

---

## Actuator hookup: PIEZO ports → PK2JA2P1

`PIEZO 1/2/3` are the **high-voltage** outputs (−20…+130 V). The rear sticker
is literal: **do not mate or unmate these with `NETZ` on**.

The Rev A manual describes the DA-15 (HV + optional SG / ID-chip) but **does
not print a pin table**. Newport also says a homemade actuator cable can void
calibration and is unsupported. Do **not** guess pins from a generic D-sub
diagram.

### Find HV+ / HV− with no stack attached

1. Power the NPC3 from 24 V (`UB`), stacks **unplugged**.
2. Disable soft start over USB/RS-232 (`fenable,0,0` and `fenable,1,0`; see
   below). Soft start otherwise sweeps **−20 → +130 V for ~10 s** on boot.
3. Zero the Axis1 / Axis2 knobs. Confirm the TFT shows ~0 V (or a known knob
   voltage) with no MOD attached.
4. With a DMM, probe the `PIEZO 1` DA-15 against chassis / a known ground pin
   and write down which pin tracks the displayed voltage.
5. Repeat for `PIEZO 2`.
6. Only then wire **PK2JA2P1 red → HV+**, **black → HV− / GND**. Never reverse;
   never apply negative bias. Capacitance is ~1 µF — 40 mA is plenty for slow
   PID.

The grey Belden DA-15 is the right *family* of connector for this port. Continuity
the other end before cutting it. A VGA-style HD-15 (3×5) will **not** mate; the
NPC3 uses a standard 2-row DA-15 (8+7).

The display may show `NOT CONNECTED` for a two-wire homemade cable. On a
non-SG NPC3 that is often just “no ID chip,” not “HV is dead,” but confirm with
the DMM on the port **before** attaching a stack.

---

## Soft start, knobs, and remote

| Risk | What happens | What to do |
|------|----------------|------------|
| Soft start (`fenable` / `fready`) | Boot sweep −20…+130 V | `fenable,0,0` and `fenable,1,0` **before** any stack is connected. Read back with `fenable,0` / `fenable,1`. |
| Front knobs | Add to analog MOD. Sum must stay in 0…10 V MOD or the TFT flags UDL/OVL | Park knobs at 0 for analog PID. |
| `setk,<ch>,1` (remote) | Disables knobs **and** MOD; `set` writes volts directly | Use only for the digital path. |
| Today's firmware park / STOP / CLR = 0 V DAC | Maps to **−20 V** on the NPC3 | Change park only after the scaler (or digital) path is chosen. Safe on the DAC alone. |

USB/RS-232 notes from the manual: 19200 8N1, software flow control. Channels
are 0-based (`PIEZO 1` = channel 0). After Enter the prompt is `NPC3>`.
`set,0,37.5` means **37.5 V** in open loop (this unit is not an SG).

---

## Bring-up order (no stacks until step 6)

1. Teensy + DAC only. `PING` / `TEST` / DMM on OUTA/OUTB as already recorded
   (1.00 V / 2.00 V).
2. Power NPC3 from 24 V. No piezos. Confirm TFT, knobs, and that this is
   **NPC3** (open loop), not NPC3SG.
3. Serial: `ver`, `fenable,0,0`, `fenable,1,0`, knobs at 0.
4. Analog: SMA/header on OUTA/OUTB → MOD 1 / MOD 2 + GND. `SET 0 1000` should
   move Axis1 on the TFT toward **−20 + 15×1.0 = −5 V** if wired 1:1 (no scaler
   yet). `SET 0 0` should go to **−20 V**. Cross-check MON pin 2 with a DMM
   (0–10 V scale).
5. Identify `PIEZO 1/2` HV pins with the DMM. Write them into this file.
6. Only then: scaler (or digital clamp) so park = 0 V stack and max = 75 V.
   Connect PK2JA2P1 red/black. First motion is a few volts around mid-bias,
   watching the TFT and a current-limited DMM.

---

## Parts still needed

- 24 V / ≥2.5 A supply if the original `UB` brick is missing
- DB-25 male (or the Newport BNC–DB-25 MOD/MON adapter) + two coax jumpers
- ×4 analog scaler **or** a decision to drive the NPC3 digitally and retire
  analog command
- Confirmed DA-15 HV pinout (measure; do not invent)
- Second PK2JA2P1 if only one box is on the bench (tip **and** tilt)

---

## Software follow-ups (not done in this pass)

- `SerialPiezoDriver` still a stub on COM5.
- Firmware park/STOP/CLR stay at 0 V DAC until the analog scaler exists.
- When analog-to-NPC3 is live, SET millivolts must be computed with
  `core.hardware.npc3_map` and clamped to 0…75 V stack.
- Digital NPC3 driver (USB/RS-232 `set` / `rk`) is a valid alternate
  `PiezoDriver` that skips the DAC for command.
