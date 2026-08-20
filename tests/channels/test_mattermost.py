"""Tests for the MattermostChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.mattermost import MattermostChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_mattermost():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("mattermost"):
        ChannelRegistry.register_value("mattermost", MattermostChannel)


TestCommonChannel = make_common_channel_tests(
    MattermostChannel,
    "mattermost",
    constructor_kwargs={"url": "https://mattermost.example.com", "token": "test-token"},
)


class TestInit:
    def test_defaults(self):
        ch = MattermostChannel()
        assert ch._url == ""
        assert ch._token == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_param(self):
        ch = MattermostChannel(url="https://mattermost.example.com", token="test-token")
        assert ch._url == "https://mattermost.example.com"
        assert ch._token == "test-token"

    def test_env_var_fallback(self):
        env = {
            "MATTERMOST_URL": "https://env.example.com",
            "MATTERMOST_TOKEN": "env-token",
        }
        with patch.dict(os.environ, env):
            ch = MattermostChannel()
            assert ch._url == "https://env.example.com"
            assert ch._token == "env-token"

    def test_constructor_overrides_env(self):
        env = {
            "MATTERMOST_URL": "https://env.example.com",
            "MATTERMOST_TOKEN": "env-token",
        }
        with patch.dict(os.environ, env):
            ch = MattermostChannel(
                url="https://explicit.example.com",
                token="explicit-token",
            )
            assert ch._url == "https://explicit.example.com"
            assert ch._token == "explicit-token"


class TestSend:
    def test_send_success(self):
        ch = MattermostChannel(url="https://mattermost.example.com", token="test-token")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("channel-id-123", "Hello!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert url.endswith("/api/v4/posts")

    def test_send_with_conversation_id(self):
        ch = MattermostChannel(url="https://mattermost.example.com", token="test-token")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("channel-id-123", "Hello!", conversation_id="root-123")
            assert result is True
            call_args = mock_post.call_args
            payload = call_args[1]["json"]
            assert "root_id" in payload
            assert payload["root_id"] == "root-123"

    def test_send_failure(self):
        ch = MattermostChannel(url="https://mattermost.example.com", token="test-token")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("channel-id-123", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = MattermostChannel(url="https://mattermost.example.com", token="test-token")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("channel-id-123", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = MattermostChannel()
        result = ch.send("channel-id-123", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = MattermostChannel(
            url="https://mattermost.example.com",
            token="test-token",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("channel-id-123", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_url_connect_error(self):
        ch = MattermostChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
