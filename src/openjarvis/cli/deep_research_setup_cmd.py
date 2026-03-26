"""``jarvis deep-research-setup`` — auto-detect local sources, ingest, and chat.

Walks the user through connecting local data sources (Apple Notes, iMessage,
Obsidian), ingesting them into a shared KnowledgeStore, and launching an
interactive Deep Research chat session with Qwen3.5 via Ollama.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table

from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.sync_engine import SyncEngine
from openjarvis.core.config import DEFAULT_CONFIG_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_NOTES_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.com.apple.notes"
    / "NoteStore.sqlite"
)

_DEFAULT_IMESSAGE_DB = Path.home() / "Library" / "Messages" / "chat.db"

_OLLAMA_MODEL = "qwen3.5:4b"

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_local_sources(
    *,
    notes_db_path: Optional[Path] = None,
    imessage_db_path: Optional[Path] = None,
    obsidian_vault_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return a list of available local sources with their config.

    Each entry is a dict with keys: ``connector_id``, ``display_name``,
    ``config`` (kwargs for the connector constructor).
    """
    sources: List[Dict[str, Any]] = []

    notes_path = notes_db_path or _DEFAULT_NOTES_DB
    if notes_path.exists():
        sources.append({
            "connector_id": "apple_notes",
            "display_name": "Apple Notes",
            "config": {"db_path": str(notes_path)},
        })

    imessage_path = imessage_db_path or _DEFAULT_IMESSAGE_DB
    if imessage_path.exists():
        sources.append({
            "connector_id": "imessage",
            "display_name": "iMessage",
            "config": {"db_path": str(imessage_path)},
        })

    if obsidian_vault_path and obsidian_vault_path.is_dir():
        sources.append({
            "connector_id": "obsidian",
            "display_name": "Obsidian / Markdown",
            "config": {"vault_path": str(obsidian_vault_path)},
        })

    return sources


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _instantiate_connector(connector_id: str, config: Dict[str, Any]) -> Any:
    """Lazily import and instantiate a connector by ID."""
    if connector_id == "apple_notes":
        from openjarvis.connectors.apple_notes import AppleNotesConnector
        return AppleNotesConnector(db_path=config.get("db_path", ""))
    elif connector_id == "imessage":
        from openjarvis.connectors.imessage import IMessageConnector
        return IMessageConnector(db_path=config.get("db_path", ""))
    elif connector_id == "obsidian":
        from openjarvis.connectors.obsidian import ObsidianConnector
        return ObsidianConnector(vault_path=config.get("vault_path", ""))
    else:
        msg = f"Unknown connector: {connector_id}"
        raise ValueError(msg)


def ingest_sources(
    sources: List[Dict[str, Any]],
    store: KnowledgeStore,
    *,
    state_db: str = "",
) -> int:
    """Connect and ingest all sources into the KnowledgeStore.

    Parameters
    ----------
    state_db:
        Path for the SyncEngine checkpoint database.  Defaults to
        ``~/.openjarvis/sync_state.db`` when empty.

    Returns total chunks indexed across all sources.
    """
    pipeline = IngestionPipeline(store)
    engine = SyncEngine(pipeline, state_db=state_db)
    total = 0
    for src in sources:
        connector = _instantiate_connector(src["connector_id"], src["config"])
        chunks = engine.sync(connector)
        total += chunks
    return total


# ---------------------------------------------------------------------------
# Chat launch
# ---------------------------------------------------------------------------


def _launch_chat(store: KnowledgeStore, console: Console) -> None:
    """Start an interactive Deep Research chat session."""
    from openjarvis.agents.deep_research import DeepResearchAgent
    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool

    console.print("\n[bold]Setting up Deep Research agent...[/bold]")

    # Engine
    engine = OllamaEngine()
    if not engine.health():
        console.print(
            "[red]Ollama is not running.[/red] Start it with: "
            "[bold]ollama serve[/bold]"
        )
        return

    models = engine.list_models()
    if _OLLAMA_MODEL not in models and f"{_OLLAMA_MODEL}:latest" not in models:
        base_name = _OLLAMA_MODEL.split(":")[0]
        matching = [m for m in models if m.startswith(base_name)]
        if not matching:
            console.print(
                f"[yellow]Model {_OLLAMA_MODEL} not found.[/yellow] "
                f"Pull it with: [bold]ollama pull {_OLLAMA_MODEL}[/bold]"
            )
            return

    # Retriever + tool
    retriever = TwoStageRetriever(store)
    search_tool = KnowledgeSearchTool(retriever=retriever)

    # Agent
    agent = DeepResearchAgent(
        engine=engine,
        model=_OLLAMA_MODEL,
        tools=[search_tool],
        interactive=True,
    )

    console.print(
        f"[green]Ready![/green] Using [bold]{_OLLAMA_MODEL}[/bold] via Ollama.\n"
        "Type your research question. Type [bold]/quit[/bold] to exit.\n"
    )

    # REPL
    while True:
        try:
            query = console.input("[bold blue]research>[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not query:
            continue
        if query.lower() in ("/quit", "/exit", "quit", "exit"):
            break

        try:
            result = agent.run(query)
            console.print(f"\n{result.content}\n")
            if result.metadata and result.metadata.get("sources"):
                console.print("[dim]Sources:[/dim]")
                for s in result.metadata["sources"]:
                    console.print(f"  [dim]- {s}[/dim]")
                console.print()
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error: {exc}[/red]\n")


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("deep-research-setup")
@click.option(
    "--obsidian-vault",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Path to an Obsidian vault directory.",
)
@click.option("--skip-chat", is_flag=True, help="Ingest only, don't launch chat.")
def deep_research_setup(obsidian_vault: Optional[str], skip_chat: bool) -> None:
    """Auto-detect local data sources, ingest, and launch Deep Research chat."""
    console = Console()
    console.print("\n[bold]Deep Research Setup[/bold]\n")

    # 1. Detect
    vault_path = Path(obsidian_vault) if obsidian_vault else None
    sources = detect_local_sources(obsidian_vault_path=vault_path)

    if not sources:
        console.print(
            "[yellow]No local data sources detected.[/yellow]\n"
            "On macOS, ensure Full Disk Access is granted in "
            "System Settings > Privacy & Security."
        )
        sys.exit(1)

    # 2. Confirm
    table = Table(title="Detected Sources")
    table.add_column("Source", style="bold")
    table.add_column("Status", style="green")
    for src in sources:
        table.add_row(src["display_name"], "ready")
    console.print(table)
    console.print()

    if not click.confirm("Ingest these sources?", default=True):
        sys.exit(0)

    # 3. Ingest
    db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(str(db_path))

    console.print("\n[bold]Ingesting...[/bold]")
    for src in sources:
        connector = _instantiate_connector(src["connector_id"], src["config"])
        pipeline = IngestionPipeline(store)
        engine = SyncEngine(pipeline)
        chunks = engine.sync(connector)
        console.print(f"  {src['display_name']}: [green]{chunks} chunks[/green]")

    total = store.count()
    console.print(
        f"\n[bold green]Done![/bold green] {total} total chunks in {db_path}\n"
    )

    # 4. Chat
    if skip_chat:
        return

    _launch_chat(store, console)
