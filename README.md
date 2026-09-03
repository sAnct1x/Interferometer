# Interferometer Automation

Production GUI for live Thorcam beam analysis, stage control, and Atria-assisted alignment.

Original Thorlabs drivers and λ-scan helpers live in `legacy/` and are still used at runtime via `core/hardware_bridge.py`. Beam math and export live under `core/analytics/`.

## Setup

```powershell
cd "C:\Users\origi\OneDrive\Desktop\College\OSU\2026\Summer 26\interferometer_automation"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env: GEMINI_API_KEY powers Atria (backend only; not shown in the UI)
python scripts\generate_icon.py
```

Close ThorCam GUI before launching. Thorlabs drivers must match the bench install (`python legacy\check_thorlabs_env.py`).

## Run

```powershell
python main.py
```

## Desktop shortcut (Windows)

```powershell
.\scripts\create_desktop_shortcut.ps1
```

## Features

- **Full-color** live camera (on-device Bayer→RGB debayering for the CS165CU); beam
  measurements are always computed on a derived intensity image, so color output never
  changes the physics
- High-frame-rate acquisition that blocks on the camera's frame event (full sensor FPS,
  near-zero idle CPU)
- **Resource-aware tiles**: a closed/minimized Bench Cameras tile pauses acquisition and
  the whole live pipeline; each analysis (beam plots, efficiency, trends, FFT) only runs
  while its tile is on screen, and everything auto-resumes when reopened
- Live camera with **beam waist** and **fringe** ROI modes (selectable)
- Real-time 1/e² analysis (`core/analytics/beam.py`) with labeled PNG/CSV packages under `outputs/beam/`
- 3D beam surface + X/Y profiles + waist trend
- Stage jog, editable limits, **safe home** on crash recovery
- Wavelength: nominal 520 nm, last scan CSV, or live placeholder
- Camera-only coupling efficiency proxy
- **Atria** natural-language assistant with **hardware permission** toggle
- Dockable octagonal glass panels: drag, float, snap; layout saved in `user_config/`

## Wedge fiber-coupling bench (520 nm)

See [`docs/Beam Diagram.png`](docs/Beam%20Diagram.png) for the physical beam path.

The physical bench is a 520 nm fiber-coupling setup with a wedge that splits the
beam into three diagnostic paths. The **Bench Cameras** tile shows all three by
**role** (see `core/camera_roles.py`) as one large primary feed plus thumbnails.
Click a thumbnail's `▣ view` to promote it, or `⤢ pop out` to tear a camera into
its own draggable/resizable tile (the home tile reflows; `⤡ pop in` or close the
tile to snap it back):

- **Far Field**: ghost reflected off the wedge; carries the coupling reticle
  (450 µm fiber bore) and the centroid the PID drives to zero.
- **Image**: second ghost (Ghost 2); imaging plane / d_i pending mentor optics
  (`docs/MENTOR_QUESTIONS.md`), shown as a labelled stub.
- **Output**: after the fiber; transmitted power for coupling efficiency η
  (η is computed Far Field → Output).

Alignment uses two **PK2JA2P1** piezo stacks (tip/tilt) on a Newport
**U100-A** mount at Mirror 5, driven by a **PID** loop on centroid error (not
open-loop hill climbing). The HV amp on the bench is a Newport **NPC3**
(S/N E-707744); Teensy + DAC8562 are wired, stacks are not. Constants live in
`config.py`; hookup and the 2.5 V vs 10 V analog gap are in
`docs/NPC3_DAC_HOOKUP.md` and `docs/BENCH_CONSTANTS.md`. The GUI still runs in
simulation behind the `PiezoDriver` interface (`core/hardware/piezo_driver.py`).

## Simulation #1 vs Simulation #2

| | Simulation #1 | Simulation #2 |
|--|---------------|----------------|
| Launch | Tools → Run Simulation / Atria `run simulation` | Tools → **Run Simulation #2: Piezo Closed Loop** |
| Cameras | 1 synthetic feed (Far Field) | 3 synthetic feeds (Far Field / Image / Output) |
| Physics | Gaussian + fringe ROI (analytics smoke test) | Wedge bench, 500 mm arms, PK2JA2P1 tip/tilt, drift + creep |
| Piezo | none | simulated stacks + PID closed loop |
| Purpose | tile / analytics smoke test | watch the loop align and hold η in real time |

Simulation #1 is unchanged. Simulation #2 is **folded into the main hub** (no
separate window): it feeds the three Bench Cameras tiles and shares one
`ClosedLoopSimulation` with the **Piezo Alignment** tile. Running it auto-connects
and arms the loop; watch η climb into the fiber reticle while thermal drift and
piezo creep force the controller to keep correcting. Error source is selectable in
the Piezo tile (Centroid PID / Efficiency η extremum-seeking / Weighted). Opening
the Piezo tile on its own also runs the loop so you can jog/tune manually. Stop via
Tools → Stop Simulation #2.

## Config

| File | Purpose |
|------|---------|
| `.env` | API key for Atria backend (gitignored) |
| `user_config/app_config.json` | ROIs, stage limits, safe home, wavelength mode |
| `user_config/tile_layout.json` | Hub tile positions and visibility |
| `legacy/interferometer_acquire_analyze.py` | Canonical Thorcam/K-Cube + scan script (runtime) |

## Legacy

`legacy/` holds `interferometer_acquire_analyze.py` (used by the GUI for camera, stage, and λ scans) plus standalone CLI beam tools. The sibling `Interferometer Project/` folder is only used to seed first-run ROI JSON.

**Secondary / not in the current primary workflow** (kept fully reachable, nothing removed): the fringe ROI + wavelength (λ) scan features and the K-Cube stage control. This bench uses a pre-measured 520 nm wavelength and piezo tip/tilt for alignment, so those tools are deprioritized in day-to-day use but remain available (fringe ROI mode in the Bench Cameras tile, Stage Control tile, and the λ-scan machinery in `legacy/`) if the bench returns to interferometric measurement.
