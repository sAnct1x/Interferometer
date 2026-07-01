"""FFT wavelength recovery from K-Cube scan CSV files."""

from __future__ import annotations

import sys
from pathlib import Path

from config import LASER_WAVELENGTH_NM, LEGACY_SCRIPTS_DIR


def recover_wavelength_from_csv(csv_path: Path) -> dict:
    """Run FFT wavelength recovery on a scan CSV."""
    if not csv_path.is_file():
        return {"error": f"Scan file not found: {csv_path}"}

    legacy = str(LEGACY_SCRIPTS_DIR)
    if legacy not in sys.path:
        sys.path.insert(0, legacy)

    try:
        import numpy as np

        from interferometer_acquire_analyze import (
            _pick_interferogram_fft_peak,
            detrend_signal,
            load_scan_csv,
        )

        pos, intensity, unit = load_scan_csv(csv_path)
        if len(pos) < 8:
            return {"error": "Too few scan points for wavelength analysis."}
        if unit != "mm":
            return {"error": "Scan must use mm units for wavelength recovery."}

        dx = np.diff(pos)
        dx_mean = float(np.mean(dx))
        if dx_mean == 0:
            return {"error": "All stage positions identical."}

        yp = detrend_signal(intensity, pos, "linear")
        fft_vals = np.fft.rfft(yp)
        power = np.abs(fft_vals) ** 2
        freqs = np.fft.rfftfreq(len(yp), d=abs(dx_mean))
        peak_idx, _, peak_warn = _pick_interferogram_fft_peak(
            freqs, power, unit=unit, peak_search_lambda_nm=(400.0, 900.0)
        )
        sigma_peak = float(freqs[peak_idx])
        if sigma_peak <= 0:
            return {"error": "Could not find valid FFT peak."}
        lambda_nm = 2.0 / sigma_peak * 1e6
        result = {
            "lambda_nm": float(lambda_nm),
            "spatial_freq_peak": sigma_peak,
            "csv_path": str(csv_path),
            "nominal_nm": LASER_WAVELENGTH_NM,
        }
        if peak_warn:
            result["warning"] = peak_warn
        return result
    except Exception as exc:
        return {"error": str(exc)}
