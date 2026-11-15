"""Voice input/output helpers for the interactive chat session."""

from __future__ import annotations

import logging
import math
import queue
import re
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

from rich.markup import escape

logger = logging.getLogger(__name__)

VOICE_EXIT = object()
# A key was pressed while listening: the user wants to type this turn.
VOICE_TYPED = object()

# The speaker's tail (device latency, room echo) must not open the next turn.
_ECHO_GUARD_SECONDS = 0.4
# Click-to-talk gives up after this much silence; hands-free waits forever.
_PUSH_TO_TALK_TIMEOUT_SECONDS = 5.0
_HANDS_FREE_HINT = "speak, or press any key to type"

VOICE_STYLE_PROMPT = """\
Voice mode: your replies are read aloud by a text-to-speech voice, as one \
side of a spoken conversation.
- Answer in the user's language, in a natural, warm, conversational tone; \
in French, use the informal "tu".
- Keep it short: one to three short sentences. Get straight to the point.
- Never use lists, bullet points, headings, tables, markdown, emojis or code \
blocks.
- Write numbers, units, acronyms and symbols the way they are spoken when \
it could be ambiguous.
- If the question needs a long answer, give the gist in one or two \
sentences, then offer to go deeper.
- The user's words come from speech recognition and may contain mistakes; \
if something seems garbled, ask them to repeat."""

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…:])\s+")
# Until the first audio chunk is out, clause boundaries (commas) also
# qualify: a long opening sentence must not delay time-to-first-audio.
_CLAUSE_SPLIT = re.compile(r"(?<=[.!?…:,;])\s+")
# Markdown noise that TTS engines read out loud ("asterisk asterisk...").
_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.DOTALL), " "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*?([^*]+)\*\*?"), r"\1"),
    (re.compile(r"^#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),
]

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


def voice_style_prompt() -> str:
    """Return the spoken-reply instructions appended to the agent prompt.

    ``<config_dir>/VOICE.md`` overrides the built-in text when present and
    non-empty, so the style can be tuned without touching code.
    """
    from openjarvis.core.paths import get_config_dir

    path = get_config_dir() / "VOICE.md"
    try:
        # utf-8-sig: Notepad and PowerShell add a BOM that must not reach
        # the prompt.
        override = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        override = ""
    except (OSError, UnicodeError) as exc:
        logger.warning("Ignoring %s (save it as UTF-8): %s", path, exc)
        override = ""
    return override.strip() or VOICE_STYLE_PROMPT


@contextmanager
def _locked(lock: threading.Lock) -> Iterator[None]:
    """Hold ``lock``; an untimed acquire() would defer Ctrl-C on Windows."""
    while not lock.acquire(timeout=0.1):
        pass
    try:
        yield
    finally:
        lock.release()


def _join_workers(workers: list[threading.Thread]) -> None:
    """Wait for ``workers``; short timed joins keep Ctrl-C responsive."""
    for worker in workers:
        while worker.is_alive():
            worker.join(0.1)


def _echo_guard() -> None:
    """Let the speaker's tail (device latency, room echo) die down."""
    time.sleep(_ECHO_GUARD_SECONDS)


def _float_setting(value: Any, default: float, name: str) -> float:
    """Coerce a TOML number, falling back (with a warning) on junk or ≤ 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if math.isfinite(number) and number > 0:
        return number
    logger.warning("Invalid [speech] %s = %r; using %s", name, value, default)
    return default


def _keyboard_pending() -> bool:
    """Return True when a key is waiting in the console, without consuming it.

    The key stays buffered so the ``input()`` that follows shows it on the
    edit line. Interactive consoles only: under redirected stdin (tests,
    pipes) a real keyboard must not hijack the session.
    """
    try:
        if not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if sys.platform == "win32":
        import msvcrt

        return bool(msvcrt.kbhit())
    import select

    return bool(select.select([sys.stdin], [], [], 0)[0])


def _read_typed() -> Optional[str] | object:
    """Read one typed line; an empty line goes back to listening."""
    try:
        typed = input("You> ").strip()
    except (EOFError, KeyboardInterrupt):
        return VOICE_EXIT
    return typed or None


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
        # A background preload and the first turn can both resolve a backend;
        # without the locks each would instantiate (and load) its own model.
        self._tts_lock = threading.Lock()
        self._stt_lock = threading.Lock()

    def _get_config(self) -> Any:
        from openjarvis.core.config import load_config

        return self._config if self._config is not None else load_config()

    @property
    def stt_ready(self) -> bool:
        """True once the STT backend has been resolved (loaded or not)."""
        return self._stt_resolved

    def get_stt_backend(self) -> Any:
        """Resolve and health-check STT once, then reuse the loaded backend."""
        with _locked(self._stt_lock):
            if not self._stt_resolved:
                from openjarvis.speech._discovery import get_speech_backend

                self._stt_backend = get_speech_backend(self._get_config())
                self._stt_resolved = True
            return self._stt_backend

    def get_turn_model_path(self) -> str:
        """Return ``speech.turn_model`` (a local Smart Turn ONNX), or ``""``."""
        speech = getattr(self._get_config(), "speech", None)
        value = getattr(speech, "turn_model", "") or ""
        return str(value).strip()

    def get_turn_pause_secs(self) -> float:
        """Return ``speech.turn_pause_secs``: silence before the end-of-turn check."""
        speech = getattr(self._get_config(), "speech", None)
        return _float_setting(
            getattr(speech, "turn_pause_secs", 0.5), 0.5, "turn_pause_secs"
        )

    def preload_turn_detector(self) -> None:
        """Load the VAD and end-of-turn models (and onnxruntime) up front.

        ``import onnxruntime`` alone can take several seconds and holds the
        GIL; paying it here keeps it out of the first listen.
        """
        try:
            from openjarvis.speech.turn_detection import load_turn_models

            load_turn_models(self.get_turn_model_path())
        except Exception:
            logger.debug("Turn detector preload failed", exc_info=True)

    def preload_stt(self) -> None:
        """Load the speech-to-text model ahead of the first turn."""
        try:
            self.get_stt_backend()
        except Exception:
            logger.debug("STT preload failed", exc_info=True)

    def preload(self) -> None:
        """Load every voice model in the order a conversation needs them.

        One thread, sequentially: the loaders are import-heavy and largely
        GIL-bound, so running them side by side would not finish sooner but
        would starve the microphone callback of the first turn.
        """
        self.preload_turn_detector()
        self.preload_stt()
        self.preload_tts()

    def get_stt_language(self) -> Optional[str]:
        """Return the configured ``speech.language``, or None to auto-detect."""
        config = self._get_config()
        return (getattr(config.speech, "language", "") or "").strip() or None

    def get_tts_backend(self) -> Any:
        """Return a cached healthy TTS backend, falling through once per key."""
        with _locked(self._tts_lock):
            if self._tts_backend is not None:
                return self._tts_backend

            from openjarvis.speech._tts_discovery import get_tts_backend

            preferred, _, _ = self.get_voice_preferences()
            self._tts_backend = get_tts_backend(
                preferred, attempted=self._tts_attempted
            )
            return self._tts_backend

    def preload_tts(self) -> None:
        """Resolve the TTS backend and load its model ahead of the first reply.

        Meant for a background thread at session start: importing a
        torch-based TTS and loading its model can take tens of seconds,
        which would otherwise all land on the first spoken answer.
        Failures are logged; the normal speak path retries and reports.
        """
        try:
            backend = self.get_tts_backend()
            preload = getattr(backend, "preload", None)
            if callable(preload):
                voice_id, _ = self.voice_for_backend(backend)
                if voice_id:
                    preload(voice_id)
                else:
                    preload()
        except Exception:
            logger.debug("TTS preload failed", exc_info=True)

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


def read_voice_input(
    console: Any,
    session: VoiceSession,
    *,
    hands_free: bool = False,
    announce: bool = True,
) -> Optional[str] | object:
    """Return the user's next message, typed or spoken, or a loop sentinel.

    Push-to-talk (default): type a message, or press Enter to record one.
    Hands-free: listen straight away; any key switches to typing for this
    turn. ``announce=False`` keeps silent re-listens from re-printing the
    prompt (and skips the echo guard, which only matters right after a
    spoken reply).
    """
    if not hands_free:
        try:
            typed = input("You> [type, or press Enter to speak] ")
        except (EOFError, KeyboardInterrupt):
            return VOICE_EXIT
        typed = typed.strip()
        return typed if typed else record_voice(console, session)

    if _keyboard_pending():  # keys typed while Jarvis was speaking
        return _typed_turn(console)
    if announce:
        try:
            _echo_guard()
        except KeyboardInterrupt:
            return VOICE_EXIT
    result = record_voice(
        console,
        session,
        should_stop=_keyboard_pending,
        hands_free=True,
        quiet=not announce,
    )
    return _typed_turn(console) if result is VOICE_TYPED else result


def _typed_turn(console: Any) -> Optional[str] | object:
    """Read a typed line in hands-free mode; an empty one resumes listening.

    The chat loop treats the resulting None like silence and re-listens
    without a prompt, so say here that the mic is open again.
    """
    typed = _read_typed()
    if typed is None:
        console.print(f"[dim cyan]Listening… ({_HANDS_FREE_HINT})[/dim cyan]")
    return typed


def _capture_turn(
    session: VoiceSession,
    *,
    hands_free: bool,
    should_stop: Callable[[], bool] | None,
) -> bytes | None | object:
    """Record one spoken turn: WAV bytes, None (nobody spoke) or VOICE_TYPED.

    Uses Silero VAD + Smart Turn end-of-turn detection when available, and
    the plain RMS/silence recorder otherwise.
    """
    from openjarvis.speech import turn_detection
    from openjarvis.speech.voice_io import record_until_silence

    model_path = session.get_turn_model_path()
    vad, _ = turn_detection.load_turn_models(model_path)
    if vad is None:
        # ~0.2 s of loud audio, like the VAD's start window: one click or
        # door slam must not become a transcribed "turn".
        audio = record_until_silence(
            should_stop=should_stop, require_speech=True, min_speech_chunks=3
        )
        if audio is None:
            return VOICE_TYPED
        return audio or None

    params = turn_detection.TurnParams(
        vad_stop_secs=session.get_turn_pause_secs(),
        start_timeout_secs=None if hands_free else _PUSH_TO_TALK_TIMEOUT_SECONDS,
    )
    audio = turn_detection.listen_for_turn(
        params=params, turn_model_path=model_path, should_stop=should_stop
    )
    if audio is turn_detection.TYPED:
        return VOICE_TYPED
    return audio


def record_voice(
    console: Any,
    session: VoiceSession | None = None,
    *,
    should_stop: Callable[[], bool] | None = None,
    hands_free: bool = False,
    quiet: bool = False,
) -> Optional[str] | object:
    """Record from mic, transcribe, and return text or a loop sentinel.

    Returns the transcript, None when nothing usable was heard (silence is
    never sent to the speech-to-text model), VOICE_TYPED when
    ``should_stop`` fired, or VOICE_EXIT on Ctrl-C or a fatal mic/STT error.
    """
    active_session = session or VoiceSession()
    if not active_session.stt_ready and not quiet:
        console.print("[dim]Loading speech recognition…[/dim]")
    try:
        backend = active_session.get_stt_backend()
    except KeyboardInterrupt:
        return VOICE_EXIT
    if backend is None:
        console.print(
            "[red]No speech-to-text backend available. "
            "Install the voice dependencies with: "
            "pip install 'OpenJarvis\\[speech]', or configure a healthy "
            "OpenAI/Deepgram backend.[/red]"
        )
        return VOICE_EXIT

    if not quiet:
        hint = _HANDS_FREE_HINT if hands_free else "speak now, stops when you finish"
        console.print(f"[dim cyan]Listening… ({hint})[/dim cyan]")
    try:
        audio = _capture_turn(
            active_session, hands_free=hands_free, should_stop=should_stop
        )
    except KeyboardInterrupt:
        return VOICE_EXIT
    except Exception as exc:
        # PortAudio failures are regular Exceptions (and can surface as
        # OSError), so report them without letting terminal control sequences
        # through. SystemExit deliberately continues to propagate, while
        # Ctrl-C maps to the chat loop's graceful-exit sentinel above.
        console.print(f"[red]Mic error: {_terminal_safe_text(exc)}[/red]")
        return VOICE_EXIT

    if audio is VOICE_TYPED:
        return VOICE_TYPED
    if not audio:
        if not hands_free:
            console.print("[dim]Nothing heard — try again.[/dim]")
        return None

    console.print("[dim]Transcribing…[/dim]")
    try:
        result = backend.transcribe(
            audio, format="wav", language=active_session.get_stt_language()
        )
    except KeyboardInterrupt:
        return VOICE_EXIT
    except Exception as exc:
        console.print(f"[red]Transcription error: {_terminal_safe_text(exc)}[/red]")
        return None
    text = result.text.strip()
    if text:
        console.print(f"[bold]You (voice):[/bold] {_terminal_safe_text(text)}")
        return text
    if not hands_free:
        console.print("[dim]Nothing heard — try again.[/dim]")
    return None


def _strip_markdown(text: str) -> str:
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _split_sentences(
    text: str, min_chars: int = 60, first_chunk_chars: int = 20
) -> list[str]:
    """Split text into sentence chunks, merging fragments below a floor.

    The first chunk uses a lower floor: getting any first sentence out
    fast is what makes the speech feel responsive, while later chunks
    can be longer since they synthesize during playback.
    """
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip()) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for part in parts:
        buf = f"{buf} {part}".strip() if buf else part
        floor = first_chunk_chars if not chunks else min_chars
        if len(buf) >= floor:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def _speak_chunks(chunks: list[str], backend: Any, synth_kwargs: dict) -> None:
    """Pipeline synthesis and playback: chunk N+1 renders while N plays.

    Raises only when nothing was played, so the caller's backend-fallback
    loop can retry from silence; a failure after partial playback is
    logged rather than re-spoken through another backend.
    """
    from openjarvis.speech.voice_io import play_wav

    done = object()
    audio_queue: queue.Queue = queue.Queue(maxsize=2)
    errors: list[Exception] = []
    stop = threading.Event()

    def _put(item: Any) -> None:
        # Bounded waits: once the reply is cut nobody drains the queue.
        while not stop.is_set():
            try:
                audio_queue.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def _producer() -> None:
        try:
            for chunk in chunks:
                if stop.is_set():
                    break
                result = backend.synthesize(chunk, **synth_kwargs)
                if result.audio:
                    _put(result)
        except Exception as exc:
            errors.append(exc)
        finally:
            _put(done)

    threading.Thread(target=_producer, daemon=True).start()

    played = False
    try:
        while True:
            try:
                item = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is done:
                break
            play_wav(item.audio, sample_rate=item.sample_rate)
            played = True
    except KeyboardInterrupt:
        stop.set()
        raise

    if errors:
        if not played:
            raise errors[0]
        logger.warning("TTS failed after partial playback: %s", errors[0])


def _iter_audio(backend: Any, text: str, synth_kwargs: dict) -> Any:
    """Yield ``(float32 samples, sample_rate)`` for *text*.

    Backends exposing ``synthesize_stream`` hand over frames while they
    decode; others are synthesized whole and decoded into a single frame.
    """
    from openjarvis.speech.voice_io import decode_audio

    stream = getattr(backend, "synthesize_stream", None)
    if callable(stream):
        kwargs = {k: v for k, v in synth_kwargs.items() if k in ("voice_id", "speed")}
        yield from stream(text, **kwargs)
        return
    result = backend.synthesize(text, **synth_kwargs)
    if result.audio:
        yield decode_audio(result.audio, result.sample_rate)


def speak_stream(
    deltas: Any,
    console: Any,
    session: VoiceSession,
) -> str:
    """Echo LLM text deltas as they arrive and speak completed sentences.

    Three-stage pipeline: the main thread consumes ``deltas`` (printing
    them plain, unrendered), an incremental splitter emits sentence
    chunks as soon as they complete, a synth thread renders them to
    audio (frame by frame when the backend streams), and a playback
    thread feeds the frames to one continuous output stream — so speech
    starts on the first completed sentence while the LLM is still
    generating, without waiting for that sentence to be fully rendered.

    Returns the full response text. TTS failures degrade to silent echo
    rather than interrupting the chat; engine errors propagate.
    """
    from openjarvis.speech import voice_io

    backend = None
    synth_kwargs: dict[str, Any] = {}
    try:
        session.get_voice_preferences()
        backend = session.get_tts_backend()
        if backend is not None:
            voice_id, speed = session.voice_for_backend(backend, console)
            synth_kwargs = {"output_format": "wav", "speed": speed}
            if voice_id:
                synth_kwargs["voice_id"] = voice_id
    except Exception as exc:
        console.print(
            f"[dim yellow]Voice setup failed: {_terminal_safe_text(exc)}[/dim yellow]"
        )
        backend = None

    done = object()
    text_queue: queue.Queue = queue.Queue()
    # Items are audio frames (~80 ms each for streaming backends), so the
    # bound is in frames: enough to run well ahead of playback.
    audio_queue: queue.Queue = queue.Queue(maxsize=512)
    stop = threading.Event()
    player = voice_io.open_stream_player() if backend is not None else None

    def _synth() -> None:
        try:
            while not stop.is_set():
                chunk = text_queue.get()
                if chunk is done:
                    break
                try:
                    for frame in _iter_audio(backend, chunk, synth_kwargs):
                        if stop.is_set():
                            break
                        audio_queue.put(frame)
                except Exception as exc:
                    logger.warning("Streaming TTS synthesis failed: %s", exc)
        finally:
            audio_queue.put(done)

    def _play() -> None:
        broken = False
        # Drain to the sentinel even after a cut: _synth blocks on put()
        # otherwise, while holding the TTS backend's lock, and every later
        # reply would wait on that lock forever.
        while (item := audio_queue.get()) is not done:
            if broken or stop.is_set():
                continue
            try:
                player.write(*item)
            except Exception as exc:
                # One warning, not one per 80 ms frame.
                logger.warning("Streaming TTS playback failed: %s", exc)
                broken = True
        # This thread owns the output stream, so it is the one to release it
        # (PortAudio streams are not thread-safe).
        try:
            if stop.is_set() or broken:
                player.abort()
            else:
                player.close()
        except Exception as exc:
            logger.warning("Streaming TTS playback failed: %s", exc)

    workers: list[threading.Thread] = []
    if backend is not None:
        workers = [
            threading.Thread(target=_synth, daemon=True),
            threading.Thread(target=_play, daemon=True),
        ]
        for worker in workers:
            worker.start()

    def _emit(chunk: str) -> None:
        if backend is not None and chunk:
            text_queue.put(chunk)

    def _cut() -> None:
        # Silence within one write block; the playback thread then drains
        # the queue and releases the device itself.
        stop.set()
        if player is not None:
            player.interrupt()

    received: list[str] = []
    pending = ""
    sent_any = False
    error: Exception | None = None
    try:
        for delta in deltas:
            received.append(delta)
            console.print(delta, end="", markup=False, highlight=False)
            pending += delta
            splitter = _SENTENCE_SPLIT if sent_any else _CLAUSE_SPLIT
            parts = splitter.split(pending)
            if len(parts) > 1:
                # All but the last part end at a sentence boundary; merge
                # them to the same floors as _split_sentences (small first
                # chunk for fast time-to-first-audio, larger afterwards).
                buf = ""
                for part in (p.strip() for p in parts[:-1] if p.strip()):
                    buf = f"{buf} {part}".strip() if buf else part
                    floor = 20 if not sent_any else 60
                    if len(buf) >= floor:
                        _emit(_strip_markdown(buf).strip())
                        sent_any = True
                        buf = ""
                # No strip(): the tail may end in the whitespace that
                # separates it from the next delta's first word.
                pending = f"{buf} {parts[-1]}" if buf else parts[-1]
        _emit(_strip_markdown(pending).strip())
    except KeyboardInterrupt:
        # Re-raise so the chat loop reports the interrupt.
        _cut()
        raise
    except Exception as exc:
        # Engine failed mid-reply: let the sentences already queued finish
        # before re-raising, so a hands-free loop never reopens the mic
        # while the speaker is still talking.
        error = exc
    finally:
        text_queue.put(done)
        console.print()

    # Let queued speech finish before handing the prompt back (matches
    # the blocking behavior of non-streaming speak()).
    try:
        _join_workers(workers)
    except KeyboardInterrupt:
        _cut()
        raise
    if error is not None:
        raise error
    return "".join(received)


def speak(text: str, console: Any, session: VoiceSession | None = None) -> None:
    """Synthesize and play text, reusing a healthy backend for the session.

    The text is spoken in sentence chunks, pipelined so the first
    sentence plays while the rest is still synthesizing.
    """
    active_session = session or VoiceSession()

    # Resolved before the loop: a bad config value must surface as a config
    # error, not be swallowed by the per-backend fallback handler below.
    try:
        active_session.get_voice_preferences()
    except Exception as exc:
        console.print(f"[red]Invalid speech config: {_terminal_safe_text(exc)}[/red]")
        return

    chunks = _split_sentences(_strip_markdown(text))
    if not chunks:
        return

    while (backend := active_session.get_tts_backend()) is not None:
        try:
            voice_id, speed = active_session.voice_for_backend(backend, console)
            synth_kwargs: dict[str, Any] = {"output_format": "wav", "speed": speed}
            if voice_id:
                synth_kwargs["voice_id"] = voice_id
            _speak_chunks(chunks, backend, synth_kwargs)
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


__all__ = [
    "VOICE_EXIT",
    "VOICE_STYLE_PROMPT",
    "VOICE_TYPED",
    "VoiceSession",
    "read_voice_input",
    "record_voice",
    "speak",
    "speak_stream",
    "voice_style_prompt",
]
