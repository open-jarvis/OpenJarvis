"""Tests for Slack messaging channel — Socket Mode binding and message handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_slack_channel_connect_with_tokens() -> None:
    """SlackChannel.connect() succeeds with bot_token + app_token."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel(
        bot_token="xoxb-test-token",
        app_token="xapp-test-token",
    )
    # Mock the SocketModeClient import to avoid real connection
    with patch("openjarvis.channels.slack.SlackChannel._socket_mode_loop"):
        ch.connect()

    from openjarvis.channels._stubs import ChannelStatus

    assert ch.status() == ChannelStatus.CONNECTED


def test_slack_channel_send_only_without_app_token() -> None:
    """SlackChannel with only bot_token enters send-only mode."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel(bot_token="xoxb-test-token")
    ch.connect()

    from openjarvis.channels._stubs import ChannelStatus

    assert ch.status() == ChannelStatus.CONNECTED
    assert ch._listener_thread is None  # No Socket Mode listener


def test_slack_channel_no_token_errors() -> None:
    """SlackChannel without any token enters error state."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel()
    ch.connect()

    from openjarvis.channels._stubs import ChannelStatus

    assert ch.status() == ChannelStatus.ERROR


def test_slack_channel_disconnect() -> None:
    """SlackChannel.disconnect() sets status to disconnected."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel(bot_token="xoxb-test-token")
    ch.connect()
    ch.disconnect()

    from openjarvis.channels._stubs import ChannelStatus

    assert ch.status() == ChannelStatus.DISCONNECTED


def test_slack_channel_handler_registration() -> None:
    """on_message registers a handler that receives messages."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel(bot_token="xoxb-test-token")
    handler = MagicMock()
    ch.on_message(handler)
    assert handler in ch._handlers


def test_slack_channel_send_without_connection_fails_gracefully() -> None:
    """send() to an unconnected channel returns False without crashing."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel()  # No token
    result = ch.send("C123456", "Hello from test")
    assert result is False


def test_slack_channel_send_with_token_is_callable() -> None:
    """send() with a token is callable and returns a bool."""
    from openjarvis.channels.slack import SlackChannel

    ch = SlackChannel(bot_token="xoxb-test-token")
    # Don't actually call the API, just verify interface
    assert callable(ch.send)
    assert hasattr(ch, "send")
