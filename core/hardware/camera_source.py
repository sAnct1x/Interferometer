"""Interface for a single camera feed, real or simulated.

A ``CameraSource`` yields frames in the same format the analytics expect: a 2D
mono ``np.ndarray`` or an ``(H, W, 3)`` color array (see
``core/camera_worker.py``). The real Thorcam path and the Simulation #2 synthetic
feed both implement this so the dashboard can bind either to a camera role.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from core.camera_roles import CameraRole


class CameraSource(ABC):
    """One diagnostic camera bound to a bench role."""

    def __init__(self, role: CameraRole) -> None:
        self._role = role

    @property
    def role(self) -> CameraRole:
        """Bench role this feed plays (Far Field / Image / Output)."""
        return self._role

    @abstractmethod
    def start(self) -> None:
        """Begin acquisition (open the device, or arm the simulator)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop acquisition and release resources."""

    @abstractmethod
    def read_frame(self) -> np.ndarray | None:
        """Return the newest frame, or ``None`` if none is ready yet."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Whether the source is currently acquiring."""
