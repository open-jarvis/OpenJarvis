"""``serena voice`` - microphone to Serena brain to spoken reply."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import click
import sounddevice as sd
import soundfile as sf
from rich.console import Console

from openjarvis.cli.listen_cmd import _resolve_input_device
from openjarvis.cli.speak_cmd import clean_for_speech
from openjarvis.speech.openai_tts import OpenAITTSBackend
from openjarvis.speech.openai_whisper import OpenAIWhisperBackend
from openjarvis.serena_audio import play_audio_file


def _record_audio(
    *,
    seconds: float,
    samplerate: int,
    device: str | None,
    output_dir: str,
    console: Console,
) -> Path:
    """Record microphone audio and return the WAV path."""
    if seconds <= 0:
        raise click.ClickException("Recording duration must be greater than zero.")

    device_arg = _resolve_input_device(device)
    if device_arg is None:
        raise click.ClickException(
            "No microphone input device found. Plug in a microphone, then run: serena listen --list-devices"
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    wav_path = out_dir / f"serena-voice-{timestamp}.wav"

    console.print(f"[cyan]Listening for {seconds:.1f} seconds...[/cyan]")
    console.print(f"[dim]Input device: {device_arg}[/dim]")

    try:
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

    return wav_path


def _transcribe_audio(path: Path, language: str | None) -> str:
    """Transcribe a WAV file through OpenAI Whisper."""
    backend = OpenAIWhisperBackend()
    audio_bytes = path.read_bytes()

    try:
        result = backend.transcribe(audio_bytes, format="wav", language=language)
    except TypeError:
        result = backend.transcribe(audio_bytes, format="wav")

    text = getattr(result, "text", None) or getattr(result, "content", None) or str(result)
    return text.strip()


def _ask_serena(question: str) -> str:
    """Ask Serena using the existing CLI path so identity/config remain consistent."""
    cmd = [sys.executable, "-m", "openjarvis.cli", "ask", question]

    result = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    answer = (result.stdout or "").strip()
    if not answer and result.stderr:
        answer = result.stderr.strip()

    if result.returncode != 0:
        raise click.ClickException(
            f"Serena ask failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    if not answer:
        raise click.ClickException("Serena did not return an answer.")

    return answer


def _speak_answer(answer: str, *, voice_id: str, output_dir: str, no_play: bool, no_interrupt: bool, console: Console) -> Path:
    """Generate TTS audio for Serena's answer and optionally play it."""
    spoken_text = clean_for_speech(answer)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"serena-voice-answer-{timestamp}.mp3"

    try:
        tts = OpenAITTSBackend()
        speech = tts.synthesize(spoken_text, voice_id=voice_id)
        speech.save(out_path)
    except Exception as exc:
        raise click.ClickException(f"OpenAI TTS failed: {exc}") from exc

    console.print(f"[green]Saved voice reply:[/green] {out_path}")

    if not no_play:
        try:
            console.print("[green]Playing through Windows default audio output.[/green]")
            play_audio_file(out_path, interruptible=not no_interrupt)
        except Exception as exc:
            console.print(f"[yellow]Audio saved but playback failed: {exc}[/yellow]")

    return out_path


@click.command()
@click.option("--seconds", default=6.0, type=float, help="Recording duration in seconds.")
@click.option("--samplerate", default=16000, type=int, help="Audio sample rate.")
@click.option("--device", default=None, help="Optional input device name or index.")
@click.option("--language", default=None, help="Optional transcription language, e.g. en.")
@click.option("--voice", "voice_id", default="nova", help="OpenAI TTS voice to use.")
@click.option("--output-dir", default="outputs/voice", help="Folder for generated audio.")
@click.option("--no-play", is_flag=True, help="Generate audio but do not play it.")
@click.option("--no-interrupt", is_flag=True, help="Disable Enter-to-interrupt during playback.")
def voice(
    seconds: float,
    samplerate: int,
    device: str | None,
    language: str | None,
    voice_id: str,
    output_dir: str,
    no_play: bool,
    no_interrupt: bool,
) -> None:
    """Listen, transcribe, ask Serena, and speak the answer."""
    console = Console(stderr=True)

    wav_path = _record_audio(
        seconds=seconds,
        samplerate=samplerate,
        device=device,
        output_dir=output_dir,
        console=console,
    )

    console.print(f"[green]Recorded:[/green] {wav_path}")

    transcript = _transcribe_audio(wav_path, language)
    if not transcript:
        console.print("[yellow]No speech detected.[/yellow]")
        return

    console.print("[bold green]You said:[/bold green]")
    console.print(transcript)

    answer = _ask_serena(transcript)

    console.print("[bold cyan]Serena:[/bold cyan]")
    console.print(answer)

    _speak_answer(
        answer,
        voice_id=voice_id,
        output_dir=output_dir,
        no_play=no_play,
        no_interrupt=no_interrupt,
        console=console,
    )


__all__ = ["voice"]
