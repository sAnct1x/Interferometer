"""Main application window for the interferometer automation hub.

Domain mixins: ``dashboard_camera``, ``dashboard_sim``, ``dashboard_beam``,
``dashboard_atria``, ``dashboard_files``.
"""

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
)

from config import (
    APP_TITLE,
    ICONS_DIR,
    LASER_WAVELENGTH_NM,
)
from core.analytics.beam import roi_mean
from core.analytics.interferometer import recover_wavelength_from_csv
from core.camera_roles import ACTIVE_ROLES, CameraRole
from core.camera_worker import CameraWorker
from core.snap_worker import SnapWorker, THUMB_SNAP_TIMEOUT_S
from core.simulation.frame_generator import SimulationFrameGenerator, make_simulation_frame
from core.simulation_worker import SimulationWorker
from core.config_store import AppConfig, StageLimits, load_config, save_config
from core.laser_wavelength import resolve_wavelength_nm
from core.motion_control import MotionController
from core.scan_worker import WavelengthScanWorker
from core.system_stats import SystemStats, SystemStatsWorker
from gui.holo_background import HoloBackground
from gui.hub_chrome import HubChromeBar
from gui.neon_theme import CHROME_TELEMETRY_GAP_PX
from gui.hub_tile import HubTile, NON_SNAPPING_TILES
from gui.tile_layout import TileLayoutController
from gui.minimized_tile_bar import MinimizedTileBar
from gui.widgets.toast import ToastOverlay
from gui.wireframe_rail import NetworkRail
from gui.widgets.ai_terminal import AtriaPanel
from gui.widgets.beam_plots import BeamPlotsPanel
from gui.widgets.camera_view import CameraView, PopoutCameraPanel, RoiMode
from gui.widgets.efficiency_meter import EfficiencyMeterPanel
from gui.widgets.hardware_status import HardwareStatusPanel
from gui.widgets.stage_control import StageControlPanel
from gui.widgets.telemetry_bar import TelemetryBar
from gui.widgets.trend_panel import TrendPanel
from gui.widgets.roi_snapshot_panel import RoiSnapshotPanel
from gui.widgets.workspace_panel import WorkspacePanel
from gui.windows.tool_windows import (
    FftDiagnosticsPanel,
    LearnReferencePanel,
    PiezoOptimizerPanel,
    TaskManagerPanel,
)
from core.tile_layout_store import STARTUP_HIDDEN_TILES
from gui.dashboard_atria import DashboardAtriaMixin
from gui.dashboard_beam import DashboardBeamMixin
from gui.dashboard_camera import DashboardCameraMixin
from gui.dashboard_files import DashboardFileMixin
from gui.dashboard_sim import DashboardSimMixin

# Tiles visible on first launch (optional tiles open from Tools / View menus)
DEFAULT_OPEN = {"beam", "camera", "roi_snapshot", "efficiency", "status", "trends", "atria"}
DEFAULT_HIDDEN = set(STARTUP_HIDDEN_TILES)

# View menu tile order (Workspace directly under Atria Chat).
VIEW_MENU_TILES: tuple[tuple[str, str], ...] = (
    ("beam", "3D Beam Profile"),
    ("trends", "Alignment Trends"),
    ("efficiency", "Beam Efficiency"),
    ("status", "System Status"),
    ("camera", "Bench Cameras"),
    ("roi_snapshot", "ROI Snapshot"),
    ("atria", "Atria"),
    ("workspace", "Workspace"),
)

# Tools menu: optional hub tiles (hidden until opened from menu).
TOOLS_MENU_TILES: tuple[tuple[str, str], ...] = (
    ("stage", "Stage Control"),
    ("piezo", "Piezo Alignment Optimizer"),
    ("fft", "Coupling Efficiency FFT"),
    ("tasks", "Atria Task Manager"),
)

# Help menu: optional hub tiles (hidden until opened from menu).
HELP_MENU_TILES: tuple[tuple[str, str], ...] = (
    ("learn", "Learn: Physics & Bench Reference"),
)


