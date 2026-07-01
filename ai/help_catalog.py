"""Atria native command catalog for the help intent and Gemini tool docs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpEntry:
    """One native Atria command row."""

    intent: str
    title: str
    description: str
    examples: tuple[str, ...]
    hardware: bool = False


HELP_SECTIONS: tuple[tuple[str, tuple[HelpEntry, ...]], ...] = (
    (
        "Reports",
        (
            HelpEntry(
                "report_beam_waist",
                "Beam waist",
                "Read 1/e² beam waist from the live beam ROI.",
                ("beam waist", "beam size", "spot size"),
            ),
            HelpEntry(
                "report_efficiency",
                "Coupling efficiency",
                "Report camera coupling η% (needs a calibrated baseline).",
                ("efficiency", "coupling", "eta"),
            ),
            HelpEntry(
                "report_wavelength",
                "Wavelength status",
                "Show active λ, diode label, and last measured value.",
                ("what is the wavelength", "report wavelength"),
            ),
        ),
    ),
    (
        "Wavelength",
        (
            HelpEntry(
                "set_wavelength_nominal",
                "Use diode label λ",
                "Switch active wavelength to the nominal diode label.",
                ("use nominal wavelength", "set wavelength to 520 nm nominal"),
            ),
            HelpEntry(
                "set_wavelength_measured",
                "Use measured λ",
                "Switch active wavelength to the last scan / recovered value.",
                ("use measured wavelength", "wavelength from scan"),
            ),
            HelpEntry(
                "set_wavelength",
                "Set λ manually",
                "Set active wavelength to a specific value in nm.",
                ("set wavelength to 532 nm"),
            ),
        ),
    ),
    (
        "Camera",
        (
            HelpEntry(
                "toggle_live_feed",
                "Live feed",
                "Start or stop the Thorcam live stream.",
                ("start live feed", "stop live feed"),
            ),
            HelpEntry(
                "snap_frame",
                "Snap frame",
                "Capture one frame to ROI Snap Shot (works without live feed).",
                ("snap frame", "capture image"),
            ),
            HelpEntry(
                "analyze_beam",
                "Analyze beam",
                "Run beam analysis on the snapshot or live frame.",
                ("analyze beam"),
            ),
            HelpEntry(
                "capture_roi",
                "Save ROI",
                "Save the current fringe ROI to config.",
                ("save roi", "capture roi"),
            ),
        ),
    ),
    (
        "Stage",
        (
            HelpEntry(
                "connect_stage",
                "Connect stage",
                "Connect the active K-Cube stage.",
                ("connect stage"),
                hardware=True,
            ),
            HelpEntry(
                "jog_stage",
                "Jog stage",
                "Move the stage relative by mm (clamped to limits).",
                ("jog stage 0.1 mm", "jog backward 0.05"),
                hardware=True,
            ),
            HelpEntry(
                "go_safe_home",
                "Go safe home",
                "Move to the saved crash-recovery safe home.",
                ("safe home", "go safe home"),
                hardware=True,
            ),
            HelpEntry(
                "mark_safe_home",
                "Save safe home",
                "Mark current position as safe home.",
                ("save safe home", "mark safe home"),
                hardware=True,
            ),
            HelpEntry(
                "run_wavelength_scan",
                "Wavelength scan",
                "Step the stage and recover λ from fringe data.",
                ("scan wavelength", "run wavelength scan"),
                hardware=True,
            ),
        ),
    ),
    (
        "Bench",
        (
            HelpEntry(
                "calibrate_efficiency",
                "Calibrate η",
                "Set efficiency baseline from current fringe ROI mean.",
                ("calibrate efficiency"),
            ),
            HelpEntry(
                "load_scan_csv",
                "Load scan CSV",
                "Import a scan CSV to recover wavelength.",
                ("load scan csv"),
            ),
            HelpEntry(
                "start_fft_monitor",
                "Start FFT monitor",
                "Live FFT on fringe ROI intensity.",
                ("start fft monitor"),
            ),
            HelpEntry(
                "stop_fft_monitor",
                "Stop FFT monitor",
                "Stop the live FFT monitor.",
                ("stop fft monitor"),
            ),
            HelpEntry(
                "run_simulation",
                "Run simulation",
                "Timed mock live feed (default 20 s) — beam, η, trends, FFT. "
                "Say duration: run simulation 30s.",
                (
                    "run simulation",
                    "start simulation",
                    "simulate",
                    "run simulation 20s",
                    "run a 10s simulation",
                    "simulate for 30 seconds",
                ),
            ),
            HelpEntry(
                "stop_simulation",
                "Stop simulation",
                "Stop the bench simulation feed.",
                ("stop simulation"),
            ),
        ),
    ),
    (
        "Tiles",
        (
            HelpEntry(
                "show_tile",
                "Open tile",
                "Show a hub tile (camera, stage, fft, tasks, etc.).",
                ("open stage control", "show camera", "open fft"),
            ),
        ),
    ),
)

_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "reports": ("report", "reports", "status", "read"),
    "wavelength": ("wavelength", "lambda", "λ"),
    "camera": ("camera", "live", "snap", "beam", "roi"),
    "stage": ("stage", "k-cube", "kcube", "jog", "home"),
    "bench": ("bench", "scan", "fft", "efficiency", "csv"),
    "tiles": ("tile", "tiles", "open", "show"),
}


def _normalize_topic(topic: str) -> str | None:
    t = topic.strip().lower()
    if not t:
        return None
    for key, aliases in _TOPIC_ALIASES.items():
        if t == key or any(a in t for a in aliases):
            return key
    return None


_SECTION_KEYS: dict[str, str] = {
    "Reports": "reports",
    "Wavelength": "wavelength",
    "Camera": "camera",
    "Stage": "stage",
    "Bench": "bench",
    "Tiles": "tiles",
}


def format_help_text(topic: str = "") -> str:
    """Build help text for the full catalog or a filtered topic."""
    key = _normalize_topic(topic)
    lines: list[str] = []

    if key is None and topic.strip():
        lines.append(f"No help topic matching “{topic.strip()}”. Showing everything.\n")

    lines.append("Native Atria commands (instant or via Gemini tools):")
    lines.append("Type these phrases directly for instant execution (no API call).")
    lines.append("Natural language (e.g. “please analyze the beam”) uses Gemini.")
    lines.append("Enable “Allow hardware control” for stage moves and scans.\n")

    for section_name, entries in HELP_SECTIONS:
        section_key = _SECTION_KEYS[section_name]
        if key is not None and key != section_key:
            continue

        lines.append(f"## {section_name}")
        for entry in entries:
            hw = " [hardware]" if entry.hardware else ""
            ex = ", ".join(f'"{e}"' for e in entry.examples[:2])
            lines.append(f"• {entry.title}{hw}: {entry.description}")
            if ex:
                lines.append(f"  e.g. {ex}")
        lines.append("")

    lines.append(
        "Ask anything else in plain language — Atria uses Gemini when an API key is set."
    )
    return "\n".join(lines).strip()


def all_help_entries() -> list[HelpEntry]:
    out: list[HelpEntry] = []
    for _, entries in HELP_SECTIONS:
        out.extend(entries)
    return out
