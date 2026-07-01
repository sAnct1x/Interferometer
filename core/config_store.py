"""Load and save app settings: ROIs, stage limits, and wavelength."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import APP_DIR, SUMMER_26_DIR, USER_CONFIG_DIR, LASER_WAVELENGTH_NM
from core.analytics.roi import load_roi_xywh, save_roi_xywh


@dataclass
class StageLimits:
    """Travel and jog limits for one K-Cube stage row in the config file."""

    name: str = "Stage 1"
    serial: str | None = None
    min_mm: float = 0.0
    max_mm: float = 25.0
    max_jog_mm: float = 0.5
    enabled: bool = True


@dataclass
class CameraSlot:
    """Per-camera identity and ROI stored in app_config.json."""

    label: str = "Input"
    serial: str | None = None
    role: str = "input"  # "input" | "output" | "unassigned"
    beam_roi: tuple[int, int, int, int] = (636, 534, 101, 101)
    fringe_roi: tuple[int, int, int, int] = (333, 270, 722, 633)


def _default_cameras() -> list[CameraSlot]:
    return [
        CameraSlot(label="Input", role="input"),
        CameraSlot(label="Output", role="output"),
    ]


@dataclass
class AppConfig:
    """User settings persisted in ``user_config/app_config.json``."""

    beam_roi: tuple[int, int, int, int] = (636, 534, 101, 101)
    fringe_roi: tuple[int, int, int, int] = (333, 270, 722, 633)
    safe_home_mm: float | None = None
    safe_home_stage_serial: str | None = None
    efficiency_reference_mean: float | None = None
    efficiency_reference_ratio: float | None = None
    nominal_wavelength_nm: float = LASER_WAVELENGTH_NM
    last_wavelength_nm: float | None = None
    last_scan_csv: str | None = None
    wavelength_mode: str = "nominal"  # nominal | last_scan | live | manual
    stages: list[StageLimits] = field(default_factory=lambda: [StageLimits()])
    cameras: list[CameraSlot] = field(default_factory=_default_cameras)
    camera_serial: str | None = None  # kept for one-time migration only
    layout_version: int = 0
    ui_display_preset: str = "auto"


def _config_path() -> Path:
    """Return the path to ``app_config.json``."""
    return USER_CONFIG_DIR / "app_config.json"


def _seed_from_legacy() -> AppConfig:
    """Build initial config from Summer '26 beam and interferometer JSON files."""
    cfg = AppConfig()
    beam_path = SUMMER_26_DIR / "beam_roi_config.json"
    fringe_path = SUMMER_26_DIR / "Interferometer Project" / "roi_config.json"
    if beam_path.is_file():
        try:
            cfg.beam_roi = load_roi_xywh(beam_path)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    if fringe_path.is_file():
        try:
            cfg.fringe_roi = load_roi_xywh(fringe_path)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    stage_cfg_path = SUMMER_26_DIR / "Interferometer Project" / "stage_config.json"
    if stage_cfg_path.is_file():
        try:
            data = json.loads(stage_cfg_path.read_text(encoding="utf-8"))
            travel = float(data.get("travel_mm", 25))
            cfg.stages[0].max_mm = travel
            cfg.stages[0].name = str(data.get("stage_model", "Stage 1"))
            jog = data.get("kinesis", {}).get("jog_step_mm", 0.1)
            cfg.stages[0].max_jog_mm = float(jog)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return cfg


def load_config() -> AppConfig:
    """Read ``app_config.json``, creating and seeding it on first launch."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = _config_path()
    if not path.is_file():
        cfg = _seed_from_legacy()
        save_config(cfg)
        return cfg
    data = json.loads(path.read_text(encoding="utf-8"))
    stages = [StageLimits(**s) for s in data.get("stages", [{}])]
    if not stages:
        stages = [StageLimits()]

    # Migrate legacy camera_serial into cameras[0]
    raw_cameras = data.get("cameras", [])
    if raw_cameras:
        cameras = []
        for i, c in enumerate(raw_cameras):
            defaults = {"label": "Input" if i == 0 else "Output",
                        "role": "input" if i == 0 else "output"}
            defaults.update(c)
            defaults["beam_roi"] = tuple(defaults.get("beam_roi", (636, 534, 101, 101)))
            defaults["fringe_roi"] = tuple(defaults.get("fringe_roi", (333, 270, 722, 633)))
            cameras.append(CameraSlot(**{k: defaults[k] for k in CameraSlot.__dataclass_fields__}))
    else:
        cameras = _default_cameras()
        legacy_serial = data.get("camera_serial")
        if legacy_serial:
            cameras[0].serial = str(legacy_serial)

    beam_roi = tuple(data.get("beam_roi", (636, 534, 101, 101)))
    fringe_roi = tuple(data.get("fringe_roi", (333, 270, 722, 633)))

    return AppConfig(
        beam_roi=beam_roi,
        fringe_roi=fringe_roi,
        safe_home_mm=data.get("safe_home_mm"),
        safe_home_stage_serial=data.get("safe_home_stage_serial"),
        efficiency_reference_mean=data.get("efficiency_reference_mean"),
        efficiency_reference_ratio=data.get("efficiency_reference_ratio"),
        nominal_wavelength_nm=float(data.get("nominal_wavelength_nm", LASER_WAVELENGTH_NM)),
        last_wavelength_nm=data.get("last_wavelength_nm"),
        last_scan_csv=data.get("last_scan_csv"),
        wavelength_mode=data.get("wavelength_mode", "nominal"),
        stages=stages,
        cameras=cameras,
        camera_serial=data.get("camera_serial"),
        layout_version=int(data.get("layout_version", 0)),
        ui_display_preset=str(data.get("ui_display_preset", "auto")),
    )


def save_config(cfg: AppConfig) -> None:
    """Write ``app_config.json`` and companion beam/fringe ROI JSON files."""
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    def _cam_to_dict(c: CameraSlot) -> dict:
        return {
            "label": c.label,
            "serial": c.serial,
            "role": c.role,
            "beam_roi": list(c.beam_roi),
            "fringe_roi": list(c.fringe_roi),
        }

    payload: dict[str, Any] = {
        "beam_roi": list(cfg.beam_roi),
        "fringe_roi": list(cfg.fringe_roi),
        "safe_home_mm": cfg.safe_home_mm,
        "safe_home_stage_serial": cfg.safe_home_stage_serial,
        "efficiency_reference_mean": cfg.efficiency_reference_mean,
        "efficiency_reference_ratio": cfg.efficiency_reference_ratio,
        "nominal_wavelength_nm": cfg.nominal_wavelength_nm,
        "last_wavelength_nm": cfg.last_wavelength_nm,
        "last_scan_csv": cfg.last_scan_csv,
        "wavelength_mode": cfg.wavelength_mode,
        "stages": [asdict(s) for s in cfg.stages],
        "cameras": [_cam_to_dict(c) for c in cfg.cameras],
        "camera_serial": cfg.cameras[0].serial if cfg.cameras else None,
        "layout_version": cfg.layout_version,
        "ui_display_preset": cfg.ui_display_preset,
    }
    _config_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    save_roi_xywh(
        cfg.beam_roi,
        USER_CONFIG_DIR / "beam_roi.json",
        notes="Bright beam core only, used for waist measurement.",
    )
    save_roi_xywh(
        cfg.fringe_roi,
        USER_CONFIG_DIR / "fringe_roi.json",
        notes="Wide ROI for interferometer fringes.",
    )


