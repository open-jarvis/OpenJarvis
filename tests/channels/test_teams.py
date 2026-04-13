"""Tests for the TeamsChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.teams import TeamsChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_teams():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("teams"):
        ChannelRegistry.register_value("teams", TeamsChannel)


TestCommonChannel = make_common_channel_tests(
    TeamsChannel,
    "teams",
    constructor_kwargs={"app_id": "test-id", "app_password": "test-pass"},
)


class TestInit:
    def test_defaults(self):
        ch = TeamsChannel()
        assert ch._app_id == ""
        assert ch._app_password == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_param(self):
        ch = TeamsChannel(app_id="test-id", app_password="test-pass")
        assert ch._app_id == "test-id"
        assert ch._app_password == "test-pass"

    def test_env_var_fallback(self):
        env = {
            "TEAMS_APP_ID": "env-id",
            "TEAMS_APP_PASSWORD": "env-pass",
        }
        with patch.dict(os.environ, env):
            ch = TeamsChannel()
            assert ch._app_id == "env-id"
            assert ch._app_password == "env-pass"

    def test_constructor_overrides_env(self):
        env = {
            "TEAMS_APP_ID": "env-id",
            "TEAMS_APP_PASSWORD": "env-pass",
        }
        with patch.dict(os.environ, env):
            ch = TeamsChannel(app_id="explicit-id", app_password="explicit-pass")
            assert ch._app_id == "explicit-id"
            assert ch._app_password == "explicit-pass"


class TestSend:
    def test_send_success(self):
        ch = TeamsChannel(app_id="test-id", app_password="test-pass")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = ch.send("general", "Hello!")
            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            url = call_args[0][0]
            assert "/v3/conversations/" in url
            assert "general" in url

    def test_send_failure(self):
        ch = TeamsChannel(app_id="test-id", app_password="test-pass")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.post", return_value=mock_response):
            result = ch.send("general", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = TeamsChannel(app_id="test-id", app_password="test-pass")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("general", "Hello!")
            assert result is False

    def test_send_no_config(self):
        ch = TeamsChannel()
        result = ch.send("general", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = TeamsChannel(app_id="test-id", app_password="test-pass", bus=bus)

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.post", return_value=mock_response):
            ch.send("general", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_config_connect_error(self):
        ch = TeamsChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
