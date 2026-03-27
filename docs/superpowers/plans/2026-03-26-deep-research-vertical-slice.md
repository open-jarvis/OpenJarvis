# Deep Research Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the full Deep Research experience working end-to-end on a MacBook with real data — connect local sources, ingest, retrieve, and run the DeepResearchAgent with Qwen3.5 4B via Ollama producing cited research reports.

**Architecture:** Fix the Apple Notes protobuf extraction test, build a `jarvis deep-research-setup` CLI command that auto-detects local sources (Apple Notes, iMessage, Obsidian), ingests them into a shared KnowledgeStore, and launches an interactive chat session with the DeepResearchAgent. Then wire the missing API router so the desktop wizard UI works too.

**Tech Stack:** Python 3.10+, Click (CLI), SQLite/FTS5, Ollama (Qwen3.5 4B), ColBERT (optional reranking), React/Tauri (wizard smoke test)

---

### Task 1: Fix Apple Notes test

**Files:**
- Modify: `src/openjarvis/connectors/apple_notes.py` (lines 73-103, `_extract_text_from_zdata`)
- Modify: `tests/connectors/test_apple_notes.py` (lines 42-58, test data + lines 127-140, assertion)

The `_extract_text_from_zdata` function currently strips protobuf control bytes but not HTML tags. The test creates fake notes with HTML content. Real Apple Notes uses protobuf. Fix: strip HTML tags too (handles both formats gracefully), and update the test data to use protobuf-like content that exercises the actual code path.

- [ ] **Step 1: Read current files**

Read both files to confirm the exact current state (there are uncommitted changes from the earlier session):

```bash
git diff src/openjarvis/connectors/apple_notes.py
git diff tests/connectors/test_apple_notes.py
```

- [ ] **Step 2: Update `_extract_text_from_zdata` to also strip HTML tags**

In `src/openjarvis/connectors/apple_notes.py`, the function should strip HTML tags after stripping protobuf bytes. This handles both real protobuf data and HTML test data. Edit the function:

```python
def _extract_text_from_zdata(zdata: bytes) -> str:
    """Decompress gzip bytes and extract plain text from the protobuf payload.

    Parameters
    ----------
    zdata:
        Raw bytes from the ``ZDATA`` column — gzip-compressed protobuf
        (``com.apple.notes.ICNote``).

    Returns
    -------
    str
        Plain text with protobuf control bytes stripped.  Returns an empty
        string if decompression fails.
    """
    try:
        raw = gzip.decompress(zdata)
    except Exception:  # noqa: BLE001
        return ""

    text = raw.decode("utf-8", errors="replace")
    # Strip HTML tags (older Notes versions or test data may contain HTML)
    text = re.sub(r"<[^>]+>", "", text)
    # Strip non-printable control bytes and U+FFFD replacement chars that
    # come from the protobuf wire format.
    cleaned = re.sub(r"[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffd]+", " ", text)
    # Collapse whitespace runs
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    # Strip short leading protobuf varint artifacts (e.g. "3 3 " or "b b ")
    cleaned = re.sub(r"^(?:[a-z0-9] ){1,4}", "", cleaned)
    return cleaned.strip()
```

- [ ] **Step 3: Run the Apple Notes tests**

```bash
uv run pytest tests/connectors/test_apple_notes.py -v --tb=short
```

Expected: All 9 tests PASS (including `test_sync_decompresses_content`).

- [ ] **Step 4: Run the iMessage tests too (regression check)**

```bash
uv run pytest tests/connectors/test_imessage.py -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/apple_notes.py tests/connectors/test_apple_notes.py
git commit -m "fix: Apple Notes protobuf extraction handles HTML too, fix ZTITLE1 column"
```

---

### Task 2: Build `jarvis deep-research-setup` CLI command

**Files:**
- Create: `src/openjarvis/cli/deep_research_setup_cmd.py`
- Modify: `src/openjarvis/cli/__init__.py` (add command registration)
- Test: `tests/cli/test_deep_research_setup.py`

This is the core of the vertical slice — a single command that auto-detects local sources, ingests data, and drops you into a research chat.

- [ ] **Step 1: Write the test file**

Create `tests/cli/test_deep_research_setup.py`:

```python
"""Tests for the deep-research-setup CLI command."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_fake_notes_db(db_path: Path) -> None:
    """Create a minimal Apple Notes SQLite database."""
    import gzip

    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTITLE1 TEXT,
            ZMODIFICATIONDATE REAL,
            ZIDENTIFIER TEXT,
            ZNOTE INTEGER
        );
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZDATA BLOB,
            ZNOTE INTEGER
        );
    """)
    content = gzip.compress(b"Test note about meetings")
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES (1, NULL, 'Test Note', 694310400.0, 'n1', 1)"
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (1, ?, 1)", (content,))
    conn.commit()
    conn.close()


def _create_fake_imessage_db(db_path: Path) -> None:
    """Create a minimal iMessage SQLite database."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT, display_name TEXT);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER,
            date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test Chat')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute("INSERT INTO message VALUES (1, 'Hello from test', 1, 694310400000000000, 0)")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detect_local_sources(tmp_path: Path) -> None:
    """Auto-detection finds Apple Notes and iMessage when DBs exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    notes_db = tmp_path / "NoteStore.sqlite"
    imessage_db = tmp_path / "chat.db"
    _create_fake_notes_db(notes_db)
    _create_fake_imessage_db(imessage_db)

    sources = detect_local_sources(
        notes_db_path=notes_db,
        imessage_db_path=imessage_db,
        obsidian_vault_path=None,
    )
    ids = [s["connector_id"] for s in sources]
    assert "apple_notes" in ids
    assert "imessage" in ids


def test_detect_skips_missing_sources(tmp_path: Path) -> None:
    """Auto-detection skips sources whose files don't exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    sources = detect_local_sources(
        notes_db_path=tmp_path / "nonexistent.sqlite",
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=None,
    )
    assert len(sources) == 0


def test_detect_includes_obsidian_when_vault_exists(tmp_path: Path) -> None:
    """Auto-detection includes Obsidian when vault path exists."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Hello")

    sources = detect_local_sources(
        notes_db_path=tmp_path / "nonexistent.sqlite",
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=vault,
    )
    ids = [s["connector_id"] for s in sources]
    assert "obsidian" in ids


def test_ingest_sources(tmp_path: Path) -> None:
    """ingest_sources connects and ingests documents into KnowledgeStore."""
    from openjarvis.cli.deep_research_setup_cmd import detect_local_sources, ingest_sources
    from openjarvis.connectors.store import KnowledgeStore

    notes_db = tmp_path / "NoteStore.sqlite"
    _create_fake_notes_db(notes_db)

    sources = detect_local_sources(
        notes_db_path=notes_db,
        imessage_db_path=tmp_path / "nonexistent.db",
        obsidian_vault_path=None,
    )

    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(str(db_path))
    total = ingest_sources(sources, store)

    assert total > 0
    assert store.count() > 0
    store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/cli/test_deep_research_setup.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError: No module named 'openjarvis.cli.deep_research_setup_cmd'`

- [ ] **Step 3: Create the CLI command module**

Create `src/openjarvis/cli/deep_research_setup_cmd.py`:

```python
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
) -> int:
    """Connect and ingest all sources into the KnowledgeStore.

    Returns total chunks indexed across all sources.
    """
    pipeline = IngestionPipeline(store)
    engine = SyncEngine(pipeline)
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
        # Check without tag too
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

    console.print(f"\n[bold green]Done![/bold green] {store.count()} total chunks in {db_path}\n")

    # 4. Chat
    if skip_chat:
        return

    _launch_chat(store, console)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/cli/test_deep_research_setup.py -v --tb=short
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Register the command in CLI __init__.py**

In `src/openjarvis/cli/__init__.py`, add the import and registration alongside the existing commands.

Add the import near the other CLI imports:

```python
from openjarvis.cli.deep_research_setup_cmd import deep_research_setup
```

Add the registration near the other `cli.add_command()` calls:

```python
cli.add_command(deep_research_setup, "deep-research-setup")
```

- [ ] **Step 6: Verify the command is discoverable**

```bash
uv run jarvis --help | grep deep-research
```

Expected: `deep-research-setup` appears in the command list.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/cli/deep_research_setup_cmd.py tests/cli/test_deep_research_setup.py src/openjarvis/cli/__init__.py
git commit -m "feat: add jarvis deep-research-setup CLI command"
```

---

### Task 3: Wire connectors API router into FastAPI app

**Files:**
- Modify: `src/openjarvis/server/app.py`

The `connectors_router.py` already has all 6 endpoints implemented. It was never registered in the FastAPI app. This is a one-line fix.

- [ ] **Step 1: Read app.py to find where routers are included**

```bash
grep -n "include_router" src/openjarvis/server/app.py
```

Identify the section where `app.include_router(router)` and `app.include_router(dashboard_router)` are called.

- [ ] **Step 2: Add the connectors router import and registration**

