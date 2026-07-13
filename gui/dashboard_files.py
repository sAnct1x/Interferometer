"""File menu and Workspace I/O helpers for the hub dashboard."""


from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from config import DATA_DIR, OUTPUT_DIR
from core.analytics.beam_export import BEAM_OUTPUT_DIR


class DashboardFileMixin:
    """Mixin extracted from Dashboard for maintainability."""


    def _file_open_workspace(self) -> None:
        start = DATA_DIR if DATA_DIR.is_dir() else Path.home()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open in Workspace",
            str(start),
            (
                "All supported (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.csv *.txt *.json);;"
                "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif);;"
                "Data (*.csv *.txt *.json);;"
                "All files (*.*)"
            ),
        )
        if not path:
            return
        err = self._workspace_panel.open_file(Path(path))
        if err:
            self._show_error(err)
            return
        self._view_center_workspace()
        self._update_telemetry(status=f"Workspace: {Path(path).name}")

    def _view_center_workspace(self) -> None:
        """Open or refocus Workspace dead-center (same tile chrome as other panels)."""
        tile = self._tiles.get("workspace")
        if tile is not None and tile._minimized:
            self.restore_tile_from_bar("workspace")
        self._tile_layout.show_tile_centered("workspace")
        self._update_telemetry(status="Workspace centered")

    def _file_save_camera_snapshot(self) -> None:
        frame = self._roi_snapshot_panel.analysis_frame()
        if frame is None:
            frame = self._camera_panel.current_frame()
        if frame is None:
            self._show_error("No camera frame available. Start live feed or snap a frame.")
            return
        default = OUTPUT_DIR / "captures"
        default.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Camera Snapshot",
            str(default / "snapshot.png"),
            "PNG image (*.png);;JPEG image (*.jpg);;BMP image (*.bmp)",
        )
        if not path:
            return
        self._workspace_panel.open_numpy_image(frame, label="Camera snapshot")
        pix = self._workspace_panel.current_pixmap()
        if pix is None or pix.isNull():
            self._show_error("Could not prepare snapshot for save.")
            return
        if not pix.save(path):
            self._show_error(f"Failed to save image: {path}")
            return
        self._update_telemetry(status=f"Saved {Path(path).name}")

    def _file_save_workspace_image(self) -> None:
        if not self._workspace_panel.has_exportable_image():
            self._show_error("Workspace has no image to save. Open an image or save a camera snapshot first.")
            return
        pix = self._workspace_panel.current_pixmap()
        if pix is None:
            return
        default = OUTPUT_DIR / "exports"
        default.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Workspace Image",
            str(default / "workspace_export.png"),
            "PNG image (*.png);;JPEG image (*.jpg);;BMP image (*.bmp)",
        )
        if not path:
            return
        if not pix.save(path):
            self._show_error(f"Failed to save image: {path}")
            return
        self._update_telemetry(status=f"Saved {Path(path).name}")

    def _file_open_data_dir(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR.resolve())))

    def _file_open_outputs_dir(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT_DIR.resolve())))

    def _file_open_beam_outputs_dir(self) -> None:
        BEAM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(BEAM_OUTPUT_DIR.resolve())))

    def _file_load_scan_csv(self) -> None:
        start = DATA_DIR / "scans"
        if not start.is_dir():
            start = DATA_DIR
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Scan CSV",
            str(start),
            "CSV files (*.csv);;All files (*.*)",
        )
        if path:
            self._load_scan_csv(path)

