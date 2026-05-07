"""Tests for the BlueBubblesChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.bluebubbles import BlueBubblesChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_bluebubbles():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("bluebubbles"):
        ChannelRegistry.register_value("bluebubbles", BlueBubblesChannel)


TestCommonChannel = make_common_channel_tests(
    BlueBubblesChannel,
    "bluebubbles",
    constructor_kwargs={"url": "http://localhost:1234", "password": "test-pass"},
)


class TestInit:
    def test_defaults(self):
        ch = BlueBubblesChannel()
        assert ch._url == ""
        assert ch._password == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_param(self):
        ch = BlueBubblesChannel(url="http://localhost:1234", password="test-pass")
        assert ch._url == "http://localhost:1234"
        assert ch._password == "test-pass"

    def test_env_var_fallback(self):
        env = {
            "BLUEBUBBLES_URL": "http://env:1234",
            "BLUEBUBBLES_PASSWORD": "env-pass",
        }
        with patch.dict(os.environ, env):
            ch = BlueBubblesChannel()
            assert ch._url == "http://env:1234"
            assert ch._password == "env-pass"

    def test_constructor_overrides_env(self):
        env = {
            "BLUEBUBBLES_URL": "http://env:1234",
            "BLUEBUBBLES_PASSWORD": "env-pass",
        }
        with patch.dict(os.environ, env):
            ch = BlueBubblesChannel(
                url="http://explicit:1234",
                password="explicit-pass",
            )
            assert ch._url == "http://explicit:1234"
            assert ch._password == "explicit-pass"


class TestSend:
    def test_send_success(self):
        ch = BlueBubblesChannel(url="http://localhost:1234", password="test-pass")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("iMessage;+;chat123", "Hello!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["params"] == {"password": "test-pass"}
            payload = call_args[1]["json"]
            assert "chatGuid" in payload
            assert payload["chatGuid"] == "iMessage;+;chat123"
            assert "message" in payload
            assert payload["message"] == "Hello!"

    def test_send_failure(self):
        ch = BlueBubblesChannel(url="http://localhost:1234", password="test-pass")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("iMessage;+;chat123", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = BlueBubblesChannel(url="http://localhost:1234", password="test-pass")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("iMessage;+;chat123", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = BlueBubblesChannel()
        result = ch.send("iMessage;+;chat123", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = BlueBubblesChannel(
            url="http://localhost:1234",
            password="test-pass",
            bus=bus,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("iMessage;+;chat123", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_url_connect_error(self):
        ch = BlueBubblesChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
