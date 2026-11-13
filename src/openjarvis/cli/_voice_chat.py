"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

import sys
from typing import Any, Optional

from rich.markup import escape

VOICE_EXIT = object()

# Backend selection is shared with the API server and lives in
# openjarvis.speech._tts_discovery. Importing that at module level would pull
# the whole speech stack -- numpy included -- into every `jarvis` invocation,
# which tests/cli/test_cli.py guards against, so these aliases resolve lazily.
_LAZY_TTS_NAMES = {
    "_TTS_BACKEND_ORDER": "TTS_BACKEND_ORDER",
    "_BACKEND_DEFAULT_VOICE": "BACKEND_DEFAULT_VOICE",
}


def __getattr__(name: str) -> Any:
    target = _LAZY_TTS_NAMES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from openjarvis.speech import _tts_discovery

    return getattr(_tts_discovery, target)


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
        self._voice_prefs: tuple[str, str, float] | None = None
        self._voice_warned: set[str] = set()

    def get_stt_backend(self) -> Any:
        """Resolve and health-check STT once, then reuse the loaded backend."""
        if not self._stt_resolved:
            from openjarvis.core.config import load_config
            from openjarvis.speech._discovery import get_speech_backend

            config = self._config if self._config is not None else load_config()
            self._stt_backend = get_speech_backend(config)
            self._stt_resolved = True
        return self._stt_backend

    def get_stt_language(self) -> Optional[str]:
        """Return the configured ``speech.language``, or None to auto-detect."""
        from openjarvis.core.config import load_config

        config = self._config if self._config is not None else load_config()
        return (getattr(config.speech, "language", "") or "").strip() or None

    def get_tts_backend(self) -> Any:
        """Return a cached healthy TTS backend, falling through once per key."""
        if self._tts_backend is not None:
            return self._tts_backend

        from openjarvis.speech._tts_discovery import get_tts_backend

        preferred, _, _ = self.get_voice_preferences()
        self._tts_backend = get_tts_backend(preferred, attempted=self._tts_attempted)
        return self._tts_backend

    def get_voice_preferences(self) -> tuple[str, str, float]:
        """Resolve configured (tts_backend, voice_id, speed), cached per session."""
        if self._voice_prefs is None:
            from openjarvis.core.config import load_config
            from openjarvis.speech._tts_discovery import voice_preferences

            config = self._config if self._config is not None else load_config()
            self._voice_prefs = voice_preferences(config)
        return self._voice_prefs

    def voice_for_backend(self, backend: Any, console: Any = None) -> tuple[str, float]:
        """Return the voice ID valid for ``backend``, plus the configured speed.

        Voice IDs are not portable across backends, so the configured
        ``speech.voice_id`` is honored only when ``backend`` is the configured
        ``speech.tts_backend``. Otherwise the fallback backend's own default is
        used and the substitution is reported once per session.
        """
        want_backend, voice_id, speed = self.get_voice_preferences()
        active = getattr(backend, "backend_id", "") or ""
        if active == want_backend:
            return voice_id, speed

        from openjarvis.speech._tts_discovery import default_voice_for

        substitute = default_voice_for(active)
        if console is not None and active not in self._voice_warned:
            self._voice_warned.add(active)
            console.print(
                f"[dim yellow]Voice: {want_backend!r} unavailable — using "
                f"{active!r} with its default voice "
                f"({substitute or 'backend default'}).[/dim yellow]"
            )
        return substitute, speed

    def discard_tts_backend(self) -> None:
        """Forget a backend that failed synthesis and allow the next fallback."""
        self._tts_backend = None


def read_voice_input(console: Any, session: VoiceSession) -> Optional[str] | object:
    """Accept a typed message, or record speech after Ctrl+Enter.

    Plain Enter submits typed text (or re-prompts when the line is empty);
    Ctrl+Enter starts microphone recording. Ctrl-C / EOF ends the session. On a
    non-interactive stdin (piped/redirected) the chord can't exist, so we fall
    back to plain line input without the raw key reader.
    """
    prompt = "You> [type, or press Ctrl+Enter to speak] "
    if not sys.stdin.isatty():
        try:
            typed = input(prompt)
        except (EOFError, KeyboardInterrupt):
            return VOICE_EXIT
        typed = typed.strip()
        return typed if typed else record_voice(console, session)

    kind, value = _prompt_line(prompt)
    if kind == "exit":
        return VOICE_EXIT
    if kind == "speak":
        return record_voice(console, session)
    return value  # typed text, or None for an empty Enter (caller re-loops)


