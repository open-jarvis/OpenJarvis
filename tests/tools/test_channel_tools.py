"""Tests for channel MCP tools — ChannelSendTool, ChannelListTool, ChannelStatusTool."""

from __future__ import annotations

import pytest

from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelStatus,
)
from openjarvis.mcp.server import MCPServer
from openjarvis.tools.channel_tools import (
    ChannelListTool,
    ChannelSendTool,
    ChannelStatusTool,
)


class _MockChannel(BaseChannel):
    """In-memory channel implementation for testing."""

    channel_id = "mock"

    def __init__(self):
        self._sent: list[dict] = []
        self._status = ChannelStatus.CONNECTED
        self._handlers: list[ChannelHandler] = []

    def connect(self) -> None:
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        self._status = ChannelStatus.DISCONNECTED

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        self._sent.append(
            {
                "channel": channel,
                "content": content,
                "conversation_id": conversation_id,
            }
        )
        return True

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> list[str]:
        return ["mock-channel-1", "mock-channel-2"]

    def on_message(self, handler) -> None:
        self._handlers.append(handler)


class _FailingChannel(_MockChannel):
    """Channel that always fails to send."""

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        return False


class _ErrorChannel(_MockChannel):
    """Channel that raises exceptions."""

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        raise RuntimeError("Connection lost")

    def list_channels(self) -> list[str]:
        raise RuntimeError("Connection lost")

    def status(self) -> ChannelStatus:
        raise RuntimeError("Connection lost")


@pytest.fixture
def channel():
    return _MockChannel()


class TestChannelSendTool:
    def test_spec(self):
        tool = ChannelSendTool()
        assert tool.spec.name == "channel_send"
        assert tool.spec.category == "channel"
        assert "channel" in tool.spec.parameters["required"]
        assert "content" in tool.spec.parameters["required"]

    def test_send_success(self, channel):
        tool = ChannelSendTool(channel)
        result = tool.execute(channel="chat-123", content="Hello!")
        assert result.success is True
        assert "chat-123" in result.content
        assert len(channel._sent) == 1
        assert channel._sent[0]["content"] == "Hello!"

    def test_send_with_conversation_id(self, channel):
        tool = ChannelSendTool(channel)
        result = tool.execute(
            channel="chat-123",
            content="Reply",
            conversation_id="conv-1",
        )
        assert result.success is True
        assert channel._sent[0]["conversation_id"] == "conv-1"

    def test_no_backend(self):
        tool = ChannelSendTool()
        result = tool.execute(channel="chat-123", content="Hello!")
        assert result.success is False
        assert "No channel backend" in result.content

    def test_missing_params(self, channel):
        tool = ChannelSendTool(channel)
        result = tool.execute()
        assert result.success is False
        assert "required" in result.content

    def test_missing_content(self, channel):
        tool = ChannelSendTool(channel)
        result = tool.execute(channel="chat-123")
        assert result.success is False

    def test_send_failure(self):
        tool = ChannelSendTool(_FailingChannel())
        result = tool.execute(channel="chat-123", content="Hello!")
        assert result.success is False
        assert "Failed" in result.content

    def test_error_handling(self):
        tool = ChannelSendTool(_ErrorChannel())
        result = tool.execute(channel="chat-123", content="Hello!")
        assert result.success is False
        assert "Send error" in result.content

    def test_tool_id(self):
        assert ChannelSendTool.tool_id == "channel_send"


class TestChannelListTool:
    def test_spec(self):
        tool = ChannelListTool()
        assert tool.spec.name == "channel_list"
        assert tool.spec.category == "channel"

    def test_list_success(self, channel):
        tool = ChannelListTool(channel)
        result = tool.execute()
        assert result.success is True
        assert "mock-channel-1" in result.content
        assert "mock-channel-2" in result.content

    def test_no_backend(self):
        tool = ChannelListTool()
        result = tool.execute()
        assert result.success is False
        assert "No channel backend" in result.content

    def test_error_handling(self):
        tool = ChannelListTool(_ErrorChannel())
        result = tool.execute()
        assert result.success is False
        assert "List error" in result.content

    def test_tool_id(self):
        assert ChannelListTool.tool_id == "channel_list"


class TestChannelStatusTool:
    def test_spec(self):
        tool = ChannelStatusTool()
        assert tool.spec.name == "channel_status"
        assert tool.spec.category == "channel"

    def test_status_success(self, channel):
        tool = ChannelStatusTool(channel)
        result = tool.execute()
        assert result.success is True
        assert "connected" in result.content

    def test_no_backend(self):
        tool = ChannelStatusTool()
        result = tool.execute()
        assert result.success is False
        assert "No channel backend" in result.content

    def test_error_handling(self):
        tool = ChannelStatusTool(_ErrorChannel())
        result = tool.execute()
        assert result.success is False
        assert "Status error" in result.content

    def test_tool_id(self):
        assert ChannelStatusTool.tool_id == "channel_status"


class TestChannelToolsMCPDiscovery:
    def test_auto_discover_finds_channel_tools(self):
        """MCPServer auto-discovery finds channel tools."""
        server = MCPServer()
        from openjarvis.mcp.protocol import MCPRequest

        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        names = {t["name"] for t in resp.result["tools"]}
        assert "channel_send" in names
        assert "channel_list" in names
        assert "channel_status" in names

    def test_channel_tool_annotations(self):
        """Channel tools have correct MCP annotations."""
        server = MCPServer()
        from openjarvis.mcp.protocol import MCPRequest

        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tools_by_name = {t["name"]: t for t in resp.result["tools"]}

        send_tool = tools_by_name.get("channel_send", {})
        assert send_tool.get("annotations", {}).get("destructiveHint") is True

        list_tool = tools_by_name.get("channel_list", {})
        assert list_tool.get("annotations", {}).get("readOnlyHint") is True
