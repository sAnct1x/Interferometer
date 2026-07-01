"""Measure laser spot size (FWHM and 1/e²) from Thorcam TIFF captures."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tifffile as tiff

from beam_roi import DEFAULT_ROI_FILE, load_crop_box
from beam_naming import (
    BEST_POINTER,
    BEST_RUN_FILE,
    LATEST_POINTER,
    RUN_LOG_CSV,
    load_best_run,
    publish_best,
    publish_latest,
    run_info_from_capture,
    run_output_dir,
    save_best_run,
    write_pointer_file,
    write_summary_txt,
)

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_IMAGE_DIR = PROJECT_DIR / "data"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "beam_size_outputs"
# Thorcam CS165CU pixel pitch
PIXEL_SIZE_UM = 3.45

def read_tif(path: Path) -> np.ndarray:
    """Load a TIFF capture as a numpy array."""
    return np.asarray(tiff.imread(path))


def crop_image(img: np.ndarray, crop_box: tuple[int, int, int, int] | None) -> np.ndarray:
    """Crop using ``(x_min, x_max, y_min, y_max)`` indices."""
    if crop_box is None:
        return img

    x_min, x_max, y_min, y_max = crop_box
    h, w = img.shape
    x_min = int(np.clip(x_min, 0, w - 1))
    x_max = int(np.clip(x_max, x_min + 1, w))
    y_min = int(np.clip(y_min, 0, h - 1))
    y_max = int(np.clip(y_max, y_min + 1, h))
    return img[y_min:y_max, x_min:x_max]


def estimate_background_border(img: np.ndarray, border: int = 20) -> float:
    """Estimate background from border strips, biased toward dimmer pixels on tight ROIs."""
    h, w = img.shape
    b = max(1, min(int(border), h // 10, w // 10, h // 2, w // 2))

    border_pixels = np.concatenate(
        [
            img[:b, :].ravel(),
            img[-b:, :].ravel(),
            img[:, :b].ravel(),
            img[:, -b:].ravel(),
        ]
    )
    border_med = float(np.median(border_pixels))
    dim_pct = float(np.percentile(img, 5))
    return min(border_med, dim_pct)


def _profile_baseline(profile: np.ndarray, edge_fraction: float = 0.08) -> float:
    p = np.asarray(profile, dtype=float)
    edge_n = max(3, int(len(p) * edge_fraction))
    return 0.5 * (float(np.mean(p[:edge_n])) + float(np.mean(p[-edge_n:])))


def width_from_profile(profile: np.ndarray, level_fraction: float) -> float:
    """Return profile width in pixels at ``level_fraction`` of peak."""
    width_px, _, _ = width_from_profile_detailed(profile, level_fraction)
    return width_px


def width_from_profile_detailed(
    profile: np.ndarray, level_fraction: float
) -> tuple[float, float, float]:
    """Return (width_px, left_crossing_px, right_crossing_px)."""
    p = np.asarray(profile, dtype=float)
    baseline = _profile_baseline(p)
    p = p - baseline
    p[p < 0] = 0.0
    if np.allclose(p, 0):
        return np.nan, np.nan, np.nan

    peak_idx = int(np.argmax(p))
    peak = float(p[peak_idx])
    level = peak * level_fraction

    left = peak_idx
    while left > 0 and p[left] >= level:
        left -= 1
    if left == peak_idx:
        return np.nan, np.nan, np.nan

    x0, x1 = left, left + 1
    y0, y1 = p[left], p[left + 1]
    x_left = x0 + (level - y0) * (x1 - x0) / (y1 - y0 + 1e-30)

    right = peak_idx
    while right < len(p) - 1 and p[right] >= level:
        right += 1
    if right == peak_idx:
        return np.nan, np.nan, np.nan

    x0, x1 = right - 1, right
    y0, y1 = p[right - 1], p[right]
    x_right = x0 + (level - y0) * (x1 - x0) / (y1 - y0 + 1e-30)

    return float(x_right - x_left), float(x_left), float(x_right)


def _roi_limited_warning(
    axis_name: str,
    width_px: float,
    profile_len: int,
    left_x: float,
    right_x: float,
    *,
    level_name: str,
) -> str | None:
    if not np.isfinite(width_px) or profile_len <= 0:
        return None

    fill = width_px / profile_len
    edge_margin = max(3.0, 0.06 * profile_len)
    near_edge = left_x <= edge_margin or right_x >= profile_len - 1 - edge_margin

    if fill >= 0.88 or near_edge:
        width_um = width_px * PIXEL_SIZE_UM
        return (
            f"{axis_name} {level_name} width ({width_um:.0f} um, {width_px:.0f}/{profile_len} px) "
            "is ROI-limited - the box includes halo/fringes, not just the bright waist. "
            "Tighten ROI to the saturated core only (~60-90 px wide)."
        )
    return None


def measurement_warnings(
    img_bs: np.ndarray,
    x_profile: np.ndarray,
    y_profile: np.ndarray,
    *,
    background_level: float,
    raw_peak: float,
) -> list[str]:
    """Collect warnings about ROI size, background, and clipped profiles."""
    warnings: list[str] = []
    h, w = img_bs.shape

    if min(h, w) < 80:
        warnings.append(
            f"ROI crop is only {w}x{h} px — include more dark background around the beam for accurate widths."
        )

    if raw_peak > 0 and background_level / raw_peak > 0.25:
        warnings.append(
            f"Background ({background_level:.0f}) is high vs peak ({raw_peak:.0f}); "
            "border pixels may still be inside the beam halo."
        )

    for axis_name, profile in ("X", x_profile), ("Y", y_profile):
        baseline = _profile_baseline(profile)
        peak = float(np.max(profile))
        if peak <= 0:
            continue
        if baseline / peak > 0.35:
            warnings.append(
                f"{axis_name} profile edges are still bright ({100 * baseline / peak:.0f}% of peak); "
                "beam may be clipped by the ROI on that axis."
            )

    return warnings


def _append_roi_limit_warnings(
    warnings: list[str],
    *,
    e2_x_px: float,
    e2_y_px: float,
    e2_x_l: float,
    e2_x_r: float,
    e2_y_l: float,
    e2_y_r: float,
    x_len: int,
    y_len: int,
) -> None:
    """Flag the classic stuck ~361 um artifact, not every tight Gaussian crop."""
    e2_x_um = e2_x_px * PIXEL_SIZE_UM
    e2_y_um = e2_y_px * PIXEL_SIZE_UM
    e2_avg = (e2_x_um + e2_y_um) / 2
    axis_delta = abs(e2_x_um - e2_y_um)

    stuck_361 = 340 <= e2_avg <= 380 and axis_delta < 25
    severe_asymmetry = axis_delta > 50
    x_msg = _roi_limited_warning(
        "X", e2_x_px, x_len, e2_x_l, e2_x_r, level_name="1/e2"
    )
    y_msg = _roi_limited_warning(
        "Y", e2_y_px, y_len, e2_y_l, e2_y_r, level_name="1/e2"
    )

    if stuck_361:
        warnings.append(
            "1/e2 average is stuck near ~361 um (ROI/fringe artifact). "
            "Tighten ROI to the saturated core only (~60-90 px wide), excluding the first fringe ring."
        )
    elif severe_asymmetry:
        if x_msg is not None:
            warnings.append(x_msg)
        if y_msg is not None:
            warnings.append(y_msg)
        warnings.append(
            f"Large X/Y mismatch ({axis_delta:.0f} um) — recenter ROI or shrink one axis."
        )


def analyze_tif(
    path: Path,
    pixel_size_um: float = PIXEL_SIZE_UM,
    border: int = 20,
    crop_box: tuple[int, int, int, int] | None = None,
) -> dict:
    """Crop, subtract background, build profiles, return widths in µm."""
    img = read_tif(path)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)

    img = img.astype(np.float64)
    img = crop_image(img, crop_box=crop_box)
    raw_peak = float(np.max(img))
    background = estimate_background_border(img, border=border)
    img_bs = img - background
    img_bs[img_bs < 0] = 0.0

    x_profile = img_bs.sum(axis=0)
    y_profile = img_bs.sum(axis=1)
    quality_warnings = measurement_warnings(
        img_bs,
        x_profile,
        y_profile,
        background_level=background,
        raw_peak=raw_peak,
    )

    fwhm_x_px, fwhm_x_l, fwhm_x_r = width_from_profile_detailed(x_profile, 0.5)
    fwhm_y_px, fwhm_y_l, fwhm_y_r = width_from_profile_detailed(y_profile, 0.5)
    e2_x_px, e2_x_l, e2_x_r = width_from_profile_detailed(x_profile, 1 / np.e**2)
    e2_y_px, e2_y_l, e2_y_r = width_from_profile_detailed(y_profile, 1 / np.e**2)

    _append_roi_limit_warnings(
        quality_warnings,
        e2_x_px=e2_x_px,
        e2_y_px=e2_y_px,
        e2_x_l=e2_x_l,
        e2_x_r=e2_x_r,
        e2_y_l=e2_y_l,
        e2_y_r=e2_y_r,
        x_len=len(x_profile),
        y_len=len(y_profile),
    )

    return {
        "image_name": path.name,
        "background_level": background,
        "crop_box": "" if crop_box is None else str(crop_box),
        "cropped_shape": str(img_bs.shape),
        "fwhm_x_um": fwhm_x_px * pixel_size_um,
        "fwhm_y_um": fwhm_y_px * pixel_size_um,
        "fwhm_x_mm": fwhm_x_px * pixel_size_um / 1000.0,
        "fwhm_y_mm": fwhm_y_px * pixel_size_um / 1000.0,
        "one_over_e2_x_um": e2_x_px * pixel_size_um,
        "one_over_e2_y_um": e2_y_px * pixel_size_um,
        "one_over_e2_x_mm": e2_x_px * pixel_size_um / 1000.0,
        "one_over_e2_y_mm": e2_y_px * pixel_size_um / 1000.0,
        "img_bs": img_bs,
        "x_profile": x_profile,
        "y_profile": y_profile,
        "quality_warnings": quality_warnings,
    }


def save_plot(result: dict, plot_path: Path, *, run_id: str) -> None:
    """Write beam image and X/Y profile figure to ``plot_path``."""
    fig, ax = plt.subplots(1, 3, figsize=(14, 4))

    im = ax[0].imshow(result["img_bs"], cmap="plasma", origin="upper")
    ax[0].set_title(f"Beam Image\n{run_id}")
    plt.colorbar(im, ax=ax[0], fraction=0.046)

    x_profile = result["x_profile"]
    ax[1].plot(x_profile, color="rebeccapurple")
    ax[1].axhline(np.max(x_profile) / np.e**2, linestyle="--", color="rebeccapurple")
    ax[1].set_title(f"X Profile\n1/e^2 = {result['one_over_e2_x_um']:.1f} um")

    y_profile = result["y_profile"]
    ax[2].plot(y_profile, color="deeppink")
    ax[2].axhline(np.max(y_profile) / np.e**2, linestyle="--", color="deeppink")
    ax[2].set_title(f"Y Profile\n1/e^2 = {result['one_over_e2_y_um']:.1f} um")

    plt.tight_layout()
    fig.savefig(plot_path, dpi=200)
    plt.close(fig)


RUN_LOG_FIELDS = [
    "run_id",
    "capture_file",
    "analyzed_at",
    "fwhm_x_um",
    "fwhm_y_um",
    "fwhm_avg_um",
    "one_over_e2_x_um",
    "one_over_e2_y_um",
    "one_over_e2_avg_um",
    "crop_box",
    "background_level",
    "cropped_shape",
    "is_best",
]


def _result_row(result: dict, *, run_id: str, capture_file: str, is_best: bool) -> dict:
    fwhm_avg = (result["fwhm_x_um"] + result["fwhm_y_um"]) / 2
    e2_avg = (result["one_over_e2_x_um"] + result["one_over_e2_y_um"]) / 2
    return {
        "run_id": run_id,
        "capture_file": capture_file,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "fwhm_x_um": result["fwhm_x_um"],
        "fwhm_y_um": result["fwhm_y_um"],
        "fwhm_avg_um": fwhm_avg,
        "one_over_e2_x_um": result["one_over_e2_x_um"],
        "one_over_e2_y_um": result["one_over_e2_y_um"],
        "one_over_e2_avg_um": e2_avg,
        "crop_box": result["crop_box"],
        "background_level": result["background_level"],
        "cropped_shape": result["cropped_shape"],
        "is_best": "yes" if is_best else "no",
    }


def _update_run_log(rows: list[dict]) -> None:
    existing: dict[str, dict] = {}
    if RUN_LOG_CSV.is_file():
        with RUN_LOG_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["run_id"]] = row

    for row in rows:
        existing[row["run_id"]] = row

    ordered = sorted(existing.values(), key=lambda row: row["run_id"])
    RUN_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(ordered)


def _select_capture_files(image_folder: Path, *, analyze_all: bool, capture_name: str | None) -> list[Path]:
    from beam_naming import latest_capture, list_captures

    if capture_name:
        path = image_folder / capture_name
        if not path.is_file():
            raise FileNotFoundError(f"Capture not found: {path}")
        return [path]

    if analyze_all:
        captures = list_captures(image_folder)
        if not captures:
            raise FileNotFoundError(f"No TIFF files found in {image_folder}")
        return captures

    latest = latest_capture(image_folder)
    if latest is None:
        raise FileNotFoundError(f"No TIFF files found in {image_folder}")
    return [latest]


def main() -> None:
    """CLI entry: analyze one or all beam TIFF captures and write run outputs."""
    parser = argparse.ArgumentParser(description="Measure laser beam size from TIFF images.")
    parser.add_argument("--image-folder", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--output-folder", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pixel-size-um", type=float, default=PIXEL_SIZE_UM)
    parser.add_argument(
        "--roi-file",
        type=Path,
        default=DEFAULT_ROI_FILE,
        help="JSON ROI file from save_beam_roi.py (default: beam_roi_config.json).",
    )
    parser.add_argument(
        "--no-roi",
        action="store_true",
        help="Analyze the full frame instead of using a saved ROI.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze every capture in data/ (default: latest capture only).",
    )
    parser.add_argument(
        "--capture",
        type=str,
        default=None,
        help="Analyze one specific capture filename from data/.",
    )
    parser.add_argument(
        "--mark-best",
        action="store_true",
        help="Mark the analyzed run(s) as the current best measurement.",
    )
    args = parser.parse_args()

    image_folder = args.image_folder
    output_folder = args.output_folder
    image_folder.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    crop_box = None
    if not args.no_roi:
        if not args.roi_file.is_file():
            print(f"No ROI file found at {args.roi_file}")
            print("Run save_beam_roi.py first, or pass --no-roi to analyze the full frame.")
            return
        crop_box = load_crop_box(args.roi_file)
        print(f"Using ROI crop_box: {crop_box}")

    try:
        tif_files = _select_capture_files(
            image_folder,
            analyze_all=args.all,
            capture_name=args.capture,
        )
    except FileNotFoundError as exc:
        print(exc)
        print("Place .tif/.tiff files there, then rerun this script.")
        return

    best_config = load_best_run()
    log_rows = []
    last_run_id = None
    last_result = None
    last_info = None

    for tif_path in tif_files:
        info = run_info_from_capture(tif_path)
        run_id = info["run_id"]
        print(f"Processing {info['capture_file']}  ({run_id})")

        result = analyze_tif(
            tif_path,
            pixel_size_um=args.pixel_size_um,
            crop_box=crop_box,
        )
        result["run_id"] = run_id
        result["capture_file"] = info["capture_file"]

        is_best = bool(args.mark_best) or (
            best_config is not None and best_config.get("run_id") == run_id
        )
        log_row = _result_row(
            result,
            run_id=run_id,
            capture_file=info["capture_file"],
            is_best=is_best,
        )
        log_rows.append(log_row)

        run_dir = run_output_dir(run_id, output_folder)
        run_dir.mkdir(parents=True, exist_ok=True)

        plot_path = run_dir / "beam_analysis.png"
        save_plot(result, plot_path, run_id=run_id)

        csv_path = run_dir / "results.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
            writer.writeheader()
            writer.writerow(log_row)

        write_summary_txt(
            run_dir,
            run_id=run_id,
            capture_file=info["capture_file"],
            date_str=info["date_str"],
            time_str=info["time_str"],
            result=result,
        )

        publish_latest(run_id, run_dir)
        write_pointer_file(
            LATEST_POINTER,
            run_id=run_id,
            capture_file=info["capture_file"],
            result=result,
            label="LATEST",
        )

        if is_best:
            if args.mark_best:
                save_best_run(
                    run_id,
                    info["capture_file"],
                    notes="Marked best from beam_size_analysis.py",
                )
            publish_best(run_id, run_dir)
            write_pointer_file(
                BEST_POINTER,
                run_id=run_id,
                capture_file=info["capture_file"],
                result=result,
                label="BEST",
            )

        fwhm_avg = log_row["fwhm_avg_um"]
        e2_avg = log_row["one_over_e2_avg_um"]
        print(
            f"  Saved run folder: {run_dir}\n"
            f"  FWHM avg={fwhm_avg:.1f} um | 1/e2 avg={e2_avg:.1f} um"
        )
        for warning in result.get("quality_warnings", []):
            print(f"  WARNING: {warning}")

        last_run_id = run_id
        last_result = result
        last_info = info

    _update_run_log(log_rows)

    legacy_csv = output_folder / "Beam_Size_Results.csv"
    with legacy_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(log_rows)

    print(f"Updated run log: {RUN_LOG_CSV}")
    print(f"Latest results:  {LATEST_POINTER}")
    if load_best_run() is not None:
        print(f"Best results:    {BEST_POINTER}")

    if last_result is not None and last_info is not None:
        print(
            f"Latest run {last_run_id}: "
            f"FWHM avg={(last_result['fwhm_x_um'] + last_result['fwhm_y_um']) / 2:.1f} um, "
            f"1/e2 avg={(last_result['one_over_e2_x_um'] + last_result['one_over_e2_y_um']) / 2:.1f} um"
        )


if __name__ == "__main__":
    main()
