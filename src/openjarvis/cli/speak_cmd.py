"""``serena speak`` - speak text through the default audio output."""

from __future__ import annotations

import re
import time
from pathlib import Path

import click
from rich.console import Console

from openjarvis.speech.openai_tts import OpenAITTSBackend


def clean_for_speech(text: str) -> str:
    """Convert markdown-heavy assistant text into natural spoken text."""
    cleaned = text.strip()

    # Remove code fences but keep the content.
    cleaned = cleaned.replace("```", "")

    # Remove common markdown emphasis markers.
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("__", "")
    cleaned = cleaned.replace("* ", "")
    cleaned = cleaned.replace("- ", "")

    # Convert markdown headings to normal phrases.
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)

    # Remove inline code ticks.
    cleaned = cleaned.replace("`", "")

    # Reduce raw URLs for speech.
    cleaned = re.sub(r"https?://\S+", "a link", cleaned)

    # Collapse repeated whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


@click.command()
@click.argument("text", nargs=-1, required=True)
@click.option("--voice", "voice_id", default="nova", help="OpenAI TTS voice to use.")
@click.option("--output-dir", default="outputs/voice", help="Folder for generated audio.")
@click.option("--no-play", is_flag=True, help="Generate audio but do not play it.")
def speak(text: tuple[str, ...], voice_id: str, output_dir: str, no_play: bool) -> None:
    """Speak text using Serena's OpenAI TTS voice."""
    console = Console(stderr=True)

    raw_text = " ".join(text)
    spoken_text = clean_for_speech(raw_text)

    if not spoken_text:
        raise click.ClickException("No speakable text provided.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"serena-speech-{timestamp}.mp3"

    try:
        tts = OpenAITTSBackend()
        result = tts.synthesize(spoken_text, voice_id=voice_id)
        result.save(out_path)
    except Exception as exc:
        raise click.ClickException(f"OpenAI TTS failed: {exc}") from exc

    console.print(f"[green]Saved:[/green] {out_path}")

    if not no_play:
        try:
            import os

            os.startfile(str(out_path.resolve()))  # type: ignore[attr-defined]
            console.print("[green]Playing through Windows default audio output.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Audio saved but playback failed: {exc}[/yellow]")


__all__ = ["speak", "clean_for_speech"]
