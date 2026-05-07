"""Tests for the FeishuChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.feishu import FeishuChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_feishu():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("feishu"):
        ChannelRegistry.register_value("feishu", FeishuChannel)


TestCommonChannel = make_common_channel_tests(
    FeishuChannel,
    "feishu",
    constructor_kwargs={"app_id": "test-id", "app_secret": "test-secret"},
)


class TestInit:
    def test_defaults(self):
        ch = FeishuChannel()
        assert ch._app_id == ""
        assert ch._app_secret == ""
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_param(self):
        ch = FeishuChannel(app_id="test-id", app_secret="test-secret")
        assert ch._app_id == "test-id"
        assert ch._app_secret == "test-secret"

    def test_env_var_fallback(self):
        env = {
            "FEISHU_APP_ID": "env-id",
            "FEISHU_APP_SECRET": "env-secret",
        }
        with patch.dict(os.environ, env):
            ch = FeishuChannel()
            assert ch._app_id == "env-id"
            assert ch._app_secret == "env-secret"

    def test_constructor_overrides_env(self):
        env = {
            "FEISHU_APP_ID": "env-id",
            "FEISHU_APP_SECRET": "env-secret",
        }
        with patch.dict(os.environ, env):
            ch = FeishuChannel(app_id="explicit-id", app_secret="explicit-secret")
            assert ch._app_id == "explicit-id"
            assert ch._app_secret == "explicit-secret"


class TestSend:
    def test_send_success(self):
        ch = FeishuChannel(app_id="test-id", app_secret="test-secret")

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"tenant_access_token": "fake-token"}

        msg_resp = MagicMock()
        msg_resp.status_code = 200

        with patch("httpx.post", side_effect=[token_resp, msg_resp]) as mock_post:
            result = ch.send("chat_id", "Hello!")
            assert result is True
            assert mock_post.call_count == 2

    def test_send_failure(self):
        ch = FeishuChannel(app_id="test-id", app_secret="test-secret")

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"tenant_access_token": "fake-token"}

        msg_resp = MagicMock()
        msg_resp.status_code = 400
        msg_resp.text = "Bad Request"

        with patch("httpx.post", side_effect=[token_resp, msg_resp]):
            result = ch.send("chat_id", "Hello!")
            assert result is False

    def test_send_exception(self):
        ch = FeishuChannel(app_id="test-id", app_secret="test-secret")

        with patch("httpx.post", side_effect=ConnectionError("refused")):
            result = ch.send("chat_id", "Hello!")
            assert result is False

    def test_send_no_token(self):
        ch = FeishuChannel()
        result = ch.send("chat_id", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = FeishuChannel(app_id="test-id", app_secret="test-secret", bus=bus)

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"tenant_access_token": "fake-token"}

        msg_resp = MagicMock()
        msg_resp.status_code = 200

        with patch("httpx.post", side_effect=[token_resp, msg_resp]):
            ch.send("chat_id", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_no_config_connect_error(self):
        ch = FeishuChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR
