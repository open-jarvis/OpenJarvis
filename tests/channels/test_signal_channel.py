"""Tests for the SignalChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.signal_channel import SignalChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_signal():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("signal"):
        ChannelRegistry.register_value("signal", SignalChannel)


TestCommonChannel = make_common_channel_tests(
    SignalChannel,
    "signal",
    constructor_kwargs={
        "api_url": "http://localhost:8080",
        "phone_number": "+1234567890",
    },
)


class TestInit:
    def test_defaults(self):
        ch = SignalChannel()
        assert ch._api_url == ""
        assert ch._phone_number == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_params(self):
        ch = SignalChannel(api_url="http://localhost:8080", phone_number="+1234567890")
        assert ch._api_url == "http://localhost:8080"
        assert ch._phone_number == "+1234567890"

    def test_env_var_fallback(self):
        with patch.dict(
            os.environ,
            {
                "SIGNAL_API_URL": "http://env-signal:8080",
                "SIGNAL_PHONE_NUMBER": "+9876543210",
            },
        ):
            ch = SignalChannel()
            assert ch._api_url == "http://env-signal:8080"
            assert ch._phone_number == "+9876543210"

    def test_constructor_overrides_env(self):
        with patch.dict(
            os.environ,
            {
                "SIGNAL_API_URL": "http://env-signal:8080",
                "SIGNAL_PHONE_NUMBER": "+9876543210",
            },
        ):
            ch = SignalChannel(
                api_url="http://explicit:8080",
                phone_number="+1111111111",
            )
            assert ch._api_url == "http://explicit:8080"
            assert ch._phone_number == "+1111111111"


class TestSend:
    def test_send_success(self):
        ch = SignalChannel(api_url="http://localhost:8080", phone_number="+1234567890")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("+0987654321", "Hello!")
            assert result is True
            mock_post.assert_called_once()

    def test_send_failure(self):
        ch = SignalChannel(api_url="http://localhost:8080", phone_number="+1234567890")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("+0987654321", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = SignalChannel(api_url="http://localhost:8080", phone_number="+1234567890")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("+0987654321", "Hello!")
            assert result is False

    def test_send_no_config(self):
        ch = SignalChannel()
        result = ch.send("+0987654321", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = SignalChannel(
            api_url="http://localhost:8080",
            phone_number="+1234567890",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("+0987654321", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_config_connect_error(self):
        ch = SignalChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
