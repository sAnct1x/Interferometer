"""Integrated hardware and host system status tile."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout

from config import LASER_WAVELENGTH_NM
from gui.glass_panel import GlassPanel
from gui.typography import muted_style, value_style


class HardwareStatusPanel(GlassPanel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="System Status")
        self._fields: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        rows = [
            ("Wavelength (λ)", f"{LASER_WAVELENGTH_NM:.1f} nm", "wavelength"),
            ("Far Field Cam", "Idle", "camera_far_field"),
            ("Output Cam", "—", "camera_output"),
            ("Stage", "Disconnected", "stage"),
            ("Wavelength scan", "Idle", "scan"),
            ("UI scale", "100%", "ui_scale"),
            ("Display", "—", "display"),
            ("Laser", "Manual / Off", "laser"),
            ("Beam offset (Δ)", "—", "coupling_err", "How far the beam center is from its target."),
            ("Beam angle (θ)", "—", "coupling_ang", "The beam's pointing angle relative to target."),
            ("CPU", "—", "cpu"),
            ("RAM", "—", "ram"),
            ("Network", "—", "network"),
        ]
        for row, row_data in enumerate(rows):
            label, default, key = row_data[0], row_data[1], row_data[2]
            tip = row_data[3] if len(row_data) > 3 else ""
            name = QLabel(label)
            name.setStyleSheet(muted_style())
            val = QLabel(default)
            val.setStyleSheet(value_style())
            if tip:
                name.setToolTip(tip)
                val.setToolTip(tip)
            grid.addWidget(name, row, 0)
            grid.addWidget(val, row, 1)
            self._fields[key] = val

        layout.addLayout(grid)

    def update_status(self, data: dict) -> None:
        if "wavelength_nm" in data:
            lam = data["wavelength_nm"]
            if lam is not None and lam == lam:
                self._fields["wavelength"].setText(f"{float(lam):.2f} nm")
        # camera_far_field / camera_output carry the full formatted status string
        # from the dashboard (label · S/N · state · exposure).
        if "camera_far_field" in data:
            self._fields["camera_far_field"].setText(str(data["camera_far_field"]))
        if "camera_output" in data:
            self._fields["camera_output"].setText(str(data["camera_output"]))
        if "stage" in data:
            self._fields["stage"].setText(str(data["stage"]))
        if "scan" in data:
            self._fields["scan"].setText(str(data["scan"]))
        if "ui_scale" in data:
            self._fields["ui_scale"].setText(str(data["ui_scale"]))
        if "display" in data:
            self._fields["display"].setText(str(data["display"]))
        if "laser" in data:
            self._fields["laser"].setText(str(data["laser"]))
        if "coupling_err" in data:
            self._fields["coupling_err"].setText(str(data["coupling_err"]))
        if "coupling_ang" in data:
            self._fields["coupling_ang"].setText(str(data["coupling_ang"]))
        if "cpu" in data:
            self._fields["cpu"].setText(str(data["cpu"]))
        if "ram" in data:
            self._fields["ram"].setText(str(data["ram"]))
        if "network" in data:
            self._fields["network"].setText(str(data["network"]))
