# Deep Research Phase 2A: Remaining Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the 5 remaining data source connectors — Slack, Google Drive, Google Calendar, Google Contacts, and iMessage — to the connector framework built in Phase 1.

**Architecture:** Each connector follows the established `BaseConnector` pattern: registered via `@ConnectorRegistry.register()`, yields normalized `Document` objects, stores credentials via `oauth.py` helpers, exposes MCP tools for real-time agent queries. OAuth connectors (Slack, Drive, Calendar, Contacts) reuse `build_google_auth_url()` or Slack's own OAuth. iMessage reads directly from the local macOS SQLite database.

**Tech Stack:** Python 3.10+, httpx (API calls), sqlite3 (iMessage local DB), pytest + unittest.mock (mocked tests)

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Section 5 (Connector Layer), Phase 2

**Depends on:** Phase 1 complete (ConnectorRegistry, BaseConnector, Document, oauth.py, KnowledgeStore, SyncEngine all exist)

---

## File Structure

```
src/openjarvis/connectors/
├── slack_connector.py       # Slack connector (OAuth + Web API)
├── gdrive.py                # Google Drive connector (OAuth + Drive API v3)
├── gcalendar.py             # Google Calendar connector (OAuth + Calendar API v3)
├── gcontacts.py             # Google Contacts connector (OAuth + People API)
├── imessage.py              # iMessage connector (local macOS SQLite)
├── __init__.py              # (modify) Add auto-imports for new connectors

tests/connectors/
├── test_slack_connector.py
├── test_gdrive.py
├── test_gcalendar.py
├── test_gcontacts.py
├── test_imessage.py
```

---

### Task 1: Slack Connector

**Files:**
- Create: `src/openjarvis/connectors/slack_connector.py`
- Create: `tests/connectors/test_slack_connector.py`

Named `slack_connector.py` to avoid collision with the existing `channels/slack.py`.

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_slack_connector.py`:

```python
"""Tests for the Slack data source connector (mocked API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture()
def connector(tmp_path: Path):
    from openjarvis.connectors.slack_connector import SlackConnector

    return SlackConnector(credentials_path=str(tmp_path / "slack.json"))


_CHANNELS_RESPONSE = {
    "channels": [
        {"id": "C001", "name": "general", "is_member": True},
        {"id": "C002", "name": "engineering", "is_member": True},
    ],
    "response_metadata": {"next_cursor": ""},
}

_HISTORY_RESPONSE = {
    "messages": [
        {
            "ts": "1710500000.000100",
            "user": "U001",
            "text": "Let's discuss the API redesign.",
            "thread_ts": "1710500000.000100",
        },
        {
            "ts": "1710500060.000200",
            "user": "U002",
            "text": "Sounds good, I'll prepare a doc.",
        },
    ],
    "has_more": False,
}

_USERS_RESPONSE = {
    "members": [
        {"id": "U001", "real_name": "Alice", "profile": {"email": "alice@co.com"}},
        {"id": "U002", "real_name": "Bob", "profile": {"email": "bob@co.com"}},
    ],
}


def test_not_connected_without_credentials(connector) -> None:
    assert connector.is_connected() is False


def test_auth_type_is_oauth(connector) -> None:
    assert connector.auth_type == "oauth"


def test_auth_url(connector) -> None:
    url = connector.auth_url()
    assert "slack.com" in url


@patch("openjarvis.connectors.slack_connector._slack_api_users_list")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_history")
@patch("openjarvis.connectors.slack_connector._slack_api_conversations_list")
def test_sync_yields_documents(
    mock_channels, mock_history, mock_users, connector, tmp_path: Path
) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "xoxb-fake"}), encoding="utf-8")

    mock_channels.return_value = _CHANNELS_RESPONSE
    mock_history.return_value = _HISTORY_RESPONSE
    mock_users.return_value = _USERS_RESPONSE

    docs: List[Document] = list(connector.sync())

    # 2 channels x 2 messages = 4 messages, but grouped by channel
    assert len(docs) == 4
    assert all(d.source == "slack" for d in docs)
    assert all(d.doc_type == "message" for d in docs)

    msg1 = next(d for d in docs if "API redesign" in d.content)
    assert msg1.author == "Alice"
    assert msg1.metadata.get("channel") == "general"


def test_disconnect(connector, tmp_path: Path) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "xoxb-fake"}), encoding="utf-8")
    assert connector.is_connected()
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector) -> None:
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert "slack_search_messages" in names
    assert "slack_get_thread" in names
    assert "slack_list_channels" in names


def test_registry() -> None:
    from openjarvis.connectors.slack_connector import SlackConnector

    ConnectorRegistry.register_value("slack", SlackConnector)
    assert ConnectorRegistry.contains("slack")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_slack_connector.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SlackConnector**

Create `src/openjarvis/connectors/slack_connector.py`:

```python
"""Slack data source connector — syncs message history via Slack Web API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlencode

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import delete_tokens, load_tokens, save_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_SLACK_API = "https://slack.com/api"
_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "slack.json"
)


