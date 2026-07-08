"""Optics of the wedge fiber-coupling bench, reduced to what the cameras see.

The main beam folds off Mirror 5 (piezo tip/tilt) and hits the wedge near the
fiber. The wedge splits it three ways:

* Far Field (reflected ghost)  - moves on the sensor as Mirror 5 tilts.
* Fiber (transmitted)          - coupling depends on how well the tilt centres
                                 the beam on the 450 µm bore; the Output camera
                                 brightness tracks that coupling.
* Image / Ghost 2              - optics pending mentor spec; rendered as a stable
                                 placeholder so the tile is not blank.

Mirror-5 tilt is the only actuated degree of freedom. A built-in misalignment
(`base_offset_px`) is what the PID must cancel; at the tilt that cancels it the
beam sits on the fiber centre and coupling peaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from config import CAMERA_ADC_BITS, PIXEL_SIZE_UM, SENSOR_SIZE_PX
from core.camera_roles import CameraRole

# CS165CU has a 10-bit ADC, so real frames top out at 1023 counts.
_ADC_MAX = float(2 ** CAMERA_ADC_BITS - 1)

# Beam deflection is twice the mirror tilt; over the arm length that becomes a
# sensor displacement. Precomputed px-per-microradian gain for a 500 mm arm.
_ARM_MM = 500.0
_PX_PER_URAD = 2.0 * 1e-6 * _ARM_MM * 1000.0 / PIXEL_SIZE_UM  # ~0.29 px/µrad


@dataclass
class BenchScenario:
    """Fixed disturbances the controller must overcome."""

    # Built-in misalignment (px) the piezo tilt must cancel to couple. Kept
    # inside the tilt authority so a solution exists within 0..75 V.
    base_offset_px: tuple[float, float] = (-34.0, 48.0)
    drift_px_per_s: tuple[float, float] = (0.0, 0.0)  # linear walk-off (usually 0)
    drift_amp_px: tuple[float, float] = (0.0, 0.0)    # bounded thermal sway amplitude
    drift_period_s: float = 40.0                      # thermal sway period
    noise_px: float = 1.2                             # per-frame centroid jitter
    waist_um: float = 290.0                           # 1/e^2 diameter at the fiber
    couple_sigma_px: float = 42.0                     # coupling falls off over this
    peak_counts: float = 900.0                        # far-field peak (10-bit, <1023)
    background_counts: float = 18.0                    # dark/ambient floor
    read_noise_counts: float = 0.8                     # CS165CU read noise, in counts
    seed: int | None = 12345


@dataclass
class BeamSpot:
    """Parameters of one rendered Gaussian spot."""

    center_px: tuple[float, float]
    sigma_px: float
    amplitude: float


@dataclass
class _RoleGeometry:
    center_px: tuple[float, float]
    tilt_gain: float  # px displacement per µrad of Mirror-5 tilt (0 = insensitive)


class BenchModel:
    """Maps Mirror-5 tilt to per-camera spots and fiber coupling."""

    def __init__(
        self,
        scenario: BenchScenario | None = None,
        *,
        sensor_size: tuple[int, int] = SENSOR_SIZE_PX,
        pixel_um: float = PIXEL_SIZE_UM,
    ) -> None:
        self.scenario = scenario or BenchScenario()
        self.width, self.height = sensor_size
        self.pixel_um = pixel_um
        self._rng = np.random.default_rng(self.scenario.seed)
        self._grid_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
        cx, cy = self.width / 2.0, self.height / 2.0
        # Far Field tracks tilt; Image/Output sit near centre and barely move.
        self._geometry = {
            CameraRole.FAR_FIELD: _RoleGeometry((cx, cy), _PX_PER_URAD),
            CameraRole.IMAGE: _RoleGeometry((cx, cy), 0.15 * _PX_PER_URAD),
            CameraRole.OUTPUT: _RoleGeometry((cx, cy), 0.0),
        }

    # -- geometry -----------------------------------------------------------
    def _sigma_px(self) -> float:
        # 1/e^2 diameter = 4 sigma for intensity exp(-r^2/2sigma^2).
        return (self.scenario.waist_um / self.pixel_um) / 4.0

    def _offset_px(self, tilt_urad: tuple[float, float], t: float) -> tuple[float, float]:
        """Residual beam offset at the fiber after tilt cancels base misalignment."""
        s = self.scenario
        bx, by = s.base_offset_px
        dxr, dyr = s.drift_px_per_s
        ax, ay = s.drift_amp_px
        w = 2.0 * np.pi / max(s.drift_period_s, 1e-3)
        sway_x = ax * np.sin(w * t)
        sway_y = ay * np.sin(0.83 * w * t)  # incommensurate so it never fully repeats
        ox = bx + dxr * t + sway_x + _PX_PER_URAD * tilt_urad[0]
        oy = by + dyr * t + sway_y + _PX_PER_URAD * tilt_urad[1]
        return ox, oy

    def coupling_fraction(self, tilt_urad: tuple[float, float], t: float = 0.0) -> float:
        """Fraction (0..1) of light coupled into the fiber for the current tilt."""
        ox, oy = self._offset_px(tilt_urad, t)
        sig = self.scenario.couple_sigma_px
        return float(np.exp(-(ox * ox + oy * oy) / (2.0 * sig * sig)))

    def centroid_error_px(self, tilt_urad: tuple[float, float], t: float = 0.0) -> tuple[float, float]:
        """Beam centroid error vector at the fiber (target is 0,0)."""
        return self._offset_px(tilt_urad, t)

    # -- per-role spots -----------------------------------------------------
    def role_spot(self, role: CameraRole, tilt_urad: tuple[float, float], t: float = 0.0) -> BeamSpot:
        geo = self._geometry[role]
        sig = self._sigma_px()
        jitter = self.scenario.noise_px
        nx = float(self._rng.normal(0.0, jitter)) if jitter > 0 else 0.0
        ny = float(self._rng.normal(0.0, jitter)) if jitter > 0 else 0.0

        if role is CameraRole.OUTPUT:
            # Output brightness tracks coupling; spot stays put (fiber near-field).
            frac = self.coupling_fraction(tilt_urad, t)
            amp = self.scenario.peak_counts * max(frac, 0.0)
            return BeamSpot((geo.center_px[0] + nx, geo.center_px[1] + ny), sig * 1.1, amp)

        cx = geo.center_px[0] + geo.tilt_gain * tilt_urad[0] + self.scenario.base_offset_px[0] + nx
        cy = geo.center_px[1] + geo.tilt_gain * tilt_urad[1] + self.scenario.base_offset_px[1] + ny
        amp = self.scenario.peak_counts
        if role is CameraRole.IMAGE:
            amp *= 0.6  # dimmer ghost; slightly defocused
            sig *= 1.4
        return BeamSpot((cx, cy), sig, amp)

    def render(self, role: CameraRole, tilt_urad: tuple[float, float], t: float = 0.0, *, scale: float = 1.0) -> np.ndarray:
        """Render a float32 frame for one camera role.

        ``scale`` < 1 renders a downscaled frame (all geometry scaled to match)
        for smooth live display; ``scale`` = 1 is the full 1440x1080 sensor used
        by analytics and tests.
        """
        spot = self.role_spot(role, tilt_urad, t)
        return self._render_spot(spot, scale)

    def _grid(self, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
        key = (w, h)
        grid = self._grid_cache.get(key)
        if grid is None:
            grid = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
            self._grid_cache[key] = grid
        return grid

    def _render_spot(self, spot: BeamSpot, scale: float = 1.0) -> np.ndarray:
        w = max(1, int(round(self.width * scale)))
        h = max(1, int(round(self.height * scale)))
        xx, yy = self._grid(w, h)
        cx = spot.center_px[0] * scale
        cy = spot.center_px[1] * scale
        sig = max(spot.sigma_px * scale, 0.8)
        beam = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sig * sig))
        frame = beam * np.float32(spot.amplitude) + np.float32(self.scenario.background_counts)
        rn = self.scenario.read_noise_counts
        if rn > 0:
            frame = frame + self._rng.normal(0.0, rn, size=frame.shape).astype(np.float32)
        np.clip(frame, 0.0, _ADC_MAX, out=frame)
        return frame.astype(np.float32, copy=False)

    def reset(self) -> None:
        self._rng = np.random.default_rng(self.scenario.seed)
        self._grid_cache.clear()
