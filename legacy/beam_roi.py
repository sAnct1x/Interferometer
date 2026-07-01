"""Load, save, and interactively pick a beam ROI on camera or TIFF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import tifffile as tiff

PROJECT_DIR = Path(__file__).resolve().parent
INTERFEROMETER_DIR = PROJECT_DIR / "Interferometer Project"
DEFAULT_ROI_FILE = PROJECT_DIR / "beam_roi_config.json"


def roi_xywh_to_crop_box(roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Convert interferometer-style (x, y, w, h) to notebook crop_box (x_min, x_max, y_min, y_max)."""
    x, y, w, h = roi
    return (x, x + w, y, y + h)


def crop_box_to_roi_xywh(crop_box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x_min, x_max, y_min, y_max = crop_box
    return (x_min, y_min, x_max - x_min, y_max - y_min)


def save_roi(roi: tuple[int, int, int, int], path: Path = DEFAULT_ROI_FILE) -> None:
    """Write beam ROI xywh and crop_box JSON to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "x": int(roi[0]),
        "y": int(roi[1]),
        "w": int(roi[2]),
        "h": int(roi[3]),
        "crop_box": list(roi_xywh_to_crop_box(roi)),
        "notes": "Draw a box around the bright beam core only, not the full camera frame.",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved beam ROI to {path}")
    print(f"  xywh: x={roi[0]}, y={roi[1]}, w={roi[2]}, h={roi[3]}")
    print(f"  crop_box: {tuple(payload['crop_box'])}")


def load_roi(path: Path = DEFAULT_ROI_FILE) -> tuple[int, int, int, int]:
    """Read ``(x, y, w, h)`` from beam ROI JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "crop_box" in data:
        return crop_box_to_roi_xywh(tuple(int(v) for v in data["crop_box"]))
    return (int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))


