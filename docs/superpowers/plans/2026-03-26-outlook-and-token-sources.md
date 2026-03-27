# Outlook Connector + Token Source Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize Gmail IMAP to support Outlook, and extend `jarvis deep-research-setup` to detect, connect, and ingest token-based sources (Slack, Notion, Granola, Gmail IMAP, Outlook) alongside local sources.

**Architecture:** Add `imap_host` parameter to `GmailIMAPConnector`, create a thin `OutlookConnector` subclass, then extend the CLI command with `detect_token_sources()` and an interactive connect prompt that saves credentials and ingests all sources in one flow.

**Tech Stack:** Python 3.10+, imaplib, Click, Rich, SQLite/FTS5, pytest

---

### Task 1: Generalize GmailIMAPConnector with `imap_host` parameter

**Files:**
- Modify: `src/openjarvis/connectors/gmail_imap.py`
- Modify: `tests/connectors/test_gmail_imap.py`

- [ ] **Step 1: Read the current test file to understand existing test patterns**

```bash
cat tests/connectors/test_gmail_imap.py
```

- [ ] **Step 2: Add `imap_host` parameter to `GmailIMAPConnector.__init__`**

In `src/openjarvis/connectors/gmail_imap.py`, add a class attribute and constructor parameter:

```python
# Add class attribute after line 84 (after display_name):
_default_imap_host = "imap.gmail.com"

# Change __init__ signature to add imap_host:
def __init__(
    self,
    email_address: str = "",
    app_password: str = "",
    credentials_path: str = "",
    *,
    imap_host: str = "",
    max_messages: int = 500,
) -> None:
    self._email = email_address
    self._password = app_password
    self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
    self._imap_host = imap_host or self._default_imap_host
    self._max_messages = max_messages
    self._items_synced = 0
    self._items_total = 0
```

- [ ] **Step 3: Update `sync()` to use `self._imap_host`**

In `src/openjarvis/connectors/gmail_imap.py`, line 147, change:

```python
# Before:
imap = imaplib.IMAP4_SSL("imap.gmail.com")

# After:
imap = imaplib.IMAP4_SSL(self._imap_host)
```

- [ ] **Step 4: Run existing tests to verify nothing breaks**

```bash
uv run pytest tests/connectors/test_gmail_imap.py -v --tb=short
```

Expected: All existing tests PASS (they mock IMAP so the host doesn't matter).

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/gmail_imap.py
git commit -m "feat: add imap_host parameter to GmailIMAPConnector"
```

---

### Task 2: Create Outlook connector

**Files:**
- Create: `src/openjarvis/connectors/outlook.py`
- Create: `tests/connectors/test_outlook.py`

- [ ] **Step 1: Write the test file**

Create `tests/connectors/test_outlook.py`:

```python
"""Tests for OutlookConnector — thin subclass of GmailIMAPConnector."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core.registry import ConnectorRegistry


def test_outlook_registered() -> None:
    """OutlookConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.outlook import OutlookConnector

    ConnectorRegistry.register_value("outlook", OutlookConnector)
    assert ConnectorRegistry.contains("outlook")
    cls = ConnectorRegistry.get("outlook")
    assert cls.connector_id == "outlook"
    assert cls.display_name == "Outlook / Microsoft 365"


def test_outlook_uses_correct_imap_host() -> None:
    """OutlookConnector defaults to outlook.office365.com."""
    from openjarvis.connectors.outlook import OutlookConnector

    conn = OutlookConnector()
    assert conn._imap_host == "outlook.office365.com"


def test_outlook_auth_url() -> None:
    """auth_url() points to Microsoft security page."""
    from openjarvis.connectors.outlook import OutlookConnector

    conn = OutlookConnector()
    assert "microsoft.com" in conn.auth_url()


def test_outlook_handle_callback(tmp_path: Path) -> None:
    """handle_callback saves email:password credentials."""
    from openjarvis.connectors.outlook import OutlookConnector
    from openjarvis.connectors.oauth import load_tokens

    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    conn.handle_callback("user@outlook.com:mypassword123")

    tokens = load_tokens(creds_path)
    assert tokens is not None
    assert tokens["email"] == "user@outlook.com"
    assert tokens["password"] == "mypassword123"


def test_outlook_is_connected(tmp_path: Path) -> None:
    """is_connected returns True when credentials file has email+password."""
    from openjarvis.connectors.outlook import OutlookConnector

    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    assert conn.is_connected() is False

    conn.handle_callback("user@outlook.com:pass")
    assert conn.is_connected() is True


def test_outlook_sync_source_is_outlook(tmp_path: Path) -> None:
    """Documents yielded by sync() have source='outlook' and doc_id prefix 'outlook:'."""
    from unittest.mock import MagicMock, patch
    from openjarvis.connectors.outlook import OutlookConnector

    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    conn.handle_callback("user@outlook.com:pass")

    # Mock IMAP to return one email
    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [])
    mock_imap.select.return_value = ("OK", [])
    mock_imap.search.return_value = ("OK", [b"1"])

    raw_email = (
        b"From: sender@test.com\r\n"
        b"To: user@outlook.com\r\n"
        b"Subject: Test Email\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <test123@test.com>\r\n"
        b"\r\n"
        b"Hello from Outlook test"
    )
    mock_imap.fetch.return_value = ("OK", [(b"1", raw_email)])
    mock_imap.logout.return_value = ("OK", [])

    with patch("openjarvis.connectors.gmail_imap.imaplib") as mock_imaplib:
        mock_imaplib.IMAP4_SSL.return_value = mock_imap
        mock_imaplib.IMAP4 = type(mock_imap)
        docs = list(conn.sync())

    assert len(docs) == 1
    assert docs[0].source == "outlook"
    assert docs[0].doc_id.startswith("outlook:")
    assert docs[0].title == "Test Email"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/connectors/test_outlook.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError: No module named 'openjarvis.connectors.outlook'`

- [ ] **Step 3: Create the Outlook connector**

Create `src/openjarvis/connectors/outlook.py`:

```python
"""Outlook / Microsoft 365 connector — reads email via IMAP with app password.

Thin subclass of GmailIMAPConnector that defaults to the Outlook IMAP host
and relabels documents with source='outlook'.

Setup: enable 2FA on your Microsoft account, then generate an app password
at https://account.microsoft.com/security
"""

