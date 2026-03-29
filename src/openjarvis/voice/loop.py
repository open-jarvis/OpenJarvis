"""Main voice assistant loop.

State machine
─────────────
  IDLE
    └─(wake word)──► LISTENING
                        │
                        ├─(silence after speech)──► THINKING
                        │                               │
                        │                        (response ready)
                        │                               ▼
                        │                           SPEAKING
                        │                               │
                        ├─(wake word during SPEAKING)───┘  ← interrupts TTS,
                        │                                     jumps back to LISTENING
                        └─(timeout / no speech)──► IDLE

Usage
─────
    from openjarvis.voice.loop import VoiceLoop
    loop = VoiceLoop(engine=engine, model="qwen3:0.6b")
    loop.run()   # blocks; Ctrl-C to quit
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Optional

from rich.console import Console
from rich.text import Text

from openjarvis.core.types import Message, Role
from openjarvis.voice._stubs import VoiceState
from openjarvis.voice.listener import MicrophoneListener
from openjarvis.voice.speech_filter import is_detail_request, prepare_for_speech
from openjarvis.voice.tts import TTSBackend, build_tts
from openjarvis.voice.wake_word import WakeWordListener

logger = logging.getLogger(__name__)


# ── display helpers ────────────────────────────────────────────────────────────

_STATE_LABEL = {
    VoiceState.IDLE: ("[dim]● idle[/dim]", "dim"),
    VoiceState.WAKE_DETECTED: ("[bold cyan]◉ wake![/bold cyan]", "cyan"),
    VoiceState.LISTENING: ("[bold green]◎ listening[/bold green]", "green"),
    VoiceState.THINKING: ("[bold yellow]◌ thinking[/bold yellow]", "yellow"),
    VoiceState.SPEAKING: ("[bold blue]◉ speaking[/bold blue]", "blue"),
}

_BANNER = """
  [bold white]J A R V I S[/bold white]  [dim]— always on[/dim]

  [dim]wake word:[/dim]  [cyan]"Hey Jarvis"[/cyan]
  [dim]interrupt:[/dim]  say the wake word again while it's speaking
  [dim]quit:[/dim]       Ctrl-C
