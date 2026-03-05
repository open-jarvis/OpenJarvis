"""``jarvis feedback`` — trace feedback management CLI."""

from __future__ import annotations

import sys
import time
from typing import Optional

import click
from rich.console import Console


@click.group("feedback")
def feedback_group() -> None:
    """Trace feedback management."""


@feedback_group.command("score")
@click.argument("trace_id")
@click.option(
    "-s", "--score", type=float, required=True,
    help="Feedback score (0.0-1.0).",
)
def feedback_score(trace_id: str, score: float) -> None:
    """Record explicit feedback for a trace."""
    console = Console()

    if not 0.0 <= score <= 1.0:
        console.print("[red]Score must be between 0.0 and 1.0.[/red]")
        sys.exit(1)

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            console.print("[red]No trace database found.[/red]")
            sys.exit(1)

        store = TraceStore(db_path)
        updated = store.update_feedback(trace_id, score)
        store.close()

        if updated:
            console.print(
                f"[green]Recorded score {score} for trace {trace_id}[/green]"
            )
        else:
            console.print(
                f"[yellow]Trace '{trace_id}' not found.[/yellow]"
            )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)


@feedback_group.command("thumbs")
@click.option(
    "--last", is_flag=True, default=False,
    help="Rate the last interaction.",
)
@click.option(
    "--up/--down", "thumbs_up", default=True,
    help="Thumbs up or down.",
)
@click.argument("trace_id", required=False)
def feedback_thumbs(
    last: bool, thumbs_up: bool, trace_id: Optional[str],
) -> None:
    """Rate a trace with thumbs up/down."""
    console = Console()
    score = 1.0 if thumbs_up else 0.0

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            console.print("[red]No trace database found.[/red]")
            sys.exit(1)

        store = TraceStore(db_path)

        if last or trace_id is None:
            # Get the most recent trace
            traces = store.list_traces(limit=1)
            if not traces:
                console.print("[yellow]No traces found.[/yellow]")
                store.close()
                return
            trace_id = traces[0].trace_id

        updated = store.update_feedback(trace_id, score)
        store.close()

        label = "thumbs up" if thumbs_up else "thumbs down"
        if updated:
            console.print(
                f"[green]Recorded {label} for trace {trace_id}[/green]"
            )
        else:
            console.print(
                f"[yellow]Trace '{trace_id}' not found.[/yellow]"
            )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)


@feedback_group.command("evaluate")
@click.option(
    "--since", type=str, default="7d",
    help="Evaluate traces since (e.g. 7d, 24h).",
)
def feedback_evaluate(since: str) -> None:
    """Run LLM judge on recent traces."""
    console = Console()

    # Parse the time duration
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    try:
        unit = since[-1].lower()
        value = float(since[:-1])
        seconds = value * multipliers.get(unit, 86400)
    except (ValueError, IndexError):
        console.print(
            f"[red]Invalid duration '{since}'. Use e.g. 7d, 24h, 30m.[/red]"
        )
        sys.exit(1)

    since_ts = time.time() - seconds
    console.print(
        f"[cyan]Evaluating traces from the last {since}...[/cyan]"
    )

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            console.print("[yellow]No trace database found.[/yellow]")
            return

        store = TraceStore(db_path)
        traces = store.list_traces(since=since_ts)
        store.close()

        console.print(f"  Found {len(traces)} trace(s).")
        if not traces:
            return

        console.print(
            "[yellow]LLM judge evaluation is not yet "
            "fully implemented.[/yellow]"
        )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)


@feedback_group.command("stats")
def feedback_stats() -> None:
    """Show feedback statistics."""
    console = Console()

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.traces.store import TraceStore

        db_path = DEFAULT_CONFIG_DIR / "traces.db"
        if not db_path.exists():
            console.print("[yellow]No trace database found.[/yellow]")
            return

        store = TraceStore(db_path)
        all_traces = store.list_traces(limit=10000)
        store.close()

        scored = [t for t in all_traces if t.feedback is not None]
        total = len(all_traces)
        scored_count = len(scored)
        mean_score = (
            sum(t.feedback for t in scored) / scored_count
            if scored_count > 0
            else 0.0
        )
        positive = sum(1 for t in scored if t.feedback >= 0.5)

        console.print("[bold cyan]Feedback Statistics[/bold cyan]")
        console.print(f"  Total traces:    {total}")
        console.print(f"  With feedback:   {scored_count}")
        console.print(f"  Mean score:      {mean_score:.4f}")
        console.print(f"  Positive (>=0.5): {positive}")
        console.print(f"  Negative (<0.5):  {scored_count - positive}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


__all__ = ["feedback_group"]
