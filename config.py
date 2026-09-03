"""Shared paths, hardware defaults, and environment config."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
SUMMER_26_DIR = APP_DIR.parent
LEGACY_SCRIPTS_DIR = APP_DIR / "legacy"
# First-run config seed only (ROI JSON beside the old interferometer project).
LEGACY_INTERFEROMETER_DIR = SUMMER_26_DIR / "Interferometer Project"
USER_CONFIG_DIR = APP_DIR / "user_config"
ASSETS_DIR = APP_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
DATA_DIR = APP_DIR / "data"
OUTPUT_DIR = APP_DIR / "outputs"

load_dotenv(APP_DIR / ".env")

# Thorcam CS165CU
PIXEL_SIZE_UM = 3.45
SENSOR_SIZE_PX = (1440, 1080)
DEFAULT_CAMERA_SERIAL: str | None = os.getenv("CAMERA_SERIAL") or None

# Fixed bench assignments (Thorlabs CS165CU serial numbers).
# Camera 1 → Far Field, Camera 2 → Image (Ghost 2), Camera 3 → Output (η).
CAMERA_SERIAL_FAR_FIELD = "36158"
CAMERA_SERIAL_IMAGE = "38173"
CAMERA_SERIAL_OUTPUT = "36143"
CAMERA_ROLE_SERIALS: dict[str, str] = {
    "far_field": CAMERA_SERIAL_FAR_FIELD,
    "image": CAMERA_SERIAL_IMAGE,
    "output": CAMERA_SERIAL_OUTPUT,
}

# Green laser diode (nominal)
LASER_WAVELENGTH_NM = 520.0

# Beam size target (1/e² average, µm). This is the waist we want at the fiber face,
# roughly two-thirds of the fiber bore so the mode fits with margin.
BEAM_WAIST_TARGET_UM = (280.0, 300.0)
# Hollow-core fiber inner diameter (bore) for the coupling reticle. This is the
# physical hole the beam must land inside, NOT the waist target above.
FIBER_TARGET_ID_UM = 450.0

# Lab goal for Far Field → Output coupling once aligned (not a forced readout).
# The meter marks this as the target; live η auto-baselines on Start Live Feed.
COUPLING_TARGET_PCT = 90.0

# --- Wedge fiber-coupling bench geometry (520 nm) ---------------------------
# Two 500 mm arms leave the f=500 mm curved mirror (Mirror 3), fold across the
# flat silver mirrors (Mirrors 4 & 5), and hit the wedge near the fiber:
#   reflect  -> Far Field camera
#   transmit -> fiber entrance
PATH_M3_TO_FARFIELD_MM = 500.0
PATH_M3_TO_FIBER_MM = 500.0
# Curved mirror focal lengths in beam order (for the optional optics helper).
CURVED_MIRROR_FOCAL_MM = (250.0, 100.0, 500.0)

# --- Piezo actuator (Thorlabs PK2JA2P1, simulated until hardware arrives) -----
# Two single-axis PK2JA2P1 stacks replace two adjuster screws of a Newport
# U100-A ULTIMA mount on Mirror 5, giving tip (theta_x) and tilt (theta_y).
# Spec (Piezo Stack Report): 0.106 µm/V, 8 µm total travel at 75 V (+/-15%).
# A DC bias holds the stack at +4 µm (mid-range) so it can push -4..+4 µm about
# that baseline in either direction while staying in compression. The stack has
# hysteresis, so alignment uses a PID loop on error, not open-loop stepping.
PIEZO_MIRROR = "M5"
PIEZO_MAX_V = 75.0
PIEZO_TRAVEL_UM = 8.0                 # full stroke, 0..8 µm over 0..75 V
PIEZO_BASELINE_UM = 4.0              # DC bias operating point (mid-range)
PIEZO_EXPANSION_UM_PER_V = 0.106    # datasheet expansion rate
PIEZO_PIVOT_ARM_MM = 15.0           # actuator-to-pivot distance on the U100-A mount
PIEZO_STACK_MODEL = "PK2JA2P1"
MIRROR_MOUNT_MODEL = "Newport U100-A"
# HV amp on the bench: Newport NPC3 open-loop, S/N E-707744 (loaner, UCF).
# Analog MOD is 0..10 V; open-loop map is V_piezo = -20 + 15*V_mod.
# DAC8562 is still 0..2.5 V — see docs/NPC3_DAC_HOOKUP.md and npc3_map.py.
PIEZO_AMP_MODEL = "Newport NPC3"
PIEZO_AMP_SERIAL = "E-707744"
NPC3_V_MIN = -20.0
NPC3_V_MAX = 130.0
NPC3_MOD_FS = 10.0
DAC_FS_V = 2.5

# Camera: Thorlabs CS165CU (Zelux 1.6 MP color CMOS). 10-bit ADC, global
# shutter, ~34.8 fps full frame. Read noise < 4 e-. Used to make the simulated
# feeds match what the real sensor would produce.
CAMERA_MODEL = "Thorlabs CS165CU"
CAMERA_ADC_BITS = 10
CAMERA_MAX_FPS = 34.8
CAMERA_READ_NOISE_E = 4.0

# Atria backend (Gemini API key lives in .env only)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

_DEPRECATED_GEMINI_MODELS: dict[str, str] = {
    "gemini-2.0-flash": "gemini-2.5-flash",
    "models/gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-001": "gemini-2.5-flash",
}

_raw_gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_MODEL = _DEPRECATED_GEMINI_MODELS.get(_raw_gemini_model, _raw_gemini_model)

# App branding (full name in UI; compact badge only where space is tight)
APP_TITLE = "Interferometer Automation"
APP_BADGE = "IA"

# Camera streaming
# Acquisition blocks on the camera's new-frame event for up to CAMERA_FRAME_WAIT_S,
# giving the full sensor frame rate without busy-polling the CPU. CAMERA_POLL_MS is a
# short fallback sleep only used on drivers that do not expose a frame-wait call.
CAMERA_POLL_MS = 5
CAMERA_FRAME_WAIT_S = 0.2
CAMERA_SETTLE_S = 0.45
# Longer wait while hunting for the first frame after connect (USB contention).
CAMERA_BOOTSTRAP_FRAME_WAIT_S = 1.0
# If a camera connects and starts acquisition but delivers no frames within this
# window, the worker warns the UI so a dark/mis-exposed sensor is not mistaken for
# a connection hang (a tile stuck on "Connecting to <serial>…").
CAMERA_NO_FRAME_WARN_S = 4.0
# Cap how often each worker pushes frames into the Qt GUI queue. Three CS165CUs at
# ~35 fps × full RGB will otherwise flood the main thread (~100+ queued arrays/s)
# and freeze the UI while RAM climbs. Sensor acquisition still runs; extras are dropped.
CAMERA_UI_FPS = 12.0
# Popped-out camera tiles: watched, but not the main alignment surface.
CAMERA_POPOUT_FPS = 4.0
# Non-primary thumbnail cameras: keep the device open, but only refresh the
# preview on this period (seconds). Huge USB/CPU win vs streaming three live feeds.
CAMERA_THUMB_PERIOD_S = 30.0
# Downscale live preview before QPixmap conversion (analytics still use full frames).
CAMERA_PREVIEW_MAX_EDGE_PX = 720
# Even smaller preview for thumbnail tiles.
CAMERA_THUMB_PREVIEW_MAX_EDGE_PX = 320

# Which cameras stream during "Start Live Feed" (see core/camera_live_policy.py).
# Production rule: primary (large) pane is live; the other two tiles are one frozen
# snap each. Keep this on "single".
CAMERA_LIVE_POLICY = "single"

# CS165CU is a Bayer color sensor. pylablib debayers on-device to RGB when asked.
# "srgb" yields perceptually realistic color for the live view; beam measurements are
# always computed on a derived intensity image, so color output never affects the math.
CAMERA_COLOR_OUTPUT = "rgb"   # "rgb" | "grayscale" | "raw" | "auto"
CAMERA_COLOR_SPACE = "srgb"   # "srgb" (realistic) | "linear"

# Panel silhouette: rounded-rectangle corner radius (px at 1.0 UI scale) and the
# content inset that keeps widgets clear of the rounded border.
PANEL_CORNER_RADIUS_PX = 20
PANEL_CHAMFER_PX = 22
