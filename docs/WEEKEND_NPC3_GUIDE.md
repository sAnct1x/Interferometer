# Weekend lab book: Teensy + DAC → Newport NPC3

Open this file first on Saturday. Do the days in order. Do **not** skip
ahead to the piezo stacks. If you get tired, stop at the end of any numbered
day — nothing later depends on rushing.

The short technical sheet is still `docs/NPC3_DAC_HOOKUP.md`.
Write numbers into `docs/WEEKEND_LAB_LOG.md` as you go.
Convert volts with:

```powershell
python scripts\npc3_volts.py
python scripts\npc3_volts.py --piezo 37.5 --gain 4
python scripts\npc3_volts.py --dac-mv 1000 --gain 1
```

Official NPC3 manual (Rev A, 2017-02-16):
https://api.p1.mks.com/medias/sys_master/images/images/hca/hd1/9037536755742/User-Manual-NPC-NPCSG-Series-20170216-RevA.pdf

This box is labeled **MIKE CHINI UCF**. It is a loaner. Do not open it.
Do not guess pins. Do not connect stacks until Day 5 says so.

---

## 0. The story in plain words

You want a computer to tilt Mirror 5 a tiny bit so a green laser goes into a
fiber. A **piezo stack** (Thorlabs PK2JA2P1) is a ceramic sandwich. Put a
voltage on it and it gets a few millionths of a meter longer. Two stacks
replace two screws on a Newport U100-A mount: one nods, one shakes its head.

The stack wants **0 to 75 volts**. A Teensy cannot make 75 V. The Teensy
talks to a **DAC** (digital-to-analog converter). The DAC makes a small,
accurate voltage, **0 to 2.5 V**. That little voltage is a *message*, not
the muscle.

The **NPC3** is the muscle. It is a 3-channel high-voltage amplifier.
You whisper 0 to 10 V into its ear (`MOD / MON`). It shouts −20 to +130 V
out of its mouth (`PIEZO 1/2/3`). That shout is what the stack hears.

So the chain is:

```
You type on the PC
        │  USB words like  SET 0 1000
        ▼
   Teensy 4.1   (the translator)
        │  SPI ticks (DIN, SCLK, SYNC)
        ▼
   DAC8562      (whispers 0…2.5 V on OUTA / OUTB)
        │  analog wire  —  THIS IS THE GAP (needs 0…10 V)
        ▼
   NPC3 MOD     (listens, 0…10 V)
        │  multiplies and shifts:  V_piezo = −20 + 15 × V_mod
        ▼
   NPC3 PIEZO   (shouts −20…+130 V)
        │  red / black wires
        ▼
   PK2JA2P1     (grows 0…8 µm if the voltage is 0…75 V)
```

Two different ways to talk to the NPC3:

1. **Analog (this weekend, Days 1–4).** DAC voltage into `MOD / MON`.
   The front knobs **add** to that voltage. Leave knobs at zero.
2. **Digital (optional shortcut).** USB or RS-232. You type `set,0,37.5`
   and that means **37.5 volts on the stack**, not millivolts on the DAC.
   No 2.5-vs-10 problem. Knobs and MOD are ignored while remote is on.

This book does analog first so the hardware you already built still matters.
Digital is the escape hatch if you do not have a ×4 scaler by Sunday.

---

## 1. Words you will see

| Word | Means |
|------|--------|
| **Volt (V)** | How hard electricity pushes. Wall outlet ≈ 120 V. Stack max = 75 V. DAC max = 2.5 V. |
| **Millivolt (mV)** | One thousandth of a volt. 1000 mV = 1.000 V. Teensy `SET` uses mV. |
| **DAC** | Chip that turns a number into a real voltage. Yours is a TI DAC8562 on a Zonrt / ZONRT board. |
| **OUTA / OUTB** | The two analog exits on the DAC board. A = tip, B = tilt. |
| **SPI** | How the Teensy talks to the DAC: three wires (data, clock, “now!”). Already working. |
| **MOD** | Modulation = analog *input* on the NPC3. “Please go here.” |
| **MON** | Monitor = analog *output* that copies what the amp is doing, scaled to 0…10 V. A practice meter. |
| **PIEZO 1/2/3** | High-voltage *outputs*. These can hurt you and can kill a 75 V stack. |
| **Open loop** | This NPC3 does **not** read a position sensor. The display shows volts, not microns. |
| **Soft start** | On boot the NPC3 can sweep −20 → +130 V for ~10 seconds. **Off** before any stack. |
| **Park** | The “sit still, do no harm” voltage. On the DAC today that is 0 V. On the stack it must be 0 V, never −20 V. |
| **Mid-bias** | Sit at half stroke so the stack can grow *and* shrink. 37.5 V → +4 µm. |
| **Scaler / ×4** | Extra circuit that turns 0…2.5 V into 0…10 V. You do not have this yet. |
| **DMM** | Digital multimeter. The only truth on the bench. Believe the DMM, not a hope. |
| **DA-15** | Normal 15-pin D-sub, two rows (8 + 7). `PIEZO` ports. |
| **HD-15 / VGA** | Three rows of five. **Will not** plug into the NPC3. |
| **DB-25** | 25-pin D-sub. `MOD / MON`. |
| **SMA** | Tiny threaded coax jack. Gold one in the tub is for OUTA/OUTB if the holes match. |
| **Remote (`setk`)** | PC takes over. Knobs **and** analog MOD go dead. |

