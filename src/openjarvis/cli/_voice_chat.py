"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional, Tuple

from rich.markup import escape

from openjarvis.speech.wake_word import check_wake_word, strip_wake_word

VOICE_EXIT = object()

# Provenance tags for user utterances, surfaced to the LLM before answering.
SOURCE_TYPED = "typed"
SOURCE_VOICE = "voice"
SOURCE_VOICE_WAKE = "voice_wake"


def _env_flag(name: str, default: bool) -> bool:
    """Parse an environment flag as a boolean, falling back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")

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
        self._conversation_active = False
        self._voice_muted = False

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

    # -- conversation mode ---------------------------------------------------

    @property
    def conversation_active(self) -> bool:
        """True while multi-turn listening is active (no wake word needed)."""
        return self._conversation_active

    def enter_conversation(self) -> None:
        """Start multi-turn listening after the wake word fired."""
        self._conversation_active = True

    def leave_conversation(self) -> None:
        """End multi-turn listening (exit phrase or Ctrl-C)."""
        self._conversation_active = False

    # -- voice control -------------------------------------------------------

    @property
    def voice_muted(self) -> bool:
        """True when spoken replies are suppressed (``/shutup``)."""
        return self._voice_muted

    def toggle_mute(self) -> bool:
        """Flip the spoken-reply mute and return the new state."""
        self._voice_muted = not self._voice_muted
        return self._voice_muted

    def override_voice(
        self,
        *,
        voice_id: Optional[str] = None,
        speed: Optional[float] = None,
        backend: Optional[str] = None,
    ) -> str:
        """Override TTS preferences for the rest of the session.

        Returns a human-readable description of the new settings.
        """
        from openjarvis.core.config import load_config
        from openjarvis.speech._tts_discovery import voice_preferences

        config = self._config if self._config is not None else load_config()
        base_backend, base_voice, base_speed = voice_preferences(config)
        new_backend = backend or base_backend
        new_voice = voice_id if voice_id is not None else base_voice
        new_speed = float(speed) if speed is not None else base_speed
        self._voice_prefs = (new_backend, new_voice, new_speed)
        # Re-resolve the TTS backend so the new preferences take effect.
        self._tts_backend = None
        return (
            f"voice: {new_voice or 'default'} "
            f"(backend: {new_backend}, speed: x{new_speed:g})"
        )


def read_voice_input(
    console: Any,
    session: VoiceSession,
    *,
    source: Optional[str] = None,
) -> Optional[Tuple[str, str]] | object:
    """Accept a typed command/message, or record after an empty submission.

    Returns the accepted ``(command, source)`` pair — ``source`` is the
    provenance tag for the utterance (``"typed"``, ``"voice"`` or
    ``"voice_wake"``) — the ``None`` nothing-heard sentinel, or the
    ``VOICE_EXIT`` sentinel.
    """
    try:
        typed = input("You> [type, or press Enter to speak] ")
    except (EOFError, KeyboardInterrupt):
        return VOICE_EXIT
    typed = typed.strip()
    if typed:
        return (typed, source or SOURCE_TYPED)
    # Empty submission → record voice input (which now includes wake word detection)
    return record_voice(console, session, source=source)


def _is_exit_phrase(text: str, wake_word: str) -> bool:
    """True when *text* asks to end conversation mode."""
    normalized = " ".join(text.lower().split()).rstrip(".,!?…")
    word = wake_word.strip().lower()
    phrases = {
        f"merci {word}",
        f"au revoir {word}",
        f"stop {word}",
        f"arrête {word}",
        f"arrête-toi {word}",
        f"c'est tout {word}",
        f"c'est fini {word}",
        "c'est tout",
    }
    return normalized in phrases


def _record_transcript(
    console: Any,
    session: VoiceSession,
) -> Optional[str] | object:
    """Record until silence and transcribe.

    Returns the stripped transcript string, the ``None`` nothing-heard
    sentinel, or the ``VOICE_EXIT`` sentinel on Ctrl-C / mic failure.
    """
    from openjarvis.speech.voice_io import record_until_silence

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
        backend = session.get_stt_backend()
        if backend is None:
            console.print("[red]No speech-to-text backend available.[/red]")
            return VOICE_EXIT
        result = backend.transcribe(
            audio_bytes, format="wav", language=session.get_stt_language()
        )
        text = result.text.strip()
        if text:
            return text
        console.print("[dim]Nothing heard — try again.[/dim]")
        return None
    except Exception as exc:
        console.print(f"[red]Transcription error: {_terminal_safe_text(exc)}[/red]")
        return None


def _chime() -> None:
    """Play the wake-word confirmation beep (best-effort, never raises)."""
    try:
        from openjarvis.speech.voice_io import play_beep

        play_beep()
    except Exception:  # noqa: BLE001 — the chime is a nicety
        pass


def record_voice(
    console: Any,
    session: VoiceSession | None = None,
    *,
    source: Optional[str] = None,
) -> Optional[Tuple[str, str]] | object:
    """Record from mic, transcribe, and return the accepted command.

    Includes wake word detection: if the configured wake word (default "jarvis")
    is detected at the start of the transcription, the system enters active
    listening mode and the wake word is stripped from the command text; the
    returned source is then ``"voice_wake"`` instead of ``"voice"``.

    With conversation mode enabled, subsequent turns skip the wake word until
    an exit phrase ("merci jarvis", "stop jarvis", …) or Ctrl-C.

    Returns the accepted ``(command, source)`` pair, the ``None`` nothing-heard
    sentinel, or the ``VOICE_EXIT`` sentinel.
    """
    from openjarvis.core.config import load_config

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

    # Load config for wake word settings (environment overrides config).
    config = load_config()
    wake_word = os.environ.get("JARVIS_WAKE_WORD") or getattr(
        config.speech, "wake_word", "jarvis"
    )
    wake_word_enabled = _env_flag(
        "JARVIS_WAKE_ENABLED", getattr(config.speech, "wake_word_enabled", True)
    )
    utterance_source = source or SOURCE_VOICE
    conversation_enabled = _env_flag(
        "JARVIS_CONVERSATION",
        getattr(config.speech, "conversation_mode", True),
    )

    # Conversation mode: the wake word already fired on a previous turn —
    # accept commands directly until an exit phrase.
    if conversation_enabled and active_session.conversation_active:
        transcript = _record_transcript(console, active_session)
        if transcript is None or transcript is VOICE_EXIT:
            return transcript
        if _is_exit_phrase(transcript, wake_word):
            active_session.leave_conversation()
            console.print("[dim]Conversation ended.[/dim]")
            return None
        console.print(
            f"[bold]You (voice):[/bold] {_terminal_safe_text(transcript)}"
        )
        return (transcript, SOURCE_VOICE_WAKE)

    # Push-to-talk: a global hotkey (F8) opens the mic instead of the wake
    # word. Falls back to the wake-word flow when ``keyboard`` is missing.
    if _env_flag(
        "JARVIS_PUSH_TO_TALK", getattr(config.speech, "push_to_talk", False)
    ):
        from openjarvis.speech.hotkey import hotkey_available, wait_for_hotkey

        if not hotkey_available():
            console.print(
                "[dim yellow]Push-to-talk requires the 'keyboard' package — "
                "install with: pip install keyboard[/dim yellow]"
            )
        else:
            console.print(
                "[dim cyan]Press F8 to talk… (Ctrl-C to cancel)[/dim cyan]"
            )
            if not wait_for_hotkey():
                console.print("[dim]Hotkey not pressed.[/dim]")
                return None
            console.print("[bold green]Listening…[/bold green]")
            _chime()
            if conversation_enabled:
                active_session.enter_conversation()
            transcript = _record_transcript(console, active_session)
            if transcript is None or transcript is VOICE_EXIT:
                return transcript
            console.print(
                f"[bold]You (voice):[/bold] {_terminal_safe_text(transcript)}"
            )
            return (transcript, SOURCE_VOICE_WAKE)

    # Audio-level wake word (openWakeWord): always-listening, no push-to-talk.
    # Falls back to the transcript-based check below when unavailable.
    if wake_word_enabled and _env_flag(
        "JARVIS_AUDIO_WAKE", getattr(config.speech, "audio_wake_word", True)
    ):
        from openjarvis.speech.audio_wake import build_detector

        detector = build_detector(timeout=30.0)
        if detector is not None:
            console.print(
                "[dim cyan]Listening for the wake word…[/dim cyan] "
                f"([dim]say '{wake_word}'[/dim])"
            )
            try:
                detected = detector.listen()
            finally:
                detector.close()
            if not detected:
                if getattr(detector, "load_error", None):
                    console.print(
                        "[dim yellow]Audio wake word model missing — run: "
                        "python -c \"from openwakeword.utils import "
                        "download_models; download_models()\"[/dim yellow]"
                    )
                else:
                    console.print("[dim]No wake word heard — try again.[/dim]")
                return None
            console.print("[bold green]Wake word detected![/bold green]")
            _chime()
            if conversation_enabled:
                active_session.enter_conversation()
            # Audio already gated the wake phrase: record the command and
            # accept it directly (transcript check below is a no-op for it).
            transcript = _record_transcript(console, active_session)
            if transcript is None or transcript is VOICE_EXIT:
                return transcript
            console.print(
                f"[bold]You (voice):[/bold] {_terminal_safe_text(transcript)}"
            )
            return (transcript, SOURCE_VOICE_WAKE)
        console.print(
            "[dim]Audio wake word unavailable — using transcript-based "
            "detection.[/dim]"
        )

    transcript = _record_transcript(console, active_session)
    if transcript is None or transcript is VOICE_EXIT:
        return transcript
    text = transcript

    detected_wake = False
    if wake_word_enabled:
        detected_wake = check_wake_word(text, wake_word)

    if detected_wake:
        # Strip the wake word (and any trailing punctuation) from the
        # beginning of the command.
        text = strip_wake_word(text, wake_word)
        console.print(
            "[bold green]Wake word detected![/bold green] "
            f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}"
        )
        _chime()
        if conversation_enabled:
            active_session.enter_conversation()
        # If there's still text after the wake word, return it;
        # otherwise prompt for a command
        if text:
            return (text, SOURCE_VOICE_WAKE)
        console.print(
            "[dim]Please give a command after the wake word.[/dim]"
        )
        return None
    if wake_word_enabled:
        # Wake-gated listening: ignore utterances that did not carry
        # the wake word instead of treating them as commands.
        console.print(
            "[dim]No wake word detected — say "
            f"'{wake_word}' to wake Jarvis.[/dim]"
        )
        return None
    console.print(f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}")
    return (text, utterance_source)


def speak(
    text: str,
    console: Any,
    session: VoiceSession | None = None,
    *,
    interrupt_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """Synthesize and play text, reusing a healthy backend for the session.

    Returns ``True`` when the audio played to completion, ``False`` when
    *interrupt_check* fired (barge-in) or no backend could play it.
    """
    from openjarvis.speech.voice_io import play_wav

    active_session = session or VoiceSession()

    # Resolved before the loop: a bad config value must surface as a config
    # error, not be swallowed by the per-backend fallback handler below.
    try:
        active_session.get_voice_preferences()
    except Exception as exc:
        console.print(f"[red]Invalid speech config: {_terminal_safe_text(exc)}[/red]")
        return False

    while (backend := active_session.get_tts_backend()) is not None:
        try:
            voice_id, speed = active_session.voice_for_backend(backend, console)
            synth_kwargs: dict[str, Any] = {"output_format": "wav", "speed": speed}
            if voice_id:
                synth_kwargs["voice_id"] = voice_id
            result = backend.synthesize(text, **synth_kwargs)
            if result.audio:
                return play_wav(
                    result.audio,
                    sample_rate=result.sample_rate,
                    interrupt_check=interrupt_check,
                )
            return False
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
    return False


# Sentence terminators: after one of these followed by whitespace (or the end
# of the text) a sentence is complete and can be spoken aloud. A digit after
# the punctuation is NOT a boundary, so decimal points and abbreviations like
# "3.14" stay intact.
_SENTENCE_ENDINGS = frozenset({".", "!", "?", "…", "؟"})


def _speech_clean(text: str) -> str:
    """Strip Markdown artifacts that sound wrong when spoken aloud.

    Code blocks are dropped entirely; inline code, links, bold/italic markers
    and heading hashes collapse to their visible text.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    return " ".join(text.split())


