"""Background simulation feed for Live Camera and analytics tiles.

Emits synthetic frames at the UI refresh rate with backpressure so a slow GUI
cannot queue hundreds of full-resolution arrays (unlike a raw poll loop).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from config import CAMERA_UI_FPS
from core.simulation.frame_generator import SimulationFrameGenerator


class SimulationWorker(QThread):
    """Emit synthetic frames on the same cadence as the real camera UI path."""

    frame_ready = Signal(object)
    status = Signal(str)
    connected = Signal(str)
    error = Signal(str)

    def __init__(self, generator: SimulationFrameGenerator, parent=None) -> None:
        super().__init__(parent)
        self._generator = generator
        self._running = False
        self._mutex = QMutex()
        # Mirror CameraWorker: skip emit while the previous frame is still queued.
        self._gui_busy = False
        self._emit_interval_s = 1.0 / max(float(CAMERA_UI_FPS), 1.0)

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._running = False

    def acknowledge_frame(self) -> None:
        """Call from the GUI slot after a frame is handled so the next can emit."""
        with QMutexLocker(self._mutex):
            self._gui_busy = False

    def run(self) -> None:
        try:
            self.status.emit("Starting simulation feed…")
            with QMutexLocker(self._mutex):
                self._running = True
                self._gui_busy = False
            self.connected.emit("Simulation")
            self.status.emit("Simulation feed active")
            start = time.time()
            last_emit = 0.0
            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                    busy = self._gui_busy
                now = time.time()
                if busy or (now - last_emit) < self._emit_interval_s:
                    self.msleep(5)
                    continue
                t = now - start
                frame = self._generator.frame(t)
                with QMutexLocker(self._mutex):
                    self._gui_busy = True
                self.frame_ready.emit(frame)
                last_emit = now
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with QMutexLocker(self._mutex):
                self._running = False
                self._gui_busy = False
            self.status.emit("Simulation stopped")
