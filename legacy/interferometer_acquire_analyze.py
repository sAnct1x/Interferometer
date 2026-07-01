"""Interferometer acquisition and analysis (Thorcam CS165CU + K-Cube Z925)."""

from __future__ import annotations

import argparse
import csv
import re
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm as mpl_cm
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from scipy import signal
from scipy.ndimage import gaussian_filter1d

from figure_config import (
    POSTER_FIGSIZE_IN,
    POSTER_FONT_PT,
    POSTER_SAVE_DPI,
    POSTER_STFT_TRACE_YLIM,
    POSTER_STFT_TRACE_YTICKS,
)

# cv2 and pylablib are imported inside hardware functions so that analysis
# commands (analyze, compare, analyze-scan) work on machines without
# Thorlabs drivers or OpenCV installed.

_REPO_ROOT = Path(__file__).resolve().parent
# Canonical analysis exports for the poster bundle (override with --out-dir)
DEFAULT_POSTER_FIGURES_DIR = _REPO_ROOT / "my_poster_bundle" / "figures"
DEFAULT_POSTER_FRAMES_DIR = _REPO_ROOT / "my_poster_bundle" / "frames_analysis"

# Vibrant poster palette (pinks, purples, blues, oranges)
_POSTER_COLORS: dict[str, str] = {
    "line_primary": "#FF1493",
    "line_secondary": "#00B4D8",
    "spectrum": "#1E88E5",
    "spectrum_smooth": "#E53935",
    "peak_mark": "#FF6D00",
    "wavelength_line": "#7C4DFF",
    "psd": "#E91E63",
    "psd_nyq": "#78909C",
    "compare_a": "#FF4081",
    "compare_b": "#00B0FF",
    "constructive": "#FF66C4",
    "destructive": "#5E35B1",
    "overlay_line": "#4A148C",
    "frames_mean": "#D500F9",
    "frames_std": "#00E676",
    "time_trace": "#00B0FF",
}

# Consistent axis copy for poster exports (avoid “same label everywhere” confusion).
_LAB = {
    "x_mm": "Mirror position (mm)",
    "x_steps": "Stage position (steps)",
    "roi_counts": "Mean intensity in ROI (counts)",
    "roi_detrend": "Detrended mean intensity in ROI (counts)",
    # Short labels for compact figures (e.g. STFT stack) to avoid margin clipping.
    "stft_counts": "ROI",
    "stft_power_db": "Power (dB)",
    "norm_I": "Normalized intensity",
    "time_s": "Time (s)",
    "f_hz": "Frequency (Hz)",
    "sigma_mm": "Spatial frequency (fringes / mm)",
    "sigma_step": "Spatial frequency (fringes / step)",
    "psd": r"Power spectral density (counts$^2$ / Hz)",
    "power": "Spatial power (arbitrary units)",
    "lambda_nm": "Wavelength (nm)",
    "db": "Power relative to peak (decibels)",
    "roi_u8": "Mean intensity in ROI (8-bit display scale)",
    "roi_std_u8": "Intensity standard deviation in ROI (8-bit scale)",
    "x_from_file": "Position from filename (mm)",
    "x_frame_order": "Frame index",
}

def _apply_poster_mpl_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#FAFAFF",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": "#4A5568",
            "axes.linewidth": 1.0,
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.color": "#E2E8F0",
            "axes.labelcolor": "#1A202C",
            "text.color": "#1A202C",
            "xtick.color": "#1A202C",
            "ytick.color": "#1A202C",
            "axes.titleweight": "600",
            "axes.labelsize": POSTER_FONT_PT,
            "axes.titlesize": POSTER_FONT_PT,
            "xtick.labelsize": POSTER_FONT_PT,
            "ytick.labelsize": POSTER_FONT_PT,
            "legend.fontsize": POSTER_FONT_PT,
            "font.size": POSTER_FONT_PT,
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Segoe UI",
                "Arial",
                "Helvetica Neue",
                "DejaVu Sans",
                "sans-serif",
            ],
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


_apply_poster_mpl_style()


def _polish_figure(fig: Figure) -> None:
    """Hide top/right spines on Cartesian axes (skip colorbar-only axes)."""
    for ax in fig.axes:
        sp = getattr(ax, "spines", None)
        if sp is None:
            continue
        for side in ("top", "right"):
            if side in sp:
                sp[side].set_visible(False)


def _apply_poster_font_to_figure(fig: Figure) -> None:
    """Poster readability: one font size for titles, labels, ticks, legends, annotations."""
    fs = POSTER_FONT_PT
    supt = getattr(fig, "_suptitle", None)
    if supt is not None:
        supt.set_fontsize(fs)
    for ax in fig.axes:
        ax.title.set_fontsize(fs)
        ax.xaxis.label.set_fontsize(fs)
        ax.yaxis.label.set_fontsize(fs)
        ax.tick_params(axis="both", which="both", labelsize=fs)
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                t.set_fontsize(fs)
        for t in ax.texts:
            t.set_fontsize(fs)
    for t in fig.texts:
        t.set_fontsize(fs)


# --- Section: Display helpers ---

def normalize_for_display(frame: np.ndarray) -> np.ndarray:
    """Scale any frame to 0-255 uint8 via min-max normalization."""
    frame = frame.astype(np.float32)
    frame -= np.min(frame)
    max_val = np.max(frame)
    if max_val > 0:
        frame /= max_val
    return (255 * frame).astype(np.uint8)


# ROI selection preview is capped to fit small laptop screens (e.g. 1366x768).
# The ROI coordinates are always stored in full-sensor pixels.
_DISPLAY_MAX_W = 1280
_DISPLAY_MAX_H = 700


def _finalize_figure(
    fig: Figure,
    path: Path,
    *,
    dpi: int | None = None,
    show: bool = False,
    before_savefig: Callable[[], None] | None = None,
    bbox_inches: str | None = None,
    pad_inches: float | None = None,
) -> None:
    """Save figure to PNG; optionally block until the user closes the window."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Lock physical size so tight_layout/colorbars cannot leave a stale figsize (e.g. old 11×4.5).
    w_in, h_in = POSTER_FIGSIZE_IN
    cur_w, cur_h = fig.get_size_inches()
    if abs(float(cur_w) - w_in) > 0.02 or abs(float(cur_h) - h_in) > 0.02:
        fig.set_size_inches(w_in, h_in, forward=True)
    _polish_figure(fig)
    _apply_poster_font_to_figure(fig)
    if before_savefig is not None:
        before_savefig()
    out_dpi = POSTER_SAVE_DPI if dpi is None else dpi
    save_kw: dict[str, Any] = {
        "dpi": out_dpi,
        "facecolor": fig.get_facecolor(),
        "edgecolor": "none",
    }
    if bbox_inches is not None:
        save_kw["bbox_inches"] = bbox_inches
    if pad_inches is not None:
        save_kw["pad_inches"] = pad_inches
    fig.savefig(path, **save_kw)
    print(f"Saved {path}")
    if show:
        plt.show(block=True)
    plt.close(fig)


def _resize_for_display_u8(
    img: np.ndarray, max_w: int, max_h: int
) -> tuple[np.ndarray, tuple[int, int]]:
    """Resize a uint8 image to fit within max_w x max_h for on-screen display.

    Accepts 2D grayscale or HxWx3/4 color frames.
    Returns (resized_image, (original_height, original_width)) so the caller
    can map ROI coordinates back to full resolution.
    """
    import cv2

    if img.ndim not in (2, 3) or (img.ndim == 3 and img.shape[2] not in (3, 4)):
        raise ValueError(
            f"Expected 2D grayscale or HxWx3/4 color uint8, got shape {img.shape}"
        )
    fh, fw = int(img.shape[0]), int(img.shape[1])
    scale = min(max_w / fw, max_h / fh, 1.0)
    if scale >= 1.0:
        return img, (fh, fw)
    dw = max(1, int(round(fw * scale)))
    dh = max(1, int(round(fh * scale)))
    out = cv2.resize(img, (dw, dh), interpolation=cv2.INTER_AREA)
    return out, (fh, fw)


def _save_scan_snapshot(path: Path, frame: np.ndarray) -> None:
    """Save one camera frame as an 8-bit PNG, normalized for visibility.

    Handles both grayscale (HxW) and color (HxWx3/4) frames.
    Color frames are converted from RGB (pylablib convention) to BGR
    (OpenCV imwrite convention) before saving.
    """
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.squeeze(frame)
    u8 = normalize_for_display(arr)
    if u8.ndim == 3:
        u8 = cv2.cvtColor(u8[..., :3], cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), u8)


def _roi_display_to_full(
    roi: tuple[int, int, int, int],
    full_hw: tuple[int, int],
    disp_hw: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Map ROI coordinates from a scaled display image back to full-sensor pixels."""
    x, y, w, h = roi
    fh, fw = full_hw
    dh, dw = disp_hw
    return (
        int(round(x * fw / dw)),
        int(round(y * fh / dh)),
        int(round(w * fw / dw)),
        int(round(h * fh / dh)),
    )


def _parse_mm_filename_token(token: str) -> float:
    """Decode Thorlabs-style filename token like '0p0100' -> 0.01 mm."""
    return float(token.replace("p", "."))


