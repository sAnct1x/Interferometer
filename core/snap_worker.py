"""Single-frame Thorcam capture for ROI Snapshot and frozen thumbnails."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from config import CAMERA_SETTLE_S
from core.hardware_bridge import (
    apply_camera_settings,
    close_device,
    connect_camera,
    start_acquisition,
    wait_for_frame,
)

# Thumb nails must fail fast so a dark/blocked camera cannot stall live start.
DEFAULT_SNAP_TIMEOUT_S = 15.0
THUMB_SNAP_TIMEOUT_S = 3.0


class SnapWorker(QThread):
    """Grab one TLCam frame in a background thread, then release the device."""

    frame_ready = Signal(object)
    error = Signal(str)
    status = Signal(str)

    def __init__(
        self,
        camera_serial: str | None = None,
        *,
        settings: dict | None = None,
        timeout_s: float = DEFAULT_SNAP_TIMEOUT_S,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._serial = camera_serial
        self._settings = dict(settings or {})
        self._timeout_s = float(timeout_s)

    def run(self) -> None:
        """Connect, acquire one frame, emit it, and close the camera."""
        cam = None
        try:
            label = self._serial or "(auto)"
            self.status.emit(f"Connecting {label} for single frame…")
            cam = connect_camera(self._serial)
            if cam is None:
                self.error.emit(f"Camera {label} connection failed.")
                return
            if self._settings:
                apply_camera_settings(cam, self._settings)
            start_acquisition(cam)
            time.sleep(min(0.35, CAMERA_SETTLE_S))
            self.status.emit("Capturing frame…")
            frame = wait_for_frame(cam, timeout_s=self._timeout_s)
            self.frame_ready.emit(np.asarray(frame))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            close_device(cam)
