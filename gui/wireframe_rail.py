"""Left hub rail: full-height Pleiad proximity point-cloud network overlay."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from config import PANEL_CORNER_RADIUS_PX
from gui.pleiad_network import PleiadNetwork
from gui.ui_scale import get_scale, px

# Idle vs. active tick rates. The rail is purely decorative, so it runs at a
# calm ~20 FPS when nothing is happening and lifts to ~30 FPS only while it is
# actively pulsing (Atria thinking / a simulation running). Both are far cheaper
# than the old fixed 30 FPS, and the timer is fully stopped whenever the rail is
# hidden or the window is minimized (see set_animation_active / showEvent).
_IDLE_INTERVAL_MS = 50   # ~20 FPS
_ACTIVE_INTERVAL_MS = 33  # ~30 FPS


class NetworkRail(QWidget):
    """Fixed-width left rail; mouse-transparent so tiles stay interactive."""

    WIDTH = 120

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._network = PleiadNetwork(node_count=72)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(self.WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._activity = 0.0
        # Gate that the owner (dashboard) flips on window minimize/restore so the
        # animation cannot keep burning CPU behind a minimized window.
        self._window_allows_anim = True

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(_IDLE_INTERVAL_MS)

    # -- animation lifecycle ------------------------------------------------
    def _should_animate(self) -> bool:
        return self._window_allows_anim and self.isVisible()

    def _sync_timer(self) -> None:
        """Start/stop the tick timer to match visibility + window state."""
        if self._should_animate():
            interval = _ACTIVE_INTERVAL_MS if self._activity > 0.0 else _IDLE_INTERVAL_MS
            if self._timer.interval() != interval:
                self._timer.setInterval(interval)
            if not self._timer.isActive():
                self._timer.start()
        elif self._timer.isActive():
            self._timer.stop()

    def set_animation_active(self, active: bool) -> None:
        """Owner hook: pause the rail while the window is minimized/hidden."""
        self._window_allows_anim = bool(active)
        self._sync_timer()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._sync_timer()

    def set_activity(self, level: float) -> None:
        """0 = idle, 1 = fully active; nudges the network's brightness pulse."""
        self._network.set_activity(level)
        self._activity = max(0.0, min(1.0, float(level)))
        self._sync_timer()

    def _tick(self) -> None:
        # Defensive: never step/repaint if we somehow tick while not visible.
        if not self._should_animate():
            self._timer.stop()
            return
        self._network.step(dt=1.0)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        margin = px(2, get_scale())
        radius = px(PANEL_CORNER_RADIUS_PX, get_scale())
        clip = QPainterPath()
        clip.addRoundedRect(
            QRectF(margin, margin, max(1.0, self.width() - 2 * margin), max(1.0, self.height() - 2 * margin)),
            radius,
            radius,
        )
        painter.setClipPath(clip)
        self._network.paint(painter, self.width(), self.height())
