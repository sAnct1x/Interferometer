"""Splash-screen startup tasks on a background thread."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class StartupWorker(QThread):
    """Load heavy imports and config before the dashboard is constructed."""

    progress = Signal(str, int)  # message, percent 0-100
    done = Signal(bool, str)

    def run(self) -> None:
        """Warm imports and config; emit success or failure to the splash screen."""
        try:
            self.progress.emit("Starting Interferometer Automation…", 5)
            self.progress.emit("Loading core libraries…", 20)
            import numpy  # noqa: F401
            import pyqtgraph  # noqa: F401

            self.progress.emit("Loading configuration…", 45)
            from core.config_store import load_config

            load_config()

            self.progress.emit("Preparing dashboard…", 70)
            import gui.dashboard  # noqa: F401

            self.progress.emit("Ready", 100)
            self.done.emit(True, "Ready")
        except Exception as exc:
            self.progress.emit(f"Startup failed: {exc}", 100)
            self.done.emit(False, str(exc))
