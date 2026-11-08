#!/usr/bin/env python3
"""Weekly code review — summarizes recent commits in a repository.

Run manually::

    uv run python examples/scheduled_ops/code_review.py --repo-path /path/to/repo

Or register as a scheduled task::

    friday scheduler create "Weekly code review" --type cron --value "0 8 * * 1"
"""

from __future__ import annotations

from datetime import datetime, timezone

import click


@click.command()
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    help="Path to the git repository to review.",
)
@click.option(
    "--days",
    default=7,
    show_default=True,
    type=int,
    help="Number of days of commit history to review.",
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
def main(repo_path: str, days: int, model: str | None, engine_key: str | None) -> None:
    """Review recent commits and produce a summary report."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        f"You are a senior code reviewer. Examine the git repository at "
        f"'{repo_path}'. Review the commits from the last {days} days "
        f"(today is {today}).\n\n"
        "Steps:\n"
        "1. Use git_log to list recent commits.\n"
        "2. For notable commits, use git_diff to inspect the changes.\n"
        "3. Use file_read if you need to see full file context.\n"
        "4. Use think to reason about code quality, patterns, and risks.\n\n"
        "Produce a report with:\n"
        "- Summary of activity (number of commits, authors)\n"
        "- Key changes and their purpose\n"
        "- Any potential issues, bugs, or code smells\n"
        "- Suggestions for improvement"
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
            agent="native_react",
            tools=["git_log", "git_diff", "file_read", "think"],
        )
    except Exception as exc:
        click.echo(f"Error during generation: {exc}", err=True)
        raise SystemExit(1) from exc
    finally:
        j.close()

    click.echo(f"\n{'=' * 60}")
    click.echo(f"  Weekly Code Review — {today}")
    click.echo(f"  Repository: {repo_path}")
    click.echo(f"  Period: last {days} days")
    click.echo(f"{'=' * 60}\n")
    click.echo(response)
    click.echo(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
