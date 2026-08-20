"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

from typing import Any, Optional

from rich.markup import escape

VOICE_EXIT = object()
_TTS_BACKEND_ORDER = ("kokoro", "openai_tts", "cartesia")


def _terminal_safe_text(value: object) -> str:
    """Remove terminal controls and escape Rich markup from dynamic text."""
    printable = "".join(
        char for char in str(value) if char in ("\n", "\t") or char.isprintable()
    )
    return escape(printable)


class VoiceSession:
    """Cache healthy speech backends for one interactive chat session."""

    def __init__(self, config: object | None = None) -> None:
        self._config = config
        self._stt_resolved = False
        self._stt_backend: Any = None
        self._tts_backend: Any = None
        self._tts_attempted: set[str] = set()

    def get_stt_backend(self) -> Any:
        """Resolve and health-check STT once, then reuse the loaded backend."""
        if not self._stt_resolved:
            from openjarvis.core.config import load_config
            from openjarvis.speech._discovery import get_speech_backend

            config = self._config if self._config is not None else load_config()
            self._stt_backend = get_speech_backend(config)
            self._stt_resolved = True
        return self._stt_backend

    def get_tts_backend(self) -> Any:
        """Return a cached healthy TTS backend, falling through once per key."""
        if self._tts_backend is not None:
            return self._tts_backend

        # Import triggers built-in backend registration only when voice output
        # is actually requested.
        import openjarvis.speech  # noqa: F401
        from openjarvis.core.registry import TTSRegistry

        for key in _TTS_BACKEND_ORDER:
            if key in self._tts_attempted:
                continue
            self._tts_attempted.add(key)
            if not TTSRegistry.contains(key):
                continue
            try:
                candidate = TTSRegistry.get(key)()
                if candidate.health():
                    self._tts_backend = candidate
                    return candidate
            except Exception:
                continue
        return None

    def discard_tts_backend(self) -> None:
        """Forget a backend that failed synthesis and allow the next fallback."""
        self._tts_backend = None


def read_voice_input(console: Any, session: VoiceSession) -> Optional[str] | object:
    """Accept a typed command/message, or record after an empty submission."""
    try:
        typed = input("You> [type, or press Enter to speak] ")
    except (EOFError, KeyboardInterrupt):
        return VOICE_EXIT
    typed = typed.strip()
    return typed if typed else record_voice(console, session)


def record_voice(
    console: Any,
    session: VoiceSession | None = None,
) -> Optional[str] | object:
    """Record from mic, transcribe, and return text or a loop sentinel."""
    from openjarvis.speech.voice_io import record_until_silence

    active_session = session or VoiceSession()
    backend = active_session.get_stt_backend()
    if backend is None:
        console.print(
            "[red]No speech-to-text backend available. "
            "Install the voice dependencies with: "
            "pip install 'OpenJarvis[speech]', or configure a healthy "
            "OpenAI/Deepgram backend.[/red]"
        )
        return VOICE_EXIT

    console.print("[dim cyan]Listening… (speak now, stops on silence)[/dim cyan]")
    try:
        audio_bytes = record_until_silence()
    except KeyboardInterrupt:
        return VOICE_EXIT
    except Exception as exc:
        # PortAudio failures are regular Exceptions (and can surface as
        # OSError), so report them without letting terminal control sequences
        # through. SystemExit deliberately continues to propagate, while
        # Ctrl-C maps to the chat loop's graceful-exit sentinel above.
        console.print(f"[red]Mic error: {_terminal_safe_text(exc)}[/red]")
        return VOICE_EXIT

    console.print("[dim]Transcribing…[/dim]")
    try:
        result = backend.transcribe(audio_bytes, format="wav")
        text = result.text.strip()
        if text:
            console.print(f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}")
            return text
        console.print("[dim]Nothing heard — try again.[/dim]")
        return None
    except Exception as exc:
        console.print(f"[red]Transcription error: {_terminal_safe_text(exc)}[/red]")
        return None


def speak(text: str, console: Any, session: VoiceSession | None = None) -> None:
    """Synthesize and play text, reusing a healthy backend for the session."""
    from openjarvis.speech.voice_io import play_wav

    active_session = session or VoiceSession()
    while (backend := active_session.get_tts_backend()) is not None:
        try:
            result = backend.synthesize(text, output_format="wav")
            if result.audio:
                play_wav(result.audio, sample_rate=result.sample_rate)
            return
        except Exception:
            active_session.discard_tts_backend()

    console.print(
        "[dim yellow]No TTS backend available — install kokoro: "
        "pip install kokoro[/dim yellow]"
    )


__all__ = ["VOICE_EXIT", "VoiceSession", "read_voice_input", "record_voice", "speak"]
