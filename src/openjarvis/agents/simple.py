"""SimpleAgent — single-turn query-to-response agent (no tool calling)."""

from __future__ import annotations

from typing import Any, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.registry import AgentRegistry


@AgentRegistry.register("simple")
class SimpleAgent(BaseAgent):
    """Single-turn agent: query -> model -> response.  No tool calling."""

    agent_id = "simple"

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Single-turn: build messages, call engine, return result."""
        self._emit_turn_start(input)

        messages = self._build_messages(input, context)
        result = self._generate(messages)
        content = result.get("content", "")

        self._emit_turn_end(content_length=len(content))

        return AgentResult(content=content, turns=1)


__all__ = ["SimpleAgent"]
