"""Background Thorcam polling for the Live Camera tile."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from config import (
    CAMERA_BOOTSTRAP_FRAME_WAIT_S,
    CAMERA_FRAME_WAIT_S,
    CAMERA_NO_FRAME_WARN_S,
    CAMERA_POLL_MS,
    CAMERA_SETTLE_S,
    CAMERA_UI_FPS,
)
from core.hardware_bridge import (
    apply_camera_settings,
    camera_device_serial,
    close_device,
    connect_camera,
    grab_latest_frame,
    read_camera_settings,
    start_acquisition,
    stop_acquisition,
)

# How long a periodic (thumbnail) grab keeps the sensor streaming to capture one
# fresh frame before stopping again to free USB bandwidth.
_PERIODIC_GRAB_TIMEOUT_S = 2.0


class CameraWorker(QThread):
    """Poll the Thorcam in a background thread and emit normalized frames.

    Emit rate is adjustable at runtime (primary vs thumbnail vs pop-out). In
    slow/thumbnail mode the thread sleeps between grabs instead of draining the
    sensor at full rate — that is what keeps three cameras from melting the PC.
    """

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
        self._last_emit_t = 0.0
        self._emit_interval = 1.0 / max(1.0, float(CAMERA_UI_FPS))
        # When True, a frame_ready is already queued for the GUI; drop sensor
        # frames until acknowledge_frame() so QueuedConnection cannot back up.
        self._gui_busy = False
        self._gui_busy_since = 0.0
        # Continuous = keep the sensor streaming (primary / popped-out view).
        # Periodic = stop acquisition between grabs so a thumbnail camera does
        # not hog USB bandwidth while Far Field + Output stream continuously.
        self._continuous = True
        self._acquisition_active = False

    def queue_settings(self, settings: dict) -> None:
        """Thread-safe request to apply camera settings on the worker thread."""
        with QMutexLocker(self._mutex):
            self._pending_settings.update(settings)

    def set_emit_interval(self, seconds: float) -> None:
        """How often this worker may push a frame to the GUI (primary vs thumb)."""
        with QMutexLocker(self._mutex):
            new_interval = max(0.05, float(seconds))
            # Promoting a thumbnail to primary should wake the feed immediately.
            if new_interval < self._emit_interval:
                self._last_emit_t = 0.0
            self._emit_interval = new_interval

    def emit_interval(self) -> float:
        with QMutexLocker(self._mutex):
            return self._emit_interval

    def set_streaming_mode(self, continuous: bool) -> None:
        """Continuous keeps the sensor streaming (primary/pop-out); periodic stops
        acquisition between grabs so a thumbnail camera frees the USB bus."""
        cam = None
        with QMutexLocker(self._mutex):
            was = self._continuous
            cont = bool(continuous)
            if cont and not self._continuous:
                self._last_emit_t = 0.0
            self._continuous = cont
            if was and not cont and self._acquisition_active:
                cam = self._cam
                self._acquisition_active = False
        if cam is not None:
            stop_acquisition(cam)

    def streaming_mode_continuous(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._continuous

    def stop(self) -> None:
        """Request a clean shutdown of the acquisition loop."""
        with QMutexLocker(self._mutex):
            self._running = False

    def acknowledge_frame(self) -> None:
        """GUI finished handling the last emit; allow the next ``frame_ready``."""
        with QMutexLocker(self._mutex):
            self._gui_busy = False
            self._gui_busy_since = 0.0

    def run(self) -> None:
        """Connect, stream frames until ``stop()``, then release the camera."""
        cam = None
        try:
            label = self._serial or "(auto)"
            self.status.emit(f"Connecting to Thorcam {label}…")
            try:
                cam = connect_camera(self._serial)
            except Exception as exc:
                self.error.emit(str(exc))
                return
            if cam is None:
                self.error.emit(
                    f"No Thorcam {label}. Close ThorCam GUI, check USB, then retry."
                )
                return

            with QMutexLocker(self._mutex):
                self._cam = cam
                self._running = True
                self._gui_busy = False
                self._gui_busy_since = 0.0
                continuous = self._continuous

            # Apply any settings queued before the thread started (exposure etc.).
            self._apply_pending_settings(cam)

            if continuous:
                start_acquisition(cam)
                self._acquisition_active = True
                time.sleep(CAMERA_SETTLE_S)
            else:
                # Thumbnail cameras must not leave the sensor streaming — three
                # simultaneous streams starve USB and one camera gets zero frames.
                time.sleep(0.2)

            serial = camera_device_serial(cam, self._serial)
            if serial:
                self.connected.emit(str(serial))
            self.status.emit("Live feed active")
            self.settings_updated.emit(read_camera_settings(cam))
            with QMutexLocker(self._mutex):
                self._last_emit_t = 0.0

            acq_start = time.monotonic()
            frame_seen = False
            no_frame_warned = False
            label = str(serial or self._serial or "camera")

            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                    interval = self._emit_interval
                    last_emit = self._last_emit_t
                    gui_busy = self._gui_busy
                    continuous = self._continuous

                try:
                    self._apply_pending_settings(cam)
                    now = time.monotonic()

                    settings_every = 2.0 if interval < 1.0 else max(10.0, interval)
                    if now - self._settings_refresh_t >= settings_every:
                        self._settings_refresh_t = now
                        self.settings_updated.emit(read_camera_settings(cam))

                    # Until the first frame lands, poll aggressively regardless of
                    # thumbnail interval (otherwise Image waits 30 s before trying).
                    bootstrap = not frame_seen
                    wait_s = 0.0 if bootstrap else (interval - (now - last_emit))
                    if not bootstrap and (gui_busy or wait_s > 0.05):
                        sleep_ms = int(min(max(wait_s, 0.05), 0.5) * 1000)
                        self.msleep(max(1, sleep_ms))
                        continue

                    if continuous:
                        if not self._acquisition_active:
                            start_acquisition(cam)
                            self._acquisition_active = True
                            time.sleep(0.08)
                        timeout = (
                            CAMERA_BOOTSTRAP_FRAME_WAIT_S
                            if bootstrap
                            else CAMERA_FRAME_WAIT_S
                        )
                        frame = self._grab_frame(cam, timeout)
                    else:
                        frame = self._periodic_grab(cam)

                    if frame is None:
                        if bootstrap and not no_frame_warned and (
                            time.monotonic() - acq_start > CAMERA_NO_FRAME_WARN_S
                        ):
                            no_frame_warned = True
                            self.status.emit(
                                f"Connected to {label} but no frames yet — "
                                f"try raising exposure (Settings → {label})."
                            )
                        self.msleep(max(1, CAMERA_POLL_MS))
                        continue

                    frame_seen = True
                    self._maybe_emit_frame(frame)
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
                self._gui_busy = False
                self._gui_busy_since = 0.0
            if cam_obj is not None:
                close_device(cam_obj)
            self.status.emit("Camera stopped")

    def _periodic_grab(self, cam) -> object | None:
        """One grab window for a thumbnail camera, then stop acquisition again."""
        start_acquisition(cam)
        try:
            time.sleep(0.08)
            return grab_latest_frame(cam, _PERIODIC_GRAB_TIMEOUT_S)
        finally:
            stop_acquisition(cam)

    def _grab_frame(self, cam, timeout_s: float) -> object | None:
        return grab_latest_frame(cam, timeout_s)

    def _maybe_emit_frame(self, frame) -> None:
        """Rate-limit GUI emits and refuse to queue a second frame until ACKed."""
        now = time.monotonic()
        with QMutexLocker(self._mutex):
            if self._gui_busy:
                if self._gui_busy_since and (now - self._gui_busy_since) > 2.0:
                    self._gui_busy = False
                else:
                    return
            if (now - self._last_emit_t) < self._emit_interval:
                return
            self._gui_busy = True
            self._gui_busy_since = now
            self._last_emit_t = now
        self.frame_ready.emit(self._as_frame(frame))

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
        return np.array(arr, copy=True)
