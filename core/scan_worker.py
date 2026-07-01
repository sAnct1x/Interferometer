"""Background K-Cube fringe scan for wavelength recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from config import DATA_DIR, LEGACY_SCRIPTS_DIR
from core.analytics.interferometer import recover_wavelength_from_csv


class WavelengthScanWorker(QThread):
    """Run a short stage scan on the fringe ROI and FFT-recover λ."""

    status = Signal(str)
    finished_ok = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        *,
        roi_xywh: tuple[int, int, int, int],
        stage_serial: str | None,
        camera_serial: str | None,
        start_mm: float = 0.0,
        stop_mm: float = 1.5,
        step_mm: float = 0.02,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._roi = roi_xywh
        self._stage_serial = stage_serial
        self._camera_serial = camera_serial
        self._start_mm = start_mm
        self._stop_mm = stop_mm
        self._step_mm = step_mm

    def run(self) -> None:
        """Execute the stage scan and FFT wavelength recovery off the UI thread."""
        import sys

        legacy = str(LEGACY_SCRIPTS_DIR)
        if legacy not in sys.path:
            sys.path.insert(0, legacy)

        try:
            from interferometer_acquire_analyze import run_stage_scan

            out_dir = DATA_DIR / "scans"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out_csv = out_dir / f"fringes_{stamp}.csv"
            stage_cfg = LEGACY_SCRIPTS_DIR / "stage_config.json"

            self.status.emit("Connecting stage + camera for λ scan…")
            run_stage_scan(
                roi=self._roi,
                start_steps=None,
                stop_steps=None,
                step_steps=None,
                start_mm=self._start_mm,
                stop_mm=self._stop_mm,
                step_mm=self._step_mm,
                settle_s=0.15,
                out_csv=out_csv,
                stage_serial=self._stage_serial,
                cam_serial=self._camera_serial,
                meta_extra={"source": "ia_gui_wavelength_scan"},
                return_to_start=True,
                stage_config_path=stage_cfg if stage_cfg.is_file() else None,
                show_plots=False,
                live_plot=False,
            )
            self.status.emit("Analyzing interferogram FFT…")
            result = recover_wavelength_from_csv(out_csv)
            if result.get("error"):
                self.error.emit(str(result["error"]))
                return
            result["csv_path"] = str(out_csv)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