Three voltages people mix up. Write this on a sticky note:

```
DAC volts     = what OUTA/OUTB actually are      (0…2.5 V today)
MOD volts     = what the NPC3 analog ear hears   (0…10 V)
PIEZO volts   = what the stack hears             (−20…+130 V on the amp,
                                                 0…75 V allowed on a PK2JA2P1)
```

`SET 0 1000` means “DAC channel A = 1000 mV = 1.000 V.”
It does **not** mean 1000 V. It does **not** mean 1 V on the stack.

---

## 2. The formula (memorize this)

The NPC3 manual says: in open loop, 0 V on MOD → −20 V on the piezo,
10 V on MOD → +130 V on the piezo. That is a straight line:

```
V_piezo = −20 + 15 × V_mod
V_mod   = (V_piezo + 20) / 15
```

Check it:

- MOD 0 V  → −20 + 0     = −20 V
- MOD 1 V  → −20 + 15    = −5 V
- MOD 10 V → −20 + 150   = +130 V
- Want 0 V on the stack  → MOD = 20/15 = **1.333 V**
- Want 37.5 V            → MOD = 57.5/15 = **3.833 V**
- Want 75 V              → MOD = 95/15  = **6.333 V**

Your DAC, today, can only make 0…2.5 V. Plug that into the formula with
no scaler (`V_mod = V_dac`):

- DAC 0 V     → stack **−20 V**   ← this is today's park. Fatal for the stack.
- DAC 1.000 V → stack **−5 V**    ← what `TEST` channel A does if you wire 1:1
- DAC 2.500 V → stack **+17.5 V** ← as high as you can go. Need 75 V.

That is the whole problem. The whisper is too quiet, and “quiet” on this
amp is not zero — it is **negative twenty volts**.

A ×4 scaler (`V_mod = 4 × V_dac`) fixes the range:

