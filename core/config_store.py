"""Load and save app settings: ROIs, stage limits, and wavelength."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import SUMMER_26_DIR, USER_CONFIG_DIR, LASER_WAVELENGTH_NM
from core.analytics.roi import load_roi_xywh, save_roi_xywh
from core.camera_roles import ACTIVE_ROLES, CameraRole


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
    """Per-camera identity and ROI stored in app_config.json.

    On the three-camera wedge bench a slot is bound to a fixed ``role``
    (far_field | image | output). Legacy two-camera files stored input/output;
    ``CameraRole.coerce`` maps those forward on load.
    """

    label: str = "Far Field"
    serial: str | None = None
    role: str = "far_field"  # far_field | image | output | unassigned
    beam_roi: tuple[int, int, int, int] = (636, 534, 101, 101)
    fringe_roi: tuple[int, int, int, int] = (333, 270, 722, 633)


def _default_cameras() -> list[CameraSlot]:
    """One slot per active bench role, in display order (Far Field first)."""
    return [
        CameraSlot(label=role.label, role=role.value)
        for role in ACTIVE_ROLES
    ]


def _default_camera_roles() -> dict[str, str | None]:
    """Placeholder role -> serial map for the three-camera bench.

    Serials are unknown until hardware arrives; the UI picker fills these in and
    save_config persists them. Simulation #2 ignores serials entirely.
    """
    return {role.value: None for role in ACTIVE_ROLES}


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
    # role (far_field | image | output) -> camera serial for the 3-camera bench.
    camera_roles: dict[str, str | None] = field(default_factory=_default_camera_roles)
    camera_serial: str | None = None  # kept for one-time migration only
    layout_version: int = 0
    ui_display_preset: str = "auto"
    # Remembers which monitor/position the main window was last closed on, so
    # relaunching doesn't always dump you back on the primary display.
    window_screen_name: str | None = None
    window_geometry: tuple[int, int, int, int] | None = None
    window_maximized: bool = True

    def camera_by_role(self, role) -> CameraSlot | None:
        """Return the camera slot bound to ``role`` (accepts CameraRole or str)."""
        want = CameraRole.coerce(role).value
        for slot in self.cameras:
            if CameraRole.coerce(slot.role).value == want:
                return slot
        return None


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

    # Build exactly one slot per active bench role, migrating any saved cameras
    # onto their coerced role (legacy input -> far_field, output -> output).
    saved_by_role: dict[str, dict] = {}
    for c in data.get("cameras", []):
        role_key = CameraRole.coerce(c.get("role")).value
        saved_by_role.setdefault(role_key, c)  # first match wins per role

    legacy_serial = data.get("camera_serial")
    cameras: list[CameraSlot] = []
    for role in ACTIVE_ROLES:
        saved = saved_by_role.get(role.value, {})
        beam_roi = tuple(saved.get("beam_roi", (636, 534, 101, 101)))
        fringe = tuple(saved.get("fringe_roi", (333, 270, 722, 633)))
        serial = saved.get("serial")
        if serial is None and role is CameraRole.FAR_FIELD and legacy_serial:
            serial = str(legacy_serial)
        cameras.append(
            CameraSlot(
                label=str(saved.get("label", role.label)),
                serial=str(serial) if serial else None,
                role=role.value,
                beam_roi=beam_roi,
                fringe_roi=fringe,
            )
        )

    beam_roi = tuple(data.get("beam_roi", (636, 534, 101, 101)))
    fringe_roi = tuple(data.get("fringe_roi", (333, 270, 722, 633)))

    camera_roles = _default_camera_roles()
    raw_roles = data.get("camera_roles")
    if isinstance(raw_roles, dict):
        for role, serial in raw_roles.items():
            key = CameraRole.coerce(role).value
            if key in camera_roles:
                camera_roles[key] = str(serial) if serial else None

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
        camera_roles=camera_roles,
        camera_serial=data.get("camera_serial"),
        layout_version=int(data.get("layout_version", 0)),
        ui_display_preset=str(data.get("ui_display_preset", "auto")),
        window_screen_name=data.get("window_screen_name"),
        window_geometry=(
            tuple(data["window_geometry"]) if data.get("window_geometry") else None
        ),
        window_maximized=bool(data.get("window_maximized", True)),
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
        # Keep the role->serial map in lockstep with the camera slots.
        "camera_roles": {
            CameraRole.coerce(c.role).value: c.serial for c in cfg.cameras
        },
        "camera_serial": (
            cfg.camera_by_role(CameraRole.FAR_FIELD).serial
            if cfg.camera_by_role(CameraRole.FAR_FIELD)
            else None
        ),
        "layout_version": cfg.layout_version,
        "ui_display_preset": cfg.ui_display_preset,
        "window_screen_name": cfg.window_screen_name,
        "window_geometry": list(cfg.window_geometry) if cfg.window_geometry else None,
        "window_maximized": cfg.window_maximized,
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


