"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Any, Optional

from rich.markup import escape

logger = logging.getLogger(__name__)

VOICE_EXIT = object()

# Replies are spoken sentence by sentence so playback can start after the
# first chunk is synthesized instead of after the whole reply. Fragments
# shorter than this are merged into the next one ("Sim, senhor." alone would
# add a pause for little gain).
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")
_MIN_SPEECH_CHUNK_CHARS = 20

# Only local backends are warmed up with a real synthesis: for API backends
# it would be a billed request the user never asked for.
_LOCAL_TTS_BACKENDS = frozenset({"kokoro"})

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
        # Held while a backend is resolved or warmed up, so a turn that starts
        # mid warm-up waits for the loaded model instead of loading a second copy.
        self._stt_lock = threading.RLock()
        self._tts_lock = threading.RLock()

    def warm_up(self) -> None:
        """Load the STT and TTS models in a background thread.

        Both load lazily on first use, which on CPU adds tens of seconds to
        the first voice turn. Failures are only logged here; the real call
        reports them to the user.
        """
        threading.Thread(target=self._warm_up, name="voice-warmup", daemon=True).start()

    def _warm_up(self) -> None:
        with self._stt_lock:
            try:
                ensure_model = getattr(self.get_stt_backend(), "_ensure_model", None)
                if callable(ensure_model):
                    ensure_model()
            except Exception:
                logger.debug("STT warm-up failed", exc_info=True)
        with self._tts_lock:
            try:
                backend = self.get_tts_backend()
                if getattr(backend, "backend_id", "") in _LOCAL_TTS_BACKENDS:
                    # A short synthesis also loads the language pipeline and
                    # voice tensor, not just the shared model.
                    backend.synthesize("Ok.", **self.synth_kwargs_for(backend))
            except Exception:
                logger.debug("TTS warm-up failed", exc_info=True)

    def get_stt_backend(self) -> Any:
        """Resolve and health-check STT once, then reuse the loaded backend."""
        with self._stt_lock:
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
        with self._tts_lock:
            if self._tts_backend is not None:
                return self._tts_backend

            from openjarvis.speech._tts_discovery import get_tts_backend

            preferred, _, _ = self.get_voice_preferences()
            self._tts_backend = get_tts_backend(
                preferred, attempted=self._tts_attempted
            )
            return self._tts_backend

    def synth_kwargs_for(self, backend: Any, console: Any = None) -> dict[str, Any]:
        """Keyword arguments for ``backend.synthesize`` from the voice config."""
        voice_id, speed = self.voice_for_backend(backend, console)
        synth_kwargs: dict[str, Any] = {"output_format": "wav", "speed": speed}
        if voice_id:
            synth_kwargs["voice_id"] = voice_id
        return synth_kwargs

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

    chunks = _split_for_speech(text)
    while (backend := active_session.get_tts_backend()) is not None:
        try:
            synth_kwargs = active_session.synth_kwargs_for(backend, console)
            # Only the first chunk decides whether this backend works; once it
            # is playing, falling back would restart the reply from the top.
            first = backend.synthesize(chunks[0], **synth_kwargs)
        except Exception as exc:
            console.print(
                f"[dim yellow]Voice backend "
                f"{getattr(backend, 'backend_id', '?')!r} failed: "
                f"{_terminal_safe_text(exc)}[/dim yellow]"
            )
            active_session.discard_tts_backend()
            continue
        _play_pipelined(backend, first, chunks[1:], synth_kwargs, console, play_wav)
        return

    console.print(
        "[dim yellow]No TTS backend available — install kokoro: "
        "pip install kokoro[/dim yellow]"
    )


def _split_for_speech(text: str) -> list[str]:
    """Split a reply into sentence-sized chunks for incremental playback."""
    chunks: list[str] = []
    pending = ""
    for sentence in _SENTENCE_BREAK.split(text.strip()):
        pending = f"{pending} {sentence}".strip()
        if len(pending) >= _MIN_SPEECH_CHUNK_CHARS:
            chunks.append(pending)
            pending = ""
    if pending:
        chunks.append(pending)
    return chunks or [text]


def _play_pipelined(
    backend: Any,
    first: Any,
    rest: list[str],
    synth_kwargs: dict[str, Any],
    console: Any,
    play_wav: Any,
) -> None:
    """Play ``first`` while the remaining chunks are synthesized in order."""
    results: queue.Queue[Any] = queue.Queue()

    def synthesize_rest() -> None:
        try:
            for chunk in rest:
                results.put(backend.synthesize(chunk, **synth_kwargs))
        except Exception as exc:
            results.put(exc)

    if rest:
        threading.Thread(target=synthesize_rest, name="voice-tts", daemon=True).start()

    try:
        result = first
        for remaining in range(len(rest), -1, -1):
            if isinstance(result, Exception):
                console.print(
                    f"[dim yellow]Voice playback stopped: "
                    f"{_terminal_safe_text(result)}[/dim yellow]"
                )
                return
            if result.audio:
                play_wav(result.audio, sample_rate=result.sample_rate)
            if remaining:
                result = results.get()
    except Exception as exc:
        console.print(
            "[dim yellow]Voice playback failed: "
            f"{_terminal_safe_text(exc)}[/dim yellow]"
        )


__all__ = ["VOICE_EXIT", "VoiceSession", "read_voice_input", "record_voice", "speak"]
