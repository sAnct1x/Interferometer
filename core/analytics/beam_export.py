"""Professional beam-analysis export into dated run folders under ``outputs/beam``.

Each Analyze / Save Report writes a self-contained run directory with labeled
figures (PNG), scalars (CSV), human summary (TXT), and machine metadata (JSON).
``latest/`` always mirrors the most recent run for Atria and File → Open.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from config import (
    BEAM_WAIST_TARGET_UM,
    LASER_WAVELENGTH_NM,
    OUTPUT_DIR,
    PIXEL_SIZE_UM,
)

BEAM_OUTPUT_DIR = OUTPUT_DIR / "beam"
BEAM_RUNS_DIR = BEAM_OUTPUT_DIR / "runs"
BEAM_LATEST_DIR = BEAM_OUTPUT_DIR / "latest"
BEAM_RUN_LOG = BEAM_OUTPUT_DIR / "run_log.csv"
BEAM_LATEST_POINTER = BEAM_OUTPUT_DIR / "LATEST.txt"

_RUN_ID_RE = re.compile(r"^run_(\d{3})_(\d{8})_(\d{6})$")

RUN_LOG_FIELDS = [
    "run_id",
    "analyzed_at",
    "source",
    "fwhm_x_um",
    "fwhm_y_um",
    "one_over_e2_x_um",
    "one_over_e2_y_um",
    "one_over_e2_avg_um",
    "m2",
    "fit_quality",
    "background_level",
    "wavelength_nm",
    "run_dir",
]


def next_beam_run_id() -> str:
    """Next sequential ID, e.g. ``run_012_20260713_170315``."""
    BEAM_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    max_seq = 0
    for path in BEAM_RUNS_DIR.iterdir():
        if not path.is_dir():
            continue
        m = _RUN_ID_RE.match(path.name)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{max_seq + 1:03d}_{stamp}"


def latest_beam_run_dir() -> Path | None:
    """Directory pointed to by ``LATEST.txt``, or the newest ``runs/`` folder."""
    if BEAM_LATEST_POINTER.is_file():
        name = BEAM_LATEST_POINTER.read_text(encoding="utf-8").strip()
        candidate = BEAM_RUNS_DIR / name
        if candidate.is_dir():
            return candidate
    if BEAM_LATEST_DIR.is_dir() and any(BEAM_LATEST_DIR.iterdir()):
        return BEAM_LATEST_DIR
    if not BEAM_RUNS_DIR.is_dir():
        return None
    runs = sorted(
        [p for p in BEAM_RUNS_DIR.iterdir() if p.is_dir() and _RUN_ID_RE.match(p.name)],
        key=lambda p: p.name,
    )
    return runs[-1] if runs else None


def read_latest_summary() -> dict[str, Any] | None:
    """Load ``meta.json`` + ``summary.txt`` from the latest beam run, if any."""
    run_dir = latest_beam_run_dir()
    if run_dir is None:
        return None
    meta_path = run_dir / "meta.json"
    summary_path = run_dir / "summary.txt"
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    summary = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
    return {
        "run_dir": str(run_dir),
        "run_id": meta.get("run_id") or run_dir.name,
        "meta": meta,
        "summary": summary,
        "report_png": str(run_dir / "beam_report.png"),
        "heatmap_png": str(run_dir / "beam_heatmap.png"),
        "profiles_png": str(run_dir / "beam_profiles.png"),
        "surface_png": str(run_dir / "beam_surface_3d.png"),
    }


def export_beam_run(
    result: dict[str, Any],
    *,
    frame: np.ndarray | None = None,
    source: str = "live",
    wavelength_nm: float | None = None,
    camera_serial: str | None = None,
    roi_xywh: tuple[int, int, int, int] | None = None,
    notes: str = "",
) -> Path:
    """Write a full labeled beam-analysis package; return the run directory."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import gridspec

    run_id = next_beam_run_id()
    run_dir = BEAM_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lam = float(wavelength_nm if wavelength_nm is not None else LASER_WAVELENGTH_NM)
    quality = result.get("beam_quality") or {}
    w0 = float(result.get("one_over_e2_avg_um", float("nan")))
    m2 = float(result.get("m2", quality.get("m2", float("nan"))))
    target = BEAM_WAIST_TARGET_UM[1]

    img = np.asarray(result.get("img_bs"))
    x_prof = np.asarray(result.get("x_profile"), dtype=float)
    y_prof = np.asarray(result.get("y_profile"), dtype=float)
    x_fit = quality.get("x_fit") or {}
    y_fit = quality.get("y_fit") or {}

    # --- Figures (publication style: white, labeled, high DPI) ---
    _save_heatmap_figure(plt, run_dir / "beam_heatmap.png", img, run_id, w0, m2)
    _save_profiles_figure(
        plt, run_dir / "beam_profiles.png", x_prof, y_prof, x_fit, y_fit, result, run_id
    )
    _save_surface_figure(plt, run_dir / "beam_surface_3d.png", img, run_id, w0)
    _save_report_figure(
        plt,
        gridspec,
        run_dir / "beam_report.png",
        img,
        x_prof,
        y_prof,
        x_fit,
        y_fit,
        result,
        quality,
        run_id=run_id,
        analyzed_at=analyzed_at,
        wavelength_nm=lam,
        source=source,
        target_um=target,
    )

    if frame is not None:
        _save_frame_png(run_dir / "source_frame.png", np.asarray(frame))

    meta = {
        "run_id": run_id,
        "analyzed_at": analyzed_at,
        "source": source,
        "wavelength_nm": lam,
        "pixel_size_um": PIXEL_SIZE_UM,
        "camera_serial": camera_serial,
        "roi_xywh": list(roi_xywh) if roi_xywh else None,
        "beam_waist_target_um": list(BEAM_WAIST_TARGET_UM),
        "fwhm_x_um": _num(result.get("fwhm_x_um")),
        "fwhm_y_um": _num(result.get("fwhm_y_um")),
        "one_over_e2_x_um": _num(result.get("one_over_e2_x_um")),
        "one_over_e2_y_um": _num(result.get("one_over_e2_y_um")),
        "one_over_e2_avg_um": _num(w0),
        "m2": _num(m2),
        "fit_quality": quality.get("fit_quality"),
        "background_level": _num(result.get("background_level")),
        "cropped_shape": list(result.get("cropped_shape") or []),
        "quality_warnings": list(result.get("quality_warnings") or []),
        "notes": notes,
        "artifacts": [
            "beam_report.png",
            "beam_heatmap.png",
            "beam_profiles.png",
            "beam_surface_3d.png",
            "results.csv",
            "summary.txt",
            "meta.json",
        ],
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    _write_results_csv(run_dir / "results.csv", meta)
    _write_summary_txt(run_dir / "summary.txt", meta)
    _append_run_log(meta, run_dir)
    _publish_latest(run_dir, run_id)

    return run_dir


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or abs(v) == float("inf"):
        return None
    return v


def _axis_um(n: int) -> np.ndarray:
    return np.arange(max(n, 1), dtype=float) * PIXEL_SIZE_UM


def _save_heatmap_figure(plt, path: Path, img: np.ndarray, run_id: str, w0: float, m2: float) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 5.2), dpi=160)
    if img.ndim >= 2 and img.size:
        extent = [0, img.shape[1] * PIXEL_SIZE_UM, img.shape[0] * PIXEL_SIZE_UM, 0]
        im = ax.imshow(img, cmap="magma", origin="upper", extent=extent, aspect="equal")
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label("Intensity (a.u.)", fontsize=10)
    ax.set_xlabel("x (µm)", fontsize=11)
    ax.set_ylabel("y (µm)", fontsize=11)
    ax.set_title(f"Beam intensity map (ROI)\n{run_id}  ·  w₀={w0:.1f} µm  ·  M²≈{m2:.2f}", fontsize=12)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_profiles_figure(
    plt,
    path: Path,
    x_prof: np.ndarray,
    y_prof: np.ndarray,
    x_fit: dict,
    y_fit: dict,
    result: dict,
    run_id: str,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), dpi=160)
    for ax, prof, fit, label, e2_key, color in (
        (axes[0], x_prof, x_fit, "X", "one_over_e2_x_um", "#7b2cbf"),
        (axes[1], y_prof, y_fit, "Y", "one_over_e2_y_um", "#c9184a"),
    ):
        if prof.size:
            um = _axis_um(len(prof))
            ax.plot(um, prof, color=color, lw=2.0, label=f"{label} profile")
            peak = float(np.max(prof)) if prof.size else 0.0
            if peak > 0:
                ax.axhline(peak / np.e**2, color=color, ls="--", lw=1.2, alpha=0.7, label="1/e²")
            if fit.get("fit") is not None and fit.get("x_um") is not None:
                ax.plot(fit["x_um"], fit["fit"], color="#0a9396", ls="--", lw=1.8, label="Gaussian fit")
            e2 = result.get(e2_key, float("nan"))
            ax.set_title(f"{label} profile  ·  1/e² = {e2:.1f} µm", fontsize=11)
            ax.set_xlabel(f"{label.lower()} (µm)", fontsize=10)
            ax.set_ylabel("Intensity (a.u.)", fontsize=10)
            ax.legend(fontsize=8, loc="best", frameon=True)
            ax.grid(True, alpha=0.25)
    fig.suptitle(f"Beam profiles with Gaussian fits — {run_id}", fontsize=12, y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_surface_figure(plt, path: Path, img: np.ndarray, run_id: str, w0: float) -> None:
    """Pseudo-3D surface (matplotlib) so the run folder has a shareable 3D view."""
    fig = plt.figure(figsize=(7.2, 5.6), dpi=160)
    ax = fig.add_subplot(111, projection="3d")
    if img.ndim >= 2 and img.size:
        h, w = img.shape[:2]
        # Downsample for a clean figure without huge meshes.
        step = max(1, max(h, w) // 80)
        z = np.asarray(img[::step, ::step], dtype=float)
        ys = np.arange(z.shape[0]) * PIXEL_SIZE_UM * step
        xs = np.arange(z.shape[1]) * PIXEL_SIZE_UM * step
        X, Y = np.meshgrid(xs, ys)
        ax.plot_surface(X, Y, z, cmap="magma", linewidth=0, antialiased=True, alpha=0.95)
        ax.set_xlabel("x (µm)")
        ax.set_ylabel("y (µm)")
        ax.set_zlabel("I (a.u.)")
    ax.set_title(f"3D beam surface  ·  {run_id}  ·  w₀={w0:.1f} µm", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_report_figure(
    plt,
    gridspec,
    path: Path,
    img: np.ndarray,
    x_prof: np.ndarray,
    y_prof: np.ndarray,
    x_fit: dict,
    y_fit: dict,
    result: dict,
    quality: dict,
    *,
    run_id: str,
    analyzed_at: str,
    wavelength_nm: float,
    source: str,
    target_um: float,
) -> None:
    fig = plt.figure(figsize=(12.5, 8.5), dpi=160)
    gs = gridspec.GridSpec(2, 3, height_ratios=[1.15, 1.0], hspace=0.32, wspace=0.28)

    ax0 = fig.add_subplot(gs[0, 0])
    if img.ndim >= 2 and img.size:
        extent = [0, img.shape[1] * PIXEL_SIZE_UM, img.shape[0] * PIXEL_SIZE_UM, 0]
        im = ax0.imshow(img, cmap="magma", origin="upper", extent=extent, aspect="equal")
        fig.colorbar(im, ax=ax0, fraction=0.046, pad=0.04)
    ax0.set_title("Intensity map (ROI)")
    ax0.set_xlabel("x (µm)")
    ax0.set_ylabel("y (µm)")

    ax_s = fig.add_subplot(gs[0, 1], projection="3d")
    if img.ndim >= 2 and img.size:
        step = max(1, max(img.shape[:2]) // 60)
        z = np.asarray(img[::step, ::step], dtype=float)
        ys = np.arange(z.shape[0]) * PIXEL_SIZE_UM * step
        xs = np.arange(z.shape[1]) * PIXEL_SIZE_UM * step
        X, Y = np.meshgrid(xs, ys)
        ax_s.plot_surface(X, Y, z, cmap="magma", linewidth=0, antialiased=True)
    ax_s.set_title("3D surface")
    ax_s.set_xlabel("x (µm)")
    ax_s.set_ylabel("y (µm)")

    ax_m = fig.add_subplot(gs[0, 2])
    ax_m.axis("off")
    w0 = result.get("one_over_e2_avg_um", float("nan"))
    m2 = result.get("m2", quality.get("m2", float("nan")))
    lines = [
        "Interferometer Automation",
        "Beam analysis report",
        "",
        f"Run ID:     {run_id}",
        f"Timestamp:  {analyzed_at}",
        f"Source:     {source}",
        f"λ:          {wavelength_nm:.2f} nm",
        f"Pixel size: {PIXEL_SIZE_UM:.2f} µm",
        "",
        f"w₀ (1/e² avg): {w0:.2f} µm",
        f"Target w₀:     {target_um:.0f} µm",
        f"1/e² X / Y:    {result.get('one_over_e2_x_um', float('nan')):.2f} / "
        f"{result.get('one_over_e2_y_um', float('nan')):.2f} µm",
        f"FWHM X / Y:    {result.get('fwhm_x_um', float('nan')):.2f} / "
        f"{result.get('fwhm_y_um', float('nan')):.2f} µm",
        f"M² (proxy):    {m2:.3f}",
        f"Fit quality:   {quality.get('fit_quality', '—')}",
        f"Background:    {result.get('background_level', float('nan')):.1f}",
    ]
    warnings = result.get("quality_warnings") or []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in warnings[:4]:
            lines.append(f"  • {w}")
    ax_m.text(
        0.0,
        1.0,
        "\n".join(lines),
        transform=ax_m.transAxes,
        va="top",
        ha="left",
        family="monospace",
        fontsize=9.5,
        linespacing=1.35,
    )

    for col, prof, fit, label, color in (
        (0, x_prof, x_fit, "X", "#7b2cbf"),
        (1, y_prof, y_fit, "Y", "#c9184a"),
    ):
        ax = fig.add_subplot(gs[1, col])
        if prof.size:
            um = _axis_um(len(prof))
            ax.plot(um, prof, color=color, lw=2.0, label="data")
            if fit.get("fit") is not None and fit.get("x_um") is not None:
                ax.plot(fit["x_um"], fit["fit"], color="#0a9396", ls="--", lw=1.8, label="fit")
            peak = float(np.max(prof))
            if peak > 0:
                ax.axhline(peak / np.e**2, color=color, ls=":", lw=1.0, alpha=0.7)
        ax.set_title(f"{label} profile + Gaussian fit")
        ax.set_xlabel(f"{label.lower()} (µm)")
        ax.set_ylabel("Intensity (a.u.)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.25)

    ax_n = fig.add_subplot(gs[1, 2])
    ax_n.axis("off")
    ax_n.text(
        0.0,
        1.0,
        (
            "Notes\n"
            "• Heatmap / 3D / profiles use the Beam waist ROI.\n"
            "• w₀ is the 1/e² diameter average of X and Y fits.\n"
            "• M² is a fit-quality proxy, not a full ISO caustic scan.\n"
            "• Files: beam_report.png, beam_heatmap.png,\n"
            "  beam_profiles.png, beam_surface_3d.png,\n"
            "  results.csv, summary.txt, meta.json"
        ),
        transform=ax_n.transAxes,
        va="top",
        ha="left",
        fontsize=9.5,
        linespacing=1.4,
    )

    fig.suptitle(
        f"Beam analysis report — {run_id}",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_frame_png(path: Path, frame: np.ndarray) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    arr = np.asarray(frame)
    if arr.ndim == 3 and arr.shape[-1] >= 3:
        rgb = arr[..., :3]
        if rgb.dtype != np.uint8:
            peak = float(rgb.max()) or 1.0
            rgb = np.clip(rgb.astype(np.float32) * (255.0 / peak), 0, 255).astype(np.uint8)
        Image.fromarray(rgb, mode="RGB").save(path)
        return
    gray = arr if arr.ndim == 2 else arr[..., 0]
    g = gray.astype(np.float32)
    lo, hi = np.percentile(g, 1), np.percentile(g, 99.5)
    if hi <= lo:
        hi = lo + 1
    u8 = np.clip((g - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(u8, mode="L").save(path)


def _write_results_csv(path: Path, meta: dict[str, Any]) -> None:
    fields = [
        "run_id",
        "analyzed_at",
        "source",
        "wavelength_nm",
        "fwhm_x_um",
        "fwhm_y_um",
        "one_over_e2_x_um",
        "one_over_e2_y_um",
        "one_over_e2_avg_um",
        "m2",
        "fit_quality",
        "background_level",
        "camera_serial",
        "roi_xywh",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({k: meta.get(k) for k in fields})


def _write_summary_txt(path: Path, meta: dict[str, Any]) -> None:
    warnings = meta.get("quality_warnings") or []
    lines = [
        "Interferometer Automation — Beam Analysis Summary",
        "=" * 52,
        f"Run ID:          {meta.get('run_id')}",
        f"Analyzed at:     {meta.get('analyzed_at')}",
        f"Source:          {meta.get('source')}",
        f"Wavelength:      {meta.get('wavelength_nm')} nm",
        f"Camera serial:   {meta.get('camera_serial') or '—'}",
        f"ROI (x,y,w,h):   {meta.get('roi_xywh')}",
        "",
        f"w₀ (1/e² avg):   {meta.get('one_over_e2_avg_um')} µm",
        f"1/e² X / Y:      {meta.get('one_over_e2_x_um')} / {meta.get('one_over_e2_y_um')} µm",
        f"FWHM X / Y:      {meta.get('fwhm_x_um')} / {meta.get('fwhm_y_um')} µm",
        f"M² (proxy):      {meta.get('m2')}",
        f"Fit quality:     {meta.get('fit_quality')}",
        f"Background:      {meta.get('background_level')}",
        "",
        "Artifacts:",
        "  beam_report.png, beam_heatmap.png, beam_profiles.png,",
        "  beam_surface_3d.png, results.csv, meta.json",
    ]
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  - {w}" for w in warnings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_run_log(meta: dict[str, Any], run_dir: Path) -> None:
    BEAM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "run_id": meta.get("run_id"),
        "analyzed_at": meta.get("analyzed_at"),
        "source": meta.get("source"),
        "fwhm_x_um": meta.get("fwhm_x_um"),
        "fwhm_y_um": meta.get("fwhm_y_um"),
        "one_over_e2_x_um": meta.get("one_over_e2_x_um"),
        "one_over_e2_y_um": meta.get("one_over_e2_y_um"),
        "one_over_e2_avg_um": meta.get("one_over_e2_avg_um"),
        "m2": meta.get("m2"),
        "fit_quality": meta.get("fit_quality"),
        "background_level": meta.get("background_level"),
        "wavelength_nm": meta.get("wavelength_nm"),
        "run_dir": str(run_dir),
    }
    write_header = not BEAM_RUN_LOG.is_file()
    with BEAM_RUN_LOG.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _publish_latest(run_dir: Path, run_id: str) -> None:
    if BEAM_LATEST_DIR.exists():
        shutil.rmtree(BEAM_LATEST_DIR)
    shutil.copytree(run_dir, BEAM_LATEST_DIR)
    BEAM_LATEST_POINTER.write_text(run_id + "\n", encoding="utf-8")
