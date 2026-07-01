"""Intensity heatmaps for beam ROI visualization (Gaussian peak = hot center)."""

from __future__ import annotations

import numpy as np

try:
    import matplotlib.cm as mpl_cm

    _TURBO = mpl_cm.get_cmap("turbo")
except Exception:
    _TURBO = None


def normalize_intensity(gray: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Return normalized 0–1 float array and (lo, hi) used for scaling."""
    g = np.asarray(gray, dtype=np.float64)
    lo, hi = np.percentile(g, 1.0), np.percentile(g, 99.5)
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((g - lo) / (hi - lo), 0.0, 1.0)
    return norm, float(lo), float(hi)


def intensity_to_rgb(gray: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Map scalar intensity to RGB (low = blue/purple, high = red/yellow)."""
    norm, lo, hi = normalize_intensity(gray)
    if _TURBO is not None:
        rgb = _TURBO(norm)[..., :3]
        return (rgb * 255).astype(np.uint8), lo, hi

    # Fallback jet-like ramp without matplotlib
    t = norm
    r = np.clip(1.5 - 4.0 * np.abs(t - 0.75), 0, 1)
    g = np.clip(1.5 - 4.0 * np.abs(t - 0.5), 0, 1)
    b = np.clip(1.5 - 4.0 * np.abs(t - 0.25), 0, 1)
    rgb = np.stack([r, g, b], axis=-1)
    return (rgb * 255).astype(np.uint8), lo, hi


def colormap_rgb_at(t: float) -> tuple[int, int, int]:
    """Sample turbo (or fallback jet) at normalized intensity t ∈ [0, 1]."""
    t = float(np.clip(t, 0.0, 1.0))
    if _TURBO is not None:
        r, g, b, _ = _TURBO(t)
        return int(r * 255), int(g * 255), int(b * 255)
    return (
        int(255 * min(1.0, 1.5 - 4.0 * abs(t - 0.75))),
        int(255 * min(1.0, 1.5 - 4.0 * abs(t - 0.5))),
        int(255 * min(1.0, 1.5 - 4.0 * abs(t - 0.25))),
    )


def intensity_centroid(
    gray: np.ndarray,
    roi: tuple[int, int, int, int],
) -> tuple[float, float]:
    """Intensity-weighted centroid in full-image pixel coordinates."""
    rx, ry, rw, rh = roi
    h, w = gray.shape
    rx = max(0, min(rx, w - 1))
    ry = max(0, min(ry, h - 1))
    rw = max(1, min(rw, w - rx))
    rh = max(1, min(rh, h - ry))
    crop = np.asarray(gray[ry : ry + rh, rx : rx + rw], dtype=np.float64)
    crop = np.clip(crop - np.min(crop), 0, None)
    total = float(crop.sum())
    if total <= 0:
        return rx + rw / 2.0, ry + rh / 2.0
    yy, xx = np.indices(crop.shape)
    cx = rx + float((xx * crop).sum() / total)
    cy = ry + float((yy * crop).sum() / total)
    return cx, cy


def padded_roi_crop(
    gray: np.ndarray,
    roi: tuple[int, int, int, int],
    *,
    pad_fraction: float = 0.22,
    min_pad_px: int = 24,
) -> tuple[np.ndarray, int, int]:
    """Crop gray around ROI with padding; returns (crop, origin_x, origin_y)."""
    h, w = gray.shape
    rx, ry, rw, rh = roi
    pad = max(min_pad_px, int(pad_fraction * max(rw, rh)))
    x0 = max(0, rx - pad)
    y0 = max(0, ry - pad)
    x1 = min(w, rx + rw + pad)
    y1 = min(h, ry + rh + pad)
    return gray[y0:y1, x0:x1], x0, y0
