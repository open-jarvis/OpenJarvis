"""Tests for the WhatsAppChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.whatsapp import WhatsAppChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_whatsapp():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("whatsapp"):
        ChannelRegistry.register_value("whatsapp", WhatsAppChannel)


TestCommonChannel = make_common_channel_tests(
    WhatsAppChannel,
    "whatsapp",
    constructor_kwargs={"access_token": "test-token", "phone_number_id": "12345"},
)


class TestInit:
    def test_defaults(self):
        ch = WhatsAppChannel()
        assert ch._token == ""
        assert ch._phone_number_id == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_token(self):
        ch = WhatsAppChannel(access_token="my-token", phone_number_id="12345")
        assert ch._token == "my-token"
        assert ch._phone_number_id == "12345"

    def test_env_var_fallback(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "env-token",
                "WHATSAPP_PHONE_NUMBER_ID": "env-id",
            },
        ):
            ch = WhatsAppChannel()
            assert ch._token == "env-token"
            assert ch._phone_number_id == "env-id"

    def test_constructor_overrides_env(self):
        with patch.dict(
            os.environ,
            {
                "WHATSAPP_ACCESS_TOKEN": "env-token",
                "WHATSAPP_PHONE_NUMBER_ID": "env-id",
            },
        ):
            ch = WhatsAppChannel(
                access_token="explicit-token",
                phone_number_id="explicit-id",
            )
            assert ch._token == "explicit-token"
            assert ch._phone_number_id == "explicit-id"


class TestSend:
    def test_send_success(self):
        ch = WhatsAppChannel(access_token="test-token", phone_number_id="12345")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("+1234567890", "Hello!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert "graph.facebook.com" in url
            assert "12345" in url

    def test_send_failure(self):
        ch = WhatsAppChannel(access_token="test-token", phone_number_id="12345")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("+1234567890", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = WhatsAppChannel(access_token="test-token", phone_number_id="12345")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("+1234567890", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = WhatsAppChannel()
        result = ch.send("+1234567890", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = WhatsAppChannel(
            access_token="test-token",
            phone_number_id="12345",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("+1234567890", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_token_connect_error(self):
        ch = WhatsAppChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
