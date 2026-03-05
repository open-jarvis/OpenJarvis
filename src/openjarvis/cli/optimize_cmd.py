"""``jarvis optimize`` — LLM-driven configuration optimization CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table


@click.group("optimize")
def optimize_group() -> None:
    """LLM-driven configuration optimization."""


@optimize_group.command("run")
@click.option(
    "-c", "--config", "config_path", type=str, default=None,
    help="TOML config file for the optimization run.",
)
@click.option(
    "-b", "--benchmark", type=str, default=None,
    help="Benchmark name (e.g. supergpqa, mmlu-pro).",
)
@click.option(
    "-t", "--trials", type=int, default=20,
    help="Maximum number of trials.",
)
@click.option(
    "--optimizer-model", type=str, default="claude-sonnet-4-6",
    help="Model used by the LLM optimizer.",
)
@click.option(
    "--max-samples", type=int, default=50,
    help="Maximum samples per trial evaluation.",
)
@click.option(
    "--output-dir", type=str, default="results/optimize/",
    help="Directory for trial output files.",
)
def optimize_run(
    config_path: Optional[str],
    benchmark: Optional[str],
    trials: int,
    optimizer_model: str,
    max_samples: int,
    output_dir: str,
) -> None:
    """Run an optimization loop over OpenJarvis configuration."""
    console = Console(stderr=True)

    if config_path is not None:
        try:
            from openjarvis.optimize.config import load_optimize_config
        except ImportError:
            console.print(
                "[red]Optimization framework not available.[/red]"
            )
            sys.exit(1)

        try:
            data = load_optimize_config(config_path)
        except Exception as exc:
            console.print(f"[red]Error loading config: {exc}[/red]")
            sys.exit(1)

        opt_section = data.get("optimize", {})
        benchmark = benchmark or opt_section.get("benchmark", "")
        trials = opt_section.get("max_trials", trials)
        optimizer_model = opt_section.get("optimizer_model", optimizer_model)
        max_samples = opt_section.get("max_samples", max_samples)

    if not benchmark:
        raise click.UsageError(
            "Provide --benchmark/-b or a config file with "
            "[optimize] benchmark = '...'."
        )

    console.print(
        f"[cyan]Starting optimization:[/cyan] "
        f"benchmark={benchmark}, max_trials={trials}"
    )
    console.print(f"[cyan]Optimizer model:[/cyan] {optimizer_model}")
    console.print(f"[cyan]Max samples/trial:[/cyan] {max_samples}")

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.optimize.llm_optimizer import LLMOptimizer
        from openjarvis.optimize.optimizer import OptimizationEngine
        from openjarvis.optimize.search_space import DEFAULT_SEARCH_SPACE
        from openjarvis.optimize.store import OptimizationStore
        from openjarvis.optimize.trial_runner import TrialRunner

        store = OptimizationStore(DEFAULT_CONFIG_DIR / "optimize.db")
        llm_opt = LLMOptimizer(
            search_space=DEFAULT_SEARCH_SPACE,
            optimizer_model=optimizer_model,
        )
        runner = TrialRunner(
            benchmark=benchmark,
            max_samples=max_samples,
            output_dir=output_dir,
        )
        engine = OptimizationEngine(
            search_space=DEFAULT_SEARCH_SPACE,
            llm_optimizer=llm_opt,
            trial_runner=runner,
            store=store,
            max_trials=trials,
        )

        run = engine.run(
            progress_callback=lambda t, m: console.print(
                f"  [dim]Trial {t}/{m} complete[/dim]"
            ),
        )

        store.close()

        console.print("\n[green]Optimization complete.[/green]")
        console.print(f"  Run ID:   {run.run_id}")
        console.print(f"  Status:   {run.status}")
        console.print(f"  Trials:   {len(run.trials)}")
        if run.best_trial is not None:
            console.print(
                f"  Best trial: {run.best_trial.trial_id} "
                f"(accuracy={run.best_trial.accuracy:.4f})"
            )
    except ImportError as exc:
        console.print(
            f"[red]Missing dependency for optimization: {exc}[/red]"
        )
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Optimization failed: {exc}[/red]")
        sys.exit(1)


@optimize_group.command("status")
def optimize_status() -> None:
    """Show optimization run status."""
    console = Console()

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            console.print("[yellow]No optimization runs found.[/yellow]")
            return

        store = OptimizationStore(db_path)
        runs = store.list_runs()
        store.close()

        if not runs:
            console.print("[yellow]No optimization runs found.[/yellow]")
            return

        table = Table(
            title="[bold]Optimization Runs[/bold]",
            border_style="bright_blue",
            title_style="bold cyan",
        )
        table.add_column("Run ID", style="cyan", no_wrap=True)
        table.add_column("Benchmark", style="white")
        table.add_column("Status", style="green")
        table.add_column("Optimizer", style="dim")
        table.add_column("Best Trial", style="bold")

        for run in runs:
            table.add_row(
                run["run_id"],
                run.get("benchmark", ""),
                run.get("status", ""),
                run.get("optimizer_model", ""),
                run.get("best_trial_id", "") or "-",
            )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@optimize_group.command("results")
@click.argument("run_id")
def optimize_results(run_id: str) -> None:
    """Show trial results for an optimization run."""
    console = Console()

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            console.print("[red]No optimization data found.[/red]")
            return

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            console.print(f"[red]Run '{run_id}' not found.[/red]")
            return

        console.print(f"[bold cyan]Optimization Run: {run.run_id}[/bold cyan]")
        console.print(f"  Benchmark: {run.benchmark}")
        console.print(f"  Status:    {run.status}")
        console.print(f"  Trials:    {len(run.trials)}")

        if not run.trials:
            console.print("[yellow]No trials recorded.[/yellow]")
            return

        table = Table(
            title="[bold]Trial Results[/bold]",
            border_style="bright_blue",
        )
        table.add_column("Trial ID", style="cyan", no_wrap=True)
        table.add_column("Accuracy", justify="right", style="bold")
        table.add_column("Latency (s)", justify="right")
        table.add_column("Cost ($)", justify="right")
        table.add_column("Samples", justify="right", style="dim")

        for trial in run.trials:
            table.add_row(
                trial.trial_id,
                f"{trial.accuracy:.4f}",
                f"{trial.mean_latency_seconds:.4f}",
                f"{trial.total_cost_usd:.4f}",
                str(trial.samples_evaluated),
            )

        console.print(table)

        if run.best_trial is not None:
            console.print(
                f"\n[green]Best:[/green] {run.best_trial.trial_id} "
                f"(accuracy={run.best_trial.accuracy:.4f})"
            )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@optimize_group.command("best")
@click.argument("run_id")
@click.option(
    "-o", "--output", type=str, default=None,
    help="Output recipe path (TOML).",
)
def optimize_best(run_id: str, output: Optional[str]) -> None:
    """Export best recipe from an optimization run."""
    console = Console()

    try:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        from openjarvis.optimize.optimizer import OptimizationEngine
        from openjarvis.optimize.store import OptimizationStore

        db_path = DEFAULT_CONFIG_DIR / "optimize.db"
        if not db_path.exists():
            console.print("[red]No optimization data found.[/red]")
            return

        store = OptimizationStore(db_path)
        run = store.get_run(run_id)
        store.close()

        if run is None:
            console.print(f"[red]Run '{run_id}' not found.[/red]")
            return

        if run.best_trial is None:
            console.print("[yellow]No best trial found in this run.[/yellow]")
            return

        output_path = Path(
            output or f"results/optimize/best_{run_id}.toml"
        )
        engine = OptimizationEngine.__new__(OptimizationEngine)
        engine.export_best_recipe(run, output_path)

        console.print(
            f"[green]Best recipe exported to:[/green] {output_path}"
        )
        console.print(
            f"  Trial: {run.best_trial.trial_id} "
            f"(accuracy={run.best_trial.accuracy:.4f})"
        )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@optimize_group.command("personal")
@click.argument("action", type=click.Choice(["synthesize", "run"]))
@click.option(
    "--workflow", type=str, default="default",
    help="Workflow ID for personal optimization.",
)
@click.option(
    "-t", "--trials", type=int, default=10,
    help="Maximum trials for personal optimization.",
)
def optimize_personal(action: str, workflow: str, trials: int) -> None:
    """Personal workflow optimization."""
    console = Console()

    if action == "synthesize":
        console.print(
            f"[cyan]Synthesizing personal benchmarks for "
            f"workflow '{workflow}'...[/cyan]"
        )
        console.print(
            "[yellow]Personal benchmark synthesis is not yet "
            "fully implemented.[/yellow]"
        )
    elif action == "run":
        console.print(
            f"[cyan]Running personal optimization for "
            f"workflow '{workflow}' (max {trials} trials)...[/cyan]"
        )
        console.print(
            "[yellow]Personal optimization is not yet "
            "fully implemented.[/yellow]"
        )


__all__ = ["optimize_group"]
