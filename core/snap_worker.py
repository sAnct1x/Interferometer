"""Single-frame Thorcam capture for ROI Snap Shot and offline analysis."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThread, Signal

from core.hardware_bridge import close_device, connect_camera, wait_for_frame


class SnapWorker(QThread):
    """Grab one TLCam frame in a background thread."""

    frame_ready = Signal(object)
    error = Signal(str)
    status = Signal(str)

    def __init__(self, camera_serial: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._serial = camera_serial

    def run(self) -> None:
        """Connect, wait for one frame, emit it, and close the camera."""
        cam = None
        try:
            self.status.emit("Connecting camera for single frame…")
            cam = connect_camera(self._serial)
            if cam is None:
                self.error.emit("Camera connection failed.")
                return
            self.status.emit("Capturing frame…")
            frame = wait_for_frame(cam, timeout_s=15.0)
            self.frame_ready.emit(np.asarray(frame))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            close_device(cam)
