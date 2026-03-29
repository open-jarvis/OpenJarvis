"""``jarvis voice`` — always-on desktop voice assistant mode."""

from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console

from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.core.config import load_config


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend (ollama, cloud, …).")
@click.option("-m", "--model", "model_name", default=None, help="Model name.")
@click.option("--tts", "tts_backend", default=None, type=click.Choice(["piper", "say", "silent"]), help="TTS backend.")
@click.option("--wake-word", "wake_word", default=None, help="Custom wake word / model path.")
@click.option("--energy", "energy_threshold", default=300, show_default=True, help="VAD energy threshold (0–32767).")
@click.option("--no-wake", is_flag=True, default=False, help="Skip wake word — always listen (push-to-talk feel).")
def voice(
    engine_key: Optional[str],
    model_name: Optional[str],
    tts_backend: Optional[str],
    wake_word: Optional[str],
    energy_threshold: int,
    no_wake: bool,
) -> None:
    """Start always-on voice assistant mode.

    \b
    Requires:
      uv pip install sounddevice numpy faster-whisper
      uv pip install openwakeword          # wake word detection
      uv pip install piper-tts             # optional: best TTS quality

    \b
    Wake word (default): "Hey Jarvis"
    Interrupt:           Say the wake word again while Jarvis is speaking
    Quit:                Ctrl-C
    """
    console = Console(stderr=True)

    # ── check audio deps ──────────────────────────────────────────────────────
    missing = []
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        missing.append("sounddevice")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        missing.append("faster-whisper")

    if missing:
        console.print(
            f"[red]Missing dependencies:[/red] {', '.join(missing)}\n"
            f"Install with:  [bold]uv pip install {' '.join(missing)}[/bold]"
        )
        sys.exit(1)

    # ── engine setup ─────────────────────────────────────────────────────────
    config = load_config()

    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    register_builtin_models()
    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    model = model_name or config.intelligence.default_model
    if not model:
        from openjarvis.engine import discover_engines, discover_models
        all_engines = discover_engines(config)
        all_models = discover_models(all_engines)
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model = engine_models[0]
        else:
            console.print("[red]No model available.[/red]")
            sys.exit(1)

    console.print(
        f"[dim]engine:[/dim] [cyan]{engine_name}[/cyan]  "
        f"[dim]model:[/dim] [cyan]{model}[/cyan]"
    )

    # ── TTS ───────────────────────────────────────────────────────────────────
    from openjarvis.voice.tts import build_tts
    tts = build_tts(prefer=tts_backend)

    # ── wake word ─────────────────────────────────────────────────────────────
    from openjarvis.voice.wake_word import WakeWordListener, _build_default_detector

    if no_wake:
        # Swap in an energy detector so it fires immediately when you speak
        from openjarvis.voice.wake_word import EnergyWakeWordDetector
        detector = EnergyWakeWordDetector(energy_threshold=energy_threshold)
        wake_listener = WakeWordListener(detector=detector)
    elif wake_word:
        from openjarvis.voice.wake_word import OpenWakeWordDetector
        try:
            detector = OpenWakeWordDetector(wake_words=[wake_word])
            wake_listener = WakeWordListener(detector=detector)
        except ImportError:
            console.print("[yellow]openwakeword not installed — using energy fallback[/yellow]")
            wake_listener = WakeWordListener()
    else:
        wake_listener = WakeWordListener()

    # ── build & run loop ──────────────────────────────────────────────────────
    from openjarvis.voice.loop import VoiceLoop

    loop = VoiceLoop(
        engine=engine,
        model=model,
        tts=tts,
        energy_threshold=energy_threshold,
    )

    # Inject the configured wake listener
    loop._wake_listener = wake_listener

    loop.run()


__all__ = ["voice"]