"""


class VoiceLoop:
    """Orchestrates wake word → STT → LLM → TTS pipeline."""

    def __init__(
        self,
        engine,
        model: str,
        *,
        tts: Optional[TTSBackend] = None,
        system_prompt: Optional[str] = None,
        history_limit: int = 20,
        listen_timeout: float = 8.0,
        energy_threshold: int = 300,
    ) -> None:
        self._engine = engine
        self._model = model
        self._tts = tts or build_tts()
        self._system_prompt = system_prompt or _default_system_prompt()
        self._history_limit = history_limit
        self._listen_timeout = listen_timeout
        self._energy_threshold = energy_threshold

        self._console = Console()
        self._state = VoiceState.IDLE
        self._history: list[Message] = [
            Message(role=Role.SYSTEM, content=self._system_prompt)
        ]

        # STT backend (faster-whisper, lazy loaded)
        self._stt = None

        # Components (created on run())
        self._wake_listener: Optional[WakeWordListener] = None
        self._mic: Optional[MicrophoneListener] = None

        # Interrupt flag: set when a new wake fires mid-speech
        self._interrupt = threading.Event()

    # ── public ─────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block and run the voice loop until Ctrl-C."""
        self._console.print(_BANNER)
        self._setup()

        try:
            while True:
                self._tick()
        except KeyboardInterrupt:
            self._console.print("\n[dim]Shutting down. Later.[/dim]")
        finally:
            self._teardown()

    # ── setup / teardown ───────────────────────────────────────────────────────

    def _setup(self) -> None:
        self._mic = MicrophoneListener(energy_threshold=self._energy_threshold)
        self._wake_listener = WakeWordListener()
        self._wake_listener.start()
        self._set_state(VoiceState.IDLE)
        self._console.print(self._status_line())

    def _teardown(self) -> None:
        if self._wake_listener:
            self._wake_listener.stop()
        if self._tts:
            self._tts.stop()

    # ── main tick ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Single iteration of the state machine."""

        # ── IDLE: wait for wake word ──────────────────────────────────────────
        if self._state == VoiceState.IDLE:
            result = self._wake_listener.wait_for_wake(timeout=1.0)
            if result:
                self._wake_listener.drain()
                self._set_state(VoiceState.LISTENING)
                self._handle_listening()
            return

        # States other than IDLE are driven by _handle_* methods; if we
        # somehow land here in a non-IDLE state reset to IDLE.
        self._set_state(VoiceState.IDLE)

    # ── state handlers ─────────────────────────────────────────────────────────

    def _handle_listening(self) -> None:
        self._console.print(self._status_line())
        self._interrupt.clear()

        # Start a background thread watching for another wake word (interruption)
        interrupt_thread = threading.Thread(
            target=self._watch_for_interrupt, daemon=True
        )
        interrupt_thread.start()

        audio_bytes = self._mic.record_utterance()

        if self._interrupt.is_set() or audio_bytes is None:
            self._set_state(VoiceState.IDLE)
            self._console.print(self._status_line())
            return

        # ── THINKING ─────────────────────────────────────────────────────────
        self._set_state(VoiceState.THINKING)
        self._console.print(self._status_line())

        transcription = self._transcribe(audio_bytes)
        if not transcription:
            self._console.print("[dim]  (nothing heard)[/dim]")
            self._set_state(VoiceState.IDLE)
            self._console.print(self._status_line())
            return

        self._console.print(f"\n  [bold]You:[/bold] {transcription}")

        response = self._generate(transcription)
        if not response:
            self._set_state(VoiceState.IDLE)
            self._console.print(self._status_line())
            return

        full_response = is_detail_request(transcription)
        spoken = prepare_for_speech(response, full_response=full_response)

        self._console.print(f"  [bold cyan]Jarvis:[/bold cyan] {spoken}\n")

        # ── SPEAKING ─────────────────────────────────────────────────────────
        self._set_state(VoiceState.SPEAKING)
        self._console.print(self._status_line())

        tts_thread = threading.Thread(
            target=self._speak_async, args=(spoken,), daemon=True
        )
        tts_thread.start()

        # While speaking, watch for interrupt
        while tts_thread.is_alive():
            if self._interrupt.is_set():
                self._tts.stop()
                break
            time.sleep(0.05)

        tts_thread.join(timeout=1.0)

        if self._interrupt.is_set():
            # Jump straight back to listening for the interrupted utterance
            self._interrupt.clear()
            self._set_state(VoiceState.LISTENING)
            self._wake_listener.drain()
            self._handle_listening()
        else:
            self._set_state(VoiceState.IDLE)
            self._console.print(self._status_line())

    def _watch_for_interrupt(self) -> None:
        """Background: fires _interrupt if wake word detected."""
        result = self._wake_listener.wait_for_wake(timeout=self._listen_timeout + 30)
        if result:
            self._interrupt.set()
            self._mic.cancel()

    def _speak_async(self, text: str) -> None:
        try:
            self._tts.speak(text)
        except Exception as exc:
            logger.warning("TTS error: %s", exc)

    # ── STT ────────────────────────────────────────────────────────────────────

    def _transcribe(self, audio_bytes: bytes) -> Optional[str]:
        try:
            backend = self._get_stt()
            result = backend.transcribe(audio_bytes, format="wav")
            return result.text.strip() or None
        except Exception as exc:
            logger.warning("STT error: %s", exc)
            return None

    def _get_stt(self):
        if self._stt is None:
            from openjarvis.speech.faster_whisper import FasterWhisperBackend
            self._stt = FasterWhisperBackend(model_size="base", device="auto", compute_type="int8")
        return self._stt

    # ── LLM ────────────────────────────────────────────────────────────────────

    def _generate(self, user_text: str) -> Optional[str]:
        self._history.append(Message(role=Role.USER, content=user_text))
        # Keep history bounded
        if len(self._history) > self._history_limit + 1:
            self._history = [self._history[0]] + self._history[-(self._history_limit):]
        try:
            result = self._engine.generate(self._history, model=self._model)
            content = (
                result.get("content", "") if isinstance(result, dict) else str(result)
            )
            self._history.append(Message(role=Role.ASSISTANT, content=content))
            return content or None
        except Exception as exc:
            logger.warning("LLM error: %s", exc)
            return None

    # ── helpers ────────────────────────────────────────────────────────────────

    def _set_state(self, state: VoiceState) -> None:
        self._state = state

    def _status_line(self) -> str:
        label, _ = _STATE_LABEL.get(self._state, ("[dim]unknown[/dim]", "dim"))
        return f"  {label}"


# ── default personality ────────────────────────────────────────────────────────

def _default_system_prompt() -> str:
    """Load soul.md if present, else return a built-in personality."""
    import pathlib

    base = pathlib.Path("~/.openjarvis").expanduser()
    for name in ("SOUL.md", "soul.md"):
        soul = base / name
        if soul.exists():
            return soul.read_text()

    return (
        "You are Jarvis.\n\n"
        "Speak like a sharp, casual assistant with dry humor. "
        "Keep responses short and natural — like talking to someone you know. "
        "Avoid formal phrases like 'Here are…' or 'According to…'. "
        "Give the answer directly, optionally add a quick remark, then stop. "
        "Only go into detail if the user asks. "
        "Never start with 'Certainly', 'Of course', or 'Great question'."
    )


__all__ = ["VoiceLoop"]
