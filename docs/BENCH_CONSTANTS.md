# Bench constants (520 nm wedge fiber-coupling)

Single source of truth is `config.py`; this file explains each value and its
origin. Cameras and the Teensy 4.1 + DAC8562 path are on the bench.
The HV amp is the **Newport NPC3** (S/N E-707744, open-loop, −20…+130 V).
PK2JA2P1 stacks are not connected yet — see `docs/NPC3_DAC_HOOKUP.md`.
Stack voltages below are still design targets from the Piezo Stack Report.

## Optical

| Constant | Value | Notes |
|----------|-------|-------|
| `LASER_WAVELENGTH_NM` | 520.0 | Green diode; pre-measured, not scanned on this bench |
| `BEAM_WAIST_TARGET_UM` | (280, 300) | 1/e² waist target at the fiber face (~2/3 of the bore) |
| `FIBER_TARGET_ID_UM` | 450.0 | Hollow-core fiber bore for the coupling reticle (was wrongly 300) |
| `PATH_M3_TO_FARFIELD_MM` | 500 | Mirror 3 → flats → wedge (reflect) → Far Field camera |
| `PATH_M3_TO_FIBER_MM` | 500 | Mirror 3 → flats → wedge (transmit) → fiber |
| `CURVED_MIRROR_FOCAL_MM` | (250, 100, 500) | Curved mirrors in beam order |

## Piezo (Thorlabs PK2JA2P1 ×2, simulated)

| Constant | Value | Notes |
|----------|-------|-------|
| `PIEZO_MIRROR` | "M5" | Steering mirror, upstream of the wedge |
| `PIEZO_MAX_V` | 75.0 | Drive voltage for full stroke |
| `PIEZO_TRAVEL_UM` | 8.0 | Full stroke (±15% per datasheet) |
| `PIEZO_BASELINE_UM` | 4.0 | DC bias operating point; stack sits at +4 µm and swings ±4 µm |
| `PIEZO_EXPANSION_UM_PER_V` | 0.106 | Datasheet expansion rate (8/75 ≈ 0.107) |
| `PIEZO_PIVOT_ARM_MM` | 15.0 | Actuator-to-pivot distance on the U100-A (report value; refine when measured) |

Two single-axis stacks replace two adjuster screws of the Newport **U100-A**
ULTIMA mount (tip θx, tilt θy), driven by a 2-channel DAC8562 → **NPC3**. Alignment
is a **PID on centroid error**, not open-loop hill climbing (hysteresis + creep
make absolute positioning unreliable; see the Piezo Stack Report).

## Teensy 4.1 + Zonri DAC8562 (bring-up 2026-08-26)

Firmware: `firmware/teensy41_piezo` (v0.4.0). USB Serial on **COM5**, board
serial `20022040` (`VID_16C0` `PID_0483`). Host class
`SerialPiezoDriver` is still a stub. Weekend bring-up (plain words, every
step): `docs/WEEKEND_NPC3_GUIDE.md`. Short sheet: `docs/NPC3_DAC_HOOKUP.md`.

Verified on the bench: bit-bang SPI, internal 2.5 V ref, gain = 1, both
channels track SET. DMM: OUTA 1.00 V and OUTB 2.00 V after `TEST`.

### Wiring (leave this up)

| Teensy 4.1 | DAC8562 |
|---|---|
| GND | GND |
| 3.3V | VCC / AVDD (not 5 V — Teensy I/O is not 5 V tolerant) |
| 11 | DIN |
| 13 | SCLK |
| 10 | SYNC |
| (jumper on DAC only) | LDAC → DAC GND |
| (jumper on DAC only) | CLR → DAC VCC |

### DAC output voltages — do not mix these up

`SET` millivolts are **DAC analog out**, 0..2500 (full scale 2.5 V). They are
**not** stack volts and they are **not** NPC3 MOD volts.

The NPC3 analog input is 0..10 V. Open loop: `V_piezo = -20 + 15 × V_mod`.
Direct-wiring today's 0..2.5 V DAC into MOD tops out at **17.5 V** on the stack
and today's 0 V park becomes **−20 V** (fatal for a PK2JA2P1). A ×4 scaler
(or digital `set` on USB/RS-232) is required before any stack is attached.
Helpers: `core/hardware/npc3_map.py`. Full pinout and bring-up:
`docs/NPC3_DAC_HOOKUP.md`.

| State | OUTA | OUTB | When |
|-------|------|------|------|
| **Park (boot / STOP / CLR)** | 0 V | 0 V | Default now. Safe with no amp/stacks. **Unsafe** on the NPC3 analog input. |
| **Mid-bias (after ×4 scaler)** | 0.958 V | 0.958 V | Maps to MOD 3.833 V → 37.5 V / +4 µm. Unreachable without a scaler. |
| **Bring-up TEST** | 1.00 V | 2.00 V | Serial `TEST`. Proves the two channels are independent. |

Next session: analog bring-up DAC → `MOD / MON` **with no stacks**, or a digital
NPC3 driver. Do not connect the stacks until park means 0 V on the NPC3 output
and mid-bias is measured at 37.5 V.

### Derived (from the constants above)
- Piezo authority: ±4 µm over a 15 mm arm ≈ ±267 µrad mechanical → ±533 µrad beam
  → ≈ ±77 px per axis at the 500 mm Far Field arm on the CS165CU (3.45 µm px).
- Resolution: 0.1 V step (10.6 nm) ≈ 0.7 µrad ≈ 0.2 px, sub-pixel fine tuning on
  top of manual coarse alignment (datasheet sensitivity 0.14 arcsec).

## Camera (Thorlabs CS165CU Zelux)

| Constant | Value | Notes |
|----------|-------|-------|
| `PIXEL_SIZE_UM` | 3.45 | Square pixels |
| `SENSOR_SIZE_PX` | (1440, 1080) | 1.6 MP |
| `CAMERA_ADC_BITS` | 10 | Frames top out at 1023 counts |
| `CAMERA_MAX_FPS` | 34.8 | Full-frame, USB 3.0 |
| `CAMERA_READ_NOISE_E` | 4.0 | < 4 e- RMS; simulated feeds add a small read-noise floor |

### Bench serial assignments

| Role | Camera # | Serial | Notes |
|------|----------|--------|-------|
| Far Field | 1 | `36158` | Wedge ghost ~500 mm out; coupling reticle |
| Image | 2 | `38173` | Ghost 2 near fiber plane (optics pending) |
| Output | 3 | `36143` | After fiber; efficiency η |

Source of truth: `CAMERA_ROLE_SERIALS` in `config.py` (also seeded into
`user_config/app_config.json`).

## Still pending mentor input
- Image camera (Ghost 2): imaged plane, total path length (d_o), and lens element
  (f) for the thin-lens d_i. `core/optics/image_camera.py` is documentation-only;
  live display uses the raw Thorcam feed — no placement math required in software.

## Camera live policy (`config.CAMERA_LIVE_POLICY`)

Three CS165CU cameras on one USB tree cannot reliably stream simultaneously.

| Policy | Use when |
|--------|----------|
| `single` (default) | Alignment or viewing one camera at a time |
| `dual_efficiency` | Live η needs Far Field + Output together |
| `all` | Legacy / debugging only |

Non-streaming roles: **Snap Frame** (exclusive USB grab) or **promote** to switch
the live stream (`single` policy).

See `docs/MENTOR_QUESTIONS.md` for remaining optics inputs.
