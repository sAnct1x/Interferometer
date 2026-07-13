"""Beam analyze / export / latest-run helpers for the hub dashboard.

Keeps matplotlib export and Atria beam-report intents out of the main window file.
Export runs on a worker thread so Analyze Beam does not freeze the UI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QThread, Signal

from config import CAMERA_SERIAL_FAR_FIELD
from core.analytics.beam import analyze_frame, crop_box_from_xywh
from core.analytics.beam_export import export_beam_run, read_latest_summary
from core.analytics.beam_quality import analyze_beam_quality
from core.camera_roles import CameraRole
from core.laser_wavelength import resolve_wavelength_nm


class _BeamExportWorker(QThread):
    """Background matplotlib package writer for one analysis result."""

    finished_ok = Signal(object, bool)  # Path, open_workspace
    failed = Signal(str, bool)  # message, quiet

    def __init__(
        self,
        *,
        result: dict,
        frame: np.ndarray | None,
        source: str,
        wavelength_nm: float,
        roi_xywh: tuple[int, int, int, int] | None,
        open_workspace: bool,
        quiet: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._result = result
        self._frame = frame
        self._source = source
        self._wavelength_nm = wavelength_nm
        self._roi_xywh = roi_xywh
        self._open_workspace = open_workspace
        self._quiet = quiet

    def run(self) -> None:
        try:
            run_dir = export_beam_run(
                self._result,
                frame=self._frame,
                source=self._source,
                wavelength_nm=self._wavelength_nm,
                camera_serial=CAMERA_SERIAL_FAR_FIELD,
                roi_xywh=self._roi_xywh,
            )
            self.finished_ok.emit(run_dir, self._open_workspace)
        except Exception as exc:
            self.failed.emit(str(exc), self._quiet)


class DashboardBeamMixin:
    """Mixin: Analyze Beam, Save Report, and latest-run open/summarize."""

    def _analyze_beam(self) -> None:
        self._on_analyze_snapshot()

    def _on_analyze_snapshot(self) -> None:
        frame = self._roi_snapshot_panel.analysis_frame()
        if frame is None:
            self._show_error("Snap a frame from Bench Cameras first.")
            return
        roi = self._roi_snapshot_panel.current_roi()
        crop = crop_box_from_xywh(roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        quality = analyze_beam_quality(
            result["x_profile"],
            result["y_profile"],
            measured_w0_um=w0,
        )
        result["beam_quality"] = quality
        result["m2"] = quality["m2"]
        self._beam_panel.update_analysis(result, frame=frame)
        self._trend_panel.append_sample(w0_um=w0)
        self._log_action(f"Beam analyzed, w₀ ≈ {w0:.1f} µm")
        self._update_telemetry(beam_waist_um=w0, status="Beam analyzed")
        self._export_beam_report(
            result=result,
            frame=frame,
            source="roi_snapshot",
            roi_xywh=tuple(roi) if roi else None,
            open_workspace=False,
        )

    def _analyze_beam_snapshot(self) -> None:
        """Run a one-shot beam analysis on the latest live frame (on-demand, not live)."""
        frame = self._last_frame.get(CameraRole.FAR_FIELD)
        if frame is None and self._simulation_active:
            frame = getattr(self, "_simulation_last_frame", None)
        if frame is None:
            self._show_error("No live frame available. Start the camera feed first.")
            return
        roi = self._camera_panel.current_roi()
        crop = crop_box_from_xywh(roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        quality = analyze_beam_quality(
            result["x_profile"],
            result["y_profile"],
            measured_w0_um=w0,
        )
        result["beam_quality"] = quality
        result["m2"] = quality["m2"]
        self._beam_panel.update_analysis(result, frame=frame)
        if self._is_tile_open("trends"):
            self._trend_panel.append_sample(w0_um=w0)
        self._log_action(f"Beam analyzed (live), w₀ ≈ {w0:.1f} µm")
        self._update_telemetry(beam_waist_um=w0, status="Beam analyzed")
        self._export_beam_report(
            result=result,
            frame=frame,
            source="live_analyze",
            roi_xywh=tuple(roi) if roi else None,
            open_workspace=False,
        )

    def _export_beam_report(
        self,
        *,
        result: dict | None = None,
        frame: np.ndarray | None = None,
        source: str = "manual",
        roi_xywh: tuple[int, int, int, int] | None = None,
        open_workspace: bool = True,
        quiet: bool = False,
    ) -> Path | None:
        """Queue a labeled beam package write (worker thread; returns None immediately)."""
        if result is None:
            result = self._beam_panel.last_analysis()
        if frame is None:
            frame = self._beam_panel.last_analysis_frame()
        if result is None:
            if quiet:
                return None
            self._show_error("No beam analysis to export. Click Analyze Beam first.")
            return None
        if roi_xywh is None:
            try:
                roi = self._camera_panel.current_roi()
                if roi is not None:
                    roi_xywh = tuple(int(v) for v in roi)
            except Exception:
                roi_xywh = None

        prev = getattr(self, "_beam_export_worker", None)
        if prev is not None and prev.isRunning():
            if not quiet:
                self._update_telemetry(status="Beam export already running…")
            return None

        worker = _BeamExportWorker(
            result=result,
            frame=None if frame is None else np.asarray(frame).copy(),
            source=source,
            wavelength_nm=float(resolve_wavelength_nm(self._cfg)),
            roi_xywh=roi_xywh,
            open_workspace=open_workspace,
            quiet=quiet,
            parent=self,
        )
        self._beam_export_worker = worker
        worker.finished_ok.connect(self._on_beam_export_finished)
        worker.failed.connect(self._on_beam_export_failed)
        self._update_telemetry(status="Saving beam report…")
        worker.start()
        return None

    def _on_beam_export_finished(self, run_dir: object, open_workspace: bool) -> None:
        path = Path(str(run_dir))
        self._log_action(f"Beam report saved → {path.name}")
        self._update_telemetry(status=f"Beam report {path.name}")
        if open_workspace:
            report = path / "beam_report.png"
            if report.is_file():
                err = self._workspace_panel.open_file(report)
                if err is None:
                    self.show_tile("workspace")
                    self._view_center_workspace()

    def _on_beam_export_failed(self, message: str, quiet: bool) -> None:
        if not quiet:
            self._show_error(f"Beam export failed: {message}")

    def _open_latest_beam_run(self) -> None:
        """Open the latest beam report PNG in Workspace (and reveal the run folder)."""
        info = read_latest_summary()
        if info is None:
            self._show_error(
                "No beam run found yet. Analyze Beam or click Save Report first."
            )
            return
        report = Path(info["report_png"])
        if report.is_file():
            err = self._workspace_panel.open_file(report)
            if err:
                self._show_error(err)
            else:
                self.show_tile("workspace")
                self._view_center_workspace()
        run_dir = Path(info["run_dir"])
        if run_dir.is_dir():
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(run_dir.resolve())))
        self._log_action(f"Opened latest beam run {info.get('run_id')}")

    def _summarize_latest_beam_run(self) -> None:
        """Post latest beam-run summary + artifact list to Atria."""
        info = read_latest_summary()
        if info is None:
            self._show_error(
                "No saved beam run yet. Analyze Beam (or Save Report) first."
            )
            return
        meta = info.get("meta") or {}
        summary = (info.get("summary") or "").strip()
        artifacts = meta.get("artifacts") or [
            "beam_report.png",
            "beam_heatmap.png",
            "beam_profiles.png",
            "beam_surface_3d.png",
            "results.csv",
            "meta.json",
        ]
        lines = [
            "Latest beam analysis package",
            f"Run: {info.get('run_id')}",
            f"Folder: {info.get('run_dir')}",
            "",
        ]
        if summary:
            lines.append(summary)
        else:
            w0 = meta.get("one_over_e2_avg_um")
            m2 = meta.get("m2")
            lines.append(f"w₀ ≈ {w0} µm · M² ≈ {m2}")
        lines.append("")
        lines.append("Artifacts:")
        for name in artifacts:
            lines.append(f"  • {name}")
        lines.append("")
        lines.append(
            "Ask me to open the latest beam report to view figures in Workspace."
        )
        self.show_tile("atria")
        self._ai_panel.post_bench_message("\n".join(lines))
        report = Path(info["report_png"])
        if report.is_file():
            self._workspace_panel.open_file(report)
            self.show_tile("workspace")
