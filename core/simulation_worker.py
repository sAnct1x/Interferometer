"""Background simulation feed for Live Camera and analytics tiles."""

from __future__ import annotations

import time

from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from config import CAMERA_POLL_MS
from core.simulation.frame_generator import SimulationFrameGenerator


class SimulationWorker(QThread):
    """Emit synthetic frames on the same cadence as the real camera worker."""

    frame_ready = Signal(object)
    status = Signal(str)
    connected = Signal(str)
    error = Signal(str)

    def __init__(self, generator: SimulationFrameGenerator, parent=None) -> None:
        super().__init__(parent)
        self._generator = generator
        self._running = False
        self._mutex = QMutex()

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._running = False

    def run(self) -> None:
        try:
            self.status.emit("Starting simulation feed…")
            with QMutexLocker(self._mutex):
                self._running = True
            self.connected.emit("Simulation")
            self.status.emit("Simulation feed active")
            start = time.time()
            while True:
                with QMutexLocker(self._mutex):
                    if not self._running:
                        break
                t = time.time() - start
                frame = self._generator.frame(t)
                self.frame_ready.emit(frame)
                self.msleep(CAMERA_POLL_MS)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            with QMutexLocker(self._mutex):
                self._running = False
            self.status.emit("Simulation stopped")
