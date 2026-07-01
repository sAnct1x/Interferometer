"""ROI Snap Shot tile: frozen frame heatmap with draggable ROI and analysis actions."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from gui.glass_panel import GlassPanel, PentagonButton
from gui.widgets.camera_view import RoiMode, SnapshotRoiViewport


class RoiSnapshotPanel(GlassPanel):
    roi_changed = Signal(tuple)
    capture_requested = Signal()
    analyze_requested = Signal()
    wavelength_scan_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="ROI Snap Shot")
        self._snapshot: np.ndarray | None = None
        self._roi: tuple[int, int, int, int] = (636, 534, 101, 101)
        self._mode = RoiMode.BEAM

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        self._snapshot_viewport = SnapshotRoiViewport()
        self._snapshot_viewport.roi_changed.connect(self._on_viewport_roi_changed)
        layout.addWidget(self._snapshot_viewport, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        save_btn = PentagonButton("Save ROI", compact=True)
        save_btn.clicked.connect(self.capture_requested.emit)
        actions.addWidget(save_btn)
        scan_btn = PentagonButton("Scan wavelength", compact=True)
        scan_btn.clicked.connect(self.wavelength_scan_requested.emit)
        actions.addWidget(scan_btn)
        analyze_btn = PentagonButton("Analyze Beam", compact=True)
        analyze_btn.clicked.connect(self.analyze_requested.emit)
        actions.addWidget(analyze_btn)
        actions.addStretch()
        layout.addLayout(actions)

    def has_snapshot(self) -> bool:
        return self._snapshot is not None

    def set_roi(self, roi: tuple[int, int, int, int], mode: RoiMode | None = None) -> None:
        self._roi = roi
        if mode is not None:
            self._mode = mode
            self._snapshot_viewport.set_mode(mode)
        if self._snapshot is not None:
            self._snapshot_viewport.set_frame(self._snapshot, self._roi)

    def set_mode(self, mode: RoiMode) -> None:
        self._mode = mode
        self._snapshot_viewport.set_mode(mode)

    def current_roi(self) -> tuple[int, int, int, int]:
        if self._snapshot is not None:
            return self._snapshot_viewport.current_roi()
        return self._roi

    def current_mode(self) -> RoiMode:
        return self._mode

    def set_snapshot(
        self,
        frame: np.ndarray,
        roi: tuple[int, int, int, int],
        mode: RoiMode,
    ) -> None:
        self._snapshot = np.asarray(frame).copy()
        self._roi = roi
        self._mode = mode
        self._snapshot_viewport.set_mode(mode)
        self._snapshot_viewport.set_frame(self._snapshot, self._roi)

    def clear(self) -> None:
        self._snapshot = None
        self._snapshot_viewport.clear()

    def analysis_frame(self) -> np.ndarray | None:
        if self._snapshot is None:
            return None
        return self._snapshot.copy()

    def _on_viewport_roi_changed(self, roi: tuple[int, int, int, int]) -> None:
        self._roi = roi
        self.roi_changed.emit(roi)
