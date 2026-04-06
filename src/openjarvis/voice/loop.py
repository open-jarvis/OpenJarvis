"""VoiceLoop — the core Jarvis voice pipeline.

Full cycle:
    Mic → VAD → STT → (wake-word check) → Agent → TTS → Playback → repeat

Usage::

    from openjarvis.voice.loop import VoiceLoop

    loop = VoiceLoop(
        config=config,
        engine=engine,
        model_name="qwen3:8b",
        agent_name="simple",
        wake_word="jarvis",
        require_wake_word=True,
        speak_responses=True,
    )
    loop.run_forever()     # blocks; Ctrl-C to stop
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from rich.console import Console

from openjarvis.voice.audio_io import AudioPlayer, MicrophoneStream, pcm_to_wav
from openjarvis.voice.vad import VoiceActivityDetector
from openjarvis.voice.wake_word import WakeWordDetector, WakeWordResult

logger = logging.getLogger(__name__)
console = Console(stderr=True)


class VoiceLoop:
    """Orchestrates the full listen → think → speak cycle.

    Parameters
    ----------
    config:
        Loaded ``JarvisConfig``.
    engine:
        An ``InferenceEngine`` instance (already set up by the CLI).
    model_name:
        Model identifier string.
    agent_name:
        Agent registry key (e.g. ``"simple"``, ``"orchestrator"``).
    tool_names:
        List of tool registry keys to enable (passed through to the agent).
    wake_word:
        Keyword to listen for (e.g. ``"jarvis"``).
    require_wake_word:
        If False, every detected utterance is sent to the agent directly.
    speak_responses:
        If True (default), synthesise and play the agent's response.
    tts_backend:
        Explicit TTS backend key (``"auto"`` = auto-discover).
    """

    def __init__(
        self,
        config,
        engine,
        model_name: str,
        agent_name: str = "simple",
        tool_names: Optional[list[str]] = None,
        wake_word: str = "jarvis",
        require_wake_word: bool = True,
        speak_responses: bool = True,
        tts_backend: str = "auto",
        bus=None,
        screenshot_context: bool = False,
        screenshot_ocr: bool = False,
    ) -> None:
        self._config = config
        self._engine = engine
        self._model = model_name
        self._agent_name = agent_name
        self._tool_names = tool_names or []
        self._require_wake_word = require_wake_word
        self._speak = speak_responses
        self._bus = bus
        self._screenshot_context = screenshot_context
        self._screenshot_ocr = screenshot_ocr

        # Override TTS backend choice if specified
        if tts_backend != "auto":
            config.speech.tts_backend = tts_backend

        # Build sub-components
        self._mic = MicrophoneStream(
            sample_rate=16_000,
            frame_ms=30,
            device=config.speech.input_device or None,
        )

        self._vad = VoiceActivityDetector(
            engine=config.speech.vad_engine,
            aggressiveness=config.speech.vad_aggressiveness,
            sample_rate=16_000,
            silence_timeout_ms=config.speech.silence_timeout_ms,
            min_speech_ms=config.speech.min_speech_ms,
        )

        self._wake = WakeWordDetector(
            keyword=wake_word,
            engine=config.speech.wake_word_engine,
        )

        self._player = AudioPlayer(device=config.speech.output_device or None)

        # Lazy-init STT and TTS on first use
        self._stt = None
        self._tts = None

    # ------------------------------------------------------------------
    # Lazy backend access
    # ------------------------------------------------------------------

    def _get_stt(self):
        if self._stt is None:
            from openjarvis.speech._discovery import get_speech_backend

            self._stt = get_speech_backend(self._config)
            if self._stt is None:
                raise RuntimeError(
                    "No STT backend available.\n"
                    "Install faster-whisper:  uv sync --extra speech\n"
                    "Or set OPENAI_API_KEY for cloud STT."
                )
        return self._stt

    def _get_tts(self):
        if self._tts is None:
            from openjarvis.voice.tts_discovery import get_tts_backend

            self._tts = get_tts_backend(self._config)
            if self._tts is None:
                logger.warning(
                    "No TTS backend available — responses will be printed only.\n"
                    "Install kokoro: pip install kokoro soundfile\n"
                    "Or set CARTESIA_API_KEY / OPENAI_API_KEY."
                )
        return self._tts

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    def _transcribe(self, pcm_bytes: bytes) -> str:
        """Convert raw PCM → WAV → transcribed text."""
        wav = pcm_to_wav(pcm_bytes, sample_rate=16_000)
        stt = self._get_stt()
        result = stt.transcribe(
            wav,
            format="wav",
            language=self._config.speech.language or None,
        )
        return result.text.strip()

    # ------------------------------------------------------------------
    # Agent
    # ------------------------------------------------------------------

    def _run_agent(self, query: str) -> str:
        """Run the configured agent and return the response text."""
        from openjarvis.agents._stubs import AgentContext
        from openjarvis.core.events import EventBus
        from openjarvis.core.registry import AgentRegistry

        import openjarvis.agents  # noqa: F401 — trigger registration

        bus = self._bus or EventBus()

        if not AgentRegistry.contains(self._agent_name):
            raise RuntimeError(
                f"Unknown agent '{self._agent_name}'. "
                f"Available: {', '.join(AgentRegistry.keys())}"
            )

        agent_cls = AgentRegistry.get(self._agent_name)

        # Build tools if the agent accepts them
        tools = []
        if self._tool_names and getattr(agent_cls, "accepts_tools", False):
            import openjarvis.tools  # noqa: F401

            from openjarvis.core.registry import ToolRegistry

            for name in self._tool_names:
                name = name.strip()
                if name and ToolRegistry.contains(name):
                    tools.append(ToolRegistry.get(name)())

        agent_kwargs: dict = {
            "bus": bus,
            "temperature": self._config.intelligence.temperature,
            "max_tokens": self._config.intelligence.max_tokens,
        }
        if getattr(agent_cls, "accepts_tools", False):
            agent_kwargs["tools"] = tools
            agent_kwargs["max_turns"] = self._config.agent.max_turns
            agent_kwargs["interactive"] = False

        agent = agent_cls(self._engine, self._model, **agent_kwargs)
        result = agent.run(query, context=AgentContext())
        return result.content.strip()

    # ------------------------------------------------------------------
    # TTS + playback
    # ------------------------------------------------------------------

    def _speak_text(self, text: str) -> None:
        """Synthesise text to speech and play it."""
        tts = self._get_tts()
        if tts is None:
            return  # No TTS — already warned during init

        voice_id = self._config.speech.tts_voice_id or ""
        speed = self._config.speech.tts_speed

        try:
            result = tts.synthesize(
                text,
                voice_id=voice_id,
                speed=speed,
                output_format="wav",
            )
        except Exception:
            # Some backends (Cartesia) may not support WAV — retry with mp3
            try:
                result = tts.synthesize(
                    text,
                    voice_id=voice_id,
                    speed=speed,
                    output_format="mp3",
                )
            except Exception as exc:
                logger.warning("TTS synthesis failed: %s", exc)
                return

        self._player.play(result.audio, format=result.format, sample_rate=result.sample_rate)

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    def run_once(self) -> Optional[str]:
        """Listen for one utterance, process it, return the response text.

        Returns ``None`` if no speech was detected in this cycle.
        """
        frame_gen = self._mic.frames()
        pcm = self._vad.collect_utterance(frame_gen)

        if pcm is None:
            return None

        try:
            text = self._transcribe(pcm)
        except Exception as exc:
            logger.warning("STT failed: %s", exc)
            return None

        if not text:
            return None

        logger.debug("Transcribed: %r", text)

        # Wake word check
        if self._require_wake_word:
            check: WakeWordResult = self._wake.check_transcript(text)
            if not check.detected:
                logger.debug("No wake word in: %r — ignoring.", text)
                return None
            command = check.command
            if not command:
                # Wake word detected but no command — ask "how can I help?"
                command = "How can I help you?"
        else:
            command = text

        console.print(f"\n[bold cyan]You:[/bold cyan] {command}")

        # Optionally prepend screen context before sending to agent
        agent_input = command
        if self._screenshot_context:
            from openjarvis.cli.ask import _prepend_screen_context

            agent_input = _prepend_screen_context(
                command, ocr=self._screenshot_ocr
            )

        # Agent
        try:
            response = self._run_agent(agent_input)
        except Exception as exc:
            logger.error("Agent error: %s", exc)
            response = "I'm sorry, I encountered an error processing that request."

        console.print(f"[bold green]Jarvis:[/bold green] {response}\n")

        if self._speak:
            self._speak_text(response)

        return response

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Run the voice loop until Ctrl-C is pressed."""
        wake_hint = (
            f'Say "[bold]{self._wake.keyword}[/bold]" to wake me up.'
            if self._require_wake_word
            else "Listening... (any speech will be processed)"
        )
        console.print(f"\n[bold blue]Jarvis Voice Loop[/bold blue]")
        console.print(f"[dim]{wake_hint}  Press Ctrl-C to stop.[/dim]\n")

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                console.print("\n[dim]Voice loop stopped.[/dim]")
                break
            except Exception as exc:
                logger.error("Unexpected error in voice loop: %s", exc, exc_info=True)
                time.sleep(0.5)  # brief pause before retrying
