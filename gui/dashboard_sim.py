"""Simulation #1 (mock camera) and Simulation #2 (piezo closed loop) for the hub.

Workers emit frames onto the same camera/analytics path as live hardware
so tiles stay consistent between bench modes."""


from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer

from ai.intents import DEFAULT_SIMULATION_DURATION_SEC
from ai.simulation_report import format_results_statement, format_simulation_report
from core.analytics.beam import analyze_frame, crop_box_from_xywh, roi_mean
from core.analytics.beam_quality import analyze_beam_quality
from core.analytics.coupling import coupling_overlay, default_target_center
from core.analytics.efficiency import coupling_efficiency_percent
from core.camera_roles import CameraRole
from core.config_store import load_config, save_config
from core.simulation.frame_generator import SimulationFrameGenerator, make_simulation_frame
from core.simulation_worker import SimulationWorker
from gui.widgets.camera_view import RoiMode


class DashboardSimMixin:
    """Mixin extracted from Dashboard for maintainability."""


    def _update_sim2_running(self) -> None:
        """Run the closed-loop engine only while Simulation #2 is armed.

        Opening the Piezo tile alone must not spin 30 Hz control + triple renders.
        """
        want = bool(self._sim2_camera_mode)
        if want and not self._sim2_running:
            self._sim2.start()
            self._sim2_running = True
        elif not want and self._sim2_running:
            self._sim2.stop()
            self._sim2_running = False

    def _start_simulation_two(self) -> None:
        if self._simulation_active:
            self._stop_simulation()
        if self._camera_live:
            self._stop_camera()
        self._sim2_camera_mode = True
        self._camera_panel.set_live_active(True, simulation=True)
        self._sim2.connect_driver()
        self._sim2.set_auto(True)
        if hasattr(self._piezo_panel, "sync_buttons"):
            self._piezo_panel.sync_buttons()
        self._update_sim2_running()
        # Piezo's default home overlaps ROI Snapshot's; Sim #2 doesn't feed ROI
        # Snapshot anyway, so tuck it away instead of letting Piezo land on top
        # of it. Only ever auto-hides here, and only un-hides what we hid.
        self._roi_snapshot_was_open_before_sim2 = self._is_tile_open("roi_snapshot")
        if self._roi_snapshot_was_open_before_sim2:
            self.hide_tile("roi_snapshot")
        for tile_id in ("camera", "piezo", "efficiency"):
            self.show_tile(tile_id)
        self._set_activity_source("sim2", 0.45)
        self._log_action("Simulation #2 (piezo closed loop) started")
        self._update_telemetry(status="Simulation #2: piezo closed loop", laser="Simulated")

    def _stop_simulation_two(self) -> None:
        if not self._sim2_camera_mode:
            return
        # Gather the results statement while _sim2_camera_mode is still true
        # (so it reports "Simulation #2" instead of falling back to idle/live).
        self._build_and_post_results_statement()
        self._sim2_camera_mode = False
        self._set_activity_source("sim2", 0.0)
        self._sim2.set_auto(False)
        if hasattr(self._piezo_panel, "sync_buttons"):
            self._piezo_panel.sync_buttons()
        self._update_sim2_running()
        if getattr(self, "_roi_snapshot_was_open_before_sim2", False):
            self.show_tile("roi_snapshot")
        self._roi_snapshot_was_open_before_sim2 = False
        self._camera_panel.set_live_active(False)
        self._camera_panel.show_idle()
        self._camera_panel.set_coupling_overlay(None)
        self._refresh_status(camera_far_field="Idle")
        self._update_telemetry(status="Simulation #2 stopped", laser="Manual")
        self._log_action("Simulation #2 stopped")

    def _on_sim2_frames(self, frames: dict) -> None:
        if not self._sim2_camera_mode:
            return
        for role, payload in frames.items():
            self._camera_panel.set_role_frame(role, payload["frame"], repaint=True)
            overlay = payload.get("overlay")
            if overlay is not None:
                self._camera_panel.set_coupling_overlay(overlay, role)
        now = time.time()
        if now - self._sim2_analytics_last_t >= 0.6:
            self._sim2_analytics_last_t = now
            self._process_sim2_analytics()

    def _process_sim2_analytics(self) -> None:
        """Feed the 3D Beam Profile panel from Simulation #2's Far Field frame.

        Display frames from ``frames_ready`` are downscaled for smooth
        rendering, so beam-fit analytics render a fresh full-resolution frame
        instead (also cached into ``_last_frame`` so a manual "Analyze Beam"
        click works during Simulation #2 too).
        """
        frame = self._sim2.far_field_frame_full_res()
        self._last_frame[CameraRole.FAR_FIELD] = frame
        if not self._is_tile_open("beam"):
            return
        roi = self._cfg.beam_roi
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
        self._beam_panel.update_analysis(result, live=True, update_surface=True)
        if self._is_tile_open("trends"):
            self._trend_panel.append_sample(w0_um=w0)
        if w0 == w0:
            self._update_telemetry(beam_waist_um=w0)

    def _on_sim2_tick(self, rec: dict) -> None:
        if not self._sim2_camera_mode:
            return
        self._camera_panel.set_role_metric(CameraRole.OUTPUT, f"η {rec['eta_pct']:.1f}%")
        self._camera_panel.set_role_metric(CameraRole.FAR_FIELD, f"error {rec['err_px']:.1f} px")
        if self._is_tile_open("efficiency"):
            self._efficiency_panel.set_efficiency(
                rec["eta_pct"],
                detail="Simulation #2: efficiency from Far Field to Output camera",
            )
        self._update_telemetry(efficiency_pct=rec["eta_pct"])

    def _process_frame(
        self, frame: np.ndarray, *, source_role: CameraRole | None = None
    ) -> None:
        now = time.time()
        role = source_role or CameraRole.FAR_FIELD
        roi = self._camera_panel.current_roi()
        overlay: dict | None = None
        # Coupling reticle is Far Field geometry only.
        want_overlay = role is CameraRole.FAR_FIELD

        if self._simulation_active:
            self._simulation_last_frame = np.asarray(frame).copy()
            if now - self._sim_display_last_t >= 0.1:
                self._sim_display_last_t = now
                if want_overlay:
                    target = default_target_center(frame, roi)
                    overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
                    self._camera_panel.set_coupling_overlay(overlay)
                self._camera_panel.set_role_frame(role, frame, repaint=True)
                self._last_sim_overlay = overlay
            else:
                self._camera_panel.set_role_frame(role, frame, repaint=False)
                overlay = self._last_sim_overlay
        elif self._camera_live:
            if now - self._live_display_last_t >= 0.1:
                self._live_display_last_t = now
                if want_overlay:
                    target = default_target_center(frame, roi)
                    overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
                    self._camera_panel.set_coupling_overlay(overlay)
                # Paint the role that produced this frame (do not force Far Field).
                self._camera_panel.set_role_frame(role, frame, repaint=True)
                self._last_live_overlay = overlay
            else:
                self._camera_panel.set_role_frame(role, frame, repaint=False)
                overlay = self._last_live_overlay

        if want_overlay and overlay is None:
            target = default_target_center(frame, roi)
            overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
            if self._camera_live:
                self._last_live_overlay = overlay
            elif self._simulation_active:
                self._last_sim_overlay = overlay

        if not self._camera_live or now - self._live_analytics_last_t >= 0.25:
            fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
            if fringe_mean == fringe_mean:
                self._update_fft_monitor(float(fringe_mean))

        # ROI Snapshot holding a freeze must not block dual-cam η — that left
        # Beam Efficiency stuck after any Snap Frame.
        if self._roi_snapshot_panel.has_snapshot():
            self._compute_live_efficiency()
            if overlay is not None:
                self._refresh_status(
                    camera_far_field=self._camera_status_label(),
                    coupling_err=f"{overlay['error_um']:.1f} µm",
                    coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
                )
            return

        if self._simulation_active:
            if now - self._sim_analytics_last_t >= 0.25:
                self._sim_analytics_last_t = now
                self._process_simulation_analytics(frame)
            if overlay is not None:
                self._refresh_status(
                    camera_far_field=self._camera_status_label(),
                    coupling_err=f"{overlay['error_um']:.1f} µm",
                    coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
                )
            return

        # Beam fitting is on-demand only. Dual-cam η stays live (~4 Hz inside helper).
        if self._camera_live and now - self._live_analytics_last_t < 0.25:
            self._compute_live_efficiency()
            return
        if self._camera_live:
            self._live_analytics_last_t = now

        mode = self._camera_panel.current_mode()
        if mode != RoiMode.BEAM:
            eta_pct = None
            mean = roi_mean(frame, roi)
            if self._cfg.efficiency_reference_mean:
                eta_pct = coupling_efficiency_percent(mean, self._cfg.efficiency_reference_mean)
            if self._is_tile_open("efficiency"):
                self._efficiency_panel.set_efficiency(
                    eta_pct,
                    detail="Efficiency vs. the calibrated 100% baseline",
                )
            if self._is_tile_open("trends"):
                self._trend_panel.append_sample(eta_pct=eta_pct)
            self._update_telemetry(efficiency_pct=eta_pct, status="Fringe ROI")
        else:
            self._compute_live_efficiency()

        if overlay is not None:
            self._refresh_status(
                camera_far_field=self._camera_status_label(),
                coupling_err=f"{overlay['error_um']:.1f} µm",
                coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
            )

    def _camera_status_label(self) -> str:
        if self._simulation_active:
            return "Simulated"
        if self._camera_live:
            return "Active"
        return "Idle"

    def _process_simulation_analytics(self, frame: np.ndarray) -> None:
        """Update beam, efficiency, and both trend series during simulation."""
        beam_roi = self._cfg.beam_roi
        crop = crop_box_from_xywh(beam_roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        if self._is_tile_open("beam"):
            quality = analyze_beam_quality(
                result["x_profile"],
                result["y_profile"],
                measured_w0_um=w0,
            )
            result["beam_quality"] = quality
            result["m2"] = quality["m2"]
            self._beam_panel.update_analysis(result, live=True)

        fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
        eta_pct = None
        if self._cfg.efficiency_reference_mean and fringe_mean == fringe_mean:
            eta_pct = coupling_efficiency_percent(
                fringe_mean,
                self._cfg.efficiency_reference_mean,
            )

        if self._is_tile_open("efficiency"):
            self._efficiency_panel.set_efficiency(
                eta_pct,
                detail="Simulated fiber exit η · P(out)/P(in) vs calibrated baseline",
            )
        if self._is_tile_open("trends"):
            self._trend_panel.append_sample(eta_pct=eta_pct, w0_um=w0)
        self._update_telemetry(
            beam_waist_um=w0,
            efficiency_pct=eta_pct,
            status="Simulation",
            laser="Simulated",
        )

    def _start_simulation(
        self,
        duration_sec: float | None = None,
        *,
        report_to_atria: bool = False,
    ) -> None:
        if self._simulation_active:
            return
        self._stop_camera()
        self._camera_panel.set_live_active(False)

        self._cfg = load_config()
        self._simulation_generator.refresh_config(self._cfg)
        cal_t = self._simulation_generator.calibration_time_for_peak_fringe()
        cal_frame = self._simulation_generator.frame(cal_t)
        fringe_mean = roi_mean(cal_frame, self._cfg.fringe_roi)
        if fringe_mean == fringe_mean and fringe_mean > 0:
            self._cfg.efficiency_reference_mean = fringe_mean
            save_config(self._cfg)

        self._trend_panel.reset()
        self._fft_times.clear()
        self._fft_samples.clear()
        self._simulation_planned_sec = duration_sec
        self._simulation_report_to_atria = report_to_atria
        self._simulation_last_frame = None
        self._simulation_fft_peak_hz = None
        self._simulation_fft_rate_hz = None
        self._simulation_timer.stop()

        self._simulation_worker = SimulationWorker(self._simulation_generator, self)
        self._simulation_worker.frame_ready.connect(self._on_frame)
        self._simulation_worker.error.connect(self._on_simulation_error)
        self._simulation_worker.status.connect(self._on_simulation_status)
        self._simulation_worker.connected.connect(self._on_simulation_connected)
        self._simulation_worker.start()

        self._simulation_active = True
        self._camera_live = True
        self._camera_panel.set_live_active(True, simulation=True)

        if not self._fft_panel.is_monitoring():
            self._fft_panel.set_monitoring(True)

        for tile_id in ("camera", "beam", "efficiency", "trends", "fft", "roi_snapshot"):
            self.show_tile(tile_id)
        self._set_activity_source("sim1", 0.45)

        if duration_sec is not None and duration_sec > 0:
            self._simulation_timer.start(int(duration_sec * 1000))

        if report_to_atria and duration_sec is not None:
            self._log_action(f"Atria: run simulation ({duration_sec:.0f} s)")
        else:
            self._log_action("Bench simulation started")
        self._refresh_status(camera_far_field="Simulated", laser="Simulated")
        self._update_telemetry(status="Simulation active", laser="Simulated")

    def _on_simulation_duration_elapsed(self) -> None:
        if self._simulation_active:
            self._stop_simulation()

    def _stop_simulation(self) -> None:
        if not self._simulation_active:
            return
        self._simulation_timer.stop()
        self._simulation_active = False
        self._set_activity_source("sim1", 0.0)
        worker = self._simulation_worker
        self._simulation_worker = None
        if worker is not None:
            worker.stop()
            if worker.isRunning():
                worker.finished.connect(
                    self._on_simulation_worker_finished,
                    Qt.ConnectionType.SingleShotConnection,
                )
            else:
                QTimer.singleShot(0, self._on_simulation_worker_finished)
        else:
            QTimer.singleShot(0, self._on_simulation_worker_finished)

    def _on_simulation_worker_finished(self) -> None:
        """Light cleanup on the UI thread; defer heavy plot rebuild."""
        self._camera_live = False
        self._camera_panel.set_live_active(False)
        self._camera_panel.show_idle()
        self._camera_panel.set_coupling_overlay(None)
        self._fft_panel.set_monitoring(False, emit=False)
        self._log_action("Bench simulation stopped")
        self._refresh_status(camera_far_field="Idle", laser="Manual")
        self._update_telemetry(status="Simulation stopped", laser="Manual")
        QTimer.singleShot(0, self._complete_simulation_finalize)

    def _complete_simulation_finalize(self) -> None:
        """Finalize plots and Atria report without blocking worker teardown."""
        planned_sec = self._simulation_planned_sec
        report_to_atria = self._simulation_report_to_atria
        last_frame = self._simulation_last_frame
        overlay = self._last_sim_overlay
        fft_peak = self._simulation_fft_peak_hz
        fft_rate = self._simulation_fft_rate_hz

        self._simulation_planned_sec = None
        self._simulation_report_to_atria = False
        self._simulation_last_frame = None
        self._simulation_fft_peak_hz = None
        self._simulation_fft_rate_hz = None
        self._last_sim_overlay = None

        beam_result = None
        if last_frame is not None:
            beam_result = self._finalize_simulation_plots(last_frame)

        if report_to_atria:
            self._post_simulation_atria_report(
                planned_sec=planned_sec,
                beam_result=beam_result,
                coupling_overlay=overlay,
                fft_peak_hz=fft_peak,
                fft_rate_hz=fft_rate,
            )

    def _finalize_simulation_plots(self, frame: np.ndarray) -> dict:
        """Run full (non-live) analysis so 3D surface and profiles reflect the final frame."""
        roi = self._cfg.beam_roi
        self._roi_snapshot_panel.set_snapshot(frame, roi, RoiMode.BEAM)
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
        self._beam_panel.update_analysis(result, live=False, frame=frame)
        self._export_beam_report(
            result=result,
            frame=frame,
            source="simulation",
            open_workspace=False,
            quiet=True,
        )
        fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
        eta_pct = None
        if self._cfg.efficiency_reference_mean and fringe_mean == fringe_mean:
            eta_pct = coupling_efficiency_percent(
                fringe_mean,
                self._cfg.efficiency_reference_mean,
            )
        self._efficiency_panel.set_efficiency(
            eta_pct,
            detail="Simulated fiber exit η · final frame",
        )
        self._update_telemetry(
            beam_waist_um=w0 if w0 == w0 else None,
            efficiency_pct=eta_pct,
            status="Simulation complete",
            laser="Simulated",
        )
        return result

    def _post_simulation_atria_report(
        self,
        *,
        planned_sec: float | None,
        beam_result: dict | None,
        coupling_overlay: dict | None,
        fft_peak_hz: float | None,
        fft_rate_hz: float | None,
    ) -> None:
        report = format_simulation_report(
            planned_sec=planned_sec,
            trend_summary=self._trend_panel.summary(),
            beam_result=beam_result,
            coupling_overlay=coupling_overlay,
            fft_peak_hz=fft_peak_hz,
            fft_rate_hz=fft_rate_hz,
        )
        self.show_tile("atria")
        self._ai_panel.post_bench_message(report)

    def _current_mode_label(self) -> str:
        """Which of the four bench states is active right now, for reporting."""
        if self._simulation_active:
            return "sim1"
        if self._sim2_camera_mode:
            return "sim2"
        if self._camera_live:
            return "live"
        return "idle"

    def _build_and_post_results_statement(self) -> None:
        """Post a full "what's happening right now" summary to Atria.

        Works on demand (results_statement intent) or auto-posted when
        Simulation #2 stops; gathers telemetry, the session trend summary,
        the latest coupling overlay, and (when Simulation #2 has run at all)
        its control history and current drift/noise settings.
        """
        sim2_history = None
        sim2_disturbance = None
        if self._sim2_camera_mode or self._sim2_running:
            sim2_history = list(self._sim2.controller.history)
            sim2_disturbance = self._sim2.disturbance_snapshot()
        report = format_results_statement(
            mode=self._current_mode_label(),
            telemetry=dict(self._telemetry),
            trend_summary=self._trend_panel.summary(),
            coupling_overlay=self._last_sim_overlay or self._last_live_overlay,
            fft_peak_hz=self._simulation_fft_peak_hz,
            fft_rate_hz=self._simulation_fft_rate_hz,
            sim2_history=sim2_history,
            sim2_disturbance=sim2_disturbance,
        )
        self.show_tile("atria")
        self._ai_panel.post_bench_message(report)

    def _on_simulation_error(self, message: str) -> None:
        self._stop_simulation()
        self._show_error(message)

    def _on_simulation_status(self, status: str) -> None:
        self._update_telemetry(status=status)

    def _on_simulation_connected(self, _label: str) -> None:
        self._refresh_status(camera_far_field="Simulated")

