"""Wavelength display with three selectable modes."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QLabel, QRadioButton, QButtonGroup, QFileDialog

from config import LASER_WAVELENGTH_NM
from gui.glass_panel import GlassPanel, PentagonButton


class WavelengthPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Wavelength")
        self._on_mode_change = None
        self._on_load_scan = None

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)

        self._value = QLabel(f"{LASER_WAVELENGTH_NM:.1f} nm")
        self._value.setStyleSheet(
            "color: #00e5ff; font-size: 28px; font-family: Consolas; "
            "background: rgba(0,229,255,0.06); padding: 4px 8px; "
            "border: 1px solid rgba(0,229,255,0.35); border-radius: 6px;"
        )
        layout.addWidget(self._value)

        self._detail = QLabel("Mode: nominal (520 nm green diode)")
        self._detail.setStyleSheet("color: #64748b;")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        self._group = QButtonGroup(self)
        for i, (label, mode) in enumerate(
            [
                ("Nominal label (520 nm)", "nominal"),
                ("Last scan result", "last_scan"),
                ("Live / active estimate", "live"),
            ]
        ):
            rb = QRadioButton(label)
            rb.setProperty("mode", mode)
            if mode == "nominal":
                rb.setChecked(True)
            self._group.addButton(rb, i)
            layout.addWidget(rb)
        self._group.idClicked.connect(self._mode_clicked)

        load_btn = PentagonButton("Load Scan CSV…")
        load_btn.clicked.connect(self._pick_csv)
        layout.addWidget(load_btn)

        self._cal_btn = PentagonButton("Calibrate η baseline")
        layout.addWidget(self._cal_btn)
        layout.addStretch()

    def bind(self, *, on_mode_change, on_load_scan, on_calibrate=None) -> None:
        self._on_mode_change = on_mode_change
        self._on_load_scan = on_load_scan
        if on_calibrate:
            self._cal_btn.clicked.connect(on_calibrate)

    def set_mode(self, mode: str) -> None:
        for btn in self._group.buttons():
            if btn.property("mode") == mode:
                btn.setChecked(True)
                break

    def set_wavelength(self, nm: float | None, *, detail: str = "") -> None:
        if nm is None or nm != nm:
            self._value.setText("—")
        else:
            self._value.setText(f"{nm:.2f} nm")
        if detail:
            self._detail.setText(detail)

    def _mode_clicked(self, _id: int) -> None:
        btn = self._group.checkedButton()
        if btn and self._on_mode_change:
            self._on_mode_change(btn.property("mode"))

    def _pick_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select scan CSV", filter="CSV (*.csv)")
        if path and self._on_load_scan:
            self._on_load_scan(path)
