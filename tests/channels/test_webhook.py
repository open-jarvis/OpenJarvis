"""Tests for the WebhookChannel adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from friday_ai.channels._stubs import ChannelStatus
from friday_ai.channels.webhook import WebhookChannel
from friday_ai.core.events import EventBus, EventType
from friday_ai.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_webhook():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("webhook"):
        ChannelRegistry.register_value("webhook", WebhookChannel)


class TestRegistration:
    def test_registry_key(self):
        assert ChannelRegistry.contains("webhook")

    def test_channel_id(self):
        ch = WebhookChannel(url="https://example.com/hook")
        assert ch.channel_id == "webhook"


class TestInit:
    def test_defaults(self):
        ch = WebhookChannel()
        assert ch._url == ""
        assert ch._secret == ""
        assert ch._method == "POST"
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_params(self):
        ch = WebhookChannel(
            url="https://example.com/hook",
            secret="s3cr3t",
            method="PUT",
        )
        assert ch._url == "https://example.com/hook"
        assert ch._secret == "s3cr3t"
        assert ch._method == "PUT"


class TestConnect:
    def test_connect_with_url(self):
        ch = WebhookChannel(url="https://example.com/hook")
        ch.connect()
        assert ch.status() == ChannelStatus.CONNECTED

    def test_connect_no_url(self):
        ch = WebhookChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestSend:
    def test_send_success(self):
        ch = WebhookChannel(url="https://example.com/hook")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response) as mock_req:
            result = ch.send("target", "Hello!")
            assert result is True
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args[0][0] == "POST"
            assert call_args[0][1] == "https://example.com/hook"
            payload = call_args[1]["json"]
            assert payload["channel"] == "target"
            assert payload["content"] == "Hello!"

    def test_send_put_method(self):
        ch = WebhookChannel(url="https://example.com/hook", method="PUT")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response) as mock_req:
            ch.send("target", "Hello!")
            assert mock_req.call_args[0][0] == "PUT"

    def test_send_with_secret(self):
        ch = WebhookChannel(url="https://example.com/hook", secret="s3cr3t")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response) as mock_req:
            ch.send("target", "Hello!")
            headers = mock_req.call_args[1]["headers"]
            assert headers["X-Webhook-Secret"] == "s3cr3t"

    def test_send_without_secret(self):
        ch = WebhookChannel(url="https://example.com/hook")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response) as mock_req:
            ch.send("target", "Hello!")
            headers = mock_req.call_args[1]["headers"]
            assert "X-Webhook-Secret" not in headers

    def test_send_with_metadata(self):
        ch = WebhookChannel(url="https://example.com/hook")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response) as mock_req:
            ch.send("target", "Hello!", metadata={"key": "value"})
            payload = mock_req.call_args[1]["json"]
            assert payload["metadata"] == {"key": "value"}

    def test_send_failure(self):
        ch = WebhookChannel(url="https://example.com/hook")

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.request", return_value=mock_response):
            result = ch.send("target", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = WebhookChannel(url="https://example.com/hook")

        with patch("httpx.request", side_effect=ConnectionError("refused")):
            result = ch.send("target", "Hello!")
            assert result is False

    def test_send_no_url(self):
        ch = WebhookChannel()
        result = ch.send("target", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = WebhookChannel(url="https://example.com/hook", bus=bus)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.request", return_value=mock_response):
            ch.send("target", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestListChannels:
    def test_list_channels(self):
        ch = WebhookChannel(url="https://example.com/hook")
        assert ch.list_channels() == ["webhook"]


class TestStatus:
    def test_disconnected_initially(self):
        ch = WebhookChannel(url="https://example.com/hook")
        assert ch.status() == ChannelStatus.DISCONNECTED


class TestOnMessage:
    def test_on_message(self):
        ch = WebhookChannel(url="https://example.com/hook")
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


class TestDisconnect:
    def test_disconnect(self):
        ch = WebhookChannel(url="https://example.com/hook")
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED
