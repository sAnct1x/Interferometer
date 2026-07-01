"""Load and save beam and fringe ROI rectangles as JSON."""

from __future__ import annotations

import json
from pathlib import Path

from core.analytics.beam import crop_box_from_xywh


def load_roi_xywh(path: Path) -> tuple[int, int, int, int]:
    """Read ``(x, y, w, h)`` from a ROI JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "crop_box" in data:
        cb = tuple(int(v) for v in data["crop_box"])
        x_min, x_max, y_min, y_max = cb
        return (x_min, y_min, x_max - x_min, y_max - y_min)
    return (int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))


def save_roi_xywh(
    roi: tuple[int, int, int, int],
    path: Path,
    *,
    notes: str = "",
    extra: dict | None = None,
) -> None:
    """Write ROI JSON with xywh, crop_box, and optional notes/extra fields."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "x": int(roi[0]),
        "y": int(roi[1]),
        "w": int(roi[2]),
        "h": int(roi[3]),
        "crop_box": list(crop_box_from_xywh(roi)),
        "notes": notes,
    }
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
