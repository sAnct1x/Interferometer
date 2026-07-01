# Interferometer Automation

Production GUI for live Thorcam beam analysis, stage control, and Atria-assisted alignment.

Original scripts remain in `Summer 26/` and `Interferometer Project/` as fallbacks. This app **copies** logic into modular modules under `core/`.

## Setup

```powershell
cd "C:\Users\origi\OneDrive\Desktop\College\OSU\2026\Summer 26\interferometer_automation"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env — GEMINI_API_KEY powers Atria (backend only; not shown in the UI)
python scripts\generate_icon.py
```

Close ThorCam GUI before launching. Thorlabs drivers must match the legacy project (`python legacy\check_thorlabs_env.py`).

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
- **Resource-aware tiles**: a closed/minimized Live Camera tile pauses acquisition and
  the whole live pipeline; each analysis (beam plots, efficiency, trends, FFT) only runs
  while its tile is on screen, and everything auto-resumes when reopened
- Live camera with **beam waist** and **fringe** ROI modes (selectable)
- Real-time 1/e² analysis (same math as `beam_size_analysis.py`)
- 3D beam surface + X/Y profiles + waist trend
- Stage jog, editable limits, **safe home** on crash recovery
- Wavelength: nominal 520 nm, last scan CSV, or live placeholder
- Camera-only coupling efficiency proxy
- **Atria** natural-language assistant with **hardware permission** toggle
- Dockable octagonal glass panels — drag, float, snap; layout saved in `user_config/`

## Config

| File | Purpose |
|------|---------|
| `.env` | API key for Atria backend (gitignored) |
| `user_config/app_config.json` | ROIs, stage limits, safe home, wavelength mode |
| `user_config/tile_layout.json` | Hub tile positions and visibility |
| `legacy/interferometer_acquire_analyze.py` | Canonical Thorcam/K-Cube + scan script (runtime) |

## Legacy

`legacy/` holds `interferometer_acquire_analyze.py` (used by the GUI for camera, stage, and λ scans) plus standalone CLI beam tools. The sibling `Interferometer Project/` folder is only used to seed first-run ROI JSON.
