# Channel Gateway → DeepResearch Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the ChannelBridge (from PR #78, now merged) to route incoming messages from Slack, iMessage/BlueBubbles, WhatsApp, and SMS to the DeepResearchAgent, and add an AppleScript-based iMessage daemon for direct iPhone-to-agent messaging without external services.

**Architecture:** Modify `ChannelBridge.handle_incoming()` to use DeepResearchAgent instead of generic `JarvisSystem.ask()`. Add an `IMessageDaemon` that polls `chat.db` for new messages and routes them through the bridge. Add `jarvis channels` CLI commands for setup and lifecycle.

**Tech Stack:** Python 3.10+, sqlite3, subprocess (AppleScript), Click, asyncio, pytest

---

### Task 1: Wire ChannelBridge to DeepResearchAgent

**Files:**
- Modify: `src/openjarvis/server/channel_bridge.py`
- Create: `tests/server/test_channel_bridge_deep_research.py`

- [ ] **Step 1: Read `channel_bridge.py` to find `_handle_chat` method**

The `_handle_chat` method currently calls `self._system.ask()`. We need it to use DeepResearchAgent when available.

- [ ] **Step 2: Write the test**

Create `tests/server/test_channel_bridge_deep_research.py`:

```python
"""Test ChannelBridge routes to DeepResearchAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_handle_chat_uses_deep_research_agent() -> None:
    """When a DeepResearch agent is configured, route through it."""
    from openjarvis.server.channel_bridge import ChannelBridge
    from openjarvis.server.session_store import SessionStore

    mock_agent = MagicMock()
    mock_agent.run.return_value = MagicMock(
        content="Found 3 results about Spain.",
    )

    bridge = ChannelBridge(
        channels={},
        session_store=SessionStore(db_path=":memory:"),
        bus=MagicMock(),
        deep_research_agent=mock_agent,
    )

    result = bridge.handle_incoming(
        sender_id="+15551234567",
        content="When was my last trip to Spain?",
        channel_type="twilio",
    )

    assert "Spain" in result
    mock_agent.run.assert_called_once()


def test_handle_chat_falls_back_to_system() -> None:
    """When no DeepResearch agent, fall back to system.ask()."""
    from openjarvis.server.channel_bridge import ChannelBridge
    from openjarvis.server.session_store import SessionStore

    mock_system = MagicMock()
    mock_system.ask.return_value = "Generic response"

    bridge = ChannelBridge(
        channels={},
        session_store=SessionStore(db_path=":memory:"),
        bus=MagicMock(),
        system=mock_system,
    )

    result = bridge.handle_incoming(
        sender_id="+15551234567",
        content="Hello",
        channel_type="twilio",
    )

    assert result == "Generic response"
    mock_system.ask.assert_called_once()
```

- [ ] **Step 3: Modify `ChannelBridge.__init__` to accept `deep_research_agent`**

In `channel_bridge.py`, add `deep_research_agent` parameter to `__init__`:

```python
def __init__(
    self,
    channels: Dict[str, BaseChannel],
    session_store: SessionStore,
    bus: EventBus,
    system: Any = None,
    agent_manager: Any = None,
    deep_research_agent: Any = None,
) -> None:
    self._channels = channels
    self._session_store = session_store
    self._bus = bus
    self._system = system
    self._agent_manager = agent_manager
    self._deep_research_agent = deep_research_agent
    self._notification_timestamps: Dict[str, float] = {}
    self._subscribe_notifications()
```

- [ ] **Step 4: Modify `_handle_chat` to use DeepResearchAgent first**

Find the `_handle_chat` method. Replace the body to try DeepResearchAgent first, fall back to system:

```python
def _handle_chat(
    self,
    sender_id: str,
    content: str,
    channel_type: str,
    max_length: int = _DEFAULT_MAX_LENGTH,
) -> str:
    """Route chat to DeepResearchAgent or JarvisSystem."""
    # Try DeepResearchAgent first
    if self._deep_research_agent is not None:
        try:
            result = self._deep_research_agent.run(content)
            response = result.content or "No results found."
        except Exception as exc:
            logger.error("DeepResearch agent failed: %s", exc)
            response = f"Research error: {exc}"
    elif self._system is not None:
        response = self._system.ask(content)
    else:
        response = "No agent or system configured."

    # Truncate if needed
    if len(response) > max_length:
        self._session_store.set_overflow(sender_id, response)
        response = response[:max_length] + "\n\n(truncated — send /more for the rest)"

    return response
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/server/test_channel_bridge_deep_research.py tests/server/test_channel_bridge.py -v --tb=short
```

