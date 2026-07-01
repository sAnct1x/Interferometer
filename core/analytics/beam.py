"""Live and offline beam waist analysis from Thorcam frames."""

from __future__ import annotations

from typing import Any

import numpy as np

from config import PIXEL_SIZE_UM
from core.analytics.profiles import (
    estimate_background_border,
    profile_baseline,
    width_from_profile_detailed,
)


def to_grayscale(img: np.ndarray) -> np.ndarray:
    """Convert RGB or mono input to a 2D grayscale array."""
    if img.ndim == 3:
        return img[..., :3].mean(axis=2)
    return np.asarray(img)


def crop_image(img: np.ndarray, crop_box: tuple[int, int, int, int] | None) -> np.ndarray:
    """Crop using ``(x_min, x_max, y_min, y_max)`` indices."""
    if crop_box is None:
        return img
    x_min, x_max, y_min, y_max = crop_box
    h, w = img.shape
    x_min = int(np.clip(x_min, 0, w - 1))
    x_max = int(np.clip(x_max, x_min + 1, w))
    y_min = int(np.clip(y_min, 0, h - 1))
    y_max = int(np.clip(y_max, y_min + 1, h))
    return img[y_min:y_max, x_min:x_max]


def crop_box_from_xywh(roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Convert ``(x, y, w, h)`` ROI to ``(x_min, x_max, y_min, y_max)``."""
    x, y, w, h = roi
    return (x, x + w, y, y + h)


def roi_mean(frame: np.ndarray, roi_xywh: tuple[int, int, int, int]) -> float:
    """Mean grayscale intensity inside an ``(x, y, w, h)`` ROI."""
    x, y, w, h = roi_xywh
    h_img, w_img = frame.shape[:2]
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    if x >= x2 or y >= y2:
        return float("nan")
    patch = to_grayscale(frame)[y:y2, x:x2]
    return float(np.mean(patch))


def _roi_limited_warning(
    axis_name: str,
    width_px: float,
    profile_len: int,
    left_x: float,
    right_x: float,
    *,
    level_name: str,
    pixel_size_um: float,
) -> str | None:
    if not np.isfinite(width_px) or profile_len <= 0:
        return None
    fill = width_px / profile_len
    edge_margin = max(3.0, 0.06 * profile_len)
    near_edge = left_x <= edge_margin or right_x >= profile_len - 1 - edge_margin
    if fill >= 0.88 or near_edge:
        width_um = width_px * pixel_size_um
        return (
            f"{axis_name} {level_name} width ({width_um:.0f} µm) is ROI-limited; "
            "tighten the box to the bright core only."
        )
    return None


def measurement_warnings(
    img_bs: np.ndarray,
    x_profile: np.ndarray,
    y_profile: np.ndarray,
    *,
    background_level: float,
    raw_peak: float,
) -> list[str]:
    """Collect ROI size, background, and profile-edge warnings for the user."""
    warnings: list[str] = []
    h, w = img_bs.shape
    if min(h, w) < 80:
        warnings.append(f"ROI crop is only {w}×{h} px — include more dark margin around the beam.")
    if raw_peak > 0 and background_level / raw_peak > 0.25:
        warnings.append("Background is high vs peak; border may still be inside the halo.")
    for axis_name, profile in ("X", x_profile), ("Y", y_profile):
        baseline = profile_baseline(profile)
        peak = float(np.max(profile))
        if peak <= 0:
            continue
        if baseline / peak > 0.35:
            warnings.append(f"{axis_name} profile edges are still bright — beam may be clipped by ROI.")
    return warnings


def _append_roi_limit_warnings(
    warnings: list[str],
    *,
    e2_x_px: float,
    e2_y_px: float,
    e2_x_l: float,
    e2_x_r: float,
    e2_y_l: float,
    e2_y_r: float,
    x_len: int,
    y_len: int,
    pixel_size_um: float,
) -> None:
    """Append stuck-waist and axis-asymmetry warnings after width measurement."""
    e2_x_um = e2_x_px * pixel_size_um
    e2_y_um = e2_y_px * pixel_size_um
    e2_avg = (e2_x_um + e2_y_um) / 2
    axis_delta = abs(e2_x_um - e2_y_um)
    stuck_361 = 340 <= e2_avg <= 380 and axis_delta < 25
    severe_asymmetry = axis_delta > 50
    x_msg = _roi_limited_warning(
        "X", e2_x_px, x_len, e2_x_l, e2_x_r, level_name="1/e²", pixel_size_um=pixel_size_um
    )
    y_msg = _roi_limited_warning(
        "Y", e2_y_px, y_len, e2_y_l, e2_y_r, level_name="1/e²", pixel_size_um=pixel_size_um
    )
    if stuck_361:
        warnings.append(
            "1/e² average stuck near ~361 µm — ROI includes fringes/halo, not just the bright waist."
        )
    elif severe_asymmetry:
        if x_msg:
            warnings.append(x_msg)
        if y_msg:
            warnings.append(y_msg)
        warnings.append(f"Large X/Y mismatch ({axis_delta:.0f} µm) — recenter or resize ROI.")


def analyze_frame(
    frame: np.ndarray,
    *,
    crop_box: tuple[int, int, int, int] | None = None,
    pixel_size_um: float = PIXEL_SIZE_UM,
    border: int = 20,
) -> dict[str, Any]:
    """Analyze one camera frame; returns metrics plus img_bs and profiles for plotting."""
    img = to_grayscale(frame).astype(np.float64)
    img = crop_image(img, crop_box=crop_box)
    raw_peak = float(np.max(img))
    background = estimate_background_border(img, border=border)
    img_bs = img - background
    img_bs[img_bs < 0] = 0.0

    x_profile = img_bs.sum(axis=0)
    y_profile = img_bs.sum(axis=1)
    quality_warnings = measurement_warnings(
        img_bs, x_profile, y_profile, background_level=background, raw_peak=raw_peak
    )

    fwhm_x_px, _, _ = width_from_profile_detailed(x_profile, 0.5)
    fwhm_y_px, _, _ = width_from_profile_detailed(y_profile, 0.5)
    e2_x_px, e2_x_l, e2_x_r = width_from_profile_detailed(x_profile, 1 / np.e**2)
    e2_y_px, e2_y_l, e2_y_r = width_from_profile_detailed(y_profile, 1 / np.e**2)

    _append_roi_limit_warnings(
        quality_warnings,
        e2_x_px=e2_x_px,
        e2_y_px=e2_y_px,
        e2_x_l=e2_x_l,
        e2_x_r=e2_x_r,
        e2_y_l=e2_y_l,
        e2_y_r=e2_y_r,
        x_len=len(x_profile),
        y_len=len(y_profile),
        pixel_size_um=pixel_size_um,
    )

    e2_avg = (e2_x_px + e2_y_px) / 2 * pixel_size_um if np.isfinite(e2_x_px) else float("nan")

    return {
        "fwhm_x_um": fwhm_x_px * pixel_size_um,
        "fwhm_y_um": fwhm_y_px * pixel_size_um,
        "one_over_e2_x_um": e2_x_px * pixel_size_um,
        "one_over_e2_y_um": e2_y_px * pixel_size_um,
        "one_over_e2_avg_um": (e2_x_px * pixel_size_um + e2_y_px * pixel_size_um) / 2,
        "background_level": background,
        "cropped_shape": img_bs.shape,
        "img_bs": img_bs,
        "x_profile": x_profile,
        "y_profile": y_profile,
        "quality_warnings": quality_warnings,
        "beam_waist_um": e2_avg,
    }
