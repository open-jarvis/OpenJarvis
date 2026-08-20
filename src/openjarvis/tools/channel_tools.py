"""Channel MCP tools — expose channel operations as BaseTool instances.

These tools wrap the ``BaseChannel`` ABC so that channel operations
(send, list, status) are discoverable and callable via MCP.
"""

from __future__ import annotations

from typing import Any

from openjarvis.channels._stubs import BaseChannel
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("channel_send")
class ChannelSendTool(BaseTool):
    """MCP-exposed tool: send a message via a channel backend."""

    tool_id = "channel_send"
    is_local = False

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_send",
            description="Send a message to a channel (Telegram, Discord, Slack, etc.).",
            parameters={
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Target chat/channel ID to send to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The message content to send.",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional conversation/thread ID for replies.",
                    },
                },
                "required": ["channel", "content"],
            },
            category="channel",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._channel is None:
            return ToolResult(
                tool_name="channel_send",
                content="No channel backend configured.",
                success=False,
            )
        target = params.get("channel", "")
        content = params.get("content", "")
        if not target or not content:
            return ToolResult(
                tool_name="channel_send",
                content="Both 'channel' and 'content' are required.",
                success=False,
            )
        try:
            ok = self._channel.send(
                target,
                content,
                conversation_id=params.get("conversation_id", ""),
            )
            if ok:
                return ToolResult(
                    tool_name="channel_send",
                    content=f"Message sent to {target}",
                    success=True,
                )
            return ToolResult(
                tool_name="channel_send",
                content=f"Failed to send message to {target}",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_send",
                content=f"Send error: {exc}",
                success=False,
            )


@ToolRegistry.register("channel_list")
class ChannelListTool(BaseTool):
    """MCP-exposed tool: list available channels."""

    tool_id = "channel_list"

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_list",
            description="List available messaging channels.",
            parameters={
                "type": "object",
                "properties": {},
            },
            category="channel",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._channel is None:
            return ToolResult(
                tool_name="channel_list",
                content="No channel backend configured.",
                success=False,
            )
        try:
            channels = self._channel.list_channels()
            if not channels:
                return ToolResult(
                    tool_name="channel_list",
                    content="No channels available.",
                    success=True,
                )
            return ToolResult(
                tool_name="channel_list",
                content="\n".join(channels),
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_list",
                content=f"List error: {exc}",
                success=False,
            )


@ToolRegistry.register("channel_status")
class ChannelStatusTool(BaseTool):
    """MCP-exposed tool: check channel connection status."""

    tool_id = "channel_status"

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_status",
            description="Check the connection status of the messaging channel.",
            parameters={
                "type": "object",
                "properties": {},
            },
            category="channel",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._channel is None:
            return ToolResult(
                tool_name="channel_status",
                content="No channel backend configured.",
                success=False,
            )
        try:
            st = self._channel.status()
            return ToolResult(
                tool_name="channel_status",
                content=f"Channel status: {st.value}",
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_status",
                content=f"Status error: {exc}",
                success=False,
            )


__all__ = [
    "ChannelListTool",
    "ChannelSendTool",
    "ChannelStatusTool",
]
