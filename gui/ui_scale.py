"""UI scale for any monitor resolution or laptop display."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QGuiApplication, QScreen

# Workspace pixel area used when the UI was tuned (not the raw monitor size).
REFERENCE_WORKSPACE_WIDTH = 2480
REFERENCE_WORKSPACE_HEIGHT = 1180

# Absolute floors so controls never disappear on very small windows.
ABS_MIN_TILE_W = 48
ABS_MIN_TILE_H = 40
ABS_MIN_WINDOW_W = 800
ABS_MIN_WINDOW_H = 500

# Cap tile minimums as a fraction of workspace so several tiles can coexist on one screen.
MAX_TILE_MIN_WIDTH_FRAC = 0.46
MAX_TILE_MIN_HEIGHT_FRAC = 0.58

_current_scale = 1.0
_last_workspace_size: tuple[int, int] = (0, 0)
_last_screen_label: str = ""
_active_preset_id = "auto"


@dataclass(frozen=True)
class DisplayPreset:
    """Target display profile — scales chrome, tiles, fonts, grid, and backdrop together."""

    id: str
    label: str
    design_width: int = REFERENCE_WORKSPACE_WIDTH
    design_height: int = REFERENCE_WORKSPACE_HEIGHT
    scale_multiplier: float = 1.0
    scale_min: float = 0.32
    scale_max: float = 1.0
    use_compact_layout: bool = False


DISPLAY_PRESETS: tuple[DisplayPreset, ...] = (
    DisplayPreset("auto", "Auto — match this monitor"),
    DisplayPreset(
        "1440p",
        "1440p design (2560×1440)",
        REFERENCE_WORKSPACE_WIDTH,
        REFERENCE_WORKSPACE_HEIGHT,
        1.0,
        0.40,
        1.0,
    ),
    DisplayPreset(
        "1080p",
        "1080p (1920×1080)",
        2100,
        1000,
        0.92,
        0.36,
        0.90,
    ),
    DisplayPreset(
        "1366",
        "1366×768 laptop",
        2900,
        1350,
        0.78,
        0.32,
        0.68,
        use_compact_layout=True,
    ),
    DisplayPreset(
        "1280",
        "1280×720 compact",
        3100,
        1450,
        0.68,
        0.32,
        0.58,
        use_compact_layout=True,
    ),
)

_PRESET_BY_ID: dict[str, DisplayPreset] = {p.id: p for p in DISPLAY_PRESETS}


def display_presets() -> tuple[DisplayPreset, ...]:
    return DISPLAY_PRESETS


def preset_by_id(preset_id: str) -> DisplayPreset | None:
    return _PRESET_BY_ID.get(preset_id)


def get_display_preset_id() -> str:
    return _active_preset_id


def get_display_preset() -> DisplayPreset:
    return _PRESET_BY_ID.get(_active_preset_id, _PRESET_BY_ID["auto"])


def set_display_preset_id(preset_id: str) -> None:
    global _active_preset_id
    if preset_id in _PRESET_BY_ID:
        _active_preset_id = preset_id


def compute_ui_scale(width: int, height: int, preset: DisplayPreset | None = None) -> float:
    """Scale factor for a workspace size and the active (or given) display preset."""
    preset = preset or get_display_preset()
    if width <= 0 or height <= 0:
        return preset.scale_max
    sx = width / max(1, preset.design_width)
    sy = height / max(1, preset.design_height)
    raw = min(sx, sy) * preset.scale_multiplier
    return max(preset.scale_min, min(preset.scale_max, raw))


def workspace_ui_scale(width: int, height: int) -> float:
    """Scale factor from live workspace pixels vs the active display preset."""
    return compute_ui_scale(width, height)


# Unscaled chrome stack (title + telemetry + gap) for boot-time workspace estimates.
_BOOT_CHROME_RESERVE_PX = 40 + 38 + 24


def _chrome_reserve_px(scale: float | None = None) -> int:
    """Approximate vertical space used by title bar + telemetry before the workspace."""
    s = scale if scale is not None else get_scale()
    return chrome_bar_height(s) + telemetry_bar_height(s) + 24


def screen_ui_scale(screen: QScreen | None = None) -> float:
    """Estimate scale from monitor available geometry (used before the window is sized)."""
    if screen is None:
        app = QGuiApplication.instance()
        screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return get_display_preset().scale_max
    geo = screen.availableGeometry()
    rough_ws_h = max(200, geo.height() - _BOOT_CHROME_RESERVE_PX)
    rough_ws_w = max(200, geo.width() - 120)
    rough_scale = workspace_ui_scale(rough_ws_w, rough_ws_h)
    rail = int(round(120 * rough_scale))
    chrome = _chrome_reserve_px(rough_scale)
    ws_w = max(200, geo.width() - rail)
    ws_h = max(200, geo.height() - chrome)
    return workspace_ui_scale(ws_w, ws_h)


def screen_display_label(screen: QScreen | None = None) -> str:
    """Human-readable monitor size for status / debugging."""
    if screen is None:
        app = QGuiApplication.instance()
        screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return "unknown"
    avail = screen.availableGeometry()
    logical = screen.size()
    name = screen.model() or screen.name() or "display"
    dpr = screen.devicePixelRatio()
    avail_txt = f"{avail.width()}×{avail.height()}"
    if logical.width() != avail.width() or logical.height() != avail.height():
        avail_txt = f"{avail_txt} avail"
    native_txt = f"{logical.width()}×{logical.height()}"
    if dpr > 1.01:
        return f"{avail_txt} · {native_txt} @{dpr:.0f}x ({name})"
    return f"{avail_txt} · {native_txt} ({name})"


def set_current_scale(scale: float) -> None:
    global _current_scale
    preset = get_display_preset()
    _current_scale = max(preset.scale_min, min(preset.scale_max, float(scale)))


def get_scale() -> float:
    return _current_scale


def set_workspace_context(width: int, height: int, screen: QScreen | None = None) -> float:
    """Update scale from the live workspace and remember context for telemetry."""
    global _last_workspace_size, _last_screen_label
    scale = workspace_ui_scale(width, height)
    set_current_scale(scale)
    _last_workspace_size = (width, height)
    _last_screen_label = screen_display_label(screen)
    return scale


def ui_scale_summary() -> dict[str, str | float]:
    """Snapshot for System Status / telemetry."""
    w, h = _last_workspace_size
    preset = get_display_preset()
    return {
        "ui_scale": get_scale(),
        "ui_scale_pct": f"{int(round(get_scale() * 100))}%",
        "ui_preset": preset.label,
        "workspace_px": f"{w}×{h}" if w and h else "—",
        "display": _last_screen_label or "—",
    }


def px(value: float, scale: float | None = None) -> int:
    s = scale if scale is not None else _current_scale
    return max(1, int(round(value * s)))


def tile_min_size(
    tile_id: str,
    scale: float | None = None,
    *,
    workspace_width: int | None = None,
    workspace_height: int | None = None,
) -> tuple[int, int]:
    """Scaled minimum tile size, capped so multiple tiles fit on small displays."""
    from gui.hub_tile import DEFAULT_MIN_SIZE, TILE_MIN_SIZES

    base = TILE_MIN_SIZES.get(tile_id, DEFAULT_MIN_SIZE)
    s = scale if scale is not None else _current_scale
    min_w = px(base[0], s)
    min_h = px(base[1], s)

    if workspace_width is not None and workspace_width > 0:
        cap_w = int(workspace_width * MAX_TILE_MIN_WIDTH_FRAC)
        min_w = min(min_w, cap_w)
    if workspace_height is not None and workspace_height > 0:
        cap_h = int(workspace_height * MAX_TILE_MIN_HEIGHT_FRAC)
        min_h = min(min_h, cap_h)

    return max(ABS_MIN_TILE_W, min_w), max(ABS_MIN_TILE_H, min_h)


def rail_width(scale: float | None = None) -> int:
    return px(120, scale)


def chrome_bar_height(scale: float | None = None) -> int:
    return max(40, px(46, scale))


def menubar_height(scale: float | None = None) -> int:
    """Menu row height — never shrink below a usable click target."""
    return max(24, px(30, scale))


def telemetry_bar_height(scale: float | None = None) -> int:
    return max(38, px(52, scale))


def panel_header_height(scale: float | None = None) -> int:
    return px(32, scale)


def grid_cell_px(scale: float | None = None) -> int:
    """Fine workspace grid spacing — scales with the active display preset."""
    return max(8, px(32, scale))


def window_minimum_size(
    scale: float | None = None,
    *,
    screen_width: int | None = None,
    screen_height: int | None = None,
) -> tuple[int, int]:
    """Window minimum that fits small laptops but never exceeds the current monitor."""
    s = scale if scale is not None else _current_scale
    want_w = px(1280, s)
    want_h = px(720, s)
    min_w = max(ABS_MIN_WINDOW_W, want_w)
    min_h = max(ABS_MIN_WINDOW_H, want_h)
    if screen_width is not None:
        min_w = min(screen_width, min_w)
    if screen_height is not None:
        min_h = min(screen_height, min_h)
    return min_w, min_h


def apply_app_font_scale(app, scale: float | None = None) -> None:
    """Scale the default application font (widgets without explicit px stylesheets)."""
    from gui.typography import BODY_FONT_PT

    s = scale if scale is not None else _current_scale
    target_pt = max(7.5, BODY_FONT_PT * s)
    font = app.font()
    if abs(font.pointSizeF() - target_pt) < 0.1:
        return
    font.setPointSizeF(target_pt)
    app.setFont(font)
