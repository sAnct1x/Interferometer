"""Default and user-saved hub tile positions in normalized workspace coordinates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import USER_CONFIG_DIR

LAYOUT_VERSION = 2

# Tiles hidden on first launch (opened from Tools / View menus).
STARTUP_HIDDEN_TILES = frozenset(
    {"stage", "workspace", "piezo", "fft", "tasks"}
)

# Home layout: left beam/trends/efficiency/status, center camera, right atria.
DEFAULT_TILE_LAYOUT: dict[str, dict[str, float]] = {
    "beam": {"x": 0.02, "y": 0.02, "w": 0.36, "h": 0.40},
    "trends": {"x": 0.02, "y": 0.43, "w": 0.36, "h": 0.22},
    "efficiency": {"x": 0.02, "y": 0.66, "w": 0.17, "h": 0.30},
    "status": {"x": 0.21, "y": 0.66, "w": 0.17, "h": 0.30},
    "camera": {"x": 0.40, "y": 0.02, "w": 0.34, "h": 0.47},
    "roi_snapshot": {"x": 0.40, "y": 0.50, "w": 0.34, "h": 0.46},
    "atria": {"x": 0.76, "y": 0.02, "w": 0.22, "h": 0.94},
    "stage": {"x": 0.40, "y": 0.44, "w": 0.22, "h": 0.30},
    "piezo": {"x": 0.58, "y": 0.55, "w": 0.22, "h": 0.35},
    "fft": {"x": 0.58, "y": 0.18, "w": 0.22, "h": 0.32},
    "tasks": {"x": 0.76, "y": 0.55, "w": 0.22, "h": 0.38},
    "workspace": {"x": 0.24, "y": 0.16, "w": 0.52, "h": 0.68},
}

# Recommended homes for small laptops (1366×768 / 1280×720 presets).
COMPACT_TILE_LAYOUT: dict[str, dict[str, float]] = {
    "camera": {"x": 0.02, "y": 0.02, "w": 0.50, "h": 0.44},
    "beam": {"x": 0.02, "y": 0.48, "w": 0.50, "h": 0.48},
    "atria": {"x": 0.54, "y": 0.02, "w": 0.44, "h": 0.94},
}

COMPACT_HIDDEN_TILES = frozenset(
    {"trends", "roi_snapshot", "efficiency", "status", "stage", "piezo", "fft", "tasks", "workspace"}
)


@dataclass
class TileLayoutFile:
    """On-disk JSON schema for saved tile home positions."""

    version: int = LAYOUT_VERSION
    homes: dict[str, dict[str, float]] | None = None


def layout_json_path() -> Path:
    """Path to ``user_config/tile_layout.json``."""
    return USER_CONFIG_DIR / "tile_layout.json"


def layout_log_path() -> Path:
    """Path to the append-only human-readable tile layout log."""
    return USER_CONFIG_DIR / "tile_layout.log"


def _layout_json_path() -> Path:
    return layout_json_path()


def _layout_log_path() -> Path:
    return layout_log_path()


def load_tile_layout() -> dict[str, dict[str, float]]:
    """Return saved homes merged with defaults (workspace omitted until user saves)."""
    homes, _ = load_tile_layout_with_keys()
    return homes


def load_tile_layout_with_keys() -> tuple[dict[str, dict[str, float]], set[str]]:
    """Return (merged homes, tile ids explicitly stored in the user's layout file)."""
    path = _layout_json_path()
    if not path.is_file():
        homes = dict(DEFAULT_TILE_LAYOUT)
        homes.pop("workspace", None)
        return homes, set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(data.get("version", 0))
        if version < LAYOUT_VERSION:
            homes = dict(DEFAULT_TILE_LAYOUT)
            homes.pop("workspace", None)
            return homes, set()

        saved = data.get("homes", {})
        if not isinstance(saved, dict) or not saved:
            homes = dict(DEFAULT_TILE_LAYOUT)
            homes.pop("workspace", None)
            return homes, set()

        saved_keys = set(saved.keys())
        merged = dict(DEFAULT_TILE_LAYOUT)
        merged.update(saved)
        if "workspace" not in saved_keys:
            merged.pop("workspace", None)
        return merged, saved_keys
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        homes = dict(DEFAULT_TILE_LAYOUT)
        homes.pop("workspace", None)
        return homes, set()


def save_tile_layout(homes: dict[str, dict[str, float]], *, note: str = "manual save") -> Path:
    """Write JSON homes and append a human-readable log entry."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": LAYOUT_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "homes": homes,
    }
    json_path = _layout_json_path()
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    log_path = _layout_log_path()
    lines = [
        f"--- {payload['saved_at']} ({note}) ---",
    ]
    for tile_id, rect in sorted(homes.items()):
        lines.append(
            f"  {tile_id:12s}  x={rect['x']:.4f}  y={rect['y']:.4f}  "
            f"w={rect['w']:.4f}  h={rect['h']:.4f}"
        )
    lines.append("")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    return json_path


def reset_tile_layout_file() -> None:
    """Delete the saved layout file so defaults apply on next launch."""
    path = _layout_json_path()
    if path.is_file():
        path.unlink()
