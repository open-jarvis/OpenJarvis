"""Tests for the TraceCollector."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import StepType
from openjarvis.traces.collector import TraceCollector
from openjarvis.traces.store import TraceStore


class _FakeAgent(BaseAgent):
    """Minimal agent that returns a fixed response."""

    agent_id = "fake"

    def __init__(
        self,
        response: str = "test response",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._response = response
        self._bus = bus

    def run(
        self, input: str, context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        # Simulate an inference step via event bus
        if self._bus:
            self._bus.publish(EventType.INFERENCE_START, {
                "model": "qwen3:8b",
                "engine": "ollama",
            })
            self._bus.publish(EventType.INFERENCE_END, {
                "total_tokens": 50,
            })
        return AgentResult(content=self._response, turns=1)


class _ToolAgent(BaseAgent):
    """Agent that simulates a tool call during execution."""

    agent_id = "tool_agent"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def run(
        self, input: str, context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        # Simulate inference + tool call + inference
        inf = {"model": "qwen3:8b", "engine": "ollama"}
        self._bus.publish(EventType.INFERENCE_START, inf)
        self._bus.publish(EventType.INFERENCE_END, {"total_tokens": 30})
        self._bus.publish(EventType.TOOL_CALL_START, {
            "tool": "calculator", "arguments": {"expr": "2+2"},
        })
        self._bus.publish(EventType.TOOL_CALL_END, {
            "tool": "calculator", "success": True, "latency": 0.01,
        })
        self._bus.publish(EventType.INFERENCE_START, inf)
        self._bus.publish(EventType.INFERENCE_END, {"total_tokens": 20})
        return AgentResult(content="4", turns=2)


class TestTraceCollector:
    def test_basic_collection(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="hello", bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        result = collector.run("say hello")

        assert result.content == "hello"
        assert store.count() == 1

        traces = store.list_traces()
        trace = traces[0]
        assert trace.query == "say hello"
        assert trace.agent == "fake"
        assert trace.model == "qwen3:8b"
        assert trace.engine == "ollama"
        assert trace.result == "hello"
        store.close()

    def test_records_generate_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace = store.list_traces()[0]
        generate_steps = [s for s in trace.steps if s.step_type == StepType.GENERATE]
        assert len(generate_steps) == 1
        assert generate_steps[0].output.get("tokens") == 50
        store.close()

    def test_records_tool_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _ToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        tool_steps = [s for s in trace.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) == 1
        assert tool_steps[0].input["tool"] == "calculator"
        assert tool_steps[0].output["success"] is True
        store.close()

    def test_records_respond_step(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="final answer", bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace = store.list_traces()[0]
        respond_steps = [s for s in trace.steps if s.step_type == StepType.RESPOND]
        assert len(respond_steps) == 1
        assert respond_steps[0].output["content"] == "final answer"
        store.close()

    def test_records_memory_retrieve(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        # Monkey-patch agent to emit memory event
        original_run = agent.run

        def run_with_memory(input, context=None, **kwargs):
            bus.publish(EventType.MEMORY_RETRIEVE, {
                "query": "meeting notes",
                "num_results": 3,
                "latency": 0.2,
            })
            return original_run(input, context=context, **kwargs)

        agent.run = run_with_memory
        collector.run("find my meeting notes")

        trace = store.list_traces()[0]
        retrieve_steps = [s for s in trace.steps if s.step_type == StepType.RETRIEVE]
        assert len(retrieve_steps) == 1
        assert retrieve_steps[0].input["query"] == "meeting notes"
        store.close()

    def test_publishes_trace_complete(self, tmp_path: Path) -> None:
        bus = EventBus(record_history=True)
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("test")

        trace_events = [
            e for e in bus.history
            if e.event_type == EventType.TRACE_COMPLETE
        ]
        assert len(trace_events) == 1
        assert trace_events[0].data["trace"].query == "test"
        store.close()

    def test_no_store(self) -> None:
        """Collector works without a store (just collects, doesn't persist)."""
        bus = EventBus()
        agent = _FakeAgent(response="ok", bus=bus)
        collector = TraceCollector(agent, bus=bus)  # no store

        result = collector.run("test")
        assert result.content == "ok"

    def test_no_bus(self, tmp_path: Path) -> None:
        """Collector works without a bus (no event-based step collection)."""
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(response="ok")
        collector = TraceCollector(agent, store=store)  # no bus

        result = collector.run("test")
        assert result.content == "ok"
        assert store.count() == 1
        # Only the RESPOND step (no events to capture)
        trace = store.list_traces()[0]
        assert len(trace.steps) == 1
        assert trace.steps[0].step_type == StepType.RESPOND
        store.close()

    def test_timing(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        before = time.time()
        collector.run("test")
        after = time.time()

        trace = store.list_traces()[0]
        assert trace.started_at >= before
        assert trace.ended_at <= after
        assert trace.ended_at >= trace.started_at
        store.close()

    def test_unsubscribes_after_run(self, tmp_path: Path) -> None:
        """Events after run() completes should NOT affect the next trace."""
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _FakeAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("first")

        # Emit events after run — should not affect stored trace
        bus.publish(EventType.INFERENCE_START, {"model": "stray"})
        bus.publish(EventType.INFERENCE_END, {"total_tokens": 999})

        assert store.count() == 1
        trace = store.list_traces()[0]
        # No step with model="stray"
        for s in trace.steps:
            assert s.input.get("model") != "stray"
        store.close()


class _RichToolAgent(BaseAgent):
    """Agent that emits content-enriched events for testing."""

    agent_id = "rich_tool_agent"

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def run(
        self, input: str, context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        from openjarvis.core.types import ToolResult

        # Turn 1: inference with tool call request
        self._bus.publish(EventType.INFERENCE_START, {
            "model": "test-model", "engine": "test",
        })
        self._bus.publish(EventType.INFERENCE_END, {
            "total_tokens": 30,
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "content": "I'll calculate that for you.",
            "tool_calls": [
                {"id": "call_1", "name": "calculator",
                 "arguments": "{\"expr\": \"2+2\"}"},
            ],
            "finish_reason": "tool_calls",
        })
        # Tool execution
        self._bus.publish(EventType.TOOL_CALL_START, {
            "tool": "calculator", "arguments": {"expr": "2+2"},
        })
        self._bus.publish(EventType.TOOL_CALL_END, {
            "tool": "calculator", "success": True, "latency": 0.01,
            "result": "4",
        })
        # Turn 2: final answer
        self._bus.publish(EventType.INFERENCE_START, {
            "model": "test-model", "engine": "test",
        })
        self._bus.publish(EventType.INFERENCE_END, {
            "total_tokens": 15,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "content": "The answer is 4.",
            "tool_calls": [],
            "finish_reason": "stop",
        })

        # Return result with messages in metadata
        messages = [
            {"role": "user", "content": input},
            {"role": "assistant", "content": "I'll calculate that for you."},
            {"role": "tool", "content": "4", "name": "calculator"},
            {"role": "assistant", "content": "The answer is 4."},
        ]
        return AgentResult(
            content="The answer is 4.",
            tool_results=[
                ToolResult(tool_name="calculator", content="4",
                           success=True),
            ],
            turns=2,
            metadata={"messages": messages},
        )


class TestRichTraceCollector:
    def test_captures_content_in_generate_steps(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        gen_steps = [s for s in trace.steps if s.step_type == StepType.GENERATE]
        assert len(gen_steps) == 2
        assert gen_steps[0].output["content"] == "I'll calculate that for you."
        expected_tc = [
            {"id": "call_1", "name": "calculator",
             "arguments": "{\"expr\": \"2+2\"}"},
        ]
        assert gen_steps[0].output["tool_calls"] == expected_tc
        assert gen_steps[0].output["finish_reason"] == "tool_calls"
        assert gen_steps[1].output["content"] == "The answer is 4."
        assert gen_steps[1].output["finish_reason"] == "stop"
        store.close()

    def test_captures_tool_arguments_and_result(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        tool_steps = [s for s in trace.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) == 1
        assert tool_steps[0].input["tool"] == "calculator"
        assert tool_steps[0].input["arguments"] == {"expr": "2+2"}
        assert tool_steps[0].output["result"] == "4"
        assert tool_steps[0].output["success"] is True
        store.close()

    def test_captures_messages_in_trace(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = store.list_traces()[0]
        assert len(trace.messages) == 4
        assert trace.messages[0]["role"] == "user"
        assert trace.messages[3]["role"] == "assistant"
        store.close()

    def test_last_trace_property(self, tmp_path: Path) -> None:
        bus = EventBus()
        store = TraceStore(tmp_path / "test.db")
        agent = _RichToolAgent(bus=bus)
        collector = TraceCollector(agent, store=store, bus=bus)

        collector.run("What is 2+2?")

        trace = collector.last_trace
        assert trace is not None
        assert trace.query == "What is 2+2?"
        assert len(trace.messages) == 4
        store.close()
