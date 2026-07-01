"""Gaussian fit quality and M² proxy from 1D beam profiles."""

from __future__ import annotations

import numpy as np

from config import LASER_WAVELENGTH_NM, PIXEL_SIZE_UM


def _gaussian(x: np.ndarray, amp: float, x0: float, sigma: float, offset: float) -> np.ndarray:
    """Evaluate a 1D Gaussian with floor offset."""
    sigma = max(float(sigma), 0.5)
    return offset + amp * np.exp(-0.5 * ((x - x0) / sigma) ** 2)


def fit_gaussian_profile(profile: np.ndarray, *, pixel_size_um: float = PIXEL_SIZE_UM) -> dict:
    """Moment-based Gaussian fit; returns curve overlay and M² proxy."""
    x = np.arange(len(profile), dtype=float)
    offset = float(np.percentile(profile, 8))
    amp = float(max(profile.max() - offset, 1.0))
    weights = np.clip(profile - offset, 0, None)
    total = float(weights.sum())
    if total <= 0:
        nan = float("nan")
        return {"fit": None, "x_um": x * pixel_size_um, "w0_um": nan, "m2": nan, "fit_quality": nan}

    x0 = float((x * weights).sum() / total)
    var = float((weights * (x - x0) ** 2).sum() / total)
    sigma = max(np.sqrt(var), 0.5)
    fit = _gaussian(x, amp, x0, sigma, offset)

    measured = float(profile.max())
    fit_peak = float(fit.max())
    peak_ratio = fit_peak / max(measured, 1.0)
    residual = float(np.linalg.norm(profile - fit) / (np.linalg.norm(profile) + 1e-9))

    w0_um = 2.828427 * sigma * pixel_size_um
    m2 = 1.0 + 2.5 * residual + max(0.0, 1.0 - peak_ratio)
    fit_quality = max(0.0, 1.0 - residual)
    return {
        "fit": fit,
        "x_um": x * pixel_size_um,
        "w0_um": w0_um,
        "m2": m2,
        "fit_quality": fit_quality,
        "peak_ratio": peak_ratio,
    }


def analyze_beam_quality(
    x_profile: np.ndarray,
    y_profile: np.ndarray,
    *,
    measured_w0_um: float,
    pixel_size_um: float = PIXEL_SIZE_UM,
) -> dict:
    """Combine X/Y fits into dashboard metrics."""
    fx = fit_gaussian_profile(x_profile, pixel_size_um=pixel_size_um)
    fy = fit_gaussian_profile(y_profile, pixel_size_um=pixel_size_um)
    m2 = float(np.nanmean([fx["m2"], fy["m2"]]))
    quality = float(np.nanmean([fx["fit_quality"], fy["fit_quality"]]))
    return {
        "m2": m2,
        "fit_quality": quality,
        "x_fit": fx,
        "y_fit": fy,
        "w0_peak_um": measured_w0_um,
        "wavelength_nm": LASER_WAVELENGTH_NM,
    }
