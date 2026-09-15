"""TraceCollector — wraps any BaseAgent to record interaction traces."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any, Dict, List, Optional
from uuid import uuid4

from openjarvis.agents._stubs import (
    _RUN_WORKER_LEASE,
    AgentContext,
    AgentResult,
    AgentRunCompleted,
    AgentStreamEvent,
    AgentTextDelta,
    BaseAgent,
)
from openjarvis.core.events import RUN_ID, EventBus, EventType
from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.traces.store import TraceStore


class TraceCollector:
    """Wraps a ``BaseAgent`` and records a :class:`Trace` for every ``run()``.

    The collector subscribes to the ``EventBus`` to capture inference, tool,
    and memory events emitted during agent execution, converting them into
    ``TraceStep`` objects.  When the agent finishes, the complete ``Trace``
    is persisted to the ``TraceStore`` and published on the bus.

    Enhanced to capture full model response content, tool call arguments and
    results, and the complete conversation message history.

    Usage::

        agent = OrchestratorAgent(engine, model, tools=tools, bus=bus)
        collector = TraceCollector(agent, store=trace_store, bus=bus)
        result = collector.run("What is 2+2?")
        trace = collector.last_trace  # Rich trace with steps + messages
    """

    def __init__(
        self,
        agent: BaseAgent,
        *,
        store: Optional[TraceStore] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._agent = agent
        self._store = store
        self._bus = bus
        self._current_steps: list[TraceStep] = []
        self._current_model: str = ""
        self._current_engine: str = ""
        self._last_trace: Optional[Trace] = None
        self._trace_id = uuid4().hex
        self._state_lock = threading.RLock()
        self._terminal = False
        self._ttft: float | None = None
        self._first_text: float | None = None
        self._pending_inference: Any = None
        self._pending_tools: dict[str, Any] = {}
        self._async_writes = False
        self._queue_wait: float | None = None

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute with invocation-local collection state."""
        session = TraceCollector(self._agent, store=self._store, bus=self._bus)
        token, unsubs = session._begin(input, kwargs.get("model", ""))
        result = None
        status = "failed"
        try:
            result = self._agent.run(input, context=context, **kwargs)
            status = "completed"
            return result
        except (asyncio.CancelledError, GeneratorExit):
            status = "interrupted"
            raise
        finally:
            session._finish(input, result, status, token, unsubs)
            self._last_trace = session.last_trace

    async def run_stream(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        *,
        wait_for_admission: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Record admission and all terminal paths without sharing run state."""
        session = TraceCollector(self._agent, store=self._store, bus=self._bus)
        session._async_writes = True
        token, unsubs = session._begin(input, kwargs.get("model", ""))
        completed: AgentResult | None = None
        status = "failed"
        try:
            if self._store is not None and session._admission_write is None:
                raise RuntimeError("trace_admission_not_durable")
            if session._admission_write is not None:
                # Durable admission before execution, but never block the
                # event loop or cancel the writer with a barge-in task.
                await asyncio.shield(asyncio.wrap_future(session._admission_write))
            if wait_for_admission is not None:
                session._journal("runtime_acquire_requested", {})
                acquire_requested = time.monotonic()
                await wait_for_admission()
                session._queue_wait = time.monotonic() - acquire_requested
                session._journal(
                    "runtime_acquired",
                    {
                        "queue_wait_seconds": session._queue_wait,
                    },
                )
            stream = self._agent.run_stream(input, context=context, **kwargs)
            async with aclosing(stream):
                async for event in stream:
                    if isinstance(event, AgentRunCompleted):
                        completed = event.result
                    if (
                        isinstance(event, AgentTextDelta)
                        and session._first_text is None
                    ):
                        session._first_text = time.monotonic() - session._started_mono
                    yield event
            status = "completed" if completed is not None else "failed"
        except (asyncio.CancelledError, GeneratorExit):
            status = "interrupted"
            raise
        finally:
            session._finish(input, completed, status, token, unsubs)
            self._last_trace = session.last_trace

    def _begin(self, input: str, model: str):
        self._started_at = time.time()
        self._started_mono = time.monotonic()
        self._current_model = model
        token = RUN_ID.set(self._trace_id)
        self._admission_write = self._journal(
            "run_admitted",
            {"query": input, "model": model},
        )
        return token, self._subscribe()

    def _journal(self, event_type: str, data: dict, **timing: Any) -> Any:
        if self._store is not None:
            try:
                timing.setdefault("timestamp", time.time())
                timing.setdefault("monotonic_timestamp", time.monotonic())
                if self._async_writes:
                    return self._store.submit_write(
                        self._store.append_run_event,
                        self._trace_id,
                        event_type,
                        dict(data),
                        **timing,
                    )
                self._store.append_run_event(self._trace_id, event_type, data, **timing)
            except Exception:
                logging.getLogger(__name__).exception(
                    "run journal write failed: run_id=%s event=%s",
                    self._trace_id,
                    event_type,
                )

    def _finish(self, input, result, status, token, unsubs) -> None:
        try:
            with self._state_lock:
                self._terminal = True
                if self._pending_inference is not None:
                    event = self._pending_inference
                    self._current_steps.append(
                        TraceStep(
                            step_type=StepType.GENERATE,
                            timestamp=event.timestamp,
                            duration_seconds=max(
                                0.0, time.monotonic() - event.monotonic_timestamp
                            ),
                            input={"model": self._current_model},
                            metadata={"status": status, "ttft": None},
                        )
                    )
                for event in self._pending_tools.values():
                    self._current_steps.append(
                        TraceStep(
                            step_type=StepType.TOOL_CALL,
                            timestamp=event.timestamp,
                            duration_seconds=max(
                                0.0, time.monotonic() - event.monotonic_timestamp
                            ),
                            input={
                                "tool": event.data.get("tool"),
                                "arguments": event.data.get("arguments", {}),
                            },
                            metadata={
                                "status": "outcome_pending",
                                "invocation_id": event.data.get("invocation_id"),
                            },
                        )
                    )
                self._journal(f"run_{status}", {"status": status})
                self._record_completed(
                    input,
                    result or AgentResult(content=""),
                    self._started_at,
                    time.time(),
                    status=status,
                )
            lease = _RUN_WORKER_LEASE.get()
            if lease is not None and lease.has_pending_workers:

                def settled():
                    self._journal("worker_settled", {})
                    self._unsubscribe(unsubs)

                lease.when_settled(settled)
            else:
                self._unsubscribe(unsubs)
        finally:
            try:
                RUN_ID.reset(token)
            except ValueError:
                # A consumer may close a suspended iterator in another Task.
                pass

    def _record_completed(
        self,
        input: str,
        result: AgentResult,
        started_at: float,
        ended_at: float,
        *,
        status: str = "completed",
    ) -> None:
        """Build, persist, and publish the trace for one completed result."""

        # Add final respond step
        if status == "completed":
            self._current_steps.append(
                TraceStep(
                    step_type=StepType.RESPOND,
                    timestamp=ended_at,
                    duration_seconds=0.0,
                    output={"content": result.content, "turns": result.turns},
                )
            )

        # Extract messages from agent result metadata
        messages: List[Dict[str, Any]] = result.metadata.get("messages", [])

        # Build and persist the trace
        trace = Trace(
            trace_id=self._trace_id,
            query=input,
            agent=getattr(self._agent, "agent_id", "unknown"),
            model=self._current_model,
            engine=self._current_engine,
            steps=list(self._current_steps),
            result=result.content if status == "completed" else "",
            messages=messages,
            started_at=started_at,
            ended_at=ended_at,
            metadata={
                "status": status,
                "ttft_seconds": self._ttft,
                "first_text_seconds": self._first_text,
                "queue_wait_seconds": self._queue_wait,
            },
        )
        # Nested/parallel spans cannot be summed into wall-clock latency.
        trace.total_latency_seconds = max(0.0, time.monotonic() - self._started_mono)
        for step in trace.steps:
            trace.total_tokens += step.output.get("tokens", 0)

        self._last_trace = trace

        if self._store is not None:
            # The agent has already produced `result` above -- a trace-store
            # failure (e.g. a still-unserializable field) must not turn a
            # completed answer into a 500 from the caller. Log loudly rather
            # than swallowing it; see traces/store.py's _json_default for
            # the fix to the actual bytes-in-output cause.
            try:
                if self._async_writes:
                    self._store.submit_write(self._store.save, trace)
                else:
                    self._store.save(trace)
            except Exception:
                logging.getLogger("openjarvis.traces").exception(
                    "trace persistence failed for trace_id=%s; continuing without it",
                    trace.trace_id,
                )

        if self._bus is not None and status == "completed":
            self._bus.publish(EventType.TRACE_COMPLETE, {"trace": trace})

    @property
    def last_trace(self) -> Optional[Trace]:
        """Return the trace from the most recent ``run()``."""
        return self._last_trace

    # -- event handlers --------------------------------------------------------

    def _subscribe(self) -> list[tuple]:
        if self._bus is None:
            return []
        handlers = [
            (EventType.INFERENCE_START, self._on_inference_start),
            (EventType.INFERENCE_END, self._on_inference_end),
            (EventType.TOOL_CALL_START, self._on_tool_start),
            (EventType.TOOL_CALL_END, self._on_tool_end),
            (EventType.MEMORY_RETRIEVE, self._on_memory_retrieve),
        ]
        subscriptions = []
        for evt_type, handler in handlers:

            def scoped(event, handler=handler):
                if event.run_id != self._trace_id:
                    return
                with self._state_lock:
                    self._journal(
                        event.event_type.value,
                        event.data,
                        timestamp=event.timestamp,
                        monotonic_timestamp=event.monotonic_timestamp,
                    )
                    if not self._terminal:
                        handler(event)

            self._bus.subscribe(evt_type, scoped)
            subscriptions.append((evt_type, scoped))
        return subscriptions

    def _unsubscribe(self, handlers: list[tuple]) -> None:
        if self._bus is None:
            return
        for evt_type, handler in handlers:
            self._bus.unsubscribe(evt_type, handler)

    def _on_inference_start(self, event: Any) -> None:
        self._pending_inference = event
        self._current_model = event.data.get("model", self._current_model)
        self._current_engine = event.data.get("engine", self._current_engine)
        self._inference_start_time = event.timestamp

    def _on_inference_end(self, event: Any) -> None:
        self._pending_inference = None
        start = getattr(self, "_inference_start_time", event.timestamp)
        data = event.data
        usage = data.get("usage", {})
        if self._ttft is None:
            self._ttft = data.get("ttft")
        self._current_steps.append(
            TraceStep(
                step_type=StepType.GENERATE,
                timestamp=start,
                duration_seconds=event.timestamp - start,
                input={"model": self._current_model},
                output={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "tokens": usage.get(
                        "total_tokens",
                        data.get("total_tokens", 0),
                    ),
                    "content": data.get("content", ""),
                    "tool_calls": data.get("tool_calls", []),
                    "tool_results": data.get("tool_results", []),
                    "content_blocks": data.get("content_blocks", []),
                    "finish_reason": data.get("finish_reason", ""),
                },
                metadata={
                    "engine": self._current_engine,
                    "ttft": data.get("ttft", 0.0),
                    "energy_joules": data.get("energy_joules", 0.0),
                    "power_watts": data.get("power_watts", 0.0),
                    "gpu_utilization_pct": data.get(
                        "gpu_utilization_pct",
                        0.0,
                    ),
                    "throughput_tok_per_sec": data.get(
                        "throughput_tok_per_sec",
                        0.0,
                    ),
                },
            )
        )

    def _on_tool_start(self, event: Any) -> None:
        self._tool_start_time = event.timestamp
        self._tool_start_data = event.data
        self._pending_tools[
            event.data.get("invocation_id", event.data.get("tool", ""))
        ] = event

    def _on_tool_end(self, event: Any) -> None:
        start = getattr(self, "_tool_start_time", event.timestamp)
        start_data = getattr(self, "_tool_start_data", {})
        pending = self._pending_tools.pop(
            event.data.get("invocation_id", event.data.get("tool", "")),
            None,
        )
        if pending is not None:
            start, start_data = pending.timestamp, pending.data
        # Pull through any metadata the tool attached to its ToolResult
        # (e.g. SkillTool's skill/skill_source/skill_kind tags) so the
        # SkillOptimizer can bucket traces by skill name.
        result_metadata = event.data.get("metadata") or {}
        arguments = result_metadata.get("arguments")
        if not isinstance(arguments, dict):
            arguments = start_data.get("arguments", {})
        self._current_steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=start,
                duration_seconds=event.data.get(
                    "latency",
                    event.timestamp - start,
                ),
                input={
                    "tool": event.data.get("tool", ""),
                    "arguments": arguments,
                },
                output={
                    "success": event.data.get("success", False),
                    "result": event.data.get("result", ""),
                },
                metadata=dict(result_metadata),
            )
        )

    def _on_memory_retrieve(self, event: Any) -> None:
        self._current_steps.append(
            TraceStep(
                step_type=StepType.RETRIEVE,
                timestamp=event.timestamp,
                duration_seconds=event.data.get("latency", 0.0),
                input={"query": event.data.get("query", "")},
                output={
                    "num_results": event.data.get("num_results", 0),
                },
            )
        )


def record_response_trace(
    store: Optional[TraceStore],
    *,
    query: str,
    result: str,
    model: str = "",
    engine: str = "",
    agent: str = "server",
    started_at: float,
    ended_at: float,
) -> Optional[Trace]:
    """Persist a minimal single-step ``Trace`` for a non-agent response.

    The streaming SSE and WebSocket chat paths stream straight from the
    engine, bypassing the agent (and therefore ``TraceCollector``). They call
    this so those interactions still land in ``traces.db`` — otherwise streamed
    chats, which are the desktop GUI's main path, would never produce traces.

    Best-effort: returns the saved ``Trace`` or ``None`` (when *store* is
    ``None`` or persistence raised), and never propagates an exception into the
    caller's response path.
    """
    if store is None:
        return None
    try:
        duration = max(0.0, ended_at - started_at)
        trace = Trace(
            query=query,
            agent=agent,
            model=model,
            engine=engine,
            result=result,
            started_at=started_at,
            ended_at=ended_at,
            steps=[
                TraceStep(
                    step_type=StepType.RESPOND,
                    timestamp=ended_at,
                    duration_seconds=duration,
                    output={"content": result},
                )
            ],
        )
        trace.total_latency_seconds = duration
        store.save(trace)
        return trace
    except Exception:
        import logging

        logging.getLogger("openjarvis.traces").debug(
            "record_response_trace failed", exc_info=True
        )
        return None


__all__ = ["TraceCollector", "record_response_trace"]
