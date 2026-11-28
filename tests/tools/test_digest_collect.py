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

    def test_contact_connectors_stay_out_of_messages(self):
        """An address book is not message activity.

        Both contact connectors ignore ``since`` -- ``GContactsConnector``
        says so in its own docstring, because the People API cannot filter
        connections by date server-side.  Mapping them into MESSAGES puts
        the whole address book into a one-hour briefing: the section opens
        with a contact nobody touched.  Leaving them unmapped is the
        deliberate choice, not an oversight.
        """
        from openjarvis.tools.digest_collect import _CONNECTOR_TO_SECTION

        for connector in ("gcontacts", "apple_contacts"):
            assert _CONNECTOR_TO_SECTION.get(connector) != "MESSAGES", connector

    def test_no_connector_is_mapped_to_two_sections(self):
        from openjarvis.tools.digest_collect import _SECTION_ORDER

        seen: dict = {}
        for section, ids in _SECTION_ORDER:
            for cid in ids:
                assert cid not in seen, f"{cid} in {seen[cid]} and {section}"
                seen[cid] = section


def test_apple_calendar_event_reaches_the_briefing_with_when_and_where():
    """The briefing must carry the event, not just its name.

    This asserts the text the model actually receives.  Section mapping
    alone passed while the event still arrived as ``[apple_calendar] Board
    meeting``: classified correctly and stripped of everything that makes
    it useful.
    """
    from openjarvis.tools.digest_collect import DigestCollectTool

    event = Document(
        doc_id="apple_calendar:1",
        source="apple_calendar",
        doc_type="calendar_event",
        content="Board meeting\nDate: Thursday, November 20 2026 at 9:30 AM",
        title="Board meeting",
        timestamp=datetime(2026, 10, 1, 8, 0),
        metadata={
            "summary": "Board meeting",
            "calendar": "Work",
            "start": "2026-11-20T09:30:00",
            "all_day": False,
            "location": "Room 4",
        },
    )

    factory = MagicMock()
    factory.return_value.is_connected.return_value = True
    factory.return_value.sync.return_value = [event]
    with (
        patch.object(ConnectorRegistry, "contains", return_value=True),
        patch.object(ConnectorRegistry, "get", return_value=factory),
    ):
        result = DigestCollectTool().execute(sources=["apple_calendar"])

    assert "=== CALENDAR ===" in result.content
    line = next(ln for ln in result.content.splitlines() if "Board meeting" in ln)
    assert "Nov 20" in line
    assert "9:30 AM" in line
    assert "Room 4" in line


def test_contacts_do_not_open_the_messages_section():
    """A contact nobody touched must not show up as recent activity."""
    from openjarvis.tools.digest_collect import DigestCollectTool

    contact = Document(
        doc_id="gcontacts:1",
        source="gcontacts",
        doc_type="contact",
        content="An unrelated old contact",
        title="An unrelated old contact",
    )

    factory = MagicMock()
    factory.return_value.is_connected.return_value = True
    factory.return_value.sync.return_value = [contact]
    with (
        patch.object(ConnectorRegistry, "contains", return_value=True),
        patch.object(ConnectorRegistry, "get", return_value=factory),
    ):
        result = DigestCollectTool().execute(sources=["gcontacts"])

    assert "=== MESSAGES ===" not in result.content
