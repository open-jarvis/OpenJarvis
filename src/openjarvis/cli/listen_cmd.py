"""``serena listen`` - record microphone audio and transcribe it."""

from __future__ import annotations

import time
from pathlib import Path

import click
import sounddevice as sd
import soundfile as sf
from rich.console import Console
from rich.table import Table

from openjarvis.speech.openai_whisper import OpenAIWhisperBackend


def _print_audio_devices(console: Console) -> None:
    """Print available input and output audio devices."""
    devices = sd.query_devices()

    table = Table(title="Serena Audio Devices")
    table.add_column("Index", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Input Channels", justify="right")
    table.add_column("Output Channels", justify="right")
    table.add_column("Default", style="yellow")

    try:
        default_input, default_output = sd.default.device
    except Exception:
        default_input, default_output = None, None

    for idx, dev in enumerate(devices):
        max_in = int(dev.get("max_input_channels", 0))
        max_out = int(dev.get("max_output_channels", 0))

        marker = ""
        if idx == default_input:
            marker += "default input"
        if idx == default_output:
            marker += " default output" if marker else "default output"

        table.add_row(
            str(idx),
            str(dev.get("name", "")),
            str(max_in),
            str(max_out),
            marker,
        )

    console.print(table)


@click.command()
@click.option("--seconds", default=6.0, type=float, help="Recording duration in seconds.")
@click.option("--samplerate", default=16000, type=int, help="Audio sample rate.")
@click.option("--device", default=None, help="Optional input device name or index.")
@click.option("--output-dir", default="outputs/voice", help="Folder for recorded audio.")
@click.option("--language", default=None, help="Optional transcription language, e.g. en.")
@click.option("--list-devices", is_flag=True, help="List available audio input/output devices.")
def listen(
    seconds: float,
    samplerate: int,
    device: str | None,
    output_dir: str,
    language: str | None,
    list_devices: bool,
) -> None:
    """Record from the default microphone and transcribe with OpenAI Whisper."""
    console = Console(stderr=True)

    if list_devices:
        _print_audio_devices(console)
        return

    if seconds <= 0:
        raise click.ClickException("Recording duration must be greater than zero.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    wav_path = out_dir / f"serena-listen-{timestamp}.wav"

    console.print(f"[cyan]Listening for {seconds:.1f} seconds...[/cyan]")

    try:
        device_arg = int(device) if device and str(device).isdigit() else device
        audio = sd.rec(
            int(seconds * samplerate),
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            device=device_arg,
        )
        sd.wait()
        sf.write(str(wav_path), audio, samplerate)
    except Exception as exc:
        raise click.ClickException(f"Microphone recording failed: {exc}") from exc

    console.print(f"[green]Recorded:[/green] {wav_path}")

    try:
        backend = OpenAIWhisperBackend()
        audio_bytes = wav_path.read_bytes()

        try:
            result = backend.transcribe(audio_bytes, format="wav", language=language)
        except TypeError:
            result = backend.transcribe(audio_bytes, format="wav")

        text = getattr(result, "text", None) or getattr(result, "content", None) or str(result)
        text = text.strip()
    except Exception as exc:
        raise click.ClickException(f"Transcription failed: {exc}") from exc

    if not text:
        console.print("[yellow]No speech detected.[/yellow]")
        return

    console.print("[bold green]Transcript:[/bold green]")
    console.print(text)


__all__ = ["listen"]
