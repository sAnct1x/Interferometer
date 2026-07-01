"""1D profile math for beam width measurement."""

from __future__ import annotations

import numpy as np


def profile_baseline(profile: np.ndarray, edge_fraction: float = 0.08) -> float:
    """Estimate profile baseline from the outer edge strips."""
    p = np.asarray(profile, dtype=float)
    edge_n = max(3, int(len(p) * edge_fraction))
    return 0.5 * (float(np.mean(p[:edge_n])) + float(np.mean(p[-edge_n:])))


def width_from_profile_detailed(
    profile: np.ndarray, level_fraction: float
) -> tuple[float, float, float]:
    """Return (width_px, left_crossing_px, right_crossing_px)."""
    p = np.asarray(profile, dtype=float)
    baseline = profile_baseline(p)
    p = p - baseline
    p[p < 0] = 0.0
    if np.allclose(p, 0):
        return np.nan, np.nan, np.nan

    peak_idx = int(np.argmax(p))
    peak = float(p[peak_idx])
    level = peak * level_fraction

    left = peak_idx
    while left > 0 and p[left] >= level:
        left -= 1
    if left == peak_idx:
        return np.nan, np.nan, np.nan

    x0, x1 = left, left + 1
    y0, y1 = p[left], p[left + 1]
    x_left = x0 + (level - y0) * (x1 - x0) / (y1 - y0 + 1e-30)

    right = peak_idx
    while right < len(p) - 1 and p[right] >= level:
        right += 1
    if right == peak_idx:
        return np.nan, np.nan, np.nan

    x0, x1 = right - 1, right
    y0, y1 = p[right - 1], p[right]
    x_right = x0 + (level - y0) * (x1 - x0) / (y1 - y0 + 1e-30)

    return float(x_right - x_left), float(x_left), float(x_right)


def estimate_background_border(img: np.ndarray, border: int = 20) -> float:
    """Estimate background level from image border strips and dim percentile."""
    h, w = img.shape
    b = max(1, min(int(border), h // 10, w // 10, h // 2, w // 2))
    border_pixels = np.concatenate(
        [
            img[:b, :].ravel(),
            img[-b:, :].ravel(),
            img[:, :b].ravel(),
            img[:, -b:].ravel(),
        ]
    )
    border_med = float(np.median(border_pixels))
    dim_pct = float(np.percentile(img, 5))
    return min(border_med, dim_pct)
