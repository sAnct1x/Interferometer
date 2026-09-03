# Questions for mentor: bench optics & cameras

Bring this list tomorrow. Skip anything you've already settled in lab notes.

---

## Image camera (Ghost 2)

1. For the Image camera on the second ghost beam, which plane are we actually trying to image? The beam waist at the fiber, the wedge face, Mirror 5, or something else?

2. What's the total path length along Ghost 2, from the wedge (or wherever that ghost originates) to the Image camera sensor?

3. Along that ghost path, which element should we treat as the "lens" when we apply the thin-lens equation (1/f = 1/d_o + 1/d_i)? Is it one of the curved mirrors, an effective focal length for the whole path, or something local to the wedge fold?

4. Is the Image camera a one-time placement problem (we compute d_i once, mount it, and leave it), or do we need a live focus-quality metric in software that updates while we're aligning?

---

## Far Field vs fiber paths (confirming our notes)

5. We have written down that both routes are **500 mm total from Mirror 3**:
   - Mirror 3 → flat → flat → wedge → **reflect** → Far Field camera = **500 mm**
   - Mirror 3 → flat → flat → wedge → **transmit** → fiber entrance = **500 mm**  
   Does that match your layout? Any segment lengths worth writing down separately (e.g. Mirror 3 → first flat only)?

6. At the Far Field camera plane, should we expect the same beam waist (280–300 µm) as at the fiber entrance, or a different size because it's a different sample of the ghost beam? If different, is there a known ratio or do we calibrate empirically?

---

## Efficiency & calibration

7. How should we define coupling efficiency η in software?
   - Far Field power vs Output power (after fiber)?
   - Something else as the input reference?
   - Include the Image camera in the formula at all, or is it alignment-only?

8. When we "Set η = 100%", what physical condition defines that: best alignment you've achieved manually, a known good coupling measurement, or a lab standard?

9. Do we need to bake in wedge split ratios and ghost-beam ND losses as constants, or is a single calibration at good alignment enough?

---

## Alignment & control

10. Which camera should the closed-loop controller use as primary feedback: Far Field centroid, Output centroid, η from Far Field + Output, or some combination?

11. Which mirror is on the piezo stack (PK2JA2P1)? Mirror 4, Mirror 5, or another?

12. Are we still using the K-Cube linear stage for anything on this bench, or is alignment entirely piezo tilt now?

13. From the amplifier options in the report (KPZ101, Apex PA94, PDL200), which one are we actually building with? That affects voltage range, channels, and how the GUI should talk to hardware.
    **Answered (bench, 2026-09-03):** Newport **NPC3** S/N **E-707744** (open-loop, −20…+130 V, 3 ch). Analog MOD is 0…10 V; DAC8562 is still 0…2.5 V. See `docs/NPC3_DAC_HOOKUP.md`.

14. Is there existing Teensy firmware and a serial command format, or does that need to be defined from scratch?

15. What are safe voltage limits and step sizes for the PK2JA2P1 in normal operation? What should the software do on fault (clamp, park, disable)?

---

## Hardware inventory

16. How many Thorcam units are on the bench at once: three dedicated cameras (Far Field, Image, Output), or fewer sensors swapped between roles?

17. Do you have serial numbers or fixed USB slots assigned to each camera role?
    **Answered:** Far Field `36158`, Image `38173`, Output `36143`
    (see `CAMERA_ROLE_SERIALS` in `config.py`).

18. Is the interferometer / fringe ROI / wavelength-scan workflow still part of this bench, or is this setup purely fiber coupling and we can drop fringe-first UI?

---

## Simulation & testing without hardware

19. For offline testing, is it enough if Simulation #2 fakes the three camera feeds and piezo responses, or do you want it tied to real serial hardware when the Teensy is plugged in?

20. What would you consider a successful demo of automated alignment: hold η above X% for Y seconds, hit a centroid tolerance, something else?
