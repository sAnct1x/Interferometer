"""Run IDs, capture folders, and summary files for beam-size measurements."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = PROJECT_DIR / "data"
OUTPUT_DIR = PROJECT_DIR / "beam_size_outputs"
RUNS_DIR = OUTPUT_DIR / "runs"
LATEST_DIR = OUTPUT_DIR / "latest"
BEST_DIR = OUTPUT_DIR / "best"
RUN_LOG_CSV = OUTPUT_DIR / "run_log.csv"
BEST_RUN_FILE = PROJECT_DIR / "beam_best_run.json"
LATEST_POINTER = OUTPUT_DIR / "LATEST.txt"
BEST_POINTER = OUTPUT_DIR / "BEST.txt"

NEW_CAPTURE_RE = re.compile(r"^run_(\d{3})_(\d{8})_(\d{6})_beam$")
OLD_CAPTURE_RE = re.compile(r"^beam_capture_(\d{8})_(\d{6})$")


def parse_capture_stem(stem: str) -> dict | None:
    """Parse a capture filename stem into run metadata, or ``None`` if unrecognized."""
    match = NEW_CAPTURE_RE.match(stem)
    if match:
        seq, date_str, time_str = match.groups()
        run_id = f"run_{seq}_{date_str}_{time_str}"
        return {
            "run_id": run_id,
            "seq": int(seq),
            "date_str": date_str,
            "time_str": time_str,
            "capture_name": f"{run_id}_beam.tiff",
        }

    match = OLD_CAPTURE_RE.match(stem)
    if match:
        date_str, time_str = match.groups()
        return {
            "run_id": f"legacy_{date_str}_{time_str}",
            "seq": None,
            "date_str": date_str,
            "time_str": time_str,
            "capture_name": f"beam_capture_{date_str}_{time_str}.tiff",
        }

    return None


def list_captures(capture_dir: Path = CAPTURE_DIR) -> list[Path]:
    """All .tif/.tiff files in data/, sorted by run number then timestamp."""
    files = list(capture_dir.glob("*.tif")) + list(capture_dir.glob("*.tiff"))
    return sorted(files, key=_capture_sort_key)


def _capture_sort_key(path: Path) -> tuple:
    info = parse_capture_stem(path.stem)
    if info is None:
        return (1, path.name)
    seq = info["seq"] if info["seq"] is not None else 999999
    return (0, seq, info["date_str"], info["time_str"])


def latest_capture(capture_dir: Path = CAPTURE_DIR) -> Path | None:
    """Return the most recent capture TIFF in ``capture_dir``, if any."""
    captures = list_captures(capture_dir)
    return captures[-1] if captures else None


def next_run_id(capture_dir: Path = CAPTURE_DIR) -> str:
    """Next sequential ID, e.g. run_003_20260611_165015."""
    max_seq = 0
    for path in list_captures(capture_dir):
        info = parse_capture_stem(path.stem)
        if info and info["seq"] is not None:
            max_seq = max(max_seq, info["seq"])
    return f"run_{max_seq + 1:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def make_capture_path(run_id: str, capture_dir: Path = CAPTURE_DIR) -> Path:
    """Build the TIFF path for a given ``run_id`` under ``capture_dir``."""
    return capture_dir / f"{run_id}_beam.tiff"


def run_info_from_capture(path: Path) -> dict:
    """Return run metadata dict for a capture TIFF path."""
    info = parse_capture_stem(path.stem)
    if info is None:
        raise ValueError(f"Unrecognized capture filename: {path.name}")
    info["capture_path"] = path
    info["capture_file"] = path.name
    return info


def run_output_dir(run_id: str, output_dir: Path = OUTPUT_DIR) -> Path:
    """Return ``beam_size_outputs/runs/<run_id>`` for one analysis run."""
    return output_dir / "runs" / run_id


def format_human_timestamp(date_str: str, time_str: str) -> str:
    """Format ``YYYYMMDD`` and ``HHMMSS`` tokens as ``YYYY-MM-DD HH:MM:SS``."""
    return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"


def load_best_run(path: Path = BEST_RUN_FILE) -> dict | None:
    """Load the marked best-run JSON, or ``None`` if missing."""
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_best_run(run_id: str, capture_file: str, notes: str = "", path: Path = BEST_RUN_FILE) -> None:
    """Persist which run the operator marked as the best beam capture."""
    payload = {
        "run_id": run_id,
        "capture_file": capture_file,
        "notes": notes,
        "marked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_summary_txt(
    run_dir: Path,
    *,
    run_id: str,
    capture_file: str,
    date_str: str,
    time_str: str,
    result: dict,
) -> None:
    fwhm_avg = (result["fwhm_x_um"] + result["fwhm_y_um"]) / 2
    e2_avg = (result["one_over_e2_x_um"] + result["one_over_e2_y_um"]) / 2
    lines = [
        f"Run ID:      {run_id}",
        f"Capture:     {capture_file}",
        f"Timestamp:   {format_human_timestamp(date_str, time_str)}",
        "",
        "Beam size:",
        f"  FWHM (um):   X={result['fwhm_x_um']:.1f}  Y={result['fwhm_y_um']:.1f}  avg={fwhm_avg:.1f}",
        f"  1/e2 (um):   X={result['one_over_e2_x_um']:.1f}  Y={result['one_over_e2_y_um']:.1f}  avg={e2_avg:.1f}",
        "",
        f"ROI crop_box: {result['crop_box']}",
        "Plot:         beam_analysis.png",
        "Results:      results.csv",
    ]
    (run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pointer_file(
    path: Path,
    *,
    run_id: str,
    capture_file: str,
    result: dict,
    label: str,
) -> None:
    fwhm_avg = (result["fwhm_x_um"] + result["fwhm_y_um"]) / 2
    e2_avg = (result["one_over_e2_x_um"] + result["one_over_e2_y_um"]) / 2
    lines = [
        f"{label}: {run_id}",
        f"Capture: {capture_file}",
        f"FWHM avg: {fwhm_avg:.1f} um",
        f"1/e2 avg: {e2_avg:.1f} um",
        f"Run folder: beam_size_outputs\\runs\\{run_id}",
        f"Plot: beam_size_outputs\\{label.lower()}\\beam_analysis.png",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def publish_run_folder(run_dir: Path, target_dir: Path) -> None:
    """Copy one run's outputs into latest/ or best/ so you always know where to look."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in run_dir.iterdir():
        dest = target_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


def publish_latest(run_id: str, run_dir: Path) -> None:
    """Copy run outputs into ``beam_size_outputs/latest/``."""
    publish_run_folder(run_dir, LATEST_DIR)


def publish_best(run_id: str, run_dir: Path) -> None:
    """Copy run outputs into ``beam_size_outputs/best/``."""
    publish_run_folder(run_dir, BEST_DIR)