def roi_mean(frame: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    """Compute the mean pixel value inside the ROI bounding box."""
    x, y, w, h = roi
    sub = frame[y : y + h, x : x + w]
    if sub.size == 0:
        return float("nan")
    return float(np.mean(sub))


# --- Section: Hardware setup (setup_camera, setup_stage, ROI I/O) ---

def load_stage_config(path: Path | None = None) -> dict[str, Any]:
    """Load stage_config.json (model, pylablib scale, kinesis params).

    Returns an empty dict if the file is missing or unreadable.
    """
    p = path or Path("stage_config.json")
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def setup_stage(
    serial: str | None = None,
    *,
    scale: str = "step",
    stage_config: dict[str, Any] | None = None,
) -> Any:
    """Connect to a Thorlabs K-Cube motor via pylablib.

    Args:
        serial: Device serial number. Auto-detected from USB if None.
        scale: pylablib scale name. "step" gives raw encoder counts;
               a stage model like "Z825" gives calibrated mm positions.
        stage_config: Parsed stage_config.json dict (for display info only).
    """
    from pylablib.devices import Thorlabs

    print("Connecting to Thorlabs K-Cube...")
    devs = Thorlabs.list_kinesis_devices()
    if not devs:
        raise RuntimeError("No Thorlabs Kinesis devices found.")
    addr = serial or devs[0][0]
    stage = Thorlabs.KinesisMotor(addr, scale=scale)
    # Short delay for the controller to finish its USB handshake.
    time.sleep(1.5)
    pos = stage.get_position()
    cfg = stage_config or {}
    if cfg.get("stage_model"):
        print(f"  stage_config: model {cfg.get('stage_model')}, pylablib scale={scale!r}")
    if scale == "step":
        print(f"K-Cube connected ({addr}), position: {pos} (encoder/controller steps)")
    else:
        # pylablib returns metres for named scales; convert to mm for display.
        print(f"K-Cube connected ({addr}), position: {float(pos) * 1000.0:.6f} mm ({scale} scaling)")
    return stage


def _try_set_stage_velocity_mm_s(stage: Any, velocity_mm_s: float) -> bool:
    """Set K-Cube max velocity via pylablib (API varies by version). Returns True if set."""
    v_m_s = float(velocity_mm_s) * 1e-3
    for setter in [
        lambda: stage.setup_velocity(speed=v_m_s),
        lambda: stage.setup_velocity(max_velocity=v_m_s),
    ]:
        try:
            setter()
            return True
        except (TypeError, AttributeError):
            continue
    return False


def setup_camera(serial: str | None = None) -> Any:
    """Connect to a Thorlabs TLCam (scientific camera) via pylablib.

    Returns the camera object, or None if no camera is found.
    """
    from pylablib.devices import Thorlabs
    from pylablib.devices.Thorlabs.TLCamera import ThorlabsTLCamera

    print("Connecting to Thorcam...")
    cams = Thorlabs.list_cameras_tlcam()
    if not cams:
        print("No Thorcam found.")
        return None
    cam = ThorlabsTLCamera(serial or cams[0])
    print("Thorcam connected.")
    return cam


def select_roi(cam: Any) -> tuple[int, int, int, int] | None:
    """Show a live camera preview and let the user draw an ROI box.

    Press 's' to freeze the frame, drag to select, then press Enter.
    Press 'c' to cancel.
    Returns (x, y, w, h) in full-sensor pixels, or None if cancelled.
    """
    import cv2

    print(
        "Live preview: press 's' to freeze, then drag ROI from the center of the fringes "
        "(larger box = more pixels / better fringe sampling). 'c' to cancel."
    )
    print(
        f"If the preview is scaled to fit this display (max {_DISPLAY_MAX_W}x{_DISPLAY_MAX_H}), "
        "saved ROI is still in full camera pixels."
    )
    cam.start_acquisition()
    last_frame = None
    try:
        while True:
            frame = cam.read_newest_image()
            if frame is not None:
                last_frame = np.squeeze(frame)
                u8 = normalize_for_display(last_frame)
                disp, _ = _resize_for_display_u8(u8, _DISPLAY_MAX_W, _DISPLAY_MAX_H)
                cv2.imshow("Thorcam Live", disp)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("c"):
                cam.stop_acquisition()
                cv2.destroyAllWindows()
                return None
            if key == ord("s"):
                break
    finally:
        cam.stop_acquisition()

    if last_frame is None:
        cv2.destroyAllWindows()
        return None

    frozen = normalize_for_display(last_frame)
    frozen_disp, full_hw = _resize_for_display_u8(frozen, _DISPLAY_MAX_W, _DISPLAY_MAX_H)
    cv2.imshow("Select ROI", frozen_disp)
    roi_d = cv2.selectROI("Select ROI", frozen_disp, fromCenter=True, showCrosshair=True)
    cv2.destroyAllWindows()
    if roi_d is None or roi_d[2] == 0 or roi_d[3] == 0:
        return None
    dh, dw = frozen_disp.shape[0], frozen_disp.shape[1]
    x, y, w, h = _roi_display_to_full(tuple(map(int, roi_d)), full_hw, (dh, dw))
    print(f"ROI (full sensor pixels): x={x}, y={y}, w={w}, h={h}")
    return (x, y, w, h)


def save_roi(roi: tuple[int, int, int, int], path: Path) -> None:
    """Write ROI to JSON, preserving any existing camera metadata fields."""
    payload: dict[str, object] = {"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            for key in ("camera_model", "camera_serial", "sensor_size_px"):
                if key in prev:
                    payload[key] = prev[key]
        except (OSError, json.JSONDecodeError):
            pass
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"ROI saved to {path}")


def load_roi(path: Path) -> tuple[int, int, int, int]:
    """Read ROI from JSON and return (x, y, w, h) in sensor pixels."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return (int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))


# --- Section: Acquisition metadata ---

@dataclass
class AcquisitionMeta:
    """Structured metadata written as a JSON sidecar alongside each CSV."""
    created_utc: str
    mode: str
    lambda_vacuum_nm: float | None = None
    lambda_status: str = "unknown"
    lambda_bounds_nm: list[float] | None = None
    lambda_notes: str = ""
    refractive_index_air: float = 1.0
    interferometer_notes: str = ""
    camera_model: str | None = None
    exposure_s: float | None = None
    frame_rate_hz: float | None = None
    gain: float | None = None
    stage_serial: str | None = None
    stage_units: str = "step"
    settle_s: float = 0.2
    welch_window: str = "hann"
    welch_scaling: str = "density"
    detrend: str = "linear"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        """Flatten to a plain dict for JSON serialization."""
        d = asdict(self)
        d.pop("extra", None)
        out = {k: v for k, v in d.items() if v is not None or k in ("lambda_vacuum_nm",)}
        out.update(self.extra)
        return out


def write_sidecar(path_csv: Path, meta: AcquisitionMeta) -> None:
    """Write metadata JSON next to the CSV (e.g. data.csv -> data.csv.meta.json)."""
    path = path_csv.with_suffix(path_csv.suffix + ".meta.json")
    path.write_text(json.dumps(meta.to_json_dict(), indent=2), encoding="utf-8")
    print(f"Metadata: {path}")


# --- Section: run_stage_scan ---

def iter_scan_positions(start: int, stop: int, step: int) -> list[int]:
    """Generate integer stage positions from start to stop (inclusive).

    Uses range() instead of a manual while loop for clarity and speed.
    """
    if step == 0:
        raise ValueError("step must be non-zero")
    # +1 / -1 makes the endpoint inclusive (range is normally exclusive).
    end = stop + 1 if step > 0 else stop - 1
    return list(range(start, end, step))


def iter_scan_positions_mm(start_mm: float, stop_mm: float, step_mm: float) -> list[float]:
    """Generate float stage positions in mm from start to stop (inclusive).

    Uses np.arange() instead of repeated float addition to avoid
    accumulation drift over many steps.
    """
    if step_mm == 0:
        raise ValueError("step must be non-zero")
    # Small epsilon so np.arange includes the endpoint when it falls
    # exactly on a step boundary (standard floating-point workaround).
    eps = abs(step_mm) * 1e-6
    if step_mm > 0:
        return list(np.arange(start_mm, stop_mm + eps, step_mm).astype(float))
    else:
        return list(np.arange(start_mm, stop_mm - eps, step_mm).astype(float))


def run_stage_scan(
    *,
    roi: tuple[int, int, int, int],
    start_steps: int | None,
    stop_steps: int | None,
    step_steps: int | None,
    start_mm: float | None,
    stop_mm: float | None,
    step_mm: float | None,
    settle_s: float,
    out_csv: Path,
    stage_serial: str | None,
    cam_serial: str | None,
    meta_extra: dict[str, Any],
    return_to_start: bool = True,
    save_frames_dir: Path | None = None,
    stage_config_path: Path | None = None,
    show_plots: bool = False,
    live_plot: bool = False,
) -> Path:
    """Step through stage positions, capture a frame at each, record ROI mean.

    Two modes:
      - Encoder steps: --start/--stop/--step (raw integer positions).
      - Millimetres:   --start-mm/--stop-mm/--step-mm (matches Kinesis readout,
                       requires stage_config.json with pylablib_scale).

    Outputs: CSV, metadata JSON, quick-look plots (intensity vs position,
    intensity vs elapsed time).
    """
    cfg = load_stage_config(stage_config_path)
    use_mm = start_mm is not None
    if use_mm:
        scale_name = str(cfg.get("pylablib_scale", "step"))
        if scale_name == "step":
            raise RuntimeError(
                "For --start-mm/--stop-mm/--step-mm, set stage_config.json pylablib_scale "
                "to a named stage (e.g. Z825) so positions match Kinesis mm readout."
            )
        stage = setup_stage(stage_serial, scale=scale_name, stage_config=cfg)
    else:
        stage = setup_stage(stage_serial, scale="step", stage_config=cfg)

    cam = setup_camera(cam_serial)
    if cam is None:
        stage.close()
        raise RuntimeError("Thorcam required for scan.")

    # Build the list of target positions.
    if use_mm:
        assert start_mm is not None and stop_mm is not None and step_mm is not None
        positions_mm = iter_scan_positions_mm(start_mm, stop_mm, step_mm)
        # pylablib uses metres internally for named-scale stages.
        positions_m = [p * 1e-3 for p in positions_mm]
    else:
        assert start_steps is not None and stop_steps is not None and step_steps is not None
        positions_mm = None
        positions_m = None

    if use_mm:
        positions = positions_m
        npos = len(positions)
    else:
        positions = iter_scan_positions(start_steps, stop_steps, step_steps)
        npos = len(positions)

    if not positions:
        stage.close()
        cam.close()
        raise ValueError("No scan positions generated; check start/stop/step.")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    meta = AcquisitionMeta(
        created_utc=datetime.now(timezone.utc).isoformat(),
        mode="stage_scan",
        settle_s=settle_s,
        stage_serial=stage_serial,
        extra=meta_extra,
    )

    # Nyquist warning for step-scan.
    if use_mm and step_mm is not None:
        lambda_est = 650e-6  # mm (red laser)
        fringe_period = lambda_est / 2.0
        nyquist_spatial = 1.0 / (2.0 * abs(step_mm))
        fringe_freq = 2.0 / lambda_est
        fringes_per_step = abs(step_mm) / fringe_period
        if fringe_freq > nyquist_spatial:
            print(
                f"\n  *** ALIASING WARNING ***\n"
                f"  Step size {step_mm} mm -> Nyquist = {nyquist_spatial:.1f} fringes/mm\n"
                f"  Expected fringe freq (~650 nm) = {fringe_freq:.0f} fringes/mm\n"
                f"  Each step jumps ~{fringes_per_step:.0f} fringes. "
                f"FFT wavelength recovery will fail.\n"
                f"  Need step < {fringe_period:.6f} mm ({fringe_period*1e6:.0f} nm) "
                f"for Nyquist, or use continuous-scan.\n"
            )
        else:
            print(
                f"  Nyquist OK: step {step_mm} mm, "
                f"Nyquist {nyquist_spatial:.0f} > {fringe_freq:.0f} fringes/mm"
            )

    # Acquisition loop: move -> wait for move -> settle -> capture frame.
    rows: list[tuple[float, float, float]] = []
    live_fig = None
    live_ax = None
    try:
        cam.start_acquisition()
        if live_plot:
            plt.ion()
            live_fig, live_ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
        for i, target in enumerate(positions):
            stage.move_to(target)
            stage.wait_move()
            time.sleep(settle_s)
            frame = cam.read_newest_image()
            photo_note = ""
            if frame is None:
                intensity = float("nan")
            else:
                intensity = roi_mean(np.squeeze(frame), roi)
                if save_frames_dir is not None:
                    if use_mm:
                        assert positions_mm is not None
                        tag = f"{positions_mm[i]:.4f}".replace(".", "p")
                        snap = save_frames_dir / f"position_{tag}mm.png"
                    else:
                        snap = save_frames_dir / f"position_{int(target):09d}_steps.png"
                    _save_scan_snapshot(snap, frame)
                    photo_note = f"  photo={snap.name}"
            t = time.perf_counter()
            actual_pos = stage.get_position()
            if use_mm:
                pos_out = float(actual_pos) * 1e3
            else:
                pos_out = float(actual_pos)
            rows.append((t, pos_out, intensity))
            if use_mm:
                print(f"  [{i+1}/{npos}] pos={pos_out:.6f} mm  I_mean={intensity:.4g}{photo_note}")
            else:
                print(f"  [{i+1}/{npos}] steps={int(target)}  I_mean={intensity:.4g}{photo_note}")
            if live_plot and live_ax is not None:
                pos_plot = [r[1] for r in rows]
                int_plot = [r[2] for r in rows]
                live_ax.clear()
                live_ax.plot(
                    pos_plot, int_plot, ".-", lw=1, color=_POSTER_COLORS["line_primary"]
                )
                if use_mm:
                    live_ax.set_xlabel(_LAB["x_mm"])
                else:
                    live_ax.set_xlabel(_LAB["x_steps"])
                live_ax.set_ylabel(_LAB["roi_counts"])
                live_ax.set_title("Live: fringe scan (stepping)")
                live_ax.grid(True, alpha=0.3)
                assert live_fig is not None
                live_fig.canvas.draw_idle()
                live_fig.canvas.flush_events()
                plt.pause(0.001)

        # Return stage to starting position (default behavior).
        if return_to_start:
            if use_mm:
                assert start_mm is not None
                print(f"Returning stage to start position ({start_mm:.6f} mm)...")
                stage.move_to(start_mm * 1e-3)
            else:
                assert start_steps is not None
                print(f"Returning stage to start position ({start_steps} steps)...")
                stage.move_to(start_steps)
            stage.wait_move()
            time.sleep(settle_s)
    finally:
        if live_fig is not None:
            plt.ioff()
            plt.close(live_fig)
        cam.stop_acquisition()
        cam.close()
        stage.close()

    # Write CSV.
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if use_mm:
            w.writerow(["time_s_monotonic", "position_mm", "intensity_mean"])
        else:
            w.writerow(["time_s_monotonic", "position_steps", "intensity_mean"])
        t0 = rows[0][0]
        for t, pos, ims in rows:
            w.writerow([f"{t - t0:.6f}", f"{pos:.8g}", f"{ims:.8g}"])

    # Write metadata sidecar.
    if use_mm:
        assert start_mm is not None and stop_mm is not None and step_mm is not None
        meta.extra["scan_start_mm"] = start_mm
        meta.extra["scan_stop_mm"] = stop_mm
        meta.extra["scan_step_mm"] = step_mm
        meta.extra["scan_units"] = "mm"
        meta.extra["pylablib_scale"] = cfg.get("pylablib_scale")
    else:
        assert start_steps is not None and stop_steps is not None and step_steps is not None
        meta.extra["scan_start_steps"] = start_steps
        meta.extra["scan_stop_steps"] = stop_steps
        meta.extra["scan_step_steps"] = step_steps
        meta.extra["scan_units"] = "encoder_steps"
    meta.extra["n_positions"] = npos
    if save_frames_dir is not None:
        meta.extra["scan_save_frames_dir"] = str(save_frames_dir.resolve())
    meta.extra["return_to_start"] = return_to_start
    if return_to_start:
        if use_mm:
            meta.extra["returned_to_start_mm"] = start_mm
        else:
            meta.extra["returned_to_start_steps"] = start_steps
    write_sidecar(out_csv, meta)

    # Quick-look plot 1: intensity vs stage position (interferogram).
    t_arr, pos_arr, int_arr = zip(*rows)
    t_rel = np.asarray(t_arr, dtype=float) - float(t_arr[0])
    qc = _POSTER_COLORS
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.plot(pos_arr, int_arr, ".-", lw=1, color=qc["line_primary"])
    if use_mm:
        ax.set_xlabel(_LAB["x_mm"])
    else:
        ax.set_xlabel(_LAB["x_steps"])
    ax.set_ylabel(_LAB["roi_counts"])
    ax.set_title("Fringe scan: intensity vs. mirror position (quick look)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    plot_path = out_csv.with_suffix(".scan.png")
    _finalize_figure(fig, plot_path, show=show_plots)

    # Quick-look plot 2: intensity vs elapsed time.
    fig2, ax2 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax2.plot(t_rel, int_arr, ".-", lw=1, color=qc["time_trace"])
    ax2.set_xlabel("Elapsed time (s)")
    ax2.set_ylabel(_LAB["roi_counts"])
    ax2.set_title(
        "Fringe scan: mean intensity vs. time (stage stepped in visit order)"
    )
    ax2.grid(True, alpha=0.3)
    fig2.tight_layout()
    plot_time = out_csv.with_name(out_csv.stem + "_intensity_vs_time.png")
    _finalize_figure(fig2, plot_time, show=show_plots)

    return out_csv


# --- Section: run_continuous_scan ---

def run_continuous_scan(
    *,
    roi: tuple[int, int, int, int],
    velocity_mm_s: float,
    distance_mm: float,
    out_csv: Path,
    stage_serial: str | None,
    cam_serial: str | None,
    meta_extra: dict[str, Any],
    return_to_start: bool = True,
    save_frames_dir: Path | None = None,
    save_frames_every: int = 15,
    stage_config_path: Path | None = None,
    show_plots: bool = False,
    live_plot: bool = False,
    return_velocity_mm_s: float | None = None,
    max_samples: int = 1200,
    max_duration_s: float | None = 120.0,
) -> Path:
    """FTS continuous scan: constant-velocity mirror motion + camera sampling.

    Instead of discrete step-and-measure, the mirror moves at constant
    velocity *v* while the camera samples at its natural frame rate *fs*.
    Each optical frequency nu produces a beat at f = 2*v*nu/c, so the
    camera's Nyquist limit (fs/2) sets the maximum observable optical
    frequency.  The laser wavelength is recovered from:

        lambda = 2 * v / f_beat

    Positions are recorded from the **encoder readback** (not commanded),
    so analyze-scan works on the output CSV unchanged.
    """
    cfg = load_stage_config(stage_config_path)
    scale_name = str(cfg.get("pylablib_scale", "step"))
    if scale_name == "step":
        raise RuntimeError(
            "continuous-scan requires stage_config.json with pylablib_scale "
            "set to a named stage (e.g. Z825)."
        )

    stage = setup_stage(stage_serial, scale=scale_name, stage_config=cfg)
    cam = setup_camera(cam_serial)
    if cam is None:
        stage.close()
        raise RuntimeError("Thorcam required for continuous scan.")

    if save_frames_every < 1:
        raise ValueError("save_frames_every must be >= 1")
    if max_samples < 1:
        raise ValueError("max_samples must be >= 1")
    if max_duration_s is not None and max_duration_s < 0:
        raise ValueError("max_duration_s must be non-negative (use 0 in CLI to disable)")
    if distance_mm <= 0.0 or distance_mm > 1.0:
        raise ValueError(
            "continuous-scan: --distance-mm must be in (0, 1.0] mm (max travel 1.0 mm)."
        )

    dist_m = distance_mm * 1e-3

    start_pos_m = stage.get_position()
    start_mm = float(start_pos_m) * 1e3
    target_m = start_pos_m + dist_m
    target_mm = float(target_m) * 1e3

    # Set stage velocity for the FTS crawl (slow; set via pylablib or Kinesis).
    if _try_set_stage_velocity_mm_s(stage, velocity_mm_s):
        print(f"  Stage velocity set to {velocity_mm_s:.6f} mm/s via pylablib")
    else:
        print(
            f"  WARNING: could not set velocity via pylablib.\n"
            f"  Set max velocity to {velocity_mm_s} mm/s in Kinesis GUI before continuing."
        )

    lambda_est_nm = 650.0
    f_beat = 2.0 * velocity_mm_s / (lambda_est_nm * 1e-6)
    fs_est = 20.0
    duration_est = distance_mm / velocity_mm_s
    n_fringes_est = distance_mm / (lambda_est_nm * 1e-6 / 2.0)

    print(f"\n--- Continuous scan (FTS) parameters ---")
    print(f"  Velocity:          {velocity_mm_s:.6f} mm/s")
    print(f"  Distance:          {distance_mm:.4f} mm  ({start_mm:.4f} -> {target_mm:.4f} mm)")
    print(f"  Est. duration:     {duration_est:.1f} s")
    print(f"  Beat freq (~650nm):{f_beat:.2f} Hz")
    nyq_ok = f_beat < fs_est / 2
    if nyq_ok:
        print(f"  Nyquist check:     OK  (f_beat {f_beat:.2f} < fs/2 ~{fs_est/2:.1f} Hz)")
    else:
        print(f"  WARNING: f_beat {f_beat:.1f} Hz >= Nyquist ~{fs_est/2:.1f} Hz! Lower velocity.")
    print(f"  Est. fringes:      ~{n_fringes_est:.0f}")
    print(f"  Wavelength formula: lambda = 2*v / f_peak")
    print(f"  Max samples:       {max_samples} (stop when reached or scan ends)")
    if max_duration_s is not None and max_duration_s > 0:
        print(f"  Max duration:      {max_duration_s:.1f} s (stop when reached or scan ends)")
    print(f"  Max travel:        1.0 mm (--distance-mm cap)")
    if save_frames_dir is not None:
        print(
            f"  Save frames:       every {save_frames_every} frame(s) -> {save_frames_dir}"
        )
    print(f"----------------------------------------\n")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[float, float, float]] = []
    live_fig = None
    live_ax = None
    last_live_t = 0.0
    interrupted = False
    stopped_at_sample_cap = False
    stopped_at_duration_cap = False

    try:
        cam.start_acquisition()
        time.sleep(0.3)

        if live_plot:
            plt.ion()
            live_fig, live_ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)

        stage.move_to(target_m)
        t_start = time.perf_counter()

        last_report = 0.0
        frame_idx = 0
        try:
            while True:
                t = time.perf_counter() - t_start
                if max_duration_s is not None and max_duration_s > 0 and t > max_duration_s:
                    stopped_at_duration_cap = True
                    print(
                        f"  Max duration ({max_duration_s:.1f} s) reached; stopping capture.",
                        flush=True,
                    )
                    break
                if not stage.is_moving() and t > 2.0:
                    break
                # Allow extra headroom: real motion can be slower than commanded velocity.
                time_limit_s = duration_est * 2.25 + 60.0
                if t > time_limit_s:
                    print(
                        f"  Timeout reached ({time_limit_s:.0f} s cap), stopping capture. "
                        "Increase cap in code or reduce --distance-mm if this triggers early."
                    )
                    break

                frame = cam.read_newest_image()
                if frame is not None:
                    pos_m = stage.get_position()
                    pos_mm = float(pos_m) * 1e3
                    intensity = roi_mean(np.squeeze(frame), roi)
                    rows.append((t, pos_mm, intensity))

                    if save_frames_dir is not None and frame_idx % save_frames_every == 0:
                        tag = f"{pos_mm:.4f}".replace(".", "p")
                        snap_path = save_frames_dir / f"frame_{frame_idx:06d}_{tag}mm.png"
                        _save_scan_snapshot(snap_path, frame)

                    frame_idx += 1
                    if live_plot and live_ax is not None and (
                        frame_idx % 30 == 0 or t - last_live_t >= 0.5
                    ):
                        pos_arr = np.array([r[1] for r in rows])
                        int_arr = np.array([r[2] for r in rows])
                        live_ax.clear()
                        live_ax.plot(
                            pos_arr, int_arr, lw=0.5, color=_POSTER_COLORS["line_primary"]
                        )
                        live_ax.set_xlabel(_LAB["x_mm"])
                        live_ax.set_ylabel(_LAB["roi_counts"])
                        live_ax.set_title("Live: continuous scan")
                        live_ax.grid(True, alpha=0.3)
                        assert live_fig is not None
                        live_fig.canvas.draw_idle()
                        live_fig.canvas.flush_events()
                        plt.pause(0.001)
                        last_live_t = t
                    if t - last_report >= 10.0:
                        n = len(rows)
                        rate = n / t if t > 0 else 0
                        print(
                            f"  ... {n} samples, {t:.1f} s, pos={pos_mm:.4f} mm, "
                            f"~{rate:.1f} Hz"
                        )
                        last_report = t
                    if len(rows) >= max_samples:
                        stopped_at_sample_cap = True
                        print(
                            f"  Max samples ({max_samples}) reached; stopping capture.",
                            flush=True,
                        )
                        break
        except KeyboardInterrupt:
            interrupted = True
            print("\nInterrupted (Ctrl+C); stopping capture.", flush=True)
    finally:
        if live_fig is not None:
            plt.ioff()
            plt.close(live_fig)
        cam.stop_acquisition()
        cam.close()

    if len(rows) < 8:
        stage.close()
        if interrupted:
            print(
                "Too few samples before interrupt; no CSV written. "
                "Let the scan run longer or reduce --distance-mm for a shorter run.",
                flush=True,
            )
            raise SystemExit(130)
        raise RuntimeError("Too few samples captured; check velocity and camera.")

    if interrupted:
        print(
            f"  Capture stopped by user: {len(rows)} samples over {rows[-1][0]:.1f} s "
            f"(partial run; CSV and plots still written)",
            flush=True,
        )
    elif stopped_at_duration_cap:
        print(
            f"  Capture complete (time cap): {len(rows)} samples over {rows[-1][0]:.1f} s",
            flush=True,
        )
    elif stopped_at_sample_cap:
        print(
            f"  Capture complete (sample cap): {len(rows)} samples over {rows[-1][0]:.1f} s",
            flush=True,
        )
    else:
        print(f"  Capture complete: {len(rows)} samples over {rows[-1][0]:.1f} s")

    ret_v_used: float | None = None
    if return_to_start:
        ret_v = return_velocity_mm_s
        if ret_v is None:
            ret_v = float(
                (cfg.get("kinesis") or {}).get("return_velocity_mm_s", 2.2)
            )
        ret_v_used = ret_v
        print(
            f"Returning stage to start ({start_mm:.4f} mm) at {ret_v:.3g} mm/s "
            f"(faster than FTS crawl; see stage_config kinesis.return_velocity_mm_s)..."
        )
        if _try_set_stage_velocity_mm_s(stage, ret_v):
            print(f"  Return velocity set to {ret_v:.6g} mm/s via pylablib")
        else:
            print(
                f"  WARNING: could not set return velocity via pylablib. "
                f"Set max velocity to ~{ret_v:.2f} mm/s in Kinesis for a fast return."
            )
        stage.move_to(start_pos_m)
        stage.wait_move()
    stage.close()

    actual_dist = rows[-1][1] - rows[0][1]
    actual_dur = rows[-1][0] - rows[0][0]
    actual_v = actual_dist / actual_dur if actual_dur > 0 else 0

    # CSV (same format as step-scan so analyze-scan works unchanged).
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s_monotonic", "position_mm", "intensity_mean"])
        t0 = rows[0][0]
        for t, pos, ims in rows:
            w.writerow([f"{t - t0:.6f}", f"{pos:.8g}", f"{ims:.8g}"])

    meta = AcquisitionMeta(
        created_utc=datetime.now(timezone.utc).isoformat(),
        mode="continuous_scan",
        extra={
            **meta_extra,
            "scan_mode": "continuous_fts",
            "commanded_velocity_mm_s": velocity_mm_s,
            "actual_velocity_mm_s": actual_v,
            "commanded_distance_mm": distance_mm,
            "actual_distance_mm": actual_dist,
            "actual_duration_s": actual_dur,
            "scan_units": "mm",
            "pylablib_scale": cfg.get("pylablib_scale"),
            "n_samples": len(rows),
            "user_interrupt": interrupted,
            "max_samples_cap": max_samples,
            "stopped_at_sample_cap": stopped_at_sample_cap,
            "stopped_at_duration_cap": stopped_at_duration_cap,
            "max_duration_s": max_duration_s,
            "max_travel_mm": 1.0,
            "return_to_start": return_to_start,
            "return_velocity_mm_s": ret_v_used,
            "position_source": "encoder_readback",
            "fts_note": (
                f"lambda = 2*v/f_beat. Actual v = {actual_v:.6g} mm/s. "
                f"Use this v (not commanded) for wavelength from PSD peak."
            ),
            **(
                {
                    "scan_save_frames_dir": str(save_frames_dir.resolve()),
                    "save_frames_every_n": save_frames_every,
                }
                if save_frames_dir is not None
                else {}
            ),
        },
    )
    write_sidecar(out_csv, meta)

    # Quick-look plots.
    t_arr = np.array([r[0] - rows[0][0] for r in rows])
    pos_arr = np.array([r[1] for r in rows])
    int_arr = np.array([r[2] for r in rows])

    qc = _POSTER_COLORS
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.plot(pos_arr, int_arr, lw=0.5, color=qc["line_primary"])
    ax.set_xlabel(_LAB["x_mm"])
    ax.set_ylabel(_LAB["roi_counts"])
    ax.set_title("Continuous scan: intensity vs. mirror position (encoder readback)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    plot_path = out_csv.with_suffix(".scan.png")
    _finalize_figure(fig, plot_path, show=show_plots)

    fig2, ax2 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax2.plot(t_arr, int_arr, lw=0.5, color=qc["time_trace"])
    ax2.set_xlabel(_LAB["time_s"])
    ax2.set_ylabel(_LAB["roi_counts"])
    ax2.set_title("Continuous scan: mean intensity vs. time")
    ax2.grid(True, alpha=0.3)
    fig2.tight_layout()
    plot_time = out_csv.with_name(out_csv.stem + "_intensity_vs_time.png")
    _finalize_figure(fig2, plot_time, show=show_plots)

    print(f"\n--- Continuous scan summary ---")
    print(f"  Actual velocity: {actual_v:.6g} mm/s")
    print(f"  Actual distance: {actual_dist:.6g} mm in {actual_dur:.1f} s")
    print(f"  Samples: {len(rows)}")
    print(f"  Use: analyze-scan {out_csv} --out-dir my_poster_bundle/figures")
    if save_frames_dir is not None:
        print(
            f"  Saved PNGs: analyze-frames --frames-dir {save_frames_dir} "
            f"--roi-file roi_config.json --out-dir my_poster_bundle/frames_analysis"
        )
    print(f"-------------------------------\n")

    return out_csv


# --- Section: run_timeseries ---

def run_timeseries(
    *,
    roi: tuple[int, int, int, int],
    max_samples: int | None,
    duration_s: float | None,
    settle_s: float,
    out_csv: Path,
    cam_serial: str | None,
    meta_extra: dict[str, Any],
    show_plots: bool = False,
    live_plot: bool = False,
) -> Path:
    """Record ROI-mean intensity vs clock time at a fixed stage position.

    Stops when **either** limit is hit (whichever comes first): ``duration_s``
    wall time or ``max_samples`` valid frames. Either limit may be omitted
    (``None``) to use only the other.
    """
    if max_samples is None and duration_s is None:
        raise ValueError("Provide at least one of max_samples or duration_s")
    cam = setup_camera(cam_serial)
    if cam is None:
        raise RuntimeError("Thorcam required for time-domain capture.")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    meta = AcquisitionMeta(
        created_utc=datetime.now(timezone.utc).isoformat(),
        mode="timeseries",
        settle_s=settle_s,
        extra=meta_extra,
    )

    rows: list[tuple[float, float]] = []
    progress_every_s = 10.0
    progress_every_n = 500
    last_progress_t = 0.0
    last_progress_n = 0
    live_fig = None
    live_ax = None
    last_live_t = 0.0
    try:
        cam.start_acquisition()
        time.sleep(settle_s)
        if live_plot:
            plt.ion()
            live_fig, live_ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
        t_start = time.perf_counter()
        n = 0
        lim_parts: list[str] = []
        if duration_s is not None:
            lim_parts.append(f"{duration_s:.0f} s")
        if max_samples is not None:
            lim_parts.append(f"{max_samples} samples")
        print(
            "Recording ROI mean (first progress line after ~10 s or 500 samples). "
            f"Stop when first reached: {' or '.join(lim_parts)}."
        )
        while True:
            t = time.perf_counter() - t_start
            if duration_s is not None and t > duration_s:
                break
            frame = cam.read_newest_image()
            if frame is not None:
                intensity = roi_mean(np.squeeze(frame), roi)
                rows.append((t, intensity))
                n += 1
                if live_plot and live_ax is not None and (
                    n % 200 == 0 or t - last_live_t >= 0.5
                ):
                    tt = np.array([r[0] for r in rows])
                    yy = np.array([r[1] for r in rows])
                    live_ax.clear()
                    live_ax.plot(tt, yy, lw=0.6, color=_POSTER_COLORS["psd"])
                    live_ax.set_xlabel(_LAB["time_s"])
                    live_ax.set_ylabel(_LAB["roi_counts"])
                    live_ax.set_title("Live: timeseries at fixed alignment")
                    live_ax.grid(True, alpha=0.3)
                    assert live_fig is not None
                    live_fig.canvas.draw_idle()
                    live_fig.canvas.flush_events()
                    plt.pause(0.001)
                    last_live_t = t
                if (
                    n - last_progress_n >= progress_every_n
                    or t - last_progress_t >= progress_every_s
                ):
                    rate = n / t if t > 0 else float("nan")
                    if max_samples is not None and duration_s is not None:
                        goal = f" (target {duration_s:.0f} s or {max_samples} samples)"
                    elif max_samples is not None:
                        goal = f" / {max_samples} samples"
                    else:
                        goal = f" (target {duration_s:.0f} s)"
                    print(
                        f"  ... {n} samples, {t:.1f} s elapsed, ~{rate:.2f} Hz effective{goal}"
                    )
                    last_progress_t = t
                    last_progress_n = n
                if max_samples is not None and n >= max_samples:
                    break
    finally:
        if live_fig is not None:
            plt.ioff()
            plt.close(live_fig)
        cam.stop_acquisition()
        cam.close()

    if len(rows) < 2:
        raise RuntimeError("Need at least 2 samples for analysis.")

    # Write CSV.
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "intensity_mean"])
        for t, ims in rows:
            w.writerow([f"{t:.8f}", f"{ims:.8g}"])

    # Estimate effective sample rate from timestamp spacing.
    times = np.array([r[0] for r in rows])
    if times[-1] > times[0]:
        fs_est = float((len(times) - 1) / (times[-1] - times[0]))
    else:
        fs_est = float("nan")
    meta.extra["fs_hz_estimate"] = fs_est
    meta.extra["n_samples"] = len(rows)
    if duration_s is not None:
        meta.extra["duration_limit_s"] = duration_s
    if max_samples is not None:
        meta.extra["max_samples_limit"] = max_samples
    write_sidecar(out_csv, meta)

    # Quick-look time-domain plot.
    qc = _POSTER_COLORS
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.plot(times, [r[1] for r in rows], lw=0.9, color=qc["psd"])
    ax.set_xlabel(_LAB["time_s"])
    ax.set_ylabel(_LAB["roi_counts"])
    ax.set_title("Timeseries: mean intensity vs. time (fixed alignment)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    plot_path = out_csv.with_suffix(".timeseries.png")
    _finalize_figure(fig, plot_path, show=show_plots)
    print(f"Estimated mean sample rate: {fs_est:.4g} Hz (from timestamps)")
    return out_csv


# --- Section: Analysis (time-domain PSD and spectrogram) ---

def load_timeseries_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load a time-domain CSV and return (time_s, intensity_mean) arrays."""
    times: list[float] = []
    intens: list[float] = []
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            times.append(float(row["time_s"]))
            intens.append(float(row["intensity_mean"]))
    return np.asarray(times), np.asarray(intens)


def detrend_signal(
    y: np.ndarray, t: np.ndarray, how: Literal["none", "mean", "linear"]
) -> np.ndarray:
    """Remove baseline drift before spectral analysis.

    "none"   -- return a copy unchanged.
    "mean"   -- subtract the DC offset (np.mean).
    "linear" -- fit and subtract a 1st-order polynomial (removes slow drift).
    """
    if how == "none":
        return y.copy()
    if how == "mean":
        return y - np.mean(y)
    if how == "linear":
        coeffs = np.polyfit(t, y, 1)
        return y - np.polyval(coeffs, t)
    raise ValueError(how)


def _spectrum_smooth_overlay(y: np.ndarray, j_target: int) -> np.ndarray:
    """Smooth |FFT|^2 for plotting; red peak stays on the raw maximum bin and matches its height.

    Uses Savitzky–Golay with decreasing window (largest smooth fit that keeps argmax at
    ``j_target``), then Gaussian fallback with small σ. Finally scales the curve so the
    value at ``j_target`` equals the raw peak (no short red peak vs tall blue peak).
    """
    y = np.asarray(y, dtype=np.float64)
    n = y.size
    if n < 5:
        return y.copy()
    j_target = max(0, min(int(j_target), n - 1))
    peak_raw = max(float(y[j_target]), 1e-30)

    max_w = min(121, n if n % 2 else n - 1)
    if max_w % 2 == 0:
        max_w -= 1
    max_w = max(5, max_w)

    out: np.ndarray | None = None
    for win in range(max_w, 4, -2):
        poly = min(3, win - 1)
        try:
            cand = signal.savgol_filter(y, win, poly, mode="nearest")
            cand = np.maximum(cand, 0.0)
            if int(np.argmax(cand)) == j_target:
                out = cand
                break
        except ValueError:
            continue

    if out is None:
        sigma = float(max(3.0, min(16.0, n / 30.0)))
        for _ in range(16):
            cand = np.maximum(gaussian_filter1d(y, sigma=sigma, mode="nearest"), 0.0)
            if int(np.argmax(cand)) == j_target:
                out = cand
                break
            sigma *= 0.86
            if sigma < 0.45:
                break
    if out is None:
        out = np.maximum(gaussian_filter1d(y, sigma=0.65, mode="nearest"), 0.0)

    m = max(float(out[j_target]), 1e-30)
    out = out * (peak_raw / m)
    return out


def analyze_timeseries_file(
    *,
    csv_path: Path,
    out_dir: Path,
    detrend: Literal["none", "mean", "linear"] = "linear",
    welch_nperseg: int | None = None,
    stft_nperseg: int = 256,
    stft_noverlap: int | None = None,
    meta_override: dict[str, Any] | None = None,
    show_plots: bool = False,
    psd_semilogy_ylim: tuple[float, float] | None = None,
) -> None:
    """Run Welch PSD and Gaussian-window STFT on a time-domain CSV.

    Produces *_psd.png, *_stft.png, and *_analysis.meta.json.

    The frequency axis shows how fast the ROI brightness fluctuates (Hz),
    NOT the laser optical frequency (~4e14 Hz).
    """
    t, y = load_timeseries_csv(csv_path)
    if len(y) < 8:
        raise ValueError("Too few points for spectral analysis.")

    # Sample rate from mean timestamp spacing.
    dt_mean = float(np.mean(np.diff(t)))
    fs = 1.0 / dt_mean if dt_mean > 0 else float("nan")
    nyq = 0.5 * fs

    yp = detrend_signal(y, t, detrend)

    # Welch PSD: auto-select segment length if not specified.
    nperseg = welch_nperseg or min(1024, max(16, len(yp) // 8))
    nperseg = min(nperseg, len(yp))

    f_w, pxx = signal.welch(
        yp,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        scaling="density",
        return_onesided=True,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = csv_path.stem

    pc = _POSTER_COLORS
    # -- PSD plot --
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.semilogy(f_w, pxx + 1e-30, lw=1.2, color=pc["psd"])
    ax.axvline(
        nyq, color=pc["psd_nyq"], ls="--", lw=1, label=f"Nyquist ({nyq:.3g} Hz)"
    )
    ax.set_xlabel(_LAB["f_hz"])
    ax.set_ylabel(_LAB["psd"])
    ax.set_title("Band-averaged power spectrum of intensity fluctuations")
    ax.set_xlim(0, nyq * 1.02)
    if psd_semilogy_ylim is not None:
        ax.set_ylim(*psd_semilogy_ylim)
    ax.legend(loc="upper right")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    psd_path = out_dir / f"{stem}_psd.png"
    _finalize_figure(fig, psd_path, show=show_plots)

    # -- Spectrogram (Gaussian-window STFT) --
    nper = min(stft_nperseg, len(yp))
    # Gaussian window with std = nperseg/6 gives a good time-frequency tradeoff.
    std = nper / 6.0
    win = signal.windows.gaussian(nper, std)
    # Energy-normalize the window so power levels are comparable.
    win /= np.sqrt(np.sum(win**2) / nper + 1e-30)
    nover = stft_noverlap if stft_noverlap is not None else int(0.75 * nper)

    f_s, t_s, Zxx = signal.stft(
        yp,
        fs=fs,
        window=win,
        nperseg=nper,
        noverlap=nover,
        boundary="zeros",
    )

    # Two panels: (1) detrended trace used by STFT;
    # (2) spectrogram of power vs time and Hz. Not optical fringes; expect drift/broadband noise,
    # not a clean sine unless something periodic (e.g. line frequency) dominates.
    t_ref = np.max(np.abs(Zxx)) + 1e-30
    power_db = 10.0 * np.log10(np.abs(Zxx) ** 2 / t_ref + 1e-30)
    # Widen dynamic range so the plot is not "all one color" when one bin hits 0 dB.
    vmin_db = float(max(np.percentile(power_db, 8), -55.0))
    vmax_db = 0.0

    # Two-column GridSpec: trace and spectrogram both use column 0 so their widths match.
    # The colorbar lives in column 1 (spectrogram row only). Attaching a vertical colorbar
    # to ax_spec with ax=ax_spec shrinks the heatmap and misaligns it with the trace above.
    # Margins below are fairly tight so the axes fill POSTER_FIGSIZE_IN; time vs Hz are left
    # auto-aspect (no set_aspect("equal"); that would distort a spectrogram).
    fig = plt.figure(figsize=POSTER_FIGSIZE_IN)
    gs = fig.add_gridspec(
        2,
        2,
        width_ratios=[1.0, 0.042],
        height_ratios=[1.55, 2.0],
        hspace=0.052,
        wspace=0.042,
        left=0.085,
        right=0.93,
        top=0.89,
        bottom=0.10,
    )
    ax_top = fig.add_subplot(gs[0, 0])
    ax_spec = fig.add_subplot(gs[1, 0], sharex=ax_top)
    cax = fig.add_subplot(gs[1, 1])

    ax_top.plot(t, yp, lw=0.9, color=pc["psd"])
    ax_top.set_ylabel(_LAB["stft_counts"], labelpad=12)
    ax_top.set_ylim(*POSTER_STFT_TRACE_YLIM)
    ax_top.set_yticks(POSTER_STFT_TRACE_YTICKS)
    ax_top.grid(True, alpha=0.3)
    # Tick marks on the top panel for alignment; "Time (s)" labels only on the bottom row.
    ax_top.tick_params(labelbottom=False, bottom=True)

    im = ax_spec.pcolormesh(
        t_s,
        f_s,
        power_db,
        shading="auto",
        cmap="plasma",
        vmin=vmin_db,
        vmax=vmax_db,
    )
    ax_spec.axhline(nyq, color=pc["line_secondary"], ls="--", lw=0.9, alpha=0.85)
    ax_spec.set_ylim(0, nyq)
    ax_spec.set_ylabel(_LAB["f_hz"], labelpad=12)
    fig.colorbar(im, cax=cax, label=_LAB["stft_power_db"])
    ax_spec.set_xlabel("")
    fig.suptitle("Intensity vs. time and frequency spectrum", fontsize=POSTER_FONT_PT, y=0.975)
    fig.supxlabel(_LAB["time_s"], fontsize=POSTER_FONT_PT, y=0.022)
    t_lo = min(float(np.min(t)), float(np.min(t_s)))
    t_hi = max(float(np.max(t)), float(np.max(t_s)))
    ax_top.set_xlim(t_lo, t_hi)
    ax_spec.set_xlim(t_lo, t_hi)

    def _stft_prepare_save() -> None:
        fig.canvas.draw()
        # GridSpec keeps column 0 aligned; snap after layout so the trace matches the
        # spectrogram width (do not use align_ylabels; it shifts axes by different amounts).
        pos_spec = ax_spec.get_position()
        pos_top = ax_top.get_position()
        ax_top.set_position([pos_spec.x0, pos_top.y0, pos_spec.width, pos_top.height])
        fig.canvas.draw()

    stft_path = out_dir / f"{stem}_stft.png"
    _finalize_figure(fig, stft_path, show=show_plots, before_savefig=_stft_prepare_save)

    # -- Analysis metadata --
    analysis_meta = {
        "source_csv": str(csv_path.resolve()),
        "fs_hz": fs,
        "nyquist_hz": nyq,
        "detrend": detrend,
        "welch_nperseg": nperseg,
        "stft_nperseg": nper,
        "stft_noverlap": nover,
        "analysis_utc": datetime.now(timezone.utc).isoformat(),
        "frequency_axis_note": (
            "PSD/STFT frequency (Hz) = fluctuation rate of ROI mean intensity vs time, "
            "limited by camera sampling rate (Nyquist). Not the laser optical frequency (~4e14 Hz)."
        ),
    }
    if meta_override:
        analysis_meta.update(meta_override)
    (out_dir / f"{stem}_analysis.meta.json").write_text(
        json.dumps(analysis_meta, indent=2),
        encoding="utf-8",
    )


def print_validation_hints(csv_path: Path) -> None:
    """Print sanity checks (sample count, duration, fs, Nyquist) before plots."""
    t, y = load_timeseries_csv(csv_path)
    dt = np.diff(t)
    fs = 1.0 / np.mean(dt) if np.mean(dt) > 0 else float("nan")
    print("\n--- Validation (read this before using figures) ---")
    print(f"  Samples: {len(y)}")
    print(f"  Duration: {t[-1] - t[0]:.4g} s")
    print(f"  Mean dt: {np.mean(dt):.6g} s  (std {np.std(dt):.6g} s)")
    print(f"  Estimated fs: {fs:.5g} Hz; Nyquist: {0.5*fs:.5g} Hz")
    print("  Do not interpret spectral peaks above Nyquist.")
    print(
        "  PSD/STFT Hz axis = fluctuation rate of ROI intensity vs time (drift, vibration, noise)."
    )
    print(
        "  This is NOT the laser optical frequency (~4e14 Hz); the camera samples ~10-30 Hz."
    )
    print("----------------------------------------------------\n")


# --- Section: Analysis (scan FFT and wavelength recovery) ---

def load_scan_csv(path: Path) -> tuple[np.ndarray, np.ndarray, str]:
    """Load a scan CSV and return (positions, intensities, unit).

    Auto-detects the position column: 'position_mm' or 'position_steps'.
    """
    positions: list[float] = []
    intens: list[float] = []
    unit = "steps"
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        fields = r.fieldnames or []
        if "position_mm" in fields:
            pos_col = "position_mm"
            unit = "mm"
        elif "position_steps" in fields:
            pos_col = "position_steps"
            unit = "steps"
        else:
            raise ValueError(
                f"Scan CSV must have 'position_mm' or 'position_steps'; found {fields}"
            )
        for row in r:
            positions.append(float(row[pos_col]))
            intens.append(float(row["intensity_mean"]))
    return np.asarray(positions), np.asarray(intens), unit


def _sigma_fr_per_mm_range_from_lambda_nm(
    lambda_min_nm: float, lambda_max_nm: float
) -> tuple[float, float]:
    """Map wavelength band (nm) to spatial frequency band (fringes/mm).

    Michelson double-pass: lambda_nm = 2/sigma * 1e6  =>  sigma = 2e6/lambda_nm.
    Short wavelength corresponds to high sigma.
    """
    if lambda_min_nm <= 0 or lambda_max_nm <= 0 or lambda_min_nm >= lambda_max_nm:
        raise ValueError("Need 0 < lambda_min_nm < lambda_max_nm")
    sigma_at_short_lambda = 2e6 / lambda_min_nm
    sigma_at_long_lambda = 2e6 / lambda_max_nm
    return sigma_at_long_lambda, sigma_at_short_lambda


def _symmetric_wavelength_xlim(peak_nm: float) -> tuple[float, float]:
    """Wavelength axis limits centered on the recovered peak (symmetric span in nm)."""
    lo_band, hi_band = 400.0, 1000.0
    d_lo = peak_nm - lo_band
    d_hi = hi_band - peak_nm
    if d_lo > 0 and d_hi > 0:
        half = min(d_lo, d_hi)
    else:
        half = max(abs(d_lo), abs(d_hi), 250.0)
    if half < 50 or not np.isfinite(half):
        half = 250.0
    xmin = max(200.0, peak_nm - half)
    xmax = min(1200.0, peak_nm + half)
    return xmin, xmax


def _pick_interferogram_fft_peak(
    freqs: np.ndarray,
    power: np.ndarray,
    *,
    unit: str,
    peak_search_lambda_nm: tuple[float, float] | None,
) -> tuple[int, str, str | None]:
    """Choose FFT bin for fringe carrier; avoid spurious low-spatial-frequency maxima.

    For ``position_mm`` data, optional ``peak_search_lambda_nm`` restricts the search
    to spatial frequencies consistent with that visible/NIR band (default in
    ``analyze_scan_file``). Continuous FTS rows are unevenly spaced in x; the FFT
    still uses mean ``dx`` (same as before), but the **global** argmax often locks
    onto drift/envelope instead of fringes unless restricted.

    Returns (peak_idx, method, warning_or_none).
    """
    power_no_dc = power.copy()
    power_no_dc[0] = 0

    if unit != "mm" or peak_search_lambda_nm is None:
        idx = int(np.argmax(power_no_dc))
        return idx, "global_argmax", None

    lo_nm, hi_nm = peak_search_lambda_nm
    smin, smax = _sigma_fr_per_mm_range_from_lambda_nm(lo_nm, hi_nm)
    in_band = (freqs > 0) & (freqs >= smin) & (freqs <= smax)
    if not np.any(in_band):
        idx = int(np.argmax(power_no_dc))
        w = (
            f"No FFT bins between σ={smin:.4g} and {smax:.4g} fr/mm "
            f"(λ≈{lo_nm:.0f}–{hi_nm:.0f} nm); fell back to global argmax."
        )
        return idx, "global_argmax_fallback", w

    masked = power_no_dc.copy()
    masked[~in_band] = 0.0
    idx = int(np.argmax(masked))
    if masked[idx] <= 0:
        idx = int(np.argmax(power_no_dc))
        return idx, "global_argmax_fallback", (
            "Band-limited search found no power in-band; fell back to global argmax."
        )
    return idx, "band_limited_lambda_nm", None


def _plot_scan_constructive_destructive_real(
    pos: np.ndarray,
    yp: np.ndarray,
    *,
    unit: str,
    out_path: Path,
    show_plots: bool,
) -> None:
    """Shade constructive (bright) vs destructive (dark) using detrended interferogram."""
    yn = (yp - np.min(yp)) / (np.max(yp) - np.min(yp) + 1e-15)
    c = _POSTER_COLORS
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.fill_between(
        pos,
        0,
        yn,
        where=yn >= 0.5,
        color=c["constructive"],
        alpha=0.42,
        interpolate=True,
        label="Constructive (bright)",
    )
    ax.fill_between(
        pos,
        0,
        yn,
        where=yn < 0.5,
        color=c["destructive"],
        alpha=0.42,
        interpolate=True,
        label="Destructive (dark)",
    )
    ax.plot(pos, yn, color=c["overlay_line"], lw=1.25)
    if unit == "mm":
        ax.set_xlabel(_LAB["x_mm"])
    else:
        ax.set_xlabel(_LAB["x_steps"])
    ax.set_ylabel(_LAB["norm_I"])
    ax.set_title("Bright vs dark fringes (min–max normalized)")
    ax.legend(loc="upper right", framealpha=0.92)
    ax.set_ylim(-0.05, 1.05)
    fig.tight_layout()
    _finalize_figure(fig, out_path, show=show_plots)


def _plot_scan_phase_colored_line(
    pos: np.ndarray,
    yp: np.ndarray,
    *,
    unit: str,
    out_path: Path,
    show_plots: bool,
) -> None:
    """Interferogram line colored by analytic-signal phase (Hilbert), real data."""
    if float(np.std(yp)) < 1e-12 * (abs(float(np.mean(yp))) + 1.0):
        return
    analytic = signal.hilbert(yp.astype(np.float64))
    phase = np.unwrap(np.angle(analytic))
    phase_wrapped = (phase - phase[0]) % (2.0 * np.pi)
    yn = (yp - np.min(yp)) / (np.max(yp) - np.min(yp) + 1e-15)
    points = np.array([pos, yn]).T.reshape(-1, 1, 2)
    segs = np.concatenate([points[:-1], points[1:]], axis=1)
    norm = mcolors.Normalize(0.0, 2.0 * np.pi)
    lc = LineCollection(segs, cmap="cool", norm=norm, linewidths=2.5)
    lc.set_array(0.5 * (phase_wrapped[:-1] + phase_wrapped[1:]))
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.add_collection(lc)
    ax.set_xlim(float(np.min(pos)), float(np.max(pos)))
    ax.set_ylim(float(np.min(yn)) - 0.05, float(np.max(yn)) + 0.05)
    sm = mpl_cm.ScalarMappable(cmap="cool", norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, label="Phase (rad)")
    if unit == "mm":
        ax.set_xlabel(_LAB["x_mm"])
    else:
        ax.set_xlabel(_LAB["x_steps"])
    ax.set_ylabel(_LAB["norm_I"])
    ax.set_title("Fringe phase along the scan (color encodes phase)")
    fig.tight_layout()
    _finalize_figure(fig, out_path, show=show_plots)


def analyze_scan_file(
    *,
    csv_path: Path,
    out_dir: Path,
    detrend: Literal["none", "mean", "linear"] = "linear",
    show_plots: bool = False,
    peak_search_lambda_nm: tuple[float, float] | None = (400.0, 900.0),
) -> None:
    """FFT the interferogram (intensity vs position) to recover laser wavelength.

    Michelson interferometer physics:
        OPD = 2 * mirror_displacement   (double-pass: light goes to mirror and back)
        Fringe spacing = lambda / 2      (in mirror travel)
        FFT peak at spatial freq sigma = 2 / lambda   (fringes per mm)
        Therefore: lambda = 2 / sigma

    For **mm** scans, the default peak picker searches only spatial frequencies
    consistent with **peak_search_lambda_nm** (default 400–900 nm) so that
    continuous-scan interferograms do not pick a spurious low-frequency maximum.

    Produces *_interferogram.png, *_constructive_destructive.png, *_phase_colored.png,
    *_spectrum.png, *_wavelength.png (mm scans), and *_scan_analysis.meta.json.
    """
    pos, intensity, unit = load_scan_csv(csv_path)
    if len(pos) < 8:
        raise ValueError("Too few scan points for spectral analysis.")

    if unit == "steps":
        print(
            "WARNING: scan CSV uses encoder steps, not mm. The spectrum x-axis "
            "will be in 1/steps, which is not physically meaningful for wavelength "
            "recovery. Re-run the scan with --start-mm/--stop-mm/--step-mm for "
            "proper wavelength extraction."
        )

    # Mean step size sets the FFT frequency axis resolution.
    dx = np.diff(pos)
    dx_mean = float(np.mean(dx))
    if dx_mean == 0:
        raise ValueError("All positions are the same; cannot compute spectrum.")

    yp = detrend_signal(intensity, pos, detrend)

    # Real-valued input -> rfft is sufficient and twice as fast as fft.
    N = len(yp)
    fft_vals = np.fft.rfft(yp)
    power = np.abs(fft_vals) ** 2
    freqs = np.fft.rfftfreq(N, d=abs(dx_mean))

    peak_idx, peak_method, peak_warn = _pick_interferogram_fft_peak(
        freqs, power, unit=unit, peak_search_lambda_nm=peak_search_lambda_nm
    )
    sigma_peak = float(freqs[peak_idx])
    if peak_warn:
        print(f"WARNING: {peak_warn}", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = csv_path.stem
    pc = _POSTER_COLORS

    # -- Plot 1: Interferogram --
    fig1, ax1 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax1.plot(
        pos,
        intensity,
        ".-",
        lw=1.0,
        markersize=2,
        color=pc["line_primary"],
        markerfacecolor=pc["line_secondary"],
        markeredgecolor=pc["overlay_line"],
        markeredgewidth=0.3,
    )
    if unit == "mm":
        ax1.set_xlabel(_LAB["x_mm"])
    else:
        ax1.set_xlabel(_LAB["x_steps"])
    ax1.set_ylabel(_LAB["roi_counts"])
    ax1.set_title("Interferogram: mean intensity vs. mirror position")
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    igram_path = out_dir / f"{stem}_interferogram.png"
    _finalize_figure(fig1, igram_path, show=show_plots)

    # -- Real data: constructive / destructive + phase-colored fringe line --
    cd_path = out_dir / f"{stem}_constructive_destructive.png"
    _plot_scan_constructive_destructive_real(
        pos,
        yp,
        unit=unit,
        out_path=cd_path,
        show_plots=show_plots,
    )
    phase_path = out_dir / f"{stem}_phase_colored.png"
    _plot_scan_phase_colored_line(
        pos,
        yp,
        unit=unit,
        out_path=phase_path,
        show_plots=show_plots,
    )

    # -- Plot 2: Spectrum (spatial frequency) --
    f_spec = freqs[1:]
    p_spec = power[1:].astype(np.float64)
    # Global argmax (excl. DC) often locks onto slow drift/envelope for long continuous scans;
    # physics + poster use the same peak as _pick_interferogram_fft_peak (band-limited in mm).
    j_global = int(np.argmax(p_spec))
    sigma_global_argmax = float(f_spec[j_global])
    j_plot = int(peak_idx) - 1
    if j_plot < 0 or j_plot >= len(p_spec):
        j_plot = j_global
    p_smooth = _spectrum_smooth_overlay(p_spec, j_plot)
    fig2, ax2 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax2.plot(
        f_spec,
        p_spec,
        lw=1.05,
        color=pc["spectrum"],
        alpha=0.92,
        zorder=1,
    )
    ax2.plot(
        f_spec,
        p_smooth,
        lw=2.15,
        color=pc["spectrum_smooth"],
        zorder=3,
    )
    if unit == "mm":
        ax2.set_xlabel(_LAB["sigma_mm"])
    else:
        ax2.set_xlabel(_LAB["sigma_step"])
    ax2.set_ylabel(_LAB["power"])
    ax2.set_title("Spatial-frequency spectrum of the interferogram")
    ax2.grid(True, alpha=0.3)

    # Vertical line and λ: σ from band-limited picker (same bin as red smooth overlay target).
    lambda_nm: float | None = None
    if sigma_peak > 0:
        ax2.axvline(
            sigma_peak,
            color=pc["peak_mark"],
            ls="--",
            lw=1.2,
            alpha=0.9,
            zorder=2,
        )
        if unit == "mm":
            lambda_nm = float(2.0 / sigma_peak * 1e6)
            ax2.annotate(
                f"Spatial frequency = {sigma_peak:.2f} mm⁻¹\n"
                f"Wavelength = {lambda_nm:.1f} nm",
                xy=(sigma_peak, p_spec[j_plot]),
                xytext=(sigma_peak * 1.15, p_spec[j_plot] * 0.8),
                fontsize=POSTER_FONT_PT,
                arrowprops=dict(arrowstyle="->", color=pc["peak_mark"]),
                color=pc["peak_mark"],
            )
        # Zoom x-axis so the fringe band fills the frame (avoids empty high-frequency tail).
        if unit == "mm":
            x_max = min(float(freqs[-1]), max(5000.0, float(sigma_peak) * 1.75))
            ax2.set_xlim(0.0, x_max)

    fig2.tight_layout()
    spec_path = out_dir / f"{stem}_spectrum.png"
    _finalize_figure(fig2, spec_path, show=show_plots)

    # -- Plot 3: Wavelength axis (mm scans only) --
    if unit == "mm" and sigma_peak > 0:
        mask = freqs > 0
        # Convert spatial freq (fringes/mm) to wavelength (nm):
        # lambda = 2 / freq (mm) * 1e6 (nm/mm)
        wavelengths_nm = 2.0 / freqs[mask] * 1e6
        fig3, ax3 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
        ax3.plot(wavelengths_nm, power[mask], lw=1.2, color=pc["wavelength_line"])
        ax3.set_xlabel(_LAB["lambda_nm"])
        ax3.set_ylabel(_LAB["power"])
        ax3.set_title("Power vs wavelength (from spatial transform)")
        wl_lo, wl_hi = _symmetric_wavelength_xlim(float(lambda_nm))
        ax3.set_xlim(wl_lo, wl_hi)
        ax3.axvline(
            lambda_nm,
            color=pc["peak_mark"],
            ls="--",
            lw=1.2,
            alpha=0.9,
            label=f"Peak = {lambda_nm:.1f} nm",
            zorder=2,
        )
        ax3.legend(loc="upper right")
        ax3.grid(True, alpha=0.3)
        fig3.tight_layout()
        wl_path = out_dir / f"{stem}_wavelength.png"
        _finalize_figure(fig3, wl_path, show=show_plots)

    # -- Metadata --
    meta: dict[str, Any] = {
        "source_csv": str(csv_path.resolve()),
        "position_unit": unit,
        "n_points": N,
        "dx_mean": dx_mean,
        "detrend": detrend,
        "peak_spatial_freq": float(sigma_peak),
        "peak_selection_method": peak_method,
        "analysis_utc": datetime.now(timezone.utc).isoformat(),
    }
    if unit == "mm" and sigma_peak > 0:
        meta["global_argmax_spatial_freq_fr_per_mm"] = float(sigma_global_argmax)
    if unit == "mm" and peak_search_lambda_nm is not None:
        meta["peak_search_lambda_nm"] = [peak_search_lambda_nm[0], peak_search_lambda_nm[1]]
    if unit == "mm" and sigma_peak > 0:
        assert lambda_nm is not None
        meta["recovered_wavelength_nm"] = float(lambda_nm)
        meta["wavelength_note"] = (
            "lambda = 2/sigma (Michelson double-pass). For mm scans, sigma is the band-limited "
            "carrier peak in |FFT|^2 (default search ~400–900 nm), not the global spectrum maximum "
            "(which often tracks slow drift on long continuous scans). Compare global_argmax_spatial_freq_fr_per_mm."
        )
        # Typical red HeNe ~633 nm; diodes ~635-660 nm. Warn if FFT lambda is not poster-credible.
        if lambda_nm < 620.0 or lambda_nm > 680.0:
            meta["poster_plausibility"] = (
                f"Recovered λ={lambda_nm:.1f} nm is outside a typical red-laser band (~620–680 nm). "
                "Do not use as primary reported λ without checking the FFT peak; stepped scans "
                "often agree better with the source label than long continuous scans."
            )
    if sigma_peak > 0:
        meta["spectrum_plot_overlay"] = (
            "Red: Savitzky–Golay (or Gaussian fallback) on |FFT|^2, largest smooth window that keeps "
            "argmax on the selected carrier bin; then scaled so red height at that bin equals blue. "
            "Orange line: band-limited carrier σ (mm scans) or global argmax (steps)."
        )
    meta_path = out_dir / f"{stem}_scan_analysis.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Metadata: {meta_path}")

    # -- Terminal summary --
    print(f"\n--- Scan analysis summary ---")
    print(f"  Points: {N}, dx_mean: {dx_mean:.6g} {unit}")
    if unit == "mm" and sigma_peak > 0:
        print(f"  Peak spatial freq (carrier, band-limited): {sigma_peak:.4g} fringes/mm")
        print(f"  Recovered wavelength: {lambda_nm:.1f} nm")
        print(f"  (Expected for red HeNe: ~632.8 nm; red diode: ~635-660 nm)")
        if lambda_nm < 620.0 or lambda_nm > 680.0:
            print(
                f"  WARNING: λ={lambda_nm:.1f} nm is atypical for red sources; "
                "prefer stepped-scan λ for the poster or re-check FFT peak.",
                file=sys.stderr,
            )
    elif sigma_peak > 0:
        print(f"  Peak spatial freq: {sigma_peak:.6g} fringes/step (use mm scan for wavelength)")
    print("-----------------------------\n")


# --- Section: Analysis (compare runs and saved frame PNGs) ---

def shared_psd_semilogy_ylim_for_two_csvs(
    path_a: Path,
    path_b: Path,
    *,
    detrend: Literal["none", "mean", "linear"] = "linear",
) -> tuple[float, float]:
    """Vertical axis for semilogy PSD plots so two runs share one scale (poster)."""
    def _pxx(path: Path) -> np.ndarray:
        t, y = load_timeseries_csv(path)
        yp = detrend_signal(y, t, detrend)
        dt = float(np.mean(np.diff(t)))
        fs = 1.0 / dt
        nperseg = min(1024, max(16, len(yp) // 8))
        nperseg = min(nperseg, len(yp))
        _f_w, pxx = signal.welch(
            yp,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=nperseg // 2,
            scaling="density",
            return_onesided=True,
        )
        return pxx

    pxa = _pxx(path_a)
    pxb = _pxx(path_b)
    p_all = np.concatenate([pxa, pxb])
    p_pos = p_all[p_all > 0]
    if p_pos.size:
        return (float(np.min(p_pos)) * 0.5, float(np.max(p_all)) * 2.0)
    return (1e-30, 1.0)


def compare_two_runs(
    path_a: Path,
    path_b: Path,
    label_a: str,
    label_b: str,
    out_dir: Path,
    show_plots: bool = False,
) -> None:
    """Overlay Welch PSDs from two time-domain CSVs (e.g. stable vs noisy)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def _compute_psd(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
        """Load one CSV, detrend, and compute its Welch PSD."""
        t, y = load_timeseries_csv(path)
        yp = detrend_signal(y, t, "linear")
        dt = float(np.mean(np.diff(t)))
        fs = 1.0 / dt
        nperseg = min(1024, max(16, len(yp) // 8))
        nperseg = min(nperseg, len(yp))
        f_w, pxx = signal.welch(
            yp,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=nperseg // 2,
            scaling="density",
            return_onesided=True,
        )
        return f_w, pxx, fs

    fa, pxa, fsa = _compute_psd(path_a)
    fb, pxb, fsb = _compute_psd(path_b)
    nyq = min(0.5 * fsa, 0.5 * fsb)

    pc = _POSTER_COLORS
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    ax.semilogy(fa, pxa + 1e-30, lw=1.2, color=pc["compare_a"], label=label_a)
    ax.semilogy(fb, pxb + 1e-30, lw=1.2, color=pc["compare_b"], label=label_b)
    ax.axvline(nyq, color=pc["psd_nyq"], ls="--", lw=1)
    ax.set_xlim(0, nyq * 1.02)
    ax.set_xlabel(_LAB["f_hz"])
    ax.set_ylabel(_LAB["psd"])
    ax.set_title("Power spectrum of intensity fluctuations (two conditions)")
    ax.legend()
    ax.grid(True, which="both", alpha=0.3)
    ax.set_ylim(*shared_psd_semilogy_ylim_for_two_csvs(path_a, path_b, detrend="linear"))
    fig.tight_layout()
    outp = out_dir / "compare_psd.png"
    _finalize_figure(fig, outp, show=show_plots)


def analyze_frames_folder(
    *,
    frames_dir: Path,
    roi: tuple[int, int, int, int],
    out_csv: Path,
    out_dir: Path,
    show_plots: bool = False,
) -> None:
    """Compute ROI mean and std on each snapshot PNG from ``--save-frames``.

    PNGs are min-max normalized per frame to 0-255 for visibility; ``roi_mean_u8``
    and ``roi_std_u8`` use that scale (not raw camera counts). Curves vs position
    still match the *shape* of the main interferogram for the same run.
    """
    import cv2

    frame_re = re.compile(r"^frame_(\d+)_(.+)mm\.png$", re.I)
    pos_re = re.compile(r"^position_(.+)mm\.png$", re.I)

    pngs = sorted(frames_dir.glob("*.png"))
    if not pngs:
        raise ValueError(f"No PNG files in {frames_dir}")

    rx, ry, rw, rh = roi
    rows_out: list[dict[str, Any]] = []
    for i, p in enumerate(pngs):
        img = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"  skip (unreadable): {p.name}")
            continue
        if img.ndim == 3:
            img = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY)
        ih, iw = int(img.shape[0]), int(img.shape[1])
        x0 = max(0, min(rx, iw - 1))
        y0 = max(0, min(ry, ih - 1))
        x1 = min(iw, x0 + rw)
        y1 = min(ih, y0 + rh)
        patch = img[y0:y1, x0:x1].astype(np.float64)
        if patch.size == 0:
            print(f"  skip (empty ROI): {p.name}")
            continue
        roi_mean = float(np.mean(patch))
        roi_std = float(np.std(patch))
        fidx: int | None = None
        pos_mm: float | None = None
        mf = frame_re.match(p.name)
        if mf:
            fidx = int(mf.group(1))
            pos_mm = _parse_mm_filename_token(mf.group(2))
        else:
            mp = pos_re.match(p.name)
            if mp:
                pos_mm = _parse_mm_filename_token(mp.group(1))
        rows_out.append(
            {
                "sort_index": i,
                "filename": p.name,
                "frame_index": fidx,
                "position_mm": pos_mm,
                "roi_mean_u8": roi_mean,
                "roi_std_u8": roi_std,
            }
        )

    if not rows_out:
        raise ValueError("No PNGs produced usable ROI statistics.")

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys())
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        wtr = csv.DictWriter(f, fieldnames=fieldnames)
        wtr.writeheader()
        wtr.writerows(rows_out)
    print(f"Saved {out_csv}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = frames_dir.name
    pc = _POSTER_COLORS

    has_pos = sum(1 for r in rows_out if r["position_mm"] is not None)
    fig, ax = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    if has_pos >= 2:
        order = sorted(
            (r["position_mm"], r["roi_mean_u8"])
            for r in rows_out
            if r["position_mm"] is not None
        )
        xs = [p[0] for p in order]
        ys = [p[1] for p in order]
        ax.plot(xs, ys, ".-", lw=0.9, markersize=3, color=pc["frames_mean"])
        ax.set_xlabel(_LAB["x_from_file"])
    else:
        ax.plot(
            [r["sort_index"] for r in rows_out],
            [r["roi_mean_u8"] for r in rows_out],
            ".-",
            lw=0.9,
            color=pc["frames_mean"],
        )
        ax.set_xlabel(_LAB["x_frame_order"])
    ax.set_ylabel(_LAB["roi_u8"])
    ax.set_title("Saved frames: mean ROI intensity")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.1)
    p1 = out_dir / f"{stem}_frames_roi_mean.png"
    _finalize_figure(fig, p1, show=show_plots)

    fig2, ax2 = plt.subplots(figsize=POSTER_FIGSIZE_IN)
    if has_pos >= 2:
        order2 = sorted(
            (r["position_mm"], r["roi_std_u8"])
            for r in rows_out
            if r["position_mm"] is not None
        )
        xs2 = [p[0] for p in order2]
        ys2 = [p[1] for p in order2]
        ax2.plot(xs2, ys2, ".-", lw=0.9, markersize=3, color=pc["frames_std"])
        ax2.set_xlabel(_LAB["x_from_file"])
    else:
        ax2.plot(
            [r["sort_index"] for r in rows_out],
            [r["roi_std_u8"] for r in rows_out],
            ".-",
            lw=0.9,
            color=pc["frames_std"],
        )
        ax2.set_xlabel(_LAB["x_frame_order"])
    ax2.set_ylabel(_LAB["roi_std_u8"])
    ax2.set_title("Saved frames: intensity contrast (standard deviation)")
    ax2.grid(True, alpha=0.3)
    fig2.tight_layout()
    p2 = out_dir / f"{stem}_frames_roi_std.png"
    _finalize_figure(fig2, p2, show=show_plots)

    meta_path = out_dir / f"{stem}_frames_analysis.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "frames_dir": str(frames_dir.resolve()),
                "roi_xywh": list(roi),
                "n_pngs": len(pngs),
                "n_used": len(rows_out),
                "metrics_csv": str(out_csv.resolve()),
                "note": (
                    "PNG metrics use min-max normalized 8-bit display scale "
                    "(not raw camera counts); compare shape to the main scan CSV."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Metadata: {meta_path}")


# --- Section: CLI ---

def _add_show_plots_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--show-plots",
        action="store_true",
        help=(
            "After saving each figure, open an interactive window; close it to continue. "
            "Default is save-only (no windows)."
        ),
    )


def _add_live_plot_arg(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--live-plot",
        action="store_true",
        help=(
            "During acquisition: refresh a matplotlib window as data arrives "
            "(scan, continuous-scan, or timeseries only)."
        ),
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with subcommands for each workflow step."""
    p = argparse.ArgumentParser(
        description="Interferometer acquire + analyze (Thorcam + K-Cube)."
    )
    sub = p.add_subparsers(dest="command", required=True)

    # -- scan --
    ps = sub.add_parser("scan", help="Step stage, record ROI mean vs position.")
    ps.add_argument("--roi-file", type=Path, default=Path("roi_config.json"))
    ps.add_argument(
        "--start", type=int, default=None,
        help="Scan start in raw encoder steps (default mode).",
    )
    ps.add_argument("--stop", type=int, default=None)
    ps.add_argument("--step", type=int, default=None)
    ps.add_argument(
        "--start-mm", type=float, default=None,
        help="Scan start in mm (requires stage_config.json with pylablib_scale).",
    )
    ps.add_argument("--stop-mm", type=float, default=None)
    ps.add_argument("--step-mm", type=float, default=None)
    ps.add_argument(
        "--stage-config", type=Path, default=Path("stage_config.json"),
        help="Stage model / pylablib scale config file (default: stage_config.json).",
    )
    ps.add_argument("--settle-s", type=float, default=0.2)
    ps.add_argument("--out", type=Path, default=Path("data/scan.csv"))
    ps.add_argument("--stage-serial", default=None)
    ps.add_argument("--cam-serial", default=None)
    ps.add_argument("--lambda-nm", type=float, default=None)
    ps.add_argument("--lambda-status", default="unknown")
    ps.add_argument("--notes", default="", help="Freeform notes stored in metadata JSON.")
    ps.add_argument(
        "--no-return-to-start", action="store_true",
        help="Do not return stage to start position after scan (default: return).",
    )
    ps.add_argument(
        "--save-frames", type=Path, default=None, metavar="DIR",
        help="Save one PNG per position to this folder.",
    )
    _add_show_plots_arg(ps)
    _add_live_plot_arg(ps)

    # -- timeseries --
    pt = sub.add_parser(
        "timeseries",
        help="Time-domain capture: ROI mean vs clock time at fixed alignment.",
    )
    pt.add_argument("--roi-file", type=Path, default=Path("roi_config.json"))
    pt.add_argument(
        "--duration-s",
        type=float,
        default=120.0,
        help="Stop after this many seconds (default 120). Use 0 for no time limit.",
    )
    pt.add_argument(
        "--max-samples",
        type=int,
        default=1200,
        help="Stop after this many valid frames (default 1200). Use 0 for no sample cap.",
    )
    pt.add_argument("--settle-s", type=float, default=0.2)
    pt.add_argument("--out", type=Path, default=Path("data/timeseries.csv"))
    pt.add_argument("--cam-serial", default=None)
    pt.add_argument("--lambda-nm", type=float, default=None)
    pt.add_argument("--lambda-status", default="unknown")
    pt.add_argument("--notes", default="")
    _add_show_plots_arg(pt)
    _add_live_plot_arg(pt)

    # -- analyze --
    pa = sub.add_parser(
        "analyze", help="Welch PSD + Gaussian-window STFT from a time-domain CSV."
    )
    pa.add_argument("csv", type=Path)
    pa.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_POSTER_FIGURES_DIR,
        help=f"Analysis PNG/JSON output directory (default: {DEFAULT_POSTER_FIGURES_DIR})",
    )
    pa.add_argument("--detrend", choices=["none", "mean", "linear"], default="linear")
    pa.add_argument("--welch-nperseg", type=int, default=None)
    pa.add_argument("--stft-nperseg", type=int, default=256)
    pa.add_argument("--stft-noverlap", type=int, default=None)
    pa.add_argument("--validate-only", action="store_true")
    _add_show_plots_arg(pa)

    # -- compare --
    pc = sub.add_parser("compare", help="Overlay PSD for two time-domain CSVs.")
    pc.add_argument("csv_a", type=Path)
    pc.add_argument("csv_b", type=Path)
    pc.add_argument("--label-a", default="A")
    pc.add_argument("--label-b", default="B")
    pc.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_POSTER_FIGURES_DIR,
        help=f"Analysis PNG/JSON output directory (default: {DEFAULT_POSTER_FIGURES_DIR})",
    )
    _add_show_plots_arg(pc)

    # -- analyze-scan --
    psa = sub.add_parser(
        "analyze-scan",
        help="FFT the interferogram (scan CSV) to recover laser wavelength.",
    )
    psa.add_argument(
        "csv", type=Path,
        help="Scan CSV (must have position_mm or position_steps column).",
    )
    psa.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_POSTER_FIGURES_DIR,
        help=f"Analysis PNG/JSON output directory (default: {DEFAULT_POSTER_FIGURES_DIR})",
    )
    psa.add_argument("--detrend", choices=["none", "mean", "linear"], default="linear")
    psa.add_argument(
        "--peak-lambda-min-nm",
        type=float,
        default=400.0,
        metavar="NM",
        help="With mm scans: search FFT peak only for σ consistent with λ≥this (default 400).",
    )
    psa.add_argument(
        "--peak-lambda-max-nm",
        type=float,
        default=900.0,
        metavar="NM",
        help="With mm scans: search FFT peak only for σ consistent with λ≤this (default 900).",
    )
    psa.add_argument(
        "--peak-global",
        action="store_true",
        help="Use legacy global FFT maximum (can pick spurious low-σ drift on continuous scans).",
    )
    _add_show_plots_arg(psa)

    # -- continuous-scan --
    pcs = sub.add_parser(
        "continuous-scan",
        help="FTS continuous scan: constant-velocity mirror + camera sampling.",
    )
    pcs.add_argument("--roi-file", type=Path, default=Path("roi_config.json"))
    pcs.add_argument(
        "--velocity-mm-s", type=float, default=0.001,
        help=(
            "Mirror velocity in mm/s (default 0.001). "
            "Beat freq = 2*v/lambda; keep below camera Nyquist (~10 Hz)."
        ),
    )
    pcs.add_argument(
        "--distance-mm", type=float, default=1.0,
        help="Travel distance in mm; must be <= 1.0 mm (default 1.0).",
    )
    pcs.add_argument(
        "--max-samples",
        type=int,
        default=1200,
        metavar="N",
        help="Stop after N valid camera samples (default 1200), or when travel/time ends.",
    )
    pcs.add_argument(
        "--max-duration-s",
        type=float,
        default=120.0,
        metavar="SEC",
        help="Stop capture after SEC seconds (default 120). Use 0 for no time limit.",
    )
    pcs.add_argument("--out", type=Path, default=Path("data/continuous_scan.csv"))
    pcs.add_argument("--stage-serial", default=None)
    pcs.add_argument("--cam-serial", default=None)
    pcs.add_argument("--lambda-nm", type=float, default=None)
    pcs.add_argument("--notes", default="")
    pcs.add_argument("--no-return-to-start", action="store_true")
    pcs.add_argument(
        "--return-velocity-mm-s",
        type=float,
        default=None,
        help=(
            "Max velocity (mm/s) for moving back to start after the scan. "
            "Default: stage_config.json kinesis.return_velocity_mm_s (2.2 if unset). "
            "Use a higher value than --velocity-mm-s so the return is not slow."
        ),
    )
    pcs.add_argument(
        "--save-frames", type=Path, default=None, metavar="DIR",
        help="Save snapshot PNGs to this folder (spaced by --save-frames-every).",
    )
    pcs.add_argument(
        "--save-frames-every",
        type=int,
        default=15,
        metavar="N",
        help=(
            "With --save-frames: save one PNG every N frames (default 15). "
            "Typical range 10-20 to limit disk use."
        ),
    )
    pcs.add_argument(
        "--stage-config", type=Path, default=Path("stage_config.json"),
    )
    _add_show_plots_arg(pcs)
    _add_live_plot_arg(pcs)

    # -- analyze-frames --
    paf = sub.add_parser(
        "analyze-frames",
        help="ROI mean/std on PNGs from continuous-scan --save-frames (same ROI as acquisition).",
    )
    paf.add_argument(
        "--frames-dir",
        type=Path,
        required=True,
        help="Folder with frame_*_*.png or position_*mm.png from --save-frames.",
    )
    paf.add_argument("--roi-file", type=Path, default=Path("roi_config.json"))
    paf.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="Per-file metrics CSV (default: <out-dir>/<frames-dir-name>_frames_metrics.csv).",
    )
    paf.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_POSTER_FRAMES_DIR,
        help=f"Frames analysis PNG/CSV output directory (default: {DEFAULT_POSTER_FRAMES_DIR})",
    )
    _add_show_plots_arg(paf)

    # -- save-roi --
    pr = sub.add_parser("save-roi", help="Interactive ROI selection; saves roi_config.json.")
    pr.add_argument("--out", type=Path, default=Path("roi_config.json"))
    pr.add_argument("--cam-serial", default=None)

    return p


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the appropriate command handler."""
    argv = argv if argv is not None else sys.argv[1:]
    args = build_arg_parser().parse_args(argv)

    if args.command == "save-roi":
        cam = setup_camera(args.cam_serial)
        if cam is None:
            return 1
        try:
            roi = select_roi(cam)
        finally:
            cam.close()
        if roi is None:
            print("No ROI saved.")
            return 1
        save_roi(roi, args.out)
        return 0

    if args.command == "scan":
        roi = load_roi(args.roi_file)
        extra = {
            "lambda_vacuum_nm": args.lambda_nm,
            "lambda_status": args.lambda_status,
            "notes": args.notes,
        }
        mm = (
            args.start_mm is not None
            or args.stop_mm is not None
            or args.step_mm is not None
        )
        st = (
            args.start is not None
            or args.stop is not None
            or args.step is not None
        )
        if mm and st:
            print(
                "Use either --start/--stop/--step (encoder) OR "
                "--start-mm/--stop-mm/--step-mm, not both.",
                file=sys.stderr,
            )
            return 2
        if mm:
            if args.start_mm is None or args.stop_mm is None or args.step_mm is None:
                print(
                    "MM scan requires --start-mm, --stop-mm, and --step-mm.",
                    file=sys.stderr,
                )
                return 2
            run_stage_scan(
                roi=roi,
                start_steps=None, stop_steps=None, step_steps=None,
                start_mm=args.start_mm, stop_mm=args.stop_mm, step_mm=args.step_mm,
                settle_s=args.settle_s,
                out_csv=args.out,
                stage_serial=args.stage_serial,
                cam_serial=args.cam_serial,
                meta_extra=extra,
                return_to_start=not args.no_return_to_start,
                save_frames_dir=args.save_frames,
                stage_config_path=args.stage_config,
                show_plots=args.show_plots,
                live_plot=args.live_plot,
            )
        else:
            if args.start is None or args.stop is None or args.step is None:
                print(
                    "Scan requires --start, --stop, --step (encoder) "
                    "OR --start-mm/--stop-mm/--step-mm.",
                    file=sys.stderr,
                )
                return 2
            run_stage_scan(
                roi=roi,
                start_steps=args.start, stop_steps=args.stop, step_steps=args.step,
                start_mm=None, stop_mm=None, step_mm=None,
                settle_s=args.settle_s,
                out_csv=args.out,
                stage_serial=args.stage_serial,
                cam_serial=args.cam_serial,
                meta_extra=extra,
                return_to_start=not args.no_return_to_start,
                save_frames_dir=args.save_frames,
                stage_config_path=args.stage_config,
                show_plots=args.show_plots,
                live_plot=args.live_plot,
            )
        return 0

    if args.command == "timeseries":
        roi = load_roi(args.roi_file)
        extra = {
            "lambda_vacuum_nm": args.lambda_nm,
            "lambda_status": args.lambda_status,
            "notes": args.notes,
        }
        ts_dur = args.duration_s if args.duration_s and args.duration_s > 0 else None
        ts_max_n = args.max_samples if args.max_samples and args.max_samples > 0 else None
        if ts_dur is None and ts_max_n is None:
            print(
                "timeseries: set a positive --duration-s and/or --max-samples "
                "(defaults are 120 s and 1200 samples; use 0 to disable one limit).",
                file=sys.stderr,
            )
            return 2
        run_timeseries(
            roi=roi,
            max_samples=ts_max_n,
            duration_s=ts_dur,
            settle_s=args.settle_s,
            out_csv=args.out,
            cam_serial=args.cam_serial,
            meta_extra=extra,
            show_plots=args.show_plots,
            live_plot=args.live_plot,
        )
        return 0

    if args.command == "analyze":
        print_validation_hints(args.csv)
        if args.validate_only:
            return 0
        analyze_timeseries_file(
            csv_path=args.csv,
            out_dir=args.out_dir,
            detrend=args.detrend,
            welch_nperseg=args.welch_nperseg,
            stft_nperseg=args.stft_nperseg,
            stft_noverlap=args.stft_noverlap,
            show_plots=args.show_plots,
        )
        return 0

    if args.command == "compare":
        compare_two_runs(
            args.csv_a,
            args.csv_b,
            args.label_a,
            args.label_b,
            args.out_dir,
            show_plots=args.show_plots,
        )
        return 0

    if args.command == "analyze-scan":
        if args.peak_lambda_min_nm >= args.peak_lambda_max_nm:
            print(
                "--peak-lambda-min-nm must be less than --peak-lambda-max-nm",
                file=sys.stderr,
            )
            return 2
        peak_nm: tuple[float, float] | None = None
        if not args.peak_global:
            peak_nm = (args.peak_lambda_min_nm, args.peak_lambda_max_nm)
        analyze_scan_file(
            csv_path=args.csv,
            out_dir=args.out_dir,
            detrend=args.detrend,
            show_plots=args.show_plots,
            peak_search_lambda_nm=peak_nm,
        )
        return 0

    if args.command == "continuous-scan":
        if args.save_frames is not None and args.save_frames_every < 1:
            print("--save-frames-every must be >= 1", file=sys.stderr)
            return 2
        if args.max_samples < 1:
            print("--max-samples must be >= 1", file=sys.stderr)
            return 2
        max_dur_cs = args.max_duration_s
        if max_dur_cs is not None and max_dur_cs <= 0:
            max_dur_cs = None
        roi = load_roi(args.roi_file)
        extra = {
            "lambda_vacuum_nm": args.lambda_nm,
            "notes": args.notes,
        }
        run_continuous_scan(
            roi=roi,
            velocity_mm_s=args.velocity_mm_s,
            distance_mm=args.distance_mm,
            out_csv=args.out,
            stage_serial=args.stage_serial,
            cam_serial=args.cam_serial,
            meta_extra=extra,
            return_to_start=not args.no_return_to_start,
            save_frames_dir=args.save_frames,
            save_frames_every=args.save_frames_every,
            stage_config_path=args.stage_config,
            show_plots=args.show_plots,
            live_plot=args.live_plot,
            return_velocity_mm_s=args.return_velocity_mm_s,
            max_samples=args.max_samples,
            max_duration_s=max_dur_cs,
        )
        return 0

    if args.command == "analyze-frames":
        roi = load_roi(args.roi_file)
        out_csv = args.out_csv
        if out_csv is None:
            out_csv = args.out_dir / f"{args.frames_dir.name}_frames_metrics.csv"
        analyze_frames_folder(
            frames_dir=args.frames_dir,
            roi=roi,
            out_csv=out_csv,
            out_dir=args.out_dir,
            show_plots=args.show_plots,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
