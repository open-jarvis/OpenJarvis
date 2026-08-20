"""Shared parametrized tests for channel implementations.

Every channel must pass these baseline tests. Import and call
``make_common_channel_tests`` to generate a test class.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.core.registry import ChannelRegistry


def make_common_channel_tests(
    channel_cls,
    channel_key: str,
    *,
    constructor_kwargs: dict | None = None,
):
    """Return a test class that validates common channel contract.

    Usage in each test file::

        from tests.channels.channel_test_helpers import (
            make_common_channel_tests,
        )
        TestCommonChannel = make_common_channel_tests(
            SlackChannel, "slack",
            constructor_kwargs={"bot_token": "xoxb-test"},
        )
    """
    kwargs = constructor_kwargs or {}

    class CommonChannelTests:
        def test_registry_key(self):
            assert ChannelRegistry.contains(channel_key)

        def test_channel_id(self):
            ch = channel_cls(**kwargs)
            assert ch.channel_id == channel_key

        def test_list_channels(self):
            ch = channel_cls(**kwargs)
            assert ch.list_channels() == [channel_key]

        def test_disconnected_initially(self):
            ch = channel_cls(**kwargs)
            assert ch.status() == ChannelStatus.DISCONNECTED

        def test_on_message_registers_handler(self):
            ch = channel_cls(**kwargs)
            handler = MagicMock()
            ch.on_message(handler)
            assert handler in ch._handlers

        def test_disconnect(self):
            ch = channel_cls(**kwargs)
            ch._status = ChannelStatus.CONNECTED
            ch.disconnect()
            assert ch.status() == ChannelStatus.DISCONNECTED

    CommonChannelTests.__name__ = f"TestCommon_{channel_key}"
    CommonChannelTests.__qualname__ = f"TestCommon_{channel_key}"
    return CommonChannelTests