| Stack goal | MOD | DAC with no scaler | DAC after ×4 |
|------------|-----|--------------------|--------------|
| −20 V (amp floor, **bad**) | 0.000 V | 0 mV (today's park) | 0 mV |
| 0 V (safe park) | 1.333 V | 1333 mV | 333 mV |
| 37.5 V (mid-bias) | 3.833 V | cannot reach | 958 mV |
| 75 V (stack max) | 6.333 V | cannot reach | 1583 mV |
| 130 V (amp ceiling, **bad**) | 10.000 V | — | 2500 mV |

`core/hardware/npc3_map.py` is this table in code.

---

## 3. Safety rules (read out loud)

1. **The stack stays in the box until Day 5.** Days 1–4 never need it.
2. **Never plug or unplug `PIEZO` cables with `NETZ` on.** The sticker on
   the back is not decoration. High voltage lives on those pins.
3. **Never put a negative voltage on a PK2JA2P1.** Red is +, black is
   ground. Reverse or −20 V can crack the ceramic.
4. **Never put more than 75 V on a PK2JA2P1.** The NPC3 can do 130 V.
   Software and your hands must stop at 75.
5. **Turn soft start off** before a stack is even in the same zip code
   as a cable (`fenable,0,0` and `fenable,1,0`).
6. **Do not power the DAC from 5 V.** Teensy 4.1 pins die at 5 V. 3.3 V
   only. This is already wired. Do not “fix” it.
7. **Do not open the NPC3.** No user parts inside. Shock hazard.
8. **One hand in your pocket** when probing `PIEZO` pins with a DMM.
   The other hand holds the probe. You already turned `NETZ` off to
   mate connectors; probing live HV is the only time those pins are hot.
9. **If something smells, smokes, or the TFT says OVL/UDL and you do
   not know why:** `NETZ` to **O**, unplug `UB`, walk away, write down
   what you just did.

---

## 4. What is already on the bench

From the photos you sent:

| Thing | How to recognize it | Job |
|-------|---------------------|-----|
| Teensy 4.1 | Long green board on a white breadboard. USB on the **right**, microSD on the **left**, big square chip in the middle. | Talks USB to the PC and SPI to the DAC. |
| Zonrt DAC board | Smaller green board, logo **ZONRT**, pads labeled **OUTA** and **OUTB**. Header with colored jumpers. | Makes the 0…2.5 V whispers. |
| NPC3 | Black box, blue bumpers, front says **Piezo Controller · Model NPC3**, three knobs Axis1/2/3. Top sticker **MIKE CHINI UCF**. | The muscle. |
| NPC3 back | Three stacked DA-15 = `PIEZO 1/2/3`. Wide DB-25 = `MOD / MON`. Then `RS 232`, rocker `NETZ`, barrel `UB`, USB-B. | Where cables go. |
| NPC3 bottom | White label: NPC3, 24 V DC, max 2.5 A, S/N **E-707744**, Made in Germany. | Identity. |
| Gold SMA | Threaded gold jack, 4 stubby legs + 1 long center pin, in a clear tub. | Optional analog takeoff. |
| Grey Belden + DA-15 | Coiled grey cable, metal hood, **two rows** of holes (8+7). | Maybe an actuator cable. **Not** for the DAC. |
| PK2JA2P1 box | Small Thorlabs brown box. 3.0×3.0×10.0 mm, 75 V, end hemisphere. | The stack. Stays closed. |

Leave the Teensy ↔ DAC SPI wires alone. They already work (August 26):

| Teensy 4.1 | DAC8562 | What that wire is |
|------------|---------|-------------------|
| GND | GND | Shared zero. Both boards agree what “0 V” means. |
| 3.3 V | VCC / AVDD | Food for the DAC. Not 5 V. |
| pin 11 | DIN | The bits (the number). |
| pin 13 | SCLK | The clock (when to listen). |
| pin 10 | SYNC | The “this message starts now” line. |
| (jumper on DAC) | LDAC → DAC GND | “Update as soon as the bits arrive.” |
| (jumper on DAC) | CLR → DAC VCC | “Do not wipe the outputs.” |

Host firmware is `firmware/teensy41_piezo` v0.4.0. Last time it was **COM5**,
board serial `20022040` (`VID_16C0` `PID_0483`). COM numbers can move.
If Windows gives you COM7, use COM7.

---

## 5. Shopping list (buy or borrow before you solder)

You can do Days 1–3 with what you have. Day 4 needs a way into `MOD / MON`.
Day 5 needs a scaler **or** a digital decision, plus a proven DA-15 pinout.

- [ ] 24 V DC supply, **at least 2.5 A**, 2.1 mm barrel, center positive —
      if the original NPC3 brick is missing. The label says 24 V / max 2.5 A.
- [ ] Digital multimeter with sharp probes. Banana-to-grabber leads help.
- [ ] USB-A or USB-C cable for the Teensy (you already have this).
- [ ] USB-B cable for the NPC3 **or** a DE-9 RS-232 cable.
- [ ] Serial terminal on the PC: Arduino IDE Serial Monitor, PuTTY, or
      Tera Term. You need **two** ports if Teensy and NPC3 are both plugged in.
- [ ] Way into `MOD / MON`:
      - best: the Newport BNC-to-DB-25 adapter that shipped with the NPC3
      - else: **DB-25 male** solder-cup connector + hood + two bits of coax
        or three Dupont wires (MOD1, MOD2, GND)
- [ ] Way out of OUTA / OUTB: the gold SMA **if the holes match**, or a
      0.1" header and two short coax pigtails
- [ ] Soldering iron, flux, solder, helping hands, eye protection
- [ ] Optional ×4 scaler (op-amp that turns 0…2.5 V into 0…10 V) — only
      if you stay analog for Day 5
- [ ] Second PK2JA2P1 if you only have one box (you need two axes later)

You do **not** need the GUI, Gemini, or cameras this weekend.

---

## 6. How to use the DMM (do this once on a battery)

1. Turn the dial to **DC volts**. A V with a straight line, not a wavy AC line.
2. Black probe in **COM**. Red probe in **VΩ** (the voltage hole, not the
   10 A hole).
3. Touch the probes to a AA battery. You should see about 1.5 V.
4. Red on the more-positive thing, black on the less-positive thing.
   If the number is negative, you swapped the probes. That is fine — just
   read the sign.
5. On the DAC, black on DAC GND (or the Teensy GND rail), red on OUTA
   or OUTB.
6. On `MOD / MON` monitor pins, black on a MOD ground pin, red on MON.
7. On `PIEZO` pins (Day 4, stacks **off**), black on chassis or a pin you
   already proved is ground, red on the pin you are testing. Expect tens
   of volts. Use a 200 V DC range if the meter is not auto-ranging.

Write every reading in the lab log. A reading you did not write down did
not happen.

---

## 7. How D-sub pins are numbered (read twice)

A D-sub looks like a skinny D. The **wide** row is the top.

**Rule:** pin 1 is at the top, on the **left**, when you look at the
**male pins** (the pointy side) with the D hanging down (wide row on top).

The NPC3 `MOD / MON` is **female** (holes). When you look **into** the
holes on the back of the box, left and right are flipped:

```
Looking INTO the NPC3 MOD/MON (female, wide row on top):

 13 12 11 10  9  8  7  6  5  4  3  2  1
   25 24 23 22 21 20 19 18 17 16 15 14

Pin 1  = MOD channel 1     (top row, far RIGHT)
Pin 5  = MOD channel 2
Pin 2  = MON channel 1
Pin 6  = MON channel 2
Pin 14 = GND               (bottom row, far RIGHT)
Pin 18 = GND
```

The plug **you solder** is male. Looking at the solder cups on the
**back** of that plug (wires toward you, wide row on top) is the same
picture as looking into the female. Looking at the **pins** of that
plug (the face that goes into the NPC3) is the mirror:

```
Looking at the MALE plug face (pins toward you, wide row on top):

  1  2  3  4  5  6  7  8  9 10 11 12 13
   14 15 16 17 18 19 20 21 22 23 24 25
```

**Count twice. Buzz with the DMM continuity beep from solder cup to
pin face before you plug it in.** One swapped pin is a bad day.

`PIEZO` ports are **DA-15**, two rows, 8 on top + 7 on the bottom.
Same “pin 1 top-left on the male face” rule. The Rev A manual **does
not print** which of those 15 pins is HV+. You will find it with a
DMM on Day 4. Do not copy a random picture from the internet.

VGA / HD-15 is three rows of five. If your grey cable is that, it
will not mate. The photos looked like a normal 8+7 DA-15. Confirm
with your eyes: two rows, not three.

---

## Day 0 — Friday night (20 minutes, no power)

1. Print or open `docs/WEEKEND_LAB_LOG.md`. Put a pen next to the bench.
2. Clear drinks, bags, and dangling necklace/bracelet off the bench.
3. Confirm the PK2JA2P1 box is **closed** and not next to the NPC3
   cables. Put it on a different shelf if you are tempted.
4. Confirm Teensy SPI wires still match the table in §4. Do not
   rewire “to be tidy” tonight.
5. Find the 24 V brick, USB cables, and DMM. If the 24 V brick is
   missing, **stop.** Do not invent a supply. Buy or borrow 24 V / ≥2.5 A.
6. Read §2 and §3 again. Sleep.

---

## Day 1 — Saturday morning: prove the Teensy + DAC still work

**Goal:** OUTA = 1.00 V and OUTB = 2.00 V after `TEST`, same as August 26.
**Stacks:** in the box. **NPC3:** off, unplugged.

1. Plug the Teensy USB into the PC. Windows should make a COM port.
2. Device Manager → Ports (COM & LPT). Write the COM number in the log.
   Last time: COM5, serial `20022040`.
3. Open a serial terminal:
   - Baud **115200**
   - 8 data bits, no parity, 1 stop bit
   - Newline = NL (`\n`), not just CR
4. Reset the Teensy (button next to the microSD) or unplug/replug USB.
   You should see:

   ```
   READY 0.4.0
   ```

   If you see nothing: wrong COM, wrong baud, or the terminal opened
   after the 3-second wait. Hit reset again.

5. Type these lines, one at a time. Press Enter after each.
   Expected answers are on the right.

   | You type | It should say | Meaning |
   |----------|---------------|---------|
   | `PING` | `PONG 0.4.0` | Firmware is alive. |
   | `GET` | `STATUS 0 0 0` | Both channels parked at 0 mV. |
   | `TEST` | `OK TEST 1000 2000` | A=1.000 V, B=2.000 V. |
   | `GET` | `STATUS 1000 2000 0` | It remembers. |

6. DMM, DC volts:
   - Black on DAC GND (same net as Teensy GND).
   - Red on **OUTA** pads (the cluster labeled OUTA, even if unsoldered —
     touch the pad or the via). Expect **about 1.00 V**.
   - Red on **OUTB**. Expect **about 2.00 V**.
   - Write the real numbers. 0.98–1.02 V is fine. 0 V or 3.3 V is not.

7. Type `STOP`. Expect `OK STOP`. DMM on OUTA and OUTB should fall to
   **about 0.00 V**.

8. If TEST voltages are wrong, **stop.** Do not touch the NPC3. The SPI
   path is broken (wrong pin, loose jumper, DAC unpowered). Fix that
   first. The August wiring table is the known-good.

Day 1 pass = TEST voltages match and STOP returns to ~0 V.

---

## Day 2 — Saturday: wake the NPC3 with nothing connected

**Goal:** TFT lives, knobs move the displayed volts, no cables on
`PIEZO` or `MOD / MON`.
**Stacks:** in the box.

1. `NETZ` rocker to **O** (off).
2. Plug the 24 V brick into `UB` (the barrel jack). The brick should
   light if it has an LED. The NPC3 stays off until you flip `NETZ`.
3. Confirm **nothing** is in `PIEZO 1/2/3` or `MOD / MON`.
4. Flip `NETZ` to **I**.
5. Wait. The TFT should light. For ~10 seconds the amp may run its
   start-up. The display should say this is an **NPC3** (open loop),
   not NPC3SG. Write the firmware line if `ver` later shows one.
6. Turn **Axis1** a little. The number next to channel 1 / PIEZO 1
   should change. Turn it back toward **0**.
7. Same for Axis2. Leave Axis3 alone.
8. Park **all three knobs so the display reads as close to 0 V as
   you can get.** Write the three numbers. They will add to analog
   MOD later. Zero is the only safe knob position for Day 3–4.
9. Leave it on for five minutes. No fan-scream, no smell, no error
   banner. Then `NETZ` to **O** before you plug any data cable
   (the manual wants the amp off while you mate RS-232 / USB).

Day 2 pass = you saw a live TFT and you can zero the knobs.

If the screen is black: the last user may have typed `light,0`.
Day 3 will fix that with `light,200` after serial is up. Also check
the 24 V brick is actually 24 V on the DMM (barrel: outer = ground,
inner = +24 V on this unit — confirm with the brick’s own label
before you assume).

---

## Day 3 — Saturday: talk to the NPC3 and kill soft start

**Goal:** a `NPC3>` prompt, soft start **off**, knobs still at 0.
**Stacks:** in the box. **MOD / MON:** still empty.

1. `NETZ` = **O**. Plug USB-B (or RS-232) into the PC.
2. Windows → another COM port. Write it down. This is **not** the
   Teensy port.
3. Open a **second** terminal (leave the Teensy one closed for now):

   | Setting | Value |
   |---------|--------|
   | Baud | **19200** (not 115200) |
   | Data | 8 |
   | Parity | none |
   | Stop | 1 |
   | Flow control | **XON/XOFF** (software) |

4. `NETZ` = **I**. Wait for the TFT.
5. Click in the terminal. Press **Enter**. You should see:

   ```
   NPC3>
   ```

   If not: wrong baud, wrong flow control, or you used the Teensy
   COM. Try 19200 again. USB may need the driver from the Newport
   CD / website (`USB Driver Installer` on the NPC3 product page).

6. Type these. The commas are real. Use a **dot** for decimals, not
   a comma (`37.5` not `37,5`).

   | You type | What it does |
   |----------|----------------|
   | `ver` | Prints firmware version, date, serial. Copy the whole reply into the log. |
   | `s` | Lists commands. Proves the parser is happy. |
   | `fenable,0` | Reads soft-start flag for channel 0 (`PIEZO 1`). |
   | `fenable,1` | Same for channel 1 (`PIEZO 2`). |
   | `fenable,0,0` | **Turns soft start OFF** on channel 0. |
   | `fenable,1,0` | **Turns soft start OFF** on channel 1. |
   | `fenable,0` | Read it back. Must be off. |
   | `fenable,1` | Read it back. Must be off. |
   | `fready` | Read the “all channels” flag. If it says on, send `fready,0`. |
   | `ERR?` | Should be something like `ERROR,"OK. No error."` |
   | `light` | Read brightness 0…255. If the screen was dark, `light,200`. |

   Channel numbers start at **0**. `PIEZO 1` = 0, `PIEZO 2` = 1,
   `PIEZO 3` = 2.

7. **Do not** type `setk,0,1` this weekend unless you have chosen the
   digital path on Day 5. Remote **disables** analog MOD. For Days 3–4
   you want analog alive, so remote stays off.

8. `NETZ` = **O** before you unplug USB if you are done for the hour.
   Soft-start-off should survive a reboot (the manual says many
   settings are remembered). **Prove it:** power cycle, `fenable,0`
   again. If it came back on, turn it off every time you power up
   until a stack has been connected and you are sure it sticks.

Day 3 pass = you have a `ver` dump in the log and both `fenable`
reads say off after a power cycle.

---

## Day 4a — Saturday afternoon: analog takeoff on OUTA / OUTB

**Goal:** two real wires leaving OUTA and OUTB, still **not** plugged
into the NPC3.
**Stacks:** in the box. Iron is hot.

1. Unplug the Teensy USB. No power on the DAC while you solder.
2. Look at the OUTA cluster. Count the holes.

   - **5 holes** in a plus-sign / four-corners-plus-center → the gold
     SMA was made for this. Center pin = signal. Four short legs =
     ground / shield. Solder that.
   - **2×3 header** (six holes in two columns) → **do not** force the
     SMA. Solder a 0.1" header. One pin on the OUT copper, one pin
     on the GND copper. You will find which is which with the DMM
     **after** you power the Teensy again (Day 1 TEST: the pin that
     goes to 1.00 V is OUTA signal).
   - Unsure? Take a photo, do **not** solder, and stop for the day.

3. Same for OUTB.
4. After the joints cool: Teensy USB in, `TEST`, DMM from each new
   connector’s **center / signal** to GND. Still ~1.00 V and ~2.00 V?
   If a voltage died, you bridged signal to ground. Unsolder and fix.
   Type `STOP` when you are done so the DAC sits at 0 V.

5. Build or find the `MOD / MON` cable:

   | Wire | DB-25 male pin (solder cup, see §7) | Other end |
   |------|-------------------------------------|-----------|
   | OUTA signal | **1** | SMA center or header signal A |
   | OUTB signal | **5** | SMA center or header signal B |
   | GND | **14** (also jumper 14 to 18 if you want both grounds) | SMA shields / DAC GND |

   Optional extra pair for a DMM, not required to run:

   | MON 1 | pin **2** | DMM red when you want a 0…10 V copy of channel 1 |
   | MON 2 | pin **6** | same for channel 2 |
   | GND   | pin **15** | DMM black |

6. Continuity-beep **every** pin. Pin 1 on the plug face really is
   the OUTA wire. Pin 5 really is OUTB. No shorts from 1 to 5, or
   from 1 to any ground.

7. Do **not** plug this cable into `PIEZO 1`. `PIEZO` is the high-
   voltage mouth. `MOD / MON` is the ear. Wrong port = you just
   fed 0…2.5 V into a 130 V output (or worse). Look at the label
   on the metal: **MOD / MON**.

Day 4a pass = TEST still reads 1.00 / 2.00 V on the new connectors,
and the DB-25 is buzzed out.

---

## Day 4b — Saturday afternoon: DAC → MOD, still no stacks

**Goal:** prove the formula on the TFT and a DMM.
**Stacks:** in the box. Knobs at 0. Soft start off.

1. Teensy USB in. Serial 115200. Type `STOP` so DAC is 0 V.
2. NPC3 `NETZ` = **O**. Plug the DB-25 into **`MOD / MON` only**.
   Thumb-screws snug, not gorilla-tight.
3. `NETZ` = **I**. Wait. Knobs still ~0.
4. Because DAC is at 0 V, the formula says the TFT should show
   about **−20 V** on Axis1 and Axis2. Write what it actually says.

   - If you see ~0 V: the MOD pins are not getting to the amp
     (wrong pins, remote is on, or this unit ignores analog until
     something is enabled). Check `setk` was never turned on.
     Recheck pin 1 / 5 / 14.
   - If you see ~−20 V: **the analog ear is alive.** This is the
     expected “park is poisonous” result. Do **not** connect a
     stack. You are succeeding.

5. Teensy terminal:

   ```
   SET 0 1000
   ```

   That is 1.000 V on OUTA. Formula: −20 + 15×1.0 = **−5 V** on
   `PIEZO 1`. TFT Axis1 should move toward −5 V. Axis2 should
   stay near −20 V (OUTB is still 0).

6. ```
   SET 1 2000
   ```

   OUTB = 2.000 V → Axis2 toward −20 + 30 = **+10 V**.

7. DMM on MON pin 2 vs GND. The manual says MON 0…10 V copies
   the actuator voltage −20…+130 V. So:

   ```
   V_mon ≈ (V_piezo + 20) / 15
   ```

   At −5 V piezo, MON ≈ 1.00 V. At +10 V piezo, MON ≈ 2.00 V.
   Write TFT, DMM on OUTA/OUTB, and DMM on MON. They should
   tell the same story.

8. ```
   SET 0 0
   SET 1 0
   ```

   or `STOP`. TFT should go back toward −20 V / −20 V.

9. Fill this table in the lab log (no scaler):

   | Command | DAC DMM | TFT piezo V | Expected piezo V | MON DMM | Expected MON |
   |---------|---------|-------------|------------------|---------|--------------|
   | `STOP` | 0 / 0 | | −20 / −20 | | 0 / 0 |
   | `SET 0 1000` | ~1.00 / 0 | | −5 / −20 | | ~1.00 / 0 |
   | `TEST` | ~1.00 / 2.00 | | −5 / +10 | | ~1.00 / 2.00 |

   If the TFT tracks the formula within a volt, Day 4b passes.
   You have proven the ear. You have also proven that **park is
   −20 V.** That is why the stack is still in the box.

10. `STOP` on the Teensy. `NETZ` = **O**. Unplug `MOD / MON` if
    you are leaving the bench. Do not leave −20 V sitting on the
    ports overnight “just in case.”

---

## Day 4c — Saturday: find HV+ on `PIEZO 1` and `PIEZO 2`

**Goal:** write down which DA-15 pin is the loud one.
**Stacks:** in the box. This is the last thing you do Saturday.

1. `NETZ` = **O**. `MOD / MON` unplugged. Nothing in `PIEZO`.
2. Knobs will be your only command. That is what you want.
3. `NETZ` = **I**. Soft start still off? Check `fenable,0`.
4. Set Axis1 knob to a **small, known** voltage the TFT agrees
   with — for example **10 V**. Not 100 V. You are hunting a pin,
   not exercising the amp.
5. DMM, DC volts, 200 V range. Black probe on the NPC3 chassis
   screw or the metal hood of the `PIEZO 1` shell (that is
   usually ground — confirm it reads ~0 V vs the `UB` barrel
   outer).
6. Red probe, **one pin at a time**, into `PIEZO 1` sockets.
   Most pins will be ~0 V or a sensor supply. **One pin** should
   jump to about the same number as the TFT (≈10 V). That pin
   is HV+.
7. Turn Axis1 back to 0. That pin should fall toward 0 V.
   Turn it to 10 V again. Same pin rises. Write:

   ```
   PIEZO 1 HV+ = pin ____
   PIEZO 1 GND = pin ____   (the pin that stays 0 V and
                            beeps to chassis, if any)
   ```

   If no pin is a hard ground, the return may be the shell.
   Write that down too.

8. Axis1 back to 0. Repeat for `PIEZO 2` / Axis2.
9. Axis1 and Axis2 back to **0**. `NETZ` = **O**.
10. Put those pin numbers in `docs/WEEKEND_LAB_LOG.md` **and**
    in a commit if you are at a PC with git. Future-you will
    not remember.

Day 4c pass = two pin numbers on paper, found by a DMM, not by
a website.

**Do not** solder the grey Belden cable to a stack tonight.
Continuity the free end of that cable if you want (which color
goes to which pin) and write it down. That is enough.

---

## Day 5 — Sunday: pick a path, then (maybe) a stack

You are not allowed to touch a stack until **one** of these is true.

### Path A — stay analog (needs a ×4)

You add a circuit whose output is `4 × V_dac`, 0…10 V, and feed
**that** into MOD 1 / MOD 2.

Then the safe DAC commands become:

| Want on stack | Type on Teensy |
|---------------|----------------|
| 0 V park | `SET 0 333` and `SET 1 333` |
| 37.5 V mid-bias | `SET 0 958` and `SET 1 958` |
| 75 V full | `SET 0 1583` and `SET 1 1583` |
| never | `SET 0 0` (that is −20 V again) |
| never | `SET 0 2500` (that is 130 V) |

Firmware today still boots to 0 V DAC. **Do not plug a stack into
an NPC3 that is listening to a Teensy that just rebooted.** Either
change park in firmware first (not done in this repo yet) or keep
the Teensy unplugged / `STOP` unused and command only through
values ≥ 333 mV after the scaler.

Prove Path A **without** a stack: scaler output DMM = 4× DAC,
TFT = −20 + 15 × scaler. Then, and only then, Path A is allowed
to go to §Day 5 common.

### Path B — go digital (no scaler, recommended if you do not
have an op-amp on Sunday)

