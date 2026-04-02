"""``jarvis digest`` — display and play the morning digest."""

from __future__ import annotations

import subprocess
import threading

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.agents.digest_store import DigestStore


def _play_audio(audio_path: str) -> None:
    """Play audio file in background using available system player."""
    players = ["ffplay -nodisp -autoexit", "aplay", "afplay", "paplay"]
    for player in players:
        cmd_parts = player.split() + [audio_path]
        try:
            subprocess.run(
                cmd_parts,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue


@click.command("digest", help="Display and play the morning digest.")
@click.option("--text-only", is_flag=True, help="Print text without audio playback.")
@click.option("--fresh", is_flag=True, help="Re-generate the digest (skip cache).")
@click.option("--history", is_flag=True, help="Show past digests.")
@click.option("--section", type=str, default="", help="Show only a specific section.")
@click.option("--db-path", type=str, default="", help="Path to digest database.")
def digest(
    text_only: bool,
    fresh: bool,
    history: bool,
    section: str,
    db_path: str,
) -> None:
    """Display and optionally play the morning digest."""
    console = Console()
    store = DigestStore(db_path=db_path) if db_path else DigestStore()

    if history:
        past = store.history(limit=10)
        if not past:
            console.print("[dim]No past digests found.[/dim]")
            store.close()
            return
        for artifact in past:
            console.print(
                f"[bold]{artifact.generated_at.strftime('%Y-%m-%d %H:%M')}[/bold]"
                f" — {artifact.model_used} / {artifact.voice_used}"
            )
            console.print(artifact.text[:200] + "...\n")
        store.close()
        return

    if fresh:
        # Trigger on-demand generation
        console.print("[yellow]Generating fresh digest...[/yellow]")
        try:
            from openjarvis.sdk import Jarvis

            with Jarvis() as j:
                result = j.ask("Generate my morning digest", agent="morning_digest")
                console.print(Markdown(result))
        except Exception as exc:
            console.print(f"[red]Failed to generate digest: {exc}[/red]")
        store.close()
        return

    # Try to load today's cached digest
    artifact = store.get_today()
    if artifact is None:
        console.print("[dim]No digest for today. Use --fresh to generate one.[/dim]")
        store.close()
        return

    # Display text
    text = artifact.text
    if section:
        # Try to extract just the requested section
        lines = text.split("\n")
        in_section = False
        section_lines = []
        for line in lines:
            if line.strip().lower().startswith(
                f"## {section.lower()}"
            ) or line.strip().lower().startswith(f"# {section.lower()}"):
                in_section = True
                section_lines.append(line)
            elif in_section and line.strip().startswith("#"):
                break
            elif in_section:
                section_lines.append(line)
        text = "\n".join(section_lines) if section_lines else text

    # Play audio in background while text renders
    audio_path = str(artifact.audio_path)
    if not text_only and audio_path and artifact.audio_path.exists():
        audio_thread = threading.Thread(
            target=_play_audio, args=(audio_path,), daemon=True
        )
        audio_thread.start()

    console.print(Markdown(text))
    store.close()
