"""Camera-based coupling efficiency proxies (single and dual camera)."""

from __future__ import annotations


def coupling_efficiency_percent(current_mean: float, reference_mean: float) -> float | None:
    """Single-camera η: current ROI mean as a fraction of the calibrated reference mean."""
    if reference_mean <= 0 or not _finite(current_mean):
        return None
    eta = 100.0 * current_mean / reference_mean
    return float(min(max(eta, 0.0), 100.0))


def dual_camera_efficiency_percent(
    mean_input: float,
    mean_output: float,
    exp_input_us: float,
    exp_output_us: float,
    reference_ratio: float | None,
) -> float | None:
    """Two-camera η: (mean_out / exp_out) / (mean_in / exp_in) vs calibrated reference.

    Normalising each mean by its camera's exposure time makes the comparison valid even
    when the two cameras run at different integration periods. Returns ``None`` until
    ``reference_ratio`` is set via "Set as η=100%".
    """
    if not (_finite(mean_input) and _finite(mean_output)):
        return None
    if mean_input <= 0 or exp_input_us <= 0 or exp_output_us <= 0:
        return None
    ratio = (mean_output / exp_output_us) / (mean_input / exp_input_us)
    if reference_ratio is None or reference_ratio <= 0:
        return None
    eta = 100.0 * ratio / reference_ratio
    return float(min(max(eta, 0.0), 200.0))


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")