from __future__ import annotations

from typing import Iterator, Optional

from datetime import datetime

from openjarvis.connectors._stubs import Document
from openjarvis.connectors.gmail_imap import GmailIMAPConnector
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "outlook.json"
)


@ConnectorRegistry.register("outlook")
class OutlookConnector(GmailIMAPConnector):
    """Outlook connector using IMAP + app password.

    Inherits all IMAP logic from :class:`GmailIMAPConnector` and overrides
    the IMAP host, credential path, auth URL, and document source labels.
    """

    connector_id = "outlook"
    display_name = "Outlook / Microsoft 365"
    _default_imap_host = "outlook.office365.com"

    def __init__(
        self,
        email_address: str = "",
        app_password: str = "",
        credentials_path: str = "",
        *,
        max_messages: int = 500,
    ) -> None:
        super().__init__(
            email_address,
            app_password,
            credentials_path or _DEFAULT_CREDENTIALS_PATH,
            max_messages=max_messages,
        )

    def auth_url(self) -> str:
        """Return the Microsoft account security page for app passwords."""
        return "https://account.microsoft.com/security"

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        """Sync emails and relabel with source='outlook'."""
        for doc in super().sync(since=since, cursor=cursor):
            doc.source = "outlook"
            doc.doc_id = doc.doc_id.replace("gmail:", "outlook:", 1)
            yield doc
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/connectors/test_outlook.py -v --tb=short
```

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/outlook.py tests/connectors/test_outlook.py
git commit -m "feat: add Outlook connector as IMAP subclass"
```

---

### Task 3: Extend deep-research-setup with token source detection and interactive connect

**Files:**
- Modify: `src/openjarvis/cli/deep_research_setup_cmd.py`
- Modify: `tests/cli/test_deep_research_setup.py`

- [ ] **Step 1: Write tests for token source detection**

Append to `tests/cli/test_deep_research_setup.py`:

```python
def test_detect_token_sources_finds_connected(tmp_path: Path) -> None:
    """detect_token_sources finds sources with valid credential files."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()
    (connectors_dir / "slack.json").write_text('{"token": "xoxb-test"}')
    (connectors_dir / "notion.json").write_text('{"token": "ntn_test"}')

    sources = detect_token_sources(connectors_dir=connectors_dir)
    ids = [s["connector_id"] for s in sources]
    assert "slack" in ids
    assert "notion" in ids


def test_detect_token_sources_skips_empty(tmp_path: Path) -> None:
    """detect_token_sources skips files with empty or invalid JSON."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()
    (connectors_dir / "slack.json").write_text("{}")
    (connectors_dir / "notion.json").write_text("invalid json")

    sources = detect_token_sources(connectors_dir=connectors_dir)
    assert len(sources) == 0


def test_detect_token_sources_empty_dir(tmp_path: Path) -> None:
    """detect_token_sources returns empty list when no credential files exist."""
    from openjarvis.cli.deep_research_setup_cmd import detect_token_sources

    connectors_dir = tmp_path / "connectors"
    connectors_dir.mkdir()

    sources = detect_token_sources(connectors_dir=connectors_dir)
    assert len(sources) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/cli/test_deep_research_setup.py::test_detect_token_sources_finds_connected -v --tb=short
```

Expected: FAIL — `ImportError: cannot import name 'detect_token_sources'`

- [ ] **Step 3: Add `detect_token_sources` and `_TOKEN_SOURCES` to deep_research_setup_cmd.py**

Add after the `detect_local_sources` function (around line 80):

```python
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
        "prompt_label": "Bot token (xoxb-... or xoxe-...)",
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
    """Return token-based sources that already have valid credentials.

    Scans ``~/.openjarvis/connectors/`` for known credential files.
    """
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
        # Must have at least one non-empty value
        if not data or not any(v for v in data.values() if v):
            continue
        sources.append({
            "connector_id": ts["connector_id"],
            "display_name": ts["display_name"],
            "config": {},
        })

    return sources
```

