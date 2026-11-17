"""Tests for the digest_collect tool."""

from __future__ import annotations

import importlib
from datetime import datetime
from unittest.mock import MagicMock, patch

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry, ToolRegistry


def test_digest_collect_registered():
    from openjarvis.tools import digest_collect

    # The registry fixture clears entries, while Python caches imported modules.
    if not ToolRegistry.contains("digest_collect"):
        importlib.reload(digest_collect)
    assert ToolRegistry.get("digest_collect") is digest_collect.DigestCollectTool


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


class TestSectionMapping:
    """Every connector a briefing section needs must map to that section.

    An unmapped connector is not dropped -- it lands under OTHER, which is
    worse than an error: the data is collected, the section it belongs to
    stays empty, and nothing reports a problem.
    """

    def test_apple_calendar_belongs_to_the_calendar_section(self):
        from openjarvis.tools.digest_collect import _CONNECTOR_TO_SECTION

        assert _CONNECTOR_TO_SECTION.get("apple_calendar") == "CALENDAR"

    def test_both_calendars_land_in_the_same_section(self):
        from openjarvis.tools.digest_collect import _CONNECTOR_TO_SECTION

        assert (
            _CONNECTOR_TO_SECTION["apple_calendar"]
            == (_CONNECTOR_TO_SECTION["gcalendar"])
        )

    def test_contact_connectors_are_mapped(self):
        from openjarvis.tools.digest_collect import _CONNECTOR_TO_SECTION

        for connector in ("gcontacts", "apple_contacts"):
            assert connector in _CONNECTOR_TO_SECTION, connector

    def test_no_connector_is_mapped_to_two_sections(self):
        from openjarvis.tools.digest_collect import _SECTION_ORDER

        seen: dict = {}
        for section, ids in _SECTION_ORDER:
            for cid in ids:
                assert cid not in seen, f"{cid} in {seen[cid]} and {section}"
                seen[cid] = section


def test_native_calendar_and_contacts_reach_their_briefing_sections():
    from openjarvis.tools.digest_collect import DigestCollectTool

    docs = {
        source: [
            Document(
                doc_id=source,
                source=source,
                doc_type="test",
                content=title,
                title=title,
            )
        ]
        for source, title in {
            "apple_calendar": "Tomorrow planning meeting",
            "apple_contacts": "Alice native contact",
            "gcontacts": "Bob Google contact",
        }.items()
    }
    factories = {}
    for source, documents in docs.items():
        factory = MagicMock()
        factory.return_value.is_connected.return_value = True
        factory.return_value.sync.return_value = documents
        factories[source] = factory
    with (
        patch.object(ConnectorRegistry, "contains", return_value=True),
        patch.object(ConnectorRegistry, "get", side_effect=factories.__getitem__),
    ):
        result = DigestCollectTool().execute(sources=list(docs))
    messages, calendar = result.content.split("=== CALENDAR ===")
    assert "=== MESSAGES ===" in messages
    assert "Alice native contact" in messages
    assert "Bob Google contact" in messages
    assert "Tomorrow planning meeting" in calendar
    assert "=== OTHER ===" not in result.content
    assert result.metadata["total_items"] == 3