def _prompt_line(prompt: str) -> tuple[str, Optional[str]]:
    """Read a line, telling Ctrl+Enter (speak) from Enter (submit).

    In raw mode Enter arrives as CR and Ctrl+Enter as LF (Ctrl+J); that single
    difference is what this reader relies on. Returns one of
    ``("exit", None)``, ``("speak", None)``, ``("text", line)``, ``("empty", None)``.
    """
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    except OSError:
        pass
    try:
        return (
            _prompt_line_windows() if sys.platform == "win32" else _prompt_line_posix()
        )
    except (KeyboardInterrupt, Exception):
        return ("exit", None)


def _prompt_line_windows() -> tuple[str, Optional[str]]:
    import msvcrt

    buf: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x03", "\x1a"):  # Ctrl+C / Ctrl+Z
            return ("exit", None)
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()  # discard extended-key scan code (arrows, etc.)
            continue
        if ch == "\r":  # Enter: submit text, or re-prompt when empty
            sys.stdout.write("\n")
            sys.stdout.flush()
            return ("text", "".join(buf).strip()) if buf else ("empty", None)
        if ch == "\n":  # Ctrl+Enter / Ctrl+J: speak
            return ("speak", None)
        if ch in ("\b", "\x7f"):
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if ch >= " ":
            buf.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()


def _prompt_line_posix() -> tuple[str, Optional[str]]:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf: list[str] = []
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "":
                return ("exit", None)
            if ch == "\x03":  # Ctrl+C
                return ("exit", None)
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                if ch == "\n":  # Ctrl+Enter / Ctrl+J
                    return ("speak", None)
                return ("text", "".join(buf).strip()) if buf else ("empty", None)
            if ch in ("\x7f", "\b"):
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch >= " " and ch != "\x7f":
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
        result = backend.transcribe(
            audio_bytes, format="wav", language=active_session.get_stt_language()
        )
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

    # Resolved before the loop: a bad config value must surface as a config
    # error, not be swallowed by the per-backend fallback handler below.
    try:
        active_session.get_voice_preferences()
    except Exception as exc:
        console.print(f"[red]Invalid speech config: {_terminal_safe_text(exc)}[/red]")
        return

    while (backend := active_session.get_tts_backend()) is not None:
        try:
            voice_id, speed = active_session.voice_for_backend(backend, console)
            synth_kwargs: dict[str, Any] = {"output_format": "wav", "speed": speed}
            if voice_id:
                synth_kwargs["voice_id"] = voice_id
            result = backend.synthesize(text, **synth_kwargs)
            if result.audio:
                play_wav(result.audio, sample_rate=result.sample_rate)
            return
        except Exception as exc:
            console.print(
                f"[dim yellow]Voice backend "
                f"{getattr(backend, 'backend_id', '?')!r} failed: "
                f"{_terminal_safe_text(exc)}[/dim yellow]"
            )
            active_session.discard_tts_backend()

    console.print(
        "[dim yellow]No TTS backend available — install kokoro: "
        "pip install kokoro[/dim yellow]"
    )


def make_spoken_reply(
    content: str,
    engine: Any,
    model: str,
    engine_kwargs: dict | None = None,
) -> str:
    """Condense a full reply into a short spoken version.

    The terminal keeps the full text; the speaker gets a warm one-to-three
    sentence summary that leads with a recommendation for questions. Falls back
    to the full text when the engine cannot produce a condensed form.
    """
    from openjarvis.core.types import Message, Role

    prompt = (
        "Condense the assistant reply below into a short natural spoken summary "
        "for text-to-speech: one to three sentences, under 60 words, warm and "
        "human, not a verbatim read-out. When the reply answers a question, lead "
        "with a direct recommendation. Return only the words to speak."
    )
    messages = [
        Message(role=Role.SYSTEM, content=prompt),
        Message(role=Role.USER, content=content),
    ]
    try:
        result = engine.generate(messages, model=model, **(engine_kwargs or {}))
        text = result.get("content", "") if isinstance(result, dict) else str(result)
    except Exception:
        text = ""
    return (text or "").strip() or content


__all__ = [
    "VOICE_EXIT",
    "VoiceSession",
    "read_voice_input",
    "record_voice",
    "speak",
    "make_spoken_reply",
]
