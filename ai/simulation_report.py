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
        "Tiles updated: Live Camera, ROI Snapshot, 3D beam profile, η meter, "
        "alignment trends, and FFT spectrum."
    )
    return "\n".join(lines)


def _summarize_values(values: list[float]) -> dict[str, Any] | None:
    """Build the mean/min/max/last/n shape ``_fmt_stats`` expects, from raw samples."""
    if not values:
        return None
    return {
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "last": values[-1],
        "n": len(values),
    }


def _summarize_sim2_history(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce ``AlignmentController.history`` samples to reportable stats."""
    etas = [
        h["efficiency"] * 100.0 for h in history if h.get("efficiency") is not None
    ]
    errs = [
        (h["centroid_error_px"][0] ** 2 + h["centroid_error_px"][1] ** 2) ** 0.5
        for h in history
        if h.get("centroid_error_px") is not None
    ]
    v0 = [h["voltages"][0] for h in history if h.get("voltages") is not None]
    v1 = [h["voltages"][1] for h in history if h.get("voltages") is not None]
    return {
        "n": len(history),
        "eta_pct": _summarize_values(etas),
        "err_px": _summarize_values(errs),
        "voltage_v0": _summarize_values(v0),
        "voltage_v1": _summarize_values(v1),
        "mode": history[-1]["mode"] if history else None,
    }


_MODE_LABELS: dict[str, str] = {
    "sim1": "Simulation #1 (mock camera feed)",
    "sim2": "Simulation #2 (piezo closed loop)",
    "live": "Live camera",
    "idle": "Idle (nothing running)",
}


def format_results_statement(
    *,
    mode: str,
    telemetry: dict[str, Any],
    trend_summary: dict[str, Any] | None,
    coupling_overlay: dict[str, Any] | None,
    fft_peak_hz: float | None,
    fft_rate_hz: float | None,
    sim2_history: list[dict[str, Any]] | None = None,
    sim2_disturbance: dict[str, Any] | None = None,
) -> str:
    """On-demand or auto-posted summary of whatever is currently observable.

    Unlike ``format_simulation_report`` (which only fires after a timed
    Simulation #1 run), this works at any moment - idle, live camera,
    Simulation #1, or Simulation #2 - and folds in Simulation #2's control
    history and drift settings when they're relevant.
    """
    lines: list[str] = ["RESULTS STATEMENT", f"Mode: {_MODE_LABELS.get(mode, mode)}"]

    lam = telemetry.get("wavelength_nm")
    if lam is not None:
        lines.append(
            f"Wavelength: {float(lam):.2f} nm ({telemetry.get('wavelength_mode', 'nominal')})"
        )

    eta = telemetry.get("efficiency_pct")
    if eta is not None:
        lines.append(f"Coupling η: {float(eta):.1f}%")

    w0 = telemetry.get("beam_waist_um")
    if w0 is not None and w0 == w0:
        lines.append(f"Beam waist w₀: {float(w0):.1f} µm")

    if coupling_overlay is not None:
        err_um = coupling_overlay.get("error_um")
        err_ang = coupling_overlay.get("error_angle_deg")
        if err_um is not None and err_um == err_um:
            ang_txt = (
                f"{float(err_ang):.0f}°"
                if err_ang is not None and err_ang == err_ang
                else "—"
            )
            lines.append(f"Coupling error: Δ {float(err_um):.1f} µm · angle {ang_txt}")

    eta_trend = (trend_summary or {}).get("eta")
    w0_trend = (trend_summary or {}).get("w0")
    if eta_trend and eta_trend.get("n", 0) > 0:
        lines.append(f"η trend this session: {_fmt_stats(eta_trend, '%', 1)}")
    if w0_trend and w0_trend.get("n", 0) > 0:
        lines.append(f"w₀ trend this session: {_fmt_stats(w0_trend, 'µm', 1)}")

    if sim2_history:
        stats = _summarize_sim2_history(sim2_history)
        lines.append(
            f"Simulation #2 control samples: {stats['n']} (mode: {stats.get('mode') or '—'})"
        )
        if stats["eta_pct"]:
            lines.append(f"Sim #2 η: {_fmt_stats(stats['eta_pct'], '%', 1)}")
        if stats["err_px"]:
            lines.append(f"Sim #2 centroid error: {_fmt_stats(stats['err_px'], 'px', 2)}")
        if stats["voltage_v0"] and stats["voltage_v1"]:
            lines.append(
                f"Piezo voltages: axis0 {stats['voltage_v0']['min']:.1f}-{stats['voltage_v0']['max']:.1f} V, "
                f"axis1 {stats['voltage_v1']['min']:.1f}-{stats['voltage_v1']['max']:.1f} V"
            )

    if sim2_disturbance:
        ax, ay = sim2_disturbance.get("drift_amp_px", (0.0, 0.0))
        lines.append(
            f"Drift settings: sway amplitude ({ax:.1f}, {ay:.1f}) px, "
            f"period {sim2_disturbance.get('drift_period_s', 0.0):.0f} s, "
            f"centroid noise {sim2_disturbance.get('noise_px', 0.0):.2f} px, "
            f"piezo creep {sim2_disturbance.get('creep_frac', 0.0):.2f}"
        )

    if fft_peak_hz is not None and fft_peak_hz > 0:
        rate_txt = f"{fft_rate_hz:.1f} Hz" if fft_rate_hz and fft_rate_hz > 0 else "—"
        lines.append(f"FFT peak tone: {fft_peak_hz:.2f} Hz (sample rate {rate_txt})")

    if len(lines) <= 2:
        lines.append(
            "Nothing running yet: start Simulation #1, Simulation #2, or the live "
            "camera feed, then ask again."
        )

    return "\n".join(lines)
