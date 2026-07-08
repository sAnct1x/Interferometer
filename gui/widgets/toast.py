"""Floating toast notifications for status feedback that would otherwise be
buried in the (hidden by default) Task Manager tile or a truncated telemetry
chip. Purely visual, auto-dismissing, and never blocks input."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QSizePolicy, QVBoxLayout, QWidget

from gui.glass_panel import octagon_path
from gui.neon_theme import COLOR_CYAN, COLOR_HOT, COLOR_PINK, glass_fill_gradient, tile_dark_overlay
from gui.typography import TEXT_PRIMARY, body_pt

_MAX_VISIBLE = 3
_MAX_WIDTH_PX = 320
_FADE_IN_MS = 150
_HOLD_MS = 2200
_FADE_OUT_MS = 400


class _ToastPill(QWidget):
    """One auto-dismissing message. ``kind`` picks the border accent."""

    def __init__(self, text: str, kind: str, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMaximumWidth(_MAX_WIDTH_PX)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(_MAX_WIDTH_PX - 28)
        label.setStyleSheet(
            f"QLabel {{ color: {TEXT_PRIMARY}; font-size: {max(9, int(body_pt()))}pt; "
            "background: transparent; }"
        )
        layout.addWidget(label)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade_anim: QPropertyAnimation | None = None

    def start_lifecycle(self, on_dismissed) -> None:
        self._on_dismissed = on_dismissed
        self._fade_to(1.0, _FADE_IN_MS)
        QTimer.singleShot(_FADE_IN_MS + _HOLD_MS, self._begin_fade_out)

    def _begin_fade_out(self) -> None:
        self._fade_to(0.0, _FADE_OUT_MS, then=self._dismiss)

    def _fade_to(self, target: float, duration_ms: int, *, then=None) -> None:
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(duration_ms)
        anim.setStartValue(self._effect.opacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if then is not None:
            anim.finished.connect(then)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    def _dismiss(self) -> None:
        if self._on_dismissed is not None:
            self._on_dismissed(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = octagon_path(rect, chamfer=10)
        painter.fillPath(path, glass_fill_gradient(rect, path))
        painter.fillPath(path, tile_dark_overlay())

        accent = COLOR_HOT if self._kind == "error" else COLOR_CYAN
        outer = QPen(accent, 2)
        painter.setPen(outer)
        painter.drawPath(path)
        inner = QPen(COLOR_PINK if self._kind != "error" else QColor(255, 200, 90), 1)
        painter.setPen(inner)
        painter.drawPath(path)


class ToastOverlay(QWidget):
    """Bottom-anchored stack of auto-dismissing notifications.

    Parented directly to the main window (same pattern as the hex rail and
    minimized-tile bar overlays) and repositioned on resize by the caller.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self._pills: list[_ToastPill] = []

    def show_message(self, text: str, kind: str = "info") -> None:
        """Queue a toast. ``kind`` is ``"info"`` (default) or ``"error"``."""
        if not text:
            return
        while len(self._pills) >= _MAX_VISIBLE:
            self._remove_pill(self._pills[0])

        pill = _ToastPill(text, kind, self)
        self._pills.append(pill)
        self._layout.addWidget(pill)
        pill.start_lifecycle(self._remove_pill)

    def _remove_pill(self, pill: _ToastPill) -> None:
        if pill not in self._pills:
            return
        self._pills.remove(pill)
        self._layout.removeWidget(pill)
        pill.setParent(None)
        pill.deleteLater()

    def pending_count(self) -> int:
        """Number of toasts currently visible (used by tests)."""
        return len(self._pills)
