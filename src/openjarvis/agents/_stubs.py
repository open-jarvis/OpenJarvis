"""ABC for agent implementations.

Adapted from IPW's ``BaseAgent`` at ``src/agents/base.py``.
Provides ``BaseAgent`` with concrete helper methods for event emission,
message building, and generation, plus ``ToolUsingAgent`` intermediate
base for agents that accept tools.
"""

from __future__ import annotations

import asyncio
import re
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Conversation, Message, Role, ToolResult
from openjarvis.engine._stubs import InferenceEngine

_RUN_MODEL: ContextVar[str | None] = ContextVar("openjarvis_run_model", default=None)
_RUN_WORKER_LEASE: ContextVar[AgentWorkerLease | None]


def _noop() -> None:
    """No-op unregister for callbacks that were never retained."""


def _invoke_quietly(callback: Callable[[], None]) -> None:
    """Run a cancellation callback without letting it break lease settlement."""
    try:
        callback()
    except Exception:  # noqa: BLE001 — best-effort cooperative cancellation
        pass


class AgentWorkerLease:
    """Retain caller ownership until every task-local sync worker settles."""

    def __init__(self) -> None:
        self._pending: set[asyncio.Task[Any]] = set()
        self._settled_callbacks: list[Callable[[], None]] = []
        # Registration happens on the ``to_thread`` worker, signaling on the
        # event-loop thread, so this state needs a real lock.
        self._cancel_lock = threading.Lock()
        self._cancel_callbacks: list[Callable[[], None]] = []
        self._cancelled = False

    @property
    def has_pending_workers(self) -> bool:
        """Return whether a sync child is still running outside the event loop."""
        return bool(self._pending)

    async def run_sync(self, function: Callable[..., Any], /, *args: Any) -> Any:
        """Run one sync child while keeping its completion attached to this lease."""
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._pending.add(task)
        task.add_done_callback(self._worker_settled)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # The caller walked away. Tell the retained worker so it can drop
            # its own blocking child (an in-flight MCP request); the worker
            # itself stays retained until it actually settles.
            self._signal_cancelled()
            raise

    def register_cancellation(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register ``callback`` for caller cancellation; return an unregister."""
        with self._cancel_lock:
            if not self._cancelled:
                self._cancel_callbacks.append(callback)

                def unregister() -> None:
                    with self._cancel_lock:
                        if callback in self._cancel_callbacks:
                            self._cancel_callbacks.remove(callback)

                return unregister
        # Already cancelled while this worker was starting up — fire now.
        _invoke_quietly(callback)
        return _noop

    def _signal_cancelled(self) -> None:
        with self._cancel_lock:
            if self._cancelled:
                return
            self._cancelled = True
            callbacks, self._cancel_callbacks = self._cancel_callbacks, []
        for callback in callbacks:
            _invoke_quietly(callback)

    def when_settled(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` now or after the final retained worker exits."""
        if not self._pending:
            callback()
            return
        self._settled_callbacks.append(callback)

    def _worker_settled(self, task: asyncio.Task[Any]) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()
        if self._pending:
            return
        callbacks = self._settled_callbacks
        self._settled_callbacks = []
        for callback in callbacks:
            callback()


_RUN_WORKER_LEASE = ContextVar("openjarvis_run_worker_lease", default=None)


async def run_agent_sync_worker(
    function: Callable[..., Any], /, *args: Any
) -> Any:
    """Run sync Agent work under the active runtime lease when one exists."""
    lease = _RUN_WORKER_LEASE.get()
    if lease is None:
        return await asyncio.to_thread(function, *args)
    return await lease.run_sync(function, *args)


def register_agent_worker_cancellation(
    callback: Callable[[], None],
) -> Callable[[], None]:
    """Register for active lease cancellation; return an unregister callback.

    Sync Agent work that blocks on a cancellable child (an in-flight MCP
    ``tools/call``) uses this so a walked-away caller drops that child instead
    of waiting out its full timeout. Outside a runtime lease this is a no-op.
    """
    lease = _RUN_WORKER_LEASE.get()
    if lease is None:
        return _noop
    return lease.register_cancellation(callback)


class AgentPersistenceStaging:
    """Hold answer-derived writes until the caller confirms the turn landed."""

    def __init__(self) -> None:
        self._staged: list[Callable[[], None]] = []

    @property
    def has_staged_writes(self) -> bool:
        """Return whether any answer-derived write is still uncommitted."""
        return bool(self._staged)

    def stage(self, write: Callable[[], None]) -> None:
        """Retain ``write`` until :meth:`commit` or :meth:`discard` decides it."""
        self._staged.append(write)

    def commit(self) -> None:
        """Apply every retained write in the order it was staged."""
        staged, self._staged = self._staged, []
        for write in staged:
            write()

    def discard(self) -> None:
        """Drop every retained write, leaving the durable stores untouched."""
        self._staged = []


_RUN_PERSISTENCE: ContextVar[AgentPersistenceStaging | None] = ContextVar(
    "openjarvis_run_persistence", default=None
)


def stage_agent_persistence(write: Callable[[], None]) -> None:
    """Defer an answer-derived write when the active run stages persistence.

    Runs ``write`` immediately outside a staged run, so Agents used without
    :class:`~openjarvis.agents.runtime.NativeAgentRuntime` keep persisting
    exactly as before.
    """
    staging = _RUN_PERSISTENCE.get()
    if staging is None:
        write()
        return
    staging.stage(write)


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


@dataclass(frozen=True)
class AgentTextDelta:
    """A text delta emitted while an agent run is streaming."""

    content: str


@dataclass(frozen=True)
class AgentRunCompleted:
    """The terminal event emitted after an agent run completes."""

    result: AgentResult


@dataclass(frozen=True)
class AgentToolStarted:
    """Emitted just before a tool call is executed during a streaming run."""

    tool_name: str


@dataclass(frozen=True)
class AgentToolFinished:
    """Emitted after a tool call returns, successful or not."""

    tool_name: str
    ok: bool


AgentStreamEvent = (
    AgentTextDelta | AgentRunCompleted | AgentToolStarted | AgentToolFinished
)


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
    # Plain conversational agents may opt into the managed runtime's generic
    # function-calling loop.  Specialized agents keep their own execution
    # class even when process-wide MCP tools are available.
    supports_managed_tool_fallback: bool = False

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

    def _apply_persona(self, system_prompt: Optional[str]) -> Optional[str]:
        """Append SOUL/MEMORY/USER persona to a self-assembled system prompt.

        Agents like ``monitor_operative`` / ``operative`` build their own
        system prompt and bypass ``_build_messages`` (and thus the prompt
        builder). This lets them honor the same persona files as one-shot
        ``jarvis ask`` (#376) by *appending* persona to — never replacing —
        their specialized instructions. No-op when no ``prompt_builder`` is
        wired or no persona files exist.
        """
        if self._prompt_builder is None:
            return system_prompt
        persona = self._prompt_builder.persona_sections()
        if not persona:
            return system_prompt
        return f"{system_prompt}\n\n{persona}" if system_prompt else persona

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
        context_messages = (
            list(context.conversation.messages) if context is not None else []
        )
        # Check if the context already supplies a system message
        _context_has_system = (
            context
            and context.conversation.messages
            and any(m.role == Role.SYSTEM for m in context.conversation.messages)
        )

        if self._prompt_builder is not None:
            effective_system_prompt = self._prompt_builder.build()
        elif system_prompt:
            effective_system_prompt = system_prompt
        elif _context_has_system:
            effective_system_prompt = None
        else:
            # Fall back to the config-level default (grounds local models)
            try:
                cfg = load_config()
                effective_system_prompt = cfg.agent.default_system_prompt or None
            except Exception:
                effective_system_prompt = None
        if effective_system_prompt:
            context_system_text = "\n\n".join(
                message.text
                for message in context_messages
                if message.role == Role.SYSTEM
                and message.metadata.get("memory_context")
                and message.text
            )
            if context_system_text:
                effective_system_prompt = (
                    f"{effective_system_prompt}\n\n{context_system_text}"
                )
                context_messages = [
                    message
                    for message in context_messages
                    if not (
                        message.role == Role.SYSTEM
                        and message.metadata.get("memory_context")
                    )
                ]
            messages.append(Message(role=Role.SYSTEM, content=effective_system_prompt))
        if context_messages:
            messages.extend(context_messages)
        messages.append(Message(role=Role.USER, content=input))
        return messages

    def _effective_model(self) -> str:
        return _RUN_MODEL.get() or self._model

    def _generate(self, messages: list[Message], **extra_kwargs: Any) -> dict:
        """Call ``engine.generate()`` with stored defaults.

        Extra kwargs (e.g. ``tools``) are forwarded to the engine.
        Publishes INFERENCE_START/END events on the bus when the engine
        does not publish its own (i.e. non-instrumented engines).
        """
        model = self._effective_model()
        if self._bus and not getattr(self._engine, "_publishes_events", False):
            engine_id = getattr(self._engine, "engine_id", "")
            self._bus.publish(
                EventType.INFERENCE_START,
                {"model": model, "engine": engine_id},
            )

        max_tokens = extra_kwargs.pop("max_tokens", self._max_tokens)
        result = self._engine.generate(
            messages,
            model=model,
            temperature=self._temperature,
            max_tokens=max_tokens,
            **extra_kwargs,
        )

        if self._bus and not getattr(self._engine, "_publishes_events", False):
            usage = result.get("usage", {})
            self._bus.publish(
                EventType.INFERENCE_END,
                {
                    "model": model,
                    "usage": usage,
                    "content": result.get("content", ""),
                    "tool_calls": result.get("tool_calls", []),
                    "finish_reason": result.get("finish_reason", ""),
                },
            )

        return result

    def _run_with_model(
        self,
        input: str,
        context: AgentContext | None,
        model: str | None,
        kwargs: dict[str, Any],
    ) -> AgentResult:
        token = _RUN_MODEL.set(model or None)
        try:
            return self.run(input, context, **kwargs)
        finally:
            _RUN_MODEL.reset(token)

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

    async def run_stream(
        self, input: str, context: AgentContext | None = None, **kwargs: Any
    ) -> AsyncIterator[AgentStreamEvent]:
        """Stream the completed run through the compatibility event contract."""
        model = kwargs.pop("model", None)
        result = await run_agent_sync_worker(
            self._run_with_model,
            input,
            context,
            model,
            kwargs,
        )
        if not bool(result.metadata.get("pending_approval")) and result.content.strip():
            yield AgentTextDelta(result.content.strip())
        yield AgentRunCompleted(result)


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
        skill_few_shot_examples: Optional[List[str]] = None,
        prompt_builder: Optional[Any] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_builder=prompt_builder,
        )
        from openjarvis.tools._stubs import ToolExecutor

        self._tools = tools or []
        # Plan 2B I3: store optimized few-shot examples for agents to inject
        # into their own system prompt templates as appropriate.
        self._skill_few_shot_examples = list(skill_few_shot_examples or [])
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

        # LoopGuard configuration belongs to the shared Agent; mutable call
        # counters belong to one top-level run and are created on demand.
        self._loop_guard_config = None
        try:
            from openjarvis.agents.loop_guard import LoopGuardConfig

            if loop_guard_config is None:
                loop_guard_config = LoopGuardConfig()
            elif isinstance(loop_guard_config, dict):
                loop_guard_config = LoopGuardConfig(**loop_guard_config)
            if loop_guard_config.enabled:
                self._loop_guard_config = loop_guard_config
        except ImportError:
            pass

    def _new_loop_guard(self) -> Any | None:
        """Create independent mutable guard state for one top-level run."""
        if self._loop_guard_config is None:
            return None
        from openjarvis.agents.loop_guard import LoopGuard

        return LoopGuard(self._loop_guard_config, bus=self._bus)

    def _tool_is_polling(self, tool_name: str) -> bool:
        """Return the explicit polling classification for one configured tool."""
        return any(
            tool.spec.name == tool_name
            and bool(tool.spec.metadata.get("polling", False))
            for tool in self._tools
        )


__all__ = [
    "AgentContext",
    "AgentResult",
    "AgentTextDelta",
    "AgentRunCompleted",
    "AgentStreamEvent",
    "AgentToolFinished",
    "AgentToolStarted",
    "BaseAgent",
    "ToolUsingAgent",
    "register_agent_worker_cancellation",
    "run_agent_sync_worker",
]
