"""A2AAgentTool — wraps an external A2A agent as an invocable tool."""

from __future__ import annotations

import logging
from typing import Any

from friday_ai.a2a.client import A2AClient
from friday_ai.core.types import ToolResult
from friday_ai.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


class A2AAgentTool(BaseTool):
    """Wraps an external A2A agent as a BaseTool.

    Follows the MCPToolAdapter pattern for external tool integration.
    """

    tool_id: str

    def __init__(self, client: A2AClient, *, name: str = "") -> None:
        self._client = client
        self._name = name or "a2a_agent"
        self.tool_id = self._name
        # Try to discover agent info
        try:
            card = client.discover()
            if not name:
                self._name = f"a2a_{card.name.lower().replace(' ', '_')}"
                self.tool_id = self._name
            self._description = card.description or f"External A2A agent: {card.name}"
        except Exception as exc:
            logger.debug("Failed to fetch A2A agent description: %s", exc)
            self._description = "External A2A agent"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description=self._description,
            parameters={
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Input text to send to the remote agent.",
                    },
                },
                "required": ["input"],
            },
            category="a2a",
            required_capabilities=["network:fetch"],
        )

    def execute(self, **params: Any) -> ToolResult:
        input_text = params.get("input", "")
        if not input_text:
            return ToolResult(
                tool_name=self._name,
                content="No input provided.",
                success=False,
            )
        try:
            task = self._client.send_task(input_text)
            return ToolResult(
                tool_name=self._name,
                content=task.output_text,
                success=task.state in ("completed", "working"),
                metadata={"task_id": task.task_id, "state": str(task.state)},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self._name,
                content=f"A2A call failed: {exc}",
                success=False,
            )


__all__ = ["A2AAgentTool"]
