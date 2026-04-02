"""ABC for agent implementations.

Adapted from IPW's ``BaseAgent`` at ``src/agents/base.py``.
Provides ``BaseAgent`` with concrete helper methods for event emission,
message building, and generation, plus ``ToolUsingAgent`` intermediate
base for agents that accept tools.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Conversation, Message, Role, ToolResult
from openjarvis.engine._stubs import InferenceEngine


@dataclass(slots=True)
class AgentContext:
    """Runtime context handed to an agent on each invocation."""

    conversation: Conversation = field(default_factory=Conversation)
    tools: List[str] = field(default_factory=list)
    memory_results: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    """Result returned after an agent completes a run."""

    content: str
    tool_results: List[ToolResult] = field(default_factory=list)
    turns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Base class for all agent implementations.

    Subclasses must be registered via
    ``@AgentRegistry.register("name")`` to become discoverable.

    Provides concrete helper methods that eliminate boilerplate in
    subclasses:

    - :meth:`_emit_turn_start` / :meth:`_emit_turn_end` -- event bus
    - :meth:`_build_messages` -- conversation + system prompt assembly
    - :meth:`_generate` -- delegates to engine with stored defaults
    - :meth:`_max_turns_result` -- standard max-turns-exceeded result
    - :meth:`_strip_think_tags` -- remove ``<think>`` blocks
    """

    agent_id: str
    accepts_tools: bool = False

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        prompt_builder: Optional[Any] = None,
    ) -> None:
        self._engine = engine
        self._model = model
        self._bus = bus
        self._prompt_builder = prompt_builder

        # Three-tier resolution: explicit arg > config > class default > hardcoded
        if temperature is not None and max_tokens is not None:
            self._temperature = temperature
            self._max_tokens = max_tokens
        else:
            try:
                cfg = load_config()
                self._temperature = (
                    temperature
                    if temperature is not None
                    else cfg.intelligence.temperature
                )
                self._max_tokens = (
                    max_tokens
                    if max_tokens is not None
                    else cfg.intelligence.max_tokens
                )
            except Exception:
                self._temperature = (
                    temperature
                    if temperature is not None
                    else getattr(self, "_default_temperature", 0.7)
                )
                self._max_tokens = (
                    max_tokens
                    if max_tokens is not None
                    else getattr(self, "_default_max_tokens", 1024)
                )

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def _emit_turn_start(self, input: str) -> None:
        """Publish ``AGENT_TURN_START`` if an event bus is available."""
        if self._bus:
            self._bus.publish(
                EventType.AGENT_TURN_START,
                {"agent": self.agent_id, "input": input},
            )

    def _emit_turn_end(self, **data: Any) -> None:
        """Publish ``AGENT_TURN_END`` if an event bus is available."""
        if self._bus:
            payload: Dict[str, Any] = {"agent": self.agent_id}
            payload.update(data)
            self._bus.publish(EventType.AGENT_TURN_END, payload)

    def _build_messages(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        *,
        system_prompt: Optional[str] = None,
    ) -> list[Message]:
        """Assemble the message list for a generate call.

        Optionally prepends a system prompt, then appends any context
        conversation messages, and finally the user input.
        """
        messages: list[Message] = []
        if self._prompt_builder is not None:
            effective_system_prompt = self._prompt_builder.build()
        elif system_prompt:
            effective_system_prompt = system_prompt
        else:
            effective_system_prompt = None
        if effective_system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=effective_system_prompt))
        if context and context.conversation.messages:
            messages.extend(context.conversation.messages)
        messages.append(Message(role=Role.USER, content=input))
        return messages

    def _generate(self, messages: list[Message], **extra_kwargs: Any) -> dict:
        """Call ``engine.generate()`` with stored defaults.

        Extra kwargs (e.g. ``tools``) are forwarded to the engine.
        Publishes INFERENCE_START/END events on the bus when the engine
        does not publish its own (i.e. non-instrumented engines).
        """
        if self._bus and not getattr(self._engine, "_publishes_events", False):
            engine_id = getattr(self._engine, "engine_id", "")
            self._bus.publish(
                EventType.INFERENCE_START,
                {"model": self._model, "engine": engine_id},
            )

        result = self._engine.generate(
            messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **extra_kwargs,
        )

        if self._bus and not getattr(self._engine, "_publishes_events", False):
            usage = result.get("usage", {})
            self._bus.publish(
                EventType.INFERENCE_END,
                {
                    "model": self._model,
                    "usage": usage,
                    "content": result.get("content", ""),
                    "tool_calls": result.get("tool_calls", []),
                    "finish_reason": result.get("finish_reason", ""),
                },
            )

        return result

    def _max_turns_result(
        self,
        tool_results: list[ToolResult],
        turns: int,
        content: str = "",
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """Build the standard result for when ``max_turns`` is exceeded."""
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        md: Dict[str, Any] = {"max_turns_exceeded": True}
        if metadata:
            md.update(metadata)
        return AgentResult(
            content=content or "Maximum turns reached without a final answer.",
            tool_results=tool_results,
            turns=turns,
            metadata=md,
        )

    def _check_continuation(
        self,
        result: dict,
        messages: list,
        *,
        max_continuations: int = 2,
    ) -> str:
        """Re-prompt on ``finish_reason == "length"`` to get complete output.

        Returns the concatenated content after up to *max_continuations*
        follow-up generate calls.
        """
        content = result.get("content", "")
        finish_reason = result.get("finish_reason", "")

        for _ in range(max_continuations):
            if finish_reason != "length":
                break
            # Append what we have so far and ask the model to continue
            from openjarvis.core.types import Message, Role

            messages.append(Message(role=Role.ASSISTANT, content=content))
            messages.append(
                Message(
                    role=Role.USER,
                    content="Continue from where you left off.",
                ),
            )
            cont = self._generate(messages)
            continuation = cont.get("content", "")
            content += continuation
            finish_reason = cont.get("finish_reason", "")

        return content

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Remove ``<think>...</think>`` blocks from model output.

        Handles both ``<think>...</think>`` and the common distilled-model
        pattern where the opening ``<think>`` is absent and the response
        begins directly with reasoning text followed by ``</think>``.
        """
        # Full <think>...</think> blocks
        text = re.sub(
            r"<think>.*?</think>\s*",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        # Leading content before a bare </think> (no opening tag)
        text = re.sub(r"^.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE)
        return text.strip()

    @abstractmethod
    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the agent on *input* and return an ``AgentResult``."""


class ToolUsingAgent(BaseAgent):
    """Intermediate base for agents that accept and use tools.

    Sets ``accepts_tools = True`` for CLI/SDK introspection, and
    initialises a :class:`ToolExecutor` from the provided tools.
    """

    accepts_tools: bool = True

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List["BaseTool"]] = None,  # noqa: F821
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        loop_guard_config: Optional[Any] = None,
        capability_policy: Optional[Any] = None,
        agent_id: Optional[str] = None,
        interactive: bool = False,
        confirm_callback: Optional[Any] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        from openjarvis.tools._stubs import ToolExecutor

        self._tools = tools or []
        _aid = agent_id or getattr(self, "agent_id", "")
        self._executor = ToolExecutor(
            self._tools,
            bus=bus,
            capability_policy=capability_policy,
            agent_id=_aid,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )
        # Resolve max_turns: explicit arg > config > class default > 10
        if max_turns is not None:
            self._max_turns = max_turns
        else:
            try:
                cfg = load_config()
                self._max_turns = cfg.agent.max_turns
            except Exception:
                self._max_turns = getattr(self, "_default_max_turns", 10)

        # Loop guard
        self._loop_guard = None
        try:
            from openjarvis.agents.loop_guard import LoopGuard, LoopGuardConfig

            if loop_guard_config is None:
                loop_guard_config = LoopGuardConfig()
            elif isinstance(loop_guard_config, dict):
                loop_guard_config = LoopGuardConfig(**loop_guard_config)
            if loop_guard_config.enabled:
                self._loop_guard = LoopGuard(loop_guard_config, bus=bus)
        except ImportError:
            pass


__all__ = ["AgentContext", "AgentResult", "BaseAgent", "ToolUsingAgent"]