class SentenceSpeaker:
    """Speak a streamed reply sentence by sentence.

    Mirrors the "speak while still thinking" pattern of voice assistants:
    ``feed()`` buffers the token stream and, as soon as a sentence boundary is
    crossed, hands the finished sentence to the TTS backend — so Jarvis starts
    talking before the model has generated the rest of the answer. ``flush()``
    speaks whatever text remains without a terminator.

    With *interrupt_check* (barge-in), a sentence interrupted by user speech
    stops the speaker entirely: :attr:`interrupted` turns ``True`` and the
    remaining reply is dropped instead of being spoken over the user.
    """

    def __init__(
        self,
        session: VoiceSession,
        console: Any,
        *,
        speak_fn: Optional[Callable[..., None]] = None,
        interrupt_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._session = session
        self._console = console
        self._speak_fn = speak_fn or speak
        self._interrupt_check = interrupt_check
        self._buffer = ""
        self._interrupted = False

    @property
    def interrupted(self) -> bool:
        """True once a sentence was cut off by user speech (barge-in)."""
        return self._interrupted

    def _speak(self, text: str) -> bool:
        """Speak *text* through the configured function; track interruptions."""
        if self._interrupt_check is None:
            self._speak_fn(text, self._console, self._session)
            return True
        # Discard any stale trigger accumulated while the model was still
        # generating, then let playback poll for fresh ones.
        self._interrupt_check()
        played = self._speak_fn(
            text,
            self._console,
            self._session,
            interrupt_check=self._interrupt_check,
        )
        if played is False:
            self._interrupted = True
        return played is not False

    def _pop_sentence(self) -> Optional[str]:
        """Return the first complete sentence, or None when buffering."""
        text = self._buffer
        for i, char in enumerate(text):
            if char not in _SENTENCE_ENDINGS:
                continue
            if i + 1 < len(text) and not text[i + 1].isspace():
                continue  # decimal point or abbreviation — keep buffering
            sentence = text[: i + 1]
            self._buffer = text[i + 1 :]
            return _speech_clean(sentence)
        return None

    def feed(self, token: str) -> None:
        """Buffer *token* and speak any sentence it completes."""
        if self._interrupted:
            return
        self._buffer += token
        while True:
            sentence = self._pop_sentence()
            if not sentence:
                return
            if not self._speak(sentence):
                self._buffer = ""
                return

    def flush(self) -> None:
        """Speak the remaining buffered text, if any."""
        if self._interrupted:
            self._buffer = ""
            return
        leftover = _speech_clean(self._buffer)
        self._buffer = ""
        if leftover:
            self._speak(leftover)


__all__ = [
    "SOURCE_TYPED",
    "SOURCE_VOICE",
    "SOURCE_VOICE_WAKE",
    "SentenceSpeaker",
    "VOICE_EXIT",
    "VoiceSession",
    "read_voice_input",
    "record_voice",
    "speak",
]
