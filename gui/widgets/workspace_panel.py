"""Workspace tile for viewing opened images, scans, and saved analysis artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
)

from gui.glass_panel import GlassPanel
from gui.typography import hint_style, muted_style, primary_style, TEXT_PRIMARY


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_TEXT_SUFFIXES = {".csv", ".txt", ".log", ".json"}


class WorkspacePanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Workspace")
        self._current_path: Path | None = None
        self._current_pixmap: QPixmap | None = None

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        self._path_label = QLabel("Open a file from File → Open in Workspace…")
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet(
            muted_style() + " font-family: Consolas; padding: 2px 4px;"
        )
        layout.addWidget(self._path_label)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._empty = QLabel("No file loaded.\n\nUse File → Open in Workspace to view images, CSV scans, or saved graphs.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(hint_style())
        self._stack.addWidget(self._empty)

        self._image_area = QScrollArea()
        self._image_area.setWidgetResizable(True)
        self._image_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._image_area.setWidget(self._image_label)
        self._stack.addWidget(self._image_area)

        self._text_view = QTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setStyleSheet(
            f"background: rgba(12,8,32,0.85); color: {TEXT_PRIMARY}; "
            "border: 1px solid #a855f7; border-radius: 6px; "
            "font-family: Consolas; padding: 8px;"
        )
        self._stack.addWidget(self._text_view)

        layout.addWidget(self._stack, stretch=1)

    def current_path(self) -> Path | None:
        return self._current_path

    def has_exportable_image(self) -> bool:
        return self._current_pixmap is not None and not self._current_pixmap.isNull()

    def current_pixmap(self) -> QPixmap | None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return None
        return self._current_pixmap

    def clear(self) -> None:
        self._current_path = None
        self._current_pixmap = None
        self._path_label.setText("Open a file from File → Open in Workspace…")
        self._image_label.clear()
        self._text_view.clear()
        self._stack.setCurrentWidget(self._empty)

    def open_file(self, path: Path) -> str | None:
        path = path.resolve()
        if not path.is_file():
            return f"File not found: {path}"

        suffix = path.suffix.lower()
        try:
            if suffix in _IMAGE_SUFFIXES:
                pix = QPixmap(str(path))
                if pix.isNull():
                    return f"Could not load image: {path.name}"
                self._show_image(path, pix)
                return None
            if suffix in _TEXT_SUFFIXES or suffix == "":
                text = path.read_text(encoding="utf-8", errors="replace")
                self._show_text(path, text)
                return None
            # Last resort: try as image
            pix = QPixmap(str(path))
            if not pix.isNull():
                self._show_image(path, pix)
                return None
            return f"Unsupported file type: {suffix or path.name}"
        except OSError as exc:
            return str(exc)

    def open_numpy_image(self, frame: np.ndarray, *, label: str = "Camera snapshot") -> None:
        gray = np.asarray(frame)
        if gray.ndim == 3:
            if gray.shape[2] >= 3:
                rgb = gray[:, :, :3].astype(np.uint8)
                h, w, _ = rgb.shape
                qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            else:
                gray = gray[:, :, 0]
                h, w = gray.shape
                qimg = QImage(gray.astype(np.uint8).data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            h, w = gray.shape
            qimg = QImage(gray.astype(np.uint8).data, w, h, w, QImage.Format.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg.copy())
        self._show_image(Path(label), pix, display_name=label)

    def _show_image(self, path: Path, pix: QPixmap, *, display_name: str | None = None) -> None:
        self._current_path = path
        self._current_pixmap = pix
        name = display_name or path.name
        self._path_label.setText(f"{name}  —  {path}")
        scaled = pix.scaled(
            max(200, self._image_area.width() - 24),
            max(200, self._image_area.height() - 24),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._stack.setCurrentWidget(self._image_area)

    def _show_text(self, path: Path, text: str) -> None:
        self._current_path = path
        self._current_pixmap = None
        self._path_label.setText(f"{path.name}  —  {path}")
        lines = text.splitlines()
        if len(lines) > 800:
            preview = "\n".join(lines[:800]) + f"\n\n… ({len(lines) - 800} more lines)"
        else:
            preview = text
        self._text_view.setPlainText(preview)
        self._stack.setCurrentWidget(self._text_view)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._stack.currentWidget() is self._image_area and self._current_pixmap is not None:
            scaled = self._current_pixmap.scaled(
                max(200, self._image_area.width() - 24),
                max(200, self._image_area.height() - 24),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_label.setPixmap(scaled)
