"""Live camera pipeline, snap workers, and pop-out tiles for the hub.

Thorlabs SDK access is serialized via TLCAM_LOCK in core.hardware_bridge.
Under CAMERA_LIVE_POLICY=single only the primary role streams continuously;
other roles are frozen snaps."""


from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import Qt, QTimer

from config import CAMERA_LIVE_POLICY, COUPLING_TARGET_PCT
from core.analytics.beam import roi_mean
from core.analytics.coupling import coupling_overlay, default_target_center
from core.analytics.efficiency import coupling_efficiency_percent, dual_camera_efficiency_percent
from core.camera_live_policy import LivePolicy, policy_summary, streaming_roles, thumb_roles
from core.camera_roles import ACTIVE_ROLES, CameraRole
from core.camera_worker import CameraWorker
from core.config_store import save_config
from core.hardware_bridge import list_cameras
from core.snap_worker import SnapWorker
from gui.widgets.camera_view import RoiMode


class DashboardCameraMixin:
    """Mixin extracted from Dashboard for maintainability."""


    def _on_live_feed_toggled(self, active: bool) -> None:
        # Prefer the guarded dashboard entry so Start Live Feed cannot hard-crash
        # the UI thread on a setup exception.
        if hasattr(self, "_toggle_live_feed"):
            self._toggle_live_feed(active)
            return
        if self._simulation_active:
            if not active:
                self._stop_simulation()
            return
        if active:
            self._start_camera()
        else:
            self._stop_camera()

    def _popped_roles(self) -> set[CameraRole]:
        return {r for r in ACTIVE_ROLES if self._camera_panel.is_popped(r)}

    def _live_roles(self) -> list[CameraRole]:
        """Roles that should hold an open worker for the current live-feed policy."""
        return streaming_roles(
            CAMERA_LIVE_POLICY,
            primary=self._camera_panel.primary_role(),
            popped=self._popped_roles(),
            cfg=self._cfg,
        )

    def _serial_for_role(self, role: CameraRole) -> str | None:
        slot = self._cfg.camera_by_role(role)
        if slot is not None and slot.serial:
            return slot.serial
        return self._role_actual_serial.get(role)

    def _show_role_standby(self, role: CameraRole) -> None:
        """Non-streaming role: keep frozen snap if we have one, else a short hint."""
        if role is CameraRole.FAR_FIELD:
            self._camera_panel.set_coupling_overlay(None, role)
        if self._camera_panel.role_frame(role) is not None:
            return
        self._camera_panel.show_role_status(
            role, f"{role.label}\n\nFrozen snap\n(promote for live)"
        )

    def _thumb_roles(self) -> list[CameraRole]:
        return thumb_roles(primary=self._camera_panel.primary_role(), cfg=self._cfg)

    def _reconcile_camera_workers(self, *, refresh_thumbs: bool = True) -> None:
        """Only the primary streams live; other roles become frozen snaps."""
        primary = self._camera_panel.primary_role()
        allowed = set(self._live_roles())

        # Exclusive USB: stop every non-primary worker first (keep last frame as snap).
        for role in ACTIVE_ROLES:
            if role not in allowed and self._role_live.get(role):
                self._stop_role_worker(role, keep_preview=True)
                self._show_role_standby(role)

        self._sync_camera_preview_rates()
        self._camera_live = True

        if refresh_thumbs:
            # Snap thumbs with exclusive USB, then open the primary live streamer.
            self._queue_thumb_snaps_then_live(primary)
        else:
            if not self._role_live.get(primary):
                self._start_role_worker(primary)
            self._refresh_status()

    def _queue_thumb_snaps_then_live(self, primary: CameraRole) -> None:
        """Start only the primary live streamer — never open a second TLCam here.

        Exclusive Image/Output snaps during Start Live Feed poisoned the Thorlabs
        SDK on this USB hub (hung ``Connecting…``, then native crash on Stop).
        Thumbs keep their last frame or a standby placeholder; use Snap Frame
        (which briefly pauses live) when a fresh thumb is needed.
        """
        self._camera_live = True
        self._live_primary_pending = None
        self._pending_thumb_snaps = []
        self._defer_screen_refit_until = time.time() + 5.0

        for role in ACTIVE_ROLES:
            if role != primary:
                # Drop any leftover non-primary worker before primary opens.
                if self._role_live.get(role):
                    self._stop_role_worker(role, keep_preview=True)
                self._show_role_standby(role)

        if not self._role_live.get(primary):
            self._start_role_worker(primary)
        self._sync_camera_preview_rates()
        self._refresh_status()

    def _start_primary_after_thumbs(self) -> None:
        """Compatibility entry: open primary after any leftover exclusive snaps."""
        primary = getattr(self, "_live_primary_pending", None) or self._camera_panel.primary_role()
        self._live_primary_pending = None
        self._pending_thumb_snaps = []
        if self._camera_live and not self._role_live.get(primary):
            self._start_role_worker(primary)
        self._sync_camera_preview_rates()
        self._refresh_status()
        for role in ACTIVE_ROLES:
            if role != primary:
                self._show_role_standby(role)

    def _advance_thumb_snap_queue(self) -> None:
        """Drain leftover exclusive snaps (manual / promote), then open primary."""
        if self._snap_worker is not None and self._snap_worker.isRunning():
            return
        if any(self._role_live.values()):
            for role in list(self._camera_workers):
                if self._role_live.get(role):
                    self._stop_role_worker(role, keep_preview=True)
        if not self._pending_thumb_snaps:
            if self._live_primary_pending is not None or self._camera_live:
                self._start_primary_after_thumbs()
            return
        role = self._pending_thumb_snaps.pop(0)
        self._grab_single_frame_for_role(role.value, from_thumb_queue=True)


    def _on_camera_settings_changed(self, settings: dict) -> None:
        role = CameraRole.coerce(settings.get("role", "far_field"))
        worker_settings = {k: v for k, v in settings.items() if k != "role"}
        worker = self._camera_workers.get(role)
        if worker is not None and worker.isRunning():
            worker.queue_settings(worker_settings)

    def _on_camera_settings_updated(self, settings: dict, role=None) -> None:
        role = CameraRole.FAR_FIELD if role is None else CameraRole.coerce(role)
        self._camera_panel.set_camera_settings(settings, role)
        exp_us = settings.get("exposure_us")
        if exp_us is not None:
            self._last_exp_us[role] = float(exp_us)
            if role == CameraRole.FAR_FIELD:
                self._update_telemetry(far_field_exposure_us=float(exp_us))
            elif role == CameraRole.OUTPUT:
                self._update_telemetry(output_exposure_us=float(exp_us))
        if role == CameraRole.FAR_FIELD:
            measured = settings.get("measured_fps")
            if measured is not None and measured > 0:
                self._update_telemetry(camera_measured_fps=float(measured))

    def _camera_exposure_label(self, role=CameraRole.FAR_FIELD) -> str:
        key = "far_field_exposure_us" if role == CameraRole.FAR_FIELD else "output_exposure_us"
        exp_us = self._telemetry.get(key)
        if exp_us is None:
            return "—"
        if exp_us >= 1000:
            return f"{exp_us / 1000:.2f} ms"
        return f"{exp_us:.0f} µs"

    def _far_field_status_label(self, status_override: str | None = None) -> str:
        slot = self._cfg.camera_by_role(CameraRole.FAR_FIELD)
        label = slot.label if slot else "Far Field"
        serial = slot.serial if (slot and slot.serial) else "No S/N"
        if status_override is not None:
            status = status_override
        elif self._simulation_active or self._sim2_camera_mode:
            status = "Simulated"
        elif self._role_live.get(CameraRole.FAR_FIELD):
            status = "Active"
        else:
            status = "Idle"
        exp = self._camera_exposure_label(CameraRole.FAR_FIELD)
        parts = [f"{label}", f"S/N {serial}", status]
        if exp != "—":
            parts.append(exp)
        return "  ·  ".join(parts)

    def _output_status_label(self) -> str:
        slot = self._cfg.camera_by_role(CameraRole.OUTPUT)
        if slot is None:
            return "—"
        label = slot.label
        serial = slot.serial if slot.serial else "No S/N"
        if self._sim2_camera_mode:
            status = "Simulated"
        elif self._role_live.get(CameraRole.OUTPUT):
            status = "Active"
        else:
            status = "Idle"
        exp = self._camera_exposure_label(CameraRole.OUTPUT)
        parts = [f"{label}", f"S/N {serial}", status]
        if exp != "—":
            parts.append(exp)
        return "  ·  ".join(parts)

    def _start_role_worker(self, role: CameraRole) -> bool:
        worker = self._camera_workers.get(role)
        if worker is not None and worker.isRunning():
            return False
        slot = self._cfg.camera_by_role(role)
        serial = slot.serial if slot else None
        if not serial:
            serial = self._pick_auto_serial(role)
        if not serial:
            self._camera_panel.show_role_error(
                role, "No camera serial assigned.\nPick a device in Cam:."
            )
            return False
        self._camera_panel.show_role_status(
            role, f"{role.label}\n\nConnecting to {serial}…"
        )
        worker = CameraWorker(serial, self)
        # Match USB/streaming mode before the thread opens the device.
        tier = self._camera_panel.preview_tier(role)
        worker.set_streaming_mode(tier in ("primary", "popout"))
        settings = self._camera_panel.stored_camera_settings(role)
        if settings.get("exposure_us") is not None:
            worker.queue_settings({"exposure_us": settings["exposure_us"]})
        # Ghost-beam paths are often much dimmer — borrow Far Field exposure when
        # Image/Output are still on the UI default until the operator tunes them.
        if role in (CameraRole.IMAGE, CameraRole.OUTPUT):
            ui_exp = float(settings.get("exposure_us") or 0)
            ff_exp = float(self._last_exp_us.get(CameraRole.FAR_FIELD, 0))
            if ff_exp > 0 and ui_exp <= 15_000:
                worker.queue_settings({"exposure_us": ff_exp})
        if settings.get("fps_auto") is not None:
            payload: dict = {"fps_auto": settings["fps_auto"]}
            if not settings.get("fps_auto") and settings.get("fps_hz"):
                payload["fps_hz"] = settings["fps_hz"]
            worker.queue_settings(payload)
        worker.frame_ready.connect(
            lambda f, rr=role, w=worker: self._on_role_frame(rr, f, w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.error.connect(lambda e, rr=role: self._on_role_camera_error(rr, e))
        if role == CameraRole.FAR_FIELD:
            worker.status.connect(self._on_camera_status)
        else:
            worker.status.connect(lambda s, rr=role: self._on_role_camera_status(rr, s))
        worker.connected.connect(lambda s, rr=role: self._on_role_camera_connected(rr, s))
        worker.settings_updated.connect(
            lambda s, rr=role: self._on_camera_settings_updated(s, rr)
        )
        worker.start()
        self._camera_workers[role] = worker
        self._role_live[role] = True
        self._camera_panel.set_camera_serial(role, serial)
        self._apply_preview_rate(role, worker)
        # Soft-fail if the SDK open hangs — keep the UI from sitting on Connecting forever.
        # Bench open+settle can take ~15–20s on a loaded USB hub; don't trip early.
        QTimer.singleShot(
            30_000,
            lambda rr=role, w=worker: self._watchdog_role_connect(rr, w),
        )
        return True

    def _watchdog_role_connect(self, role: CameraRole, worker: CameraWorker) -> None:
        """If a live worker never connected/delivered a frame, stop with a soft error."""
        if self._camera_workers.get(role) is not worker:
            return
        if not worker.isRunning():
            return
        if self._last_frame.get(role) is not None:
            return
        # Connected but still dark — give one more window for the first frame.
        if role in self._role_actual_serial:
            QTimer.singleShot(
                15_000,
                lambda rr=role, w=worker: self._watchdog_role_first_frame(rr, w),
            )
            return
        self._fail_role_connect(role, worker)

    def _watchdog_role_first_frame(self, role: CameraRole, worker: CameraWorker) -> None:
        if self._camera_workers.get(role) is not worker:
            return
        if not worker.isRunning():
            return
        if self._last_frame.get(role) is not None:
            return
        self._fail_role_connect(role, worker)

    def _fail_role_connect(self, role: CameraRole, worker: CameraWorker) -> None:
        self._stop_role_worker(role, keep_preview=True)
        self._camera_panel.show_role_error(
            role,
            "Timed out connecting.\nClose ThorCam GUI, unplug/replug USB, retry.",
        )
        still_live = any(self._role_live.values())
        self._camera_live = still_live
        if not still_live:
            self._camera_panel.set_live_active(False)
        self._toast.show_message(
            f"{role.label}: connect timed out (SDK busy or USB conflict)",
            kind="error",
        )
        self._refresh_status()

    def _on_primary_camera_role_changed(self, _role_value: str) -> None:
        if self._camera_live and not self._simulation_active and not self._sim2_camera_mode:
            # Demoted camera keeps its last frame as the frozen thumb; new primary goes live.
            self._reconcile_camera_workers(refresh_thumbs=True)
        else:
            self._sync_camera_preview_rates()

    def _apply_preview_rate(self, role: CameraRole, worker: CameraWorker | None = None) -> None:
        """Primary streams continuously; thumbnails grab one frame periodically."""
        from config import CAMERA_POPOUT_FPS, CAMERA_THUMB_PERIOD_S, CAMERA_UI_FPS

        worker = worker or self._camera_workers.get(role)
        if worker is None or not worker.isRunning():
            return
        tier = self._camera_panel.preview_tier(role)
        continuous = tier in ("primary", "popout")
        worker.set_streaming_mode(continuous)
        if tier == "primary":
            worker.set_emit_interval(1.0 / max(1.0, float(CAMERA_UI_FPS)))
        elif tier == "popout":
            worker.set_emit_interval(1.0 / max(1.0, float(CAMERA_POPOUT_FPS)))
        else:
            worker.set_emit_interval(float(CAMERA_THUMB_PERIOD_S))

    def _sync_camera_preview_rates(self) -> None:
        """Recompute emit intervals after promote / pop-out / pop-in."""
        for role in ACTIVE_ROLES:
            self._apply_preview_rate(role)

    def _pick_auto_serial(self, role: CameraRole) -> str | None:
        """Best-effort pick for a role left on "Auto": skip serials other roles already
        claim, either explicitly configured or already connected this session."""
        taken: set[str] = set()
        for other_role in ACTIVE_ROLES:
            if other_role == role:
                continue
            other_slot = self._cfg.camera_by_role(other_role)
            if other_slot and other_slot.serial:
                taken.add(other_slot.serial)
            actual = self._role_actual_serial.get(other_role)
            if actual:
                taken.add(actual)
        try:
            candidates = [s for s in list_cameras() if s not in taken]
        except Exception:
            candidates = []
        return candidates[0] if candidates else None

    def _on_role_camera_connected(self, role: CameraRole, serial: str) -> None:
        """Record the serial a role's worker actually connected to.

        Do not push placeholder strings like ``Thorcam`` into the Cam: picker —
        that overwrote the lab assignment and left roles looking unassigned.
        """
        cleaned = (serial or "").strip()
        if cleaned and cleaned.lower() != "thorcam":
            self._role_actual_serial[role] = cleaned
            slot = self._cfg.camera_by_role(role)
            # Only update the picker when this matches (or fills) the configured slot.
            if slot is not None and (not slot.serial or slot.serial == cleaned):
                if slot.serial != cleaned:
                    slot.serial = cleaned
                    self._cfg.camera_roles[role.value] = cleaned
                    save_config(self._cfg)
                self._camera_panel.set_camera_serial(role, cleaned)
        self._refresh_status(camera_far_field="Active")

    def _start_camera(self) -> None:
        if self._simulation_active:
            self._stop_simulation()
        if self._sim2_camera_mode:
            self._stop_simulation_two()
        # Production rule: snap the two thumbnails, then live-stream only the primary.
        self._pending_camera_roles = []
        self._camera_live = True
        try:
            self._toast.show_message(policy_summary(CAMERA_LIVE_POLICY), kind="info")
        except Exception:
            pass
        for role in list(self._camera_workers):
            if self._role_live.get(role):
                self._stop_role_worker(role, keep_preview=True)
        self._reconcile_camera_workers(refresh_thumbs=True)

    def _start_next_pending_camera(self) -> None:
        pending = getattr(self, "_pending_camera_roles", None)
        if not pending:
            if any(self._role_live.values()):
                self._camera_live = True
                self._defer_screen_refit_until = time.time() + 5.0
                self._sync_camera_preview_rates()
                for role in ACTIVE_ROLES:
                    if role not in set(self._live_roles()):
                        self._show_role_standby(role)
                self._refresh_status()
            return
        role = pending.pop(0)
        started = self._start_role_worker(role)
        if not started:
            # Skip to the next role immediately.
            QTimer.singleShot(0, self._start_next_pending_camera)
            return
        # Stagger opens when multiple roles are allowed (dual / all policies).
        delay = 900 if len(getattr(self, "_pending_camera_roles", [])) > 0 else 0
        QTimer.singleShot(delay, self._start_next_pending_camera)

    def _stop_role_worker(self, role: CameraRole, *, keep_preview: bool = False) -> None:
        """Stop and release a single role's camera worker, if one is running."""
        worker = self._camera_workers.get(role)
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass
            # Never QThread.terminate() — that corrupts the Thorlabs SDK process state.
            if not worker.wait(5000):
                try:
                    worker.frame_ready.disconnect()
                except Exception:
                    pass
                try:
                    worker.error.disconnect()
                except Exception:
                    pass
            self._camera_workers[role] = None
        self._role_live[role] = False
        if not keep_preview:
            self._last_frame[role] = None
        elif role is CameraRole.FAR_FIELD:
            self._camera_panel.set_coupling_overlay(None, role)
        self._role_display_last_t[role] = 0.0
        self._role_actual_serial.pop(role, None)

    def _stop_camera(self) -> None:
        self._pending_camera_roles = []
        self._pending_thumb_snaps = []
        self._live_primary_pending = None
        self._resume_primary_after_thumbs = False
        self._auto_snap_roles.clear()
        snap = getattr(self, "_snap_worker", None)
        if snap is not None and snap.isRunning():
            # Let the in-flight exclusive snap finish so TLCAM_LOCK is released cleanly.
            snap.wait(3000)
        for role in list(self._camera_workers):
            self._stop_role_worker(role)
        if self._simulation_active:
            return
        self._camera_live = False
        self._live_display_last_t = 0.0
        self._last_frame_processed_t = 0.0
        self._live_analytics_last_t = 0.0
        self._last_live_overlay = None
        self._camera_panel.show_idle()
        self._camera_panel.set_coupling_overlay(None)
        self._beam_panel.reset()
        self._efficiency_panel.reset()
        self._trend_panel.reset()
        self._fft_panel.reset()
        self._refresh_status(camera_far_field="Idle")
        self._update_telemetry(beam_waist_um=None, efficiency_pct=None, status="Camera off")

    def _on_camera_error(self, message: str) -> None:
        """Legacy single-feed error path (Simulation #1 / snap helpers)."""
        self._stop_camera()
        self._camera_panel.set_live_active(False)
        self._show_error(message)

    def _on_role_camera_error(self, role: CameraRole, message: str) -> None:
        """Stop only the failing role so the other two live feeds keep running."""
        self._stop_role_worker(role)
        self._camera_panel.show_role_error(role, message)
        still_live = any(self._role_live.values())
        self._camera_live = still_live
        if not still_live:
            self._camera_panel.set_live_active(False)
        self._refresh_status()
        self._toast.show_message(f"{role.label}: {message}", kind="error")
        self._log_action(f"{role.label} camera error: {message}")

    def _on_role_camera_status(self, role: CameraRole, status: str) -> None:
        # Once real frames are flowing for this role, never overwrite the live
        # image with a status message (that would blank the feed).
        if self._last_frame.get(role) is not None:
            return
        s = status.lower()
        slot = self._cfg.camera_by_role(role)
        serial = slot.serial if slot and slot.serial else ""
        if "connecting" in s:
            detail = f"Connecting to {serial}…" if serial else status
            self._camera_panel.show_role_status(role, f"{role.label}\n\n{detail}")
        elif "no frames" in s:
            self._camera_panel.show_role_status(role, f"{role.label}\n\n{status}")
            # Live stream connected but sensor silent — fall back to an exclusive
            # single-frame grab (same path as Snap Frame) once per role per session.
            if (
                role == self._camera_panel.primary_role()
                and role not in self._auto_snap_roles
                and (self._snap_worker is None or not self._snap_worker.isRunning())
            ):
                self._auto_snap_roles.add(role)
                QTimer.singleShot(400, lambda rv=role.value: self._grab_single_frame_for_role(rv))
        elif "active" in s:
            # Connect succeeded; distinguish this from a connect hang while we
            # wait for the first frame to land.
            where = f" to {serial}" if serial else ""
            self._camera_panel.show_role_status(
                role, f"{role.label}\n\nConnected{where}\nWaiting for frames…"
            )

    def _on_camera_status(self, status: str) -> None:
        self._update_telemetry(status=status)
        s = status.lower()
        if "active" in s:
            self._refresh_status(camera_far_field="Active")
        if "connecting" in s or "no frames" in s or "active" in s:
            self._on_role_camera_status(CameraRole.FAR_FIELD, status)

    def _on_frame(self, frame: np.ndarray) -> None:
        # Far Field entry point (also used by Simulation #1's single feed).
        try:
            self._last_frame[CameraRole.FAR_FIELD] = frame
            # Cap main-thread processing at ~12 FPS regardless of camera hardware rate.
            now = time.time()
            if now - self._last_frame_processed_t < (1.0 / 12.0):
                # Still refresh η — dual-cam needs FF even when display is throttled.
                self._compute_live_efficiency()
                return
            self._last_frame_processed_t = now
            self._process_frame(frame, source_role=CameraRole.FAR_FIELD)
        finally:
            # SimulationWorker uses the same backpressure contract as CameraWorker.
            worker = getattr(self, "_simulation_worker", None)
            if worker is not None and hasattr(worker, "acknowledge_frame"):
                worker.acknowledge_frame()

    def _on_role_frame(self, role: CameraRole, frame: np.ndarray, worker=None) -> None:
        try:
            if role == CameraRole.FAR_FIELD:
                self._on_frame(frame)
                return
            self._last_frame[role] = frame
            # Always cache so promote/η can read the buffer even when we skip a redraw.
            self._camera_panel.set_role_frame(role, frame, repaint=False)
            # Dual-cam η is cheap (two ROI means). Do not hide it behind the 12 Hz
            # display throttle — that left Beam Efficiency stuck on "Need Output"
            # while Output was already streaming.
            if role in (CameraRole.OUTPUT, CameraRole.FAR_FIELD):
                self._compute_live_efficiency()
            now = time.time()
            if now - self._role_display_last_t.get(role, 0.0) < (1.0 / 12.0):
                return
            self._role_display_last_t[role] = now
            self._camera_panel.set_role_frame(role, frame, repaint=True)
            # Primary non-FF feeds (e.g. Output promoted) need the same live path
            # for telemetry, but skip Far Field coupling overlay.
            if role == self._camera_panel.primary_role():
                self._process_frame(frame, source_role=role)
        finally:
            # Let the worker emit again (coalesced latest frame). Without this,
            # QueuedConnection piles up full-res arrays and freezes the UI.
            if worker is not None:
                worker.acknowledge_frame()

    def _compute_live_efficiency(self) -> None:
        """Live η from Far Field + Output (live or snap), ~4 Hz.

        On first dual-frame after live start with no saved baseline, auto-arms the
        reference so the meter moves immediately. Lab target is ~90% (see
        ``COUPLING_TARGET_PCT``); use Recalibrate when coupling looks ideal.
        """
        if not self._is_tile_open("efficiency"):
            return
        now = time.time()
        if now - getattr(self, "_efficiency_last_t", 0.0) < 0.25:
            return
        self._efficiency_last_t = now

        try:
            ff = self._last_frame.get(CameraRole.FAR_FIELD)
            out = self._last_frame.get(CameraRole.OUTPUT)
            if ff is None:
                ff = self._camera_panel.role_frame(CameraRole.FAR_FIELD)
                if ff is not None:
                    self._last_frame[CameraRole.FAR_FIELD] = ff
            if out is None:
                out = self._camera_panel.role_frame(CameraRole.OUTPUT)
                if out is not None:
                    self._last_frame[CameraRole.OUTPUT] = out

            if ff is None or out is None:
                missing = []
                if ff is None:
                    missing.append("Far Field")
                if out is None:
                    missing.append("Output")
                self._efficiency_panel.set_efficiency(
                    None,
                    detail=(
                        f"Waiting for {' + '.join(missing)} — "
                        "Start Live Feed, or promote/Snap the missing camera."
                    ),
                )
                return

            roi_ff = self._cfg.beam_roi
            out_slot = self._cfg.camera_by_role(CameraRole.OUTPUT)
            roi_out = out_slot.beam_roi if out_slot else roi_ff
            mean_in = float(roi_mean(ff, roi_ff))
            mean_out = float(roi_mean(out, roi_out))
            exp_in = max(self._last_exp_us.get(CameraRole.FAR_FIELD, 1.0), 1.0)
            exp_out = max(self._last_exp_us.get(CameraRole.OUTPUT, 1.0), 1.0)
            if mean_in <= 0 or exp_in <= 0 or exp_out <= 0:
                self._efficiency_panel.set_efficiency(
                    None,
                    detail=(
                        f"FF {mean_in:.0f} cts @ {exp_in:.0f} µs  |  "
                        f"Out {mean_out:.0f} cts @ {exp_out:.0f} µs  ·  "
                        "Far Field ROI mean is ~0 — check beam / ROI."
                    ),
                )
                return

            ratio = (mean_out / exp_out) / (mean_in / exp_in)
            ref = self._cfg.efficiency_reference_ratio
            auto_note = ""
            if ref is None or ref <= 0:
                # Arm baseline so "good starting alignment" reads near the lab target.
                target = max(float(COUPLING_TARGET_PCT), 1.0)
                ref = ratio * (100.0 / target)
                self._cfg.efficiency_reference_ratio = ref
                save_config(self._cfg)
                auto_note = f"  ·  auto-baseline → ~{target:.0f}% now"
                self._log_action(
                    f"η auto-baselined at ~{target:.0f}% (ratio={ref:.4g})"
                )

            eta_pct = dual_camera_efficiency_percent(
                mean_in, mean_out, exp_in, exp_out, ref
            )
            out_live = bool(self._role_live.get(CameraRole.OUTPUT))
            ff_live = bool(self._role_live.get(CameraRole.FAR_FIELD))
            detail = (
                f"FF ({'live' if ff_live else 'snap'}): {mean_in:.0f} cts @ {exp_in:.0f} µs  |  "
                f"Out ({'live' if out_live else 'snap'}): {mean_out:.0f} cts @ {exp_out:.0f} µs  |  "
                f"target {COUPLING_TARGET_PCT:.0f}%"
                f"{auto_note}"
            )
            self._efficiency_panel.set_efficiency(eta_pct, detail=detail)
            if eta_pct is not None:
                self._update_telemetry(efficiency_pct=eta_pct)
                if self._is_tile_open("trends"):
                    self._trend_panel.append_sample(eta_pct=eta_pct)
        except Exception as exc:
            self._efficiency_panel.set_efficiency(
                None, detail=f"η error: {exc}"
            )

    def _on_camera_label_changed(self, role_value: str, label: str) -> None:
        slot = self._cfg.camera_by_role(role_value)
        if slot is not None:
            slot.label = label
            save_config(self._cfg)

    def _refresh_available_cameras(self) -> None:
        """Rescan connected Thorcams and refresh every role's device picker."""
        from core.config_store import apply_bench_camera_serials

        # Keep the lab map pinned even if an earlier session saved Auto/nulls.
        if apply_bench_camera_serials(self._cfg):
            save_config(self._cfg)
            for slot in self._cfg.cameras:
                self._camera_panel.set_camera_label(slot.role, slot.label)
                if slot.serial:
                    self._camera_panel.set_camera_serial(slot.role, slot.serial)
        try:
            serials = list_cameras()
        except Exception:
            serials = []
        # Always advertise the three bench serials so pickers stay stable even if
        # a camera is briefly unplugged or the SDK enumeration is flaky.
        from config import CAMERA_ROLE_SERIALS

        ordered: list[str] = []
        seen: set[str] = set()
        for sn in CAMERA_ROLE_SERIALS.values():
            if sn and sn not in seen:
                ordered.append(sn)
                seen.add(sn)
        for sn in serials:
            if sn and sn not in seen:
                ordered.append(sn)
                seen.add(sn)
        self._camera_panel.set_available_cameras(ordered)

    def _on_camera_selection_changed(self, role_value: str, serial: str) -> None:
        """User picked a specific physical camera (by serial) for a bench role."""
        role = CameraRole.coerce(role_value)
        serial = (serial or "").strip() or None
        if serial and serial.lower() == "thorcam":
            serial = None
        slot = self._cfg.camera_by_role(role)
        if slot is None:
            return
        previous = slot.serial
        # If another role already owns this serial, swap instead of clearing it
        # to Auto — clearing left Image/Output on "first found" and caused fights.
        if serial:
            for other_role in ACTIVE_ROLES:
                if other_role == role:
                    continue
                other_slot = self._cfg.camera_by_role(other_role)
                if other_slot is not None and other_slot.serial == serial:
                    other_slot.serial = previous
                    self._cfg.camera_roles[other_role.value] = previous
                    self._camera_panel.set_camera_serial(other_role, previous or "")
                    break
        slot.serial = serial
        self._cfg.camera_roles[role.value] = serial
        save_config(self._cfg)
        self._camera_panel.set_camera_serial(role, serial or "")
        # Reconnect on the fly only if this role is in the current live policy.
        if self._role_live.get(role) and not self._simulation_active and not self._sim2_camera_mode:
            self._stop_role_worker(role)
            if role in self._live_roles():
                self._start_role_worker(role)
        elif self._camera_live:
            self._reconcile_camera_workers()
        self._refresh_status()

    # --- Camera pop-out tiles (tear a feed into its own draggable tile) ---

    def _popout_camera(self, role_value: str) -> None:
        role = CameraRole.coerce(role_value)
        if self._camera_panel.is_popped(role):
            self._return_popout_pane(role)
            return
        tile_id = self.POPOUT_TILE_IDS.get(role.value)
        if tile_id is None:
            return
        pane = self._camera_panel.detach_pane(role)
        if pane is None:
            return
        self._popout_panels[tile_id].set_pane(pane)
        self.show_tile(tile_id)
        if self._camera_live:
            self._reconcile_camera_workers()
        else:
            self._sync_camera_preview_rates()
        self._log_action(f"{role.label} camera popped out to its own tile")

    def _popin_camera(self, role_value: str) -> None:
        self._return_popout_pane(CameraRole.coerce(role_value))

    def _return_popout_pane(self, role: CameraRole) -> None:
        tile_id = self.POPOUT_TILE_IDS.get(role.value)
        if tile_id is None or not self._camera_panel.is_popped(role):
            return
        self._popout_panels[tile_id].take_pane()
        self._camera_panel.attach_pane(role)
        self.hide_tile(tile_id)
        if self._camera_live:
            self._reconcile_camera_workers()
        else:
            self._sync_camera_preview_rates()

