"""Atria natural-language lab assistant with Gemini chat, tools, and local fallbacks."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot, QMetaObject, Qt

from ai.atria_tools import (
    gemini_function_declarations,
    intent_from_tool_call,
)
from ai.help_catalog import format_help_text
from ai.intents import DEFAULT_SIMULATION_DURATION_SEC, Intent, parse_intent
from config import GEMINI_API_KEY, GEMINI_MODEL
from core.laser_wavelength import wavelength_mode_label

MAX_CHAT_TURNS = 24
MAX_TOOL_ROUNDS = 6

IntentExecutor = Callable[[Intent, bool], str]


def time_greeting() -> str:
    """Morning / afternoon / evening greeting for the composer placeholder."""
    hour = datetime.now().hour
    if hour < 12:
        label = "Good morning."
    elif hour < 17:
        label = "Good afternoon."
    else:
        label = "Good evening."
    return f"{label} Message Atria — type help for commands."


def _build_system_instruction() -> str:
    return (
        "You are Atria, the alignment assistant for an interferometer lab console. "
        "Be concise, calm, and precise. Use the provided tools to read telemetry and "
        "run bench actions when the user asks. "
        "Telemetry context uses nominal = diode label, measured = scan/manual. "
        "For stage moves and wavelength scans, call the tool only when the user clearly "
        "wants the action. If hardware control may be disabled, still call the tool and "
        "explain the result. "
        "For help, tell users they can type help or ask you to list commands. "
        "Bench simulation via run_simulation defaults to 20 seconds unless the user "
        "specifies another duration (10s, 30s, etc.); summarize metrics when it ends. "
        "Combine tool results into a natural reply."
    )


def _history_to_contents(history: list[dict[str, str]]) -> list[Any]:
    from google.genai import types

    contents: list[Any] = []
    for turn in history[-MAX_CHAT_TURNS:]:
        role = turn.get("role", "user")
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        gemini_role = "user" if role == "user" else "model"
        contents.append(
            types.Content(role=gemini_role, parts=[types.Part(text=text)])
        )
    return contents


def run_gemini_turn(
    user_message: str,
    history: list[dict[str, str]],
    telemetry_context: str,
    execute_intent: IntentExecutor,
    hardware_allowed: bool,
) -> str:
    """One conversational turn: Gemini chat with tool loop and intent execution."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    tools = [types.Tool(function_declarations=gemini_function_declarations())]
    config = types.GenerateContentConfig(
        tools=tools,
        system_instruction=_build_system_instruction(),
    )

    contents = _history_to_contents(history)
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part(text=f"Telemetry:\n{telemetry_context}\n\nUser: {user_message}")],
        )
    )

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )

        if not response.function_calls:
            text = getattr(response, "text", None)
            if text and str(text).strip():
                return str(text).strip()
            return "Done."

        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        for fc in response.function_calls:
            intent = intent_from_tool_call(fc.name, dict(fc.args or {}))
            if intent is None:
                result_text = f"Unknown tool: {fc.name}"
            else:
                result_text = execute_intent(intent, hardware_allowed)

            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result_text},
                        )
                    ],
                )
            )

    return "I ran several bench actions. Check the tiles for the latest state."


