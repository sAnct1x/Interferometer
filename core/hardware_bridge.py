"""Thorcam and K-Cube access via legacy ``interferometer_acquire_analyze`` in ``legacy/``."""

from __future__ import annotations

import sys
import time
from typing import Any

from config import LEGACY_SCRIPTS_DIR


def _ensure_legacy_path() -> None:
    legacy = str(LEGACY_SCRIPTS_DIR)
    if legacy not in sys.path:
        sys.path.insert(0, legacy)


def list_cameras() -> list[str]:
    """Return serial number strings of all connected TLCam cameras."""
    _ensure_legacy_path()
    try:
        from pylablib.devices import Thorlabs

        return [str(s) for s, _ in Thorlabs.list_cameras_tlcam()]
    except Exception:
        return []


def connect_camera(serial: str | None = None) -> Any | None:
    _ensure_legacy_path()
    from thorlabs_hw import setup_camera

    cam = setup_camera(serial)
    if cam is not None:
        _configure_color(cam)
    return cam


def _configure_color(cam: Any) -> None:
    """Enable on-device debayering to RGB for color (Bayer) sensors like the CS165CU.

    Monochrome sensors are left untouched. Any driver/SDK mismatch degrades
    gracefully to the camera's default output rather than aborting the connection.
    """
    from config import CAMERA_COLOR_OUTPUT, CAMERA_COLOR_SPACE

    try:
        sensor_type = getattr(cam.get_sensor_info(), "sensor_type", None)
    except Exception:
        return
    if sensor_type != "bayer":
        return
    try:
        cam.set_color_format(CAMERA_COLOR_OUTPUT, CAMERA_COLOR_SPACE)
    except Exception:
        pass


def connect_stage(serial: str | None = None, *, scale: str = "Z825") -> Any:
    _ensure_legacy_path()
    from thorlabs_hw import load_stage_config, setup_stage

    cfg = load_stage_config(LEGACY_SCRIPTS_DIR / "stage_config.json")
    scale_name = str(cfg.get("pylablib_scale", scale))
    return setup_stage(serial, scale=scale_name, stage_config=cfg)


def close_device(device: Any) -> None:
    if device is None:
        return
    try:
        if hasattr(device, "stop_acquisition"):
            device.stop_acquisition()
    except Exception:
        pass
    try:
        device.close()
    except Exception:
        pass


def wait_for_frame(cam: Any, timeout_s: float = 15.0) -> Any:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        frame = cam.read_newest_image()
        if frame is not None:
            return frame
        time.sleep(0.05)
    raise TimeoutError("Camera returned no frame within timeout.")


def _tlcam_lib() -> Any:
    from pylablib.devices.Thorlabs.tl_camera_sdk_lib import wlib

    return wlib


def read_camera_settings(cam: Any) -> dict[str, Any]:
    """Read exposure, FPS mode, white balance, and measured rate from an open TLCam."""
    settings: dict[str, Any] = {
        "color_sensor": False,
        "exposure_us": None,
        "exposure_min_us": 10.0,
        "exposure_max_us": 1_000_000.0,
        "fps_auto": True,
        "fps_hz": None,
        "fps_min": 1.0,
        "fps_max": 120.0,
        "measured_fps": None,
        "wb_rgb": (1.0, 1.0, 1.0),
    }
    if cam is None:
        return settings

    try:
        sensor = cam.get_sensor_info()
        settings["color_sensor"] = getattr(sensor, "sensor_type", None) == "bayer"
    except Exception:
        pass

    try:
        settings["exposure_us"] = float(cam.get_exposure()) * 1e6
    except Exception:
        pass

    try:
        exp_min, exp_max = _tlcam_lib().tl_camera_get_exposure_time_range(cam.handle)
        settings["exposure_min_us"] = float(exp_min)
        settings["exposure_max_us"] = float(exp_max)
    except Exception:
        pass

    try:
        lib = _tlcam_lib()
        fps_control = bool(lib.tl_camera_get_is_frame_rate_control_enabled(cam.handle))
        settings["fps_auto"] = not fps_control
        fp_min, fp_max = cam.get_frame_period_range()
        if fp_max > 0:
            settings["fps_min"] = 1.0 / fp_max
        if fp_min > 0:
            settings["fps_max"] = 1.0 / fp_min
        if fps_control:
            period = cam.get_frame_period()
            if period and period > 0:
                settings["fps_hz"] = 1.0 / period
        try:
            settings["measured_fps"] = float(
                lib.tl_camera_get_measured_frame_rate(cam.handle)
            )
        except Exception:
            timings = cam.get_frame_timings()
            if timings.frame_period > 0:
                settings["measured_fps"] = 1.0 / timings.frame_period
    except Exception:
        pass

    if settings["color_sensor"]:
        try:
            mat = cam.get_white_balance_matrix()
            settings["wb_rgb"] = (float(mat[0, 0]), float(mat[1, 1]), float(mat[2, 2]))
        except Exception:
            pass

    return settings


def apply_camera_settings(cam: Any, settings: dict[str, Any]) -> None:
    """Apply a partial settings dict to an open TLCam."""
    if cam is None or not settings:
        return

    if "exposure_us" in settings:
        cam.set_exposure(float(settings["exposure_us"]) * 1e-6)

    if "fps_auto" in settings or "fps_hz" in settings:
        fps_auto = settings.get("fps_auto")
        if fps_auto is True:
            cam.set_frame_period(None)
        elif fps_auto is False:
            fps = settings.get("fps_hz")
            if fps and float(fps) > 0:
                cam.set_frame_period(1.0 / float(fps))
            else:
                cam.set_frame_period(None)
        elif "fps_hz" in settings:
            fps = settings["fps_hz"]
            if fps and float(fps) > 0:
                cam.set_frame_period(1.0 / float(fps))

    if "wb_rgb" in settings:
        wb = settings["wb_rgb"]
        if wb is None:
            cam.set_white_balance_matrix(None)
        else:
            r, g, b = wb
            cam.set_white_balance_matrix((float(r), float(g), float(b)))
