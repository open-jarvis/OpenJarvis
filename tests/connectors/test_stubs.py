"""Tests for connector base types and registry."""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, Optional

from openjarvis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from openjarvis.core.registry import ConnectorRegistry


class FakeConnector(BaseConnector):
    connector_id = "fake"
    display_name = "Fake"
    auth_type = "filesystem"

    def __init__(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        yield Document(
            doc_id="fake:1",
            source="fake",
            doc_type="note",
            content="Hello world",
            title="Test",
        )

    def sync_status(self) -> SyncStatus:
        return SyncStatus(state="idle", items_synced=1, items_total=1)


def test_document_creation() -> None:
    doc = Document(
        doc_id="gmail:abc123",
        source="gmail",
        doc_type="email",
        content="Meeting tomorrow at 3pm",
        title="Re: Project sync",
        author="alice@example.com",
        participants=["alice@example.com", "bob@example.com"],
    )
    assert doc.source == "gmail"
    assert doc.doc_type == "email"
    assert doc.thread_id is None
    assert doc.attachments == []


def test_attachment_creation() -> None:
    att = Attachment(
        filename="report.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        sha256="abcdef1234567890",
    )
    assert att.filename == "report.pdf"
    assert att.content == b""


def test_sync_status_defaults() -> None:
    status = SyncStatus()
    assert status.state == "idle"
    assert status.items_synced == 0
    assert status.cursor is None
    assert status.error is None


def test_base_connector_lifecycle() -> None:
    conn = FakeConnector()
    assert conn.is_connected()
    docs = list(conn.sync())
    assert len(docs) == 1
    assert docs[0].doc_id == "fake:1"
    assert conn.sync_status().state == "idle"
    conn.disconnect()
    assert not conn.is_connected()


def test_connector_registry() -> None:
    ConnectorRegistry.register_value("fake", FakeConnector)
    assert ConnectorRegistry.contains("fake")
    cls = ConnectorRegistry.get("fake")
    instance = cls()
    assert instance.connector_id == "fake"


def test_mcp_tools_default_empty() -> None:
    conn = FakeConnector()
    assert conn.mcp_tools() == []
