"""``jarvis voice`` — manual smoke-testing for the wake-word voice pipeline.

Imports `sounddevice`/`openwakeword` at call time (not at module import), so
registering this command group in ``cli/__init__.py`` (inside a
try/except ImportError, since those are optional deps) never fails even
when the `speech-wakeword` extra isn't installed — only running the
subcommands does, with a clear error message.
"""

from __future__ import annotations

import time

import click
from rich.console import Console


@click.group("voice", help="Local wake-word voice pipeline — manual testing.")
def voice() -> None:
    pass


@voice.command("test-mic", help="Record a few seconds of audio to verify mic capture.")
@click.option("--seconds", type=float, default=3.0, help="Recording duration.")
@click.option(
    "--device", type=int, default=-1, help="Input device index (-1 = default)."
)
def test_mic(seconds: float, device: int) -> None:
    console = Console()
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        raise click.ClickException(
            "sounddevice/numpy not installed. Run: uv sync --extra speech-wakeword"
        )

    sample_rate = 16000
    device_label = device if device >= 0 else "default"
    console.print(f"[yellow]Recording {seconds:.1f}s from {device_label}...[/yellow]")
    dev = device if device >= 0 else None
    recording = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        device=dev,
    )
    sd.wait()
    peak = int(np.abs(recording).max()) if recording.size else 0
    console.print(
        f"[green]Captured {recording.size} samples. Peak amplitude: {peak}[/green]"
    )
    if peak < 50:
        console.print(
            "[red]Very low signal — check your microphone/device selection.[/red]"
        )

    try:
        from openjarvis.speech.wakeword import WakeWordDetector

        detector = WakeWordDetector()
        detector._ensure_model()  # noqa: SLF001 - deliberate smoke test of model load
        console.print("[green]openWakeWord model loaded successfully.[/green]")
    except Exception as exc:
        console.print(f"[red]openWakeWord model failed to load: {exc}[/red]")


@voice.command(
    "listen", help="Run the voice listener in the foreground (Ctrl+C to stop)."
)
@click.option("--model", type=str, default="", help="Override the model used.")
def listen(model: str) -> None:
    console = Console()
    from openjarvis.core.config import load_config

    config = load_config()
    if not config.voice.enabled:
        console.print(
            "[yellow]voice.enabled is false in config.toml — "
            "running anyway for this session.[/yellow]"
        )

    try:
        from openjarvis.speech._discovery import get_speech_backend

        speech_backend = get_speech_backend(config)
    except Exception as exc:
        raise click.ClickException(f"No speech (STT) backend available: {exc}")
    if speech_backend is None:
        raise click.ClickException("No speech (STT) backend configured.")

    from openjarvis.cli.science_lab_cmd import _resolve_engine_and_model

    engine, model_name = _resolve_engine_and_model(config, model)

    science_lab_agent = None
    try:
        import openjarvis.agents  # noqa: F401
        from openjarvis.core.registry import AgentRegistry

        if config.science_lab.enabled:
            science_lab_agent = AgentRegistry.create(
                "science_lab",
                engine,
                config.science_lab.model or model_name,
                min_hypotheses=config.science_lab.min_hypotheses,
                max_hypotheses=config.science_lab.max_hypotheses,
                safety_llm_fallback=config.science_lab.safety_llm_fallback,
                db_path=config.science_lab.db_path,
            )
    except Exception as exc:
        console.print(f"[dim]Science Lab agent unavailable: {exc}[/dim]")

    from openjarvis.speech.voice_service import VoiceService

    service = VoiceService(
        engine,
        config.science_lab.model or model_name,
        speech_backend,
        science_lab_agent=science_lab_agent,
        wake_word=config.voice.wake_word,
        threshold=config.voice.threshold,
        device_index=config.voice.device_index,
        sample_rate=config.voice.sample_rate,
        silence_timeout_s=config.voice.silence_timeout_s,
        stt_language=config.voice.stt_language,
        tts_backend=config.voice.tts_backend,
        voice_id=config.voice.voice_id,
        voice_speed=config.voice.voice_speed,
    )

    try:
        service.start()
    except ImportError as exc:
        raise click.ClickException(
            f"Missing dependency: {exc}. Run: uv sync --extra speech-wakeword"
        )

    console.print(
        f"[green]Listening for wake word '{config.voice.wake_word}'... "
        "(Ctrl+C to stop)[/green]"
    )
    last_state = ""
    try:
        while True:
            status = service.status()
            if status["state"] != last_state:
                console.print(
                    f"[cyan]state: {status['state']}[/cyan]"
                    + (
                        f" — {status['last_utterance']}"
                        if status.get("last_utterance")
                        else ""
                    )
                )
                last_state = status["state"]
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        console.print("[yellow]Stopped.[/yellow]")


@voice.command(
    "status", help="Show the voice listener's status from a running `jarvis serve`."
)
@click.option(
    "--url", type=str, default="http://127.0.0.1:8000", help="jarvis serve base URL."
)
def status(url: str) -> None:
    console = Console()
    import requests

    try:
        resp = requests.get(f"{url}/v1/science-lab/voice/status", timeout=5)
        resp.raise_for_status()
        console.print(resp.json())
    except Exception as exc:
        raise click.ClickException(f"Failed to reach {url}: {exc}")


__all__ = ["voice"]