Expected: All PASS (new tests + existing tests).

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/server/channel_bridge.py tests/server/test_channel_bridge_deep_research.py
git commit -m "feat: wire ChannelBridge to route messages to DeepResearchAgent"
```

---

### Task 2: Create iMessage AppleScript daemon

**Files:**
- Create: `src/openjarvis/channels/imessage_daemon.py`
- Create: `tests/channels/test_imessage_daemon.py`

- [ ] **Step 1: Write the test**

Create `tests/channels/test_imessage_daemon.py`:

```python
"""Tests for iMessage AppleScript daemon."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _create_fake_chat_db(db_path: Path) -> None:
    """Create a minimal chat.db with one message."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER,
            date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test Chat')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (1, 'Hello agent', 1, 700000000000000000, 0)"
    )
    conn.commit()
    conn.close()


def test_poll_new_messages(tmp_path: Path) -> None:
    """Daemon detects new messages after last_rowid."""
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)

    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 1
    assert messages[0]["text"] == "Hello agent"
    assert messages[0]["rowid"] == 1


def test_poll_skips_old_messages(tmp_path: Path) -> None:
    """Daemon skips messages with ROWID <= last_rowid."""
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)

    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=1,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 0


def test_poll_filters_by_chat(tmp_path: Path) -> None:
    """Daemon only returns messages from the designated chat."""
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)

    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15559999999",
    )
    assert len(messages) == 0


def test_poll_skips_own_messages(tmp_path: Path) -> None:
    """Daemon ignores messages sent by the user (is_from_me=1)."""
    from openjarvis.channels.imessage_daemon import poll_new_messages

    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT, display_name TEXT
        );
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER,
            date INTEGER, is_from_me INTEGER
        );
    """)
    conn.execute("INSERT INTO handle VALUES (1, '+15551234567')")
    conn.execute("INSERT INTO chat VALUES (1, '+15551234567', 'Test')")
    conn.execute("INSERT INTO chat_message_join VALUES (1, 1)")
    conn.execute(
        "INSERT INTO message VALUES (1, 'My own msg', 1, 700000000000000000, 1)"
    )
    conn.commit()
    conn.close()

    messages = poll_new_messages(
        db_path=str(db_path),
        last_rowid=0,
        chat_identifier="+15551234567",
    )
    assert len(messages) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/channels/test_imessage_daemon.py -v --tb=short
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the daemon module**

Create `src/openjarvis/channels/imessage_daemon.py`:

```python
"""iMessage daemon — polls chat.db and routes to DeepResearchAgent.

Monitors a designated iMessage conversation for new messages, routes
them to the agent, and sends responses back via AppleScript.

Requires macOS with Full Disk Access for chat.db reading and
Accessibility permission for AppleScript Messages control.
"""

from __future__ import annotations

import logging
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = str(
    Path.home() / "Library" / "Messages" / "chat.db"
)
_POLL_INTERVAL = 5  # seconds
_PID_FILE = str(Path.home() / ".openjarvis" / "imessage-agent.pid")


# -------------------------------------------------------------------
# Polling
# -------------------------------------------------------------------


def poll_new_messages(
    *,
    db_path: str = _DEFAULT_DB_PATH,
    last_rowid: int = 0,
    chat_identifier: str = "",
) -> List[Dict[str, Any]]:
    """Return new incoming messages since last_rowid.

    Only returns messages where ``is_from_me = 0`` (incoming) and
    that belong to the designated chat.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []

    try:
        rows = conn.execute(
            "SELECT m.ROWID as rowid, m.text, m.date, c.chat_identifier "
            "FROM message m "
            "JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
            "JOIN chat c ON c.ROWID = cmj.chat_id "
            "WHERE m.ROWID > ? AND m.is_from_me = 0 AND m.text IS NOT NULL "
            "AND c.chat_identifier = ? "
            "ORDER BY m.ROWID ASC",
            (last_rowid, chat_identifier),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


# -------------------------------------------------------------------
# AppleScript sending
# -------------------------------------------------------------------


def send_imessage(chat_identifier: str, message: str) -> bool:
    """Send an iMessage via AppleScript.

    Returns True on success, False on failure.
    """
    # Escape double quotes and backslashes for AppleScript
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "Messages"\n'
        f'  set targetChat to a reference to chat id "{chat_identifier}"\n'
        f'  send "{escaped}" to targetChat\n'
        f"end tell"
    )

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.error("Failed to send iMessage via AppleScript")
        return False


