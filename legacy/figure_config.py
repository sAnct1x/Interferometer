"""Matplotlib figure defaults for lab scan/analysis plots (shared constants)."""

from __future__ import annotations

FIG_FIGSIZE_IN: tuple[float, float] = (10.71, 6.12)
FIG_SAVE_DPI: int = 150
FIG_FONT_PT: int = 16
FIG_STFT_TRACE_YLIM: tuple[float, float] = (-25.0, 100.0)
FIG_STFT_TRACE_YTICKS: tuple[float, ...] = (-25.0, 0.0, 25.0, 50.0, 75.0, 100.0)

# Legacy names used by interferometer_acquire_analyze.py
POSTER_FIGSIZE_IN = FIG_FIGSIZE_IN
POSTER_SAVE_DPI = FIG_SAVE_DPI
POSTER_FONT_PT = FIG_FONT_PT
POSTER_STFT_TRACE_YLIM = FIG_STFT_TRACE_YLIM
POSTER_STFT_TRACE_YTICKS = FIG_STFT_TRACE_YTICKS
