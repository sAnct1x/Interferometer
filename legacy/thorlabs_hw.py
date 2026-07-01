"""Thorcam + K-Cube connect helpers — no matplotlib / poster plot dependencies."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def load_stage_config(path: Path | None = None) -> dict[str, Any]:
    """Load stage_config.json (model, pylablib scale, kinesis params)."""
    p = path or Path("stage_config.json")
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def setup_stage(
    serial: str | None = None,
    *,
    scale: str = "step",
    stage_config: dict[str, Any] | None = None,
) -> Any:
    """Connect to a Thorlabs K-Cube motor via pylablib."""
    from pylablib.devices import Thorlabs

    devs = Thorlabs.list_kinesis_devices()
    if not devs:
        raise RuntimeError("No Thorlabs Kinesis devices found.")
    addr = serial or devs[0][0]
    stage = Thorlabs.KinesisMotor(addr, scale=scale)
    time.sleep(1.5)
    return stage


def setup_camera(serial: str | None = None) -> Any | None:
    """Connect to a Thorlabs TLCam via pylablib. Returns None if no camera is found."""
    from pylablib.devices import Thorlabs
    from pylablib.devices.Thorlabs.TLCamera import ThorlabsTLCamera

    cams = Thorlabs.list_cameras_tlcam()
    if not cams:
        return None
    return ThorlabsTLCamera(serial or cams[0])
