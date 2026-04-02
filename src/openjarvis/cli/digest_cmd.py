"""``jarvis digest`` — display and play the morning digest."""

from __future__ import annotations

import subprocess
import threading
from typing import Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.agents.digest_store import DigestStore
from openjarvis.core.config import DEFAULT_CONFIG_PATH, load_config


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


def _save_digest_schedule(enabled: bool, cron: str) -> None:
    """Persist digest schedule to config.toml."""
    config_path = DEFAULT_CONFIG_PATH

    # Read existing TOML content (or start fresh)
    content = ""
    if config_path.exists():
        content = config_path.read_text()

    # Check if [digest] section already exists
    lines = content.split("\n")
    new_lines: list[str] = []
    in_digest = False
    digest_written = False

    for line in lines:
        stripped = line.strip()
        # Detect start of [digest] section
        if stripped == "[digest]":
            in_digest = True
            digest_written = True
            new_lines.append("[digest]")
            new_lines.append(f"enabled = {str(enabled).lower()}")
            new_lines.append(f'schedule = "{cron}"')
            continue
        # If inside [digest], skip old enabled/schedule keys
        if in_digest:
            if stripped.startswith("[") and stripped != "[digest]":
                in_digest = False
                new_lines.append(line)
            elif stripped.startswith("enabled") or stripped.startswith("schedule"):
                continue
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not digest_written:
        # Append [digest] section at the end
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("[digest]")
        new_lines.append(f"enabled = {str(enabled).lower()}")
        new_lines.append(f'schedule = "{cron}"')
        new_lines.append("")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(new_lines))


def _create_scheduler_task(cron: str) -> Optional[str]:
    """Create a digest task in the TaskScheduler. Returns task ID or None."""
    try:
        from openjarvis.scheduler.scheduler import TaskScheduler
        from openjarvis.scheduler.store import SchedulerStore

        db_path = DEFAULT_CONFIG_PATH.parent / "scheduler.db"
        store = SchedulerStore(db_path)
        scheduler = TaskScheduler(store)

        # Cancel any existing digest tasks first
        for task in scheduler.list_tasks(status="active"):
            if task.agent == "morning_digest":
                scheduler.cancel_task(task.id)

        task = scheduler.create_task(
            prompt="Generate my morning digest",
            schedule_type="cron",
            schedule_value=cron,
            agent="morning_digest",
        )
        store.close()
        return task.id
    except Exception:
        return None


def _cancel_scheduler_tasks() -> int:
    """Cancel all active digest tasks. Returns count cancelled."""
    try:
        from openjarvis.scheduler.scheduler import TaskScheduler
        from openjarvis.scheduler.store import SchedulerStore

        db_path = DEFAULT_CONFIG_PATH.parent / "scheduler.db"
        store = SchedulerStore(db_path)
        scheduler = TaskScheduler(store)
        count = 0
        for task in scheduler.list_tasks(status="active"):
            if task.agent == "morning_digest":
                scheduler.cancel_task(task.id)
                count += 1
        store.close()
        return count
    except Exception:
        return 0


@click.command("digest", help="Display and play the morning digest.")
@click.option("--text-only", is_flag=True, help="Print text without audio playback.")
@click.option("--fresh", is_flag=True, help="Re-generate the digest (skip cache).")
@click.option("--history", is_flag=True, help="Show past digests.")
@click.option("--section", type=str, default="", help="Show only a specific section.")
@click.option("--db-path", type=str, default="", help="Path to digest database.")
@click.option(
    "--schedule",
    type=str,
    default=None,
    is_eager=True,
    help=(
        'Set cron schedule (e.g. "0 6 * * *"), '
        '"off" to disable, or empty to show status.'
    ),
)
def digest(
    text_only: bool,
    fresh: bool,
    history: bool,
    section: str,
    db_path: str,
    schedule: Optional[str],
) -> None:
    """Display and optionally play the morning digest."""
    console = Console()

    # Handle --schedule flag
    if schedule is not None:
        _handle_schedule(console, schedule)
        return

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


def _handle_schedule(console: Console, schedule: str) -> None:
    """Handle the --schedule option logic."""
    cfg = load_config()
    digest_cfg = cfg.digest

    if schedule == "":
        # Show current schedule status
        status = "enabled" if digest_cfg.enabled else "disabled"
        console.print(f"[bold]Digest schedule:[/bold] {status}")
        console.print(f"  Cron: {digest_cfg.schedule}")
        console.print(f"  Timezone: {digest_cfg.timezone}")
        return

    if schedule.lower() == "off":
        # Disable the schedule
        _save_digest_schedule(enabled=False, cron=digest_cfg.schedule)
        cancelled = _cancel_scheduler_tasks()
        console.print("[yellow]Digest schedule disabled.[/yellow]")
        if cancelled:
            console.print(f"  Cancelled {cancelled} scheduler task(s).")
        return

    # Set a new cron schedule
    _save_digest_schedule(enabled=True, cron=schedule)
    task_id = _create_scheduler_task(schedule)
    console.print(f"[green]Digest schedule set:[/green] {schedule}")
    if task_id:
        console.print(f"  Scheduler task created: {task_id}")
    else:
        console.print(
            "  [dim]Note: scheduler task not created "
            "(start the scheduler separately).[/dim]"
        )
