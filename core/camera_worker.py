"""Background Thorcam polling for the Live Camera tile."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from config import CAMERA_FRAME_WAIT_S, CAMERA_POLL_MS, CAMERA_SETTLE_S
from core.hardware_bridge import (
    apply_camera_settings,
    close_device,
    connect_camera,
    read_camera_settings,
    wait_for_frame,
)


class CameraWorker(QThread):
    """Poll the Thorcam in a background thread and emit normalized frames."""

    frame_ready = Signal(object)  # np.ndarray
    status = Signal(str)
    connected = Signal(str)
    error = Signal(str)
    settings_updated = Signal(object)  # dict from read_camera_settings

    def __init__(self, serial: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._serial = serial
        self._running = False
        self._mutex = QMutex()
        self._cam = None
        self._pending_settings: dict = {}
        self._settings_refresh_t = 0.0

    def queue_settings(self, settings: dict) -> None:
        """Thread-safe request to apply camera settings on the worker thread."""
        with QMutexLocker(self._mutex):
            self._pending_settings.update(settings)

    def stop(self) -> None:
        """Request a clean shutdown of the acquisition loop."""
        with QMutexLocker(self._mutex):
            self._running = False

    def run(self) -> None:
        """Connect, stream frames until ``stop()``, then release the camera."""
        try:
            self.status.emit("Connecting to Thorcam…")
            cam = connect_camera(self._serial)
            if cam is None:
                self.error.emit("No Thorcam found. Close ThorCam GUI and check USB.")
                return

            with QMutexLocker(self._mutex):
                self._cam = cam
                self._running = True

            cam.start_acquisition()
            time.sleep(CAMERA_SETTLE_S)
            try:
                serial = cam.get_serial_number()
            except Exception:
                serial = "Thorcam"
            self.connected.emit(str(serial))
            self.status.emit("Live feed active")
            self.settings_updated.emit(read_camera_settings(cam))

            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                try:
                    self._apply_pending_settings(cam)
                    now = time.monotonic()
                    if now - self._settings_refresh_t >= 2.0:
                        self._settings_refresh_t = now
                        self.settings_updated.emit(read_camera_settings(cam))
                    frame = self._acquire_latest(cam)
                    if frame is not None:
                        self.frame_ready.emit(self._as_frame(frame))
                except Exception as exc:
                    self.error.emit(f"Camera read error: {exc}")
                    break
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with QMutexLocker(self._mutex):
                cam_obj = self._cam
                self._cam = None
                self._running = False
            if cam_obj is not None:
                close_device(cam_obj)
            self.status.emit("Camera stopped")

    def _acquire_latest(self, cam) -> object | None:
        """Return the newest frame, blocking on the camera's frame event when possible.

        Waiting on the hardware event delivers the full sensor frame rate while keeping
        CPU usage near zero between frames. Drivers without ``wait_for_frame`` fall back
        to a short poll sleep.
        """
        waiter = getattr(cam, "wait_for_frame", None)
        if waiter is not None:
            try:
                waiter(timeout=CAMERA_FRAME_WAIT_S)
            except Exception:
                return None
            return cam.read_newest_image()

        frame = cam.read_newest_image()
        if frame is None:
            self.msleep(CAMERA_POLL_MS)
        return frame

    def _apply_pending_settings(self, cam) -> None:
        with QMutexLocker(self._mutex):
            if not self._pending_settings:
                return
            pending = dict(self._pending_settings)
            self._pending_settings.clear()
        try:
            apply_camera_settings(cam, pending)
            self.settings_updated.emit(read_camera_settings(cam))
        except Exception as exc:
            self.error.emit(f"Camera settings error: {exc}")

    @staticmethod
    def _as_frame(frame) -> np.ndarray:
        """Normalize to a 2D mono or (H, W, 3) color array; drop only singleton axes."""
        arr = np.asarray(frame)
        if arr.ndim == 3 and arr.shape[-1] == 1:
            return arr[..., 0]
        return arr
