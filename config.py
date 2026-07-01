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

# Green laser diode (nominal)
LASER_WAVELENGTH_NM = 520.0

# Beam size target (1/e² average, µm)
BEAM_WAIST_TARGET_UM = (280.0, 300.0)
FIBER_TARGET_ID_UM = 300.0  # hollow-core fiber inner diameter for coupling reticle

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
CAMERA_SETTLE_S = 2.0

# CS165CU is a Bayer color sensor. pylablib debayers on-device to RGB when asked.
# "srgb" yields perceptually realistic color for the live view; beam measurements are
# always computed on a derived intensity image, so color output never affects the math.
CAMERA_COLOR_OUTPUT = "rgb"   # "rgb" | "grayscale" | "raw" | "auto"
CAMERA_COLOR_SPACE = "srgb"   # "srgb" (realistic) | "linear"

# Panel silhouette: rounded-rectangle corner radius (px at 1.0 UI scale) and the
# content inset that keeps widgets clear of the rounded border.
PANEL_CORNER_RADIUS_PX = 20
OCTAGON_CHAMFER_PX = 22
