#!/usr/bin/env python3
"""Gym schedule checker — looks up gym hours and class availability.

Run manually::

    uv run python examples/scheduled_ops/gym_scheduler.py --gym "24 Hour Fitness"

Or register as a scheduled task::

    friday scheduler create "Gym schedule check" --type cron --value "0 6 * * 1,3,5"

This script also demonstrates using the ``TaskScheduler`` API directly to
register itself as a recurring task.
"""

from __future__ import annotations

from datetime import datetime, timezone

import click


@click.command()
@click.option(
    "--gym",
    default="Local Gym",
    show_default=True,
    help="Name of the gym to check schedules for.",
)
@click.option(
    "--model",
    default=None,
    help="Model to use for generation (e.g. qwen3:8b).",
)
@click.option(
    "--engine",
    "engine_key",
    default=None,
    help="Engine backend to use (e.g. ollama, vllm).",
)
@click.option(
    "--register/--no-register",
    default=False,
    show_default=True,
    help="Register this script as a recurring task via the scheduler API.",
)
def main(
    gym: str,
    model: str | None,
    engine_key: str | None,
    register: bool,
) -> None:
    """Check gym schedules and class availability."""
    # -- Optional: register as a scheduled task via the scheduler API ----------
    if register:
        _register_task(gym)
        return

    # -- Run the gym schedule check --------------------------------------------
    today = datetime.now(timezone.utc).strftime("%A, %Y-%m-%d")
    prompt = (
        f"Today is {today}. Search for the current schedule and class "
        f"availability at '{gym}'. Include:\n"
        "- Opening and closing hours for today\n"
        "- Available group fitness classes (time, name, instructor if listed)\n"
        "- Any closures, maintenance, or special events\n"
        "- A brief recommendation for the best workout window today"
    )

    try:
        from friday_ai import Friday

        kwargs: dict[str, str | None] = {}
        if model:
            kwargs["model"] = model
        if engine_key:
            kwargs["engine_key"] = engine_key

        j = Friday(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:
        click.echo(
            f"Error: Could not initialize Friday: {exc}\n\n"
            "Make sure an inference engine is running (e.g. `ollama serve`) "
            "and the friday_ai package is installed (`uv sync`).",
            err=True,
        )
        raise SystemExit(1) from exc

    try:
        response = j.ask(
            prompt,
            agent="orchestrator",
            tools=["web_search", "think"],
        )
    except Exception as exc:
        click.echo(f"Error during generation: {exc}", err=True)
        raise SystemExit(1) from exc
    finally:
        j.close()

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  Gym Schedule — {today}")
    click.echo(f"  Gym: {gym}")
    click.echo(f"{'=' * 60}\n")
    click.echo(response)
    click.echo(f"\n{'=' * 60}")


def _register_task(gym: str) -> None:
    """Register this script as a recurring scheduled task."""
    try:
        from friday_ai.scheduler import TaskScheduler
        from friday_ai.scheduler.store import SchedulerStore

        store = SchedulerStore()
        scheduler = TaskScheduler(store)
        task = scheduler.create_task(
            prompt=f"Check gym schedule for '{gym}'",
            schedule_type="cron",
            schedule_value="0 6 * * 1,3,5",
            agent="orchestrator",
            tools="web_search,think",
        )
        click.echo(f"Registered scheduled task: {task.id}")
        click.echo("  Schedule: MWF at 6:00 AM UTC")
        click.echo(f"  Next run: {task.next_run}")
        click.echo(
            "\nStart the scheduler daemon to execute tasks automatically:\n"
            "  friday scheduler start"
        )
    except Exception as exc:
        click.echo(f"Error registering task: {exc}", err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
