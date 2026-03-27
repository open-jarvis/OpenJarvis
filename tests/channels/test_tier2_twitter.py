"""Tests for the TwitterChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.twitter import TwitterChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_twitter():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("twitter"):
        ChannelRegistry.register_value("twitter", TwitterChannel)


def test_twitter_channel_registered():
    """Twitter channel should be discoverable via the registry."""
    assert ChannelRegistry.contains("twitter")
    cls = ChannelRegistry.get("twitter")
    assert cls is TwitterChannel


def test_twitter_no_credentials_status():
    """Without credentials, connect() sets status to ERROR."""
    ch = TwitterChannel()
    ch.connect()
    assert ch.status() == ChannelStatus.ERROR


def test_twitter_send_no_credentials_returns_false():
    """send() returns False when client is not connected."""
    ch = TwitterChannel()
    result = ch.send("timeline", "Hello Twitter!")
    assert result is False


def test_twitter_send_tweet():
    """send() with a non-numeric channel calls create_tweet."""
    ch = TwitterChannel(bearer_token="test-bearer")
    mock_client = MagicMock()
    ch._client = mock_client
    ch._status = ChannelStatus.CONNECTED

    result = ch.send("timeline", "Hello from Jarvis!")
    assert result is True
    mock_client.create_tweet.assert_called_once_with(text="Hello from Jarvis!")


def test_twitter_send_dm_when_channel_is_numeric():
    """send() with a numeric channel calls create_direct_message."""
    ch = TwitterChannel(bearer_token="test-bearer")
    mock_client = MagicMock()
    ch._client = mock_client
    ch._status = ChannelStatus.CONNECTED

    result = ch.send("12345678", "Hello via DM!")
    assert result is True
    mock_client.create_direct_message.assert_called_once_with(
        participant_id=12345678,
        text="Hello via DM!",
    )


def test_twitter_send_reply():
    """send() with conversation_id sets in_reply_to_tweet_id."""
    ch = TwitterChannel(bearer_token="test-bearer")
    mock_client = MagicMock()
    ch._client = mock_client
    ch._status = ChannelStatus.CONNECTED

    result = ch.send(
        "timeline",
        "This is a reply",
        conversation_id="999888777",
    )
    assert result is True
    mock_client.create_tweet.assert_called_once_with(
        text="This is a reply",
        in_reply_to_tweet_id=999888777,
    )


def test_twitter_list_channels():
    """list_channels() returns the expected identifiers."""
    ch = TwitterChannel()
    assert ch.list_channels() == ["timeline", "dm"]


def test_twitter_event_bus_integration():
    """Successful send publishes CHANNEL_MESSAGE_SENT on the event bus."""
    bus = EventBus(record_history=True)
    ch = TwitterChannel(bearer_token="test-bearer", bus=bus)
    mock_client = MagicMock()
    ch._client = mock_client
    ch._status = ChannelStatus.CONNECTED

    ch.send("timeline", "Event test!")

    event_types = [e.event_type for e in bus.history]
    assert EventType.CHANNEL_MESSAGE_SENT in event_types

    sent_event = next(
        e for e in bus.history if e.event_type == EventType.CHANNEL_MESSAGE_SENT
    )
    assert sent_event.data["content"] == "Event test!"
    assert sent_event.data["channel"] == "timeline"


@pytest.mark.live_channel
def test_twitter_connect_live():
    """Live test: connect with real credentials from env vars.

    Skipped unless all required env vars are set.
    """
    required_vars = [
        "TWITTER_BEARER_TOKEN",
        "TWITTER_API_KEY",
        "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_SECRET",
    ]
    for var in required_vars:
        if not os.environ.get(var):
            pytest.skip(f"Missing env var {var}")

    ch = TwitterChannel()
    ch.connect()
    assert ch.status() == ChannelStatus.CONNECTED
    ch.disconnect()
    assert ch.status() == ChannelStatus.DISCONNECTED
