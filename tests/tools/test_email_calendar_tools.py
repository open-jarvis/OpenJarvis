"""Tests for email/calendar agent tools (connectors mocked)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from openjarvis.core.registry import ConnectorRegistry
from openjarvis.tools.email_calendar_tools import (
    CalendarCreateEventTool,
    CalendarListEventsTool,
    EmailListTool,
    EmailSendTool,
)


def _connected(**methods):
    """Build a mock connector that reports itself connected."""
    conn = MagicMock()
    conn.is_connected.return_value = True
    for name, val in methods.items():
        setattr(conn, name, val)
    return conn


def _patch_registry(conn):
    """Patch ConnectorRegistry so tools resolve to the mock connector."""
    return (
        patch.object(ConnectorRegistry, "contains", return_value=True),
        patch.object(ConnectorRegistry, "get", return_value=lambda: conn),
    )


# ---------------------------------------------------------------------------
# Specs / confirmation gating
# ---------------------------------------------------------------------------


def test_email_send_requires_confirmation():
    spec = EmailSendTool().spec
    assert spec.requires_confirmation is True
    assert "channel:send" in spec.required_capabilities


def test_calendar_create_requires_confirmation():
    spec = CalendarCreateEventTool().spec
    assert spec.requires_confirmation is True
    assert "calendar:write" in spec.required_capabilities


def test_read_tools_do_not_require_confirmation():
    assert EmailListTool().spec.requires_confirmation is False
    assert CalendarListEventsTool().spec.requires_confirmation is False


# ---------------------------------------------------------------------------
# email_send
# ---------------------------------------------------------------------------


def test_email_send_success():
    conn = _connected(send_message=MagicMock(return_value="msg123"))
    c1, c2 = _patch_registry(conn)
    with c1, c2:
        result = EmailSendTool().execute(
            to="alice@example.com, bob@example.com",
            subject="Hi",
            body="Hello there",
        )
    assert result.success is True
    assert "msg123" in result.content
    kwargs = conn.send_message.call_args.kwargs
    assert kwargs["to"] == ["alice@example.com", "bob@example.com"]
    assert kwargs["subject"] == "Hi"


def test_email_send_missing_recipient():
    result = EmailSendTool().execute(to="", subject="x", body="y")
    assert result.success is False
    assert "recipient" in result.content.lower()


def test_email_send_not_connected():
    conn = MagicMock()
    conn.is_connected.return_value = False
    with patch.object(ConnectorRegistry, "contains", return_value=True), patch.object(
        ConnectorRegistry, "get", return_value=lambda: conn
    ):
        result = EmailSendTool().execute(
            to="a@example.com", subject="x", body="y"
        )
    assert result.success is False
    assert "not connected" in result.content.lower()


# ---------------------------------------------------------------------------
# email_list
# ---------------------------------------------------------------------------


def test_email_list_success():
    doc = SimpleNamespace(
        title="Subject A",
        author="alice@example.com",
        timestamp=datetime(2026, 6, 5, 9, 30),
        metadata={"snippet": "hello"},
    )
    conn = _connected(sync=MagicMock(return_value=iter([doc])))
    c1, c2 = _patch_registry(conn)
    with c1, c2:
        result = EmailListTool().execute(max_results=5)
    assert result.success is True
    assert "Subject A" in result.content
    assert result.metadata["count"] == 1


# ---------------------------------------------------------------------------
# calendar_create_event
# ---------------------------------------------------------------------------


def test_calendar_create_success():
    conn = _connected(
        create_event=MagicMock(
            return_value={"id": "evt1", "htmlLink": "https://cal/evt1"}
        )
    )
    c1, c2 = _patch_registry(conn)
    with c1, c2:
        result = CalendarCreateEventTool().execute(
            summary="Standup",
            start="2026-06-10T09:00:00",
            end="2026-06-10T09:30:00",
            attendees="a@x.com, b@x.com",
        )
    assert result.success is True
    assert result.metadata["event_id"] == "evt1"
    kwargs = conn.create_event.call_args.kwargs
    assert kwargs["summary"] == "Standup"
    assert kwargs["attendees"] == ["a@x.com", "b@x.com"]


def test_calendar_create_missing_fields():
    result = CalendarCreateEventTool().execute(summary="x", start="", end="")
    assert result.success is False


# ---------------------------------------------------------------------------
# calendar_list_events
# ---------------------------------------------------------------------------


def test_calendar_list_success():
    doc = SimpleNamespace(
        title="Meeting", timestamp=datetime(2026, 6, 6, 14, 0)
    )
    conn = _connected(sync=MagicMock(return_value=iter([doc])))
    c1, c2 = _patch_registry(conn)
    with c1, c2:
        result = CalendarListEventsTool().execute(days_ahead=7)
    assert result.success is True
    assert "Meeting" in result.content
