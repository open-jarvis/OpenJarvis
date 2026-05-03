"""``serena live`` - live conversational Serena session with memory context and voice output."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.core.config import load_config
from openjarvis.core.types import Message, Role
from openjarvis.engine import get_engine
from openjarvis.intelligence import register_builtin_models
from openjarvis.security import setup_security
from openjarvis.core.events import EventBus
from openjarvis.serena_audio import play_audio_file
from openjarvis.serena_identity import get_serena_system_prompt
from openjarvis.cli.speak_cmd import clean_for_speech
from openjarvis.speech.openai_tts import OpenAITTSBackend


def _read_input(prompt: str = "You> ") -> str | None:
    """Read live user input."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _speak_text(
    text: str,
    *,
    voice_id: str,
    output_dir: str,
    no_play: bool,
    no_interrupt: bool,
    console: Console,
) -> None:
    """Convert Serena text to speech and play it internally."""
    spoken_text = clean_for_speech(text)
    if not spoken_text:
        return

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"serena-live-{timestamp}.mp3"

    try:
        tts = OpenAITTSBackend()
        speech = tts.synthesize(spoken_text, voice_id=voice_id)
        speech.save(out_path)
    except Exception as exc:
        console.print(f"[yellow]Voice generation failed: {exc}[/yellow]")
        return

    if no_play:
        console.print(f"[dim]Voice saved: {out_path}[/dim]")
        return

    try:
        play_audio_file(out_path, interruptible=not no_interrupt)
    except Exception as exc:
        console.print(f"[yellow]Playback failed: {exc}[/yellow]")


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("--voice", "voice_id", default="nova", help="OpenAI TTS voice to use.")
@click.option("--output-dir", default="outputs/voice", help="Folder for generated audio.")
@click.option("--no-speak", is_flag=True, help="Do not speak Serena replies.")
@click.option("--no-interrupt", is_flag=True, help="Disable Enter-to-interrupt during playback.")
@click.option("--max-history", default=30, type=int, help="Maximum conversation messages to keep.")
def live(
    engine_key: str | None,
    model_name: str | None,
    voice_id: str,
    output_dir: str,
    no_speak: bool,
    no_interrupt: bool,
    max_history: int,
) -> None:
    """Start a live Serena session with conversation context and spoken replies."""
    console = Console(stderr=True)

    config = load_config()
    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        raise click.ClickException(
            "No inference engine available. Check OPENAI_API_KEY and run: serena doctor"
        )

    engine_name, engine = resolved

    bus = EventBus(record_history=True)
    sec = setup_security(config, engine, bus)
    engine = sec.engine

    model = model_name or config.intelligence.default_model
    if not model:
        raise click.ClickException("No model configured. Set intelligence.default_model in config.")

    history: List[Message] = [
        Message(role=Role.SYSTEM, content=get_serena_system_prompt()),
    ]

    console.print()
    console.print("[bold cyan]Serena Live[/bold cyan]")
    console.print(f"  Brain: [cyan]{engine_name} / {model}[/cyan]")
    console.print(f"  Voice: [cyan]{'off' if no_speak else voice_id}[/cyan]")
    console.print("  Commands: [dim]/quit, /exit, /clear, /mute, /speak, /model, /help[/dim]")
    console.print()

    muted = no_speak

    while True:
        user_input = _read_input("You> ")
        if user_input is None:
            console.print("\n[dim]Serena live session ended.[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Serena live session ended.[/dim]")
            break

        if cmd == "/help":
            console.print(
                "[bold]Live commands:[/bold]\n"
                "  /quit, /exit  - end session\n"
                "  /clear        - clear conversation context\n"
                "  /mute         - stop speaking replies\n"
                "  /speak        - resume speaking replies\n"
                "  /model        - show current model\n"
                "  /help         - show this help"
            )
            continue

        if cmd == "/clear":
            history = [Message(role=Role.SYSTEM, content=get_serena_system_prompt())]
            console.print("[dim]Conversation context cleared.[/dim]")
            continue

        if cmd == "/mute":
            muted = True
            console.print("[dim]Serena voice muted for this live session.[/dim]")
            continue

        if cmd == "/speak":
            muted = False
            console.print("[dim]Serena voice enabled for this live session.[/dim]")
            continue

        if cmd == "/model":
            console.print(f"Brain: [cyan]{engine_name} / {model}[/cyan]")
            continue

        history.append(Message(role=Role.USER, content=user_input))

        # Keep context bounded while preserving the system prompt.
        if len(history) > max_history + 1:
            history = [history[0]] + history[-max_history:]

        try:
            result = engine.generate(
                history,
                model=model,
                temperature=config.intelligence.temperature,
                max_tokens=config.intelligence.max_tokens,
            )
            answer = result.get("content", "") if isinstance(result, dict) else str(result)
            answer = answer.strip()
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
            continue
        except Exception as exc:
            console.print(f"[red]Serena error: {exc}[/red]")
            continue

        if not answer:
            console.print("[yellow]Serena returned no answer.[/yellow]")
            continue

        history.append(Message(role=Role.ASSISTANT, content=answer))

        console.print()
        console.print("[bold cyan]Serena>[/bold cyan]")
        console.print(Markdown(answer))
        console.print()

        if not muted:
            _speak_text(
                answer,
                voice_id=voice_id,
                output_dir=output_dir,
                no_play=False,
                no_interrupt=no_interrupt,
                console=console,
            )


__all__ = ["live"]
