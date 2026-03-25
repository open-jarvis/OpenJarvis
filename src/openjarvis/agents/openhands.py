"""OpenHandsAgent -- wraps the real openhands-sdk for AI-driven development.

Requires the ``openhands-sdk`` package (``uv sync --extra openhands``).
For the native CodeAct-style agent, see :mod:`openjarvis.agents.native_openhands`.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.engine._stubs import InferenceEngine


@AgentRegistry.register("openhands")
class OpenHandsAgent(BaseAgent):
    """Agent that wraps the real openhands-sdk package.

    This is a thin adapter that delegates to the ``openhands-sdk``
    library for AI-driven software development tasks.  Requires
    ``openhands-sdk`` to be installed.
    """

    agent_id = "openhands"
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._workspace = workspace or os.getcwd()
        self._api_key = api_key or os.environ.get("LLM_API_KEY", "")

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        try:
            from openhands.sdk import (  # type: ignore[import-untyped]
                LLM,
                Agent,
                Conversation,
            )
        except ImportError:
            raise ImportError(
                "OpenHandsAgent requires the openhands-sdk package. "
                "Install it with: uv sync --extra openhands"
            ) from None

        self._emit_turn_start(input)

        llm = LLM(model=self._model, api_key=self._api_key)
        agent = Agent(llm=llm)
        conversation = Conversation(agent=agent, workspace=self._workspace)
        conversation.send_message(input)
        conversation.run()

        # Extract result from conversation
        messages = conversation.get_messages()
        content = messages[-1].content if messages else ""

        self._emit_turn_end(turns=1)
        return AgentResult(content=content, turns=1)


__all__ = ["OpenHandsAgent"]
