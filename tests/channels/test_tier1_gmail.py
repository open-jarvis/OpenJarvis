"""Tests for the GmailChannel adapter."""

from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.gmail import GmailChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_gmail():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("gmail"):
        ChannelRegistry.register_value("gmail", GmailChannel)


class TestRegistration:
    def test_gmail_channel_registered(self):
        assert ChannelRegistry.contains("gmail")

    def test_channel_id(self):
        ch = GmailChannel()
        assert ch.channel_id == "gmail"


class TestNoCredentials:
    def test_gmail_no_credentials_status(self):
        ch = GmailChannel()
        ch.connect()
        assert ch.status() in (ChannelStatus.ERROR, ChannelStatus.DISCONNECTED)

    def test_gmail_send_no_credentials_returns_false(self):
        ch = GmailChannel()
        result = ch.send("recipient@example.com", "Hello!")
        assert result is False


class TestSend:
    def test_gmail_send_constructs_mime(self):
        ch = GmailChannel()
        mock_service = MagicMock()
        ch._service = mock_service
        ch._status = ChannelStatus.CONNECTED

        result = ch.send("recipient@example.com", "Hello Gmail!")
        assert result is True

        # Verify send was called
        mock_service.users().messages().send.assert_called_once()
        call_kwargs = mock_service.users().messages().send.call_args[1]
        assert call_kwargs["userId"] == "me"

        # Verify the body contains base64-encoded MIME message
        body = call_kwargs["body"]
        assert "raw" in body
        decoded = base64.urlsafe_b64decode(body["raw"]).decode("utf-8")
        assert "recipient@example.com" in decoded
        assert "Hello Gmail!" in decoded

    def test_gmail_send_with_thread_id(self):
        ch = GmailChannel()
        mock_service = MagicMock()
        ch._service = mock_service
        ch._status = ChannelStatus.CONNECTED

        result = ch.send(
            "recipient@example.com",
            "Thread reply",
            conversation_id="thread-abc123",
        )
        assert result is True

        call_kwargs = mock_service.users().messages().send.call_args[1]
        body = call_kwargs["body"]
        assert body["threadId"] == "thread-abc123"

    def test_gmail_send_with_subject_metadata(self):
        ch = GmailChannel()
        mock_service = MagicMock()
        ch._service = mock_service
        ch._status = ChannelStatus.CONNECTED

        result = ch.send(
            "recipient@example.com",
            "Body text",
            metadata={"subject": "Custom Subject"},
        )
        assert result is True

        call_kwargs = mock_service.users().messages().send.call_args[1]
        decoded = base64.urlsafe_b64decode(
            call_kwargs["body"]["raw"],
        ).decode("utf-8")
        assert "Custom Subject" in decoded

    def test_gmail_send_exception_returns_false(self):
        ch = GmailChannel()
        mock_service = MagicMock()
        mock_service.users().messages().send().execute.side_effect = RuntimeError(
            "API error"
        )
        ch._service = mock_service
        ch._status = ChannelStatus.CONNECTED

        result = ch.send("recipient@example.com", "Hello!")
        assert result is False


class TestListChannels:
    def test_gmail_list_channels(self):
        ch = GmailChannel()
        assert ch.list_channels() == ["inbox"]


class TestOnMessage:
    def test_gmail_on_message_registers_handler(self):
        ch = GmailChannel()
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


class TestEventBus:
    def test_gmail_event_bus_integration(self):
        bus = EventBus(record_history=True)
        ch = GmailChannel(bus=bus)
        mock_service = MagicMock()
        ch._service = mock_service
        ch._status = ChannelStatus.CONNECTED

        ch.send("recipient@example.com", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_disconnected_initially(self):
        ch = GmailChannel()
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_status_error_when_connected_but_no_service(self):
        ch = GmailChannel()
        ch._status = ChannelStatus.CONNECTED
        ch._service = None
        assert ch.status() == ChannelStatus.ERROR


class TestDisconnect:
    def test_disconnect(self):
        ch = GmailChannel()
        ch._service = MagicMock()
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED
        assert ch._service is None


class TestEnvVarFallback:
    def test_credentials_path_env_var(self):
        with patch.dict(os.environ, {"GMAIL_CREDENTIALS_PATH": "/tmp/creds.json"}):
            ch = GmailChannel()
            assert ch._credentials_path == "/tmp/creds.json"

    def test_token_path_env_var(self):
        with patch.dict(os.environ, {"GMAIL_TOKEN_PATH": "/tmp/token.json"}):
            ch = GmailChannel()
            assert ch._token_path == "/tmp/token.json"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"GMAIL_CREDENTIALS_PATH": "/env/creds.json"}):
            ch = GmailChannel(credentials_path="/explicit/creds.json")
            assert ch._credentials_path == "/explicit/creds.json"


@pytest.mark.live_channel
class TestLive:
    def test_gmail_send_live(self):
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "")
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "")
        recipient = os.environ.get("GMAIL_TEST_RECIPIENT", "")

        if not creds_path and not token_path:
            pytest.skip("No Gmail credentials configured")
        if not recipient:
            pytest.skip("No GMAIL_TEST_RECIPIENT configured")

        ch = GmailChannel(
            credentials_path=creds_path,
            token_path=token_path,
        )
        ch.connect()
        if ch.status() != ChannelStatus.CONNECTED:
            pytest.skip("Gmail channel failed to connect")

        result = ch.send(
            recipient,
            "OpenJarvis Gmail channel test message",
            metadata={"subject": "OpenJarvis Test"},
        )
        assert result is True
        ch.disconnect()