1. `MOD / MON` can stay unplugged.
2. Terminal at 19200. Soft start still off. Knobs ignored once
   remote is on.
3. ```
   setk,0,1
   setk,1,1
   set,0,10
   set,1,10
   rk,0
   rk,1
   ```
   `set,0,10` means **10 volts on the stack**, not 10 mV.
   `rk,0` should come back near 10 V.
4. Walk 10 → 20 → 37.5. Never above 75. Never below 0.
   ```
   set,0,0
   set,1,0
   ```
   is a **safe** park on the digital path (0 V, not −20 V).
5. To give analog back later: `setk,0,0` and `setk,1,0`.
   The manual says turning remote off can dump the actuator
   toward its minimum. Do that with **no stack** attached
   the first time, and watch the TFT.

Path B pass (no stack) = `rk` agrees with `set` at 0, 10, 37.5.

### Day 5 common — first time a stack is allowed

Only after Path A **or** Path B passed with **no** stack:

1. `NETZ` = **O**.
2. PK2JA2P1: red = +, black = ground. Short the two leads together
   for a second before you wire them (piezos store charge). Then
   un-short.
3. Solder or crimp **one** stack to `PIEZO 1` using the pin numbers
   from Day 4c. Red → HV+, black → GND/shell. No extra pins.
4. Strain-relieve the wires. The ceramic hates being yanked.
5. `NETZ` = **I**. Soft start off. Command **10 V** only
   (digital `set,0,10` or analog equivalent that the TFT shows
   as +10 V, not −20 V).
6. The stack is 3 mm × 3 mm × 10 mm. You will not see 1 µm with
   your eye. Trust the TFT / `rk` and a current-limited DMM
   across the stack leads (expect ~10 V). If the voltage on the
   stack leads does not match the TFT, `NETZ` = **O** and stop.
7. If 10 V is happy, 20 V, then 37.5 V. Stop there for the
   weekend. Do **not** go to 75 V on the first day the ceramic
   has ever seen this amp.
8. Park at 0 V (digital) or the scaler’s 0 V-stack code (analog).
   `NETZ` = **O** before you unplug anything.

A second stack on `PIEZO 2` is the same recipe, another day.

---

## 8. Teensy command crib (115200)

| Type | Reply | What it does |
|------|-------|----------------|
| `PING` | `PONG 0.4.0` | Heartbeat. |
| `GET` | `STATUS <mV0> <mV1> <flag>` | Last SET values. flag 1 = last SET was clamped. |
| `SET 0 1000` | `OK 0 1000` | OUTA = 1000 mV. Axis 0 only. |
| `SET 1 2000` | `OK 1 2000` | OUTB = 2000 mV. |
| `TEST` or `INIT` | `OK TEST 1000 2000` | A=1 V, B=2 V. |
| `STOP` | `OK STOP` | Both 0 V DAC. |
| `CLR` | `OK CLR` | Same as STOP today. |

