"""Map natural-language chat to dashboard backend actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_SIMULATION_DURATION_SEC = 20.0


@dataclass
class Intent:
    """Structured command parsed from user text for the dashboard executor."""

    name: str
    params: dict[str, Any]
    raw: str


# Tile ids for "open/show …" commands.
_TILE_ALIASES: tuple[tuple[str, str], ...] = (
    (r"\b(live camera|camera feed|camera)\b", "camera"),
    (r"\b(roi snap|roi snapshot|snapshot)\b", "roi_snapshot"),
    (r"\b(3d beam|beam profile|beam plot)\b", "beam"),
    (r"\b(efficiency|beam efficiency|eta meter)\b", "efficiency"),
    (r"\b(system status|hardware status|status)\b", "status"),
    (r"\b(alignment trends|trends)\b", "trends"),
    (r"\b(stage control|stage|k-cube|kcube)\b", "stage"),
    (r"\b(piezo|piezo optimizer)\b", "piezo"),
    (r"\b(fft|coupling fft|vibration|spectrum)\b", "fft"),
    (r"\b(task manager|tasks)\b", "tasks"),
    (r"\b(atria|chat)\b", "atria"),
    (r"\b(workspace)\b", "workspace"),
)


def _parse_nm(text: str) -> float | None:
    """Extract a wavelength in nanometres from text like ``532 nm``."""
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*nm", text)
    if m:
        return float(m.group(1))
    return None


def parse_simulation_duration(text: str) -> float | None:
    """Parse run length from phrases like ``20s``, ``30 seconds``, or ``1 minute``."""
    t = text.strip().lower()
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds)\b", t)
    if m:
        return float(m.group(1))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes)\b", t)
    if m:
        return float(m.group(1)) * 60.0
    return None


def parse_intent(text: str) -> Intent | None:
    """Return the best-matching intent for ``text``, or ``None`` if empty."""
    t = text.strip().lower()
    if not t:
        return None

    if re.match(r"^help(\s+.*)?$", t):
        topic = text.strip()[4:].strip() if len(text.strip()) > 4 else ""
        return Intent("help", {"topic": topic}, text)

    if re.search(r"\b(stop|end)\b.*\bsimulation\b", t) or t in ("stop simulation", "end simulation"):
        return Intent("stop_simulation", {}, text)

    if re.search(r"\b(run|start)\b.*\bsimulation\b", t) or t in (
        "run simulation",
        "start simulation",
        "simulate",
    ) or re.search(r"\bsimulate\b", t):
        params: dict[str, Any] = {}
        dur = parse_simulation_duration(text)
        if dur is not None:
            params["duration_sec"] = dur
        return Intent("run_simulation", params, text)

    if re.search(r"\b(beam waist|beam size|spot size|1/e|tell me the beam)\b", t):
        return Intent("report_beam_waist", {}, text)

    if re.search(r"\b(efficiency|coupling|eta)\b", t) and "wavelength" not in t and "lambda" not in t:
        return Intent("report_efficiency", {}, text)

    # --- Wavelength set / source selection (before generic wavelength report) ---
    explicit_nm = _parse_nm(t)
    if re.search(
        r"\b(set|update|change|use)\b.*\b(wavelength|lambda)\b.*\b(to|=)\b",
        t,
    ) or re.search(r"\b(wavelength|lambda)\b.*\b(to|=)\s*[0-9]", t):
        if explicit_nm is not None:
            if re.search(r"\b(nominal|diode|label|catalog|rated|nameplate)\b", t):
                return Intent(
                    "set_wavelength_nominal",
                    {"nm": explicit_nm},
                    text,
                )
            return Intent("set_wavelength", {"nm": explicit_nm}, text)

    if re.search(
        r"\b(use|switch to|set)\b.*\b(measured|scan|interferometer|fft|recovered)\b",
        t,
    ) and re.search(r"\b(wavelength|lambda|λ)\b", t):
        return Intent("set_wavelength_measured", {}, text)

    if re.search(
        r"\b(use|switch to|set)\b.*\b(nominal|diode|label|catalog|rated|nameplate)\b",
        t,
    ) and re.search(r"\b(wavelength|lambda|λ)\b", t):
        params_nom: dict[str, Any] = {}
        if explicit_nm is not None:
            params_nom["nm"] = explicit_nm
        return Intent("set_wavelength_nominal", params_nom, text)

    if re.search(
        r"\b(update|set|change)\b.*\b(wavelength|lambda|λ)\b.*\bto\b.*\b(measured|scan)\b",
        t,
    ):
        return Intent("set_wavelength_measured", {}, text)

    if re.search(
        r"\b(update|set|change)\b.*\b(wavelength|lambda|λ)\b.*\bto\b.*\b(nominal|diode|label|catalog)\b",
        t,
    ):
        params: dict[str, Any] = {}
        if explicit_nm is not None:
            params["nm"] = explicit_nm
        return Intent("set_wavelength_nominal", params, text)

    if re.search(r"\b(wavelength|lambda|λ)\b.*\b(measured|from scan|last scan|scan result)\b", t):
        return Intent("set_wavelength_measured", {}, text)

    if re.search(r"\b(determine the wavelength|what is the wavelength)\b", t):
        return Intent("report_wavelength", {}, text)

    if re.search(r"\b(what is|report|tell me)\b.*\b(wavelength|lambda)\b", t) and not re.search(
        r"\b(scan|set|load|open|start|stop|connect|jog)\b", t
    ):
        return Intent("report_wavelength", {}, text)

    # --- Bench actions (before jog/capture so phrases stay specific) ---
    if re.search(r"\b(stop|end|turn off)\b.*\b(fft|vibration|spectrum)\b", t):
        return Intent("stop_fft_monitor", {}, text)

    if re.search(r"\b(start|run|monitor)\b.*\b(fft|vibration|spectrum)\b", t):
        return Intent("start_fft_monitor", {}, text)

    if re.search(r"\b(stop|end|turn off)\b.*\b(live|feed)\b", t):
        return Intent("toggle_live_feed", {"active": False}, text)

    if re.search(r"\b(start|begin|turn on)\b.*\b(live|feed)\b", t):
        return Intent("toggle_live_feed", {"active": True}, text)

    if re.search(r"\b(snap|capture)\b.*\b(frame|image|snapshot)\b", t) or t in (
        "snap",
        "snap frame",
    ):
        return Intent("snap_frame", {}, text)

    if re.search(r"\banalyze\b.*\b(beam|snapshot|roi)\b", t):
        return Intent("analyze_beam", {}, text)

    if (
        re.search(r"\b(scan|run)\b.*\b(wavelength|lambda|λ|fringes?)\b", t)
        or re.search(r"\b(k-cube|kcube)\b.*\bscan\b", t)
        or re.search(r"\bscan wavelength\b", t)
    ):
        return Intent("run_wavelength_scan", {}, text)

    if re.search(r"\b(calibrate|set)\b.*\b(efficiency|eta|η|baseline)\b", t):
        return Intent("calibrate_efficiency", {}, text)

    if re.search(r"\b(load|import|open)\b.*\b(scan\s*)?csv\b", t):
        path_m = re.search(r"([a-z]:\\[^\s]+|/[^\s]+|\S+\.csv)", text.strip(), re.I)
        params_csv: dict[str, Any] = {}
        if path_m:
            params_csv["path"] = path_m.group(1)
        return Intent("load_scan_csv", params_csv, text)

    if re.search(r"\b(connect|link)\b.*\b(stage|kcube|k-cube)\b", t) or t == "connect stage":
        return Intent("connect_stage", {}, text)

    if re.search(r"\b(open|show|display)\b", t):
        for pattern, tile_id in _TILE_ALIASES:
            if re.search(pattern, t):
                return Intent("show_tile", {"tile_id": tile_id}, text)

    jog = re.search(
        r"jog\s+(?:stage\s+)?(?:(forward|backward|back|rev(?:erse)?)\s+)?([0-9.]+)\s*(mm|um|µm)?",
        t,
    )
    if jog or re.search(r"\bjog\b", t):
        direction = (jog.group(1) if jog else None) or "forward"
        amount = float(jog.group(2)) if jog and jog.group(2) else 0.1
        unit = (jog.group(3) if jog else "mm") or "mm"
        if unit in ("um", "µm"):
            amount /= 1000.0
        if direction in ("back", "backward", "rev", "reverse"):
            amount = -amount
        return Intent("jog_stage", {"delta_mm": amount}, text)

    if re.search(r"\bsafe home\b", t):
        return Intent("go_safe_home", {}, text)

    if re.search(r"\b(save safe home|mark safe home)\b", t):
        return Intent("mark_safe_home", {}, text)

    if re.search(r"\b(capture roi|save roi)\b", t):
        return Intent("capture_roi", {}, text)

    return Intent("freeform", {"message": text}, text)