Add the import at the top of `app.py` with the other router imports:

```python
from openjarvis.server.connectors_router import create_connectors_router
```

Add the router registration in the same block as the other `app.include_router()` calls:

```python
app.include_router(create_connectors_router())
```

- [ ] **Step 3: Verify the endpoints are now exposed**

```bash
uv run python3 -c "
from openjarvis.server.app import create_app
from openjarvis.engine.ollama import OllamaEngine

engine = OllamaEngine()
app = create_app(engine, 'test')
routes = [r.path for r in app.routes]
connector_routes = [r for r in routes if 'connector' in r]
print(f'Connector routes: {connector_routes}')
assert any('connector' in r for r in routes), 'No connector routes found!'
print('PASS: Connectors router is registered')
"
```

Expected: Lists `/connectors`, `/connectors/{connector_id}`, etc. and prints PASS.

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/server/app.py
git commit -m "fix: register connectors API router in FastAPI app"
```

---

### Task 4: End-to-end test with real data

**Files:** None (manual testing)

This is the live validation. We pull the Ollama model, run the setup command, and test the Deep Research agent with real personal data.

- [ ] **Step 1: Ensure Ollama is running and pull the model**

```bash
ollama list
ollama pull qwen3.5:4b
```

Expected: Model downloaded. If Ollama isn't running, start it with `ollama serve &`.

- [ ] **Step 2: Run the deep research setup**

```bash
uv run jarvis deep-research-setup
```

Expected output:
```
Deep Research Setup

  Detected Sources
┌──────────────┬────────┐
│ Source       │ Status │
├──────────────┼────────┤
│ Apple Notes  │ ready  │
│ iMessage     │ ready  │
└──────────────┴────────┘

Ingest these sources? [Y/n]: Y

Ingesting...
  Apple Notes: ~100 chunks
  iMessage: ~52000 chunks

Done! ~52100 total chunks in ~/.openjarvis/knowledge.db

Setting up Deep Research agent...
Ready! Using qwen3.5:4b via Ollama.
Type your research question. Type /quit to exit.

research>
```

If iMessage ingestion is too slow (52K messages), you can Ctrl+C and re-run with a smaller dataset — we can add a `--limit` flag later.

- [ ] **Step 3: Test retrieval quality with 3 queries**

At the `research>` prompt, try:

1. A person's name who appears in both Apple Notes and iMessage
2. A topic from your notes (e.g. "Georgia Tech" which appeared in Apple Notes)
3. A time-bounded query like "what messages did I send last week"

Evaluate: Does the agent use `knowledge_search`? Does it cite sources? Does it make multiple hops?

- [ ] **Step 4: Document results**

Note: query, response quality, number of tool calls, latency, and any errors. This informs whether we need a larger model or retrieval tuning.

---

### Task 5: Smoke test wizard UI

**Files:**
- None (manual testing)

- [ ] **Step 1: Start the FastAPI server**

```bash
uv run jarvis serve --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Open the frontend dev server**

In a second terminal:

```bash
cd frontend && npm run dev
```

Expected: Vite dev server starts at `http://localhost:5173`.

- [ ] **Step 3: Walk through the wizard**

Open `http://localhost:5173` in a browser. The setup wizard should:
1. Show the source picker with Apple Notes, iMessage, etc.
2. Allow connecting local sources (click → instant green checkmark for local auth types)
3. Show the ingest dashboard with progress polling from `/v1/connectors/{id}/sync`
4. Land on the "Ready" screen

Note any errors — the frontend was built on a remote server and never build-tested until now.

- [ ] **Step 4: Commit any fixes needed**

If frontend or API fixes are required, commit them:

```bash
git add -A
git commit -m "fix: wizard UI smoke test fixes"
```

---

### Task 6: Run full test suite (regression check)

**Files:** None

- [ ] **Step 1: Run all connector + agent tests**

```bash
uv run pytest tests/connectors/ tests/agents/test_deep_research.py tests/agents/test_deep_research_integration.py tests/agents/test_channel_agent.py tests/agents/test_channel_agent_integration.py tests/cli/test_deep_research_setup.py -v --tb=short
```

Expected: All tests PASS (220+ existing + 4 new from Task 2).

- [ ] **Step 2: Run linter**

```bash
uv run ruff check src/openjarvis/cli/deep_research_setup_cmd.py src/openjarvis/server/app.py src/openjarvis/connectors/apple_notes.py
```

Expected: No errors.

- [ ] **Step 3: Commit and push**

```bash
git push origin feat/deep-research-setup
```
