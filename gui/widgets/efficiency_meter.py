"""Vertical fiber-output efficiency meter (Far Field → Output coupling η)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QWidget, QSizePolicy

from config import COUPLING_TARGET_PCT
from gui.glass_panel import GlassPanel, BracketButton
from gui.neon_theme import COLOR_BLUE, COLOR_CYAN, COLOR_HOT, COLOR_MAGENTA, COLOR_PURPLE
from gui.typography import callout_style, hint_style, muted_style


class EfficiencyMeterPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Beam Efficiency")
        self._eta: float | None = None
        target = float(COUPLING_TARGET_PCT)
        self._detail = (
            f"Start Live Feed — η tracks Far Field → Output automatically "
            f"(lab target ~{target:.0f}%)"
        )

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

        self._bar = _ThermoBar(target_pct=target)
        layout.addWidget(self._bar, stretch=1)

        self._formula = QLabel(
            f"η = P(out)/P(in)  ·  lab target ~{target:.0f}%  ·  auto-starts with live feed"
        )
        self._formula.setStyleSheet(hint_style())
        self._formula.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formula.setToolTip(
            "Coupling efficiency from Far Field (before fiber) to Output (after fiber). "
            f"Aim for ~{target:.0f}%. Recalibrate only when you have a known-good alignment."
        )
        layout.addWidget(self._formula)

        self._cal_btn = BracketButton("Recalibrate 100%", compact=True)
        self._cal_btn.setToolTip(
            "Mark the current Far Field / Output ratio as 100%. "
            "Live feed already auto-baselines once; use this after a known-good alignment."
        )
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
            self._value.setText(f"{clamped:.1f} %")
            self._bar.set_level(clamped / 100.0, eta_pct=clamped)
        if detail:
            self._sub.setText(detail)

    def current_efficiency_pct(self) -> float | None:
        eta = self._eta
        if eta is None or eta != eta:
            return None
        return float(eta)

    def reset(self) -> None:
        target = float(COUPLING_TARGET_PCT)
        self.set_efficiency(
            None,
            detail=(
                f"Start Live Feed — η tracks Far Field → Output automatically "
                f"(lab target ~{target:.0f}%)"
            ),
        )


class _ThermoBar(QWidget):
    """Vertical η axis with labeled percent ticks and a lab-target marker."""

    TICK_PCTS = (0, 10, 25, 50, 75, 90, 100)

    def __init__(self, *, target_pct: float = 90.0) -> None:
        super().__init__()
        self._level = 0.0
        self._eta_pct: float | None = None
        self._target_pct = float(target_pct)
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

        from gui.typography import TEXT_MUTED, TEXT_PRIMARY, body_pt

        body = max(8.0, body_pt())
        painter.fillRect(bar, QColor(20, 16, 40))

        fill_h = int(bar.height() * self._level)
        if fill_h > 0:
            fill = QRect(bar.left(), bar.bottom() - fill_h + 1, bar.width(), fill_h)
            grad = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            grad.setColorAt(0.0, COLOR_HOT)
            grad.setColorAt(0.45, COLOR_MAGENTA)
            grad.setColorAt(0.75, COLOR_PURPLE)
            grad.setColorAt(1.0, COLOR_CYAN)
            painter.fillRect(fill, grad)

        painter.setPen(QPen(COLOR_BLUE, 1))
        painter.drawRect(bar)

        # Target band (~90%)
        t = max(0.0, min(1.0, self._target_pct / 100.0))
        ty = bar.bottom() - int(bar.height() * t)
        painter.setPen(QPen(COLOR_CYAN, 2, Qt.PenStyle.DashLine))
        painter.drawLine(bar.left() - 2, ty, bar.right() + 2, ty)

        painter.setFont(QFont("Segoe UI", int(body)))
        painter.setPen(QColor(TEXT_MUTED))
        for pct in self.TICK_PCTS:
            y = bar.bottom() - int(bar.height() * (pct / 100.0))
            painter.drawLine(bar.right() + 2, y, bar.right() + 8, y)
            painter.drawText(
                QRect(bar.right() + 10, y - 8, tick_w - 12, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"{pct}",
            )

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(
            QRect(inner.left(), bar.top(), axis_w - 2, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            "η%",
        )

        if self._eta_pct is not None and self._eta_pct == self._eta_pct:
            live_label = f"{self._eta_pct:.1f}%"
            painter.setPen(QColor(COLOR_CYAN))
            painter.drawText(
                QRect(inner.left(), bar.bottom() - 18, axis_w + bar_w, 18),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                live_label,
            )
