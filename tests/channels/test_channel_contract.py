"""Parametrized contract tests — verify every channel implements BaseChannel correctly.

These tests run without any credentials and verify that all channel adapters
handle graceful degradation (no crashes on missing auth, idempotent disconnect,
valid enum returns).
"""

from __future__ import annotations

import importlib

import pytest

import openjarvis.channels  # noqa: F401 — trigger registration
from openjarvis.channels._stubs import ChannelStatus
from openjarvis.core.registry import ChannelRegistry

# Collect channel classes at import time (before registry gets cleared).
# We store the actual class objects, not registry keys, so they survive
# the autouse _clean_registries fixture.
importlib.reload(openjarvis.channels)
_ALL_CHANNELS = [(key, ChannelRegistry.get(key)) for key in ChannelRegistry.keys()]


@pytest.fixture(params=_ALL_CHANNELS, ids=lambda x: x[0])
def channel_entry(request):
    """Parametrized fixture yielding (channel_key, channel_cls) tuples.

    Uses the class reference captured at import time — does not depend
    on the registry being populated at test time.
    """
    return request.param


def test_has_channel_id(channel_entry):
    key, channel_cls = channel_entry
    assert hasattr(channel_cls, "channel_id")
    assert isinstance(channel_cls.channel_id, str)
    assert len(channel_cls.channel_id) > 0


def test_connect_no_credentials_no_crash(channel_entry):
    key, channel_cls = channel_entry
    ch = channel_cls()
    ch.connect()
    # Should not raise — just set status to ERROR or DISCONNECTED


def test_disconnect_idempotent(channel_entry):
    key, channel_cls = channel_entry
    ch = channel_cls()
    ch.disconnect()
    ch.disconnect()  # Second call should not raise


def test_status_returns_valid_enum(channel_entry):
    key, channel_cls = channel_entry
    ch = channel_cls()
    s = ch.status()
    assert isinstance(s, ChannelStatus)


def test_list_channels_returns_list(channel_entry):
    key, channel_cls = channel_entry
    ch = channel_cls()
    result = ch.list_channels()
    assert isinstance(result, list)


def test_send_no_credentials_returns_false(channel_entry):
    key, channel_cls = channel_entry
    if key == "webchat":
        pytest.skip("WebChatChannel is in-memory and always succeeds")
    ch = channel_cls()
    result = ch.send("test", "hello")
    assert result is False


def test_on_message_accepts_handler(channel_entry):
    key, channel_cls = channel_entry
    ch = channel_cls()
    ch.on_message(lambda msg: None)
    # Should not raise
