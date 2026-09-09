# Weekend lab log (fill this in)

Print this or copy it. Every blank you skip is a measurement you will
forget. The how-to is `docs/WEEKEND_NPC3_GUIDE.md`.

Name: ________________________    Dates: ____________________

---

## Gear in front of you

- [ ] Teensy 4.1 on breadboard, USB on the right
- [ ] Zonrt DAC, OUTA / OUTB visible
- [ ] NPC3, front says Model NPC3, top says MIKE CHINI UCF
- [ ] Bottom label S/N **E-707744** (circle if it matches)
- [ ] PK2JA2P1 box is **closed** and not next to the HV cables
- [ ] 24 V / ≥2.5 A brick found
- [ ] DMM found, tried on a AA battery: _______ V

Teensy COM port: `COM______`    (was COM5)
NPC3 COM port:   `COM______`

---

## Day 1 — Teensy + DAC

Baud 115200.

| Command | Reply (copy exactly) |
|---------|----------------------|
| reset / plug | |
| `PING` | |
| `GET` after boot | |
| `TEST` | |
| `GET` after TEST | |
| `STOP` | |

DMM black on DAC GND.

| Point | Expected | Measured |
|-------|----------|----------|
| OUTA after `TEST` | ~1.00 V | ________ V |
| OUTB after `TEST` | ~2.00 V | ________ V |
| OUTA after `STOP` | ~0.00 V | ________ V |
| OUTB after `STOP` | ~0.00 V | ________ V |

Day 1 pass?  [ ] yes   [ ] no — stopped because: ____________________

---

## Day 2 — NPC3 alone

- [ ] `NETZ` O, nothing in PIEZO or MOD/MON
- [ ] 24 V brick into `UB`. Brick label: ________ V / ________ A
- [ ] DMM on brick (if you checked): ________ V
- [ ] `NETZ` I. TFT lived?  [ ] yes  [ ] no
- [ ] Display says NPC3 (not NPC3SG)?  [ ] yes  [ ] no

Knob parked (write the TFT volts):

| Axis | TFT volts after you zeroed it |
|------|-------------------------------|
| 1 | ________ V |
| 2 | ________ V |
| 3 | ________ V |

Day 2 pass?  [ ] yes   [ ] no

---

## Day 3 — NPC3 serial + soft start

Baud **19200**, XON/XOFF.

`ver` reply (whole thing):

```
________________________________________________
________________________________________________
```

| Command | Reply |
|---------|--------|
| `fenable,0` before change | |
| `fenable,1` before change | |
| `fenable,0,0` | (none is ok) |
| `fenable,1,0` | (none is ok) |
| `fenable,0` after | must be off: ________ |
| `fenable,1` after | must be off: ________ |
| `fready` | |
| `ERR?` | |
| `light` | |

Power-cycled and `fenable,0` still off?  [ ] yes  [ ] no
If no: I will send `fenable,0,0` and `fenable,1,0` on every boot.

Day 3 pass?  [ ] yes   [ ] no

---

## Day 4a — analog takeoff

OUTA footprint:  [ ] 5-hole SMA   [ ] 2×3 header   [ ] other: ________
OUTB footprint:  [ ] 5-hole SMA   [ ] 2×3 header   [ ] other: ________

After soldering, `TEST` again:

| Point | Measured |
|-------|----------|
| OUTA | ________ V |
| OUTB | ________ V |

DB-25 male buzzed:

- [ ] plug pin 1 → OUTA signal
- [ ] plug pin 5 → OUTB signal
- [ ] plug pin 14 → DAC GND
- [ ] pin 1 is **not** shorted to pin 5
- [ ] pin 1 is **not** shorted to pin 14

Day 4a pass?  [ ] yes   [ ] no

---

## Day 4b — DAC into MOD / MON (no stacks)

Knobs at 0. Soft start off. Cable in **MOD / MON** only.

Formula reminder: `V_piezo = −20 + 15 × V_dac` (no scaler).

| Command | DAC DMM A / B | TFT 1 / 2 | Expected TFT | MON DMM 1 / 2 |
|---------|---------------|-----------|--------------|---------------|
| `STOP` | _____ / _____ | _____ / _____ | −20 / −20 | _____ / _____ |
| `SET 0 1000` | _____ / _____ | _____ / _____ | −5 / −20 | _____ / _____ |
| `TEST` | _____ / _____ | _____ / _____ | −5 / +10 | _____ / _____ |
| `STOP` again | _____ / _____ | _____ / _____ | −20 / −20 | _____ / _____ |

Analog ear is alive (TFT went to about −20 V at `STOP`)?  [ ] yes  [ ] no

Day 4b pass?  [ ] yes   [ ] no

---

## Day 4c — which PIEZO pin is HV+ (no stacks)

`MOD / MON` unplugged. Axis1 TFT set to about **10 V**.

| Port | HV+ pin # | GND / shell? | TFT while measuring | DMM on that pin |
|------|-----------|--------------|---------------------|-----------------|
| PIEZO 1 | ________ | ________ | ________ V | ________ V |
| PIEZO 2 | ________ | ________ | ________ V | ________ V |

How I know (one sentence):

```
____________________________________________________________
```

Grey Belden free-end colors (if I buzzed them):

| Color | DA-15 pin |
|-------|-----------|
| | |
| | |

Day 4c pass?  [ ] yes   [ ] no

---

## Day 5 — path choice

I chose:  [ ] Path A analog ×4    [ ] Path B digital `set`    [ ] stop, no stack

### Path A extras

Scaler measured gain (V_mod / V_dac): ________
`SET 0 333` TFT: ________ V   (want ~0)
`SET 0 958` TFT: ________ V   (want ~37.5)

### Path B extras

```
setk,0,1
set,0,10
rk,0   → ________
set,0,37.5
rk,0   → ________
set,0,0
rk,0   → ________
```

### Stack (only if a path passed with no stack)

- [ ] `NETZ` was O when I mated the DA-15
- [ ] Soft start still off
- [ ] One stack only, PIEZO 1, red = HV+, black = GND
- [ ] First command was **10 V**, TFT: ________ V, DMM on stack: ________ V
- [ ] Then 20 V: TFT ________   DMM ________
- [ ] Then 37.5 V: TFT ________   DMM ________
- [ ] I did **not** go to 75 V this weekend
- [ ] Parked at 0 V (digital) or scaler 0 V-stack code (analog)
- [ ] `NETZ` O, unplugged, stack leads shorted and bagged

---

## Shutdown

- [ ] Teensy `STOP`, USB out
- [ ] NPC3 knobs ~0, `NETZ` O, `UB` out
- [ ] MOD / MON unplugged
- [ ] PIEZO unplugged
- [ ] Stack (if used) shorted and bagged

Notes / surprises / what to do Monday:

```
____________________________________________________________
____________________________________________________________
____________________________________________________________
```
