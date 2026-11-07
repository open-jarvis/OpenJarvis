#!/usr/bin/env python3
"""Daily news digest — searches for and summarizes top stories on chosen topics.

Run manually::

    uv run python examples/scheduled_ops/daily_digest.py --topics "AI,robotics"

Or register as a scheduled task::

    friday scheduler create "Run daily digest" --type cron --value "0 9 * * *"
"""

from __future__ import annotations

from datetime import datetime, timezone

import click


@click.command()
@click.option(
    "--topics",
    default="AI,tech",
    show_default=True,
    help="Comma-separated list of topics to include in the digest.",
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
def main(topics: str, model: str | None, engine_key: str | None) -> None:
    """Generate a morning news digest for the given topics."""
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    if not topic_list:
        click.echo("Error: --topics must contain at least one topic.", err=True)
        raise SystemExit(1)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        f"Today is {today}. Search for and summarize the top news stories on "
        f"the following topics: {', '.join(topic_list)}. "
        "For each topic, provide 3-5 bullet points covering the most important "
        "developments. End with a one-paragraph outlook for the day."
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
    click.echo(f"  Daily Digest — {today}")
    click.echo(f"  Topics: {', '.join(topic_list)}")
    click.echo(f"{'=' * 60}\n")
    click.echo(response)
    click.echo(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
