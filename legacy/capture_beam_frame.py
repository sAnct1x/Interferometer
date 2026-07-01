"""Grab one raw Thorcam frame and save a numbered TIFF under ``data/``."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import tifffile as tiff

# This folder holds the beam scripts; Interferometer Project has the camera code.
PROJECT_DIR = Path(__file__).resolve().parent
INTERFEROMETER_DIR = PROJECT_DIR / "Interferometer Project"
OUTPUT_DIR = PROJECT_DIR / "data"

sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(INTERFEROMETER_DIR))

from beam_naming import make_capture_path, next_run_id  # noqa: E402
from interferometer_acquire_analyze import setup_camera  # noqa: E402


def capture_raw_tiff(
    cam_serial: str | None = None,
    settle_s: float = 2.0,
    timeout_s: float = 15.0,
) -> Path:
    """Grab one raw Thorcam frame and save it as TIFF for beam-size analysis."""
    cam = setup_camera(cam_serial)
    if cam is None:
        raise RuntimeError("No Thorcam found. Close ThorCam GUI if it is open, then retry.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = next_run_id(OUTPUT_DIR)
    out_path = make_capture_path(run_id, OUTPUT_DIR)

    try:
        cam.start_acquisition()
        time.sleep(settle_s)

        frame = None
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            candidate = cam.read_newest_image()
            if candidate is not None:
                frame = candidate
                break
            time.sleep(0.1)

        if frame is None:
            raise RuntimeError(
                "Camera returned no frame within timeout. Close ThorCam GUI and retry."
            )

        arr = np.squeeze(np.asarray(frame))
        tiff.imwrite(out_path, arr)
        print(f"Saved raw capture: {out_path}")
        print(f"Run ID: {run_id}")
        print(f"Frame shape: {arr.shape}, dtype: {arr.dtype}")
        return out_path
    finally:
        try:
            cam.stop_acquisition()
        except Exception:
            pass
        cam.close()


if __name__ == "__main__":
    capture_raw_tiff()
