"""K-Cube stage wrapper with travel limits and safe-home recovery."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from core.config_store import AppConfig, StageLimits, load_config, save_config
from core.hardware_bridge import close_device, connect_stage


class MotionController(QObject):
    """Qt wrapper for one K-Cube stage with config-backed limits and safe home."""

    status = Signal(str)
    position_changed = Signal(float)
    error = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stage: Any | None = None
        self._cfg: AppConfig = load_config()
        self._active_index = 0

    @property
    def connected(self) -> bool:
        return self._stage is not None

    @property
    def limits(self) -> StageLimits:
        return self._cfg.stages[self._active_index]

    def reload_config(self) -> None:
        """Reload stage limits and safe-home fields from disk."""
        self._cfg = load_config()

    @property
    def active_index(self) -> int:
        return self._active_index

    def stages(self) -> list[StageLimits]:
        self._cfg = load_config()
        return list(self._cfg.stages)

    def set_active_index(self, index: int) -> None:
        """Select which configured stage row is active (disconnects if needed)."""
        self._cfg = load_config()
        if index < 0 or index >= len(self._cfg.stages):
            return
        if index == self._active_index:
            return
        was_connected = self._stage is not None
        if was_connected:
            self.disconnect()
        self._active_index = index
        self.status.emit(f"Active stage: {self.limits.name}")
        if was_connected:
            self.connect_stage()

    def connect_stage(self, serial: str | None = None) -> bool:
        """Connect the active stage and emit the current position in mm."""
        try:
            self._stage = connect_stage(serial or self.limits.serial)
            pos = self.get_position_mm()
            self.position_changed.emit(pos)
            self.status.emit(f"Stage connected at {pos:.4f} mm")
            return True
        except Exception as exc:
            self.error.emit(str(exc))
            return False

    def disconnect(self) -> None:
        """Close the stage handle and clear the connected flag."""
        close_device(self._stage)
        self._stage = None
        self.status.emit("Stage disconnected")

    def get_position_mm(self) -> float:
        """Return the current stage position in millimetres, or NaN if offline."""
        if self._stage is None:
            return float("nan")
        pos_m = float(self._stage.get_position())
        return pos_m * 1000.0

    def _clamp_target_mm(self, target_mm: float) -> float:
        lim = self.limits
        return float(max(lim.min_mm, min(lim.max_mm, target_mm)))

    def jog_mm(self, delta_mm: float) -> bool:
        """Move relative to the current position, clamped to jog and travel limits."""
        if self._stage is None:
            self.error.emit("Stage not connected")
            return False
        lim = self.limits
        delta = max(-lim.max_jog_mm, min(lim.max_jog_mm, delta_mm))
        target = self._clamp_target_mm(self.get_position_mm() + delta)
        return self.move_to_mm(target)

    def move_to_mm(self, target_mm: float) -> bool:
        """Absolute move in millimetres, clamped to configured min/max travel."""
        if self._stage is None:
            self.error.emit("Stage not connected")
            return False
        target = self._clamp_target_mm(target_mm)
        try:
            self._stage.move_to(target * 1e-3)
            self._stage.wait_move()
            pos = self.get_position_mm()
            self.position_changed.emit(pos)
            self.status.emit(f"Stage at {pos:.4f} mm")
            return True
        except Exception as exc:
            self.error.emit(str(exc))
            return False

    def mark_safe_home(self) -> None:
        """Save the current stage position as the crash-recovery safe home."""
        if self._stage is None:
            self.error.emit("Stage not connected")
            return
        self._cfg = load_config()
        self._cfg.safe_home_mm = self.get_position_mm()
        self._cfg.safe_home_stage_serial = self.limits.serial
        save_config(self._cfg)
        self.status.emit(f"Safe home saved at {self._cfg.safe_home_mm:.4f} mm")

    def go_safe_home(self) -> bool:
        """Move to the last saved safe-home position, if one exists."""
        self._cfg = load_config()
        if self._cfg.safe_home_mm is None:
            self.error.emit("No safe home position saved yet.")
            return False
        return self.move_to_mm(self._cfg.safe_home_mm)

    def update_limits(self, limits: StageLimits) -> None:
        """Persist updated travel and jog limits for the active stage index."""
        self._cfg = load_config()
        if self._active_index < len(self._cfg.stages):
            self._cfg.stages[self._active_index] = limits
        else:
            self._cfg.stages.append(limits)
        save_config(self._cfg)
        self.status.emit("Stage limits saved")

    def on_crash_recovery(self) -> None:
        """Attempt to return stage to safe home after abnormal exit."""
        self._cfg = load_config()
        if self._cfg.safe_home_mm is None:
            return
        if not self.connect_stage(self._cfg.safe_home_stage_serial):
            return
        self.go_safe_home()