class IntentBridge(QObject):
    """Execute intents on the GUI thread from the worker thread."""

    def __init__(self, executor: IntentExecutor) -> None:
        super().__init__()
        self._executor = executor
        self._pending_intent: Intent | None = None
        self._pending_hw = False
        self._result = ""

    @Slot()
    def _run(self) -> None:
        if self._pending_intent is not None:
            self._result = self._executor(self._pending_intent, self._pending_hw)

    def run_blocking(self, intent: Intent, hardware_allowed: bool) -> str:
        self._pending_intent = intent
        self._pending_hw = hardware_allowed
        QMetaObject.invokeMethod(
            self,
            "_run",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        return self._result


class AtriaWorker(QThread):
    """Run Atria chat turns off the UI thread."""

    reply_ready = Signal(str)
    intent_ready = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._user_message = ""
        self._history: list[dict[str, str]] = []
        self._telemetry_context = ""
        self._hardware_allowed = False
        self._intent_bridge: IntentBridge | None = None
        self._local_fallback = False

    def set_intent_bridge(self, bridge: IntentBridge) -> None:
        self._intent_bridge = bridge

    def ask(
        self,
        user_message: str,
        history: list[dict[str, str]],
        telemetry_context: str,
        hardware_allowed: bool,
        local_fallback: bool = False,
    ) -> None:
        self._user_message = user_message
        self._history = list(history)
        self._telemetry_context = telemetry_context
        self._hardware_allowed = hardware_allowed
        self._local_fallback = local_fallback
        if self.isRunning():
            self.wait(30000)
        self.start()

    def run(self) -> None:
        try:
            if self._local_fallback:
                self._run_local_fallback()
                return

            if not GEMINI_API_KEY:
                self.error.emit(
                    "Atria is not configured — add your API key to .env (see .env.example)."
                )
                return

            if self._intent_bridge is None:
                self.error.emit("Atria intent bridge not initialized.")
                return

            reply = run_gemini_turn(
                self._user_message,
                self._history,
                self._telemetry_context,
                self._intent_bridge.run_blocking,
                self._hardware_allowed,
            )
            self.reply_ready.emit(reply)
        except Exception as exc:
            self.error.emit(str(exc))

    def _run_local_fallback(self) -> None:
        intent = parse_intent(self._user_message)
        if intent and intent.name != "freeform":
            self.intent_ready.emit(intent)
            return
        self.error.emit(
            "No API key — use native phrases (type help) or add GEMINI_API_KEY to .env."
        )


def format_intent_reply(intent: Intent, telemetry: dict) -> str:
    """Local responses for structured intents (no API call)."""
    if intent.name == "help":
        return format_help_text(str(intent.params.get("topic", "")))

    if intent.name == "report_beam_waist":
        w = telemetry.get("beam_waist_um")
        if w is None or w != w:
            return "Beam waist unavailable — check camera feed and beam ROI."
        return f"Beam waist (1/e² average): {w:.1f} µm."

    if intent.name == "report_efficiency":
        eta = telemetry.get("efficiency_pct")
        if eta is None:
            return "Efficiency unavailable — calibrate a reference baseline first."
        return f"Camera coupling efficiency: {eta:.1f}%."

    if intent.name == "report_wavelength":
        mode = telemetry.get("wavelength_mode", "nominal")
        lam = telemetry.get("wavelength_nm")
        nominal = telemetry.get("nominal_wavelength_nm")
        measured = telemetry.get("measured_wavelength_nm")
        parts = []
        if lam is not None:
            parts.append(
                f"Active λ ({wavelength_mode_label(mode)}): {float(lam):.2f} nm."
            )
        if nominal is not None:
            parts.append(f"Diode label: {float(nominal):.2f} nm.")
        if measured is not None:
            parts.append(f"Last measured: {float(measured):.2f} nm.")
        if not parts:
            return "No wavelength on file yet — nominal default is 520 nm (green diode)."
        return " ".join(parts)

    if intent.name == "set_wavelength_nominal":
        nm = intent.params.get("nm")
        if nm is not None:
            return f"Using diode label wavelength: {float(nm):.2f} nm."
        nominal = telemetry.get("nominal_wavelength_nm")
        if nominal is not None:
            return f"Using diode label wavelength: {float(nominal):.2f} nm."
        return "Switching active wavelength to the diode label (nominal) value."

    if intent.name == "set_wavelength_measured":
        measured = telemetry.get("measured_wavelength_nm")
        if measured is None:
            return (
                "No measured wavelength yet — run Scan λ (K-Cube) or load a scan CSV, "
                "then ask again."
            )
        return f"Using measured wavelength: {float(measured):.2f} nm."

    if intent.name == "set_wavelength":
        nm = float(intent.params.get("nm", 0))
        return f"Active wavelength set to {nm:.2f} nm (manual entry)."

    if intent.name == "jog_stage":
        d = intent.params.get("delta_mm", 0.0)
        return f"Jog request: {d:+.4f} mm (requires hardware permission)."

    if intent.name == "go_safe_home":
        return "Moving to safe home (requires hardware permission)."

    if intent.name == "mark_safe_home":
        return "Saving current stage position as safe home."

    if intent.name == "capture_roi":
        return "Saving the current ROI to config."

    if intent.name == "toggle_live_feed":
        active = intent.params.get("active", True)
        return "Starting live camera feed." if active else "Stopping live camera feed."

    if intent.name == "snap_frame":
        return "Snapping a frame to ROI Snap Shot."

    if intent.name == "analyze_beam":
        return "Analyzing beam on the ROI snapshot (or live frame)."

    if intent.name == "run_wavelength_scan":
        return "Starting K-Cube fringe scan for wavelength recovery (requires hardware permission)."

    if intent.name == "calibrate_efficiency":
        return "Calibrating η baseline from the current fringe ROI mean."

    if intent.name == "load_scan_csv":
        path = intent.params.get("path")
        if path:
            return f"Loading scan CSV: {path}"
        return "Opening scan CSV picker to recover wavelength."

    if intent.name == "connect_stage":
        return "Connecting K-Cube stage (requires hardware permission)."

    if intent.name == "show_tile":
        tid = intent.params.get("tile_id", "camera")
        return f"Opening {tid.replace('_', ' ')} tile."

    if intent.name == "start_fft_monitor":
        return "Starting live FFT monitor on fringe ROI intensity."

    if intent.name == "stop_fft_monitor":
        return "Stopping FFT monitor."

    if intent.name == "run_simulation":
        dur = intent.params.get("duration_sec")
        if dur is None:
            dur = DEFAULT_SIMULATION_DURATION_SEC
        return (
            f"Starting {float(dur):.0f} s bench simulation "
            "(mock camera, beam, η, trends, FFT). I'll summarize results when it finishes."
        )

    if intent.name == "stop_simulation":
        return "Stopping bench simulation."

    return intent.raw
