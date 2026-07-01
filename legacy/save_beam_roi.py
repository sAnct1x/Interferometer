"""CLI tool to save the beam ROI around the bright spot."""

from __future__ import annotations

import argparse
from pathlib import Path

from beam_roi import DEFAULT_ROI_FILE, resolve_crop_box, suggest_roi_from_tif, save_roi


def main() -> None:
    """Parse CLI flags and save a beam ROI JSON file."""
    parser = argparse.ArgumentParser(
        description="Save an ROI around the bright beam core for beam-size analysis."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Drag ROI on live Thorcam (same as interferometer save-roi).",
    )
    parser.add_argument(
        "--from-tiff",
        type=Path,
        default=None,
        help="Drag ROI on a saved TIFF.",
    )
    parser.add_argument(
        "--manual-crop-box",
        nargs=4,
        type=int,
        metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX"),
        help="Manual crop_box in mentor notebook format.",
    )
    parser.add_argument(
        "--suggest-from-tiff",
        type=Path,
        default=None,
        help="Auto-estimate ROI around brightest region (starting point only).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.65,
        help="Brightness fraction for --suggest-from-tiff (default 0.65).",
    )
    parser.add_argument("--cam-serial", default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_ROI_FILE)
    args = parser.parse_args()

    if args.suggest_from_tiff is not None:
        roi = suggest_roi_from_tif(args.suggest_from_tiff, threshold_fraction=args.threshold)
        save_roi(roi, args.out)
        print("Auto-suggested ROI saved. Re-run with --from-tiff to refine manually.")
        return

    if not any([args.live, args.from_tiff, args.manual_crop_box]):
        args.live = True

    manual = tuple(args.manual_crop_box) if args.manual_crop_box else None
    crop_box = resolve_crop_box(
        roi_file=args.out,
        interactive_live=args.live,
        interactive_tiff=args.from_tiff is not None,
        manual_crop_box=manual,
        use_saved_file=False,
        cam_serial=args.cam_serial,
        tiff_path=args.from_tiff,
    )

    if crop_box is None:
        print("No ROI saved.")
        print("Tips: drag the green box to move it, drag yellow handles to resize,")
        print("      click Confirm ROI or press Enter, or use --manual-crop-box X_MIN X_MAX Y_MIN Y_MAX")
        return

    print(f"crop_box = {crop_box}")


if __name__ == "__main__":
    main()
