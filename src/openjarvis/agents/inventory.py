"""Inventory Agent — handles stock, supplies, and procurement queries."""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool


@AgentRegistry.register("inventory")
class InventoryAgent(ToolUsingAgent):
    """Domain agent for housekeeping inventory, supplies, and procurement."""

    agent_id = "inventory"
    _default_temperature = 0.3
    _default_max_tokens = 2048
    _default_max_turns = 6

    _SYSTEM_PROMPT = (
        "You are the Housekeeping & Inventory specialist for Landhaus Bavaria. "
        "Track linen, toiletries, minibar supplies, and maintenance items. "
        "Alert when stock is low and suggest reorder quantities."
    )

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[Any] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        from openjarvis.core.types import Message, Role

        self._emit_turn_start(input)
        messages = [
            Message(role=Role.SYSTEM, content=self._SYSTEM_PROMPT),
            Message(role=Role.USER, content=input),
        ]
        result = self._generate(messages)
        self._emit_turn_end(turns=1)
        return AgentResult(
            content=result.get("content", ""),
            tool_results=[],
            turns=1,
            metadata={"agent": self.agent_id},
        )
