"""Main application window for the interferometer automation hub."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QEvent, QTimer, QRect
from PySide6.QtGui import QIcon, QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QFileDialog,
)

from config import APP_TITLE, ICONS_DIR, LASER_WAVELENGTH_NM, DATA_DIR, OUTPUT_DIR
from core.analytics.beam import analyze_frame, crop_box_from_xywh, roi_mean
from core.analytics.beam_quality import analyze_beam_quality
from core.analytics.coupling import coupling_overlay, default_target_center
from core.analytics.efficiency import coupling_efficiency_percent, dual_camera_efficiency_percent
from core.analytics.interferometer import recover_wavelength_from_csv
from core.camera_worker import CameraWorker
from core.snap_worker import SnapWorker
from core.simulation.frame_generator import SimulationFrameGenerator, make_simulation_frame
from core.simulation_worker import SimulationWorker
from core.config_store import AppConfig, CameraSlot, StageLimits, load_config, save_config
from core.laser_wavelength import resolve_wavelength_nm
from core.motion_control import MotionController
from core.scan_worker import WavelengthScanWorker
from core.system_stats import SystemStats, SystemStatsWorker
from ai.intents import DEFAULT_SIMULATION_DURATION_SEC, Intent
from ai.simulation_report import format_simulation_report
from gui.holo_background import HoloBackground
from gui.hub_chrome import HubChromeBar
from gui.neon_theme import CHROME_TELEMETRY_GAP_PX
from gui.hub_tile import HubTile, NON_SNAPPING_TILES
from gui.tile_layout import TileLayoutController
from gui.minimized_tile_bar import MinimizedTileBar
from gui.wireframe_rail import HexRailOverlay
from gui.widgets.ai_terminal import AtriaPanel
from gui.widgets.beam_plots import BeamPlotsPanel
from gui.widgets.camera_view import CameraView, RoiMode
from gui.widgets.efficiency_meter import EfficiencyMeterPanel
from gui.widgets.hardware_status import HardwareStatusPanel
from gui.widgets.stage_control import StageControlPanel
from gui.widgets.telemetry_bar import TelemetryBar
from gui.widgets.trend_panel import TrendPanel
from gui.widgets.roi_snapshot_panel import RoiSnapshotPanel
from gui.widgets.workspace_panel import WorkspacePanel
from gui.windows.tool_windows import (
    FftDiagnosticsPanel,
    PiezoOptimizerPanel,
    TaskManagerPanel,
)
from core.tile_layout_store import STARTUP_HIDDEN_TILES

# Tiles visible on first launch (optional tiles open from Tools / View menus)
DEFAULT_OPEN = {"beam", "camera", "roi_snapshot", "efficiency", "status", "trends", "atria"}
DEFAULT_HIDDEN = set(STARTUP_HIDDEN_TILES)

# View menu tile order (Workspace directly under Atria Chat).
VIEW_MENU_TILES: tuple[tuple[str, str], ...] = (
    ("beam", "3D Beam Profile"),
    ("trends", "Alignment Trends"),
    ("efficiency", "Beam Efficiency"),
    ("status", "System Status"),
    ("camera", "Live Camera"),
    ("roi_snapshot", "ROI Snap Shot"),
    ("atria", "Atria Chat"),
    ("workspace", "Workspace"),
)

# Tools menu: optional hub tiles (hidden until opened from menu).
TOOLS_MENU_TILES: tuple[tuple[str, str], ...] = (
    ("stage", "Stage Control"),
    ("piezo", "Piezo Alignment Optimizer"),
    ("fft", "Coupling Efficiency FFT"),
    ("tasks", "Atria Task Manager"),
)


class Dashboard(QMainWindow):
    TILE_SPECS: dict[str, tuple[str, str]] = {
        "camera": ("Live Camera", "Phase 1 — coupling reticle"),
        "roi_snapshot": ("ROI Snap Shot", "Phase 1 — frozen frame ROI"),
        "beam": ("3D Beam Profile", "Phase 1 — w₀ and M²"),
        "efficiency": ("Beam Efficiency", "Phase 1 — ground truth"),
        "status": ("System Status", "Phase 2 — hardware matrix"),
        "trends": ("Alignment Trends", "Phase 2 — η and w₀ history"),
        "stage": ("Stage Control", "K-Cube jog and limits"),
        "piezo": ("Piezo Alignment Optimizer", "Phase 3 — piezo calibration"),
        "fft": ("Coupling Efficiency FFT", "Phase 3 — vibration spectrum"),
        "tasks": ("Atria Task Manager", "Phase 3 — task queue"),
        "atria": ("Atria", "Phase 2 — command console"),
        "workspace": ("Workspace", "Review saved captures & data"),
    }

    def __init__(self) -> None:
        super().__init__()
        from gui.ui_scale import (
            screen_ui_scale,
            set_current_scale,
            window_minimum_size,
        )

        boot_scale = screen_ui_scale()
        set_current_scale(boot_scale)
        min_w, min_h = window_minimum_size(boot_scale)
        self.setMinimumSize(min_w, min_h)
        self._screen_hooked = False
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._layout_applied = False
        self._shutting_down = False
        self._pre_maximize_geometry = None
        self._main_drag_active = False
        self._tiles: dict[str, HubTile] = {}
        self._tile_layout = TileLayoutController(self)
        self._view_tile_actions: dict[str, object] = {}
        self._display_preset_actions: dict[str, QAction] = {}

        icon_path = ICONS_DIR / "app_icon.png"
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._cfg: AppConfig = load_config()
        from gui.ui_scale import preset_by_id, set_display_preset_id

        preset_id = self._cfg.ui_display_preset
        set_display_preset_id(preset_id if preset_by_id(preset_id) else "auto")
        self._telemetry: dict = {
            "wavelength_mode": self._cfg.wavelength_mode,
            "status": "Starting",
        }
        self._apply_wavelength_config()

        self._chrome = HubChromeBar(self)
        self._telemetry_bar = TelemetryBar()
        self._camera_panel = CameraView()
        self._roi_snapshot_panel = RoiSnapshotPanel()
        self._beam_panel = BeamPlotsPanel()
        self._efficiency_panel = EfficiencyMeterPanel()
        self._status_panel = HardwareStatusPanel()
        self._trend_panel = TrendPanel()
        self._stage_panel = StageControlPanel()
        self._piezo_panel = PiezoOptimizerPanel()
        self._fft_panel = FftDiagnosticsPanel()
        self._tasks_panel = TaskManagerPanel()
        self._ai_panel = AtriaPanel()
        self._workspace_panel = WorkspacePanel()

        self._camera_panel.set_roi(self._cfg.beam_roi, RoiMode.BEAM)
        self._roi_snapshot_panel.set_roi(self._cfg.beam_roi, RoiMode.BEAM)
        self._stage_panel.set_stages(self._cfg.stages, active_index=0)
        for i, slot in enumerate(self._cfg.cameras[:2]):
            self._camera_panel.set_camera_label(i, slot.label)
            if slot.serial:
                self._camera_panel.set_camera_serial(i, slot.serial)

        self.setStyleSheet(
            "QMainWindow::separator { background: transparent; width: 2px; height: 2px; }"
        )

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, CHROME_TELEMETRY_GAP_PX)
        shell_layout.setSpacing(CHROME_TELEMETRY_GAP_PX)
        shell_layout.addWidget(self._chrome)
        shell_layout.addWidget(self._telemetry_bar)
        self.setMenuWidget(shell)

        workspace = HoloBackground()
        workspace.setMinimumSize(60, 60)
        self.setCentralWidget(workspace)
        self._workspace = workspace

        self._hex_rail = HexRailOverlay(self)
        self._min_tile_bar = MinimizedTileBar(self)
        self._min_tile_bar.restore_requested.connect(self.restore_tile_from_bar)
        self._min_tile_bar.close_requested.connect(self._close_tile_from_bar)
        self._min_tile_bar.hide()

        self._register_tiles()
        self._validate_menu_wiring()
        self._apply_default_visibility()
        self._build_menus()

        self._motion = MotionController(self)
        self._camera_worker: CameraWorker | None = None
        self._camera_worker_b: CameraWorker | None = None
        self._camera_live = False
        self._camera_live_b = False
        # Live acquisition is paused when the Live Camera tile is hidden/minimized and
        # auto-resumed when it is shown again (see _on_camera_tile_visibility).
        self._camera_resume_on_show = False
        self._camera_resume_on_show_b = False
        self._last_frame_a: np.ndarray | None = None
        self._last_frame_b: np.ndarray | None = None
        self._last_exp_a_us: float = 1.0
        self._last_exp_b_us: float = 1.0
        self._simulation_active = False
        self._simulation_worker: SimulationWorker | None = None
        self._simulation_generator = SimulationFrameGenerator(load_config())
        self._scan_worker: WavelengthScanWorker | None = None
        self._snap_worker: SnapWorker | None = None
        self._resume_live_after_scan = False
        self._fft_times: list[float] = []
        self._fft_samples: list[float] = []
        self._fft_last_sample_t: float | None = None
        self._fft_plot_last_t: float = 0.0
        self._sim_analytics_last_t: float = 0.0
        self._sim_display_last_t: float = 0.0
        self._live_display_last_t: float = 0.0
        self._live_display_last_t_b: float = 0.0
        self._live_analytics_last_t: float = 0.0
        self._last_frame_processed_t: float = 0.0
        self._defer_screen_refit_until: float = 0.0
        self._last_applied_scale: float = boot_scale
        self._last_sim_overlay: dict | None = None
        self._last_live_overlay: dict | None = None
        self._simulation_planned_sec: float | None = None
        self._simulation_report_to_atria: bool = False
        self._simulation_last_frame: np.ndarray | None = None
        self._simulation_fft_peak_hz: float | None = None
        self._simulation_fft_rate_hz: float | None = None
        self._last_workspace_px: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._system_stats = SystemStats()
        self._stats_worker = SystemStatsWorker(self)
        self._stats_worker.stats_ready.connect(self._apply_system_stats)

        self._sys_timer = QTimer(self)
        self._sys_timer.setInterval(2000)
        self._sys_timer.timeout.connect(self._poll_system_stats)

        self._simulation_timer = QTimer(self)
        self._simulation_timer.setSingleShot(True)
        self._simulation_timer.timeout.connect(self._on_simulation_duration_elapsed)

        self._display_refresh_timer = QTimer(self)
        self._display_refresh_timer.setSingleShot(True)
        self._display_refresh_timer.timeout.connect(self._refresh_display_geometry)

        self._wire_signals()
        self._refresh_status()
        self._update_telemetry(status="Ready")
        self._apply_ui_scale()

    def _apply_ui_scale(self) -> None:
        """Recompute pixel sizes from the live workspace or current monitor."""
        from PySide6.QtWidgets import QApplication

        from gui.glass_panel import PentagonButton
        from gui.ui_scale import (
            apply_app_font_scale,
            rail_width,
            screen_ui_scale,
            set_current_scale,
            set_workspace_context,
            tile_min_size,
            ui_scale_summary,
            window_minimum_size,
        )
        from gui.window_controls import screen_for_widget

        screen = screen_for_widget(self)
        ws = self._tile_layout.workspace_rect()
        if ws.width() > 200 and ws.height() > 200:
            scale = set_workspace_context(ws.width(), ws.height(), screen)
        else:
            scale = screen_ui_scale(screen)
            set_current_scale(scale)

        if abs(scale - self._last_applied_scale) < 0.005:
            summary = ui_scale_summary()
            self._telemetry.update(summary)
            self._workspace.update()
            return

        self._last_applied_scale = scale

        geo = screen.availableGeometry() if screen is not None else None
        win_min_w, win_min_h = window_minimum_size(
            scale,
            screen_width=geo.width() if geo is not None else None,
            screen_height=geo.height() if geo is not None else None,
        )
        self.setMinimumSize(win_min_w, win_min_h)

        for tile_id, tile in self._tiles.items():
            mw, mh = tile_min_size(
                tile_id,
                scale,
                workspace_width=ws.width(),
                workspace_height=ws.height(),
            )
            tile.setMinimumSize(mw, mh)

        self._chrome.apply_ui_scale(scale)
        self._telemetry_bar.apply_ui_scale(scale)
        self._telemetry_bar.update()
        self._hex_rail.setFixedWidth(rail_width(scale))

        for tile in self._tiles.values():
            panel = tile.content_panel()
            if panel is None:
                continue
            from gui.glass_panel import GlassPanel
            from gui.typography import panel_title_stylesheet

            if isinstance(panel, GlassPanel):
                hdr = panel.header_widget()
                if hdr is not None:
                    hdr.set_title_stylesheet(panel_title_stylesheet(scale))
            for btn in panel.findChildren(PentagonButton):
                btn._apply_sizing()
            panel.update()

        app = QApplication.instance()
        if app is not None:
            apply_app_font_scale(app, scale)

        summary = ui_scale_summary()
        self._telemetry.update(summary)
        self._workspace.update()

    def _on_screen_changed(self, _screen=None) -> None:
        """Re-fit window and layout when dragged between monitors (1080p ↔ 1440p)."""
        from gui.window_controls import is_maximized, maximize_on_screen, screen_for_widget

        # Thorcam USB init can spuriously fire screenChanged; avoid showNormal/maximize flicker.
        if time.time() < self._defer_screen_refit_until:
            self._schedule_display_refresh(delay_ms=400)
            return

        # Don't snap or relayout while the user is actively dragging the window.
        if getattr(self, "_main_drag_active", False):
            return

        screen = screen_for_widget(self)
        maximized = is_maximized(self)
        nearly_full = False
        if screen is not None:
            avail = screen.availableGeometry()
            geo = self.geometry()
            nearly_full = (
                geo.width() >= int(avail.width() * 0.9)
                and geo.height() >= int(avail.height() * 0.9)
            )
        if maximized or nearly_full:
            maximize_on_screen(self, screen)
        self._schedule_display_refresh()

    def _schedule_display_refresh(self, delay_ms: int = 60) -> None:
        """Debounce scale + tile relayout until Qt finishes geometry updates."""
        self._display_refresh_timer.start(max(0, delay_ms))

    def _refresh_display_geometry(self) -> None:
        """Full UI scale and proportional tile relayout for the active monitor."""
        self._tile_layout.reset_layout_tracking()
        self._last_workspace_px = (0, 0, 0, 0)
        self._apply_ui_scale()
        self._sync_layout_after_resize()
        self._position_hex_rail()
        self._refresh_status()

    def _sync_layout_after_resize(self) -> None:
        """Reposition tiles after workspace geometry or UI scale changes."""
        if self._layout_applied:
            self._tile_layout.on_window_resized()

    # --- Tile registration ---

    def _register_tiles(self) -> None:
        widgets = {
            "camera": self._camera_panel,
            "roi_snapshot": self._roi_snapshot_panel,
            "beam": self._beam_panel,
            "efficiency": self._efficiency_panel,
            "status": self._status_panel,
            "trends": self._trend_panel,
            "stage": self._stage_panel,
            "piezo": self._piezo_panel,
            "fft": self._fft_panel,
            "tasks": self._tasks_panel,
            "atria": self._ai_panel,
            "workspace": self._workspace_panel,
        }
        for tile_id, widget in widgets.items():
            title, _ = self.TILE_SPECS[tile_id]
            tile = HubTile(tile_id, title, widget, self, self._workspace)
            tile.tile_closed.connect(self._on_tile_closed)
            tile.tile_drag_released.connect(self._on_tile_drag_released)
            tile.tile_double_clicked.connect(self._tile_layout.toggle_focus)
            tile.tile_resized.connect(self._tile_layout.handle_resize)
            tile.tile_visibility_changed.connect(self._on_tile_visibility_changed)
            self._tiles[tile_id] = tile

    def _validate_menu_wiring(self) -> None:
        """Fail fast in dev if a menu tile id is missing from the hub."""
        menu_ids = {tid for tid, _ in VIEW_MENU_TILES} | {tid for tid, _ in TOOLS_MENU_TILES}
        missing = sorted(menu_ids - set(self._tiles.keys()))
        if missing:
            raise RuntimeError(f"Menu references tiles that were not registered: {missing}")
        spec_missing = sorted(set(self._tiles.keys()) - set(self.TILE_SPECS.keys()))
        if spec_missing:
            raise RuntimeError(f"Registered tiles missing TILE_SPECS entries: {spec_missing}")

    @property
    def tiles(self) -> dict[str, HubTile]:
        return self._tiles

    def chrome_height(self) -> int:
        """Total height from window top through telemetry, including band gaps."""
        return (
            self._chrome.height()
            + CHROME_TELEMETRY_GAP_PX
            + self._telemetry_bar.height()
            + CHROME_TELEMETRY_GAP_PX
        )

    # --- Menu bar ---

    def _build_menus(self) -> None:
        menu = self._chrome.hub_menu()

        file_menu = menu.addMenu("File")
        file_menu.addAction("Open in Workspace…", self._file_open_workspace)
        file_menu.addSeparator()
        file_menu.addAction("Save Camera Snapshot…", self._file_save_camera_snapshot)
        file_menu.addAction("Save Workspace Image…", self._file_save_workspace_image)
        file_menu.addSeparator()
        file_menu.addAction("Load Scan CSV…", self._file_load_scan_csv)
        file_menu.addSeparator()
        file_menu.addAction("Open Data Folder", self._file_open_data_dir)
        file_menu.addAction("Open Outputs Folder", self._file_open_outputs_dir)

        view_menu = menu.addMenu("View")
        view_menu.aboutToShow.connect(self._sync_view_menu_checks)
        self._add_menu_tile_actions(
            view_menu,
            VIEW_MENU_TILES,
            action_store=self._view_tile_actions,
            toggle=True,
        )
        view_menu.addSeparator()
        scale_menu = view_menu.addMenu("Display scale")
        self._display_preset_group = QActionGroup(self)
        self._display_preset_group.setExclusive(True)
        from gui.ui_scale import display_presets

        for preset in display_presets():
            act = QAction(preset.label, scale_menu)
            act.setCheckable(True)
            act.setData(preset.id)
            act.triggered.connect(
                lambda _checked=False, pid=preset.id: self._set_display_preset(pid)
            )
            scale_menu.addAction(act)
            self._display_preset_group.addAction(act)
            self._display_preset_actions[preset.id] = act
        self._sync_display_preset_menu()

        tools_menu = menu.addMenu("Tools")
        tools_menu.addAction("Run Simulation", self._start_simulation)
        tools_menu.addAction("Stop Simulation", self._stop_simulation)
        tools_menu.addAction("Inject Synthetic Frame", self._inject_synthetic_frame)
        tools_menu.addSeparator()
        self._add_menu_tile_actions(tools_menu, TOOLS_MENU_TILES)

        layout_menu = menu.addMenu("Layout")
        layout_menu.addAction("Save Current Layout as Home", self._save_tile_layout)
        layout_menu.addAction("Reload Saved Layout", self._reload_tile_layout)
        layout_menu.addAction("Reset Tile Layout", self._reset_tile_layout)
        layout_menu.addAction("Apply Compact Laptop Layout", self._apply_compact_layout)
        layout_menu.addSeparator()
        layout_menu.addAction(
            "Layout tips (Shift = free drag, no grid snap)",
            self._show_layout_tips,
        )

    def _add_menu_tile_actions(
        self,
        menu,
        entries: tuple[tuple[str, str], ...],
        *,
        action_store: dict[str, object] | None = None,
        toggle: bool = False,
    ) -> None:
        from PySide6.QtGui import QAction

        for tile_id, label in entries:
            if tile_id not in self.TILE_SPECS or tile_id not in self._tiles:
                continue
            act = QAction(label, menu)
            if toggle:
                act.setCheckable(True)
                act.triggered.connect(
                    lambda _checked=False, tid=tile_id: self._toggle_tile_from_menu(tid)
                )
            else:
                act.triggered.connect(lambda _checked=False, tid=tile_id: self.show_tile(tid))
            menu.addAction(act)
            if action_store is not None:
                action_store[tile_id] = act

    def _is_tile_open(self, tile_id: str) -> bool:
        tile = self._tiles.get(tile_id)
        if tile is None:
            return False
        return tile.isVisible() and not tile._minimized

    def _sync_view_menu_checks(self) -> None:
        for tile_id, act in self._view_tile_actions.items():
            act.setChecked(self._is_tile_open(tile_id))

    def _sync_display_preset_menu(self) -> None:
        from gui.ui_scale import get_display_preset_id

        active = get_display_preset_id()
        for preset_id, act in self._display_preset_actions.items():
            act.setChecked(preset_id == active)

    def _set_display_preset(self, preset_id: str) -> None:
        from gui.ui_scale import get_display_preset_id, preset_by_id, set_display_preset_id

        if preset_by_id(preset_id) is None:
            return
        previous = get_display_preset_id()
        preset = preset_by_id(preset_id)
        set_display_preset_id(preset_id)
        self._cfg.ui_display_preset = preset_id
        save_config(self._cfg)
        self._sync_display_preset_menu()
        self._refresh_display_geometry()
        if preset is not None and preset.use_compact_layout and previous != preset_id:
            self._tile_layout.apply_compact_layout()
            self._sync_view_menu_checks()
        if preset is not None:
            self._update_telemetry(status=f"Display scale: {preset.label}")

    def _apply_compact_layout(self) -> None:
        self._tile_layout.apply_compact_layout()
        self._sync_view_menu_checks()
        self._update_telemetry(status="Compact laptop layout applied")

    def _toggle_tile_from_menu(self, tile_id: str) -> None:
        if self._is_tile_open(tile_id):
            self.hide_tile(tile_id)
        else:
            self.show_tile(tile_id)
        self._sync_view_menu_checks()

    # --- File menu actions ---

    def _file_open_workspace(self) -> None:
        start = DATA_DIR if DATA_DIR.is_dir() else Path.home()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open in Workspace",
            str(start),
            (
                "All supported (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.csv *.txt *.json);;"
                "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif);;"
                "Data (*.csv *.txt *.json);;"
                "All files (*.*)"
            ),
        )
        if not path:
            return
        err = self._workspace_panel.open_file(Path(path))
        if err:
            self._show_error(err)
            return
        self._view_center_workspace()
        self._update_telemetry(status=f"Workspace: {Path(path).name}")

    def _view_center_workspace(self) -> None:
        """Open or refocus Workspace dead-center (same tile chrome as other panels)."""
        tile = self._tiles.get("workspace")
        if tile is not None and tile._minimized:
            self.restore_tile_from_bar("workspace")
        self._tile_layout.show_tile_centered("workspace")
        self._update_telemetry(status="Workspace centered")

    def _file_save_camera_snapshot(self) -> None:
        frame = self._roi_snapshot_panel.analysis_frame()
        if frame is None:
            frame = self._camera_panel.current_frame()
        if frame is None:
            self._show_error("No camera frame available — start live feed or snap a frame.")
            return
        default = OUTPUT_DIR / "captures"
        default.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Camera Snapshot",
            str(default / "snapshot.png"),
            "PNG image (*.png);;JPEG image (*.jpg);;BMP image (*.bmp)",
        )
        if not path:
            return
        self._workspace_panel.open_numpy_image(frame, label="Camera snapshot")
        pix = self._workspace_panel.current_pixmap()
        if pix is None or pix.isNull():
            self._show_error("Could not prepare snapshot for save.")
            return
        if not pix.save(path):
            self._show_error(f"Failed to save image: {path}")
            return
        self._update_telemetry(status=f"Saved {Path(path).name}")

    def _file_save_workspace_image(self) -> None:
        if not self._workspace_panel.has_exportable_image():
            self._show_error("Workspace has no image to save — open an image or save a camera snapshot first.")
            return
        pix = self._workspace_panel.current_pixmap()
        if pix is None:
            return
        default = OUTPUT_DIR / "exports"
        default.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Workspace Image",
            str(default / "workspace_export.png"),
            "PNG image (*.png);;JPEG image (*.jpg);;BMP image (*.bmp)",
        )
        if not path:
            return
        if not pix.save(path):
            self._show_error(f"Failed to save image: {path}")
            return
        self._update_telemetry(status=f"Saved {Path(path).name}")

    def _file_open_data_dir(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR.resolve())))

    def _file_open_outputs_dir(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT_DIR.resolve())))

    def _file_load_scan_csv(self) -> None:
        start = DATA_DIR / "scans"
        if not start.is_dir():
            start = DATA_DIR
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Scan CSV",
            str(start),
            "CSV files (*.csv);;All files (*.*)",
        )
        if path:
            self._load_scan_csv(path)

    # --- Tile visibility and layout ---

    def minimize_tile(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        if tile is None or tile._minimized:
            return
        if not tile.isVisible():
            tile.show()
        if tile._workspace_maximized:
            if tile._pre_maximize_geometry is not None:
                tile.setGeometry(tile._pre_maximize_geometry)
            tile._workspace_maximized = False
            panel = tile.content_panel()
            if panel is not None and panel.header_widget() is not None:
                panel.header_widget().set_maximized_state(False)
        tile._saved_geometry = tile.geometry()
        tile._minimized = True
        tile.hide()
        title = self.TILE_SPECS[tile_id][0]
        self._min_tile_bar.add_tile(tile_id, title)
        self._position_min_tile_bar()
        self._sync_view_menu_checks()

    def restore_tile_from_bar(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        if tile is None:
            return
        tile._minimized = False
        self._min_tile_bar.remove_tile(tile_id)
        if tile._saved_geometry is not None:
            tile.setGeometry(tile._saved_geometry)
        tile.show()
        tile.raise_()
        self._position_min_tile_bar()
        self._sync_view_menu_checks()

    def _close_tile_from_bar(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        if tile is None:
            return
        tile._minimized = False
        self._min_tile_bar.remove_tile(tile_id)
        tile.close()

    def hide_tile(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        if tile is None:
            return
        if tile._minimized:
            self._close_tile_from_bar(tile_id)
            self._sync_view_menu_checks()
            return
        if tile.isVisible():
            tile.hide()
        self._sync_view_menu_checks()

    def show_tile(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        if tile is None:
            return
        if tile._minimized:
            self.restore_tile_from_bar(tile_id)
            self._sync_view_menu_checks()
            return
        if self._tile_layout.focus_tile is not None:
            self._tile_layout.exit_focus()
        tile.show()
        if tile_id == "workspace" and not self._tile_layout.has_custom_home("workspace"):
            self._tile_layout.show_tile_centered("workspace")
        else:
            self._tile_layout.place_at_home(tile_id, from_saved=True)
        tile.raise_()
        title = self.TILE_SPECS.get(tile_id, (tile_id, ""))[0]
        self._update_telemetry(status=f"Opened {title}")
        self._sync_view_menu_checks()

    def _on_tile_drag_released(self, tile_id: str) -> None:
        tile = self._tiles.get(tile_id)
        free = bool(tile and getattr(tile, "_free_drag_placement", False))
        if tile is not None:
            tile._free_drag_placement = False
        self._tile_layout.handle_drop(tile_id, free_placement=free)

    def _save_tile_layout(self) -> None:
        path = self._tile_layout.capture_current_as_homes(note="menu save")
        from core.tile_layout_store import layout_log_path

        log_path = layout_log_path()
        QMessageBox.information(
            self,
            APP_TITLE,
            (
                "Tile layout saved as your permanent home positions.\n\n"
                f"JSON: {path}\n"
                f"Log:  {log_path}\n\n"
                "Next launch loads these positions automatically."
            ),
        )
        self._update_telemetry(status="Layout saved")

    def _reload_tile_layout(self) -> None:
        from core.tile_layout_store import layout_json_path

        self._tile_layout.reload_saved_homes()
        self._position_min_tile_bar()
        path = layout_json_path()
        if path.is_file():
            QMessageBox.information(
                self,
                APP_TITLE,
                f"Tile layout reloaded from saved homes.\n\n{path}",
            )
            self._update_telemetry(status="Layout reloaded")
        else:
            QMessageBox.information(
                self,
                APP_TITLE,
                "No saved layout file yet — using built-in default homes.",
            )
            self._update_telemetry(status="Layout defaults applied")

    def _reset_tile_layout(self) -> None:
        self._tile_layout.restore_all_homes()
        self._apply_default_visibility()
        self._position_min_tile_bar()
        QMessageBox.information(
            self,
            APP_TITLE,
            (
                "Tile layout reset to built-in default positions.\n"
                "Optional tiles (Stage, Workspace, analysis tools) are hidden again."
            ),
        )
        self._update_telemetry(status="Layout reset")

    def snap_tile_to_grid(self, tile_id: str) -> None:
        if tile_id in NON_SNAPPING_TILES:
            return
        tile = self._tiles.get(tile_id)
        if tile is None or getattr(tile, "_workspace_maximized", False):
            return
        rect = self._tile_layout._snap_tile_rect(
            QRect(tile.pos(), tile.size()),
            tile_id,
        )
        tile.setGeometry(rect)

    def _show_layout_tips(self) -> None:
        from core.tile_layout_store import layout_json_path, layout_log_path
        from gui.workspace_grid import GRID_CELL_PX

        QMessageBox.information(
            self,
            APP_TITLE,
            (
                "Drag a tile by its title bar to move it.\n"
                f"Tiles snap to the {GRID_CELL_PX}px workspace grid.\n"
                "Hold Shift while dragging to disable grid snap.\n"
                "Resize from the outer edges of a tile.\n\n"
                "Layout → Save Current Layout as Home writes:\n"
                f"  {layout_json_path()}\n"
                f"  {layout_log_path()} (append log)\n\n"
                "Saved layout is restored on every launch."
            ),
        )

    def _on_tile_closed(self, tile_id: str) -> None:
        self._sync_view_menu_checks()

    def _on_tile_visibility_changed(self, tile_id: str, visible: bool) -> None:
        """React to a tile being shown/hidden so hidden tiles consume no resources."""
        if self._shutting_down:
            return
        if tile_id == "camera":
            self._on_camera_tile_visibility(visible)

    def _on_camera_tile_visibility(self, visible: bool) -> None:
        """Pause live acquisition while the camera tile is hidden; resume on show."""
        if visible:
            if self._camera_resume_on_show and not self._simulation_active:
                self._camera_resume_on_show = False
                self._start_camera()
                self._camera_panel.set_live_active(True)
            if self._camera_resume_on_show_b and not self._simulation_active:
                self._camera_resume_on_show_b = False
                self._start_camera_b()
            return
        if self._simulation_active:
            return
        if self._camera_live:
            self._camera_resume_on_show = True
            self._stop_camera()
            self._update_telemetry(status="Camera paused (tile hidden)")
        if self._camera_live_b:
            self._camera_resume_on_show_b = True
            self._stop_camera_b()

    # --- Signal wiring ---

    def _wire_signals(self) -> None:
        self._camera_panel._mode_combo.currentIndexChanged.connect(self._switch_roi_mode)
        self._camera_panel.snapshot_captured.connect(self._on_snapshot_captured)
        self._camera_panel.snap_requested.connect(self._grab_single_frame)
        self._camera_panel.live_feed_toggled.connect(self._on_live_feed_toggled)
        self._camera_panel.camera_settings_changed.connect(self._on_camera_settings_changed)
        self._camera_panel.layout_mode_changed.connect(self._on_camera_layout_changed)
        self._camera_panel.camera_label_changed.connect(self._on_camera_label_changed)
        self._roi_snapshot_panel.roi_changed.connect(self._on_roi_snapshot_changed)
        self._roi_snapshot_panel.capture_requested.connect(self._save_current_roi)
        self._roi_snapshot_panel.analyze_requested.connect(self._on_analyze_snapshot)
        self._beam_panel.analyze_requested.connect(self._analyze_beam_snapshot)
        self._roi_snapshot_panel.wavelength_scan_requested.connect(self._on_wavelength_scan)
        self._efficiency_panel.bind_calibrate(self._calibrate_efficiency)
        self._stage_panel.bind(
            on_jog=self._on_jog,
            on_save_limits=self._on_save_limits,
            on_safe_home=self._motion.go_safe_home,
            on_mark_home=self._motion.mark_safe_home,
            on_connect=self._connect_stage,
            on_add_stage=self._on_add_stage,
        )
        self._stage_panel.stage_changed.connect(self._on_stage_selected)
        self._motion.position_changed.connect(self._stage_panel.set_position_mm)
        self._motion.position_changed.connect(lambda p: self._update_telemetry(stage_mm=p))
        self._motion.status.connect(lambda s: self._update_telemetry(status=s))
        self._motion.error.connect(self._show_error)
        self._fft_panel.monitor_toggled.connect(self._on_fft_monitor_toggled)
        self._ai_panel.intent_action.connect(self._on_ai_intent)

    # --- Camera and frame pipeline ---

    def _on_live_feed_toggled(self, active: bool) -> None:
        if self._simulation_active:
            if not active:
                self._stop_simulation()
            return
        if active:
            self._start_camera()
        else:
            self._stop_camera()

    def _on_camera_settings_changed(self, settings: dict) -> None:
        cam_idx = int(settings.get("cam_idx", 0))
        worker_settings = {k: v for k, v in settings.items() if k != "cam_idx"}
        if cam_idx == 0:
            if self._camera_worker is not None and self._camera_worker.isRunning():
                self._camera_worker.queue_settings(worker_settings)
        else:
            if self._camera_worker_b is not None and self._camera_worker_b.isRunning():
                self._camera_worker_b.queue_settings(worker_settings)

    def _on_camera_settings_updated(self, settings: dict, cam_idx: int = 0) -> None:
        self._camera_panel.set_camera_settings(settings, cam_idx)
        exp_us = settings.get("exposure_us")
        if exp_us is not None:
            if cam_idx == 0:
                self._last_exp_a_us = float(exp_us)
                self._update_telemetry(camera_exposure_us=float(exp_us))
            else:
                self._last_exp_b_us = float(exp_us)
                self._update_telemetry(camera_b_exposure_us=float(exp_us))
        if cam_idx == 0:
            measured = settings.get("measured_fps")
            if measured is not None and measured > 0:
                self._update_telemetry(camera_measured_fps=float(measured))

    def _camera_exposure_label(self, cam_idx: int = 0) -> str:
        key = "camera_exposure_us" if cam_idx == 0 else "camera_b_exposure_us"
        exp_us = self._telemetry.get(key)
        if exp_us is None:
            return "—"
        if exp_us >= 1000:
            return f"{exp_us / 1000:.2f} ms"
        return f"{exp_us:.0f} µs"

    def _camera_a_status_label(self, status_override: str | None = None) -> str:
        slot = self._cfg.cameras[0] if self._cfg.cameras else None
        label = slot.label if slot else "Input"
        serial = slot.serial if (slot and slot.serial) else "No S/N"
        if status_override is not None:
            status = status_override
        elif self._simulation_active:
            status = "Simulated"
        elif self._camera_live:
            status = "Active"
        else:
            status = "Idle"
        exp = self._camera_exposure_label(0)
        parts = [f"{label}", f"S/N {serial}", status]
        if exp != "—":
            parts.append(exp)
        return "  ·  ".join(parts)

    def _camera_b_status_label(self) -> str:
        if len(self._cfg.cameras) < 2:
            return "—"
        slot = self._cfg.cameras[1]
        label = slot.label
        serial = slot.serial if slot.serial else "No S/N"
        status = "Active" if self._camera_live_b else "Idle"
        exp = self._camera_exposure_label(1)
        parts = [f"{label}", f"S/N {serial}", status]
        if exp != "—":
            parts.append(exp)
        return "  ·  ".join(parts)

    def _start_camera(self) -> None:
        if self._simulation_active:
            self._stop_simulation()
        if self._camera_worker is not None and self._camera_worker.isRunning():
            return
        serial_a = self._cfg.cameras[0].serial if self._cfg.cameras else None
        self._camera_worker = CameraWorker(serial_a, self)
        self._camera_worker.frame_ready.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)
        self._camera_worker.error.connect(self._on_camera_error)
        self._camera_worker.status.connect(self._on_camera_status)
        self._camera_worker.connected.connect(lambda _s: self._refresh_status(camera="Active"))
        self._camera_worker.settings_updated.connect(self._on_camera_settings_updated)
        self._defer_screen_refit_until = time.time() + 5.0
        self._camera_worker.start()
        self._camera_live = True
        if serial_a:
            self._camera_panel.set_camera_serial(0, serial_a)

    def _start_camera_b(self) -> None:
        if self._simulation_active or not self._camera_live:
            return
        if self._camera_worker_b is not None and self._camera_worker_b.isRunning():
            return
        serial_b = self._cfg.cameras[1].serial if len(self._cfg.cameras) > 1 else None
        self._camera_worker_b = CameraWorker(serial_b, self)
        self._camera_worker_b.frame_ready.connect(
            self._on_frame_b, Qt.ConnectionType.QueuedConnection
        )
        self._camera_worker_b.error.connect(lambda e: self._show_error(f"Camera B: {e}"))
        self._camera_worker_b.status.connect(lambda _s: None)
        # Auto-switch to Side-by-Side when Camera B first connects
        self._camera_worker_b.connected.connect(self._on_camera_b_connected)
        self._camera_worker_b.settings_updated.connect(
            lambda s: self._on_camera_settings_updated(s, cam_idx=1)
        )
        self._camera_worker_b.start()
        self._camera_live_b = True
        if serial_b:
            self._camera_panel.set_camera_serial(1, serial_b)
        self._refresh_status()

    def _stop_camera_b(self) -> None:
        if self._camera_worker_b is None:
            return
        self._camera_worker_b.stop()
        self._camera_worker_b.wait(3000)
        self._camera_worker_b = None
        self._camera_live_b = False
        self._last_frame_b = None
        self._live_display_last_t_b = 0.0
        self._refresh_status()

    def _on_camera_b_connected(self, _serial: str) -> None:
        """Auto-switch the camera tile to Side-by-Side once Camera B is live."""
        from gui.widgets.camera_view import LayoutMode
        if self._camera_panel.current_layout() == LayoutMode.INPUT_ONLY:
            self._camera_panel.set_layout_mode(LayoutMode.SIDE_BY_SIDE)
        self._refresh_status()

    def _stop_camera(self) -> None:
        if self._camera_worker is None:
            return
        self._camera_worker.stop()
        self._camera_worker.wait(3000)
        self._camera_worker = None
        if self._simulation_active:
            return
        self._camera_live = False
        self._live_display_last_t = 0.0
        self._live_display_last_t_b = 0.0
        self._last_frame_processed_t = 0.0
        self._live_analytics_last_t = 0.0
        self._last_live_overlay = None
        self._camera_panel.show_idle()
        self._camera_panel.set_coupling_overlay(None)
        self._beam_panel.reset()
        self._efficiency_panel.reset()
        self._trend_panel.reset()
        self._fft_panel.reset()
        self._refresh_status(camera="Idle")
        self._update_telemetry(beam_waist_um=None, efficiency_pct=None, status="Camera off")

    def _on_camera_error(self, message: str) -> None:
        self._stop_camera()
        self._camera_panel.set_live_active(False)
        self._show_error(message)

    def _on_camera_status(self, status: str) -> None:
        self._update_telemetry(status=status)
        if "active" in status.lower():
            self._refresh_status(camera="Active")

    def _on_frame(self, frame: np.ndarray) -> None:
        # Always keep the latest frame for on-demand analysis/efficiency.
        self._last_frame_a = frame
        # Cap main-thread processing at 20 FPS regardless of camera hardware rate.
        # The worker emits at full sensor FPS (30-100 Hz); without this guard, every
        # queued event runs _process_frame in the main thread, saturating the UI loop.
        now = time.time()
        if now - self._last_frame_processed_t < 0.05:
            return
        self._last_frame_processed_t = now
        self._process_frame(frame)

    def _on_frame_b(self, frame: np.ndarray) -> None:
        self._last_frame_b = frame
        now = time.time()
        # Use a dedicated timestamp so Camera B's display is independent of Camera A's.
        if now - self._live_display_last_t_b >= 0.1:
            self._live_display_last_t_b = now
            self._camera_panel.update_frame_b(frame, repaint=True)
        else:
            self._camera_panel.store_frame_b(frame)
        self._compute_live_efficiency()

    def _compute_live_efficiency(self) -> None:
        """Dual-camera live η: (mean_out/exp_out) / (mean_in/exp_in) vs reference."""
        if not self._is_tile_open("efficiency"):
            return
        if self._last_frame_a is None or self._last_frame_b is None:
            return
        roi_a = self._cfg.beam_roi
        roi_b = self._cfg.cameras[1].beam_roi if len(self._cfg.cameras) > 1 else self._cfg.beam_roi
        mean_in = roi_mean(self._last_frame_a, roi_a)
        mean_out = roi_mean(self._last_frame_b, roi_b)
        exp_a = max(self._last_exp_a_us, 1.0)
        exp_b = max(self._last_exp_b_us, 1.0)
        eta_pct = dual_camera_efficiency_percent(
            mean_in, mean_out, exp_a, exp_b, self._cfg.efficiency_reference_ratio
        )
        ref_set = self._cfg.efficiency_reference_ratio is not None
        detail = (
            f"In: {mean_in:.0f} cts × {exp_a:.0f} µs  |  "
            f"Out: {mean_out:.0f} cts × {exp_b:.0f} µs"
            + ("" if ref_set else "  ·  Set η=100% to calibrate")
        )
        self._efficiency_panel.set_efficiency(eta_pct, detail=detail)
        if eta_pct is not None:
            self._update_telemetry(efficiency_pct=eta_pct)

    def _on_camera_layout_changed(self, mode_str: str) -> None:
        from gui.widgets.camera_view import LayoutMode
        mode = LayoutMode(mode_str)
        if mode == LayoutMode.SIDE_BY_SIDE:
            if not self._camera_live_b and self._camera_live:
                self._start_camera_b()
        elif mode == LayoutMode.INPUT_ONLY:
            if self._camera_live_b:
                self._stop_camera_b()
        elif mode == LayoutMode.OUTPUT_ONLY:
            if self._camera_live_b:
                pass  # keep B running
            elif self._camera_live:
                self._start_camera_b()

    def _on_camera_label_changed(self, cam_idx: int, label: str) -> None:
        if cam_idx < len(self._cfg.cameras):
            self._cfg.cameras[cam_idx].label = label
            save_config(self._cfg)

    def _process_frame(self, frame: np.ndarray) -> None:
        now = time.time()
        roi = self._camera_panel.current_roi()
        overlay: dict | None = None

        if self._simulation_active:
            self._simulation_last_frame = np.asarray(frame).copy()
            if now - self._sim_display_last_t >= 0.1:
                self._sim_display_last_t = now
                target = default_target_center(frame, roi)
                overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
                self._camera_panel.set_coupling_overlay(overlay)
                self._camera_panel.update_frame(frame, repaint=True)
                self._last_sim_overlay = overlay
            else:
                self._camera_panel.store_frame(frame)
                overlay = self._last_sim_overlay
        elif self._camera_live:
            if now - self._live_display_last_t >= 0.1:
                self._live_display_last_t = now
                target = default_target_center(frame, roi)
                overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
                self._camera_panel.set_coupling_overlay(overlay)
                self._camera_panel.update_frame(frame)
                self._last_live_overlay = overlay
            else:
                self._camera_panel.store_frame(frame)
                overlay = self._last_live_overlay

        if overlay is None:
            target = default_target_center(frame, roi)
            overlay = coupling_overlay(frame, target_center_px=target, roi_xywh=roi)
            if self._camera_live:
                self._last_live_overlay = overlay
            elif self._simulation_active:
                self._last_sim_overlay = overlay

        if not self._camera_live or now - self._live_analytics_last_t >= 0.25:
            fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
            if fringe_mean == fringe_mean:
                self._update_fft_monitor(float(fringe_mean))

        # While a frozen snapshot is active, live analytics pause but coupling overlay still updates.
        if self._roi_snapshot_panel.has_snapshot():
            if overlay is not None:
                self._refresh_status(
                    camera=self._camera_status_label(),
                    coupling_err=f"{overlay['error_um']:.1f} µm",
                    coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
                )
            return

        if self._simulation_active:
            if now - self._sim_analytics_last_t >= 0.25:
                self._sim_analytics_last_t = now
                self._process_simulation_analytics(frame)
            if overlay is not None:
                self._refresh_status(
                    camera=self._camera_status_label(),
                    coupling_err=f"{overlay['error_um']:.1f} µm",
                    coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
                )
            return

        # Beam fitting (analyze_frame + analyze_beam_quality) is expensive and only
        # needs to run on explicit user request — click "Analyze Beam" in the beam tile.
        # Fringe-mode single-camera efficiency is lightweight (one roi_mean) so keep it live.
        if self._camera_live and now - self._live_analytics_last_t < 0.25:
            return
        if self._camera_live:
            self._live_analytics_last_t = now

        mode = self._camera_panel.current_mode()
        if mode != RoiMode.BEAM:
            eta_pct = None
            mean = roi_mean(frame, roi)
            if self._cfg.efficiency_reference_mean:
                eta_pct = coupling_efficiency_percent(mean, self._cfg.efficiency_reference_mean)
            if self._is_tile_open("efficiency"):
                self._efficiency_panel.set_efficiency(
                    eta_pct,
                    detail="Fiber exit η · P(out)/P(in) vs calibrated baseline",
                )
            if self._is_tile_open("trends"):
                self._trend_panel.append_sample(eta_pct=eta_pct)
            self._update_telemetry(efficiency_pct=eta_pct, status="Fringe ROI")

        if overlay is not None:
            self._refresh_status(
                camera=self._camera_status_label(),
                coupling_err=f"{overlay['error_um']:.1f} µm",
                coupling_ang=f"{overlay['error_angle_deg']:.0f}°",
            )

    def _camera_status_label(self) -> str:
        if self._simulation_active:
            return "Simulated"
        if self._camera_live:
            return "Active"
        return "Idle"

    def _process_simulation_analytics(self, frame: np.ndarray) -> None:
        """Update beam, efficiency, and both trend series during simulation."""
        beam_roi = self._cfg.beam_roi
        crop = crop_box_from_xywh(beam_roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        if self._is_tile_open("beam"):
            quality = analyze_beam_quality(
                result["x_profile"],
                result["y_profile"],
                measured_w0_um=w0,
            )
            result["beam_quality"] = quality
            result["m2"] = quality["m2"]
            self._beam_panel.update_analysis(result, live=True)

        fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
        eta_pct = None
        if self._cfg.efficiency_reference_mean and fringe_mean == fringe_mean:
            eta_pct = coupling_efficiency_percent(
                fringe_mean,
                self._cfg.efficiency_reference_mean,
            )

        if self._is_tile_open("efficiency"):
            self._efficiency_panel.set_efficiency(
                eta_pct,
                detail="Simulated fiber exit η · P(out)/P(in) vs calibrated baseline",
            )
        if self._is_tile_open("trends"):
            self._trend_panel.append_sample(eta_pct=eta_pct, w0_um=w0)
        self._update_telemetry(
            beam_waist_um=w0,
            efficiency_pct=eta_pct,
            status="Simulation",
            laser="Simulated",
        )

    def _start_simulation(
        self,
        duration_sec: float | None = None,
        *,
        report_to_atria: bool = False,
    ) -> None:
        if self._simulation_active:
            return
        self._stop_camera()
        self._camera_panel.set_live_active(False)

        self._cfg = load_config()
        self._simulation_generator.refresh_config(self._cfg)
        cal_t = self._simulation_generator.calibration_time_for_peak_fringe()
        cal_frame = self._simulation_generator.frame(cal_t)
        fringe_mean = roi_mean(cal_frame, self._cfg.fringe_roi)
        if fringe_mean == fringe_mean and fringe_mean > 0:
            self._cfg.efficiency_reference_mean = fringe_mean
            save_config(self._cfg)

        self._trend_panel.reset()
        self._fft_times.clear()
        self._fft_samples.clear()
        self._simulation_planned_sec = duration_sec
        self._simulation_report_to_atria = report_to_atria
        self._simulation_last_frame = None
        self._simulation_fft_peak_hz = None
        self._simulation_fft_rate_hz = None
        self._simulation_timer.stop()

        self._simulation_worker = SimulationWorker(self._simulation_generator, self)
        self._simulation_worker.frame_ready.connect(self._on_frame)
        self._simulation_worker.error.connect(self._on_simulation_error)
        self._simulation_worker.status.connect(self._on_simulation_status)
        self._simulation_worker.connected.connect(self._on_simulation_connected)
        self._simulation_worker.start()

        self._simulation_active = True
        self._camera_live = True
        self._camera_panel.set_live_active(True, simulation=True)

        if not self._fft_panel.is_monitoring():
            self._fft_panel.set_monitoring(True)

        for tile_id in ("camera", "beam", "efficiency", "trends", "fft", "roi_snapshot"):
            self.show_tile(tile_id)

        if duration_sec is not None and duration_sec > 0:
            self._simulation_timer.start(int(duration_sec * 1000))

        if report_to_atria and duration_sec is not None:
            self._log_action(f"Atria: run simulation ({duration_sec:.0f} s)")
        else:
            self._log_action("Bench simulation started")
        self._refresh_status(camera="Simulated", laser="Simulated")
        self._update_telemetry(status="Simulation active", laser="Simulated")

    def _on_simulation_duration_elapsed(self) -> None:
        if self._simulation_active:
            self._stop_simulation()

    def _stop_simulation(self) -> None:
        if not self._simulation_active:
            return
        self._simulation_timer.stop()
        self._simulation_active = False
        worker = self._simulation_worker
        self._simulation_worker = None
        if worker is not None:
            worker.stop()
            if worker.isRunning():
                worker.finished.connect(
                    self._on_simulation_worker_finished,
                    Qt.ConnectionType.SingleShotConnection,
                )
            else:
                QTimer.singleShot(0, self._on_simulation_worker_finished)
        else:
            QTimer.singleShot(0, self._on_simulation_worker_finished)

    def _on_simulation_worker_finished(self) -> None:
        """Light cleanup on the UI thread; defer heavy plot rebuild."""
        self._camera_live = False
        self._camera_panel.set_live_active(False)
        self._camera_panel.show_idle()
        self._camera_panel.set_coupling_overlay(None)
        self._fft_panel.set_monitoring(False, emit=False)
        self._log_action("Bench simulation stopped")
        self._refresh_status(camera="Idle", laser="Manual")
        self._update_telemetry(status="Simulation stopped", laser="Manual")
        QTimer.singleShot(0, self._complete_simulation_finalize)

    def _complete_simulation_finalize(self) -> None:
        """Finalize plots and Atria report without blocking worker teardown."""
        planned_sec = self._simulation_planned_sec
        report_to_atria = self._simulation_report_to_atria
        last_frame = self._simulation_last_frame
        overlay = self._last_sim_overlay
        fft_peak = self._simulation_fft_peak_hz
        fft_rate = self._simulation_fft_rate_hz

        self._simulation_planned_sec = None
        self._simulation_report_to_atria = False
        self._simulation_last_frame = None
        self._simulation_fft_peak_hz = None
        self._simulation_fft_rate_hz = None
        self._last_sim_overlay = None

        beam_result = None
        if last_frame is not None:
            beam_result = self._finalize_simulation_plots(last_frame)

        if report_to_atria:
            self._post_simulation_atria_report(
                planned_sec=planned_sec,
                beam_result=beam_result,
                coupling_overlay=overlay,
                fft_peak_hz=fft_peak,
                fft_rate_hz=fft_rate,
            )

    def _finalize_simulation_plots(self, frame: np.ndarray) -> dict:
        """Run full (non-live) analysis so 3D surface and profiles reflect the final frame."""
        roi = self._cfg.beam_roi
        self._roi_snapshot_panel.set_snapshot(frame, roi, RoiMode.BEAM)
        crop = crop_box_from_xywh(roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        quality = analyze_beam_quality(
            result["x_profile"],
            result["y_profile"],
            measured_w0_um=w0,
        )
        result["beam_quality"] = quality
        result["m2"] = quality["m2"]
        self._beam_panel.update_analysis(result, live=False)
        fringe_mean = roi_mean(frame, self._cfg.fringe_roi)
        eta_pct = None
        if self._cfg.efficiency_reference_mean and fringe_mean == fringe_mean:
            eta_pct = coupling_efficiency_percent(
                fringe_mean,
                self._cfg.efficiency_reference_mean,
            )
        self._efficiency_panel.set_efficiency(
            eta_pct,
            detail="Simulated fiber exit η · final frame",
        )
        self._update_telemetry(
            beam_waist_um=w0 if w0 == w0 else None,
            efficiency_pct=eta_pct,
            status="Simulation complete",
            laser="Simulated",
        )
        return result

    def _post_simulation_atria_report(
        self,
        *,
        planned_sec: float | None,
        beam_result: dict | None,
        coupling_overlay: dict | None,
        fft_peak_hz: float | None,
        fft_rate_hz: float | None,
    ) -> None:
        report = format_simulation_report(
            planned_sec=planned_sec,
            trend_summary=self._trend_panel.summary(),
            beam_result=beam_result,
            coupling_overlay=coupling_overlay,
            fft_peak_hz=fft_peak_hz,
            fft_rate_hz=fft_rate_hz,
        )
        self.show_tile("atria")
        self._ai_panel.post_bench_message(report)

    def _on_simulation_error(self, message: str) -> None:
        self._stop_simulation()
        self._show_error(message)

    def _on_simulation_status(self, status: str) -> None:
        self._update_telemetry(status=status)

    def _on_simulation_connected(self, _label: str) -> None:
        self._refresh_status(camera="Simulated")

    # --- ROI and snapshot ---

    def _switch_roi_mode(self) -> None:
        self._cfg = load_config()
        mode = self._camera_panel.current_mode()
        roi = self._cfg.beam_roi if mode == RoiMode.BEAM else self._cfg.fringe_roi
        self._camera_panel.set_roi(roi, mode)
        self._roi_snapshot_panel.set_mode(mode)
        if self._roi_snapshot_panel.has_snapshot():
            self._roi_snapshot_panel.set_roi(roi, mode)

    def _on_snapshot_captured(self, frame: np.ndarray) -> None:
        roi = self._camera_panel.current_roi()
        mode = self._camera_panel.current_mode()
        self._roi_snapshot_panel.set_snapshot(frame, roi, mode)
        tile = self._tiles.get("roi_snapshot")
        if tile is not None and not tile.isVisible():
            self.show_tile("roi_snapshot")
        self._log_action("Frame snapped to ROI Snap Shot")
        self._update_telemetry(status="Frame snapped to ROI Snap Shot")

    def _on_roi_snapshot_changed(self, roi: tuple[int, int, int, int]) -> None:
        mode = self._roi_snapshot_panel.current_mode()
        self._camera_panel.set_roi(roi, mode)
        self._on_roi_changed(roi, mode)

    def _on_roi_changed(
        self,
        roi: tuple[int, int, int, int],
        mode: RoiMode | None = None,
    ) -> None:
        self._cfg = load_config()
        mode = mode or self._roi_snapshot_panel.current_mode()
        if mode == RoiMode.BEAM:
            self._cfg.beam_roi = roi
        else:
            self._cfg.fringe_roi = roi
        save_config(self._cfg)

    def _save_current_roi(self) -> None:
        self._on_roi_changed(self._roi_snapshot_panel.current_roi())
        self._log_action("ROI saved to config")
        self._update_telemetry(status="ROI saved")

    def _analyze_beam(self) -> None:
        self._on_analyze_snapshot()

    def _on_analyze_snapshot(self) -> None:
        frame = self._roi_snapshot_panel.analysis_frame()
        if frame is None:
            self._show_error("Snap a frame from Live Camera first.")
            return
        roi = self._roi_snapshot_panel.current_roi()
        crop = crop_box_from_xywh(roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        quality = analyze_beam_quality(
            result["x_profile"],
            result["y_profile"],
            measured_w0_um=w0,
        )
        result["beam_quality"] = quality
        result["m2"] = quality["m2"]
        self._beam_panel.update_analysis(result)
        self._trend_panel.append_sample(w0_um=w0)
        self._log_action(f"Beam analyzed — w₀ ≈ {w0:.1f} µm")
        self._update_telemetry(beam_waist_um=w0, status="Beam analyzed")

    def _analyze_beam_snapshot(self) -> None:
        """Run a one-shot beam analysis on the latest live frame (on-demand, not live)."""
        frame = self._last_frame_a
        if frame is None and self._simulation_active:
            frame = getattr(self, "_simulation_last_frame", None)
        if frame is None:
            self._show_error("No live frame available — start the camera feed first.")
            return
        roi = self._camera_panel.current_roi()
        crop = crop_box_from_xywh(roi)
        result = analyze_frame(frame, crop_box=crop)
        w0 = result.get("one_over_e2_avg_um", float("nan"))
        quality = analyze_beam_quality(
            result["x_profile"],
            result["y_profile"],
            measured_w0_um=w0,
        )
        result["beam_quality"] = quality
        result["m2"] = quality["m2"]
        self._beam_panel.update_analysis(result)
        if self._is_tile_open("trends"):
            self._trend_panel.append_sample(w0_um=w0)
        self._log_action(f"Beam analyzed (live) — w₀ ≈ {w0:.1f} µm")
        self._update_telemetry(beam_waist_um=w0, status="Beam analyzed")

    # --- Wavelength scan ---

    def _on_wavelength_scan(self, *, skip_confirm: bool = False) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._show_error("A wavelength scan is already running.")
            return

        mode = self._roi_snapshot_panel.current_mode()
        if mode == RoiMode.FRINGE:
            roi = self._roi_snapshot_panel.current_roi()
            self._cfg.fringe_roi = roi
            save_config(self._cfg)
        else:
            roi = self._cfg.fringe_roi
            QMessageBox.information(
                self,
                APP_TITLE,
                "λ scan uses the saved fringe ROI. Switch to “Fringe ROI (λ scan)” "
                "and adjust the snapshot ROI if you need a different box.",
            )

        if not skip_confirm:
            reply = QMessageBox.question(
                self,
                APP_TITLE,
                (
                    f"Run K-Cube stage scan ({roi[2]}×{roi[3]} fringe ROI)?\n\n"
                    "Stage will move ~0–1.5 mm while the camera records fringe intensity.\n"
                    "Live feed pauses during the scan."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._log_action("Starting K-Cube wavelength scan")
        self._resume_live_after_scan = self._camera_live
        self._stop_camera()
        self._camera_panel.set_live_active(False)
        self._update_telemetry(status="λ scan — connecting hardware…")

        self._scan_worker = WavelengthScanWorker(
            roi_xywh=roi,
            stage_serial=self._active_stage_serial(),
            camera_serial=self._cfg.camera_serial,
            parent=self,
        )
        self._scan_worker.status.connect(
            lambda s: self._update_telemetry(status=s[:80])
        )
        self._scan_worker.finished_ok.connect(self._on_wavelength_scan_done)
        self._scan_worker.error.connect(self._show_error)
        self._scan_worker.finished.connect(self._after_wavelength_scan)
        self._scan_worker.start()

    def _apply_scan_result(self, result: dict, *, show_dialog: bool = True) -> None:
        lam = float(result["lambda_nm"])
        csv_path = result.get("csv_path")
        self._cfg = load_config()
        self._cfg.last_wavelength_nm = lam
        if csv_path:
            self._cfg.last_scan_csv = str(csv_path)
        self._cfg.wavelength_mode = "last_scan"
        save_config(self._cfg)
        self._apply_wavelength_config()
        self._update_telemetry(status=f"λ = {lam:.2f} nm")
        self._log_action(f"Wavelength recovered: {lam:.2f} nm")
        if csv_path:
            err = self._workspace_panel.open_file(Path(csv_path))
            if not err:
                self.show_tile("workspace")
        if show_dialog:
            warn = result.get("warning")
            if warn:
                QMessageBox.information(self, APP_TITLE, f"λ = {lam:.2f} nm\n\nNote: {warn}")
            else:
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    f"Wavelength recovered: {lam:.2f} nm\n\nCSV: {csv_path or ''}",
                )

    def _on_wavelength_scan_done(self, result: dict) -> None:
        self._apply_scan_result(result, show_dialog=True)

    def _after_wavelength_scan(self) -> None:
        self._scan_worker = None
        if self._resume_live_after_scan:
            self._resume_live_after_scan = False
            self._camera_panel.set_live_active(True)
            self._start_camera()

    # --- Stage motion ---

    def _active_stage_serial(self) -> str | None:
        self._cfg = load_config()
        idx = self._motion.active_index
        if 0 <= idx < len(self._cfg.stages):
            return self._cfg.stages[idx].serial
        return None

    def _connect_stage(self) -> bool:
        limits = self._stage_panel.build_limits()
        self._motion.update_limits(limits)
        self._motion.reload_config()
        ok = self._motion.connect_stage()
        if ok:
            name = self._motion.limits.name
            self._log_action(f"K-Cube connected ({name})")
        return ok

    def _on_stage_selected(self, index: int) -> None:
        self._motion.set_active_index(index)
        self._cfg = load_config()
        self._stage_panel.load_limits(self._motion.limits)
        self._stage_panel.set_stages(self._cfg.stages, active_index=index)
        self._log_action(f"Selected stage: {self._motion.limits.name}")

    def _on_add_stage(self) -> None:
        self._cfg = load_config()
        n = len(self._cfg.stages) + 1
        self._cfg.stages.append(StageLimits(name=f"Stage {n}"))
        save_config(self._cfg)
        new_index = len(self._cfg.stages) - 1
        self._motion.set_active_index(new_index)
        self._stage_panel.set_stages(self._cfg.stages, active_index=new_index)
        self._log_action(f"Added stage slot: Stage {n}")

    def _on_save_limits(self, limits) -> None:
        self._motion.update_limits(limits)
        self._motion.reload_config()
        self._cfg = load_config()
        idx = self._motion.active_index
        self._stage_panel.set_stages(self._cfg.stages, active_index=idx)
        self._log_action(f"Limits saved for {limits.name}")

    def _on_jog(self, delta_mm: float) -> None:
        if not self._motion.connected:
            self._motion.connect_stage()
        self._motion.jog_mm(delta_mm)
        self._log_action(f"Stage jog {delta_mm:+.4f} mm")

    def _log_action(self, message: str) -> None:
        self._tasks_panel.log_event(message)

    def _toggle_live_feed(self, active: bool) -> None:
        if self._simulation_active:
            if not active:
                self._stop_simulation()
            return
        self._camera_panel.set_live_active(active)
        if active:
            self._start_camera()
            self._log_action("Live camera feed started")
        else:
            self._stop_camera()
            self._log_action("Live camera feed stopped")

    def _grab_single_frame(self) -> None:
        if self._simulation_active and self._simulation_last_frame is not None:
            self._on_snapshot_captured(np.asarray(self._simulation_last_frame).copy())
            return
        if self._camera_panel.current_frame() is not None:
            self._camera_panel._snap_frame()
            return
        if self._snap_worker is not None and self._snap_worker.isRunning():
            return
        self._update_telemetry(status="Capturing single frame…")
        self._snap_worker = SnapWorker(self._cfg.camera_serial, self)
        self._snap_worker.frame_ready.connect(self._on_single_snap_ready)
        self._snap_worker.error.connect(self._show_error)
        self._snap_worker.status.connect(lambda s: self._update_telemetry(status=s[:80]))
        self._snap_worker.finished.connect(self._clear_snap_worker)
        self._snap_worker.start()

    def _clear_snap_worker(self) -> None:
        self._snap_worker = None

    def _on_single_snap_ready(self, frame: np.ndarray) -> None:
        self._log_action("Single frame captured from Thorcam")
        self._on_snapshot_captured(frame)

    def _load_scan_csv(self, path: str) -> None:
        csv_path = Path(path)
        result = recover_wavelength_from_csv(csv_path)
        if result.get("error"):
            self._show_error(str(result["error"]))
            return
        result["csv_path"] = str(csv_path)
        self._apply_scan_result(result, show_dialog=True)

    # --- FFT monitor ---

    def _on_fft_monitor_toggled(self, active: bool) -> None:
        if active:
            self._fft_times.clear()
            self._fft_samples.clear()
            self._fft_last_sample_t = None
            if not self._camera_live:
                self._toggle_live_feed(True)
            self._log_action("FFT vibration monitor started")
            self.show_tile("fft")
        else:
            self._log_action("FFT vibration monitor stopped")

    def _update_fft_monitor(self, intensity: float) -> None:
        if not self._fft_panel.is_monitoring():
            return
        # No point sampling / running the FFT when its tile is not on screen.
        if not self._is_tile_open("fft"):
            return
        if intensity != intensity:
            return
        now = time.time()
        self._fft_times.append(now)
        self._fft_samples.append(float(intensity))
        max_n = 2048
        if len(self._fft_samples) > max_n:
            self._fft_times = self._fft_times[-max_n:]
            self._fft_samples = self._fft_samples[-max_n:]
        if len(self._fft_samples) < 64:
            return
        now = time.time()
        if now - self._fft_plot_last_t < 0.25:
            return
        self._fft_plot_last_t = now
        times = np.array(self._fft_times)
        vals = np.array(self._fft_samples)
        dt = np.diff(times)
        if dt.size == 0:
            return
        rate = 1.0 / float(np.median(dt))
        if rate <= 0:
            return
        detrended = vals - np.mean(vals)
        spectrum = np.abs(np.fft.rfft(detrended)) ** 2
        freqs = np.fft.rfftfreq(len(detrended), d=1.0 / rate)
        mask = freqs > 0.5
        if not np.any(mask):
            return
        spec_masked = spectrum[mask]
        freqs_masked = freqs[mask]
        peak_hz = float(freqs_masked[int(np.argmax(spec_masked))])
        if self._simulation_active:
            self._simulation_fft_peak_hz = peak_hz
            self._simulation_fft_rate_hz = rate
        self._fft_panel.update_spectrum(
            freqs_masked,
            spec_masked,
            peak_hz=peak_hz,
            sample_rate_hz=rate,
        )

    def _inject_synthetic_frame(self) -> None:
        self._cfg = load_config()
        self._simulation_generator.refresh_config(self._cfg)
        frame = make_simulation_frame(time.time(), self._cfg)
        self._log_action("Synthetic frame injected")
        self._process_frame(frame)

    # --- Efficiency calibration ---

    def _calibrate_efficiency(self) -> None:
        """Set current frame ratio as the η=100% reference.

        Dual-camera mode: stores the exposure-normalised output/input ratio.
        Single-camera fallback: stores the absolute fringe ROI mean as before.
        """
        self._cfg = load_config()
        if self._last_frame_a is not None and self._last_frame_b is not None:
            roi_a = self._cfg.beam_roi
            roi_b = self._cfg.cameras[1].beam_roi if len(self._cfg.cameras) > 1 else roi_a
            mean_in = roi_mean(self._last_frame_a, roi_a)
            mean_out = roi_mean(self._last_frame_b, roi_b)
            exp_a = max(self._last_exp_a_us, 1.0)
            exp_b = max(self._last_exp_b_us, 1.0)
            if mean_in <= 0:
                self._show_error("Input camera ROI mean is zero — is Camera A running?")
                return
            ratio = (mean_out / exp_b) / (mean_in / exp_a)
            self._cfg.efficiency_reference_ratio = ratio
            save_config(self._cfg)
            self._log_action(f"η=100% calibrated (ratio={ratio:.4f})")
            self._update_telemetry(status="η baseline set (dual-cam)")
        else:
            frame = self._roi_snapshot_panel.analysis_frame() or self._camera_panel.current_frame()
            if frame is None:
                self._show_error("Start live feed or snap a frame first.")
                return
            mean = roi_mean(frame, self._cfg.fringe_roi)
            if mean != mean or mean <= 0:
                self._show_error("Fringe ROI mean invalid — check ROI.")
                return
            self._cfg.efficiency_reference_mean = mean
            save_config(self._cfg)
            self._log_action(f"η baseline calibrated ({mean:.0f} counts)")
            self._update_telemetry(status=f"η baseline = {mean:.0f}")

    def _apply_wavelength_config(self) -> None:
        """Sync telemetry λ from config (nominal vs measured/manual active value)."""
        lam = resolve_wavelength_nm(self._cfg)
        self._telemetry["wavelength_nm"] = lam
        self._telemetry["wavelength_mode"] = self._cfg.wavelength_mode
        self._telemetry["nominal_wavelength_nm"] = self._cfg.nominal_wavelength_nm
        self._telemetry["measured_wavelength_nm"] = self._cfg.last_wavelength_nm

    # --- Atria intents ---

    def _on_ai_intent(self, intent: Intent, hardware_allowed: bool) -> None:
        name = intent.name
        if name == "set_wavelength_nominal":
            self._cfg = load_config()
            nm = intent.params.get("nm")
            if nm is not None:
                self._cfg.nominal_wavelength_nm = float(nm)
            self._cfg.wavelength_mode = "nominal"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action("Atria: active λ set to nominal diode label")
            self._update_telemetry(
                status=f"λ diode label {self._telemetry['wavelength_nm']:.2f} nm",
            )
        elif name == "set_wavelength_measured":
            self._cfg = load_config()
            if self._cfg.last_wavelength_nm is None:
                self._show_error(
                    "No measured wavelength yet — run Scan wavelength or load a scan CSV."
                )
                return
            self._cfg.wavelength_mode = "last_scan"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action("Atria: active λ set to last scan")
            self._update_telemetry(
                status=f"λ measured {self._telemetry['wavelength_nm']:.2f} nm",
            )
        elif name == "set_wavelength":
            nm = float(intent.params["nm"])
            self._cfg = load_config()
            self._cfg.last_wavelength_nm = nm
            self._cfg.wavelength_mode = "manual"
            save_config(self._cfg)
            self._apply_wavelength_config()
            self._log_action(f"Atria: λ set to {nm:.2f} nm (manual)")
            self._update_telemetry(status=f"λ set to {nm:.2f} nm")
        elif name == "capture_roi":
            self._save_current_roi()
        elif name == "toggle_live_feed":
            self._toggle_live_feed(bool(intent.params.get("active", True)))
        elif name == "snap_frame":
            if self._camera_live:
                frame = self._camera_panel.current_frame()
                if frame is not None:
                    self._on_snapshot_captured(frame)
            else:
                self._grab_single_frame()
        elif name == "analyze_beam":
            self._analyze_beam()
        elif name == "run_wavelength_scan" and hardware_allowed:
            self._on_wavelength_scan(skip_confirm=True)
        elif name == "run_wavelength_scan" and not hardware_allowed:
            self._show_error("Enable hardware control to run a wavelength scan.")
        elif name == "calibrate_efficiency":
            self._calibrate_efficiency()
        elif name == "load_scan_csv":
            path = intent.params.get("path")
            if path:
                self._load_scan_csv(path)
            else:
                self._file_load_scan_csv()
        elif name == "connect_stage" and hardware_allowed:
            ok = self._motion.connect_stage()
            if ok:
                self._log_action("K-Cube stage connected")
                self.show_tile("stage")
        elif name == "connect_stage" and not hardware_allowed:
            self._show_error("Enable hardware control to connect the stage.")
        elif name == "show_tile":
            tile_id = intent.params.get("tile_id", "camera")
            if tile_id in self._tiles:
                self.show_tile(tile_id)
                self._log_action(f"Opened tile: {tile_id}")
        elif name == "start_fft_monitor":
            self._fft_panel.set_monitoring(True)
        elif name == "stop_fft_monitor":
            self._fft_panel.set_monitoring(False)
        elif name == "jog_stage" and hardware_allowed:
            if not self._motion.connected:
                self._motion.connect_stage()
            self._motion.jog_mm(float(intent.params.get("delta_mm", 0.1)))
            self._log_action(f"Atria jog {float(intent.params.get('delta_mm', 0.1)):+.4f} mm")
        elif name == "go_safe_home" and hardware_allowed:
            self._motion.go_safe_home()
            self._log_action("Atria: go safe home")
        elif name == "mark_safe_home" and hardware_allowed:
            self._motion.mark_safe_home()
            self._log_action("Atria: mark safe home")
        elif name == "run_simulation":
            dur = intent.params.get("duration_sec")
            if dur is None:
                dur = DEFAULT_SIMULATION_DURATION_SEC
            self._start_simulation(float(dur), report_to_atria=True)
        elif name == "stop_simulation":
            self._stop_simulation()
            self._log_action("Atria: stop simulation")
        elif name in ("jog_stage", "go_safe_home", "mark_safe_home") and not hardware_allowed:
            self._show_error("Enable hardware control to move the stage.")

    # --- Telemetry and status ---

    def _poll_system_stats(self) -> None:
        if self._stats_worker.isRunning():
            return
        self._stats_worker.start()

    def _apply_system_stats(self, stats: SystemStats) -> None:
        self._system_stats = stats
        if self._system_stats.cpu_percent is not None:
            self._telemetry["cpu_pct"] = self._system_stats.cpu_percent
        self._telemetry["network"] = self._system_stats.network
        self._telemetry_bar.update_telemetry(self._telemetry)
        self._refresh_status()

    def _refresh_status(self, **kwargs) -> None:
        stats = self._system_stats
        cpu_text = "—"
        if stats.cpu_percent is not None:
            cpu_text = f"{stats.cpu_percent:.1f}%"
        # Pull an optional status override for Camera A from callers that pass camera=
        cam_a_override = kwargs.pop("camera", None)
        payload = {
            "wavelength_nm": self._telemetry.get("wavelength_nm", LASER_WAVELENGTH_NM),
            "camera_a": self._camera_a_status_label(cam_a_override),
            "camera_b": self._camera_b_status_label(),
            "laser": "Manual",
            "stage": "Connected" if self._motion.connected else "Disconnected",
            "scan": "Running" if self._scan_worker and self._scan_worker.isRunning() else "Idle",
            "ui_scale": self._telemetry.get("ui_scale_pct", "—"),
            "display": self._telemetry.get("display", "—"),
            "cpu": cpu_text,
            "ram": stats.ram_detail,
            "network": stats.network,
        }
        payload.update(kwargs)
        self._status_panel.update_status(payload)

    def _update_telemetry(self, **kwargs) -> None:
        self._telemetry.update(kwargs)
        if self._system_stats.cpu_percent is not None:
            self._telemetry["cpu_pct"] = self._system_stats.cpu_percent
        self._telemetry.setdefault("laser", "Manual")
        self._ai_panel.set_telemetry(self._telemetry)
        self._telemetry_bar.update_telemetry(self._telemetry)
        self._refresh_status()

    def _show_error(self, message: str) -> None:
        self._update_telemetry(status=f"Error: {message[:60]}")
        QMessageBox.warning(self, APP_TITLE, message)

    # --- Window lifecycle ---

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_hooked = True
        self._position_hex_rail()
        self._apply_ui_scale()
        ws = self._tile_layout.workspace_rect()
        self._last_workspace_px = (ws.x(), ws.y(), ws.width(), ws.height())
        if not self._layout_applied:
            self._layout_applied = True
            self._tile_layout.apply_startup_layout()
            self._sync_view_menu_checks()
        if not self._sys_timer.isActive():
            self._poll_system_stats()
            self._sys_timer.start()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            from gui.window_controls import is_maximized

            self._chrome.set_maximized_state(is_maximized(self))
            self._schedule_display_refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        ws = self._tile_layout.workspace_rect()
        ws_key = (ws.x(), ws.y(), ws.width(), ws.height())
        if ws_key != self._last_workspace_px:
            self._last_workspace_px = ws_key
            self._apply_ui_scale()
            self._sync_layout_after_resize()
        self._position_hex_rail()
        self._position_min_tile_bar()

    def _position_min_tile_bar(self) -> None:
        from gui.ui_scale import rail_width

        top = self.height() - MinimizedTileBar.BAR_HEIGHT - 4
        left = rail_width()
        self._min_tile_bar.setGeometry(
            left,
            max(self.chrome_height(), top),
            max(200, self.width() - left - 8),
            MinimizedTileBar.BAR_HEIGHT,
        )
        if self._min_tile_bar.isVisible():
            self._min_tile_bar.raise_()

    def _position_hex_rail(self) -> None:
        from gui.ui_scale import rail_width

        top = self.chrome_height()
        self._hex_rail.setGeometry(
            0,
            top,
            rail_width(),
            max(0, self.height() - top),
        )
        self._hex_rail.raise_()
        self._position_min_tile_bar()

    def _apply_default_visibility(self) -> None:
        for tile_id in DEFAULT_HIDDEN:
            self._tiles[tile_id].hide()

    def closeEvent(self, event) -> None:
        if not self._shutting_down:
            self._shutting_down = True
            self._shutdown_all()
        event.accept()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _shutdown_all(self) -> None:
        """Tear down tiles, tool windows, and hardware when IA exits."""
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(60000)
        if self._stats_worker.isRunning():
            self._stats_worker.wait(2000)
        self._stop_simulation()
        self._stop_camera()
        self._motion.disconnect()
        for tile in self._tiles.values():
            tile.shutdown()
        if hasattr(self, "_hex_rail"):
            self._hex_rail.hide()
