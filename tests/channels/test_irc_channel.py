"""Tests for the IRCChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.irc_channel import IRCChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_irc():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("irc"):
        ChannelRegistry.register_value("irc", IRCChannel)


class TestRegistration:
    def test_registry_key(self):
        assert ChannelRegistry.contains("irc")

    def test_channel_id(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        assert ch.channel_id == "irc"


class TestInit:
    def test_defaults(self):
        ch = IRCChannel()
        assert ch._server == ""
        assert ch._nick == ""
        assert ch._password == ""
        assert ch._port == 6667
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_params(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        assert ch._server == "irc.example.com"
        assert ch._nick == "jarvis"
        assert ch._password == "pass123"

    def test_env_var_fallback(self):
        with patch.dict(
            os.environ,
            {
                "IRC_SERVER": "irc.env.com",
                "IRC_NICK": "envbot",
                "IRC_PASSWORD": "envpass",
                "IRC_PORT": "6697",
            },
        ):
            ch = IRCChannel()
            assert ch._server == "irc.env.com"
            assert ch._nick == "envbot"
            assert ch._password == "envpass"
            assert ch._port == 6697

    def test_constructor_overrides_env(self):
        with patch.dict(
            os.environ,
            {
                "IRC_SERVER": "irc.env.com",
                "IRC_NICK": "envbot",
                "IRC_PASSWORD": "envpass",
            },
        ):
            ch = IRCChannel(
                server="irc.explicit.com",
                nick="explicit",
                password="explicit-pass",
            )
            assert ch._server == "irc.explicit.com"
            assert ch._nick == "explicit"
            assert ch._password == "explicit-pass"


class TestSend:
    def test_send_success(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")

        mock_sock = MagicMock()
        with patch("socket.socket", return_value=mock_sock):
            result = ch.send("#channel", "Hello!")
            assert result is True
            mock_sock.connect.assert_called_once()
            mock_sock.sendall.assert_called()

    def test_send_failure_exception(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")

        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionError("refused")
        with patch("socket.socket", return_value=mock_sock):
            result = ch.send("#channel", "Hello!")
            assert result is False

    def test_send_no_config(self):
        ch = IRCChannel()
        result = ch.send("#channel", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = IRCChannel(
            server="irc.example.com",
            nick="jarvis",
            password="pass123",
            bus=bus,
        )

        mock_sock = MagicMock()
        with patch("socket.socket", return_value=mock_sock):
            ch.send("#channel", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestListChannels:
    def test_list_channels(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        assert ch.list_channels() == ["irc"]


class TestStatus:
    def test_disconnected_initially(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_no_server_connect_error(self):
        ch = IRCChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestOnMessage:
    def test_on_message(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers


class TestDisconnect:
    def test_disconnect(self):
        ch = IRCChannel(server="irc.example.com", nick="jarvis", password="pass123")
        ch._status = ChannelStatus.CONNECTED
        ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED
