"""``jarvis listen`` -- start the Jarvis voice loop.

Full pipeline: wake word -> STT -> agent -> TTS -> playback.

Examples::

    # Wake-word required (say "jarvis <command>")
    jarvis listen

    # Always listening — no wake word needed
    jarvis listen --no-wake-word

    # Custom wake word, specific TTS backend and agent
    jarvis listen --wake-word "hey jarvis" --tts kokoro --agent orchestrator

    # Listen once, respond, exit  (e.g. for shell scripts)
    jarvis listen --once --no-wake-word

    # Print response to terminal but don't speak it
    jarvis listen --no-speak
"""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console

logger = logging.getLogger(__name__)


@click.command("listen")
@click.option(
    "--wake-word",
    "wake_word",
    default="jarvis",
    show_default=True,
    help="Keyword to listen for before processing a command.",
)
@click.option(
    "--no-wake-word",
    "no_wake_word",
    is_flag=True,
    default=False,
    help="Process every detected utterance without requiring a wake word.",
)
@click.option(
    "--tts",
    "tts_backend",
    default="auto",
    show_default=True,
    help="TTS backend: auto | kokoro | cartesia | openai_tts",
)
@click.option(
    "--voice-id",
    "voice_id",
    default="",
    help="Voice ID for TTS backend (backend-specific).",
)
@click.option(
    "--speed",
    "tts_speed",
    default=1.0,
    type=float,
    show_default=True,
    help="TTS playback speed multiplier.",
)
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent to use (simple, orchestrator, native_react, ...). Defaults to config.",
)
@click.option(
    "--tools",
    "tool_names",
    default=None,
    help="Comma-separated list of tools to enable for the agent.",
)
@click.option(
    "-m",
    "--model",
    "model_name",
    default=None,
    help="Model to use (overrides config).",
)
@click.option(
    "-e",
    "--engine",
    "engine_key",
    default=None,
    help="Inference engine backend to use.",
)
@click.option(
    "--vad",
    "vad_engine",
    default=None,
    help="VAD engine: energy (default) | webrtcvad",
)
@click.option(
    "--silence-ms",
    "silence_ms",
    default=None,
    type=int,
    help="Milliseconds of silence that mark end-of-utterance (default 1500).",
)
@click.option(
    "--speak/--no-speak",
    "speak",
    default=True,
    show_default=True,
    help="Whether to synthesise and play Jarvis's response.",
)
@click.option(
    "--once",
    "run_once",
    is_flag=True,
    default=False,
    help="Listen for a single utterance then exit.",
)
@click.option(
    "--input-device",
    "input_device",
    default=None,
    help="Microphone device name or index (default: system default).",
)
@click.option(
    "--output-device",
    "output_device",
    default=None,
    help="Speaker device name or index (default: system default).",
)
@click.option(
    "--screenshot",
    "take_screenshot",
    is_flag=True,
    default=False,
    help="Capture screen before each agent call and include it as visual context.",
)
@click.option(
    "--screenshot-ocr",
    "screenshot_ocr",
    is_flag=True,
    default=False,
    help="Extract text from screenshots via OCR (requires pytesseract or easyocr).",
)
def listen(  # noqa: PLR0913
    wake_word: str,
    no_wake_word: bool,
    tts_backend: str,
    voice_id: str,
    tts_speed: float,
    agent_name: str | None,
    tool_names: str | None,
    model_name: str | None,
    engine_key: str | None,
    vad_engine: str | None,
    silence_ms: int | None,
    speak: bool,
    run_once: bool,
    input_device: str | None,
    output_device: str | None,
    take_screenshot: bool,
    screenshot_ocr: bool,
) -> None:
    """Start the Jarvis voice loop (wake word -> STT -> agent -> TTS)."""
    console = Console(stderr=True)

    # ------------------------------------------------------------------
    # Load config
    # ------------------------------------------------------------------
    from openjarvis.core.config import load_config

    config = load_config()

    # Apply CLI overrides to speech config
    if vad_engine:
        config.speech.vad_engine = vad_engine
    if silence_ms is not None:
        config.speech.silence_timeout_ms = silence_ms
    if input_device:
        config.speech.input_device = input_device
    if output_device:
        config.speech.output_device = output_device
    if voice_id:
        config.speech.tts_voice_id = voice_id
    if tts_speed != 1.0:
        config.speech.tts_speed = tts_speed

    # ------------------------------------------------------------------
    # Resolve agent
    # ------------------------------------------------------------------
    resolved_agent = agent_name or config.agent.default_agent or "simple"

    # ------------------------------------------------------------------
    # Resolve tool list
    # ------------------------------------------------------------------
    parsed_tools: list[str] = []
    if tool_names:
        parsed_tools = [t.strip() for t in tool_names.split(",") if t.strip()]
    elif getattr(config.agent, "tools", None):
        raw = config.agent.tools
        if isinstance(raw, str):
            parsed_tools = [t.strip() for t in raw.split(",") if t.strip()]
        elif isinstance(raw, list):
            parsed_tools = list(raw)

    # ------------------------------------------------------------------
    # Set up inference engine (mirrors ask.py setup)
    # ------------------------------------------------------------------
    from openjarvis.engine import EngineConnectionError, discover_engines, discover_models, get_engine
    from openjarvis.intelligence import merge_discovered_models, register_builtin_models
    from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
    from openjarvis.telemetry.store import TelemetryStore
    from openjarvis.core.events import EventBus

    bus = EventBus(record_history=True)
    telem_store: TelemetryStore | None = None
    if config.telemetry.enabled:
        try:
            telem_store = TelemetryStore(config.telemetry.db_path)
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Telemetry store unavailable: %s", exc)

    register_builtin_models()

    effective_engine_key = engine_key or config.intelligence.preferred_engine or None
    resolved = get_engine(config, effective_engine_key)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running:\n"
            "  [cyan]ollama serve[/cyan]\n"
            "Or set OPENAI_API_KEY / ANTHROPIC_API_KEY for cloud inference."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Security guardrails
    from openjarvis.security import setup_security
    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # Energy monitoring + instrumentation
    energy_monitor = None
    if config.telemetry.gpu_metrics:
        try:
            from openjarvis.telemetry.energy_monitor import create_energy_monitor
            energy_monitor = create_energy_monitor(
                prefer_vendor=config.telemetry.energy_vendor or None
            )
        except Exception as exc:
            logger.debug("Energy monitor unavailable: %s", exc)
    engine = InstrumentedEngine(engine, bus, energy_monitor=energy_monitor)

    # Resolve model name
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, mids in all_models.items():
        merge_discovered_models(ek, mids)

    if model_name is None:
        model_name = config.intelligence.default_model
    if not model_name:
        engine_models = all_models.get(engine_name, [])
        model_name = engine_models[0] if engine_models else config.intelligence.fallback_model
    if not model_name:
        console.print("[red]No model available.[/red]")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Check for sounddevice before starting
    # ------------------------------------------------------------------
    try:
        import sounddevice  # noqa: F401
        import soundfile    # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Missing audio dependencies.[/red bold]\n\n"
            "Install with:\n"
            "  [cyan]uv sync --extra voice[/cyan]\n\n"
            "Or manually:\n"
            "  [cyan]pip install sounddevice soundfile[/cyan]"
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Build and run the voice loop
    # ------------------------------------------------------------------
    from openjarvis.voice.loop import VoiceLoop

    loop = VoiceLoop(
        config=config,
        engine=engine,
        model_name=model_name,
        agent_name=resolved_agent,
        tool_names=parsed_tools,
        wake_word=wake_word,
        require_wake_word=not no_wake_word,
        speak_responses=speak,
        tts_backend=tts_backend,
        bus=bus,
        screenshot_context=take_screenshot,
        screenshot_ocr=screenshot_ocr,
    )

    try:
        if run_once:
            loop.run_once()
        else:
            loop.run_forever()
    finally:
        if telem_store is not None:
            try:
                telem_store.close()
            except Exception:
                pass
        if energy_monitor is not None:
            try:
                energy_monitor.close()
            except Exception:
                pass
