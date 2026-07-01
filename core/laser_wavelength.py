"""Resolve which laser wavelength the GUI and analytics should use."""

from __future__ import annotations

from config import LASER_WAVELENGTH_NM
from core.config_store import AppConfig


def resolve_wavelength_nm(cfg: AppConfig) -> float:
    """Return the wavelength used for telemetry and analysis display."""
    mode = cfg.wavelength_mode
    if mode == "nominal":
        return float(cfg.nominal_wavelength_nm)
    if cfg.last_wavelength_nm is not None and mode in ("last_scan", "live", "manual"):
        return float(cfg.last_wavelength_nm)
    return float(cfg.nominal_wavelength_nm)


def wavelength_mode_label(mode: str) -> str:
    """Return a short human label for a ``wavelength_mode`` config value."""
    labels = {
        "nominal": "diode label",
        "last_scan": "measured (scan)",
        "live": "live estimate",
        "manual": "manual entry",
    }
    return labels.get(mode, mode)