Illegal axis → `ERR axis`. Unknown word → `ERR unknown`.

---

## 9. NPC3 command crib (19200, XON/XOFF)

| Type | What it does |
|------|----------------|
| (Enter) | Shows `NPC3>` |
| `ver` | Version, date, serial |
| `s` | Help |
| `fenable,0,0` | Soft start off, channel 0 |
| `fenable,1,0` | Soft start off, channel 1 |
| `fready,0` | Soft start off, all channels |
| `setk,0,1` | Remote **on** (kills analog + knobs) |
| `setk,0,0` | Remote off |
| `set,0,37.5` | Channel 0 to **37.5 V** (open loop) |
| `setall,0,0,0` | All three channels to 0 V (needs remote on) |
| `rk,0` | Read channel 0 volts |
| `measure` | Read all three |
| `ERR?` | Last error, then clears it |
| `light,200` | Brightness |

There is no closed-loop on this unit. `cloop` is an SG command.
Ignore it.

---

## 10. What the software does **not** do yet

Do not expect the Interferometer GUI to move this hardware.

- `SerialPiezoDriver` is a stub. It raises `NotImplementedError`.
- Firmware park / STOP / CLR are still **0 V DAC**.
- Nobody clamps SET to 75 V stack-equivalent.
- Nobody talks to the NPC3 from Python.

