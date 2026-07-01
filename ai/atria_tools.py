"""Gemini function declarations and mapping to dashboard intents."""

from __future__ import annotations

from typing import Any

from google.genai import types

from ai.help_catalog import all_help_entries
from ai.intents import Intent

REPORT_TOOL_NAMES = frozenset(
    {
        "report_beam_waist",
        "report_efficiency",
        "report_wavelength",
    }
)

HARDWARE_TOOL_NAMES = frozenset(
    {
        "jog_stage",
        "go_safe_home",
        "mark_safe_home",
        "connect_stage",
        "run_wavelength_scan",
    }
)

TILE_IDS = (
    "camera",
    "roi_snapshot",
    "beam",
    "efficiency",
    "status",
    "trends",
    "stage",
    "piezo",
    "fft",
    "tasks",
    "atria",
    "workspace",
)


def _schema_object(**properties: types.Schema) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties,
    )


def _optional_nm_schema() -> types.Schema:
    return types.Schema(type=types.Type.NUMBER, description="Wavelength in nanometres")


def gemini_function_declarations() -> list[types.FunctionDeclaration]:
    """Build Gemini tool declarations from the help catalog plus extras."""
    decls: list[types.FunctionDeclaration] = []

    for entry in all_help_entries():
        params: types.Schema | None = None
        if entry.intent == "set_wavelength_nominal":
            params = _schema_object(nm=_optional_nm_schema())
        elif entry.intent == "set_wavelength":
            params = _schema_object(
                nm=types.Schema(
                    type=types.Type.NUMBER,
                    description="Wavelength in nanometres",
                )
            )
        elif entry.intent == "jog_stage":
            params = _schema_object(
                delta_mm=types.Schema(
                    type=types.Type.NUMBER,
                    description="Signed jog distance in millimetres",
                )
            )
        elif entry.intent == "toggle_live_feed":
            params = _schema_object(
                active=types.Schema(
                    type=types.Type.BOOLEAN,
                    description="True to start live feed, false to stop",
                )
            )
        elif entry.intent == "load_scan_csv":
            params = _schema_object(
                path=types.Schema(
                    type=types.Type.STRING,
                    description="Optional full path to a scan CSV file",
                )
            )
        elif entry.intent == "show_tile":
            params = _schema_object(
                tile_id=types.Schema(
                    type=types.Type.STRING,
                    description=f"Tile id: one of {', '.join(TILE_IDS)}",
                    enum=list(TILE_IDS),
                )
            )
        elif entry.intent == "run_simulation":
            params = _schema_object(
                duration_sec=types.Schema(
                    type=types.Type.NUMBER,
                    description="Run length in seconds (10, 20, 30, etc.). Defaults to 20 s.",
                )
            )

        decls.append(
            types.FunctionDeclaration(
                name=entry.intent,
                description=f"{entry.title}: {entry.description}",
                parameters=params,
            )
        )

    return decls


def intent_from_tool_call(name: str, args: dict[str, Any] | None) -> Intent | None:
    """Convert a Gemini function call into an ``Intent`` for the dashboard."""
    args = dict(args or {})
    known = {e.intent for e in all_help_entries()}
    if name not in known:
        return None

    if name == "set_wavelength_nominal":
        params: dict[str, Any] = {}
        if "nm" in args and args["nm"] is not None:
            params["nm"] = float(args["nm"])
        return Intent(name, params, f"tool:{name}")

    if name == "set_wavelength":
        nm = args.get("nm")
        if nm is None:
            return None
        return Intent(name, {"nm": float(nm)}, f"tool:{name}")

    if name == "jog_stage":
        delta = args.get("delta_mm", 0.1)
        return Intent(name, {"delta_mm": float(delta)}, f"tool:{name}")

    if name == "toggle_live_feed":
        active = args.get("active", True)
        return Intent(name, {"active": bool(active)}, f"tool:{name}")

    if name == "load_scan_csv":
        params_csv: dict[str, Any] = {}
        path = args.get("path")
        if path:
            params_csv["path"] = str(path)
        return Intent(name, params_csv, f"tool:{name}")

    if name == "show_tile":
        tile_id = str(args.get("tile_id", "camera"))
        if tile_id not in TILE_IDS:
            tile_id = "camera"
        return Intent(name, {"tile_id": tile_id}, f"tool:{name}")

    if name == "run_simulation":
        params_sim: dict[str, Any] = {}
        dur = args.get("duration_sec")
        if dur is not None:
            params_sim["duration_sec"] = float(dur)
        return Intent(name, params_sim, f"tool:{name}")

    return Intent(name, {}, f"tool:{name}")
