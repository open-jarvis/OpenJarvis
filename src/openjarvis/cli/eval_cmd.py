"""``jarvis eval`` — evaluation framework CLI commands."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# API key validation helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_PREFIXES = ("claude-",)
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")
_GOOGLE_PREFIXES = ("gemini-",)
_MINIMAX_PREFIXES = ("minimax",)

_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}

# Cheapest model per provider used for the live ping
_PROBE_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "google": "gemini-3.1-flash-lite-preview",
}


def _provider_for_model(model_name: str) -> Optional[str]:
    m = model_name.lower()
    if any(m.startswith(p) for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    if any(m.startswith(p) for p in _OPENAI_PREFIXES):
        return "openai"
    if any(m.startswith(p) for p in _GOOGLE_PREFIXES):
        return "google"
    if any(m.startswith(p) for p in _MINIMAX_PREFIXES):
        return "minimax"
    return None


def _live_ping(provider: str, key: str) -> tuple[bool, str]:
    """Make the smallest possible call to verify a key is accepted."""
    try:
        if provider == "anthropic":
            import anthropic  # type: ignore[import]
            anthropic.Anthropic(api_key=key).messages.create(
                model=_PROBE_MODELS["anthropic"],
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        elif provider == "openai":
            import openai  # type: ignore[import]
            openai.OpenAI(api_key=key).chat.completions.create(
                model=_PROBE_MODELS["openai"],
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
        elif provider == "google":
            from google import genai  # type: ignore[import]
            with genai.Client(api_key=key) as _client:
                _client.models.generate_content(
                    model=_PROBE_MODELS["google"],
                    contents="hi",
                )
        else:
            # No live check available for this provider — trust the key is set
            return True, "key set (no live probe)"
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:100]


def _resolve_key(provider: str) -> Optional[str]:
    key = os.environ.get(_PROVIDER_ENV.get(provider, ""))
    if not key and provider == "google":
        key = os.environ.get("GOOGLE_API_KEY")
    return key or None


def check_api_keys(providers_needed: set[str], console: Console) -> None:
    """Verify API keys for every required provider.

    Prints a status table, then aborts if any key is missing or rejected.
    """
    table = Table(
        title="[bold]API Key Check[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Env Var", style="dim")
    table.add_column("Set", justify="center")
    table.add_column("Live Test", justify="center")
    table.add_column("Details", style="dim")

    all_ok = True
    for provider in sorted(providers_needed):
        env_var = _PROVIDER_ENV.get(provider, "?")
        key = _resolve_key(provider)

        if not key:
            table.add_row(
                provider, env_var, "[red]✗[/red]", "[red]–[/red]", "not set"
            )
            all_ok = False
        else:
            ok, detail = _live_ping(provider, key)
            set_cell = "[green]✓[/green]"
            live_cell = "[green]✓[/green]" if ok else "[red]✗[/red]"
            if not ok:
                all_ok = False
            table.add_row(provider, env_var, set_cell, live_cell, detail)

    console.print(table)

    if not all_ok:
        console.print(
            "[red bold]One or more required API keys are missing or invalid. "
            "Set the env vars above and retry.[/red bold]"
        )
        sys.exit(1)

    console.print("[green]All required API keys verified.[/green]")
    # click.confirm("\nProceed with evaluation?", default=True, abort=True)  # Disabled for non-interactive runs

# Known benchmarks and backends — mirrored from the evals framework so the
# CLI can display them even when the (optional) evals package is not installed.
KNOWN_BENCHMARKS = {
    "supergpqa": {"category": "reasoning", "description": "SuperGPQA multiple-choice"},
    "gpqa": {"category": "reasoning", "description": "GPQA graduate-level MCQ"},
    "mmlu-pro": {"category": "reasoning", "description": "MMLU-Pro multiple-choice"},
    "math500": {"category": "reasoning", "description": "MATH-500 math problems"},
    "natural-reasoning": {"category": "reasoning", "description": "Natural Reasoning"},
    "hle": {"category": "reasoning", "description": "HLE hard challenges"},
    "simpleqa": {"category": "chat", "description": "SimpleQA factual QA"},
    "wildchat": {"category": "chat", "description": "WildChat conversation quality"},
    "ipw": {"category": "chat", "description": "IPW mixed benchmark"},
    "gaia": {"category": "agentic", "description": "GAIA agentic benchmark"},
    "frames": {"category": "rag", "description": "FRAMES multi-hop RAG"},
    "swebench": {"category": "agentic", "description": "SWE-bench code patches"},
    "swefficiency": {"category": "agentic", "description": "SWEfficiency optimization"},
    "terminalbench": {
        "category": "agentic",
        "description": "TerminalBench terminal tasks",
    },
    "terminalbench-native": {
        "category": "agentic",
        "description": "TerminalBench Native (Docker)",
    },
    "email_triage": {
        "category": "use-case",
        "description": "Email triage classification + draft",
    },
    "morning_brief": {
        "category": "use-case",
        "description": "Morning briefing generation",
    },
    "research_mining": {
        "category": "use-case",
        "description": "Research synthesis + accuracy",
    },
    "knowledge_base": {
        "category": "use-case",
        "description": "Document-grounded retrieval QA",
    },
    "coding_task": {
        "category": "use-case",
        "description": "Function-level code generation",
    },
}

KNOWN_BACKENDS = {
    "jarvis-direct": "Engine-level inference (local or cloud)",
    "jarvis-agent": "Agent-level inference with tool calling",
}


@click.group("eval")
def eval_group() -> None:
    """Evaluation framework — benchmark models, agents, and learning."""


@eval_group.command("list")
def eval_list() -> None:
    """List available benchmarks and backends."""
    console = Console()

    bench_table = Table(
        title="[bold]Available Benchmarks[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    bench_table.add_column("Name", style="cyan", no_wrap=True)
    bench_table.add_column("Category", style="white")
    bench_table.add_column("Description")
    for name, info in KNOWN_BENCHMARKS.items():
        bench_table.add_row(name, info["category"], info["description"])
    console.print(bench_table)

    backend_table = Table(
        title="[bold]Available Backends[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    backend_table.add_column("Name", style="cyan", no_wrap=True)
    backend_table.add_column("Description")
    for name, desc in KNOWN_BACKENDS.items():
        backend_table.add_row(name, desc)
    console.print(backend_table)


@eval_group.command("run")
@click.option(
    "-c",
    "--config",
    "config_path",
    default=None,
    type=click.Path(),
    help="TOML config file for suite runs.",
)
@click.option(
    "-b",
    "--benchmark",
    "benchmark",
    default=None,
    help="Benchmark to run (e.g. supergpqa, gaia, frames, wildchat).",
)
@click.option(
    "-m",
    "--model",
    "model",
    default=None,
    help="Model identifier.",
)
@click.option(
    "-n",
    "--max-samples",
    "max_samples",
    type=int,
    default=None,
    help="Maximum samples to evaluate.",
)
@click.option(
    "--backend",
    "backend",
    default="jarvis-direct",
    help="Inference backend (jarvis-direct or jarvis-agent).",
)
@click.option(
    "--agent",
    "agent_name",
    default=None,
    help="Agent name for jarvis-agent backend.",
)
@click.option(
    "-e",
    "--engine",
    "engine_key",
    default=None,
    help="Engine key (ollama, vllm, cloud, ...).",
)
@click.option(
    "--tools",
    "tools",
    default="",
    help="Comma-separated tool names.",
)
@click.option(
    "--telemetry/--no-telemetry",
    "telemetry",
    default=False,
    help="Enable telemetry collection during eval.",
)
@click.option(
    "--gpu-metrics/--no-gpu-metrics",
    "gpu_metrics",
    default=False,
    help="Enable GPU metrics collection.",
)
@click.option(
    "--seed",
    "seed",
    type=int,
    default=42,
    help="Random seed.",
)
@click.option(
    "--temperature",
    "temperature",
    type=float,
    default=0.0,
    help="Generation temperature.",
)
@click.option(
    "--max-tokens",
    "max_tokens",
    type=int,
    default=2048,
    help="Max output tokens.",
)
@click.option(
    "--model-filter",
    "model_filter",
    default=None,
    help="Filter models by name substring (for multi-model configs).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="Output JSONL path.",
)
@click.option(
    "--wandb-project",
    "wandb_project",
    default="",
    help="W&B project name (enables W&B tracking).",
)
@click.option(
    "--wandb-entity",
    "wandb_entity",
    default="",
    help="W&B entity (team or user).",
)
@click.option(
    "--wandb-tags",
    "wandb_tags",
    default="",
    help="Comma-separated W&B tags.",
)
@click.option(
    "--wandb-group",
    "wandb_group",
    default="",
    help="W&B run group.",
)
@click.option(
    "--sheets-id",
    "sheets_spreadsheet_id",
    default="",
    help="Google Sheets spreadsheet ID.",
)
@click.option(
    "--sheets-worksheet",
    "sheets_worksheet",
    default="Results",
    help="Google Sheets worksheet name.",
)
@click.option(
    "--sheets-creds",
    "sheets_credentials_path",
    default="",
    help="Path to Google service account JSON.",
)
@click.option(
    "-v",
    "--verbose",
    "verbose",
    is_flag=True,
    default=False,
    help="Verbose logging.",
)
def eval_run(
    config_path: Optional[str],
    benchmark: Optional[str],
    model: Optional[str],
    max_samples: Optional[int],
    backend: str,
    agent_name: Optional[str],
    engine_key: Optional[str],
    tools: str,
    telemetry: bool,
    gpu_metrics: bool,
    seed: int,
    temperature: float,
    max_tokens: int,
    model_filter: Optional[str],
    output_path: Optional[str],
    wandb_project: str,
    wandb_entity: str,
    wandb_tags: str,
    wandb_group: str,
    sheets_spreadsheet_id: str,
    sheets_worksheet: str,
    sheets_credentials_path: str,
    verbose: bool,
) -> None:
    """Run evaluation benchmarks."""
    console = Console(stderr=True)

    # Config-driven mode: load TOML suite, expand, run all
    if config_path is not None:
        try:
            from openjarvis.evals.core.config import expand_suite, load_eval_config
        except ImportError:
            console.print(
                "[red]Eval framework not available. "
                "Ensure the evals package is importable.[/red]"
            )
            sys.exit(1)

        try:
            suite = load_eval_config(config_path)
            run_configs = expand_suite(suite)
        except Exception as exc:
            console.print(f"[red]Error loading config: {exc}[/red]")
            sys.exit(1)

        # Filter by model name substring if requested
        if model_filter:
            run_configs = [rc for rc in run_configs if model_filter in rc.model]
            if not run_configs:
                console.print(f"[red]No models match filter '{model_filter}'[/red]")
                sys.exit(1)

        console.print(
            f"[cyan]Suite:[/cyan] {suite.meta.name or Path(config_path).stem}"
        )
        console.print(
            f"[cyan]Matrix:[/cyan] {len(suite.models)} model(s) x "
            f"{len(suite.benchmarks)} benchmark(s) = {len(run_configs)} run(s)"
        )

        # Collect all cloud providers needed (models + judge)
        cloud_providers: set[str] = set()
        for rc in run_configs:
            if rc.engine_key in (None, "cloud"):
                p = _provider_for_model(rc.model)
                if p:
                    cloud_providers.add(p)
            # Judge always runs in the cloud
            p = _provider_for_model(rc.judge_model)
            if p:
                cloud_providers.add(p)

        if cloud_providers:
            console.print()
            check_api_keys(cloud_providers, console)
            console.print()

        try:
            from openjarvis.evals.cli import _run_single
        except ImportError:
            console.print("[red]Eval CLI module not available.[/red]")
            sys.exit(1)

        for i, rc in enumerate(run_configs, 1):
            console.print(
                f"\n[bold]Run {i}/{len(run_configs)}:[/bold] "
                f"{rc.benchmark} / {rc.model}"
            )
            try:
                summary = _run_single(rc, console=console)
                console.print(
                    f"  [green]{summary.accuracy:.4f}[/green] "
                    f"({summary.correct}/{summary.scored_samples})"
                )
            except Exception as exc:
                console.print(f"  [red bold]FAILED:[/red bold] {exc}")

        return

    # CLI-driven mode: require --benchmark and --model
    if benchmark is None or model is None:
        raise click.UsageError(
            "Provide either --config/-c for suite mode, "
            "or both --benchmark/-b and --model/-m for single-run mode."
        )

    if benchmark not in KNOWN_BENCHMARKS:
        console.print(f"[yellow]Warning: unknown benchmark '{benchmark}'[/yellow]")

    try:
        from openjarvis.evals.core.types import RunConfig
    except ImportError:
        console.print(
            "[red]Eval framework not available. "
            "Ensure the evals package is importable.[/red]"
        )
        sys.exit(1)

    tool_list = [t.strip() for t in tools.split(",") if t.strip()] if tools else []

    config = RunConfig(
        benchmark=benchmark,
        backend=backend,
        model=model,
        max_samples=max_samples,
        agent_name=agent_name,
        engine_key=engine_key,
        tools=tool_list,
        output_path=output_path,
        seed=seed,
        temperature=temperature,
        max_tokens=max_tokens,
        telemetry=telemetry,
        gpu_metrics=gpu_metrics,
        wandb_project=wandb_project,
        wandb_entity=wandb_entity,
        wandb_tags=wandb_tags,
        wandb_group=wandb_group,
        sheets_spreadsheet_id=sheets_spreadsheet_id,
        sheets_worksheet=sheets_worksheet,
        sheets_credentials_path=sheets_credentials_path,
    )

    # Determine which providers are needed for this single run
    single_providers: set[str] = set()
    if engine_key in (None, "cloud"):
        p = _provider_for_model(model)
        if p:
            single_providers.add(p)
    # Judge defaults to gpt-5-mini (OpenAI)
    single_providers.add("openai")

    console.print()
    check_api_keys(single_providers, console)
    console.print()

    try:
        from openjarvis.evals.cli import _run_single

        console.print(
            f"[cyan]Benchmark:[/cyan] {benchmark}\n"
            f"[cyan]Model:[/cyan]     {model}\n"
            f"[cyan]Backend:[/cyan]   {backend}"
        )
        summary = _run_single(config, console=console)
        console.print(
            f"\n[green]Accuracy: {summary.accuracy:.4f}[/green] "
            f"({summary.correct}/{summary.scored_samples})"
        )
    except ImportError:
        console.print("[red]Eval CLI module not available.[/red]")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)


@eval_group.command("compare")
@click.argument("result_files", nargs=-1, required=True)
@click.option(
    "--metric",
    "metric",
    default="accuracy",
    help="Metric to compare across runs (default: accuracy).",
)
def eval_compare(result_files: tuple[str, ...], metric: str) -> None:
    """Compare results from multiple eval runs."""
    console = Console()

    rows: list[dict] = []
    for path_str in result_files:
        path = Path(path_str)
        summary_path = path.with_suffix(".summary.json")

        if summary_path.exists():
            with open(summary_path) as f:
                data = json.load(f)
            rows.append(
                {
                    "file": path.name,
                    "benchmark": data.get("benchmark", "?"),
                    "model": data.get("model", "?"),
                    "value": data.get(metric, "N/A"),
                    "samples": data.get("total_samples", 0),
                }
            )
        elif path.exists() and path.suffix == ".jsonl":
            # Fall back to reading JSONL and computing metric on-the-fly
            records = []
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            if records:
                if metric == "accuracy":
                    scored = [r for r in records if r.get("is_correct") is not None]
                    correct = [r for r in scored if r["is_correct"]]
                    value = len(correct) / len(scored) if scored else 0.0
                else:
                    values = [
                        r[metric]
                        for r in records
                        if metric in r and r[metric] is not None
                    ]
                    value = sum(values) / len(values) if values else "N/A"
                rows.append(
                    {
                        "file": path.name,
                        "benchmark": records[0].get("benchmark", "?"),
                        "model": records[0].get("model", "?"),
                        "value": value,
                        "samples": len(records),
                    }
                )
        else:
            console.print(f"[yellow]Skipping missing file: {path_str}[/yellow]")

    if not rows:
        console.print("[red]No valid result files found.[/red]")
        return

    table = Table(
        title=f"[bold]Comparison — {metric}[/bold]",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    table.add_column("File", style="dim")
    table.add_column("Benchmark", style="cyan")
    table.add_column("Model", style="green")
    table.add_column(metric.capitalize(), justify="right", style="bold")
    table.add_column("Samples", justify="right", style="dim")

    for row in rows:
        val = row["value"]
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)
        table.add_row(
            row["file"],
            row["benchmark"],
            row["model"],
            val_str,
            str(row["samples"]),
        )

    console.print(table)


@eval_group.command("report")
@click.argument("result_file")
def eval_report(result_file: str) -> None:
    """Generate detailed report from eval results."""
    console = Console()
    path = Path(result_file)

    # Try summary JSON first
    summary_path = path.with_suffix(".summary.json")
    if summary_path.exists():
        with open(summary_path) as f:
            data = json.load(f)

        console.print("[bold cyan]Evaluation Report[/bold cyan]")
        console.print(f"  [cyan]Benchmark:[/cyan] {data.get('benchmark', '?')}")
        console.print(f"  [cyan]Model:[/cyan]     {data.get('model', '?')}")
        console.print(f"  [cyan]Backend:[/cyan]   {data.get('backend', '?')}")
        console.print(
            f"  [cyan]Accuracy:[/cyan]  [bold]{data.get('accuracy', 0.0):.4f}[/bold]"
        )
        console.print(f"  [cyan]Samples:[/cyan]   {data.get('total_samples', 0)}")
        console.print(f"  [cyan]Scored:[/cyan]    {data.get('scored_samples', 0)}")
        console.print(f"  [cyan]Correct:[/cyan]   {data.get('correct', 0)}")
        console.print(f"  [cyan]Errors:[/cyan]    {data.get('errors', 0)}")
        console.print(
            f"  [cyan]Latency:[/cyan]   "
            f"{data.get('mean_latency_seconds', 0.0):.4f}s (mean)"
        )
        console.print(
            f"  [cyan]Cost:[/cyan]      ${data.get('total_cost_usd', 0.0):.6f}"
        )

        # Per-subject breakdown
        per_subject = data.get("per_subject", {})
        if per_subject and len(per_subject) > 1:
            sub_table = Table(
                title="[bold]Per-Subject Breakdown[/bold]",
                border_style="bright_blue",
            )
            sub_table.add_column("Subject", style="cyan")
            sub_table.add_column("Accuracy", justify="right", style="bold")
            sub_table.add_column("Total", justify="right")
            sub_table.add_column("Correct", justify="right", style="green")

            for subj, stats in sorted(per_subject.items()):
                sub_table.add_row(
                    subj,
                    f"{stats.get('accuracy', 0.0):.4f}",
                    str(int(stats.get("total", 0))),
                    str(int(stats.get("correct", 0))),
                )
            console.print(sub_table)

        return

    # Fall back to JSONL file
    if not path.exists():
        console.print(f"[red]File not found: {result_file}[/red]")
        sys.exit(1)

    records: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        console.print("[yellow]No records found in file.[/yellow]")
        return

    scored = [r for r in records if r.get("is_correct") is not None]
    correct = [r for r in scored if r["is_correct"]]
    errors = [r for r in records if r.get("error")]
    accuracy = len(correct) / len(scored) if scored else 0.0

    console.print("[bold cyan]Evaluation Report[/bold cyan]")
    console.print(f"  [cyan]File:[/cyan]      {result_file}")
    console.print(f"  [cyan]Benchmark:[/cyan] {records[0].get('benchmark', '?')}")
    console.print(f"  [cyan]Model:[/cyan]     {records[0].get('model', '?')}")
    console.print(f"  [cyan]Total:[/cyan]     {len(records)}")
    console.print(f"  [cyan]Scored:[/cyan]    {len(scored)}")
    console.print(f"  [cyan]Correct:[/cyan]   {len(correct)}")
    console.print(f"  [cyan]Accuracy:[/cyan]  [bold]{accuracy:.4f}[/bold]")
    console.print(f"  [cyan]Errors:[/cyan]    {len(errors)}")


__all__ = ["eval_group"]
