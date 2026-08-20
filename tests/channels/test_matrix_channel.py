"""Tests for the MatrixChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.matrix_channel import MatrixChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_matrix():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("matrix"):
        ChannelRegistry.register_value("matrix", MatrixChannel)


TestCommonChannel = make_common_channel_tests(
    MatrixChannel,
    "matrix",
    constructor_kwargs={
        "homeserver": "https://matrix.example.com",
        "access_token": "test-token",
    },
)


class TestInit:
    def test_defaults(self):
        ch = MatrixChannel()
        assert ch._homeserver == ""
        assert ch._access_token == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_param(self):
        ch = MatrixChannel(
            homeserver="https://matrix.example.com",
            access_token="test-token",
        )
        assert ch._homeserver == "https://matrix.example.com"
        assert ch._access_token == "test-token"

    def test_env_var_fallback(self):
        env = {
            "MATRIX_HOMESERVER": "https://env.example.com",
            "MATRIX_ACCESS_TOKEN": "env-token",
        }
        with patch.dict(os.environ, env):
            ch = MatrixChannel()
            assert ch._homeserver == "https://env.example.com"
            assert ch._access_token == "env-token"

    def test_constructor_overrides_env(self):
        env = {
            "MATRIX_HOMESERVER": "https://env.example.com",
            "MATRIX_ACCESS_TOKEN": "env-token",
        }
        with patch.dict(os.environ, env):
            ch = MatrixChannel(
                homeserver="https://explicit.example.com",
                access_token="explicit-token",
            )
            assert ch._homeserver == "https://explicit.example.com"
            assert ch._access_token == "explicit-token"


class TestSend:
    def test_send_success(self):
        ch = MatrixChannel(
            homeserver="https://matrix.example.com",
            access_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.put", return_value=mock_response) as mock_put:
            result = ch.send("!room123:example.com", "Hello!")
            assert result is True
            mock_put.assert_called_once()
            call_args = mock_put.call_args
            url = call_args[0][0]
            assert "/_matrix/client/v3/rooms/" in url
            assert "!room123:example.com" in url

    def test_send_failure(self):
        ch = MatrixChannel(
            homeserver="https://matrix.example.com",
            access_token="test-token",
        )

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.put", return_value=mock_response):
            result = ch.send("!room123:example.com", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = MatrixChannel(
            homeserver="https://matrix.example.com",
            access_token="test-token",
        )

        with patch("httpx.put", side_effect=ConnectionError("refused")):
            result = ch.send("!room123:example.com", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = MatrixChannel()
        result = ch.send("!room123:example.com", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = MatrixChannel(
            homeserver="https://matrix.example.com",
            access_token="test-token",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.put", return_value=mock_response):
            ch.send("!room123:example.com", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_homeserver_connect_error(self):
        ch = MatrixChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
