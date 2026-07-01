"""Stage jog controls, travel limits, and multi-stage selection."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from core.config_store import StageLimits
from gui.glass_panel import GlassPanel, PentagonButton
from gui.typography import callout_style, muted_style, section_style, TEXT_PRIMARY

_FIELD_STYLE = (
    "QLineEdit, QDoubleSpinBox, QComboBox {"
    "  min-height: 28px;"
    "  padding: 4px 8px;"
    "  background: rgba(18,8,40,0.85);"
    "  color: " + TEXT_PRIMARY + ";"
    "  border: 1px solid #a855f7;"
    "  border-radius: 4px;"
    "}"
    "QComboBox::drop-down {"
    "  border: none;"
    "  width: 22px;"
    "}"
    "QComboBox QAbstractItemView {"
    "  background: rgba(12,8,32,0.97);"
    "  color: " + TEXT_PRIMARY + ";"
    "  selection-background-color: rgba(168,85,247,0.45);"
    "}"
)

_LABEL_STYLE = muted_style()


class StageControlPanel(GlassPanel):
    stage_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Stage Control")
        self._on_jog = None
        self._on_save_limits = None
        self._on_safe_home = None
        self._on_mark_home = None
        self._on_connect = None
        self._on_add_stage = None
        self._combo_block = False
        self._loaded_limits: StageLimits | None = None

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(8)
        stage_pick = QLabel("Stage")
        stage_pick.setStyleSheet(_LABEL_STYLE)
        self._stage_combo = QComboBox()
        self._stage_combo.setStyleSheet(_FIELD_STYLE)
        self._stage_combo.currentIndexChanged.connect(self._on_stage_combo_changed)
        stage_row.addWidget(stage_pick)
        stage_row.addWidget(self._stage_combo, stretch=1)
        layout.addLayout(stage_row)

        self._pos_label = QLabel("Position: —")
        self._pos_label.setMinimumHeight(36)
        self._pos_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pos_label.setStyleSheet(callout_style())
        layout.addWidget(self._pos_label)

        jog_row = QHBoxLayout()
        jog_row.setSpacing(6)
        back = PentagonButton("◀ −", compact=True)
        back.clicked.connect(lambda: self._emit_jog(-self._jog_spin.value()))
        fwd = PentagonButton("+ ▶", compact=True)
        fwd.clicked.connect(lambda: self._emit_jog(self._jog_spin.value()))
        jog_row.addWidget(back)
        step_label = QLabel("Step")
        step_label.setStyleSheet(_LABEL_STYLE)
        jog_row.addWidget(step_label)
        self._jog_spin = QDoubleSpinBox()
        self._jog_spin.setRange(0.001, 5.0)
        self._jog_spin.setValue(0.1)
        self._jog_spin.setSuffix(" mm")
        self._jog_spin.setMinimumWidth(88)
        self._jog_spin.setStyleSheet(_FIELD_STYLE)
        jog_row.addWidget(self._jog_spin)
        jog_row.addWidget(fwd)
        jog_row.addStretch()
        layout.addLayout(jog_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        connect_btn = PentagonButton("Connect", compact=True)
        connect_btn.clicked.connect(lambda: self._on_connect and self._on_connect())
        mark = PentagonButton("Save Home", compact=True)
        mark.clicked.connect(lambda: self._on_mark_home and self._on_mark_home())
        go_home = PentagonButton("Go Home", compact=True)
        go_home.clicked.connect(lambda: self._on_safe_home and self._on_safe_home())
        for btn in (connect_btn, mark, go_home):
            action_row.addWidget(btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(2)
        sep.setStyleSheet("background: rgba(0,229,255,0.25); border: none;")
        layout.addWidget(sep)

        limits_label = QLabel("Travel limits")
        limits_label.setStyleSheet(section_style())
        layout.addWidget(limits_label)

        serial_row = QHBoxLayout()
        serial_row.setSpacing(8)
        serial_caption = QLabel("K-Cube serial")
        serial_caption.setStyleSheet(_LABEL_STYLE)
        self._serial = QLineEdit()
        self._serial.setPlaceholderText("Optional USB serial")
        self._serial.setStyleSheet(_FIELD_STYLE)
        serial_row.addWidget(serial_caption)
        serial_row.addWidget(self._serial, stretch=1)
        layout.addLayout(serial_row)

        limits_grid = QGridLayout()
        limits_grid.setHorizontalSpacing(10)
        limits_grid.setVerticalSpacing(4)

        self._min_mm = QDoubleSpinBox()
        self._min_mm.setRange(-100, 100)
        self._max_mm = QDoubleSpinBox()
        self._max_mm.setRange(0, 500)
        self._max_mm.setValue(25)
        self._max_jog = QDoubleSpinBox()
        self._max_jog.setRange(0.001, 10)
        self._max_jog.setValue(0.5)
        for spin in (self._min_mm, self._max_mm, self._max_jog):
            spin.setStyleSheet(_FIELD_STYLE)
            spin.setMinimumHeight(28)

        limits_grid.addWidget(self._limit_caption("Min (mm)"), 0, 0)
        limits_grid.addWidget(self._limit_caption("Max (mm)"), 0, 1)
        limits_grid.addWidget(self._limit_caption("Max jog"), 0, 2)
        limits_grid.addWidget(self._min_mm, 1, 0)
        limits_grid.addWidget(self._max_mm, 1, 1)
        limits_grid.addWidget(self._max_jog, 1, 2)
        layout.addLayout(limits_grid)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        save_lim = PentagonButton("Save Limits", compact=True)
        save_lim.clicked.connect(self._save_limits)
        footer.addWidget(save_lim)
        add_stage = PentagonButton("Add stage", compact=True)
        add_stage.clicked.connect(lambda: self._on_add_stage and self._on_add_stage())
        footer.addWidget(add_stage)
        footer.addStretch()
        layout.addLayout(footer)

    def _limit_caption(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(_LABEL_STYLE)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lab

    def bind(
        self,
        *,
        on_jog,
        on_save_limits,
        on_safe_home,
        on_mark_home,
        on_connect,
        on_add_stage=None,
    ) -> None:
        self._on_jog = on_jog
        self._on_save_limits = on_save_limits
        self._on_safe_home = on_safe_home
        self._on_mark_home = on_mark_home
        self._on_connect = on_connect
        self._on_add_stage = on_add_stage

    def set_stages(self, stages: list[StageLimits], active_index: int = 0) -> None:
        self._combo_block = True
        self._stage_combo.clear()
        for idx, stage in enumerate(stages):
            label = stage.name
            if stage.serial:
                label = f"{stage.name} · {stage.serial}"
            self._stage_combo.addItem(label, idx)
        if stages:
            pick = max(0, min(active_index, len(stages) - 1))
            self._stage_combo.setCurrentIndex(pick)
            self.load_limits(stages[pick])
        self._combo_block = False

    def current_stage_index(self) -> int:
        data = self._stage_combo.currentData()
        if data is None:
            return 0
        return int(data)

    def build_limits(self) -> StageLimits:
        name = self._stage_combo.currentText().split(" · ")[0].strip() or "Stage"
        serial = self._serial.text().strip() or None
        enabled = self._loaded_limits.enabled if self._loaded_limits else True
        return StageLimits(
            name=name,
            serial=serial,
            min_mm=self._min_mm.value(),
            max_mm=self._max_mm.value(),
            max_jog_mm=self._max_jog.value(),
            enabled=enabled,
        )

    def set_position_mm(self, pos: float) -> None:
        if pos != pos:
            self._pos_label.setText("Position: —")
        else:
            self._pos_label.setText(f"Position: {pos:.4f} mm")

    def load_limits(self, lim: StageLimits) -> None:
        self._loaded_limits = lim
        self._min_mm.setValue(lim.min_mm)
        self._max_mm.setValue(lim.max_mm)
        self._max_jog.setValue(lim.max_jog_mm)
        self._serial.setText(lim.serial or "")

    def _on_stage_combo_changed(self, combo_index: int) -> None:
        if self._combo_block or combo_index < 0:
            return
        stage_index = self._stage_combo.itemData(combo_index)
        if stage_index is None:
            stage_index = combo_index
        self.stage_changed.emit(int(stage_index))

    def _emit_jog(self, delta: float) -> None:
        if self._on_jog:
            self._on_jog(delta)

    def _save_limits(self) -> None:
        if self._on_save_limits:
            self._on_save_limits(self.build_limits())
