"""``serena say`` - ask Serena a question and speak the answer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from openjarvis.cli.speak_cmd import clean_for_speech
from openjarvis.speech.openai_tts import OpenAITTSBackend
from openjarvis.serena_audio import play_audio_file


@click.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--voice", "voice_id", default="nova", help="OpenAI TTS voice to use.")
@click.option("--output-dir", default="outputs/voice", help="Folder for generated audio.")
@click.option("--no-play", is_flag=True, help="Generate audio but do not play it.")
@click.option("--no-interrupt", is_flag=True, help="Disable Enter-to-interrupt during playback.")
def say(query: tuple[str, ...], voice_id: str, output_dir: str, no_play: bool, no_interrupt: bool) -> None:
    """Ask Serena a question, print the answer, and speak it."""
    console = Console(stderr=True)
    question = " ".join(query).strip()

    if not question:
        raise click.ClickException("No question provided.")

    # Reuse Serena's working ask command so identity, model config, and agent defaults stay consistent.
    cmd = [sys.executable, "-m", "openjarvis.cli", "ask", question]

    result = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    answer = (result.stdout or "").strip()

    # Some Rich/click output may appear on stderr depending on the command path.
    if not answer and result.stderr:
        answer = result.stderr.strip()

    if result.returncode != 0:
        raise click.ClickException(
            f"Serena ask failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    if not answer:
        raise click.ClickException("Serena did not return a speakable answer.")

    console.print(answer)

    spoken_text = clean_for_speech(answer)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    import time

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"serena-say-{timestamp}.mp3"

    try:
        tts = OpenAITTSBackend()
        speech = tts.synthesize(spoken_text, voice_id=voice_id)
        speech.save(out_path)
    except Exception as exc:
        raise click.ClickException(f"OpenAI TTS failed: {exc}") from exc

    console.print(f"[green]Saved:[/green] {out_path}")

    if not no_play:
        try:
            console.print("[green]Playing through Windows default audio output.[/green]")
            play_audio_file(out_path, interruptible=not no_interrupt)
        except Exception as exc:
            console.print(f"[yellow]Audio saved but playback failed: {exc}[/yellow]")


__all__ = ["say"]
