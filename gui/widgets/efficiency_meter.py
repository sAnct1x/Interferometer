"""Vertical fiber output efficiency meter for hollow-core fiber exit (eta)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy

from gui.glass_panel import GlassPanel, PentagonButton
from gui.typography import callout_style, hint_style, muted_style


class EfficiencyMeterPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Beam Efficiency")
        self._eta: float | None = None
        self._detail = "Hollow-core fiber exit · calibrate P(in) baseline"

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(6)

        self._value = QLabel("— %")
        self._value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value.setStyleSheet(callout_style())
        layout.addWidget(self._value)

        self._sub = QLabel(self._detail)
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(muted_style())
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub)

        self._bar = _ThermoBar()
        layout.addWidget(self._bar, stretch=1)

        self._formula = QLabel("η = P(out) / P(in)  ·  fiber exit power fraction")
        self._formula.setStyleSheet(hint_style())
        self._formula.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._formula)

        self._cal_btn = PentagonButton("Set as η = 100%", compact=True)
        cal_row = QHBoxLayout()
        cal_row.addStretch()
        cal_row.addWidget(self._cal_btn)
        cal_row.addStretch()
        layout.addLayout(cal_row)

    def bind_calibrate(self, callback) -> None:
        self._cal_btn.clicked.connect(callback)

    def set_efficiency(self, eta_pct: float | None, *, detail: str = "") -> None:
        self._eta = eta_pct
        if eta_pct is None or eta_pct != eta_pct:
            self._value.setText("— %")
            self._bar.set_level(0.0, eta_pct=None)
        else:
            clamped = min(max(float(eta_pct), 0.0), 100.0)
            self._value.setText(f"{clamped:.2f} %")
            self._bar.set_level(clamped / 100.0, eta_pct=clamped)
        if detail:
            self._sub.setText(detail)

    def current_efficiency_pct(self) -> float | None:
        eta = self._eta
        if eta is None or eta != eta:
            return None
        return float(eta)

    def reset(self) -> None:
        self.set_efficiency(
            None,
            detail="Enable live feed · use Side-by-Side view to calibrate dual-camera η",
        )


class _ThermoBar(QWidget):
    """Vertical η axis with labeled percent ticks and live readout."""

    TICK_PCTS = (0, 10, 25, 50, 75, 90, 100)

    def __init__(self) -> None:
        super().__init__()
        self._level = 0.0
        self._eta_pct: float | None = None
        self.setMinimumSize(80, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_level(self, level: float, *, eta_pct: float | None = None) -> None:
        self._level = max(0.0, min(1.0, level))
        self._eta_pct = eta_pct
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        margin = 6
        axis_w = 22
        tick_w = 46
        inner = self.rect().adjusted(margin, margin, -margin, -margin)
        bar_w = max(28, inner.width() - axis_w - tick_w)
        bar = QRect(inner.left() + axis_w, inner.top(), bar_w, inner.height())

        # Y-axis title
        from gui.typography import TEXT_MUTED, TEXT_PRIMARY, body_pt

        body = max(8.0, body_pt())
        title_font = QFont("Consolas", int(body), QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(
            QRect(inner.left(), inner.top(), axis_w - 4, inner.height()),
            Qt.AlignmentFlag.AlignCenter,
            "η\n(%)",
        )

        # Bar frame
        painter.fillRect(bar, QColor(15, 8, 35, 190))
        for width, alpha, color in (
            (8, 25, (255, 0, 110)),
            (5, 40, (168, 85, 247)),
            (2, 80, (0, 245, 255)),
        ):
            glow = QPen(QColor(*color, alpha), width)
            painter.setPen(glow)
            painter.drawRect(bar)
        painter.setPen(QPen(QColor(0, 245, 255, 180), 2))
        painter.drawRect(bar)

        # Fill
        fill_h = int(bar.height() * self._level)
        if fill_h > 0:
            grad = QLinearGradient(0, bar.bottom(), 0, bar.top())
            grad.setColorAt(0.0, QColor(124, 58, 237, 240))
            grad.setColorAt(0.35, QColor(236, 72, 153, 240))
            grad.setColorAt(0.7, QColor(59, 130, 255, 240))
            grad.setColorAt(1.0, QColor(0, 245, 255, 255))
            fill_rect = bar.adjusted(2, bar.height() - fill_h + 2, -2, -2)
            painter.fillRect(fill_rect, grad)

        tick_font = QFont("Consolas", int(body))
        painter.setFont(tick_font)
        tick_pen = QPen(QColor(TEXT_MUTED))
        label_pen = QColor(TEXT_PRIMARY)

        for pct in self.TICK_PCTS:
            y = bar.bottom() - int(bar.height() * pct / 100)
            painter.setPen(tick_pen)
            painter.drawLine(bar.right() + 3, y, bar.right() + 11, y)
            painter.setPen(label_pen)
            painter.drawText(bar.right() + 13, y + 4, f"{pct:.0f}%")

        # Live efficiency marker at fill height
        if self._eta_pct is not None and self._eta_pct == self._eta_pct:
            live_y = bar.bottom() - int(bar.height() * self._level)
            painter.setPen(QPen(QColor(TEXT_MUTED), 2))
            painter.drawLine(bar.left() - 4, live_y, bar.right() + 2, live_y)
            live_font = QFont("Consolas", int(body), QFont.Weight.Bold)
            painter.setFont(live_font)
            painter.setPen(QColor(TEXT_PRIMARY))
            live_label = f"{self._eta_pct:.2f}%"
            painter.drawText(bar.left(), live_y - 14, live_label)