Also add `import json` at the top of the file (add to existing imports section).

- [ ] **Step 4: Run token detection tests**

```bash
uv run pytest tests/cli/test_deep_research_setup.py -v --tb=short
```

Expected: All 7 tests PASS (4 old + 3 new).

- [ ] **Step 5: Add `_prompt_connect_sources` function and update `_instantiate_connector`**

Add the interactive connect function after `detect_token_sources`:

```python
def _prompt_connect_sources(console: Console) -> List[Dict[str, Any]]:
    """Interactively prompt the user to connect token-based sources."""
    connected: List[Dict[str, Any]] = []
    cdir = DEFAULT_CONFIG_DIR / "connectors"
    cdir.mkdir(parents=True, exist_ok=True)

    while True:
        # Show unconnected sources
        unconnected = [
            ts for ts in _TOKEN_SOURCES
            if not (cdir / ts["creds_file"]).exists()
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

        # Save credentials via connector's handle_callback
        connector = _instantiate_connector(choice, {})
        connector.handle_callback(token.strip())
        console.print(f"  [green]{ts['display_name']}: connected![/green]")

        connected.append({
            "connector_id": choice,
            "display_name": ts["display_name"],
            "config": {},
        })

    return connected
```

Update `_instantiate_connector` to handle all connector types:

```python
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
```

- [ ] **Step 6: Update the `deep_research_setup` Click command to use token sources**

Replace the body of the `deep_research_setup` function with:

```python
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
                src["connector_id"], src["config"],
            )
            pipeline = IngestionPipeline(store)
            engine = SyncEngine(pipeline)
            chunks = engine.sync(connector)
            console.print(
                f"  {src['display_name']}: [green]{chunks} chunks[/green]"
            )
        except Exception as exc:  # noqa: BLE001
            console.print(
                f"  {src['display_name']}: [red]error: {exc}[/red]"
            )

    total = store.count()
    console.print(
        f"\n[bold green]Done![/bold green] {total} total chunks in {db_path}\n"
    )

    # 6. Chat
    if skip_chat:
        return

    _launch_chat(store, console)
```

- [ ] **Step 7: Run all tests**

```bash
uv run pytest tests/cli/test_deep_research_setup.py tests/connectors/test_outlook.py -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 8: Lint**

```bash
uv run ruff check src/openjarvis/cli/deep_research_setup_cmd.py src/openjarvis/connectors/outlook.py src/openjarvis/connectors/gmail_imap.py
```

Expected: No errors.

- [ ] **Step 9: Commit**

```bash
git add src/openjarvis/cli/deep_research_setup_cmd.py tests/cli/test_deep_research_setup.py
git commit -m "feat: extend deep-research-setup with token source detection and interactive connect"
```

---

### Task 4: Live test — connect all sources and ingest

**Files:** None (manual testing)

- [ ] **Step 1: Connect Slack**

```bash
uv run jarvis connect slack
```

Paste: your Slack bot token (`xoxb-...` or `xoxe-...`)

- [ ] **Step 2: Connect Notion**

```bash
uv run jarvis connect notion
```

Paste: your Notion integration token (`ntn_...`)

- [ ] **Step 3: Connect Granola**

```bash
uv run jarvis connect granola
```

Paste: your Granola API key (`grn_...`)

- [ ] **Step 4: Connect Gmail IMAP**

```bash
uv run jarvis connect gmail_imap
```

Paste: `your-email@gmail.com:qpde kebj evhy zljc`

(Replace `your-email@gmail.com` with your actual Gmail address.)

- [ ] **Step 5: Run deep-research-setup and verify all sources ingest**

```bash
uv run jarvis deep-research-setup --skip-chat
```

Expected output:
```
Deep Research Setup

  Detected Sources
┌───────────────────────┬───────┬───────────┐
│ Source                │ Type  │ Status    │
├───────────────────────┼───────┼───────────┤
│ Apple Notes           │ local │ ready     │
│ iMessage              │ local │ ready     │
│ Gmail (IMAP)          │ token │ connected │
│ Slack                 │ token │ connected │
│ Notion                │ token │ connected │
│ Granola               │ token │ connected │
└───────────────────────┴───────┴───────────┘

Ingest these sources? [Y/n]: Y

Ingesting...
  Apple Notes: ~100 chunks
  iMessage: ~52000 chunks
  Gmail (IMAP): N chunks
  Slack: N chunks
  Notion: N chunks
  Granola: N chunks

Done! N total chunks in ~/.openjarvis/knowledge.db
```

- [ ] **Step 6: Test the research agent with cross-source queries**

```bash
uv run jarvis deep-research-setup
```

At the `research>` prompt, try:
1. A query that should span emails + messages
2. A query about meeting notes (Granola data)
3. A query about a Notion page

- [ ] **Step 7: Push**

```bash
git push origin feat/deep-research-setup
```
