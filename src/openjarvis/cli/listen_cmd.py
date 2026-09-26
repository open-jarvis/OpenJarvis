"""jarvis listen -- always-on wake-word voice assistant.

Unlike jarvis chat --voice (push-to-talk: press Enter, then speak),
this command runs continuously: it listens for the wake word in the
background, and on each detection records one command, answers it, and
returns to listening -- no further input needed between exchanges.
"""

from __future__ import annotations

from typing import Optional

import click
from rich.console import Console

from openjarvis.cli._voice_chat import VOICE_EXIT, VoiceSession, record_voice, speak


@click.command()
@click.option(
    "--wake-model",
    default=None,
    help="Override the configured wake-word model (default: config.speech.wakeword_model).",
)
def listen(wake_model: Optional[str]) -> None:
    """Continuously listen for the wake word, then handle one voice command."""
    from openjarvis.core.config import load_config
    from openjarvis.speech._discovery import get_wakeword_backend
    from openjarvis.system import SystemBuilder

    console = Console()
    config = load_config()

    wakeword = get_wakeword_backend(config, model_override=wake_model)
    if wakeword is None:
        console.print(
            "[red]No wake-word backend available.[/red] "
            "Check that openwakeword is installed and a microphone is "
            "connected (see `jarvis doctor`)."
        )
        raise SystemExit(1)

    try:
        system = SystemBuilder().build()
    except Exception as exc:
        console.print(f"[red]Could not start JarvisSystem: {exc}[/red]")
        raise SystemExit(1)

    voice_session = VoiceSession(config)
    wake_phrase = (wake_model or config.speech.wakeword_model).replace("_", " ")

    console.print(f"[green]Listening for the wake word ({wake_phrase!r})...[/green]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]")

    try:
        while True:
            try:
                heard = wakeword.listen()
            except KeyboardInterrupt:
                break
            if not heard:
                continue

            console.print("\n[bold cyan]Wake word detected.[/bold cyan]")
            text = record_voice(console, voice_session)
            if text is VOICE_EXIT:
                break
            if not text:
                console.print(f"[green]Listening for the wake word ({wake_phrase!r})...[/green]")
                continue

            try:
                result = system.ask(text)
                content = result.get("content", "")
            except Exception as exc:
                console.print(f"[red]Error: {exc}[/red]")
                console.print(f"[green]Listening for the wake word ({wake_phrase!r})...[/green]")
                continue

            console.print(f"[bold]Jarvis:[/bold] {content}")
            speak(content, console, voice_session)
            console.print(f"[green]Listening for the wake word ({wake_phrase!r})...[/green]")
    except KeyboardInterrupt:
        pass
    finally:
        wakeword.stop()
        console.print("\n[dim]Stopped listening.[/dim]")
        if hasattr(system, "close"):
            try:
                system.close()
            except Exception:
                pass


__all__ = ["listen"]
