"""Tests for channel registration in the ChannelRegistry."""

from __future__ import annotations

from typing import List

import pytest

from openjarvis.channels._stubs import BaseChannel, ChannelHandler, ChannelStatus
from openjarvis.core.registry import ChannelRegistry


class TestChannelRegistry:
    def test_register_channel(self) -> None:
        """Register a dummy channel class and verify it is in ChannelRegistry."""

        @ChannelRegistry.register("dummy")
        class DummyChannel(BaseChannel):
            channel_id = "dummy"

            def connect(self) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def send(
                self,
                channel,
                content,
                *,
                conversation_id="",
                metadata=None,
            ) -> bool:
                return True

            def status(self) -> ChannelStatus:
                return ChannelStatus.DISCONNECTED

            def list_channels(self) -> List[str]:
                return []

            def on_message(self, handler: ChannelHandler) -> None:
                pass

        assert ChannelRegistry.contains("dummy")
        assert ChannelRegistry.get("dummy") is DummyChannel

    def test_create_channel(self) -> None:
        """Register and create an instance via ChannelRegistry.create()."""

        @ChannelRegistry.register("creatable")
        class CreatableChannel(BaseChannel):
            channel_id = "creatable"

            def connect(self) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def send(
                self,
                channel,
                content,
                *,
                conversation_id="",
                metadata=None,
            ) -> bool:
                return True

            def status(self) -> ChannelStatus:
                return ChannelStatus.DISCONNECTED

            def list_channels(self) -> List[str]:
                return []

            def on_message(self, handler: ChannelHandler) -> None:
                pass

        instance = ChannelRegistry.create("creatable")
        assert isinstance(instance, CreatableChannel)
        assert instance.channel_id == "creatable"

    def test_duplicate_registration_raises(self) -> None:
        """Registering the same key twice should raise ValueError."""
        ChannelRegistry.register_value("dup", object)
        with pytest.raises(ValueError, match="already has an entry"):
            ChannelRegistry.register_value("dup", object)

    def test_get_missing_key_raises(self) -> None:
        """Getting an unregistered key should raise KeyError."""
        with pytest.raises(KeyError, match="does not have an entry"):
            ChannelRegistry.get("nonexistent")

    def test_keys_and_items(self) -> None:
        """Verify keys() and items() return registered entries."""

        @ChannelRegistry.register("test-ch")
        class TestCh(BaseChannel):
            channel_id = "test-ch"

            def connect(self) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def send(
                self,
                channel,
                content,
                *,
                conversation_id="",
                metadata=None,
            ) -> bool:
                return True

            def status(self) -> ChannelStatus:
                return ChannelStatus.DISCONNECTED

            def list_channels(self):
                return []

            def on_message(self, handler) -> None:
                pass

        assert "test-ch" in ChannelRegistry.keys()
        keys_from_items = [k for k, v in ChannelRegistry.items()]
        assert "test-ch" in keys_from_items
