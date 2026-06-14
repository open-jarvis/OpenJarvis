"""A2A delegation tool — lets an agent invoke another agent at runtime.

This is the bridge between the tool-calling framework and the agent
registry.  When a tool-using agent (e.g. ``bavaria_booking``) discovers a
task outside its domain (e.g. a legal compliance issue), it can call
``agent_delegate`` to hand the query off to the right specialist and
receive the result back as an observation.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)


@ToolRegistry.register("agent_delegate")
class AgentDelegateTool(BaseTool):
    """Invoke another registered agent and return its output.

    Parameters
    ----------
    engine:
        The inference engine to hand to the sub-agent.
    model:
        Model name for the sub-agent.
    bus:
        Optional event bus.
    temperature, max_tokens:
        Generation defaults forwarded to the sub-agent.
    capability_policy:
        Optional RBAC policy forwarded to the sub-agent's tool executor.
    """

    tool_id = "agent_delegate"

    def __init__(
        self,
        engine: Optional[InferenceEngine] = None,
        model: str = "",
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        capability_policy: Optional[Any] = None,
    ) -> None:
        self._engine = engine
        self._model = model
        self._bus = bus
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._capability_policy = capability_policy

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="agent_delegate",
            description=(
                "Delegate a task to another specialised agent."
                " Provide the target agent_id and a clear query."
                " The sub-agent runs to completion and its final answer"
                " is returned as the tool result."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Registered agent id to invoke"
                            " (e.g. 'legal_assistant', 'security_assistant')."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "The task or question for the sub-agent.",
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Optional additional context"
                            " (background info, previous results)."
                        ),
                    },
                },
                "required": ["agent_id", "query"],
            },
            category="agents",
            required_capabilities=["system:admin"],
        )

    def execute(
        self,
        *,
        agent_id: str,
        query: str,
        context: str = "",
    ) -> ToolResult:
        """Instantiate *agent_id*, run it with *query*, and return the result."""
        if self._engine is None or not self._model:
            return ToolResult(
                tool_name="agent_delegate",
                content=(
                    "AgentDelegateTool is not configured with an engine or model. "
                    "It can only be used inside an A2AChain."
                ),
                success=False,
            )
        if not AgentRegistry.contains(agent_id):
            return ToolResult(
                tool_name="agent_delegate",
                content=f"Agent '{agent_id}' is not registered.",
                success=False,
            )

        agent_cls = AgentRegistry.get(agent_id)

        # Build kwargs dynamically based on what the target accepts
        sig = inspect.signature(agent_cls.__init__)
        kwargs: Dict[str, Any] = {
            "bus": self._bus,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        # Only pass keys the constructor actually accepts
        kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

        if "capability_policy" in sig.parameters:
            kwargs["capability_policy"] = self._capability_policy
        if "agent_id" in sig.parameters:
            kwargs["agent_id"] = agent_id

        # Never pass tools to the sub-agent to avoid recursive delegation loops.
        # If the target agent is a ToolUsingAgent it will simply run without
        # tool-calling (plain text mode).
        if "tools" in sig.parameters:
            kwargs["tools"] = []
        if "interactive" in sig.parameters:
            kwargs["interactive"] = False
        if "confirm_callback" in sig.parameters:
            kwargs["confirm_callback"] = lambda _p: True
        if "max_turns" in sig.parameters:
            kwargs["max_turns"] = 5

        try:
            agent = agent_cls(self._engine, self._model, **kwargs)
        except Exception as exc:
            logger.exception("Failed to instantiate sub-agent %s", agent_id)
            return ToolResult(
                tool_name="agent_delegate",
                content=f"Failed to start agent '{agent_id}': {exc}",
                success=False,
            )

        # Assemble input: prepend optional context if provided
        full_input = query
        if context:
            full_input = f"[Context]\n{context}\n\n[Task]\n{query}"

        try:
            result: AgentResult = agent.run(full_input, context=AgentContext())
        except Exception as exc:
            logger.exception("Sub-agent %s crashed during run", agent_id)
            return ToolResult(
                tool_name="agent_delegate",
                content=f"Agent '{agent_id}' crashed: {exc}",
                success=False,
            )

        return ToolResult(
            tool_name="agent_delegate",
            content=result.content,
            success=True,
            metadata={
                "sub_agent": agent_id,
                "sub_turns": result.turns,
                "sub_tool_results": len(result.tool_results),
            },
        )


__all__ = ["AgentDelegateTool"]
