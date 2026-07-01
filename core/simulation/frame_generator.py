"""Synthetic camera frames: Gaussian beam, drifting centroid, modulated fringe ROI."""

from __future__ import annotations

import math

import numpy as np

from config import SENSOR_SIZE_PX
from core.config_store import AppConfig


def make_simulation_frame(t: float, cfg: AppConfig) -> np.ndarray:
    """Build one float32 sensor frame at simulation time ``t`` (seconds)."""
    w, h = SENSOR_SIZE_PX
    y = np.linspace(-1.0, 1.0, h, dtype=np.float32)
    x = np.linspace(-1.0, 1.0, w, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    sigma = 0.11 + 0.04 * math.sin(t * 0.18)
    cx = 0.03 * math.sin(t * 0.09)
    cy = 0.03 * math.cos(t * 0.12)
    beam = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))

    fringe_mod = 0.55 + 0.45 * math.sin(t * 3.0)
    fringe_stripes = 1.0 + 0.10 * np.sin(8.0 * math.pi * xx + t * 1.5)

    frame = beam * 2200.0 + 90.0
    frame = frame * fringe_stripes.astype(np.float32)

    x0, y0, rw, rh = cfg.fringe_roi
    x1 = min(w, x0 + rw)
    y1 = min(h, y0 + rh)
    if x0 < x1 and y0 < y1:
        patch = frame[y0:y1, x0:x1]
        frame[y0:y1, x0:x1] = patch * np.float32(fringe_mod)

    return frame.astype(np.float32, copy=False)


class SimulationFrameGenerator:
    """Stateful wrapper so the worker can refresh ROIs from disk."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def refresh_config(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def frame(self, t: float) -> np.ndarray:
        return make_simulation_frame(t, self._cfg)

    def calibration_time_for_peak_fringe(self) -> float:
        """Time at which fringe modulation peaks (η baseline ≈ 100%)."""
        return math.pi / 2.0 / 3.0