# -------------------------------------------------------------------
# Daemon loop
# -------------------------------------------------------------------


def run_daemon(
    *,
    chat_identifier: str,
    db_path: str = _DEFAULT_DB_PATH,
    handler: Any = None,
    poll_interval: float = _POLL_INTERVAL,
    max_iterations: int = 0,
) -> None:
    """Run the iMessage polling daemon.

    Parameters
    ----------
    chat_identifier:
        The chat to monitor (phone number or email).
    handler:
        Callable that takes a message string and returns a response string.
        If None, messages are logged but not responded to.
    poll_interval:
        Seconds between polls.
    max_iterations:
        Stop after this many iterations (0 = run forever).
    """
    # Write PID file
    pid_path = Path(_PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    # Find starting ROWID
    last_rowid = _get_max_rowid(db_path)
    logger.info(
        "iMessage daemon started — monitoring %s from ROWID %d",
        chat_identifier,
        last_rowid,
    )

    running = True

    def _stop(signum: int, frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    iterations = 0
    while running:
        messages = poll_new_messages(
            db_path=db_path,
            last_rowid=last_rowid,
            chat_identifier=chat_identifier,
        )

        for msg in messages:
            last_rowid = msg["rowid"]
            text = msg["text"]
            logger.info("Received: %s", text[:100])

            if handler is not None:
                try:
                    response = handler(text)
                    if response:
                        send_imessage(chat_identifier, response)
                except Exception:
                    logger.exception("Handler failed for message %d", msg["rowid"])

        iterations += 1
        if max_iterations and iterations >= max_iterations:
            break

        time.sleep(poll_interval)

    # Cleanup PID file
    if pid_path.exists():
        pid_path.unlink()
    logger.info("iMessage daemon stopped")


def _get_max_rowid(db_path: str) -> int:
    """Get the current max ROWID from chat.db."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
        conn.close()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0


def is_running() -> bool:
    """Check if the daemon is currently running."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


def stop_daemon() -> bool:
    """Stop the running daemon. Returns True if stopped."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_path.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/channels/test_imessage_daemon.py -v --tb=short
```

Expected: 4/4 PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/openjarvis/channels/imessage_daemon.py
git add src/openjarvis/channels/imessage_daemon.py tests/channels/test_imessage_daemon.py
git commit -m "feat: add iMessage AppleScript daemon for iPhone-to-agent messaging"
```

---

### Task 3: Add `jarvis channels` CLI commands

**Files:**
- Create: `src/openjarvis/cli/channels_cmd.py`
- Modify: `src/openjarvis/cli/__init__.py`

- [ ] **Step 1: Create the CLI command module**

Create `src/openjarvis/cli/channels_cmd.py`:

```python
"""``jarvis channels`` — manage channel connections for the DeepResearch agent."""

from __future__ import annotations

import sys
from typing import Optional

import click
from rich.console import Console
from rich.table import Table


@click.group("channels")
def channels() -> None:
    """Manage messaging channels (iMessage, Slack, WhatsApp, SMS)."""


@channels.command("status")
def channels_status() -> None:
    """Show status of all configured channels."""
    from openjarvis.channels.imessage_daemon import is_running

    console = Console()
    table = Table(title="Channel Status")
    table.add_column("Channel", style="bold")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    # iMessage daemon
    if is_running():
        table.add_row("iMessage", "[green]running[/green]", "Polling chat.db")
    else:
        table.add_row("iMessage", "[dim]stopped[/dim]", "jarvis channels imessage-start")

    console.print(table)


@channels.command("imessage-start")
@click.argument("chat_identifier")
@click.option("--background/--foreground", default=True, help="Run in background.")
def imessage_start(chat_identifier: str, background: bool) -> None:
    """Start the iMessage daemon for a chat.

    CHAT_IDENTIFIER is the phone number or email to monitor
    (e.g. +15551234567 or group chat name).
    """
    from openjarvis.channels.imessage_daemon import is_running, run_daemon

    console = Console()

    if is_running():
        console.print("[yellow]iMessage daemon is already running.[/yellow]")
        return

    if background:
        import subprocess
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "openjarvis.channels.imessage_daemon",
                "--chat", chat_identifier,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        console.print(
            f"[green]iMessage daemon started[/green] (PID {proc.pid})\n"
            f"Monitoring: {chat_identifier}\n"
            f"Text this contact from your iPhone to chat with the agent."
        )
    else:
        console.print(f"[green]Starting iMessage daemon[/green] — monitoring {chat_identifier}")
        console.print("Press Ctrl+C to stop.\n")

        from openjarvis.agents.deep_research import DeepResearchAgent
        from openjarvis.connectors.retriever import TwoStageRetriever
        from openjarvis.connectors.store import KnowledgeStore
        from openjarvis.engine.ollama import OllamaEngine
        from openjarvis.tools.knowledge_search import KnowledgeSearchTool
        from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
        from openjarvis.tools.scan_chunks import ScanChunksTool
        from openjarvis.tools.think import ThinkTool

        engine = OllamaEngine()
        store = KnowledgeStore()
        retriever = TwoStageRetriever(store)
        tools = [
            KnowledgeSearchTool(retriever=retriever),
            KnowledgeSQLTool(store=store),
            ScanChunksTool(store=store, engine=engine, model="qwen3.5:4b"),
            ThinkTool(),
        ]
        agent = DeepResearchAgent(engine=engine, model="qwen3.5:4b", tools=tools)

        def handler(text: str) -> str:
            result = agent.run(text)
            return result.content or "No results found."

        run_daemon(
            chat_identifier=chat_identifier,
            handler=handler,
        )


@channels.command("imessage-stop")
def imessage_stop() -> None:
    """Stop the iMessage daemon."""
    from openjarvis.channels.imessage_daemon import stop_daemon

    console = Console()
    if stop_daemon():
        console.print("[green]iMessage daemon stopped.[/green]")
    else:
        console.print("[dim]iMessage daemon is not running.[/dim]")
```

- [ ] **Step 2: Register in CLI __init__.py**

In `src/openjarvis/cli/__init__.py`, add:

```python
from openjarvis.cli.channels_cmd import channels
cli.add_command(channels, "channels")
```

- [ ] **Step 3: Verify**

```bash
uv run jarvis channels --help
uv run jarvis channels status
```

- [ ] **Step 4: Lint + commit**

```bash
uv run ruff check src/openjarvis/cli/channels_cmd.py
git add src/openjarvis/cli/channels_cmd.py src/openjarvis/cli/__init__.py
git commit -m "feat: add jarvis channels CLI commands for iMessage daemon lifecycle"
```

---

### Task 4: Run full test suite + push

**Files:** None

- [ ] **Step 1: Run all tests**

```bash
uv run pytest tests/connectors/ tests/agents/test_deep_research.py tests/agents/test_deep_research_integration.py tests/agents/test_channel_agent.py tests/agents/test_channel_agent_integration.py tests/cli/test_deep_research_setup.py tests/tools/test_knowledge_sql.py tests/tools/test_scan_chunks.py tests/server/test_channel_bridge.py tests/server/test_channel_bridge_deep_research.py tests/server/test_session_store.py tests/server/test_webhook_routes.py tests/server/test_auth_middleware.py tests/server/test_deep_research_tools_wiring.py tests/channels/test_twilio_sms.py tests/channels/test_imessage_daemon.py --ignore=tests/connectors/test_embedding_store.py -k "not cached_embeddings and not caches_new_embeddings" -q --tb=short
```

Expected: All PASS.

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/openjarvis/channels/imessage_daemon.py src/openjarvis/server/channel_bridge.py src/openjarvis/cli/channels_cmd.py
```

- [ ] **Step 3: Push to both branches**

```bash
git push origin feat/deep-research-setup
git push origin feat/deep-research-setup:feat/mobile-channel-gateway --force-with-lease
```
