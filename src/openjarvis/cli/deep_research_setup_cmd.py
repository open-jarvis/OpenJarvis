"""``jarvis deep-research-setup`` — auto-detect local sources, ingest, and chat.

Walks the user through connecting local data sources (Apple Notes, iMessage,
Obsidian), ingesting them into a shared KnowledgeStore, and launching an
interactive Deep Research chat session with Qwen3.5 via Ollama.
"""

from __future__ import annotations

import json
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
        sources.append(
            {
                "connector_id": "apple_notes",
                "display_name": "Apple Notes",
                "config": {"db_path": str(notes_path)},
            }
        )

    imessage_path = imessage_db_path or _DEFAULT_IMESSAGE_DB
    if imessage_path.exists():
        sources.append(
            {
                "connector_id": "imessage",
                "display_name": "iMessage",
                "config": {"db_path": str(imessage_path)},
            }
        )

    if obsidian_vault_path and obsidian_vault_path.is_dir():
        sources.append(
            {
                "connector_id": "obsidian",
                "display_name": "Obsidian / Markdown",
                "config": {"vault_path": str(obsidian_vault_path)},
            }
        )

    return sources


# ---------------------------------------------------------------------------
# Token-based source detection
# ---------------------------------------------------------------------------

_TOKEN_SOURCES = [
    {
        "connector_id": "gmail_imap",
        "display_name": "Gmail (IMAP)",
        "creds_file": "gmail_imap.json",
        "prompt_label": "email:app_password",
    },
    {
        "connector_id": "outlook",
        "display_name": "Outlook / Microsoft 365",
        "creds_file": "outlook.json",
        "prompt_label": "email:app_password",
    },
    {
        "connector_id": "slack",
        "display_name": "Slack",
        "creds_file": "slack.json",
        "prompt_label": "Bot token (xoxb-...)",
    },
    {
        "connector_id": "notion",
        "display_name": "Notion",
        "creds_file": "notion.json",
        "prompt_label": "Integration token (ntn_...)",
    },
    {
        "connector_id": "granola",
        "display_name": "Granola",
        "creds_file": "granola.json",
        "prompt_label": "API key (grn_...)",
    },
]


def detect_token_sources(
    *,
    connectors_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return token-based sources that already have valid credentials."""
    cdir = connectors_dir or (DEFAULT_CONFIG_DIR / "connectors")
    sources: List[Dict[str, Any]] = []

    for ts in _TOKEN_SOURCES:
        creds_file = cdir / ts["creds_file"]
        if not creds_file.exists():
            continue
        try:
            data = json.loads(creds_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not data or not any(v for v in data.values() if v):
            continue
        sources.append(
            {
                "connector_id": ts["connector_id"],
                "display_name": ts["display_name"],
                "config": {},
            }
        )

    return sources


def _prompt_connect_sources(console: Console) -> List[Dict[str, Any]]:
    """Interactively prompt the user to connect token-based sources."""
    connected: List[Dict[str, Any]] = []
    cdir = DEFAULT_CONFIG_DIR / "connectors"
    cdir.mkdir(parents=True, exist_ok=True)

    while True:
        unconnected = [
            ts for ts in _TOKEN_SOURCES if not (cdir / ts["creds_file"]).exists()
        ]
        if not unconnected:
            console.print("[dim]All token sources already connected.[/dim]")
            break

        if not click.confirm("Connect additional sources?", default=False):
            break

        names = [ts["connector_id"] for ts in unconnected]
        labels = [f"{ts['display_name']} ({ts['connector_id']})" for ts in unconnected]
        console.print("Available:")
        for label in labels:
            console.print(f"  {label}")

        choice = click.prompt(
            "Which source?",
            type=click.Choice(names, case_sensitive=False),
        )

        ts = next(t for t in unconnected if t["connector_id"] == choice)
        token = click.prompt(f"Paste your {ts['prompt_label']}")

        connector = _instantiate_connector(choice, {})
        connector.handle_callback(token.strip())
        console.print(f"  [green]{ts['display_name']}: connected![/green]")

        connected.append(
            {
                "connector_id": choice,
                "display_name": ts["display_name"],
                "config": {},
            }
        )

    return connected


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
    elif connector_id == "gmail_imap":
        from openjarvis.connectors.gmail_imap import GmailIMAPConnector

        return GmailIMAPConnector()
    elif connector_id == "outlook":
        from openjarvis.connectors.outlook import OutlookConnector

        return OutlookConnector()
    elif connector_id == "slack":
        from openjarvis.connectors.slack_connector import SlackConnector

        return SlackConnector()
    elif connector_id == "notion":
        from openjarvis.connectors.notion import NotionConnector

        return NotionConnector()
    elif connector_id == "granola":
        from openjarvis.connectors.granola import GranolaConnector

        return GranolaConnector()
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
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    console.print("\n[bold]Setting up Deep Research agent...[/bold]")

    # Engine
    engine = OllamaEngine()
    if not engine.health():
        console.print(
            "[red]Ollama is not running.[/red] Start it with: [bold]ollama serve[/bold]"
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

    # Tools
    retriever = TwoStageRetriever(store)
    tools = [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=_OLLAMA_MODEL),
        ThinkTool(),
    ]

    # Agent
    agent = DeepResearchAgent(
        engine=engine,
        model=_OLLAMA_MODEL,
        tools=tools,
        interactive=True,
    )

    console.print(
        f"[green]Ready![/green] Using [bold]{_OLLAMA_MODEL}[/bold] via Ollama.\n"
        "Tools: knowledge_search, knowledge_sql, scan_chunks, think\n"
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

    # 1. Detect local sources
    vault_path = Path(obsidian_vault) if obsidian_vault else None
    local_sources = detect_local_sources(obsidian_vault_path=vault_path)

    # 2. Detect already-connected token sources
    token_sources = detect_token_sources()

    all_sources = local_sources + token_sources

    # 3. Show what we found
    if all_sources:
        table = Table(title="Detected Sources")
        table.add_column("Source", style="bold")
        table.add_column("Type", style="dim")
        table.add_column("Status", style="green")
        for src in local_sources:
            table.add_row(src["display_name"], "local", "ready")
        for src in token_sources:
            table.add_row(src["display_name"], "token", "connected")
        console.print(table)
        console.print()

    # 4. Offer to connect new token sources
    newly_connected = _prompt_connect_sources(console)
    all_sources.extend(newly_connected)

    if not all_sources:
        console.print(
            "[yellow]No data sources detected or connected.[/yellow]\n"
            "On macOS, ensure Full Disk Access is granted in "
            "System Settings > Privacy & Security."
        )
        sys.exit(1)

    # 5. Confirm and ingest
    if not click.confirm("Ingest these sources?", default=True):
        sys.exit(0)

    db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(str(db_path))

    console.print("\n[bold]Ingesting...[/bold]")
    for src in all_sources:
        try:
            connector = _instantiate_connector(
                src["connector_id"],
                src["config"],
            )
            pipeline = IngestionPipeline(store)
            engine = SyncEngine(pipeline)
            chunks = engine.sync(connector)
            console.print(f"  {src['display_name']}: [green]{chunks} chunks[/green]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"  {src['display_name']}: [red]error: {exc}[/red]")

    total = store.count()
    console.print(
        f"\n[bold green]Done![/bold green] {total} total chunks in {db_path}\n"
    )

    # 6. Chat
    if skip_chat:
        return

    _launch_chat(store, console)
