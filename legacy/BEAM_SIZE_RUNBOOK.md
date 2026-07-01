# Beam Size Measurement

We use a Thorcam to take a picture of the **green laser diode** spot (520 nm), draw a small box around the **bright center only**, and calculate how wide that spot is. The number we care about most is the **1/e² diameter** in micrometers (µm). Our target is about **280–300 µm**.

---

## Step-by-step (do this every time)

Open PowerShell and go to the project folder:

```powershell
cd "C:\Users\origi\OneDrive\Desktop\College\OSU\2026\Summer 26"
```

### Step 0 — Before you start

1. Laser on, spot visible on the camera.
2. **Close the ThorCam app** (Python cannot share the camera with the GUI).
3. Keep exposure low enough that the bright center is **not a flat white blob** (not saturated).

### Step 1 — Take a picture

```powershell
python capture_beam_frame.py
```

A new file appears in `data\`, named like `run_003_20260611_165015_beam.tiff`.

### Step 2 — Draw the box (ROI)

```powershell
python save_beam_roi.py --live
```

In the window that opens:

1. Drag the **green box** so it sits on the **bright center** of the spot.
2. Use the **yellow handles** to resize.
3. The box should include **only the bright core**, not the dim rings (fringes) outside it.
4. Leave a little **dark space** on all four sides inside the box.
5. Click **Confirm ROI** or press **Enter**.

This saves `beam_roi_config.json`.

### Step 3 — Measure the beam

```powershell
python beam_size_analysis.py
```

Read the numbers in the terminal. Open `beam_size_outputs\LATEST.txt` or the plot at `beam_size_outputs\latest\beam_analysis.png`.

### Step 4 — Check that it looks right

| Good | Bad |
|------|-----|
| 1/e² average near **280–300 µm** | Stuck near **~361 µm** no matter what you move |
| X and Y close to each other (within ~15 µm) | X ≈ 300 but Y ≈ 400 |
| Box on bright core, fringes outside | Box includes the first fringe ring |

If it looks wrong, redraw the ROI (Step 2) on the same picture — you do not need a new capture unless the beam moved on the sensor.

```powershell
python save_beam_roi.py --from-tiff (Get-ChildItem data\run_*_beam.tiff | Sort-Object Name | Select-Object -Last 1).FullName
python beam_size_analysis.py
```

When you have a run you want to keep:

```powershell
python beam_size_analysis.py --mark-best
```

---

## What we are actually measuring

The camera sees the laser as a bright dot, often with faint rings around it (from the interferometer). We want the size of the **bright waist** — the main hot spot — **not** the rings.

The scripts:

1. Crop to your box (ROI).
2. Subtract background from the dark edges of that crop.
3. Add up pixel brightness along X and Y to make two graphs (profiles).
4. Find where each graph crosses the **1/e²** level (about 13.5% of the peak height).
5. Convert pixels to µm using **3.45 µm per pixel** (Thorcam CS165CU).

If the box is too big and includes rings or halo, the profile never drops to real background before the edge of the box. The code then reports the **size of the box**, not the beam. That is the common **~361 µm** mistake (~105 pixels × 3.45 µm/px).

---

## Files and folders

| Path | What it is |
|------|------------|
| `capture_beam_frame.py` | Grabs one frame from the camera |
| `save_beam_roi.py` | Draws and saves the ROI box |
| `beam_size_analysis.py` | Computes FWHM and 1/e², saves plots |
| `beam_roi.py` | ROI helpers (used by the scripts above) |
| `beam_naming.py` | Run IDs and output folder names |
| `data\` | Raw TIFF captures |
| `beam_roi_config.json` | Your saved ROI |
| `beam_size_outputs\LATEST.txt` | Quick summary of the last run |
| `beam_size_outputs\latest\beam_analysis.png` | Last plot |
| `beam_size_outputs\runs\run_NNN_...\` | One folder per measurement |

---

## Python packages you need

Install once:

```powershell
pip install -r requirements-beam.txt
```

The camera also needs **pylablib** and the Thorlabs ThorCam software (same setup as the interferometer project). From the repo root:

```powershell
cd "Interferometer Project"
python check_thorlabs_env.py
```

---

## Extra commands (optional)

```powershell
# Analyze every capture in data\, not just the latest
python beam_size_analysis.py --all

# Analyze one specific file
python beam_size_analysis.py --capture "run_002_20260611_165015_beam.tiff"

# Auto-guess a starting box (then refine with --live or --from-tiff)
python save_beam_roi.py --suggest-from-tiff "data\run_001_....tiff" --threshold 0.92
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No Thorcam found` | Close ThorCam app, check USB, run `check_thorlabs_env.py` |
| Always ~361 µm | ROI too big or includes fringes — shrink box to bright core only |
| X and Y very different | Recenter ROI |
| `No ROI file found` | Run Step 2 before Step 3 |
| ROI window errors | Make sure matplotlib can open a window; confirm with Enter when done |

---

## Settings

- **Laser:** green diode, **520 nm** (nominal; check the diode label if you need the exact value).
- **Pixel size:** 3.45 µm (CS165CU). Set in `beam_size_analysis.py` as `PIXEL_SIZE_UM`.
- **Target:** ~280–300 µm at 1/e² average.
- **Rayleigh range:** For a 300 µm diameter spot and 520 nm light, the waist changes slowly within about **14 cm** of focus. If the size never changes when you move hardware but stays at ~361 µm, that is the ROI artifact, not Rayleigh physics.
