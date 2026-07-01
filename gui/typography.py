"""Uniform UI typography — one body size everywhere except titles."""

from __future__ import annotations

from gui.neon_theme import (
    NEON_PINK,
    NEON_PURPLE,
    TEXT_HINT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_TITLE,
)

BODY_FONT_PX = 13
TITLE_FONT_PX = 14
BODY_FONT_PT = 10.0
TITLE_FONT_PT = 11.0


def _scale(scale: float | None) -> float:
    from gui.ui_scale import get_scale

    return scale if scale is not None else get_scale()


def body_px(scale: float | None = None) -> int:
    from gui.ui_scale import px

    return max(11, px(BODY_FONT_PX, _scale(scale)))


def title_px(scale: float | None = None) -> int:
    from gui.ui_scale import px

    return max(12, px(TITLE_FONT_PX, _scale(scale)))


def body_pt(scale: float | None = None) -> float:
    return max(8.0, BODY_FONT_PT * _scale(scale))


def title_pt(scale: float | None = None) -> float:
    return max(9.0, TITLE_FONT_PT * _scale(scale))


def body_css(scale: float | None = None) -> str:
    return f"font-size: {body_px(scale)}px;"


def label_style(color: str, scale: float | None = None) -> str:
    return f"color: {color}; {body_css(scale)}"


def primary_style(scale: float | None = None) -> str:
    return label_style(TEXT_PRIMARY, scale)


def hint_style(scale: float | None = None) -> str:
    return label_style(TEXT_HINT, scale)


def muted_style(scale: float | None = None) -> str:
    return label_style(TEXT_MUTED, scale)


def value_style(color: str = TEXT_PRIMARY, scale: float | None = None, mono: bool = True) -> str:
    fam = "font-family: Consolas; " if mono else ""
    return f"color: {color}; {fam}{body_css(scale)}"


def section_style(color: str = TEXT_MUTED, scale: float | None = None) -> str:
    return f"color: {color}; {body_css(scale)}; font-weight: bold;"


def callout_style(scale: float | None = None) -> str:
    return (
        value_style(TEXT_PRIMARY, scale) + " font-weight: bold; "
        f"background: rgba(168,85,247,0.15); padding: 5px 8px; "
        f"border: 1px solid rgba(148,163,184,0.35); border-radius: 6px;"
    )


def panel_title_stylesheet(scale: float | None = None) -> str:
    return (
        f"color: {TEXT_TITLE}; font-weight: bold; font-size: {title_px(scale)}px; "
        f"background: transparent; border-bottom: 1px solid {NEON_PINK}; padding-bottom: 2px;"
    )


def plot_axis_size_pt(scale: float | None = None) -> str:
    return f"{body_pt(scale):.1f}pt"


def style_neon_plot(plot, x_label: str, y_label: str, scale: float | None = None) -> None:
    import pyqtgraph as pg

    plot.setBackground((18, 10, 40, 170))
    plot.showGrid(x=True, y=True, alpha=0.3)
    axis_size = plot_axis_size_pt(scale)
    tick_pen = pg.mkPen(TEXT_MUTED, width=1)
    plot.setLabel("bottom", x_label, color=TEXT_MUTED, size=axis_size)
    plot.setLabel("left", y_label, color=TEXT_MUTED, size=axis_size)
    for axis in ("bottom", "left"):
        plot.getAxis(axis).setPen(tick_pen)
        plot.getAxis(axis).setTextPen(TEXT_PRIMARY)