def _slack_api_conversations_list(
    token: str, *, cursor: str = ""
) -> Dict[str, Any]:
    """Call conversations.list to get channels the bot is a member of."""
    params: Dict[str, str] = {
        "types": "public_channel,private_channel",
        "exclude_archived": "true",
        "limit": "200",
    }
    if cursor:
        params["cursor"] = cursor
    resp = httpx.get(
        f"{_SLACK_API}/conversations.list",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _slack_api_conversations_history(
    token: str, channel_id: str, *, cursor: str = ""
) -> Dict[str, Any]:
    """Call conversations.history to get messages in a channel."""
    params: Dict[str, str] = {"channel": channel_id, "limit": "200"}
    if cursor:
        params["cursor"] = cursor
    resp = httpx.get(
        f"{_SLACK_API}/conversations.history",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _slack_api_users_list(token: str) -> Dict[str, Any]:
    """Call users.list to build a user ID → name/email map."""
    resp = httpx.get(
        f"{_SLACK_API}/users.list",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _ts_to_datetime(ts: str) -> datetime:
    """Convert Slack message timestamp to datetime."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(tz=timezone.utc)


@ConnectorRegistry.register("slack")
class SlackConnector(BaseConnector):
    """Slack connector — syncs channel message history via Web API."""

    connector_id = "slack"
    display_name = "Slack"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._items_synced = 0
        self._items_total = 0

    def _get_token(self) -> str:
        tokens = load_tokens(self._credentials_path)
        if tokens:
            return tokens.get("token", "")
        return ""

    def is_connected(self) -> bool:
        return bool(self._get_token())

    def disconnect(self) -> None:
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        params = {
            "client_id": "openjarvis-slack",
            "scope": "channels:history,channels:read,users:read",
            "redirect_uri": "http://localhost:8789/callback",
        }
        return f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    def handle_callback(self, code: str) -> None:
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        token = self._get_token()
        if not token:
            return

        # Build user map
        users_resp = _slack_api_users_list(token)
        user_map: Dict[str, Dict[str, str]] = {}
        for member in users_resp.get("members", []):
            uid = member.get("id", "")
            user_map[uid] = {
                "name": member.get("real_name", uid),
                "email": member.get("profile", {}).get("email", ""),
            }

        # Get channels
        channels_resp = _slack_api_conversations_list(token)
        channels = channels_resp.get("channels", [])

        synced = 0
        for chan in channels:
            chan_id = chan.get("id", "")
            chan_name = chan.get("name", chan_id)

            history = _slack_api_conversations_history(token, chan_id)
            messages = history.get("messages", [])

            for msg in messages:
                ts = msg.get("ts", "")
                timestamp = _ts_to_datetime(ts)

                if since and timestamp < since:
                    continue

                user_id = msg.get("user", "")
                user_info = user_map.get(user_id, {"name": user_id, "email": ""})
                text = msg.get("text", "")

                synced += 1
                yield Document(
                    doc_id=f"slack:{chan_id}:{ts}",
                    source="slack",
                    doc_type="message",
                    content=text,
                    title=f"#{chan_name}",
                    author=user_info["name"],
                    participants=[user_info["name"]],
                    timestamp=timestamp,
                    thread_id=msg.get("thread_ts"),
                    url=f"https://slack.com/archives/{chan_id}/p{ts.replace('.', '')}",
                    metadata={
                        "channel": chan_name,
                        "channel_id": chan_id,
                        "user_id": user_id,
                    },
                )

        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._items_synced)

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="slack_search_messages",
                description="Search Slack messages by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="slack_get_thread",
                description="Get all replies in a Slack thread.",
                parameters={
                    "type": "object",
                    "properties": {
                        "channel_id": {
                            "type": "string",
                            "description": "Slack channel ID",
                        },
                        "thread_ts": {
                            "type": "string",
                            "description": "Thread timestamp",
                        },
                    },
                    "required": ["channel_id", "thread_ts"],
                },
                category="communication",
            ),
            ToolSpec(
                name="slack_list_channels",
                description="List Slack channels the bot has access to.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                category="communication",
            ),
        ]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_slack_connector.py -v`

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/slack_connector.py tests/connectors/test_slack_connector.py
git commit -m "feat: add Slack data source connector with channel history sync"
```

---

### Task 2: Google Drive Connector

**Files:**
- Create: `src/openjarvis/connectors/gdrive.py`
- Create: `tests/connectors/test_gdrive.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_gdrive.py`:

```python
"""Tests for the Google Drive connector (mocked API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture()
def connector(tmp_path: Path):
    from openjarvis.connectors.gdrive import GDriveConnector

    return GDriveConnector(credentials_path=str(tmp_path / "gdrive.json"))


_FILES_LIST_RESPONSE = {
    "files": [
        {
            "id": "doc1",
            "name": "Q3 Roadmap",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2024-03-15T10:00:00.000Z",
            "owners": [{"emailAddress": "alice@co.com", "displayName": "Alice"}],
            "webViewLink": "https://docs.google.com/document/d/doc1/edit",
        },
        {
            "id": "sheet1",
            "name": "Budget 2024",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "modifiedTime": "2024-03-16T11:00:00.000Z",
            "owners": [{"emailAddress": "bob@co.com", "displayName": "Bob"}],
            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet1/edit",
        },
    ],
    "nextPageToken": None,
}

_EXPORT_RESPONSE = "# Q3 Roadmap\n\nThis is the roadmap content."


def test_not_connected_without_credentials(connector) -> None:
    assert connector.is_connected() is False


def test_auth_url(connector) -> None:
    url = connector.auth_url()
    assert "accounts.google.com" in url
    assert "drive.readonly" in url


@patch("openjarvis.connectors.gdrive._gdrive_api_export")
@patch("openjarvis.connectors.gdrive._gdrive_api_list_files")
def test_sync_yields_documents(
    mock_list, mock_export, connector, tmp_path: Path
) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")

    mock_list.return_value = _FILES_LIST_RESPONSE
    mock_export.return_value = _EXPORT_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2
    assert all(d.source == "gdrive" for d in docs)
    assert all(d.doc_type == "document" for d in docs)

    doc1 = next(d for d in docs if d.doc_id == "gdrive:doc1")
    assert doc1.title == "Q3 Roadmap"
    assert doc1.author == "Alice"
    assert "roadmap" in doc1.content.lower()


def test_disconnect(connector, tmp_path: Path) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector) -> None:
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert "gdrive_search_files" in names
    assert "gdrive_get_document" in names
    assert "gdrive_list_recent" in names


def test_registry() -> None:
    from openjarvis.connectors.gdrive import GDriveConnector

    ConnectorRegistry.register_value("gdrive", GDriveConnector)
    assert ConnectorRegistry.contains("gdrive")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gdrive.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GDriveConnector**

Create `src/openjarvis/connectors/gdrive.py`:

```python
"""Google Drive connector — syncs files via Drive API v3."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_DRIVE_API = "https://www.googleapis.com/drive/v3"
_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "gdrive.json"
)

# Google Workspace MIME types that can be exported as text
_EXPORT_MIMES: Dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _gdrive_api_list_files(
    token: str, *, page_token: Optional[str] = None
) -> Dict[str, Any]:
    """Call files.list to enumerate accessible files."""
    params: Dict[str, str] = {
        "pageSize": "100",
        "fields": (
            "files(id,name,mimeType,modifiedTime,owners,webViewLink),"
            "nextPageToken"
        ),
        "orderBy": "modifiedTime desc",
    }
    if page_token:
        params["pageToken"] = page_token
    resp = httpx.get(
        f"{_DRIVE_API}/files",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gdrive_api_export(
    token: str, file_id: str, mime_type: str
) -> str:
    """Export a Google Workspace file as text."""
    resp = httpx.get(
        f"{_DRIVE_API}/files/{file_id}/export",
        headers={"Authorization": f"Bearer {token}"},
        params={"mimeType": mime_type},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.text


def _parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


@ConnectorRegistry.register("gdrive")
class GDriveConnector(BaseConnector):
    """Google Drive connector — syncs documents via Drive API v3."""

    connector_id = "gdrive"
    display_name = "Google Drive"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = credentials_path or _DEFAULT_CREDENTIALS_PATH
        self._items_synced = 0

    def _get_token(self) -> str:
        tokens = load_tokens(self._credentials_path)
        return tokens.get("token", "") if tokens else ""

    def is_connected(self) -> bool:
        return bool(self._get_token())

    def disconnect(self) -> None:
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return build_google_auth_url(
            client_id="openjarvis-drive", scopes=[_DRIVE_SCOPE]
        )

    def handle_callback(self, code: str) -> None:
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        token = self._get_token()
        if not token:
            return

        page_token = cursor
        synced = 0

        while True:
            resp = _gdrive_api_list_files(token, page_token=page_token)
            files = resp.get("files", [])

            for f in files:
                modified = _parse_iso(f.get("modifiedTime", ""))
                if since and modified < since:
                    continue

                file_id = f["id"]
                mime = f.get("mimeType", "")
                owners = f.get("owners", [{}])
                owner = owners[0] if owners else {}

                # Export Google Workspace files; skip binary files
                export_mime = _EXPORT_MIMES.get(mime)
                if export_mime:
                    content = _gdrive_api_export(token, file_id, export_mime)
                else:
                    # Non-exportable file — store metadata only
                    content = f"[File: {f.get('name', '')}] ({mime})"

                synced += 1
                yield Document(
                    doc_id=f"gdrive:{file_id}",
                    source="gdrive",
                    doc_type="document",
                    content=content,
                    title=f.get("name", ""),
                    author=owner.get("displayName", owner.get("emailAddress", "")),
                    timestamp=modified,
                    url=f.get("webViewLink", ""),
                    metadata={"mime_type": mime},
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._items_synced)

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="gdrive_search_files",
                description="Search Google Drive files by name or content.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="gdrive_get_document",
                description="Get the text content of a Google Drive document.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "Drive file ID"},
                    },
                    "required": ["file_id"],
                },
                category="knowledge",
            ),
            ToolSpec(
                name="gdrive_list_recent",
                description="List recently modified files in Google Drive.",
                parameters={
                    "type": "object",
                    "properties": {
                        "max_results": {
                            "type": "integer",
                            "description": "Max files to return",
                            "default": 20,
                        },
                    },
                },
                category="knowledge",
            ),
        ]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gdrive.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/gdrive.py tests/connectors/test_gdrive.py
git commit -m "feat: add Google Drive connector with file export and sync"
```

---

### Task 3: Google Calendar Connector

**Files:**
- Create: `src/openjarvis/connectors/gcalendar.py`
- Create: `tests/connectors/test_gcalendar.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_gcalendar.py`:

```python
"""Tests for Google Calendar connector (mocked API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture()
def connector(tmp_path: Path):
    from openjarvis.connectors.gcalendar import GCalendarConnector

    return GCalendarConnector(credentials_path=str(tmp_path / "gcal.json"))


_CALENDARS_RESPONSE = {
    "items": [
        {"id": "primary", "summary": "My Calendar"},
    ],
}

_EVENTS_RESPONSE = {
    "items": [
        {
            "id": "evt1",
            "summary": "Sprint Planning",
            "description": "Review sprint goals and capacity.",
            "start": {"dateTime": "2024-03-15T10:00:00Z"},
            "end": {"dateTime": "2024-03-15T11:00:00Z"},
            "attendees": [
                {"email": "alice@co.com", "displayName": "Alice"},
                {"email": "bob@co.com", "displayName": "Bob"},
            ],
            "location": "Room 3",
            "organizer": {"email": "alice@co.com", "displayName": "Alice"},
            "htmlLink": "https://calendar.google.com/event?eid=evt1",
        },
    ],
    "nextPageToken": None,
}


def test_not_connected(connector) -> None:
    assert not connector.is_connected()


def test_auth_url(connector) -> None:
    url = connector.auth_url()
    assert "accounts.google.com" in url
    assert "calendar.readonly" in url


@patch("openjarvis.connectors.gcalendar._gcal_api_events_list")
@patch("openjarvis.connectors.gcalendar._gcal_api_calendars_list")
def test_sync_yields_events(
    mock_calendars, mock_events, connector, tmp_path: Path
) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")

    mock_calendars.return_value = _CALENDARS_RESPONSE
    mock_events.return_value = _EVENTS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 1
    evt = docs[0]
    assert evt.doc_id == "gcalendar:evt1"
    assert evt.source == "gcalendar"
    assert evt.doc_type == "event"
    assert evt.title == "Sprint Planning"
    assert "Sprint Planning" in evt.content
    assert "alice@co.com" in [p for p in evt.participants]
    assert "Room 3" in evt.content


def test_disconnect(connector, tmp_path: Path) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector) -> None:
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert "calendar_get_events_today" in names
    assert "calendar_search_events" in names
    assert "calendar_next_meeting" in names


def test_registry() -> None:
    from openjarvis.connectors.gcalendar import GCalendarConnector

    ConnectorRegistry.register_value("gcalendar", GCalendarConnector)
    assert ConnectorRegistry.contains("gcalendar")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gcalendar.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GCalendarConnector**

Create `src/openjarvis/connectors/gcalendar.py`:

```python
"""Google Calendar connector — syncs events via Calendar API v3."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_CAL_API = "https://www.googleapis.com/calendar/v3"
_CAL_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "gcalendar.json"
)


def _gcal_api_calendars_list(token: str) -> Dict[str, Any]:
    resp = httpx.get(
        f"{_CAL_API}/users/me/calendarList",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _gcal_api_events_list(
    token: str,
    calendar_id: str,
    *,
    page_token: Optional[str] = None,
    time_min: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, str] = {
        "maxResults": "250",
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if page_token:
        params["pageToken"] = page_token
    if time_min:
        params["timeMin"] = time_min
    resp = httpx.get(
        f"{_CAL_API}/calendars/{calendar_id}/events",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)


def _format_event(event: Dict[str, Any]) -> str:
    """Format a calendar event as human-readable text."""
    lines = [event.get("summary", "(No title)")]

    start = event.get("start", {})
    end = event.get("end", {})
    start_str = start.get("dateTime", start.get("date", ""))
    end_str = end.get("dateTime", end.get("date", ""))
    if start_str:
        lines.append(f"When: {start_str} — {end_str}")

    location = event.get("location", "")
    if location:
        lines.append(f"Location: {location}")

    attendees = event.get("attendees", [])
    if attendees:
        names = [
            a.get("displayName", a.get("email", ""))
            for a in attendees
        ]
        lines.append(f"Attendees: {', '.join(names)}")

    organizer = event.get("organizer", {})
    org_name = organizer.get("displayName", organizer.get("email", ""))
    if org_name:
        lines.append(f"Organizer: {org_name}")

    desc = event.get("description", "")
    if desc:
        lines.append(f"\n{desc}")

    return "\n".join(lines)


@ConnectorRegistry.register("gcalendar")
class GCalendarConnector(BaseConnector):
    """Google Calendar connector — syncs events."""

    connector_id = "gcalendar"
    display_name = "Google Calendar"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = (
            credentials_path or _DEFAULT_CREDENTIALS_PATH
        )
        self._items_synced = 0

    def _get_token(self) -> str:
        tokens = load_tokens(self._credentials_path)
        return tokens.get("token", "") if tokens else ""

    def is_connected(self) -> bool:
        return bool(self._get_token())

    def disconnect(self) -> None:
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return build_google_auth_url(
            client_id="openjarvis-calendar", scopes=[_CAL_SCOPE]
        )

    def handle_callback(self, code: str) -> None:
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        token = self._get_token()
        if not token:
            return

        time_min = since.isoformat() if since else None
        cals = _gcal_api_calendars_list(token)
        synced = 0

        for cal in cals.get("items", []):
            cal_id = cal.get("id", "primary")
            page_token = cursor

            while True:
                resp = _gcal_api_events_list(
                    token, cal_id,
                    page_token=page_token,
                    time_min=time_min,
                )
                events = resp.get("items", [])

                for evt in events:
                    evt_id = evt.get("id", "")
                    start = evt.get("start", {})
                    start_str = start.get(
                        "dateTime", start.get("date", "")
                    )
                    timestamp = _parse_iso(start_str)

                    attendees = evt.get("attendees", [])
                    participant_emails = [
                        a.get("email", "") for a in attendees
                    ]

                    synced += 1
                    yield Document(
                        doc_id=f"gcalendar:{evt_id}",
                        source="gcalendar",
                        doc_type="event",
                        content=_format_event(evt),
                        title=evt.get("summary", ""),
                        author=evt.get("organizer", {}).get("email", ""),
                        participants=participant_emails,
                        timestamp=timestamp,
                        url=evt.get("htmlLink", ""),
                        metadata={
                            "calendar_id": cal_id,
                            "location": evt.get("location", ""),
                        },
                    )

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._items_synced)

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="calendar_get_events_today",
                description="Get today's calendar events.",
                parameters={"type": "object", "properties": {}},
                category="productivity",
            ),
            ToolSpec(
                name="calendar_search_events",
                description="Search calendar events by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="calendar_next_meeting",
                description="Get the next upcoming meeting.",
                parameters={"type": "object", "properties": {}},
                category="productivity",
            ),
        ]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gcalendar.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/gcalendar.py tests/connectors/test_gcalendar.py
git commit -m "feat: add Google Calendar connector with event sync"
```

---

### Task 4: Google Contacts Connector

**Files:**
- Create: `src/openjarvis/connectors/gcontacts.py`
- Create: `tests/connectors/test_gcontacts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_gcontacts.py`:

```python
"""Tests for Google Contacts connector (mocked API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


@pytest.fixture()
def connector(tmp_path: Path):
    from openjarvis.connectors.gcontacts import GContactsConnector

    return GContactsConnector(credentials_path=str(tmp_path / "gcontacts.json"))


_CONNECTIONS_RESPONSE = {
    "connections": [
        {
            "resourceName": "people/c1",
            "names": [{"displayName": "Alice Smith"}],
            "emailAddresses": [{"value": "alice@co.com"}],
            "phoneNumbers": [{"value": "+1-555-0100"}],
            "organizations": [{"name": "Acme Corp", "title": "VP Engineering"}],
        },
        {
            "resourceName": "people/c2",
            "names": [{"displayName": "Bob Jones"}],
            "emailAddresses": [{"value": "bob@co.com"}],
            "phoneNumbers": [],
            "organizations": [{"name": "Acme Corp", "title": "Designer"}],
        },
    ],
    "nextPageToken": None,
    "totalItems": 2,
}


def test_not_connected(connector) -> None:
    assert not connector.is_connected()


def test_auth_url(connector) -> None:
    url = connector.auth_url()
    assert "accounts.google.com" in url
    assert "contacts.readonly" in url


@patch("openjarvis.connectors.gcontacts._gcontacts_api_list")
def test_sync_yields_contacts(mock_list, connector, tmp_path: Path) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")

    mock_list.return_value = _CONNECTIONS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2
    assert all(d.source == "gcontacts" for d in docs)
    assert all(d.doc_type == "contact" for d in docs)

    alice = next(d for d in docs if "Alice" in d.title)
    assert "alice@co.com" in alice.content
    assert "VP Engineering" in alice.content


def test_disconnect(connector, tmp_path: Path) -> None:
    creds = Path(connector._credentials_path)
    creds.write_text(json.dumps({"token": "fake"}), encoding="utf-8")
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector) -> None:
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert "contacts_find" in names
    assert "contacts_get_info" in names


def test_registry() -> None:
    from openjarvis.connectors.gcontacts import GContactsConnector

    ConnectorRegistry.register_value("gcontacts", GContactsConnector)
    assert ConnectorRegistry.contains("gcontacts")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gcontacts.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GContactsConnector**

Create `src/openjarvis/connectors/gcontacts.py`:

```python
"""Google Contacts connector — syncs contacts via People API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import (
    build_google_auth_url,
    delete_tokens,
    load_tokens,
    save_tokens,
)
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

_PEOPLE_API = "https://people.googleapis.com/v1"
_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
_DEFAULT_CREDENTIALS_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "gcontacts.json"
)

_PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations"


def _gcontacts_api_list(
    token: str, *, page_token: Optional[str] = None
) -> Dict[str, Any]:
    """Call people.connections.list."""
    params: Dict[str, str] = {
        "personFields": _PERSON_FIELDS,
        "pageSize": "100",
    }
    if page_token:
        params["pageToken"] = page_token
    resp = httpx.get(
        f"{_PEOPLE_API}/people/me/connections",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _format_contact(person: Dict[str, Any]) -> str:
    """Format a contact as searchable text."""
    lines: List[str] = []

    names = person.get("names", [])
    if names:
        lines.append(names[0].get("displayName", ""))

    for email in person.get("emailAddresses", []):
        lines.append(email.get("value", ""))

    for phone in person.get("phoneNumbers", []):
        lines.append(phone.get("value", ""))

    for org in person.get("organizations", []):
        parts = []
        if org.get("name"):
            parts.append(org["name"])
        if org.get("title"):
            parts.append(org["title"])
        if parts:
            lines.append(", ".join(parts))

    return "\n".join(lines)


@ConnectorRegistry.register("gcontacts")
class GContactsConnector(BaseConnector):
    """Google Contacts connector — syncs contacts via People API."""

    connector_id = "gcontacts"
    display_name = "Google Contacts"
    auth_type = "oauth"

    def __init__(self, credentials_path: str = "") -> None:
        self._credentials_path = (
            credentials_path or _DEFAULT_CREDENTIALS_PATH
        )
        self._items_synced = 0

    def _get_token(self) -> str:
        tokens = load_tokens(self._credentials_path)
        return tokens.get("token", "") if tokens else ""

    def is_connected(self) -> bool:
        return bool(self._get_token())

    def disconnect(self) -> None:
        delete_tokens(self._credentials_path)

    def auth_url(self) -> str:
        return build_google_auth_url(
            client_id="openjarvis-contacts", scopes=[_CONTACTS_SCOPE]
        )

    def handle_callback(self, code: str) -> None:
        save_tokens(self._credentials_path, {"token": code})

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        token = self._get_token()
        if not token:
            return

        page_token = cursor
        synced = 0

        while True:
            resp = _gcontacts_api_list(token, page_token=page_token)
            people = resp.get("connections", [])

            for person in people:
                resource = person.get("resourceName", "")
                names = person.get("names", [])
                display_name = names[0].get("displayName", "") if names else ""
                emails = person.get("emailAddresses", [])
                primary_email = emails[0].get("value", "") if emails else ""

                synced += 1
                yield Document(
                    doc_id=f"gcontacts:{resource}",
                    source="gcontacts",
                    doc_type="contact",
                    content=_format_contact(person),
                    title=display_name,
                    author=primary_email,
                    participants=[primary_email] if primary_email else [],
                    timestamp=datetime.now(tz=timezone.utc),
                    metadata={"resource_name": resource},
                )

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._items_synced)

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="contacts_find",
                description="Find a contact by name or email.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Name or email to search",
                        },
                    },
                    "required": ["query"],
                },
                category="productivity",
            ),
            ToolSpec(
                name="contacts_get_info",
                description="Get full details for a contact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Contact name",
                        },
                    },
                    "required": ["name"],
                },
                category="productivity",
            ),
        ]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_gcontacts.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/gcontacts.py tests/connectors/test_gcontacts.py
git commit -m "feat: add Google Contacts connector with People API sync"
```

---

### Task 5: iMessage Connector (macOS Local SQLite)

**Files:**
- Create: `src/openjarvis/connectors/imessage.py`
- Create: `tests/connectors/test_imessage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_imessage.py`:

```python
"""Tests for iMessage connector (uses a temp SQLite DB mimicking chat.db)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def _create_fake_chat_db(db_path: Path) -> None:
    """Create a minimal iMessage chat.db schema with test data."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY,
            id TEXT NOT NULL
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY,
            chat_identifier TEXT NOT NULL,
            display_name TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            text TEXT,
            handle_id INTEGER,
            date INTEGER,
            is_from_me INTEGER DEFAULT 0,
            cache_roomnames TEXT
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER,
            message_id INTEGER
        );

        INSERT INTO handle VALUES (1, '+15550100');
        INSERT INTO handle VALUES (2, 'alice@icloud.com');

        INSERT INTO chat VALUES (1, '+15550100', 'Alice');
        INSERT INTO chat VALUES (2, 'chat123', 'Team Group');

        INSERT INTO message VALUES (1, 'Hey, are we meeting tomorrow?', 1, 700000000000000000, 0, NULL);
        INSERT INTO message VALUES (2, 'Yes at 3pm!', 1, 700000060000000000, 1, NULL);
        INSERT INTO message VALUES (3, 'Group message about project', 2, 700000120000000000, 0, 'chat123');

        INSERT INTO chat_message_join VALUES (1, 1);
        INSERT INTO chat_message_join VALUES (1, 2);
        INSERT INTO chat_message_join VALUES (2, 3);
    """)
    conn.commit()
    conn.close()


@pytest.fixture()
def chat_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)
    return db_path


@pytest.fixture()
def connector(chat_db: Path):
    from openjarvis.connectors.imessage import IMessageConnector

    return IMessageConnector(db_path=str(chat_db))


def test_is_connected(connector) -> None:
    assert connector.is_connected()


def test_not_connected_missing_db() -> None:
    from openjarvis.connectors.imessage import IMessageConnector

    conn = IMessageConnector(db_path="/nonexistent/chat.db")
    assert not conn.is_connected()


def test_sync_yields_messages(connector) -> None:
    docs: List[Document] = list(connector.sync())
    assert len(docs) == 3
    assert all(d.source == "imessage" for d in docs)
    assert all(d.doc_type == "message" for d in docs)


def test_sync_message_content(connector) -> None:
    docs: List[Document] = list(connector.sync())
    texts = {d.content for d in docs}
    assert "Hey, are we meeting tomorrow?" in texts
    assert "Yes at 3pm!" in texts


def test_sync_sets_author(connector) -> None:
    docs: List[Document] = list(connector.sync())
    msg1 = next(d for d in docs if "meeting tomorrow" in d.content)
    assert msg1.author == "+15550100"


def test_disconnect(connector) -> None:
    connector.disconnect()
    assert not connector.is_connected()


def test_mcp_tools(connector) -> None:
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert "imessage_search_messages" in names
    assert "imessage_get_conversation" in names


def test_registry() -> None:
    from openjarvis.connectors.imessage import IMessageConnector

    ConnectorRegistry.register_value("imessage", IMessageConnector)
    assert ConnectorRegistry.contains("imessage")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_imessage.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement IMessageConnector**

Create `src/openjarvis/connectors/imessage.py`:

```python
"""iMessage connector — reads from macOS ~/Library/Messages/chat.db."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)

# macOS iMessage stores timestamps as nanoseconds since 2001-01-01
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_NS_FACTOR = 1_000_000_000

_DEFAULT_DB_PATH = str(
    Path.home() / "Library" / "Messages" / "chat.db"
)


def _apple_ts_to_datetime(apple_ts: int) -> datetime:
    """Convert Apple's nanosecond timestamp to datetime."""
    if apple_ts == 0:
        return datetime.now(tz=timezone.utc)
    try:
        seconds = apple_ts / _NS_FACTOR
        return datetime(
            2001, 1, 1, tzinfo=timezone.utc
        ) + __import__("datetime").timedelta(seconds=seconds)
    except (ValueError, OverflowError):
        return datetime.now(tz=timezone.utc)


@ConnectorRegistry.register("imessage")
class IMessageConnector(BaseConnector):
    """iMessage connector — reads from the local macOS Messages database.

    Requires Full Disk Access permission on macOS.
    """

    connector_id = "imessage"
    display_name = "iMessage"
    auth_type = "local"

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._connected = Path(self._db_path).exists()
        self._items_synced = 0

    def is_connected(self) -> bool:
        return self._connected and Path(self._db_path).exists()

    def disconnect(self) -> None:
        self._connected = False

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,
    ) -> Iterator[Document]:
        if not self.is_connected():
            return

        conn = sqlite3.connect(
            f"file:{self._db_path}?mode=ro", uri=True
        )
        conn.row_factory = sqlite3.Row

        # Build handle ID → identifier map
        handle_map: Dict[int, str] = {}
        for row in conn.execute("SELECT ROWID, id FROM handle"):
            handle_map[row["ROWID"]] = row["id"]

        # Build message → chat map
        msg_chat: Dict[int, int] = {}
        for row in conn.execute(
            "SELECT chat_id, message_id FROM chat_message_join"
        ):
            msg_chat[row["message_id"]] = row["chat_id"]

        # Build chat map
        chat_map: Dict[int, Dict[str, str]] = {}
        for row in conn.execute(
            "SELECT ROWID, chat_identifier, display_name FROM chat"
        ):
            chat_map[row["ROWID"]] = {
                "identifier": row["chat_identifier"],
                "display_name": row["display_name"] or "",
            }

        # Query messages
        sql = (
            "SELECT ROWID, text, handle_id, date, is_from_me,"
            " cache_roomnames FROM message WHERE text IS NOT NULL"
        )
        if since:
            # Convert since to Apple timestamp
            delta = since - _APPLE_EPOCH
            apple_ts = int(delta.total_seconds() * _NS_FACTOR)
            sql += f" AND date >= {apple_ts}"

        sql += " ORDER BY date ASC"
        synced = 0

        for row in conn.execute(sql):
            msg_id = row["ROWID"]
            text = row["text"] or ""
            handle_id = row["handle_id"]
            is_from_me = row["is_from_me"]

            sender = "me" if is_from_me else handle_map.get(handle_id, "")
            timestamp = _apple_ts_to_datetime(row["date"])

            # Determine chat context
            chat_id = msg_chat.get(msg_id, 0)
            chat_info = chat_map.get(chat_id, {})
            chat_name = (
                chat_info.get("display_name")
                or chat_info.get("identifier", "")
            )

            synced += 1
            yield Document(
                doc_id=f"imessage:{msg_id}",
                source="imessage",
                doc_type="message",
                content=text,
                title=chat_name,
                author=sender,
                participants=[sender],
                timestamp=timestamp,
                thread_id=chat_info.get("identifier"),
                metadata={
                    "chat_name": chat_name,
                    "is_from_me": bool(is_from_me),
                },
            )

        conn.close()
        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=self._items_synced)

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="imessage_search_messages",
                description="Search iMessage history by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
                category="communication",
            ),
            ToolSpec(
                name="imessage_get_conversation",
                description="Get messages from a specific iMessage conversation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "contact": {
                            "type": "string",
                            "description": "Phone number or email",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max messages",
                            "default": 50,
                        },
                    },
                    "required": ["contact"],
                },
                category="communication",
            ),
        ]
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/test_imessage.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/connectors/imessage.py tests/connectors/test_imessage.py
git commit -m "feat: add iMessage connector reading from macOS Messages database"
```

---

### Task 6: Wire Up Auto-Registration + Full Test Suite

**Files:**
- Modify: `src/openjarvis/connectors/__init__.py`

- [ ] **Step 1: Update __init__.py with all new connectors**

Add auto-imports for all 5 new connectors at the bottom of `src/openjarvis/connectors/__init__.py`:

```python
try:
    import openjarvis.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gdrive  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.imessage  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 2: Run ALL connector tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/connectors/ tests/tools/test_knowledge_search.py tests/cli/test_connect.py -v`

Expected: All tests PASS (Phase 1 tests + 5 new connector test files).

- [ ] **Step 3: Run linter on all new files**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run ruff check src/openjarvis/connectors/ tests/connectors/`

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/connectors/__init__.py
git commit -m "feat: auto-register all Phase 2A connectors (Slack, Drive, Calendar, Contacts, iMessage)"
```

---

## Post-Plan Notes

**What this plan produces:** 5 additional connectors bringing the total to 9 (Gmail, Obsidian, Notion, Granola, Slack, Google Drive, Google Calendar, Google Contacts, iMessage). All follow the established BaseConnector pattern with mocked tests.

**What comes next:**
- **Phase 2B:** Desktop setup wizard UI (Tauri/TypeScript/React) — the visual onboarding experience
- **Phase 3:** ColBERTv2 persistence + DeepResearchAgent
- **Phase 4:** Channel plugins (iMessage/WhatsApp/Slack for talking to the agent)
- **Phase 5:** Incremental sync, attachment store, settings page
