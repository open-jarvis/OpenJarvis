"""Tests for the TwitterChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.twitter_channel import TwitterChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_twitter():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("twitter"):
        ChannelRegistry.register_value("twitter", TwitterChannel)


class TestRegistration:
    def test_registry_key(self):
        assert ChannelRegistry.contains("twitter")

    def test_channel_id(self):
        ch = TwitterChannel(bearer_token="test-bearer")
        assert ch.channel_id == "twitter"


class TestInit:
    def test_defaults(self):
        ch = TwitterChannel()
        assert ch._bearer == ""
        assert ch._api_key == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_bearer(self):
        ch = TwitterChannel(bearer_token="my-bearer")
        assert ch._bearer == "my-bearer"

    def test_env_var_fallback(self):
        env = {
            "TWITTER_BEARER_TOKEN": "env-bearer",
            "TWITTER_API_KEY": "env-key",
            "TWITTER_API_SECRET": "env-secret",
            "TWITTER_ACCESS_TOKEN": "env-access",
            "TWITTER_ACCESS_SECRET": "env-acc-secret",
            "TWITTER_BOT_USER_ID": "12345",
        }
        with patch.dict(os.environ, env):
            ch = TwitterChannel()
            assert ch._bearer == "env-bearer"
            assert ch._api_key == "env-key"
            assert ch._api_secret == "env-secret"
            assert ch._access_token == "env-access"
            assert ch._access_secret == "env-acc-secret"
            assert ch._bot_user_id == "12345"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"TWITTER_BEARER_TOKEN": "env-bearer"}):
            ch = TwitterChannel(bearer_token="explicit-bearer")
            assert ch._bearer == "explicit-bearer"


class TestSend:
    def test_send_success(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("twitter", "Hello from OpenJarvis!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert "api.twitter.com/2/tweets" in url
            payload = call_args[1]["json"]
            assert payload["text"] == "Hello from OpenJarvis!"
            assert "reply" not in payload

    def test_send_as_reply(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send(
                "twitter", "Replying!", conversation_id="9876543210",
            )
            assert result is True
            payload = mock_post.call_args[1]["json"]
            assert payload["reply"]["in_reply_to_tweet_id"] == "9876543210"

    def test_send_truncates_to_280(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        mock_response = MagicMock()
        mock_response.status_code = 201

        long_text = "A" * 300
        with patch("httpx.post", return_value=mock_response) as mock_post:
            ch.send("twitter", long_text)
            payload = mock_post.call_args[1]["json"]
            assert len(payload["text"]) == 280

    def test_send_failure(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("twitter", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
        )

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("twitter", "Hello!")
            assert result is False

    def test_send_no_credentials(self):
        ch = TwitterChannel()
        result = ch.send("twitter", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = TwitterChannel(
            bearer_token="b",
            api_key="ck",
            api_secret="cs",
            access_token="at",
            access_secret="as",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("httpx.post", return_value=mock_response):
            ch.send("twitter", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestListChannels:
    def test_list_channels(self):
        ch = TwitterChannel(bearer_token="b")
        assert ch.list_channels() == ["twitter"]


class TestStatus:
    def test_disconnected_initially(self):
        ch = TwitterChannel(bearer_token="b")
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_no_token_connect_error(self):
        ch = TwitterChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestOnMessage:
    def test_on_message(self):
        ch = TwitterChannel(bearer_token="b")
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


class TestDisconnect:
    def test_disconnect(self):
        ch = TwitterChannel(bearer_token="b")
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED
