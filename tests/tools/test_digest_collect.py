"""Tests for the digest_collect tool."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry, ToolRegistry


def test_digest_collect_registered():
    from openjarvis.tools.digest_collect import DigestCollectTool

    ToolRegistry.register_value("digest_collect", DigestCollectTool)
    assert ToolRegistry.contains("digest_collect")


def test_digest_collect_executes():
    from openjarvis.tools.digest_collect import DigestCollectTool

    tool = DigestCollectTool()

    mock_docs = [
        Document(
            doc_id="test-1",
            source="gmail",
            doc_type="email",
            content="Meeting at 3pm",
            title="Team standup",
            author="alice@example.com",
            timestamp=datetime(2026, 4, 1, 10, 0),
        )
    ]

    mock_connector = MagicMock()
    mock_connector.return_value.is_connected.return_value = True
    mock_connector.return_value.sync.return_value = mock_docs

    with patch.object(ConnectorRegistry, "contains", return_value=True):
        with patch.object(ConnectorRegistry, "get", return_value=mock_connector):
            result = tool.execute(sources=["gmail"], hours_back=24)

    assert result.success is True
    assert "=== MESSAGES ===" in result.content
    assert "[gmail id=test-1] From: alice@example.com" in result.content
    assert "Team standup" in result.content
    assert result.metadata["total_items"] == 1


def test_digest_collect_missing_connector():
    from openjarvis.tools.digest_collect import DigestCollectTool

    tool = DigestCollectTool()

    with patch.object(ConnectorRegistry, "contains", return_value=False):
        result = tool.execute(sources=["nonexistent"])

    assert result.success is True  # Partial success
    assert "not available" in result.content


def test_digest_collect_shows_calendar_start_time():
    from openjarvis.tools.digest_collect import DigestCollectTool

    tool = DigestCollectTool()

    mock_docs = [
        Document(
            doc_id="evt-1",
            source="gcalendar",
            doc_type="event",
            content="When: 2026-04-01T09:05:00 – 2026-04-01T10:35:00",
            title="Design review",
            timestamp=datetime(2026, 4, 1, 9, 5),
        )
    ]

    mock_connector = MagicMock()
    mock_connector.return_value.is_connected.return_value = True
    mock_connector.return_value.sync.return_value = mock_docs

    with patch.object(ConnectorRegistry, "contains", return_value=True):
        with patch.object(ConnectorRegistry, "get", return_value=mock_connector):
            result = tool.execute(sources=["gcalendar"], hours_back=24)

    expected = "[gcalendar id=evt-1] 9:05 AM — Design review (1 hour 30 min)"
    assert expected in result.content


def test_oura_line_without_day_uses_timestamp_date():
    from openjarvis.tools.digest_collect import _format_doc

    doc = Document(
        doc_id="sleep-1",
        source="oura",
        doc_type="sleep",
        content='{"score": 82}',
        timestamp=datetime(2026, 4, 1, 7, 0),
        metadata={"data_type": "sleep"},
    )

    assert _format_doc("oura", doc).startswith("[oura] Sleep — April 1: score 82")
