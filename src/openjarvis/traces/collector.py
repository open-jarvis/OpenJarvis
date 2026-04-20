"""TraceCollector — wraps any BaseAgent to record interaction traces."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus, EventType
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

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute the wrapped agent and record a trace."""
        self._current_steps = []
        self._current_model = ""
        self._current_engine = ""

        # Subscribe to events for trace collection
        unsubs = self._subscribe()

        started_at = time.time()
        try:
            result = self._agent.run(input, context=context, **kwargs)
        finally:
            self._unsubscribe(unsubs)

        ended_at = time.time()

        # Add final respond step
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
            query=input,
            agent=getattr(self._agent, "agent_id", "unknown"),
            model=self._current_model,
            engine=self._current_engine,
            steps=list(self._current_steps),
            result=result.content,
            messages=messages,
            started_at=started_at,
            ended_at=ended_at,
        )
        # Recompute totals from steps
        for step in trace.steps:
            trace.total_latency_seconds += step.duration_seconds
            trace.total_tokens += step.output.get("tokens", 0)

        self._last_trace = trace

        if self._store is not None:
            self._store.save(trace)

        if self._bus is not None:
            self._bus.publish(EventType.TRACE_COMPLETE, {"trace": trace})

        return result

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
        for evt_type, handler in handlers:
            self._bus.subscribe(evt_type, handler)
        return handlers

    def _unsubscribe(self, handlers: list[tuple]) -> None:
        if self._bus is None:
            return
        for evt_type, handler in handlers:
            self._bus.unsubscribe(evt_type, handler)

    def _on_inference_start(self, event: Any) -> None:
        self._current_model = event.data.get("model", self._current_model)
        self._current_engine = event.data.get("engine", self._current_engine)
        self._inference_start_time = event.timestamp

    def _on_inference_end(self, event: Any) -> None:
        start = getattr(self, "_inference_start_time", event.timestamp)
        data = event.data
        usage = data.get("usage", {})
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
                        "total_tokens", data.get("total_tokens", 0),
                    ),
                    "content": data.get("content", ""),
                    "tool_calls": data.get("tool_calls", []),
                    "finish_reason": data.get("finish_reason", ""),
                },
                metadata={
                    "engine": self._current_engine,
                    "ttft": data.get("ttft", 0.0),
                    "energy_joules": data.get("energy_joules", 0.0),
                    "power_watts": data.get("power_watts", 0.0),
                    "gpu_utilization_pct": data.get(
                        "gpu_utilization_pct", 0.0,
                    ),
                    "throughput_tok_per_sec": data.get(
                        "throughput_tok_per_sec", 0.0,
                    ),
                },
            )
        )

    def _on_tool_start(self, event: Any) -> None:
        self._tool_start_time = event.timestamp
        self._tool_start_data = event.data

    def _on_tool_end(self, event: Any) -> None:
        start = getattr(self, "_tool_start_time", event.timestamp)
        start_data = getattr(self, "_tool_start_data", {})
        # Pull through any metadata the tool attached to its ToolResult
        # (e.g. SkillTool's skill/skill_source/skill_kind tags) so the
        # SkillOptimizer can bucket traces by skill name.
        result_metadata = event.data.get("metadata") or {}
        self._current_steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=start,
                duration_seconds=event.data.get(
                    "latency", event.timestamp - start,
                ),
                input={
                    "tool": event.data.get("tool", ""),
                    "arguments": start_data.get("arguments", {}),
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


__all__ = ["TraceCollector"]