class Dashboard(
    DashboardFileMixin,
    DashboardBeamMixin,
    DashboardCameraMixin,
    DashboardSimMixin,
    DashboardAtriaMixin,
    QMainWindow,
):
    """Main hub window: tiles, telemetry, and orchestration.

    Domain logic lives in mixins (camera, simulation, beam export, Atria, files)
    so this class stays focused on layout, menus, and lifecycle.
    """
    TILE_SPECS: dict[str, str] = {
        "camera": "Bench Cameras",
        "roi_snapshot": "ROI Snapshot",
        "beam": "3D Beam Profile",
        "efficiency": "Beam Efficiency",
        "status": "System Status",
        "trends": "Alignment Trends",
        "stage": "Stage Control",
        "piezo": "Piezo Alignment Optimizer",
        "fft": "Coupling Efficiency FFT",
        "tasks": "Atria Task Manager",
        "learn": "Learn: Physics & Bench Reference",
        "atria": "Atria",
        "workspace": "Workspace",
        "cam_far_field": "Far Field Camera",
        "cam_image": "Image Camera",
        "cam_output": "Output Camera",
    }

    # Role -> popped-out tile id for the tear-out camera tiles.
    POPOUT_TILE_IDS: dict[str, str] = {
        CameraRole.FAR_FIELD.value: "cam_far_field",
        CameraRole.IMAGE.value: "cam_image",
        CameraRole.OUTPUT.value: "cam_output",
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
        # One closed-loop engine shared by the Piezo tile and Simulation #2.
        from gui.sim_loop import ClosedLoopSimulation

        self._sim2 = ClosedLoopSimulation(self, disturbances=True)
        self._piezo_panel = PiezoOptimizerPanel(sim=self._sim2)
        self._popout_panels: dict[str, PopoutCameraPanel] = {
            tile_id: PopoutCameraPanel(self.TILE_SPECS[tile_id])
            for tile_id in self.POPOUT_TILE_IDS.values()
        }
        self._fft_panel = FftDiagnosticsPanel()
        self._tasks_panel = TaskManagerPanel()
        self._learn_panel = LearnReferencePanel()
        self._ai_panel = AtriaPanel()
        self._workspace_panel = WorkspacePanel()

        self._camera_panel.set_roi(self._cfg.beam_roi, RoiMode.BEAM)
        self._roi_snapshot_panel.set_roi(self._cfg.beam_roi, RoiMode.BEAM)
        self._stage_panel.set_stages(self._cfg.stages, active_index=0)
        for slot in self._cfg.cameras:
            self._camera_panel.set_camera_label(slot.role, slot.label)
            if slot.serial:
                self._camera_panel.set_camera_serial(slot.role, slot.serial)
        self._refresh_available_cameras()

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

        self._network_rail = NetworkRail(self)
        self._min_tile_bar = MinimizedTileBar(self)
        self._min_tile_bar.restore_requested.connect(self.restore_tile_from_bar)
        self._min_tile_bar.close_requested.connect(self._close_tile_from_bar)
        self._min_tile_bar.hide()
        self._toast = ToastOverlay(self)

        # Left-rail brightness pulse: rises while Atria is thinking or a
        # simulation is running, so the rail reads as alive, not decorative.
        self._activity_sources: dict[str, float] = {}
        self._ai_panel.busy_changed.connect(
            lambda busy: self._set_activity_source("atria", 1.0 if busy else 0.0)
        )

        # Simulation #2 flags must exist before tiles register: _register_tiles
        # triggers visibility callbacks that read _sim2_camera_mode via
        # _update_sim2_running().
        self._sim2_camera_mode = False
        self._sim2_running = False
        self._roi_snapshot_was_open_before_sim2 = False

        self._register_tiles()
        self._validate_menu_wiring()
        self._apply_default_visibility()
        self._build_menus()

        self._motion = MotionController(self)
        # Role-keyed camera acquisition (Far Field / Image / Output).
        self._camera_workers: dict[CameraRole, CameraWorker | None] = {
            r: None for r in ACTIVE_ROLES
        }
        self._role_live: dict[CameraRole, bool] = {r: False for r in ACTIVE_ROLES}
        # Serial each role's worker actually connected to (vs. the configured serial,
        # which may be left on "Auto"). Used to avoid two Auto roles both grabbing the
        # same physical camera.
        self._role_actual_serial: dict[CameraRole, str] = {}
        self._camera_live = False  # overall live-feed state (any role active)
        self._pending_camera_roles: list[CameraRole] = []
        # Live acquisition is paused when the Live Camera tile is hidden/minimized and
        # auto-resumed when it is shown again (see _on_camera_tile_visibility).
        self._camera_resume_on_show = False
        self._last_frame: dict[CameraRole, np.ndarray | None] = {
            r: None for r in ACTIVE_ROLES
        }
        self._last_exp_us: dict[CameraRole, float] = {r: 1.0 for r in ACTIVE_ROLES}
        self._role_display_last_t: dict[CameraRole, float] = {r: 0.0 for r in ACTIVE_ROLES}
        # Simulation #2 (piezo closed loop) shares one engine with the piezo tile.
        # _sim2_camera_mode / _sim2_running are initialized earlier (before
        # _register_tiles) since tile visibility callbacks read them.
        self._simulation_active = False
        self._simulation_worker: SimulationWorker | None = None
        self._simulation_generator = SimulationFrameGenerator(load_config())
        self._scan_worker: WavelengthScanWorker | None = None
        self._snap_worker: SnapWorker | None = None
        self._snap_role: CameraRole | None = None
        self._snap_resume_live_roles: list[CameraRole] = []
        self._auto_snap_roles: set[CameraRole] = set()
        # Non-primary roles: one frozen snap each, then open the primary live stream.
        self._pending_thumb_snaps: list[CameraRole] = []
        self._live_primary_pending: CameraRole | None = None
        self._resume_primary_after_thumbs = False
        self._snap_from_thumb_queue = False
        self._resume_live_after_scan = False
        self._fft_times: list[float] = []
        self._fft_samples: list[float] = []
        self._fft_last_sample_t: float | None = None
        self._fft_plot_last_t: float = 0.0
        self._sim_analytics_last_t: float = 0.0
        self._sim_display_last_t: float = 0.0
        self._live_display_last_t: float = 0.0
        self._live_analytics_last_t: float = 0.0
        self._sim2_analytics_last_t: float = 0.0
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

        from gui.glass_panel import BracketButton
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
        self._min_tile_bar.apply_ui_scale(scale)
        self._network_rail.setFixedWidth(rail_width(scale))

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
            for btn in panel.findChildren(BracketButton):
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
        # Only re-maximize when the OS/Qt maximized flag is set. Do NOT treat a
        # large windowed frame as maximized — that made Restore look broken
        # (showNormal left a full-screen rect, then this snapped it back).
        if is_maximized(self):
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
        self._position_network_rail()
        self._refresh_status()

    def _sync_layout_after_resize(self) -> None:
        """Reposition tiles after workspace geometry or UI scale changes."""
        if self._layout_applied:
            self._tile_layout.on_window_resized()

    def _set_activity_source(self, key: str, level: float) -> None:
        """Track one contributor to the rail's activity pulse and apply the loudest."""
        if level <= 0.0:
            self._activity_sources.pop(key, None)
        else:
            self._activity_sources[key] = level
        self._network_rail.set_activity(max(self._activity_sources.values(), default=0.0))

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
            "learn": self._learn_panel,
            "atria": self._ai_panel,
            "workspace": self._workspace_panel,
        }
        widgets.update(self._popout_panels)
        for tile_id, widget in widgets.items():
            title = self.TILE_SPECS[tile_id]
            tile = HubTile(tile_id, title, widget, self, self._workspace)
            tile.tile_closed.connect(self._on_tile_closed)
            tile.tile_drag_released.connect(self._on_tile_drag_released)
            tile.tile_double_clicked.connect(self._tile_layout.toggle_focus)
            tile.tile_resized.connect(self._tile_layout.handle_resize)
            tile.tile_visibility_changed.connect(self._on_tile_visibility_changed)
            self._tiles[tile_id] = tile

    def _validate_menu_wiring(self) -> None:
        """Fail fast in dev if a menu tile id is missing from the hub."""
        menu_ids = (
            {tid for tid, _ in VIEW_MENU_TILES}
            | {tid for tid, _ in TOOLS_MENU_TILES}
            | {tid for tid, _ in HELP_MENU_TILES}
        )
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
        file_menu.addAction("Open Beam Outputs Folder", self._file_open_beam_outputs_dir)
        file_menu.addAction("Open Latest Beam Report", self._open_latest_beam_run)

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
        tools_menu.addAction("Run Simulation #2: Piezo Closed Loop", self._start_simulation_two)
        tools_menu.addAction("Stop Simulation #2", self._stop_simulation_two)
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

        help_menu = menu.addMenu("Help")
        self._add_menu_tile_actions(help_menu, HELP_MENU_TILES)
        help_menu.addSeparator()
        help_menu.addAction("Atria Commands…", self._show_atria_commands)

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
        title = self.TILE_SPECS.get(tile_id, tile_id.replace("_", " ").title())
        self._min_tile_bar.add_tile(tile_id, title)
        self._position_min_tile_bar()
        self._min_tile_bar.show()
        self._min_tile_bar.raise_()
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
        title = self.TILE_SPECS.get(tile_id, tile_id)
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
                "No saved layout file yet, using built-in default homes.",
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

    def _show_atria_commands(self) -> None:
        from ai.help_catalog import format_help_text

        QMessageBox.information(self, APP_TITLE, format_help_text())

    def _on_tile_closed(self, tile_id: str) -> None:
        if tile_id.startswith("cam_"):
            role = CameraRole.coerce(tile_id[len("cam_"):])
            if self._camera_panel.is_popped(role):
                panel = self._popout_panels.get(tile_id)
                if panel is not None:
                    panel.take_pane()
                self._camera_panel.attach_pane(role)
        self._sync_view_menu_checks()

    def _on_tile_visibility_changed(self, tile_id: str, visible: bool) -> None:
        """React to a tile being shown/hidden so hidden tiles consume no resources."""
        if self._shutting_down:
            return
        if tile_id == "camera":
            self._on_camera_tile_visibility(visible)
        elif tile_id == "piezo":
            self._update_sim2_running()

    def _on_camera_tile_visibility(self, visible: bool) -> None:
        """Pause live acquisition while the camera tile is hidden; resume on show."""
        if visible:
            if self._camera_resume_on_show and not self._simulation_active:
                self._camera_resume_on_show = False
                self._start_camera()
                self._camera_panel.set_live_active(True)
            return
        if self._simulation_active or self._sim2_camera_mode:
            return
        if self._camera_live:
            self._camera_resume_on_show = True
            self._stop_camera()
            self._update_telemetry(status="Camera paused (tile hidden)")

    # --- Signal wiring ---

    def _wire_signals(self) -> None:
        self._camera_panel._mode_combo.currentIndexChanged.connect(self._switch_roi_mode)
        self._camera_panel.snapshot_captured.connect(self._on_snapshot_captured)
        self._camera_panel.snap_requested.connect(self._grab_single_frame_for_role)
        self._camera_panel.live_feed_toggled.connect(self._on_live_feed_toggled)
        self._camera_panel.camera_settings_changed.connect(self._on_camera_settings_changed)
        self._camera_panel.camera_label_changed.connect(self._on_camera_label_changed)
        self._camera_panel.popout_requested.connect(self._popout_camera)
        self._camera_panel.popin_requested.connect(self._popin_camera)
        self._camera_panel.primary_role_changed.connect(self._on_primary_camera_role_changed)
        self._camera_panel.camera_selection_changed.connect(self._on_camera_selection_changed)
        self._camera_panel.refresh_cameras_requested.connect(self._refresh_available_cameras)
        self._sim2.frames_ready.connect(self._on_sim2_frames)
        self._sim2.control_tick.connect(self._on_sim2_tick)
        self._roi_snapshot_panel.roi_changed.connect(self._on_roi_snapshot_changed)
        self._roi_snapshot_panel.capture_requested.connect(self._save_current_roi)
        self._roi_snapshot_panel.analyze_requested.connect(self._on_analyze_snapshot)
        self._beam_panel.analyze_requested.connect(self._analyze_beam_snapshot)
        self._beam_panel.export_requested.connect(self._export_beam_report)
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
        self._log_action("Frame snapped to ROI Snapshot")
        self._update_telemetry(status="Frame snapped to ROI Snapshot")

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

    # Beam analyze/export live in gui.dashboard_beam.DashboardBeamMixin

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
        self._update_telemetry(status="λ scan: connecting hardware…")

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
        self._roi_snapshot_panel.set_scan_busy(True)
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
        self._roi_snapshot_panel.set_scan_busy(False)
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
        self._toast.show_message(message)

    def _toggle_live_feed(self, active: bool) -> None:
        if self._simulation_active:
            if not active:
                self._stop_simulation()
            return
        self._camera_panel.set_live_active(active)
        try:
            if active:
                self._start_camera()
                self._log_action("Live camera feed started")
            else:
                self._stop_camera()
                self._log_action("Live camera feed stopped")
        except Exception as exc:
            # Keep the UI alive if a worker/setup path throws; toast instead of crash.
            self._camera_live = False
            self._camera_panel.set_live_active(False)
            self._toast.show_message(f"Live feed failed: {exc}", kind="error")
            self._log_action(f"Live feed failed: {exc}")

    def _grab_single_frame_for_role(
        self, role_value: str, *, from_thumb_queue: bool = False
    ) -> None:
        """Hardware snap for one role (frozen thumb, or manual Snap Frame)."""
        if self._simulation_active and self._simulation_last_frame is not None:
            self._on_snapshot_captured(np.asarray(self._simulation_last_frame).copy())
            if from_thumb_queue:
                QTimer.singleShot(0, self._advance_thumb_snap_queue)
            return
        role = CameraRole.coerce(role_value)
        cached = self._camera_panel.role_frame(role)

        # Thumb queue: keep a demoted live frame as the frozen preview (no re-grab).
        if from_thumb_queue and cached is not None:
            self._show_role_standby(role)
            QTimer.singleShot(0, self._advance_thumb_snap_queue)
            return

        # Manual Snap while that role is streaming: push the newest live buffer
        # into ROI Snapshot (do not reuse a non-live frozen thumb).
        if not from_thumb_queue and self._role_live.get(role):
            frame = self._last_frame.get(role)
            if frame is None:
                frame = cached
            if frame is not None:
                self._ingest_role_snap(role, np.asarray(frame).copy(), to_roi=True)
                return

        if self._snap_worker is not None and self._snap_worker.isRunning():
            if from_thumb_queue and role not in self._pending_thumb_snaps:
                self._pending_thumb_snaps.insert(0, role)
            return
        serial = self._serial_for_role(role)
        if not serial:
            if from_thumb_queue:
                self._camera_panel.show_role_status(
                    role, f"{role.label}\n\nNo serial assigned"
                )
                QTimer.singleShot(0, self._advance_thumb_snap_queue)
            else:
                self._show_error(f"No serial assigned for {role.label}.")
            return

        # Never open a second TLCam while any live worker holds a device — that
        # hard-crashes the Thorlabs SDK on this bench USB. Pause live briefly.
        paused_live: list[CameraRole] = []
        if not from_thumb_queue and any(self._role_live.values()):
            for live_role in list(self._camera_workers):
                if self._role_live.get(live_role):
                    self._stop_role_worker(live_role, keep_preview=True)
                    paused_live.append(live_role)
            self._snap_resume_live_roles = paused_live
        else:
            self._snap_resume_live_roles = []

        self._snap_role = role
        self._snap_from_thumb_queue = from_thumb_queue
        self._update_telemetry(status=f"Capturing {role.label}…")
        if not from_thumb_queue:
            self._camera_panel.set_snap_busy(True)
        settings = self._camera_panel.stored_camera_settings(role)
        payload: dict = {}
        if settings.get("exposure_us") is not None:
            payload["exposure_us"] = settings["exposure_us"]
        if role in (CameraRole.IMAGE, CameraRole.OUTPUT):
            ui_exp = float(settings.get("exposure_us") or 0)
            ff_exp = float(self._last_exp_us.get(CameraRole.FAR_FIELD, 0))
            if ff_exp > 0 and ui_exp <= 15_000:
                payload["exposure_us"] = ff_exp
        if settings.get("fps_auto") is not None:
            payload["fps_auto"] = settings["fps_auto"]
            if not settings.get("fps_auto") and settings.get("fps_hz"):
                payload["fps_hz"] = settings["fps_hz"]
        self._snap_worker = SnapWorker(
            serial,
            settings=payload,
            timeout_s=THUMB_SNAP_TIMEOUT_S if from_thumb_queue else 15.0,
            parent=self,
        )
        # Generation token so late/terminate errors cannot escalate to _show_error
        # after the thumb flag was already cleared.
        self._snap_generation = int(getattr(self, "_snap_generation", 0)) + 1
        snap_gen = self._snap_generation
        self._snap_worker.frame_ready.connect(
            lambda f, g=snap_gen: self._on_single_snap_ready_gated(f, g)
        )
        self._snap_worker.error.connect(
            lambda e, g=snap_gen: self._on_snap_error_gated(e, g)
        )
        self._snap_worker.status.connect(lambda s: self._update_telemetry(status=s[:80]))
        self._snap_worker.finished.connect(self._clear_snap_worker)
        self._snap_worker.start()
        if from_thumb_queue:
            QTimer.singleShot(
                int(THUMB_SNAP_TIMEOUT_S * 1000) + 800,
                lambda g=snap_gen: self._thumb_snap_watchdog(g),
            )

    def _grab_single_frame(self) -> None:
        """Legacy entry: snap the camera selected under Show & tune."""
        self._grab_single_frame_for_role(self._camera_panel.settings_role().value)

    def _ingest_role_snap(
        self, role: CameraRole, frame: np.ndarray, *, to_roi: bool = False
    ) -> None:
        self._last_frame[role] = frame
        self._camera_panel.set_role_frame(role, frame, repaint=True)
        if role is CameraRole.FAR_FIELD and role != self._camera_panel.primary_role():
            self._camera_panel.set_coupling_overlay(None, role)
        if to_roi:
            self._on_snapshot_captured(frame)
        # Output (or Far Field) snap should refresh η immediately.
        if role in (CameraRole.FAR_FIELD, CameraRole.OUTPUT):
            self._efficiency_last_t = 0.0
            self._compute_live_efficiency()

    def _on_single_snap_ready_gated(self, frame: np.ndarray, generation: int) -> None:
        if generation != getattr(self, "_snap_generation", 0):
            return
        self._on_single_snap_ready(frame)

    def _on_snap_error_gated(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_snap_generation", 0):
            return
        self._on_snap_error(message)

    def _thumb_snap_watchdog(self, generation: int) -> None:
        """Unstick a hung thumb snap without ``terminate()`` (that corrupts TLCam)."""
        if generation != getattr(self, "_snap_generation", 0):
            return
        worker = self._snap_worker
        if worker is None or not worker.isRunning():
            return
        if not self._snap_from_thumb_queue:
            return
        # Soft-fail UI immediately; let the thread exit on its own timeout.
        # QThread.terminate() after a hung SDK open caused native crashes on Stop.
        self._on_snap_error("no frame (timeout)")
        try:
            worker.wait(1500)
        except Exception:
            pass
        if self._snap_worker is worker:
            self._clear_snap_worker()

    def _on_snap_error(self, message: str) -> None:
        """Thumb failures are soft; only manual Snap Frame escalates to Error."""
        was_thumb = bool(self._snap_from_thumb_queue)
        role = self._snap_role
        soft = was_thumb or "timeout" in message.lower() or "no frame" in message.lower()
        if soft:
            if role is not None:
                dark = np.zeros((240, 320), dtype=np.uint8)
                self._last_frame[role] = dark
                self._camera_panel.set_role_frame(role, dark, repaint=True)
                if hasattr(self._camera_panel, "set_role_metric"):
                    self._camera_panel.set_role_metric(role, "dark / no frame")
            # Quiet status — never "Error:" for background thumb snaps.
            label = role.label if role is not None else "Camera"
            self._update_telemetry(status=f"{label}: no frame yet (ok if blocked)")
            return
        self._show_error(message)

    def _clear_snap_worker(self) -> None:
        was_thumb = self._snap_from_thumb_queue
        resume_roles = list(getattr(self, "_snap_resume_live_roles", []) or [])
        self._snap_resume_live_roles = []
        self._snap_worker = None
        self._snap_role = None
        self._snap_from_thumb_queue = False
        self._camera_panel.set_snap_busy(False)
        if was_thumb or self._pending_thumb_snaps or self._live_primary_pending is not None:
            QTimer.singleShot(200, self._advance_thumb_snap_queue)
            return
        # Manual snap paused live workers — restart them if live feed is still on.
        if self._camera_live and resume_roles:
            for role in resume_roles:
                if role in self._live_roles() and not self._role_live.get(role):
                    self._start_role_worker(role)
            self._sync_camera_preview_rates()
            self._refresh_status()

    def _on_single_snap_ready(self, frame: np.ndarray) -> None:
        role = self._snap_role or self._camera_panel.settings_role()
        self._log_action(
            f"Single frame captured from {role.label} ({self._serial_for_role(role) or '?'})"
        )
        to_roi = not self._snap_from_thumb_queue
        self._ingest_role_snap(role, frame, to_roi=to_roi)

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
        ff = self._last_frame.get(CameraRole.FAR_FIELD)
        out = self._last_frame.get(CameraRole.OUTPUT)
        if ff is None:
            ff = self._camera_panel.role_frame(CameraRole.FAR_FIELD)
        if out is None:
            out = self._camera_panel.role_frame(CameraRole.OUTPUT)
        if ff is not None and out is not None:
            roi_a = self._cfg.beam_roi
            out_slot = self._cfg.camera_by_role(CameraRole.OUTPUT)
            roi_b = out_slot.beam_roi if out_slot else roi_a
            mean_in = roi_mean(ff, roi_a)
            mean_out = roi_mean(out, roi_b)
            exp_a = max(self._last_exp_us.get(CameraRole.FAR_FIELD, 1.0), 1.0)
            exp_b = max(self._last_exp_us.get(CameraRole.OUTPUT, 1.0), 1.0)
            if mean_in <= 0:
                self._show_error("Far Field ROI mean is zero. Is the Far Field camera running?")
                return
            ratio = (mean_out / exp_b) / (mean_in / exp_a)
            self._cfg.efficiency_reference_ratio = ratio
            save_config(self._cfg)
            self._log_action(f"η=100% recalibrated (ratio={ratio:.4f})")
            self._update_telemetry(status="η baseline set to 100%")
            self._efficiency_last_t = 0.0
            self._compute_live_efficiency()
            if mean_out <= 0:
                self._toast.show_message(
                    "Calibrated, but Output ROI mean is ~0 — check light after the fiber / Output ROI.",
                    kind="error",
                )
        else:
            frame = self._roi_snapshot_panel.analysis_frame() or self._camera_panel.current_frame()
            if frame is None:
                self._show_error("Start live feed or snap a frame first.")
                return
            mean = roi_mean(frame, self._cfg.fringe_roi)
            if mean != mean or mean <= 0:
                self._show_error("Fringe ROI mean invalid. Check ROI.")
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
        # Pull an optional status override for Far Field from callers that pass camera_far_field=
        far_field_override = kwargs.pop("camera_far_field", None)
        payload = {
            "wavelength_nm": self._telemetry.get("wavelength_nm", LASER_WAVELENGTH_NM),
            "camera_far_field": self._far_field_status_label(far_field_override),
            "camera_output": self._output_status_label(),
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
        """Surface errors via toast + telemetry (no blocking modal during bench work)."""
        self._update_telemetry(status=f"Error: {message[:60]}")
        self._toast.show_message(message, kind="error")

    # --- Window lifecycle ---

    def showEvent(self, event) -> None:
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_hooked = True
        self._position_network_rail()
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
            from gui.window_controls import looks_maximized

            # Pause the decorative rail animation while minimized so it stops
            # burning CPU behind a hidden window; resume when restored.
            minimized = bool(self.windowState() & Qt.WindowState.WindowMinimized)
            if hasattr(self, "_network_rail"):
                self._network_rail.set_animation_active(not minimized)

            self._chrome.set_maximized_state(looks_maximized(self))
            self._schedule_display_refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        ws = self._tile_layout.workspace_rect()
        ws_key = (ws.x(), ws.y(), ws.width(), ws.height())
        if ws_key != self._last_workspace_px:
            self._last_workspace_px = ws_key
            self._apply_ui_scale()
            self._sync_layout_after_resize()
        self._position_network_rail()
        self._position_min_tile_bar()
        self._position_toast_overlay()

    def _position_toast_overlay(self) -> None:
        from gui.ui_scale import minimized_bar_height, toast_width

        width = toast_width()
        bottom_margin = minimized_bar_height() + 16
        top = self.chrome_height() + 8
        self._toast.setGeometry(
            max(0, self.width() - width - 16),
            top,
            width,
            max(0, self.height() - top - bottom_margin),
        )
        self._toast.raise_()

    def _position_min_tile_bar(self) -> None:
        from gui.ui_scale import minimized_bar_height, rail_width

        bar_height = minimized_bar_height()
        top = self.height() - bar_height - 4
        left = rail_width()
        self._min_tile_bar.setGeometry(
            left,
            max(self.chrome_height(), top),
            max(200, self.width() - left - 8),
            bar_height,
        )
        if self._min_tile_bar.has_tiles():
            self._min_tile_bar.show()
            self._min_tile_bar.raise_()
        elif self._min_tile_bar.isVisible():
            self._min_tile_bar.hide()

    def _position_network_rail(self) -> None:
        from gui.ui_scale import rail_width

        top = self.chrome_height()
        self._network_rail.setGeometry(
            0,
            top,
            rail_width(),
            max(0, self.height() - top),
        )
        self._network_rail.raise_()
        self._position_min_tile_bar()
        self._position_toast_overlay()

    def _apply_default_visibility(self) -> None:
        for tile_id in DEFAULT_HIDDEN:
            self._tiles[tile_id].hide()

    def _remember_window_state(self) -> None:
        """Snapshot the current monitor/position so the next launch reopens here."""
        from gui.window_controls import capture_window_state

        screen_name, geometry, maximized = capture_window_state(self)
        self._cfg.window_screen_name = screen_name
        self._cfg.window_geometry = geometry
        self._cfg.window_maximized = maximized
        save_config(self._cfg)

    def closeEvent(self, event) -> None:
        if not self._shutting_down:
            self._shutting_down = True
            self._remember_window_state()
            self._shutdown_all()
        event.accept()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _shutdown_all(self) -> None:
        """Tear down tiles, workers, timers, and hardware when IA exits."""
        if hasattr(self, "_sys_timer") and self._sys_timer.isActive():
            self._sys_timer.stop()
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.wait(60000)
        if self._stats_worker.isRunning():
            self._stats_worker.wait(2000)
        snap = getattr(self, "_snap_worker", None)
        if snap is not None and snap.isRunning():
            snap.wait(3000)
        self._stop_simulation()
        self._sim2_camera_mode = False
        if self._sim2_running:
            self._sim2.stop()
            self._sim2_running = False
        self._stop_camera()
        self._motion.disconnect()
        for tile in self._tiles.values():
            tile.shutdown()
        if hasattr(self, "_network_rail"):
            self._network_rail.hide()
