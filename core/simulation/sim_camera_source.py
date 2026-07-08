"""Simulated camera feed bound to a bench role, backed by a shared SimBench.

Implements the ``CameraSource`` interface so the dashboard can treat a synthetic
feed exactly like a real Thorcam. All three role sources share one ``SimBench``,
so a piezo move made through the simulated driver shows up in every feed at once.
"""

from __future__ import annotations

import numpy as np

from core.camera_roles import CameraRole
from core.hardware.camera_source import CameraSource
from core.simulation.sim_bench import SimBench


class SimCameraSource(CameraSource):
    """One synthetic camera feed for a given role."""

    def __init__(self, role: CameraRole, bench: SimBench) -> None:
        super().__init__(role)
        self._bench = bench
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def read_frame(self) -> np.ndarray | None:
        if not self._running:
            return None
        return self._bench.render(self.role)
