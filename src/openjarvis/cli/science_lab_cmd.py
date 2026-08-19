"""``jarvis science-lab`` — chemistry/materials-science reasoning from the CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.core.config import load_config


def _resolve_engine_and_model(config, explicit_model: str = ""):
    from openjarvis.engine import get_engine

    resolved = get_engine(config, model=explicit_model or None)
    if resolved is None:
        raise click.ClickException(
            "No inference engine is available. Run `jarvis doctor` to diagnose."
        )
    _key, engine = resolved
    model_name = (
        explicit_model or config.science_lab.model or config.intelligence.default_model
    )
    if not model_name:
        models = engine.list_models()
        model_name = models[0] if models else "default"
    return engine, model_name


def _build_agent(config, explicit_model: str = "", db_path: str = ""):
    import openjarvis.agents  # noqa: F401 — trigger registration
    from openjarvis.core.registry import AgentRegistry

    engine, model_name = _resolve_engine_and_model(config, explicit_model)
    agent_cls = AgentRegistry.get("science_lab")
    return agent_cls(
        engine,
        model_name,
        min_hypotheses=config.science_lab.min_hypotheses,
        max_hypotheses=config.science_lab.max_hypotheses,
        safety_llm_fallback=config.science_lab.safety_llm_fallback,
        db_path=db_path or config.science_lab.db_path,
    )


@click.group("science-lab", help="Chemistry/materials-science reasoning (Science Lab).")
def science_lab() -> None:
    pass


@science_lab.command("analyze", help="Analyze a materials/chemistry objective.")
@click.argument("description")
@click.option("--model", type=str, default="", help="Override the model used.")
@click.option(
    "--save",
    "project_name",
    type=str,
    default="",
    help="Save the result as a named project.",
)
def analyze(description: str, model: str, project_name: str) -> None:
    console = Console()
    config = load_config()
    agent = _build_agent(config, explicit_model=model)
    result = agent.run(description, project_name=project_name or None)

    for label, text in result.metadata.get("reasoning_summary", []):
        console.print(f"[bold cyan]{label}[/bold cyan]")
        console.print(text)
        console.print()

    if result.metadata.get("refused"):
        console.print(f"[red]{result.content}[/red]")
        return

    confidence = result.metadata.get("confidence", {})
    if confidence:
        console.print(f"[bold]CONFIDENCE[/bold]  {confidence.get('rendered', '')}")
        console.print(f"[dim]Base: {confidence.get('basis', '')}[/dim]")

    if project_name:
        console.print(f"\n[green]Saved as project '{project_name}'.[/green]")


@science_lab.command("list", help="List saved science projects.")
@click.option(
    "--db-path", type=str, default="", help="Path to the science_lab database."
)
def list_projects(db_path: str) -> None:
    console = Console()
    config = load_config()
    from openjarvis.science_lab.store import ScienceProjectStore

    store = ScienceProjectStore(db_path=db_path or config.science_lab.db_path)
    projects = store.list_projects()
    store.close()
    if not projects:
        console.print("[dim]No saved projects.[/dim]")
        return
    for p in projects:
        console.print(f"[bold]{p.name}[/bold] — {p.objective}")
        console.print(f"  [dim]updated {p.updated_at.isoformat()}[/dim]")


@science_lab.command("show", help="Show a saved science project.")
@click.argument("name")
@click.option(
    "--db-path", type=str, default="", help="Path to the science_lab database."
)
def show(name: str, db_path: str) -> None:
    console = Console()
    config = load_config()
    from openjarvis.science_lab.store import ScienceProjectStore

    store = ScienceProjectStore(db_path=db_path or config.science_lab.db_path)
    project = store.get(name)
    store.close()
    if project is None:
        console.print(f"[red]No project named '{name}'.[/red]")
        return

    console.print(f"[bold]Projeto:[/bold] {project.name}")
    console.print(f"[bold]Objetivo:[/bold] {project.objective}\n")
    console.print("[bold]Propriedades desejadas:[/bold]")
    for p in project.target_properties:
        console.print(f"  - {p.name}: {p.target_value} {p.unit}".rstrip())
    console.print("\n[bold]Hipóteses:[/bold]")
    for h in project.hypotheses:
        console.print(f"  {h.id}: {h.mechanism}")
    console.print("\n[bold]Simulações:[/bold]")
    for s in project.simulations:
        console.print(f"  {s.quantity} = {s.value:.4g} {s.unit} [{s.basis}]")
    console.print(f"\n[bold]Observações:[/bold]\n{project.notes}")


__all__ = ["science_lab"]
