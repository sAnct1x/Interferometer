"""Launch the Interferometer Automation desktop app."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

LOG_PATH = ROOT / "outputs" / "launch_error.log"


def _log_error(exc: BaseException) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(traceback.format_exc(), encoding="utf-8")


def _load_stylesheet(app) -> None:
    from gui.neon_theme import app_stylesheet

    app.setStyleSheet(app_stylesheet())


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from config import APP_TITLE
    from gui.screen_placement import center_on_primary, restore_window_state, show_maximized_on_primary
    from gui.splash import SplashScreen

    app = QApplication(sys.argv)
    from PySide6.QtCore import Qt

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough,
    )
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("InterferometerAutomation")
    app.setQuitOnLastWindowClosed(True)

    # Seed the UI scale from the primary monitor before the splash is built, so
    # its fixed size and fonts already match this screen instead of always
    # rendering at the 1.0 design scale. Dashboard takes over scale management
    # (per-workspace, live) once it's constructed.
    from gui.ui_scale import screen_ui_scale, set_current_scale
    from gui.window_controls import primary_screen

    set_current_scale(screen_ui_scale(primary_screen()))

    splash = SplashScreen()
    splash.set_progress("Launching…", 0)
    center_on_primary(splash)
    splash.show()
    app.processEvents()

    _load_stylesheet(app)

    dashboard_holder: list = []

    def show_fatal(title: str, message: str) -> None:
        _log_error(RuntimeError(message))
        splash.close()
        QMessageBox.critical(None, title, f"{message}\n\nDetails saved to:\n{LOG_PATH}")
        app.quit()

    def open_dashboard(ok: bool, message: str) -> None:
        try:
            splash.set_progress("Opening dashboard…", 100)
            app.processEvents()

            from core.config_store import load_config
            from core.motion_control import MotionController
            from gui.dashboard import Dashboard

            load_config()
            recovery = MotionController()
            try:
                recovery.on_crash_recovery()
            except Exception:
                pass
            recovery.disconnect()

            dash = Dashboard()
            dashboard_holder.append(dash)
            splash.close()

            # Reopen on whichever monitor/position the app was last closed on;
            # fall back to maximizing on the primary monitor if that display
            # is no longer connected (or this is the first launch).
            cfg = load_config()
            restored = restore_window_state(
                dash,
                screen_name=cfg.window_screen_name,
                geometry=cfg.window_geometry,
                maximized=cfg.window_maximized,
            )
            if not restored:
                show_maximized_on_primary(dash)

            if not ok and message:
                dash._show_error(f"Started with warnings: {message}")
        except Exception as exc:
            show_fatal(APP_TITLE, f"The app failed to open:\n{exc}")

    splash.finished.connect(open_dashboard)

    from core.startup_worker import StartupWorker

    worker = StartupWorker()

    def on_progress(text: str, percent: int) -> None:
        splash.set_progress(text, percent)
        app.processEvents()

    worker.progress.connect(on_progress)
    worker.done.connect(splash.complete)
    worker.start()

    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _log_error(exc)
        raise