The GUI’s Simulation #2 is fake physics. It is safe to click. It
will not save you if you wire a stack on Saturday.

After the weekend, the next code work is either:

- analog: change firmware park to the 0 V-stack code and teach
  `SerialPiezoDriver` to use `core.hardware.npc3_map`, or
- digital: a new `Npc3PiezoDriver` that sends `setk` / `set` / `rk`.

---

## 11. If something is wrong

| You see | Likely | Do |
|---------|--------|-----|
| Teensy silent | Wrong COM or baud 19200 by mistake | 115200, hit reset |
| `TEST` but OUTA stays 0 V | SPI wires or DAC VCC | Recheck §4 table, 3.3 V not 5 V |
| NPC3 no `NPC3>` | Wrong COM, 115200, or no USB driver | 19200 + XON/XOFF |
| TFT black | `light,0` | `light,200` |
| TFT `not connected` | Empty `PIEZO` or homemade 2-wire cable | Normal with no stack. Believe the DMM on the port. |
| TFT UDL / OVL | Knob + MOD sum outside 0…10 V MOD | Knobs to 0, DAC to a mid value, or unplug MOD |
| TFT −20 V with DAC at 0 | Analog is working | Do not connect a stack |
| TFT 0 V with DAC at 0 and MOD plugged | Analog not reaching the chip | Pins, remote, cable |
| Smell / heat | Stop | `NETZ` O, unplug `UB` |
| Grey cable is 3-row VGA | Wrong connector | Do not force it into `PIEZO` |

---

## 12. End-of-weekend shutdown

1. Teensy: `STOP`. Unplug USB.
2. NPC3: knobs toward 0, `NETZ` = **O**, unplug `UB`.
3. Unplug `MOD / MON` and any `PIEZO` cable.
4. Short the stack leads together if you ever attached one, then
   bag it.
5. Fill the leftover blanks in `docs/WEEKEND_LAB_LOG.md`.
6. If you found HV pin numbers, commit them. Future-you is a
   stranger.

That is the whole weekend. Days 1–4c are the win. A stack on
Sunday is extra credit, not the assignment.
