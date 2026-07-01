"""Fiber coupling overlay geometry for the Live Camera reticle."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from config import FIBER_TARGET_ID_UM, PIXEL_SIZE_UM
from core.analytics.beam import to_grayscale


def fiber_target_radius_px(*, fiber_id_um: float = FIBER_TARGET_ID_UM) -> float:
    """Convert hollow-core fiber inner diameter to pixel radius on the camera."""
    return (fiber_id_um / 2.0) / PIXEL_SIZE_UM


def beam_centroid_px(frame: np.ndarray, roi_xywh: tuple[int, int, int, int] | None = None) -> tuple[float, float]:
    """Intensity-weighted centroid in full-frame coordinates."""
    gray = to_grayscale(frame).astype(np.float64)
    if roi_xywh is not None:
        x, y, w, h = roi_xywh
        gray = gray[y : y + h, x : x + w]
        offset_x, offset_y = float(x), float(y)
    else:
        offset_x = offset_y = 0.0

    weights = np.clip(gray, 0, None)
    total = float(weights.sum())
    if total <= 0:
        h, w = gray.shape
        return offset_x + w / 2, offset_y + h / 2

    yy, xx = np.indices(weights.shape)
    cx = float((xx * weights).sum() / total) + offset_x
    cy = float((yy * weights).sum() / total) + offset_y
    return cx, cy


def coupling_overlay(
    frame: np.ndarray,
    *,
    target_center_px: tuple[float, float],
    fiber_id_um: float = FIBER_TARGET_ID_UM,
    roi_xywh: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    """Build overlay geometry for the live coupling reticle."""
    cx, cy = beam_centroid_px(frame, roi_xywh)
    tx, ty = target_center_px
    dx = cx - tx
    dy = cy - ty
    dist_px = math.hypot(dx, dy)
    dist_um = dist_px * PIXEL_SIZE_UM
    angle_deg = math.degrees(math.atan2(dy, dx)) if dist_px > 0.5 else 0.0
    radius_px = fiber_target_radius_px(fiber_id_um=fiber_id_um)

    return {
        "target_center_px": (tx, ty),
        "target_radius_px": radius_px,
        "centroid_px": (cx, cy),
        "error_um": dist_um,
        "error_angle_deg": angle_deg,
        "error_vector_px": (dx, dy),
    }


def default_target_center(frame: np.ndarray, roi_xywh: tuple[int, int, int, int]) -> tuple[float, float]:
    """Return ROI center as coupling target until piezo calibration overrides it."""
    x, y, w, h = roi_xywh
    return x + w / 2.0, y + h / 2.0
