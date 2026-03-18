"""Tests for the channel abstraction stubs."""

from __future__ import annotations

from typing import Optional

import pytest

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelMessage,
    ChannelStatus,
)


class TestChannelStatus:
    def test_channel_status_values(self) -> None:
        assert ChannelStatus.CONNECTED == "connected"
        assert ChannelStatus.DISCONNECTED == "disconnected"
        assert ChannelStatus.CONNECTING == "connecting"
        assert ChannelStatus.ERROR == "error"

    def test_channel_status_is_str(self) -> None:
        assert isinstance(ChannelStatus.CONNECTED, str)

    def test_channel_status_membership(self) -> None:
        values = {s.value for s in ChannelStatus}
        assert values == {"connected", "disconnected", "connecting", "error"}


class TestChannelMessage:
    def test_channel_message_creation(self) -> None:
        msg = ChannelMessage(
            channel="slack",
            sender="user123",
            content="Hello, world!",
            message_id="msg-001",
            conversation_id="conv-001",
            metadata={"thread_ts": "12345.6789"},
        )
        assert msg.channel == "slack"
        assert msg.sender == "user123"
        assert msg.content == "Hello, world!"
        assert msg.message_id == "msg-001"
        assert msg.conversation_id == "conv-001"
        assert msg.metadata == {"thread_ts": "12345.6789"}

    def test_channel_message_defaults(self) -> None:
        msg = ChannelMessage(channel="discord", sender="bot", content="Hi")
        assert msg.message_id == ""
        assert msg.conversation_id == ""
        assert msg.metadata == {}

    def test_channel_message_metadata_isolation(self) -> None:
        msg1 = ChannelMessage(channel="a", sender="b", content="c")
        msg2 = ChannelMessage(channel="a", sender="b", content="c")
        msg1.metadata["key"] = "val"
        assert "key" not in msg2.metadata


class TestBaseChannel:
    def test_base_channel_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            BaseChannel()  # type: ignore[abstract]

    def test_channel_handler_type(self) -> None:
        """ChannelHandler should accept ChannelMessage and return Optional[str]."""

        def my_handler(msg: ChannelMessage) -> Optional[str]:
            return f"Received: {msg.content}"

        # Verify the handler can be called with a ChannelMessage
        msg = ChannelMessage(channel="test", sender="user", content="hello")
        result = my_handler(msg)
        assert result == "Received: hello"

    def test_channel_handler_none_return(self) -> None:
        def my_handler(msg: ChannelMessage) -> Optional[str]:
            return None

        msg = ChannelMessage(channel="test", sender="user", content="hello")
        result = my_handler(msg)
        assert result is None

    def test_concrete_subclass(self) -> None:
        """A concrete subclass implementing all methods should be instantiable."""

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

            def list_channels(self):
                return []

            def on_message(self, handler) -> None:
                pass

        ch = DummyChannel()
        assert ch.channel_id == "dummy"
        assert ch.status() == ChannelStatus.DISCONNECTED
        assert ch.send("test", "hello") is True
        assert ch.list_channels() == []
