"""Atria intent dispatch for the hub dashboard.

Maps structured Intent names from the chat panel onto dashboard actions.
Hardware-gated intents require the Allow hardware control toggle."""


from __future__ import annotations

from ai.intents import DEFAULT_SIMULATION_DURATION_SEC, Intent
from core.config_store import load_config, save_config


class DashboardAtriaMixin:
    """Mixin extracted from Dashboard for maintainability."""


    def _on_ai_intent(self, intent: Intent, hardware_allowed: bool) -> None:
        name = intent.name
        if name == "set_wavelength_nominal":
            self._cfg = load_config()
            nm = intent.params.get("nm")
            if nm is not None:
                self._cfg.nominal_wavelength_nm = float(nm)
            self._cfg.wavelength_mode = "nominal"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action("Atria: active λ set to nominal diode label")
            self._update_telemetry(
                status=f"λ diode label {self._telemetry['wavelength_nm']:.2f} nm",
            )
        elif name == "set_wavelength_measured":
            self._cfg = load_config()
            if self._cfg.last_wavelength_nm is None:
                self._show_error(
                    "No measured wavelength yet. Run Scan wavelength or load a scan CSV."
                )
                return
            self._cfg.wavelength_mode = "last_scan"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action("Atria: active λ set to last scan")
            self._update_telemetry(
                status=f"λ measured {self._telemetry['wavelength_nm']:.2f} nm",
            )
        elif name == "set_wavelength":
            nm = float(intent.params["nm"])
            self._cfg = load_config()
            self._cfg.last_wavelength_nm = nm
            self._cfg.wavelength_mode = "manual"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action(f"Atria: λ set to {nm:.2f} nm (manual)")
            self._update_telemetry(status=f"λ set to {nm:.2f} nm")
        elif name == "capture_roi":
            self._save_current_roi()
        elif name == "toggle_live_feed":
            self._toggle_live_feed(bool(intent.params.get("active", True)))
        elif name == "snap_frame":
            if self._camera_live:
                frame = self._camera_panel.current_frame()
                if frame is not None:
                    self._on_snapshot_captured(frame)
            else:
                self._grab_single_frame()
        elif name == "analyze_beam":
            self._analyze_beam()
        elif name == "export_beam_report":
            self._export_beam_report(source="atria", open_workspace=True)
        elif name == "open_latest_beam_run":
            self._open_latest_beam_run()
        elif name == "analyze_latest_beam_run":
            self._summarize_latest_beam_run()
        elif name == "run_wavelength_scan" and hardware_allowed:
            self._on_wavelength_scan(skip_confirm=True)
        elif name == "run_wavelength_scan" and not hardware_allowed:
            self._show_error("Enable hardware control to run a wavelength scan.")
        elif name == "calibrate_efficiency":
            self._calibrate_efficiency()
        elif name == "load_scan_csv":
            path = intent.params.get("path")
            if path:
                self._load_scan_csv(path)
            else:
                self._file_load_scan_csv()
        elif name == "connect_stage" and hardware_allowed:
            ok = self._motion.connect_stage()
            if ok:
                self._log_action("K-Cube stage connected")
                self.show_tile("stage")
        elif name == "connect_stage" and not hardware_allowed:
            self._show_error("Enable hardware control to connect the stage.")
        elif name == "show_tile":
            tile_id = intent.params.get("tile_id", "camera")
            if tile_id in self._tiles:
                self.show_tile(tile_id)
                self._log_action(f"Opened tile: {tile_id}")
        elif name == "start_fft_monitor":
            self._fft_panel.set_monitoring(True)
        elif name == "stop_fft_monitor":
            self._fft_panel.set_monitoring(False)
        elif name == "jog_stage" and hardware_allowed:
            if not self._motion.connected:
                self._motion.connect_stage()
            self._motion.jog_mm(float(intent.params.get("delta_mm", 0.1)))
            self._log_action(f"Atria jog {float(intent.params.get('delta_mm', 0.1)):+.4f} mm")
        elif name == "go_safe_home" and hardware_allowed:
            self._motion.go_safe_home()
            self._log_action("Atria: go safe home")
        elif name == "mark_safe_home" and hardware_allowed:
            self._motion.mark_safe_home()
            self._log_action("Atria: mark safe home")
        elif name == "run_simulation":
            dur = intent.params.get("duration_sec")
            if dur is None:
                dur = DEFAULT_SIMULATION_DURATION_SEC
            self._start_simulation(float(dur), report_to_atria=True)
        elif name == "stop_simulation":
            self._stop_simulation()
            self._log_action("Atria: stop simulation")
        elif name == "results_statement":
            self._build_and_post_results_statement()
        elif name in ("jog_stage", "go_safe_home", "mark_safe_home") and not hardware_allowed:
            self._show_error("Enable hardware control to move the stage.")