def load_crop_box(path: Path = DEFAULT_ROI_FILE) -> tuple[int, int, int, int]:
    """Read mentor-style ``(x_min, x_max, y_min, y_max)`` from ROI JSON."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "crop_box" in data:
        return tuple(int(v) for v in data["crop_box"])
    roi = (int(data["x"]), int(data["y"]), int(data["w"]), int(data["h"]))
    return roi_xywh_to_crop_box(roi)


def resolve_crop_box(
    *,
    project_dir: Path = PROJECT_DIR,
    roi_file: Path | None = None,
    image_folder: Path | None = None,
    interactive_live: bool = False,
    interactive_tiff: bool = False,
    manual_crop_box: tuple[int, int, int, int] | None = None,
    use_saved_file: bool = False,
    cam_serial: str | None = None,
    tiff_path: Path | None = None,
) -> tuple[int, int, int, int] | None:
    """Pick one ROI source: live camera, saved TIFF, manual crop_box, or JSON file."""
    roi_path = roi_file or (project_dir / "beam_roi_config.json")
    data_dir = image_folder or (project_dir / "data")

    modes = [interactive_live, interactive_tiff, manual_crop_box is not None, use_saved_file]
    if sum(bool(m) for m in modes) > 1:
        raise ValueError("Choose only one ROI mode at a time.")

    if interactive_live:
        roi = select_roi_live(cam_serial)
        if roi is None:
            print("Live ROI selection cancelled; no ROI saved.")
            return None
        save_roi(roi, roi_path)
        return load_crop_box(roi_path)

    if interactive_tiff:
        target = tiff_path
        if target is None:
            from beam_naming import latest_capture

            target = latest_capture(data_dir)
            if target is None:
                raise FileNotFoundError(f"No TIFF files found in {data_dir}")
        roi = select_roi_from_tif(target)
        if roi is None:
            print("TIFF ROI selection cancelled; no ROI saved.")
            return None
        save_roi(roi, roi_path)
        return load_crop_box(roi_path)

    if manual_crop_box is not None:
        save_roi(crop_box_to_roi_xywh(manual_crop_box), roi_path)
        return manual_crop_box

    if use_saved_file:
        if not roi_path.is_file():
            raise FileNotFoundError(f"No saved ROI at {roi_path}")
        return load_crop_box(roi_path)

    if roi_path.is_file():
        return load_crop_box(roi_path)

    return None


def _to_grayscale(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return img[..., :3].mean(axis=2)
    return img


def _normalize_to_u8(img: np.ndarray) -> np.ndarray:
    arr = _to_grayscale(np.asarray(img)).astype(np.float64)
    arr -= arr.min()
    if arr.max() > 0:
        arr /= arr.max()
    return (255 * arr).astype(np.uint8)


def _opencv_gui_available() -> bool:
    try:
        import cv2

        cv2.namedWindow("__roi_test__", cv2.WINDOW_NORMAL)
        cv2.destroyWindow("__roi_test__")
        return True
    except cv2.error:
        return False


def _ensure_interactive_backend() -> None:
    import matplotlib

    backend = matplotlib.get_backend().lower()
    if "agg" in backend and "tk" not in backend and "qt" not in backend:
        for candidate in ("TkAgg", "Qt5Agg", "QtAgg", "WXAgg"):
            try:
                matplotlib.use(candidate, force=True)
                break
            except Exception:
                continue


class _InteractiveRoiPicker:
    """Matplotlib ROI box that can be dragged and resized on the fly."""

    MIN_SIZE = 10
    HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def __init__(
        self,
        image_u8: np.ndarray,
        title: str,
        initial_roi: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.image = image_u8
        self.img_h, self.img_w = image_u8.shape[:2]
        self.title = title
        self.result: tuple[int, int, int, int] | None = None
        self.cancelled = False

        if initial_roi is not None:
            x, y, w, h = initial_roi
        else:
            w = max(self.MIN_SIZE, int(self.img_w * 0.3))
            h = max(self.MIN_SIZE, int(self.img_h * 0.3))
            x = (self.img_w - w) // 2
            y = (self.img_h - h) // 2

        self.x, self.y, self.w, self.h = self._clamp_roi(x, y, w, h)
        self._mode: str | None = None
        self._press_xy: tuple[float, float] | None = None
        self._start_roi: tuple[float, float, float, float] | None = None

    def _handle_hit_radius(self) -> float:
        return max(8.0, min(self.w, self.h) * 0.08, self.MIN_SIZE * 0.5)

    def _handle_points(self) -> dict[str, tuple[float, float]]:
        x, y, w, h = self.x, self.y, self.w, self.h
        return {
            "nw": (x, y),
            "n": (x + w / 2, y),
            "ne": (x + w, y),
            "e": (x + w, y + h / 2),
            "se": (x + w, y + h),
            "s": (x + w / 2, y + h),
            "sw": (x, y + h),
            "w": (x, y + h / 2),
        }

    def _clamp_roi(self, x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
        w = max(self.MIN_SIZE, min(w, self.img_w))
        h = max(self.MIN_SIZE, min(h, self.img_h))
        x = max(0, min(x, self.img_w - w))
        y = max(0, min(y, self.img_h - h))
        return int(round(x)), int(round(y)), int(round(w)), int(round(h))

    def _point_in_rect(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h

    def _hit_handle(self, px: float, py: float) -> str | None:
        radius = self._handle_hit_radius()
        for name, (hx, hy) in self._handle_points().items():
            if abs(px - hx) <= radius and abs(py - hy) <= radius:
                return name
        return None

    def _set_roi(self, x: float, y: float, w: float, h: float) -> None:
        self.x, self.y, self.w, self.h = self._clamp_roi(x, y, w, h)

    def _update_artists(self) -> None:
        self.rect_patch.set_xy((self.x, self.y))
        self.rect_patch.set_width(self.w)
        self.rect_patch.set_height(self.h)

        points = self._handle_points()
        xs = [points[name][0] for name in self.HANDLE_NAMES]
        ys = [points[name][1] for name in self.HANDLE_NAMES]
        self.handle_scatter.set_offsets(np.column_stack([xs, ys]))

        self.status_text.set_text(
            f"x={self.x}, y={self.y}, w={self.w}, h={self.h}  "
            f"({self.w * 3.45:.0f} x {self.h * 3.45:.0f} um)"
        )
        self.fig.canvas.draw_idle()

    def _on_press(self, event) -> None:
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button != 1:
            return

        px, py = float(event.xdata), float(event.ydata)
        handle = self._hit_handle(px, py)
        if handle is not None:
            self._mode = handle
        elif self._point_in_rect(px, py):
            self._mode = "move"
        else:
            self._mode = "create"
            self._set_roi(px, py, 1, 1)

        self._press_xy = (px, py)
        self._start_roi = (float(self.x), float(self.y), float(self.w), float(self.h))

    def _on_motion(self, event) -> None:
        if self._mode is None or self._press_xy is None or self._start_roi is None:
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return

        px, py = float(event.xdata), float(event.ydata)
        sx, sy = self._press_xy
        x0, y0, w0, h0 = self._start_roi

        if self._mode == "move":
            self._set_roi(x0 + (px - sx), y0 + (py - sy), w0, h0)
        elif self._mode == "create":
            x = min(sx, px)
            y = min(sy, py)
            w = max(self.MIN_SIZE, abs(px - sx))
            h = max(self.MIN_SIZE, abs(py - sy))
            self._set_roi(x, y, w, h)
        else:
            x, y, w, h = x0, y0, w0, h0
            mode = self._mode

            if mode == "nw":
                x2, y2 = x0 + w0, y0 + h0
                x = min(px, x2 - self.MIN_SIZE)
                y = min(py, y2 - self.MIN_SIZE)
                w = x2 - x
                h = y2 - y
            elif mode == "ne":
                y2 = y0 + h0
                w = max(self.MIN_SIZE, px - x0)
                y = min(py, y2 - self.MIN_SIZE)
                h = y2 - y
            elif mode == "sw":
                x2 = x0 + w0
                x = min(px, x2 - self.MIN_SIZE)
                w = x2 - x
                h = max(self.MIN_SIZE, py - y0)
            elif mode == "se":
                w = max(self.MIN_SIZE, px - x0)
                h = max(self.MIN_SIZE, py - y0)
            elif mode == "n":
                y2 = y0 + h0
                y = min(py, y2 - self.MIN_SIZE)
                h = y2 - y
            elif mode == "s":
                h = max(self.MIN_SIZE, py - y0)
            elif mode == "w":
                x2 = x0 + w0
                x = min(px, x2 - self.MIN_SIZE)
                w = x2 - x
            elif mode == "e":
                w = max(self.MIN_SIZE, px - x0)

            self._set_roi(x, y, w, h)

        self._update_artists()

    def _on_release(self, event) -> None:
        self._mode = None
        self._press_xy = None
        self._start_roi = None

    def _on_key(self, event) -> None:
        if event.key in ("enter", "return"):
            self._finish(accepted=True)
        elif event.key == "escape":
            self._finish(accepted=False)

    def _on_confirm(self, _event) -> None:
        self._finish(accepted=True)

    def _finish(self, *, accepted: bool) -> None:
        import matplotlib.pyplot as plt

        if accepted and self.w > 0 and self.h > 0:
            self.result = (self.x, self.y, self.w, self.h)
        else:
            self.cancelled = True
        plt.close(self.fig)

    def run(self) -> tuple[int, int, int, int] | None:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        from matplotlib.widgets import Button

        _ensure_interactive_backend()

        print(self.title)
        print("Interactive ROI:")
        print("  - Drag inside the box to move it")
        print("  - Drag corners/edges to resize")
        print("  - Click and drag outside the box to draw a new one")
        print("  - Press Enter or click Confirm ROI when done (Esc to cancel)")

        self.fig, self.ax = plt.subplots(figsize=(12, 9))
        self.ax.imshow(self.image, cmap="gray", origin="upper")
        self.rect_patch = Rectangle(
            (self.x, self.y),
            self.w,
            self.h,
            linewidth=2,
            edgecolor="lime",
            facecolor="lime",
            alpha=0.15,
        )
        self.ax.add_patch(self.rect_patch)

        points = self._handle_points()
        handle_xy = np.array([[points[name][0], points[name][1]] for name in self.HANDLE_NAMES])
        self.handle_scatter = self.ax.scatter(
            handle_xy[:, 0],
            handle_xy[:, 1],
            s=55,
            marker="s",
            c="yellow",
            edgecolors="black",
            linewidths=0.8,
            zorder=5,
        )

        self.status_text = self.ax.text(
            0.02,
            0.98,
            "",
            transform=self.ax.transAxes,
            va="top",
            ha="left",
            color="white",
            fontsize=10,
            bbox={"facecolor": "black", "alpha": 0.65, "pad": 4},
        )
        self._update_artists()

        self.ax.set_title(
            f"{self.title}\n"
            "Drag box to move | drag handles to resize | Enter or Confirm to save"
        )

        btn_ax = self.fig.add_axes([0.78, 0.02, 0.18, 0.05])
        confirm_btn = Button(btn_ax, "Confirm ROI")
        confirm_btn.on_clicked(self._on_confirm)

        self.fig.canvas.mpl_connect("button_press_event", self._on_press)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self.fig.subplots_adjust(bottom=0.08)
        plt.show(block=True)

        if self.cancelled or self.result is None:
            return None

        x, y, w, h = self.result
        print(f"ROI (sensor pixels): x={x}, y={y}, w={w}, h={h}")
        return self.result


def _select_roi_matplotlib(
    image_u8: np.ndarray,
    title: str,
    initial_roi: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    """Interactive draggable/resizable ROI picker (works when OpenCV has no GUI support)."""
    picker = _InteractiveRoiPicker(image_u8, title, initial_roi=initial_roi)
    return picker.run()


def select_roi_from_tif(
    tif_path: Path,
    initial_roi: tuple[int, int, int, int] | None = None,
) -> tuple[int, int, int, int] | None:
    """Freeze a saved TIFF and drag an ROI around the bright beam core."""
    u8 = _normalize_to_u8(tiff.imread(tif_path))

    if initial_roi is None and DEFAULT_ROI_FILE.is_file():
        try:
            initial_roi = load_roi(DEFAULT_ROI_FILE)
        except (json.JSONDecodeError, KeyError, ValueError):
            initial_roi = None

    if _opencv_gui_available():
        import cv2

        print(f"Select ROI on {tif_path.name}")
        print("Drag a box around the bright center of the beam. Press Enter to accept, Esc to cancel.")
        roi = cv2.selectROI("Select Beam ROI", u8, fromCenter=True, showCrosshair=True)
        cv2.destroyAllWindows()
        if roi is None or roi[2] == 0 or roi[3] == 0:
            return None
        x, y, w, h = map(int, roi)
        print(f"ROI (sensor pixels): x={x}, y={y}, w={w}, h={h}")
        return (x, y, w, h)

    print("OpenCV GUI unavailable; using matplotlib ROI selector instead.")
    return _select_roi_matplotlib(
        u8,
        f"Select Beam ROI: {tif_path.name}",
        initial_roi=initial_roi,
    )


def suggest_roi_from_tif(
    tif_path: Path,
    threshold_fraction: float = 0.15,
    pad_px: int = 30,
) -> tuple[int, int, int, int]:
    """Estimate an ROI around the brightest region (useful before manual refinement)."""
    img = _to_grayscale(np.asarray(tiff.imread(tif_path))).astype(np.float64)
    level = threshold_fraction * float(img.max())
    mask = img >= level
    ys, xs = np.where(mask)
    if xs.size == 0:
        raise RuntimeError(f"Could not find a bright region in {tif_path.name}")

    h, w = img.shape
    x_min = max(0, int(xs.min()) - pad_px)
    x_max = min(w, int(xs.max()) + pad_px + 1)
    y_min = max(0, int(ys.min()) - pad_px)
    y_max = min(h, int(ys.max()) + pad_px + 1)
    return (x_min, y_min, x_max - x_min, y_max - y_min)


def select_roi_live(cam_serial: str | None = None) -> tuple[int, int, int, int] | None:
    """Pick ROI from the live Thorcam feed."""
    import time

    sys.path.insert(0, str(INTERFEROMETER_DIR))
    from interferometer_acquire_analyze import select_roi, setup_camera

    if _opencv_gui_available():
        cam = setup_camera(cam_serial)
        if cam is None:
            raise RuntimeError("No Thorcam found. Close ThorCam GUI if it is open, then retry.")
        try:
            print("Draw the ROI around the bright beam core, not the full frame.")
            return select_roi(cam)
        finally:
            cam.close()

    print("OpenCV GUI unavailable; grabbing one live frame and using matplotlib ROI selector.")
    cam = setup_camera(cam_serial)
    if cam is None:
        raise RuntimeError("No Thorcam found. Close ThorCam GUI if it is open, then retry.")
    try:
        cam.start_acquisition()
        time.sleep(2.0)
        frame = None
        deadline = time.perf_counter() + 15.0
        while time.perf_counter() < deadline:
            candidate = cam.read_newest_image()
            if candidate is not None:
                frame = candidate
                break
            time.sleep(0.1)
        if frame is None:
            raise RuntimeError("Camera returned no frame for ROI selection.")
        u8 = _normalize_to_u8(frame)
        initial_roi = None
        if DEFAULT_ROI_FILE.is_file():
            try:
                initial_roi = load_roi(DEFAULT_ROI_FILE)
            except (json.JSONDecodeError, KeyError, ValueError):
                initial_roi = None
        return _select_roi_matplotlib(
            u8,
            "Select Beam ROI: live camera frame",
            initial_roi=initial_roi,
        )
    finally:
        try:
            cam.stop_acquisition()
        except Exception:
            pass
        cam.close()
