"""Atria command terminal with scrollable history and a fixed bottom composer."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QVBoxLayout,
    QTextEdit,
    QHBoxLayout,
    QCheckBox,
    QLabel,
    QSizePolicy,
    QWidget,
    QPlainTextEdit,
    QScrollArea,
    QTextBrowser,
    QFrame,
)

from gui.glass_panel import GlassPanel, PentagonButton
from gui.neon_theme import NEON_CYAN, NEON_PINK, NEON_PURPLE
from gui.typography import hint_style, primary_style, section_style, TEXT_MUTED, TEXT_PRIMARY
from ai.atria_agent import AtriaWorker, format_intent_reply, time_greeting, IntentBridge
from ai.intents import Intent, parse_intent

REPORT_INTENTS = frozenset(
    {
        "report_beam_waist",
        "report_efficiency",
        "report_wavelength",
    }
)
HARDWARE_INTENTS = frozenset(
    {
        "jog_stage",
        "go_safe_home",
        "mark_safe_home",
        "connect_stage",
        "run_wavelength_scan",
    }
)

_LOG_FRAME_STYLE = (
    "background: rgba(18,8,40,0.55); "
    "border: 1px solid #f472b6; border-radius: 6px;"
)

_INPUT_STYLE = (
    f"background: rgba(18,8,40,0.72); color: {TEXT_PRIMARY};"
    f"border: 1px solid {NEON_PURPLE}; border-radius: 6px; padding: 8px;"
    "font-family: Segoe UI;"
)

_DOC_CSS = (
    "body, p, div, blockquote, li { margin: 0; padding: 0; text-align: left; "
    "white-space: normal; word-wrap: break-word; }"
    "p { margin-top: 6px; }"
    "pre, code { white-space: pre-wrap; word-wrap: break-word; font-family: Consolas; }"
)


class _ComposerInput(QPlainTextEdit):
    """Multi-line composer: Enter sends, Shift+Enter inserts a newline (Cursor-style)."""

    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _ChatMessageBlock(QTextBrowser):
    """One chat bubble: block layout, word wrap, auto height (Atria Prime / Cortex pattern)."""

    def __init__(self, role: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self._chat_message = True
        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(80)

        if role == "user":
            label, accent, body = "You", NEON_PINK, TEXT_PRIMARY
            bg = "rgba(244,114,182,0.08)"
            border_side = "border-right: 2px solid #f472b6;"
        elif role == "atria":
            label, accent, body = "Atria", NEON_CYAN, TEXT_PRIMARY
            bg = "rgba(0,245,255,0.06)"
            border_side = "border-left: 2px solid #00f5ff;"
        else:
            label, accent, body = "—", TEXT_MUTED, TEXT_MUTED
            bg = "transparent"
            border_side = ""

        safe = _escape_html(text)
        self.setStyleSheet(
            f"QTextBrowser {{ color: {body}; font-family: Segoe UI; "
            f"background: {bg}; {border_side} border-radius: 6px; padding: 8px 10px; margin: 0; }}"
        )
        doc = self.document()
        doc.setDefaultStyleSheet(_DOC_CSS)
        doc.setDocumentMargin(0)
        self.setHtml(
            f"<div><span style='color:{accent}; font-weight:bold;'>{label}</span>"
            f"<p style='color:{body};'>{safe}</p></div>"
        )
        doc.contentsChanged.connect(self._schedule_height, Qt.ConnectionType.UniqueConnection)
        QTimer.singleShot(0, self._update_height)

    def _schedule_height(self) -> None:
        QTimer.singleShot(0, self._update_height)

    def _update_height(self) -> None:
        width = self.width()
        if width < 40:
            parent = self.parentWidget()
            width = parent.width() if parent is not None else 280
        pad = 20
        self.document().setTextWidth(max(80, width - pad))
        doc_h = int(self.document().size().height())
        total = max(32, doc_h + pad)
        self.setMinimumHeight(total)
        self.setMaximumHeight(total)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_height()


class _ChatHistory(QWidget):
    """Vertical message list inside a scroll area."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._chat_scroll = True
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def append(self, role: str, text: str) -> None:
        block = _ChatMessageBlock(role, text, self)
        idx = max(0, self._layout.count() - 1)
        self._layout.insertWidget(idx, block)
        QTimer.singleShot(0, block._update_height)

    def scroll_to_bottom(self, scroll: QScrollArea) -> None:
        bar = scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


class AtriaPanel(GlassPanel):
    intent_action = Signal(object, bool)  # Intent, hardware_allowed

    def __init__(self, parent=None) -> None:
        super().__init__(parent, title="Atria")
        self._telemetry: dict = {}
        self._chat_history: list[dict[str, str]] = []
        self._worker = AtriaWorker()
        self._intent_bridge = IntentBridge(self._execute_atria_intent)
        self._worker.set_intent_bridge(self._intent_bridge)
        self._worker.reply_ready.connect(self._on_atria_reply)
        self._worker.error.connect(lambda e: self._append_atria(f"Error: {e}"))
        self._worker.intent_ready.connect(self._handle_intent)

        layout = QVBoxLayout(self)
        inset = self.content_margins()
        layout.setContentsMargins(*inset)
        layout.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.set_chat_scroll = True  # hub_tile: do not collapse minimum height
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(_LOG_FRAME_STYLE)
        self._scroll.setMinimumHeight(120)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._history = _ChatHistory()
        self._scroll.setWidget(self._history)
        layout.addWidget(self._scroll, stretch=1)

        self._composer_footer = QWidget()
        self._composer_footer.setMinimumHeight(108)
        self._composer_footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        footer_layout = QVBoxLayout(self._composer_footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)

        perm_row = QHBoxLayout()
        perm_row.setSpacing(10)
        self._hw_perm = QCheckBox("Allow hardware control")
        self._hw_perm.setStyleSheet(section_style())
        perm_row.addWidget(self._hw_perm)
        hint = QLabel("Enter to send · Shift+Enter for newline")
        hint.setStyleSheet(hint_style())
        perm_row.addWidget(hint)
        perm_row.addStretch()
        footer_layout.addLayout(perm_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = _ComposerInput()
        self._input.setMinimumHeight(44)
        self._input.setMaximumHeight(88)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refresh_placeholder()
        self._input.setStyleSheet(_INPUT_STYLE)
        self._input.send_requested.connect(self._send)

        self._send_btn = PentagonButton("Send", compact=True)
        self._send_btn.setFixedSize(76, 44)
        self._send_btn.clicked.connect(self._send)

        input_row.addWidget(self._input, stretch=1)
        input_row.addWidget(self._send_btn, stretch=0)
        footer_layout.addLayout(input_row)

        layout.addWidget(self._composer_footer, stretch=0)

        self._append_system("Atria online.")

    def _refresh_placeholder(self) -> None:
        self._input.setPlaceholderText(time_greeting())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_placeholder()

    def _telemetry_context(self) -> str:
        return str(self._telemetry)

    def _execute_atria_intent(self, intent: Intent, hardware_allowed: bool) -> str:
        reply = format_intent_reply(intent, self._telemetry)
        if intent.name in HARDWARE_INTENTS and not hardware_allowed:
            return (
                f"{reply} Hardware control is disabled — enable "
                "“Allow hardware control” to run this action."
            )
        if intent.name not in REPORT_INTENTS:
            self.intent_action.emit(intent, hardware_allowed)
        return reply

    def _on_atria_reply(self, reply: str) -> None:
        self._append_atria(reply)
        self._chat_history.append({"role": "model", "text": reply})

    def set_telemetry(self, data: dict) -> None:
        self._telemetry = dict(data)

    def _send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self._append_user(text)
        self._chat_history.append({"role": "user", "text": text})

        intent = parse_intent(text)
        if intent is None:
            intent = Intent("freeform", {"message": text}, text)

        if intent.name == "help":
            reply = format_intent_reply(intent, self._telemetry)
            self._append_atria(reply)
            self._chat_history.append({"role": "model", "text": reply})
            return

        # Any parsed bench command runs immediately (e.g. "run a 10s simulation").
        if intent.name != "freeform":
            self._handle_intent(intent)
            return

        prior_history = self._chat_history[:-1]
        use_gemini = bool(GEMINI_API_KEY)
        self._worker.ask(
            text,
            prior_history,
            self._telemetry_context(),
            self._hw_perm.isChecked(),
            local_fallback=not use_gemini,
        )

    def _handle_intent(self, intent: Intent) -> None:
        reply = format_intent_reply(intent, self._telemetry)
        self._append_atria(reply)
        self._chat_history.append({"role": "model", "text": reply})
        if intent.name in REPORT_INTENTS or intent.name == "help":
            return
        needs_hw = intent.name in HARDWARE_INTENTS
        if needs_hw and not self._hw_perm.isChecked():
            self._append_atria(
                "Enable “Allow hardware control” to move the stage or run bench scans."
            )
            return
        self.intent_action.emit(intent, self._hw_perm.isChecked())

    def _append_system(self, text: str) -> None:
        self._append_message("system", text)

    def _append_user(self, text: str) -> None:
        self._append_message("user", text)

    def post_bench_message(self, text: str) -> None:
        """Append an Atria reply from bench automation (e.g. simulation finished)."""
        self._append_atria(text)
        self._chat_history.append({"role": "model", "text": text})

    def _append_atria(self, text: str) -> None:
        self._append_message("atria", text)

    def _append_message(self, role: str, text: str) -> None:
        self._history.append(role, text)
        QTimer.singleShot(0, lambda: self._history.scroll_to_bottom(self._scroll))

    def focus_composer(self) -> None:
        self._input.setFocus()


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


