"""Build Atria chat summaries after a timed bench simulation."""

from __future__ import annotations

from typing import Any

from config import BEAM_WAIST_TARGET_UM


def _fmt_stats(stats: dict[str, Any] | None, unit: str, decimals: int = 1) -> str:
    if stats is None or stats.get("n", 0) == 0:
        return "no samples"
    mean = stats["mean"]
    lo = stats["min"]
    hi = stats["max"]
    last = stats["last"]
    n = stats["n"]
    if decimals == 0:
        return (
            f"mean {mean:.0f} {unit} (min {lo:.0f}–max {hi:.0f}), "
            f"final {last:.0f} {unit} · {n} samples"
        )
    return (
        f"mean {mean:.{decimals}f} {unit} (min {lo:.{decimals}f}–max {hi:.{decimals}f}), "
        f"final {last:.{decimals}f} {unit} · {n} samples"
    )


def format_simulation_report(
    *,
    planned_sec: float | None,
    trend_summary: dict[str, Any],
    beam_result: dict[str, Any] | None,
    coupling_overlay: dict[str, Any] | None,
    fft_peak_hz: float | None,
    fft_rate_hz: float | None,
) -> str:
    """Multi-line summary for Atria chat after simulation stops."""
    dur = float(trend_summary.get("duration_s", 0.0))
    lines: list[str] = ["SIMULATION COMPLETE"]

    if planned_sec is not None and planned_sec > 0:
        lines.append(f"Ran {dur:.1f} s (planned {planned_sec:.0f} s).")
    else:
        lines.append(f"Ran {dur:.1f} s.")

    target_lo, target_hi = BEAM_WAIST_TARGET_UM
    lines.append(f"Coupling η: {_fmt_stats(trend_summary.get("eta"), "%", 1)}")
    lines.append(f"Beam waist w₀: {_fmt_stats(trend_summary.get("w0"), "µm", 1)}")
    lines.append(f"w₀ target band: {target_lo:.0f}–{target_hi:.0f} µm")

    if beam_result is not None:
        w0 = beam_result.get("one_over_e2_avg_um")
        m2 = beam_result.get("m2")
        fx = beam_result.get("fwhm_x_um")
        fy = beam_result.get("fwhm_y_um")
        if w0 is not None and w0 == w0:
            lines.append(f"Final frame w₀ (1/e² avg): {float(w0):.1f} µm")
        if m2 is not None and m2 == m2:
            lines.append(f"M² proxy: {float(m2):.2f}")
        if fx is not None and fx == fx and fy is not None and fy == fy:
            lines.append(f"FWHM: X {float(fx):.1f} µm · Y {float(fy):.1f} µm")

    if coupling_overlay is not None:
        err_um = coupling_overlay.get("error_um")
        err_ang = coupling_overlay.get("error_angle_deg")
        if err_um is not None and err_um == err_um:
            ang_txt = f"{float(err_ang):.0f}°" if err_ang is not None and err_ang == err_ang else "—"
            lines.append(
                f"Coupling overlay: Δ {float(err_um):.1f} µm · angle {ang_txt}"
            )

    if fft_peak_hz is not None and fft_peak_hz > 0:
        rate_txt = f"{fft_rate_hz:.1f} Hz" if fft_rate_hz and fft_rate_hz > 0 else "—"
        lines.append(f"FFT peak tone: {fft_peak_hz:.2f} Hz (sample rate {rate_txt})")
    else:
        lines.append("FFT: insufficient samples for a peak tone estimate.")

    lines.append(
        "Tiles updated: Live Camera, ROI Snap Shot, 3D beam profile, η meter, "
        "alignment trends, and FFT spectrum."
    )
    return "\n".join(lines)
